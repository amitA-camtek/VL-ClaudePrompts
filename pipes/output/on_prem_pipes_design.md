# VL-Camtek — On-Prem Pipeline Execution Design (No Kubernetes)

**Author role:** Senior software architect, Python distributed systems & on-prem infrastructure
**Date:** 2026-04-15
**Source analysis:** [pipeAnalysis.md](../pipeAnalysis.md)
**Target audience:** Engineering leads, platform engineers, ops, stakeholders
**Goal:** Replace the current Argo-on-Kubernetes orchestration with a simple, robust, on-prem-friendly stack while preserving the Python pipeline codebase untouched.

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Current System Recap](#2-current-system-recap)
3. [Per-Pipe Execution Strategies](#3-per-pipe-execution-strategies)
    - 3.1 [Strategy Catalog](#31-strategy-catalog-approaches-evaluated)
    - 3.2 [Per-Pipe Analysis Matrix](#32-per-pipe-analysis-matrix)
    - 3.3 [Selected Approach and Justification](#33-selected-approach-and-justification)
4. [System Architecture (HLD)](#4-system-architecture-hld)
    - 4.1 [Component Inventory](#41-component-inventory)
    - 4.2 [Block Diagram](#42-block-diagram)
    - 4.3 [End-to-End Flow Diagram (Create Dataset)](#43-end-to-end-flow-diagram-create-dataset)
    - 4.4 [Sequence Diagram — Task Submit to Pipe Execute](#44-sequence-diagram--task-submit-to-pipe-execute)
    - 4.5 [Deployment Model](#45-deployment-model)
    - 4.6 [Storage Layout](#46-storage-layout)
    - 4.7 [Queue Topology](#47-queue-topology)
5. [Migration Plan](#5-migration-plan)
6. [Operational Design](#6-operational-design)
7. [Constraints, Risks, and Tradeoffs](#7-constraints-risks-and-tradeoffs)
8. [Appendix A — systemd Unit Examples](#appendix-a--systemd-unit-examples)
9. [Appendix B — Docker Compose Stack](#appendix-b--docker-compose-stack)
10. [Appendix C — Config/Env Mapping (K8s to On-Prem)](#appendix-c--configenv-mapping-k8s-to-on-prem)

---

## 1. Executive Summary

The existing vl-camtek system orchestrates 11 pipeline flows (pipes) via **Argo Workflows on Kubernetes**. Each pipe is already a plain decorator-composed Python function invoked by `python -m pipeline.controller.controller --flow-to-run X` with env vars for the dataset/run context. Kubernetes only contributes: pod scheduling, per-run resource sizing, CPU/GPU node affinity, PVC mounts, exit handlers.

**Core insight:** The business logic does not need to change. Only the *execution layer* does.

**Recommended stack:**

- **Dramatiq** as the task-dispatch layer (Python-native, simpler than Celery, robust result handling)
- **RabbitMQ** as the broker (durable, battle-tested on-prem, supports priorities + dead-letter exchanges)
- **PostgreSQL** (existing) remains the durable state-of-record (tasks table, queue durability audit)
- **systemd** on three dedicated VM roles (api, cpu-worker, gpu-worker) for process supervision
- **NFS** (or Ceph/GlusterFS) to replace `RWMany` PVCs — shared `/data`, `/models`, `/snapshots`
- **nginx** as reverse proxy replacing the K8s ingress
- **Prometheus + Grafana + Loki** for metrics/logs
- **Restic + cron** for backups

This preserves the entire `pipeline/`, `vl/`, `vldbaccess/` tree unmodified. Only `clustplorer/logic/argo_pipeline/` and the task-abort `subprocess.run(["kubectl", ...])` call need replacement.

**Estimated scope:** medium migration — roughly 3 replaced modules, ~1,500 LOC deleted or rewritten, 6 new systemd units, one new broker service. **No change** to `pipeline/controller/`, `vl/`, `vldbaccess/` business logic.

---

## 2. Current System Recap

Summarised from [pipeAnalysis.md](../pipeAnalysis.md). The 11 pipes fall into three operational profiles:

| Profile | Pipes | CPU | GPU | Duration | Triggered by |
|---|---|---|---|---|---|
| **End-to-end datasets** | `full_pipeline_flow`, `partial_update_flow`, `reindex_dataset_flow` | yes | optional | 5 min – 4 h | HTTP API |
| **Multi-step sub-flows** | `prepare_data_flow`, `enrichment_flow`, `indexer_flow` | mixed | mixed | 2–60 min | Parent flow chain |
| **Lightweight** | `restore_dataset_flow`, `nop_flow`, `post_success_flow`, `post_error_flow`, `model_training_flow` | yes | no | < 5 min | API or exit-handler |

**Existing on-prem-friendly primitives** already in the repo (no migration needed):

- Database-as-queue: `vldbaccess/task_queue/dao.py` with `SELECT FOR UPDATE SKIP LOCKED`
- Polling worker: `clustplorer/logic/queue_worker/worker.py`
- Tasks table + state machine: `vldbaccess/tasks/`
- Pipeline CLI entrypoint: `python -m pipeline.controller.controller --flow-to-run <name>`
- Flow registry: `pipeline/controller/controller.py:56-68`

**To replace:**

- `clustplorer/logic/argo_pipeline/argo_pipeline.py` — workflow trigger
- `clustplorer/logic/argo_pipeline/argo_pipeline_creator.py` — manifest builder
- `clustplorer/logic/common/hera_utils.py` — Hera wrappers
- `clustplorer/logic/model_training/model_training_argo_manager.py`
- `clustplorer/logic/flywheel/flywheel_runner_argo_manager.py`
- `subprocess.run(["kubectl", "delete", "workflow", ...])` in `vl/tasks/dataset_creation/dataset_creation_task_service.py:237`

---

## 3. Per-Pipe Execution Strategies

### 3.1 Strategy Catalog (approaches evaluated)

Rather than invent a unique approach per pipe, we evaluate five candidate execution models against all 11 pipes. Each pipe then gets a recommendation grounded in this catalog.

#### (A) systemd-managed polling workers over the existing `task_queue` table

Keep the existing database-as-queue; add dedicated worker processes (one unit per pipe type or per pool) supervised by `systemd`. Each worker `SELECT FOR UPDATE SKIP LOCKED`s from the queue, invokes `python -m pipeline.controller.controller --flow-to-run <name>` with env vars, and writes status back to the `tasks` table — **exactly mirroring what the Argo pod does today.**

| Attribute | Rating |
|---|---|
| **Pros** | Zero new dependencies; reuses existing queue code; simplest to reason about |
| **Cons** | DB-pressure from polling; no native retry backoff; no rich DAG features |
| **Ops complexity** | Low (systemd is ubiquitous) |
| **Scalability** | Horizontal = more worker VMs; each pulls from same queue |
| **Fault tolerance** | Good — stale-claim recovery already in code; workers restart via `Restart=always` |
| **Maintainability** | High — minimal new surface |

#### (B) Dramatiq + RabbitMQ (Python-native task queue)

Introduce **Dramatiq** as the dispatch layer with **RabbitMQ** as the broker. Each pipe becomes a Dramatiq actor; the backend calls `pipeline_actor.send(dataset_id)` instead of submitting an Argo manifest. Workers are plain Python processes bound to specific queues.

| Attribute | Rating |
|---|---|
| **Pros** | Native priorities, retries with exponential backoff, dead-letter queue; routing by queue name maps cleanly to CPU/GPU worker pools; message ack semantics survive worker crashes |
| **Cons** | New broker dependency (RabbitMQ) — one more service to run + monitor |
| **Ops complexity** | Medium (RabbitMQ is well-understood; HA via clustering optional) |
| **Scalability** | Excellent — add more workers per queue; RabbitMQ handles millions of messages/sec |
| **Fault tolerance** | Excellent — message persistence + ack + requeue |
| **Maintainability** | High — Dramatiq has ~2k LOC, clear docs, actively maintained |

#### (C) Celery + Redis

Industry default. Similar to Dramatiq but larger, older codebase, more edges.

| Attribute | Rating |
|---|---|
| **Pros** | Huge community; many integrations; result-backend built-in |
| **Cons** | Known reliability issues around visibility timeouts with Redis; Celery has historically had painful memory leaks and complex config; more rope to hang yourself |
| **Ops complexity** | Medium-High |
| **Scalability** | Excellent |
| **Fault tolerance** | Good, but Redis broker has edge cases (visibility timeout double-dispatch) |
| **Maintainability** | Medium — config surface is large |

#### (D) Apache Airflow

Full workflow orchestrator with DAGs, UI, scheduler.

| Attribute | Rating |
|---|---|
| **Pros** | Rich UI; DAG-native; mature; good for cron-style scheduling |
| **Cons** | Heavy for this use case (we have only event-driven triggers, no cron DAGs); Airflow's executor model (LocalExecutor/CeleryExecutor) just punts to Celery anyway; extra scheduler/webserver/metadata DB to run |
| **Ops complexity** | High |
| **Scalability** | Good, but overkill |
| **Fault tolerance** | Good |
| **Maintainability** | Medium-High |

#### (E) Prefect 2.x / Dagster

Modern orchestrators with hybrid execution.

| Attribute | Rating |
|---|---|
| **Pros** | Modern Python APIs; good observability |
| **Cons** | Strongest value is in cloud/hybrid mode; pure on-prem self-host is second-class for both; adds significant concept-count |
| **Ops complexity** | High |
| **Scalability** | Good |
| **Fault tolerance** | Good |
| **Maintainability** | Medium — rapid version churn |

### 3.2 Per-Pipe Analysis Matrix

Two candidate approaches per pipe, then a recommendation. All pipes ultimately converge on the same core stack — intentional, because operating 11 different execution models on-prem would be untenable.

#### Pipe 1 — `full_pipeline_flow`

End-to-end, long-running, may touch GPU.

| Option | Fit | Notes |
|---|---|---|
| (A) systemd + DB queue | OK | Works, but lacks rich retry/routing |
| (B) Dramatiq + RabbitMQ | Best | Route to `cpu.pipeline` or `gpu.pipeline` queues, separate worker pools, native retries |

**Recommended: (B).** Routing to CPU-only vs GPU-enabled worker pools via queue name replaces K8s nodeAffinity cleanly.

#### Pipe 2 — `prepare_data_flow`

CPU sub-step; short.

| Option | Fit | Notes |
|---|---|---|
| (A) systemd + DB queue | Good | Fine — short, no GPU |
| (B) Dramatiq | Best | Chained via downstream actor `.send()` |

**Recommended: (B)** — to stay on one stack. Triggered by the parent pipeline actor as a downstream message.

#### Pipe 3 — `enrichment_flow`

GPU-only, heaviest.

| Option | Fit | Notes |
|---|---|---|
| (B) Dramatiq GPU queue | Best | `gpu.enrichment` queue bound only to GPU workers |
| (C) Celery GPU queue | OK | Same idea, Celery's larger footprint unnecessary |

**Recommended: (B).** Dedicate 1–N GPU VMs as `gpu-worker` role; only their Dramatiq processes subscribe to `gpu.*` queues.

#### Pipe 4 — `indexer_flow`

CPU; writes to PostgreSQL.

| Option | Fit | Notes |
|---|---|---|
| (A) systemd + DB queue | OK | OK |
| (B) Dramatiq | Best | Runs on any CPU worker; minimal config |

**Recommended: (B).**

#### Pipe 5 — `partial_update_flow`

Same shape as full pipeline but shorter.

**Recommended: (B)** — same actor routing as pipe 1.

#### Pipe 6 — `reindex_dataset_flow`

CPU + optional GPU; single-pod.

**Recommended: (B)** — `cpu.reindex` queue; if GPU needed, `gpu.reindex`.

#### Pipe 7 — `restore_dataset_flow`

Lightweight CPU; DB replay.

| Option | Fit | Notes |
|---|---|---|
| (A) systemd + DB queue | Best | Overkill to add broker for this alone |
| (B) Dramatiq | Best | Fine; already on the bus if we converge |

**Recommended: (B)** for uniformity.

#### Pipe 8 — `nop_flow`

Smoke test only.

**Recommended:** any — keep as CLI-invoked diagnostic. No queue needed. Useful as an on-prem smoke-test hitting the `cpu.default` queue end-to-end.

#### Pipe 9 — `post_success_flow` & Pipe 10 — `post_error_flow`

Argo exit handlers.

| Option | Fit | Notes |
|---|---|---|
| (B) Dramatiq middleware | Best | Dramatiq has built-in `on_success`/`on_failure` middleware — exact fit |
| (A) Try/finally in the actor | OK | Simpler but couples cleanup into the main actor |

**Recommended: (B)** — use Dramatiq middleware hooks. This gives us exit-handler semantics without K8s.

#### Pipe 11 — `model_training_flow`

CPU prep + external Camtek API call.

| Option | Fit | Notes |
|---|---|---|
| (B) Dramatiq actor | Best | Short-running; calls out to `CAMTEK_TRAIN_API_ENDPOINT` |
| (C) Celery | OK | No extra benefit |

**Recommended: (B).**

#### Bonus: Flywheel

**Recommended: (B)** — iterative loop implemented as a Dramatiq actor that re-enqueues itself (`self.send_with_options(delay=...)`).

### 3.3 Selected Approach and Justification

**Unanimously: Dramatiq + RabbitMQ + systemd**, with PostgreSQL as the durable state store (existing).

**Why Dramatiq over Celery:**

1. Smaller, less magical codebase — easier to debug on-prem
2. Priority queues built-in; we need them for interactive vs batch
3. Simpler at-least-once semantics with explicit ack
4. Less production-pain history (Celery/Redis visibility-timeout bugs, memory growth)
5. First-class middleware hooks map 1:1 to `post_success`/`post_error` exit handlers

**Why RabbitMQ over Redis:**

1. Durable message storage survives broker restart without extra config
2. Priorities, TTLs, DLX all native
3. Better routing semantics (queue bindings map cleanly to CPU/GPU pools)
4. Easier on-prem HA if we later cluster it

**Why keep PostgreSQL tasks table:**

1. UI-visible task state must survive a broker wipe — PG is the source of truth
2. Retry/abort/audit semantics already written there
3. Broker is just the dispatch mechanism; state lives in PG

**What we explicitly reject:**

- Airflow / Prefect / Dagster — overkill for an event-driven, non-DAG-scheduled workload
- Celery — larger footprint, worse reputation on-prem
- Pure systemd + DB queue — works, but lacks routing + retry polish; would reinvent Dramatiq

---

## 4. System Architecture (HLD)

### 4.1 Component Inventory

| Component | Technology | Role | Count (recommended) |
|---|---|---|---|
| **API gateway** | nginx | TLS termination, routing `/api` to backend, `/image` to image-proxy, `/` to FE | 1–2 (active/standby with keepalived for HA) |
| **Backend** | FastAPI (`clustplorer`) | HTTP API, auth via Keycloak, task creation, message dispatch | 2+ behind nginx |
| **Frontend** | React build (`clustplorer-fe`) served by nginx | UI | static, served by nginx |
| **Image proxy** | `image-proxy` service | Serves images from shared storage | 1 per region |
| **Message broker** | RabbitMQ | Task queue | 1 (single) or 3-node cluster for HA |
| **CPU workers** | Python + Dramatiq | Execute CPU pipes | N VMs (scale horizontally) |
| **GPU workers** | Python + Dramatiq | Execute GPU pipes | M VMs with NVIDIA drivers |
| **Scheduler/cleanup** | systemd timer units | Cron-like jobs (old data cleanup, orphan-task sweeper) | co-located with backend |
| **PostgreSQL** | PostgreSQL 15+ | Source of truth: datasets, tasks, task_queue audit | 1 primary + 1 hot standby (streaming replication) |
| **DuckDB** | DuckDB | Embedded analytics (files on NFS) | co-located with backend/worker |
| **Keycloak** | Keycloak | OIDC auth | 1 instance or HA pair |
| **OpenFGA** | OpenFGA | Authorization | 1 instance |
| **Shared storage** | NFS server (or Ceph/GlusterFS) | `/data`, `/models`, `/snapshots` | 1 NFS head or distributed |
| **Object storage** | MinIO | Local S3-compatible store for published media, snapshots | 1 or 4-node erasure-coded |
| **Monitoring** | Prometheus + Grafana | Metrics | 1 monitoring VM |
| **Logs** | Loki + Promtail (or ELK) | Aggregation | co-located with monitoring |
| **Backups** | Restic + cron | PG dumps + NFS snapshot | timer unit on monitoring VM |
| **Secrets** | HashiCorp Vault (optional) or SOPS + age | Secret management | optional |

### 4.2 Block Diagram

```
                                            +-------------------------+
                                            |  Users / Camtek clients |
                                            +------------+------------+
                                                         | HTTPS
                                                         v
                                  +-----------------------------------------+
                                  |        nginx (TLS, routing, 443)        |
                                  +--+-------+--------------+---------------+
                                     |       |              |
                    +----------------+       |              +---------------+
                    v                        v                              v
           +----------------+        +----------------+            +----------------+
           |  FE static     |        |  FastAPI x N   |            |  image-proxy   |
           |  (React build) |        |  (clustplorer) |            |   (images)     |
           +----------------+        +---+--------+---+            +--------+-------+
                                         |        |                         |
                    +--------------------+        +-----------+             |
                    |                                          |             |
          +---------v--------+                       +---------v------+      |
          |  PostgreSQL HA   |                       |  RabbitMQ      |      |
          |  (primary+HS)    |                       |  (broker)      |      |
          |  tasks, datasets |                       |  queues:       |      |
          |  task_queue audit|                       |   cpu.pipeline |      |
          +------------------+                       |   gpu.pipeline |      |
                                                     |   cpu.indexer  |      |
                                                     |   cpu.training |      |
                                                     |   cpu.default  |      |
                                                     |   dlx.*        |      |
                                                     +--+----------+--+      |
                                                        |          |         |
                            +---------------------------+          |         |
                            v                                      v         |
                   +----------------+                     +----------------+ |
                   |  CPU worker VM |  x N                |  GPU worker VM | xM
                   |  Dramatiq proc |                     |  Dramatiq proc |  |
                   |  systemd-managed|                    |  systemd +     |  |
                   +----+-----------+                     |   NVIDIA drvs  |  |
                        |                                 +-----+----------+  |
                        |                                       |             |
                        v                                       v             |
                    +---------------------------------------------------+     |
                    |            NFS / MinIO (shared storage)           |<----+
                    |   /data   /models   /snapshots   /thumbs          |
                    +---------------------------------------------------+

          Sidecar stack:
          +---------------------------------------------------+
          |  Keycloak   OpenFGA   Prometheus   Grafana   Loki |
          +---------------------------------------------------+
```

### 4.3 End-to-End Flow Diagram (Create Dataset)

```
[User clicks "Process" in FE]
       |
       v
POST /api/v1/dataset/{id}/process  ---------+
       |                                    |
       v                                    |
+-----------------+                          |
| FastAPI handler |                          |
| (clustplorer)   |                          |
+------+----------+                          |
       |                                     |
       +-> 1. Write `tasks` row              |
       |    (status=RUNNING, task_id=UUID)   |
       |                                     |
       +-> 2. Determine routing              |
       |    needs_gpu = enrichment_config    |
       |    size_tier = f(n_images, ...)     |
       |                                     |
       +-> 3. pipeline_actor.send_with_options(
              queue="gpu.pipeline" if gpu else "cpu.pipeline",
              priority=f(size_tier),
              args=[task_id, dataset_id, user_id, ...]
           )
                                             |
                                             v
                       +----------------------------------+
                       |        RabbitMQ (durable)        |
                       |  cpu.pipeline / gpu.pipeline     |
                       +-------------+--------------------+
                                     | AMQP prefetch
                                     v
                       +----------------------------------+
                       |  Worker: pipeline_actor.fn(...)  |
                       |  1. Set os.environ: FLOW_RUN_ID, |
                       |     DATASET_ID, PIPELINE_FLOW_TYPE
                       |  2. Invoke flow directly:        |
                       |     from pipeline.controller     |
                       |       .pipeline_flows import     |
                       |       full_dataset_pipeline_flow |
                       |     full_dataset_pipeline_flow() |
                       |  3. on_success -> middleware hook|
                       |     on_failure -> middleware hook|
                       +-------------+--------------------+
                                     |
      (@controller_step decorator writes progress to `tasks` table)
                                     |
                                     v
                       +----------------------------------+
                       |    PostgreSQL                    |
                       | UPDATE tasks SET sub_status=...  |
                       | progress_percentage=...          |
                       +----------------------------------+
                                     |
                                     v
                       tasks row: status=COMPLETED
                       dataset row: status=READY

[FE polls GET /api/v1/tasks?dataset_id=...]
```

### 4.4 Sequence Diagram — Task Submit to Pipe Execute

```
FE         FastAPI        Postgres       RabbitMQ      Worker     NFS/MinIO
 |            |               |              |            |            |
 |  POST /process             |              |            |            |
 |----------->|               |              |            |            |
 |            | INSERT tasks  |              |            |            |
 |            |-------------->|              |            |            |
 |            |       OK      |              |            |            |
 |            |<--------------|              |            |            |
 |            | publish(msg)                 |            |            |
 |            |----------------------------->|            |            |
 |            |         ack                  |            |            |
 |            |<-----------------------------|            |            |
 |    202     |                              |            |            |
 |<-----------|                              |            |            |
 |            |                              |            |            |
 |            |                              | deliver    |            |
 |            |                              |----------->|            |
 |            |                              |            | read data  |
 |            |                              |            |----------->|
 |            |                              |            |<-----------|
 |            |          (step decorator writes progress) |            |
 |            |<----------------------------------------- |            |
 |            |   UPDATE tasks progress      |            |            |
 |            |----------------------------->|            |            |
 |            |                              |            | write out  |
 |            |                              |            |----------->|
 |            |                              |            | ack msg    |
 |            |                              |<-----------|            |
 | GET /tasks |                              |            |            |
 |----------->|                              |            |            |
 |            | SELECT tasks  |              |            |            |
 |            |-------------->|              |            |            |
 |            |<--------------|              |            |            |
 |   200 OK   |                              |            |            |
 |<-----------|                              |            |            |
```

### 4.5 Deployment Model

Each component runs on a **VM or bare-metal host**, not an orchestrator. `systemd` supervises everything. Containers are used **optionally** for Python runtime isolation (via plain `docker run` under a systemd unit) but not orchestrated.

| Role | Suggested host | Services |
|---|---|---|
| `edge` VM | 2 hosts (active-passive via keepalived) | nginx, SSL certs |
| `api` VM | 2–3 hosts | FastAPI (clustplorer), image-proxy, Keycloak |
| `db` VM | 2 hosts (primary + hot standby) | PostgreSQL, OpenFGA |
| `broker` VM | 1 or 3 hosts | RabbitMQ |
| `cpu-worker` VM | N >= 2 | Dramatiq CPU actor processes |
| `gpu-worker` VM | M >= 1 | Dramatiq GPU actor processes (NVIDIA drivers) |
| `storage` VM | 1–4 hosts | NFS / MinIO |
| `monitor` VM | 1 host | Prometheus, Grafana, Loki, backup runner |

CPU / GPU workers **do not share a queue set** — GPU boxes subscribe to `gpu.*` queues only; CPU boxes subscribe to `cpu.*`. This is the architectural replacement for K8s nodeAffinity.

### 4.6 Storage Layout

K8s PVCs map to NFS exports or MinIO buckets. Naming preserved for minimal code change.

| K8s PVC | Replacement | Path / Bucket |
|---|---|---|
| `backend-efs-pvc` (RWMany models) | NFS export | `/mnt/vl/models/` |
| `duckdb-storage-pvc` (RWMany, 100Gi) | NFS export | `/mnt/vl/duckdb/` |
| `datasets-storage-pvc` (RWO, 50Gi) | Local SSD on each worker | `/var/lib/vl/datasets-staging/` |
| `db-csv-exports-pvc` | NFS export | `/mnt/vl/csv-exports/` |
| `model-storage-pvc` | NFS export | `/mnt/vl/model-output/` |
| `ground-truth-pvc` | NFS export | `/mnt/vl/ground-truth/` |
| `longhorn-data-enc-pvc` | LUKS-encrypted LVM volume on storage VM, re-exported via NFS | `/mnt/vl/data-enc/` |
| S3 bucket (thumbnails, snapshots) | MinIO bucket | `s3://vl-media`, `s3://vl-snapshots` |

**Shared `/data` between multi-step pipes:** a single NFS export is mounted at the same path on every worker; Dramatiq messages include the run-scoped subdirectory name (`/data/{FLOW_RUN_ID}/`).

### 4.7 Queue Topology

```
RabbitMQ vhost: /vl

Exchanges:
  vl.tasks           (direct)   - normal task dispatch
  vl.dlx             (fanout)   - dead-letter
  vl.exit            (topic)    - exit handlers

Queues (bound to vl.tasks with matching routing key):
  cpu.default        - nop_flow, restore_dataset_flow, model_training_flow
  cpu.pipeline       - full_pipeline_flow (CPU path), partial_update_flow (CPU)
  cpu.indexer        - indexer_flow standalone
  cpu.reindex        - reindex_dataset_flow (CPU)
  gpu.pipeline       - full_pipeline_flow (GPU path), partial_update_flow (GPU)
  gpu.enrichment     - enrichment_flow
  gpu.reindex        - reindex_dataset_flow (GPU)

Exit queues (bound to vl.exit):
  exit.success.*     - post_success_flow (middleware-generated)
  exit.failure.*     - post_error_flow

Dead-letter queues:
  dlx.<original_queue>   - e.g. dlx.gpu.enrichment

Queue args (per queue):
  x-message-ttl: 86400000       (24 h - failsafe against stuck messages)
  x-max-priority: 10             (interactive=9, batch=3, background=1)
  x-dead-letter-exchange: vl.dlx
  x-dead-letter-routing-key: dlx.<queue_name>
```

**Priority mapping:**

- User-triggered interactive datasets -> priority 9
- Add-media / retries -> priority 5
- Reindex / restore -> priority 3
- Training prep -> priority 1

---

## 5. Migration Plan

### 5.1 Phase Overview

| Phase | Scope | Goal |
|---|---|---|
| **P0** | Prep | Build target infra in parallel; no prod changes |
| **P1** | Pilot | Run `nop_flow` + `restore_dataset_flow` through new stack in staging |
| **P2** | Coexistence | Feature flag routes between Argo and Dramatiq per pipe |
| **P3** | Cutover | Flip flag to Dramatiq for all pipes; keep Argo as fallback |
| **P4** | Decommission | Remove Argo code + dependencies |

### 5.2 Required Code Changes

**New modules (net additions):**

```
clustplorer/
  logic/
    dispatch/                          <- NEW (replaces argo_pipeline/)
      __init__.py
      broker.py                        <- RabbitMQ connection
      actors.py                        <- Dramatiq actor definitions per pipe
      middleware.py                    <- on_success/on_failure exit-handler middleware
      routing.py                       <- size-tier -> queue-name logic (replaces auto-resource sizing)
  logic/
    queue_worker/worker.py             <- UNCHANGED (still serves legacy task_queue)
```

**Refactored modules:**

| File | Change |
|---|---|
| `argo_pipeline.py` | `trigger_vl_argo_processing()` replaced with `dispatch.actors.pipeline_actor.send_with_options(...)`. Keep same function signature during coexistence so API layer is unchanged. |
| `argo_pipeline_creator.py` | Deleted in P4. The resource-sizing helpers (`_compute_cpu_resources`, `_compute_gpu_resources`) are renamed and moved to `dispatch/routing.py` — they become **queue-priority** selectors instead of pod resource specs. |
| `hera_utils.py` | Deleted in P4. |
| `model_training_argo_manager.py` | Rewritten as `dispatch/training_actor.py` — a Dramatiq actor. |
| `flywheel_runner_argo_manager.py` | Rewritten as a self-re-enqueueing Dramatiq actor. |
| `dataset_creation_task_service.py:237` `_terminate_argo_workflow` | Replaced with `dramatiq_abort.abort(message_id)` using the `dramatiq-abort` middleware. |

**Unchanged (the whole point of the design):**

- All of `pipeline/` — controllers, steps, decorators, flows
- All of `vl/` — business logic
- All of `vldbaccess/` — DB access
- `vldbaccess/tasks/` — task state machine
- `vldbaccess/task_queue/` — kept, used by the existing queue worker for non-pipeline work
- `clustplorer/web/` — HTTP API (signatures unchanged; only dispatch target differs)

**Example — actor skeleton** (`dispatch/actors.py`, ~40 lines):

```python
import dramatiq
from dramatiq.brokers.rabbitmq import RabbitmqBroker
from pipeline.controller.pipeline_flows import (
    full_dataset_pipeline_flow,
    enrichment_flow,
    partial_update_flow,
    reindex_dataset_flow,
    restore_dataset_flow,
    model_training_flow,
)
from vl.common.settings import Settings

broker = RabbitmqBroker(url=Settings.RABBITMQ_URL)
dramatiq.set_broker(broker)

def _set_env(task_id, dataset_id, user_id, flow_type, **kwargs):
    import os
    os.environ["FLOW_RUN_ID"] = str(task_id)
    os.environ["DATASET_ID"] = str(dataset_id)
    os.environ["USER_ID"] = str(user_id)
    os.environ["PIPELINE_FLOW_TYPE"] = flow_type
    for k, v in kwargs.items():
        os.environ[k] = str(v)

@dramatiq.actor(queue_name="cpu.pipeline", max_retries=3, time_limit=4*3600*1000)
def run_full_pipeline_cpu(task_id, dataset_id, user_id, **env):
    _set_env(task_id, dataset_id, user_id, "PIPELINE", **env)
    full_dataset_pipeline_flow()

@dramatiq.actor(queue_name="gpu.pipeline", max_retries=3, time_limit=6*3600*1000)
def run_full_pipeline_gpu(task_id, dataset_id, user_id, **env):
    _set_env(task_id, dataset_id, user_id, "PIPELINE", **env)
    full_dataset_pipeline_flow()

@dramatiq.actor(queue_name="gpu.enrichment", max_retries=2, time_limit=4*3600*1000)
def run_enrichment(task_id, dataset_id, user_id, **env):
    _set_env(task_id, dataset_id, user_id, "ENRICHMENT", **env)
    enrichment_flow()

# ... one actor per pipe, mirrors flow_map in controller.py
```

**Example — dispatch wrapper** (`dispatch/__init__.py`, replaces `ArgoPipeline.trigger_vl_argo_processing`):

```python
from .actors import run_full_pipeline_cpu, run_full_pipeline_gpu, run_enrichment
from .routing import needs_gpu, priority_for_size

def trigger_pipeline(task_id, dataset_id, user_id, flow_type, enrichment_config, size_units):
    priority = priority_for_size(size_units)
    actor_map = {
        ("PIPELINE", True):  run_full_pipeline_gpu,
        ("PIPELINE", False): run_full_pipeline_cpu,
        ("ENRICHMENT", True): run_enrichment,
        # ... one entry per (flow_type, gpu) pair
    }
    gpu = needs_gpu(enrichment_config)
    actor = actor_map[(flow_type, gpu)]
    msg = actor.send_with_options(
        args=(str(task_id), str(dataset_id), str(user_id)),
        priority=priority,
    )
    # persist broker message_id for abort
    return msg.message_id
```

### 5.3 Infrastructure Setup

1. **Provision VMs** (Terraform or Ansible)
   - edge x 2, api x 3, db x 2, broker x 1 (or 3 for HA), cpu-worker x N, gpu-worker x M, storage x 1, monitor x 1
2. **Install PostgreSQL** — stream replication primary -> standby; restore prod schema via existing `vldbmigration/`
3. **Install RabbitMQ** — enable management plugin, `rabbitmq-plugins enable rabbitmq_management`; declare vhost `/vl`, exchanges + queues via `rabbitmqadmin` or a `rabbitmq_definitions.json` bootstrap
4. **Install NFS server** — export `/mnt/vl/{data,models,duckdb,csv-exports,model-output,ground-truth,data-enc}`; clients mount via `autofs`
5. **Install MinIO** — single-node or 4-node erasure-coded distributed mode; create buckets `vl-media`, `vl-snapshots`
6. **Install NVIDIA drivers + CUDA** on GPU workers (match the GPU pipeline image's CUDA version)
7. **Install Keycloak + OpenFGA** — pre-seed same realms/clients/models as current cluster
8. **Deploy Python code** — `uv pip install` from lockfile; systemd units for each service role (see Appendix A)
9. **Configure nginx** — TLS cert (Let's Encrypt via acme.sh, or corporate CA); proxy rules per role
10. **Configure Prometheus / Grafana / Loki** — import existing dashboards; add node_exporter, rabbitmq_exporter, postgres_exporter, nvidia_gpu_exporter

### 5.4 Replacement of Kubernetes-Specific Components

| K8s concept | On-prem equivalent |
|---|---|
| Argo Workflow CRD | Dramatiq message in RabbitMQ |
| Workflow template | Dramatiq actor |
| Pod scheduling | systemd service on a VM role |
| nodeAffinity `role=cpu-pipeline` | `cpu-worker` VM subscribes only to `cpu.*` queues |
| nodeAffinity `role=gpu-pipeline` | `gpu-worker` VM subscribes only to `gpu.*` queues |
| Tolerations | N/A (VMs are dedicated, no multi-tenant scheduling) |
| `resources.requests` | systemd `CPUQuota=`, `MemoryMax=`; optional cgroups v2 slices |
| `ttlStrategy` | RabbitMQ `x-message-ttl` + Dramatiq result TTL |
| `onExit` exit handler | Dramatiq middleware (`on_success`, `on_failure`) |
| Ingress | nginx vhost |
| PVC (RWMany) | NFS export |
| PVC (RWO) | Local disk on each worker |
| Secret | Files in `/etc/vl/secrets/` with `0600`, or Vault |
| ConfigMap | `/etc/vl/config.env` loaded via systemd `EnvironmentFile=` |
| ClusterRole `pipeline-job-manager` | N/A (no API to grant on) |
| `kubectl delete workflow` (abort) | `dramatiq_abort.abort(message_id)` |
| Helm release | Ansible playbook or Debian/RPM packages |
| Argo UI | RabbitMQ Management UI (port 15672) + Grafana |

### 5.5 Transitional Architecture (P2 — coexistence)

```
                     FastAPI
                        |
                        | feature_flag = f(dataset_id, flow_type)
                        |
              +---------+---------+
              |                   |
              v                   v
       ArgoPipeline.trigger   dispatch.trigger_pipeline
       (unchanged)            (new)
              |                   |
              v                   v
           K8s + Argo          RabbitMQ + Dramatiq
           (prod)              (new stack)
```

Gate with a per-pipe feature flag (e.g., `VL_DISPATCH_BACKEND__FULL_PIPELINE=dramatiq`). The `tasks` table stays unchanged -> UI works regardless of backend. Start with `nop_flow` and `restore_dataset_flow`, progress to heavier pipes as the new stack proves stable for 1+ week per tier.

### 5.6 Data Migration Considerations

1. **Tasks & datasets** — pgdump + restore from the K8s-hosted PG into the on-prem PG. Use logical replication during cutover to keep them in sync for minutes-scale downtime.
2. **S3 media + snapshots** — `rclone sync s3://prod-bucket minio://vl-media` in repeatable sync mode until cutover.
3. **Model weights** — one-time copy of `backend-efs-pvc` contents (~28 GB) via `rsync` to `/mnt/vl/models/`.
4. **DuckDB files** — rsync from `duckdb-storage-pvc`.
5. **In-flight workflows** — do not cut over while workflows are running. Drain Argo queue first (stop new submissions, wait for all to finalize or fail, then flip flag).

### 5.7 Risks and Mitigation

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| RabbitMQ single point of failure | Med | High | Deploy 3-node cluster with mirrored queues from day one; monitor broker health |
| NFS throughput bottleneck on large datasets | Med | Med | Benchmark before cutover; fall back to local SSD + explicit transfer step for hottest path |
| GPU driver mismatch between host and pipeline code | Med | High | Pin CUDA/driver version; run GPU smoke test (`enrichment_flow` on small dataset) nightly |
| `dramatiq-abort` not as immediate as `kubectl delete` | Low | Low | Accept; update UI copy to "Abort requested" until worker checks the abort flag |
| Message loss on broker crash | Low | High | Use publisher-confirms + durable queues + persistent messages; PG `tasks` row is source of truth anyway |
| Staff unfamiliar with Dramatiq | Med | Low | Internal runbook; Dramatiq is small (~2k LOC), easy to read |
| Double-execution due to worker crash mid-task | Low | Med | Tasks are idempotent by `FLOW_RUN_ID`; step decorator can check for already-done state |
| Broker queue backlog during peak | Med | Med | Queue depth alerting (Prometheus); auto-scale by adding worker VMs |

### 5.8 Rollback Plan

The coexistence design **is** the rollback plan. At any point during P2/P3:

1. Flip `VL_DISPATCH_BACKEND__*` flags back to `argo` (or whichever pipes haven't cut over)
2. New submissions go to Argo again
3. Drain RabbitMQ by letting current workers finish
4. Revert is instantaneous at the API boundary — no code rollback needed

Full revert (P4 reached and broken):

- Re-deploy the previous backend image (tagged pre-P4)
- K8s cluster was never removed during P0–P3 (we ran both side by side)
- Hard requirement: **do not decommission K8s until 30 days of clean on-prem operation**

---

## 6. Operational Design

### 6.1 Deployment & Release

- **Code delivery:** Backend + worker share one wheel (`vl_camtek-*.whl`). Build in CI, publish to internal PyPI (e.g., devpi or Nexus).
- **Host updates:** Ansible playbook pulls new wheel, `systemctl reload`.
- **Blue/green on API:** nginx upstream swap. API is stateless; workers drain gracefully via Dramatiq `shutdown_signal`.
- **Worker rolling deploy:** `systemctl stop` sends SIGTERM; Dramatiq lets in-flight tasks complete for up to `shutdown_timeout`; no message loss (unacked messages requeue on broker).
- **Migrations:** Run `vldbmigration` from one api host pre-release; schema is backwards-compatible for one release cycle.

### 6.2 Monitoring & Logging

**Metrics (Prometheus):**

| Exporter | What |
|---|---|
| `node_exporter` | Host CPU/mem/disk/net |
| `rabbitmq_exporter` | Queue depth, consumer count, ack rate, unacked messages |
| `postgres_exporter` | Connections, locks, replication lag, query time |
| `nvidia_gpu_exporter` | GPU utilisation, memory, temp |
| `minio` built-in `/minio/v2/metrics/cluster` | Object storage health |
| Custom app metrics via `prometheus_client` in FastAPI and workers | Task counts by status, per-pipe duration, step timings |

**Key alerts:**

- `cpu.*` or `gpu.*` queue depth > 100 for > 5 min
- RabbitMQ unacked messages > 50 for > 10 min (stuck worker)
- Postgres replication lag > 60 s
- Worker systemd unit failed > 3 restarts in 10 min
- GPU memory > 95% for > 2 min (OOM imminent)
- Broker disk usage > 70%

**Logs (Loki + Promtail):**

- All workers and backend log JSON lines to stdout; systemd journald captures; promtail ships to Loki with labels `host`, `service`, `pipe`, `task_id`, `flow_run_id`.
- Retention: 30 days hot (Loki), archive to cold storage weekly.
- Existing `get_vl_logger(__name__)` keeps the `vl.root.*` naming — no change.

**Tracing (optional):** OpenTelemetry + Tempo. Dramatiq has a middleware for propagating trace IDs.

### 6.3 Error Handling & Retries

- **Dramatiq-level retries:** per-actor `max_retries`, exponential backoff (`min_backoff`, `max_backoff`).
- **Dead-letter queue:** after exhausted retries, message lands in `dlx.<queue>`. Daily digest to `#ops-vl`.
- **Task-level retry:** existing `POST /api/v1/tasks/{id}/retry` — re-dispatches actor.
- **Abort:** `dramatiq-abort` middleware -> cancels in-flight actor; commit-phase protection unchanged.
- **Exit handlers:** `on_success` middleware enqueues `post_success_flow`; `on_failure` enqueues `post_error_flow`. Both idempotent.
- **External I/O retries:** existing OpenFGA + Camtek gRPC retry decorators unchanged.

### 6.4 Scaling Strategy Without Kubernetes

- **Vertical:** each worker VM sized for the **largest** expected single task in its pool (e.g. 16 CPU / 128 GiB for top CPU tier; 1 GPU / 96 GiB for XFER).
- **Horizontal:** add more cpu-worker VMs — they each subscribe to the same `cpu.*` queues and RabbitMQ load-balances. Same for GPU.
- **Prefetch:** set `prefetch_count=1` on workers so a slow task doesn't starve fast ones on the same VM.
- **Queue-based isolation:** heavy reindex jobs on `cpu.reindex` don't block interactive pipelines on `cpu.pipeline`.
- **Capacity planning:** establish a weekly dashboard on `queue_depth x avg_task_duration` -> if projected wait > SLO, provision more workers.
- **Auto-scale (optional):** a small controller can watch Prometheus queue depth and run `ansible-playbook scale_workers.yml -e count=N` to spin up VMware/Proxmox VMs — but this is optional; manual capacity adds are typically sufficient.

### 6.5 Backup & Disaster Recovery

| Asset | Method | Frequency | Retention | RTO / RPO |
|---|---|---|---|---|
| PostgreSQL | pgBackRest (WAL archive + full weekly + incremental daily) | WAL: continuous, full: weekly | 30 d | RTO 1 h / RPO 5 min |
| NFS (`/mnt/vl/*`) | ZFS snapshots + `zfs send` to secondary storage VM | Hourly | 7 d hourly, 90 d daily | RTO 2 h / RPO 1 h |
| MinIO buckets | `mc mirror` to secondary MinIO (or off-site) | Hourly | 30 d | RTO 2 h / RPO 1 h |
| RabbitMQ | Definitions export (`rabbitmqctl export_definitions`) | Daily | 90 d | RTO 15 min (messages are ephemeral, PG is source of truth) |
| Keycloak realms | Export JSON | Daily | 90 d | RTO 30 min |
| Model weights | Versioned in NFS + off-site rsync | Weekly | 4 versions | RTO 4 h / RPO 1 week (rarely change) |
| Config (Ansible repo) | Git + backup of Ansible Vault keys | On commit | Forever | RTO 15 min |

**DR drill:** quarterly, rehydrate from backups to a cold-site VM pool; run `nop_flow` + `restore_dataset_flow` end-to-end.

---

## 7. Constraints, Risks, and Tradeoffs

**What we lose vs. K8s/Argo:**

- **Dynamic per-workflow resource sizing.** Workers are sized statically; the largest dataset dictates the VM footprint. Mitigation: route XFER (largest) to a dedicated `gpu.pipeline.xfer` queue with one very large worker; keep a separate smaller GPU pool for routine enrichment.
- **Automatic pod cleanup.** Replaced by per-run temp-dir cleanup in `post_success_flow` / `post_error_flow` + systemd `PrivateTmp`.
- **Argo UI.** Partially replaced by RabbitMQ Management UI (message/queue level) + Grafana (task level). Lacks a step-graph view; acceptable given the internal task UI already shows progress.
- **Built-in retry backoff at pod level.** Replaced by Dramatiq retry middleware.

**What we gain:**

- **Radical simplicity.** One broker + systemd units — no CRDs, no controller, no webhook, no admission controllers.
- **Easier debugging.** `journalctl -u vl-cpu-worker@1 -f` beats `kubectl logs pod/...` for most issues.
- **Lower baseline cost.** No K8s control plane to operate/license.
- **On-prem-native.** Matches customer environments that disallow K8s for compliance.

**Non-goals (for clarity):**

- Multi-tenant workload isolation — workers are dedicated per-pool; do not run untrusted code.
- Per-second auto-scaling — manual or nightly cron-scaled sufficient.
- Workflow archive beyond 1 week — kept in PostgreSQL `tasks` table history.

---

## Appendix A — systemd Unit Examples

**`/etc/systemd/system/vl-api@.service`**

```ini
[Unit]
Description=vl-camtek FastAPI (worker %i)
After=network.target postgresql.service

[Service]
Type=simple
User=vl
Group=vl
WorkingDirectory=/opt/vl
EnvironmentFile=/etc/vl/config.env
EnvironmentFile=/etc/vl/secrets.env
ExecStart=/opt/vl/.venv/bin/uvicorn clustplorer.web:app \
          --host 127.0.0.1 --port 99%i --workers 4
Restart=always
RestartSec=5
LimitNOFILE=65536
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

Enable with `systemctl enable --now vl-api@01 vl-api@02 vl-api@03`; nginx upstream round-robins among 127.0.0.1:9901-9903.

**`/etc/systemd/system/vl-cpu-worker@.service`**

```ini
[Unit]
Description=vl-camtek Dramatiq CPU worker (instance %i)
After=network.target rabbitmq-server.service

[Service]
Type=simple
User=vl
Group=vl
WorkingDirectory=/opt/vl
EnvironmentFile=/etc/vl/config.env
EnvironmentFile=/etc/vl/secrets.env
# Subscribe only to CPU queues
ExecStart=/opt/vl/.venv/bin/dramatiq clustplorer.logic.dispatch.actors \
          --queues cpu.default cpu.pipeline cpu.indexer cpu.reindex \
          --processes 1 --threads 1 \
          --worker-shutdown-timeout 300000
Restart=always
RestartSec=10
# Resource caps (cgroups v2)
CPUQuota=1600%
MemoryMax=128G
# Clean tmp per run
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

**`/etc/systemd/system/vl-gpu-worker@.service`**

```ini
[Unit]
Description=vl-camtek Dramatiq GPU worker (instance %i)
After=network.target rabbitmq-server.service nvidia-persistenced.service

[Service]
Type=simple
User=vl
Group=vl
WorkingDirectory=/opt/vl
EnvironmentFile=/etc/vl/config.env
EnvironmentFile=/etc/vl/secrets.env
Environment=CUDA_VISIBLE_DEVICES=%i
ExecStart=/opt/vl/.venv/bin/dramatiq clustplorer.logic.dispatch.actors \
          --queues gpu.pipeline gpu.enrichment gpu.reindex \
          --processes 1 --threads 1 \
          --worker-shutdown-timeout 600000
Restart=always
RestartSec=15
MemoryMax=96G

[Install]
WantedBy=multi-user.target
```

**`/etc/systemd/system/vl-cleanup.timer`** (replaces the Argo cleanup CronJob)

```ini
[Unit]
Description=Nightly vl-camtek cleanup

[Timer]
OnCalendar=daily
Persistent=true
RandomizedDelaySec=30min

[Install]
WantedBy=timers.target
```

---

## Appendix B — Docker Compose Stack

For sites preferring container isolation but *without* an orchestrator, a single `docker-compose.yml` on each role-host supervises containers; systemd supervises the Compose project.

```yaml
version: "3.9"

x-common-env: &common
  env_file:
    - /etc/vl/config.env
    - /etc/vl/secrets.env
  restart: unless-stopped

services:
  rabbitmq:
    image: rabbitmq:3.13-management
    ports: ["5672:5672", "15672:15672"]
    volumes:
      - /var/lib/rabbitmq:/var/lib/rabbitmq
      - /etc/vl/rabbitmq/definitions.json:/etc/rabbitmq/definitions.json:ro
    <<: *common

  cpu-worker:
    image: registry.internal/vl-camtek:latest
    command: >
      dramatiq clustplorer.logic.dispatch.actors
      --queues cpu.default cpu.pipeline cpu.indexer cpu.reindex
      --processes 1 --threads 1
    volumes:
      - /mnt/vl:/mnt/vl
      - /var/lib/vl/datasets-staging:/var/lib/vl/datasets-staging
    deploy:
      resources:
        limits: { cpus: "16", memory: "128g" }
    <<: *common

  gpu-worker:
    image: registry.internal/vl-camtek-gpu:latest
    command: >
      dramatiq clustplorer.logic.dispatch.actors
      --queues gpu.pipeline gpu.enrichment gpu.reindex
      --processes 1 --threads 1
    runtime: nvidia
    environment:
      - NVIDIA_VISIBLE_DEVICES=all
    volumes:
      - /mnt/vl:/mnt/vl
    <<: *common
```

Systemd unit that supervises the Compose project:

```ini
# /etc/systemd/system/vl-compose.service
[Unit]
Description=vl-camtek Docker Compose stack
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
RemainAfterExit=true
WorkingDirectory=/etc/vl
ExecStart=/usr/bin/docker compose up -d
ExecStop=/usr/bin/docker compose down

[Install]
WantedBy=multi-user.target
```

---

## Appendix C — Config/Env Mapping (K8s to On-Prem)

| K8s source | On-prem source | Key |
|---|---|---|
| `config` ConfigMap | `/etc/vl/config.env` | `PG_URI`, `OPENFGA_API_URL`, `CAMTEK_TRAIN_API_ENDPOINT`, feature flags |
| `k8s-pipeline-config` ConfigMap | `/etc/vl/pipeline.env` (loaded by worker units) | Embedder paths, pipeline-specific |
| `storage-key` Secret | `/etc/vl/secrets.env` (mode 0600, owner vl) | `S3_ACCESS_KEY`, `S3_SECRET_KEY` |
| `keycloak-admin` Secret | `/etc/vl/secrets.env` | Keycloak admin credentials |
| `longhorn-crypto-passphrase` Secret | LUKS keyfile at `/etc/vl/luks.key` (root-only), `crypttab` entry | Encryption |
| `VL_ARGO_PIPELINE_ENABLED` | Removed | N/A (no Argo) |
| `VL_ARGO_PIPELINE_STRUCTURE` | Removed | N/A (single-actor-per-pipe model) |
| `VL_K8S_PIPELINE_IMAGE`, `VL_GPU_K8S_PIPELINE_IMAGE` | Removed | Code runs in workers directly, no image |
| `VL_K8S_NAMESPACE` | Removed | N/A |
| `VL_K8S_NODE_AFFINITY_ENABLED`, `_TOLERATIONS_ENABLED` | Removed | Queue-binding replaces affinity |
| `ARGO_WORKFLOW_SERVICE_ACCOUNT` | Removed | N/A |
| *(new)* `RABBITMQ_URL` | `/etc/vl/config.env` | `amqp://vl:pass@rabbit:5672/vl` |
| *(new)* `DISPATCH_BACKEND` | `/etc/vl/config.env` | `dramatiq` (during P4), `argo` (pre-cutover), `dual` (P2/P3) |
| *(new)* `VL_DISPATCH_QUEUE_OVERRIDES` | `/etc/vl/config.env` | JSON map for runtime queue routing overrides |

---

*End of document.*
