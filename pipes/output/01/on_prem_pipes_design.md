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
11. [Appendix D — Per-Pipe File Changes & Code](#appendix-d--per-pipe-file-changes--code)
12. [Appendix E — Deployment Plan](#appendix-e--deployment-plan)
13. [Appendix F — VM Hardware Specification](#appendix-f--vm-hardware-specification)

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

## Appendix D — Per-Pipe File Changes & Code

This appendix enumerates, per pipe, the **exact files to create or modify** plus the **ready-to-paste code**. Paths are relative to the repo root (`c:/visual layer/vl-camtek/`). Code assumes the new package `clustplorer/logic/dispatch/` has been created (see D.0 below).

### D.0 — Shared scaffolding (create once, used by all pipes)

**Files to ADD:**

| Path | Purpose |
|---|---|
| `clustplorer/logic/dispatch/__init__.py` | Package root, exports `trigger_pipeline` |
| `clustplorer/logic/dispatch/broker.py` | RabbitMQ broker singleton |
| `clustplorer/logic/dispatch/actors.py` | All Dramatiq actor definitions |
| `clustplorer/logic/dispatch/middleware.py` | `on_success` / `on_failure` exit-handler middleware |
| `clustplorer/logic/dispatch/routing.py` | Queue + priority routing logic |
| `clustplorer/logic/dispatch/abort.py` | `dramatiq-abort` wrapper |

**Files to UPDATE:**

| Path | Change |
|---|---|
| `pyproject.toml` | add `dramatiq[rabbitmq,watch] ~= 1.17`, `dramatiq-abort ~= 1.2` |
| `vl/common/settings.py` | add `RABBITMQ_URL`, `DISPATCH_BACKEND`, `ABORT_BACKEND_URL` settings |

**`clustplorer/logic/dispatch/broker.py`:**

```python
"""Single broker instance used by all actors and the dispatcher."""
from dramatiq.brokers.rabbitmq import RabbitmqBroker
from dramatiq import set_broker
from dramatiq_abort import Abortable, backends

from vl.common.settings import Settings
from clustplorer.logic.dispatch.middleware import ExitHandlerMiddleware

_broker: RabbitmqBroker | None = None

def get_broker() -> RabbitmqBroker:
    global _broker
    if _broker is None:
        _broker = RabbitmqBroker(url=Settings.RABBITMQ_URL)
        abort_backend = backends.RedisBackend(url=Settings.ABORT_BACKEND_URL)
        _broker.add_middleware(Abortable(backend=abort_backend))
        _broker.add_middleware(ExitHandlerMiddleware())
        set_broker(_broker)
    return _broker
```

**`clustplorer/logic/dispatch/middleware.py`:**

```python
"""Dramatiq middleware replacing Argo onExit handlers."""
import dramatiq
from dramatiq.middleware import Middleware

from vl.common.logging_init import get_vl_logger

logger = get_vl_logger(__name__)

class ExitHandlerMiddleware(Middleware):
    """Maps to Argo's onExit template: dispatches post_success/post_error actors."""

    def after_process_message(self, broker, message, *, result=None, exception=None):
        # Lazy import to avoid circular dep with actors module
        from clustplorer.logic.dispatch.actors import run_post_success, run_post_error

        task_id = message.args[0] if message.args else None
        if not task_id:
            return

        if exception is None:
            run_post_success.send(str(task_id))
            logger.info(f"Enqueued post_success for task {task_id}")
        else:
            run_post_error.send(str(task_id), str(exception))
            logger.error(f"Enqueued post_error for task {task_id}: {exception}")
```

**`clustplorer/logic/dispatch/routing.py`:**

```python
"""Queue selection + priority calculation. Replaces resource auto-sizing."""
from typing import Any

# Mirrors argo_pipeline_creator._compute_cpu_resources tiers, but returns a priority
def priority_for_size(units: int) -> int:
    if units < 1000:     return 9
    if units < 10_000:   return 7
    if units < 50_000:   return 5
    if units < 100_000:  return 3
    return 1

def needs_gpu(enrichment_config: dict[str, Any] | None) -> bool:
    if not enrichment_config:
        return False
    gpu_models = {
        "CAPTION_IMAGES", "OBJECT_DETECTION", "IMAGE_TAGGING",
        "XFER", "MULTIMODEL_ENCODING", "INSTANCE_RETRIEVAL",
    }
    requested = set(enrichment_config.get("models", []) or [])
    return bool(requested & gpu_models)
```

**`clustplorer/logic/dispatch/abort.py`:**

```python
"""Replacement for subprocess kubectl delete workflow."""
from dramatiq_abort import abort

def abort_task_dispatch(message_id: str) -> None:
    """Request cancellation of an in-flight Dramatiq message."""
    abort(message_id)
```

**`clustplorer/logic/dispatch/__init__.py`:**

```python
from .broker import get_broker
from .routing import needs_gpu, priority_for_size
from .abort import abort_task_dispatch
from . import actors  # triggers actor registration

__all__ = ["trigger_pipeline", "abort_task_dispatch", "needs_gpu", "priority_for_size"]

def trigger_pipeline(
    task_id, dataset_id, user_id, flow_type, enrichment_config=None,
    size_units=0, extra_env=None,
):
    """Main entry point. Replaces ArgoPipeline.trigger_vl_argo_processing()."""
    get_broker()  # ensure initialised
    priority = priority_for_size(size_units)
    gpu = needs_gpu(enrichment_config)
    actor = actors.select_actor(flow_type, gpu)
    extra = extra_env or {}
    msg = actor.send_with_options(
        args=(str(task_id), str(dataset_id), str(user_id)),
        kwargs=extra,
        priority=priority,
    )
    return msg.message_id
```

### D.1 — `full_pipeline_flow`

**Files to ADD:** entries in `clustplorer/logic/dispatch/actors.py`

**Files to UPDATE:**

| Path | Change |
|---|---|
| `clustplorer/web/api_dataset_create_workflow.py` | Replace `ArgoPipeline.trigger_vl_argo_processing(...)` call with `dispatch.trigger_pipeline(...)` |
| `clustplorer/logic/argo_pipeline/argo_pipeline.py` | Route through `dispatch.trigger_pipeline` when `Settings.DISPATCH_BACKEND == "dramatiq"` |

**Actor code (append to `actors.py`):**

```python
import os
import dramatiq

from pipeline.controller.pipeline_flows import full_dataset_pipeline_flow
from vl.common.settings import Settings

def _set_env(task_id, dataset_id, user_id, flow_type, **kwargs):
    os.environ["FLOW_RUN_ID"] = str(task_id)
    os.environ["DATASET_ID"] = str(dataset_id)
    os.environ["USER_ID"] = str(user_id)
    os.environ["PIPELINE_FLOW_TYPE"] = flow_type
    for k, v in kwargs.items():
        os.environ[k.upper()] = str(v)

@dramatiq.actor(
    queue_name="cpu.pipeline",
    max_retries=3, min_backoff=30_000, max_backoff=600_000,
    time_limit=4 * 3600 * 1000,
)
def run_full_pipeline_cpu(task_id, dataset_id, user_id, **env):
    _set_env(task_id, dataset_id, user_id, "PIPELINE", **env)
    full_dataset_pipeline_flow()

@dramatiq.actor(
    queue_name="gpu.pipeline",
    max_retries=3, min_backoff=30_000, max_backoff=600_000,
    time_limit=6 * 3600 * 1000,
)
def run_full_pipeline_gpu(task_id, dataset_id, user_id, **env):
    _set_env(task_id, dataset_id, user_id, "PIPELINE", **env)
    full_dataset_pipeline_flow()
```

**API wiring update** in `api_dataset_create_workflow.py`:

```python
# Before:
# workflow_name = ArgoPipeline.trigger_vl_argo_processing(
#     dataset_id=dataset_id, user_id=user_id, task_id=task_id, ...)

# After:
from clustplorer.logic.dispatch import trigger_pipeline
message_id = trigger_pipeline(
    task_id=task_id,
    dataset_id=dataset_id,
    user_id=user_id,
    flow_type="PIPELINE",
    enrichment_config=enrichment_config,
    size_units=size_units,
)
# Persist message_id into tasks.metadata_ (replaces metadata_.workflow_name)
await repo.update_task_metadata(task_id, {"message_id": message_id})
```

### D.2 — `prepare_data_flow`

CPU sub-step. Only reachable when parent multi-step pipeline explicitly chains it. In the new design, multi-step chaining is done **inside a single actor** via direct Python calls, so `prepare_data_flow` does not need its own actor for the main dispatch path.

**Files to UPDATE:** none for direct triggering.

**Optional ADD** — if you want a standalone "prep only" debug actor:

```python
from pipeline.controller.pipeline_flows import prepare_data_flow

@dramatiq.actor(queue_name="cpu.default", max_retries=1, time_limit=2 * 3600 * 1000)
def run_prepare_data(task_id, dataset_id, user_id, **env):
    _set_env(task_id, dataset_id, user_id, env.get("pipeline_flow_type", "PIPELINE"), **env)
    prepare_data_flow()
```

### D.3 — `enrichment_flow`

**Files to ADD:** actor entry in `actors.py`

**Files to UPDATE:** `clustplorer/logic/datasets_bl.py` — `PipelineFlowType.ENRICHMENT` branch dispatches to new actor.

**Actor:**

```python
from pipeline.controller.pipeline_flows import enrichment_flow

@dramatiq.actor(
    queue_name="gpu.enrichment",
    max_retries=2, min_backoff=60_000, max_backoff=1_800_000,
    time_limit=4 * 3600 * 1000,
)
def run_enrichment(task_id, dataset_id, user_id, **env):
    _set_env(task_id, dataset_id, user_id, "ENRICHMENT", **env)
    enrichment_flow()
```

**Call-site update in `datasets_bl.py`:**

```python
# Replace ArgoPipeline.trigger_vl_argo_processing(flow_type=ENRICHMENT, ...)
from clustplorer.logic.dispatch import trigger_pipeline
message_id = trigger_pipeline(
    task_id=task_id, dataset_id=dataset_id, user_id=user_id,
    flow_type="ENRICHMENT", enrichment_config=enrichment_config,
    size_units=size_units,
)
```

### D.4 — `indexer_flow`

CPU. Like `prepare_data_flow`, internal to multi-step. No dedicated actor unless standalone run needed.

**Optional actor** (in `actors.py`):

```python
from pipeline.controller.pipeline_flows import indexer_flow

@dramatiq.actor(queue_name="cpu.indexer", max_retries=2, time_limit=3 * 3600 * 1000)
def run_indexer(task_id, dataset_id, user_id, **env):
    _set_env(task_id, dataset_id, user_id, env.get("pipeline_flow_type", "PIPELINE"), **env)
    indexer_flow()
```

### D.5 — `partial_update_flow`

**Files to ADD:** two actors (CPU + GPU variants).

**Files to UPDATE:**

| Path | Change |
|---|---|
| `clustplorer/web/api_add_media.py` | `_process_add_media` dispatches via `trigger_pipeline(flow_type="PARTIAL_UPDATE", ...)` |
| `clustplorer/logic/argo_pipeline/argo_pipeline.py` | Remove `create_combined_partial_update_reindex_workflow` branch once cut over |

**Actors:**

```python
from pipeline.controller.pipeline_flows import partial_update_flow

@dramatiq.actor(queue_name="cpu.pipeline", max_retries=3, time_limit=3 * 3600 * 1000)
def run_partial_update_cpu(task_id, dataset_id, user_id, **env):
    _set_env(task_id, dataset_id, user_id, "PARTIAL_UPDATE", **env)
    partial_update_flow()

@dramatiq.actor(queue_name="gpu.pipeline", max_retries=3, time_limit=5 * 3600 * 1000)
def run_partial_update_gpu(task_id, dataset_id, user_id, **env):
    _set_env(task_id, dataset_id, user_id, "PARTIAL_UPDATE", **env)
    partial_update_flow()
```

### D.6 — `reindex_dataset_flow`

**Files to ADD:** actor entries.

**Files to UPDATE:** `clustplorer/web/api_add_media.py` — `/reindex` endpoint calls `trigger_pipeline(flow_type="REINDEX", ...)`.

**Actors:**

```python
from pipeline.controller.pipeline_flows import reindex_dataset_flow

@dramatiq.actor(queue_name="cpu.reindex", max_retries=2, time_limit=4 * 3600 * 1000)
def run_reindex_cpu(task_id, dataset_id, user_id, **env):
    _set_env(task_id, dataset_id, user_id, "REINDEX", **env)
    reindex_dataset_flow()

@dramatiq.actor(queue_name="gpu.reindex", max_retries=2, time_limit=6 * 3600 * 1000)
def run_reindex_gpu(task_id, dataset_id, user_id, **env):
    _set_env(task_id, dataset_id, user_id, "REINDEX", **env)
    reindex_dataset_flow()
```

### D.7 — `restore_dataset_flow`

**Files to ADD:** actor entry.

**Files to UPDATE:** `clustplorer/web/api_dataset_snapshots.py` — `/restore` and `/clone` endpoints dispatch to new actor. Must pass `SNAPSHOT_DATASET_ID`, `SNAPSHOT_DATASET_REVISION_ID` via `extra_env`.

**Actor:**

```python
from pipeline.controller.pipeline_flows import restore_dataset_flow

@dramatiq.actor(queue_name="cpu.default", max_retries=2, time_limit=3600 * 1000)
def run_restore(task_id, dataset_id, user_id, snapshot_dataset_id, snapshot_revision_id, **env):
    _set_env(
        task_id, dataset_id, user_id, "RESTORE",
        snapshot_dataset_id=snapshot_dataset_id,
        snapshot_dataset_revision_id=snapshot_revision_id,
        **env,
    )
    restore_dataset_flow()
```

**Call-site:**

```python
from clustplorer.logic.dispatch import trigger_pipeline
message_id = trigger_pipeline(
    task_id=task_id, dataset_id=dataset_id, user_id=user_id,
    flow_type="RESTORE",
    extra_env={
        "snapshot_dataset_id": snapshot_dataset_id,
        "snapshot_revision_id": snapshot_revision_id,
    },
)
```

### D.8 — `nop_flow`

**Files to ADD:** actor entry (optional — helpful for smoke tests through the full stack).

```python
from pipeline.controller.pipeline_flows import nop_flow

@dramatiq.actor(queue_name="cpu.default", max_retries=0, time_limit=60_000)
def run_nop(task_id="smoke-test", dataset_id="n/a", user_id="n/a"):
    _set_env(task_id, dataset_id, user_id, "PIPELINE")
    nop_flow()
```

**Ops smoke-test recipe:** `python -c "from clustplorer.logic.dispatch.actors import run_nop; run_nop.send()"` — verifies broker + worker end-to-end.

### D.9 — `post_success_flow` and D.10 — `post_error_flow`

These are triggered **by middleware**, not by the dispatcher. Defined once in `actors.py`, invoked by `ExitHandlerMiddleware` (see D.0).

**Actors:**

```python
from pipeline.controller.pipeline_flows import post_success_flow, post_error_flow

@dramatiq.actor(queue_name="cpu.default", max_retries=1, time_limit=600_000)
def run_post_success(task_id):
    _set_env(task_id, os.environ.get("DATASET_ID", ""), "", "PIPELINE")
    post_success_flow()

@dramatiq.actor(queue_name="cpu.default", max_retries=1, time_limit=600_000)
def run_post_error(task_id, error_message):
    os.environ["ERROR_MESSAGE"] = error_message
    _set_env(task_id, os.environ.get("DATASET_ID", ""), "", "PIPELINE")
    post_error_flow()
```

### D.11 — `model_training_flow`

**Files to ADD:** `clustplorer/logic/dispatch/training_actor.py` (or add to `actors.py`).

**Files to UPDATE:**

| Path | Change |
|---|---|
| `clustplorer/web/api_dataset_model_training.py` | Replace `ModelTrainingArgoPipeline.trigger_model_training_argo_workflow(...)` with `trigger_pipeline(flow_type="MODEL_TRAINING", ...)` |
| `clustplorer/logic/model_training/model_training_argo_pipeline.py` | Deprecate; keep stub routing to dispatch during P2/P3 |
| `clustplorer/logic/model_training/model_training_argo_manager.py` | Remove in P4 |

**Actor:**

```python
from pipeline.controller.pipeline_flows import model_training_flow

@dramatiq.actor(
    queue_name="cpu.default",
    max_retries=3, min_backoff=60_000, max_backoff=900_000,
    time_limit=2 * 3600 * 1000,
)
def run_model_training(task_id, dataset_id, user_id, **env):
    _set_env(task_id, dataset_id, user_id, "MODEL_TRAINING", **env)
    model_training_flow()
```

### D.12 — Flywheel (bonus)

**Files to UPDATE:** `clustplorer/logic/flywheel/flywheel_runner_argo_manager.py` becomes a thin wrapper around a Dramatiq actor with self-enqueueing.

```python
from pipeline.controller.pipeline_flows import full_dataset_pipeline_flow  # or flywheel-specific entry
from clustplorer.logic.dispatch import trigger_pipeline

@dramatiq.actor(queue_name="cpu.default", max_retries=2, time_limit=4 * 3600 * 1000)
def run_flywheel_iteration(task_id, dataset_id, user_id, iteration=0, max_iterations=5, **env):
    _set_env(task_id, dataset_id, user_id, "PIPELINE", **env)
    # ... run one active-learning cycle ...
    if iteration + 1 < max_iterations and _should_continue(task_id):
        run_flywheel_iteration.send_with_options(
            args=(task_id, dataset_id, user_id),
            kwargs={"iteration": iteration + 1, "max_iterations": max_iterations, **env},
            delay=30_000,  # 30-s pause between iterations
        )
```

### D.13 — Actor selector

Added to `actors.py` after all actor definitions:

```python
_ACTOR_MAP = {
    ("PIPELINE",       False): run_full_pipeline_cpu,
    ("PIPELINE",       True):  run_full_pipeline_gpu,
    ("PARTIAL_UPDATE", False): run_partial_update_cpu,
    ("PARTIAL_UPDATE", True):  run_partial_update_gpu,
    ("REINDEX",        False): run_reindex_cpu,
    ("REINDEX",        True):  run_reindex_gpu,
    ("ENRICHMENT",     True):  run_enrichment,
    ("RESTORE",        False): run_restore,
    ("MODEL_TRAINING", False): run_model_training,
}

def select_actor(flow_type: str, gpu: bool):
    key = (flow_type, gpu)
    if key not in _ACTOR_MAP:
        # Fallback: flow_type exists for CPU even if GPU requested
        key = (flow_type, False)
    return _ACTOR_MAP[key]
```

### D.14 — Abort call-site update

**File to UPDATE:** `vl/tasks/dataset_creation/dataset_creation_task_service.py`

```python
# Before (lines ~237-261):
# def _terminate_argo_workflow(workflow_name: str) -> None:
#     subprocess.run(["kubectl", "delete", "workflow", workflow_name, ...])

# After:
from clustplorer.logic.dispatch import abort_task_dispatch

@staticmethod
def _terminate_dispatched_task(message_id: str) -> None:
    try:
        abort_task_dispatch(message_id)
        logger.info(f"Requested abort of dispatched message {message_id}")
    except Exception as e:
        raise TaskWorkflowTerminationError(f"Failed to abort {message_id}: {e}")
```

Update the call-site in `abort_task` to read `metadata_.message_id` instead of `metadata_.workflow_name`.

### D.15 — File-change summary table

| Pipe | Files to ADD | Files to UPDATE |
|---|---|---|
| D.0 scaffolding | `dispatch/__init__.py`, `dispatch/broker.py`, `dispatch/actors.py`, `dispatch/middleware.py`, `dispatch/routing.py`, `dispatch/abort.py` | `pyproject.toml`, `vl/common/settings.py` |
| D.1 full_pipeline | actors in `actors.py` | `clustplorer/web/api_dataset_create_workflow.py`, `clustplorer/logic/argo_pipeline/argo_pipeline.py` |
| D.2 prepare_data | optional actor | — |
| D.3 enrichment | actor | `clustplorer/logic/datasets_bl.py` |
| D.4 indexer | optional actor | — |
| D.5 partial_update | two actors | `clustplorer/web/api_add_media.py`, `argo_pipeline.py` |
| D.6 reindex | two actors | `clustplorer/web/api_add_media.py` |
| D.7 restore | actor | `clustplorer/web/api_dataset_snapshots.py` |
| D.8 nop | actor | — |
| D.9/10 post_success/error | two actors | wired via middleware automatically |
| D.11 model_training | actor | `clustplorer/web/api_dataset_model_training.py`, `model_training_argo_pipeline.py` |
| D.12 flywheel | actor | `clustplorer/logic/flywheel/flywheel_runner_argo_manager.py` |
| D.14 abort | — | `vl/tasks/dataset_creation/dataset_creation_task_service.py` |

**P4 deletions:**

- `clustplorer/logic/argo_pipeline/argo_pipeline_creator.py`
- `clustplorer/logic/argo_pipeline/argo_pipeline.py`
- `clustplorer/logic/common/hera_utils.py`
- `clustplorer/logic/model_training/model_training_argo_manager.py`
- `clustplorer/logic/flywheel/flywheel_runner_argo_manager.py`
- `pyproject.toml` — remove `hera`, `kubernetes` dependencies

---

## Appendix E — Deployment Plan

Step-by-step rollout from a greenfield on-prem site to serving traffic. Written for a platform engineer to execute; assumes Ansible control node exists.

### E.1 — Pre-flight checklist

- [ ] IP plan approved (edge/api/db/broker/worker/storage/monitor VLANs)
- [ ] DNS entries reserved (`vl.internal`, `rabbit.vl.internal`, `pg.vl.internal`, etc.)
- [ ] TLS cert available (corporate CA or Let's Encrypt via DNS-01)
- [ ] Base OS image hardened (Ubuntu 22.04 LTS or RHEL 9 recommended)
- [ ] NTP configured on all hosts (critical for PG replication + message TTLs)
- [ ] Internal PyPI mirror / wheel repository available
- [ ] Internal container registry available (if using Docker Compose variant)
- [ ] Firewall rules pre-approved (see E.8)

### E.2 — Stage 1: Infrastructure bring-up

```
Day 0 - Storage layer
  1. Provision storage VM (16 CPU / 64 GiB / 20 TB HDD + 2 TB NVMe for cache)
  2. Install ZFS or MD-RAID; create /mnt/vl/{models,duckdb,csv-exports,
     model-output,ground-truth,data}
  3. Install NFS server; export with sec=sys, no_root_squash for workers
  4. Install MinIO (single-node, TLS); create buckets vl-media, vl-snapshots
  5. Smoke test: mount NFS from a test VM, read/write 1 GiB

Day 0 - Database layer
  6. Provision db VMs (primary + standby)
  7. Install PostgreSQL 15, enable WAL archiving to NFS
  8. Run existing vldbmigration to create schema
  9. Install OpenFGA, point at PG; import model
 10. Install Keycloak in HA pair, point at PG

Day 1 - Broker layer
 11. Provision broker VM(s) - single for pilot, 3-node cluster for prod
 12. Install RabbitMQ with management + prometheus plugins
 13. Enable publisher-confirms, quorum queues for production queues
 14. Load rabbitmq_definitions.json (vhost /vl, exchanges, queues, policies)
 15. Create operator + application users; disable guest
 16. Smoke test: rabbitmqadmin publish/get on cpu.default
```

### E.3 — Stage 2: Application bring-up

```
Day 2 - Workers
 17. Provision cpu-worker VMs (start with 2)
 18. Install system deps (build-essential, ffmpeg, libpq, python3.10)
 19. Mount /mnt/vl via autofs
 20. Install application wheel: pip install vl_camtek==X.Y.Z
 21. Drop /etc/vl/config.env and /etc/vl/secrets.env from Vault/SOPS
 22. Install vl-cpu-worker@.service and vl-gpu-worker@.service units
 23. systemctl enable --now vl-cpu-worker@1
 24. Verify with: dramatiq-test-publish; journalctl -u vl-cpu-worker@1
 25. Provision gpu-worker VMs, install NVIDIA drivers + CUDA (match prod
     version pinned in GPU image)
 26. Verify GPU visible: nvidia-smi from vl user
 27. systemctl enable --now vl-gpu-worker@1

Day 3 - API
 28. Provision api VMs (3x for HA)
 29. Install wheel; same config files
 30. Install vl-api@.service; enable 3 instances per VM (ports 9901-9903)
 31. Smoke test /healthz endpoint locally

Day 3 - Edge
 32. Provision edge VMs (2x active/passive)
 33. Install nginx + keepalived
 34. Deploy vhosts: / -> FE static, /api -> api upstream, /image -> image-proxy
 35. Install TLS cert; redirect 80 -> 443
 36. Configure keepalived VRRP on shared VIP
 37. Smoke test curl https://vl.internal/api/v1/healthz
```

### E.4 — Stage 3: Monitoring & backups

```
Day 4 - Monitoring
 38. Provision monitor VM
 39. Install Prometheus, Grafana, Loki
 40. Deploy node_exporter on every VM
 41. Deploy rabbitmq_exporter, postgres_exporter, nvidia_gpu_exporter
 42. Import existing Grafana dashboards from git
 43. Wire Alertmanager -> Slack/PagerDuty
 44. Verify queue_depth panel populated

Day 4 - Backups
 45. Install pgBackRest on db primary; configure stanza
 46. Schedule full weekly + incremental daily + continuous WAL archive
 47. Install ZFS snapshot cron (hourly + daily rotation)
 48. Configure mc mirror for MinIO; test restore-from-snapshot
 49. Validate backups by restoring the full DB to a throwaway VM
```

### E.5 — Stage 4: Pilot traffic

```
Day 5
 50. Flip VL_DISPATCH_BACKEND__NOP_FLOW = dramatiq for staging tenant only
 51. Invoke nop_flow via smoke-test: expect task COMPLETED in <5 s
 52. Flip VL_DISPATCH_BACKEND__RESTORE = dramatiq for staging
 53. Run /restore on a small test snapshot - verify SAVING -> READY
 54. Let these two pipes run for 48 h under continuous monitoring
 55. Review metrics: queue wait, actor duration, error rate, memory usage
```

### E.6 — Stage 5: Progressive cutover

```
Day 7-14
 56. Flip INDEXER, PREPARE_DATA, ENRICHMENT, REINDEX (one per day, watch 24h)
 57. Flip PARTIAL_UPDATE
 58. Flip MODEL_TRAINING
 59. Flip FULL_PIPELINE last (most traffic, most risk)
 60. Watch for: duplicate-execution, abort failures, DLX buildup, GPU OOM

Day 15+
 61. Mark P3 complete when all pipes green for 7 consecutive days
 62. Start P4 in week 3: remove argo_pipeline/* code, remove Hera dep
 63. Decommission K8s cluster at day 30
```

### E.7 — Stage 6: Decommission (P4)

- Remove Argo code modules (see D.15 P4 deletions)
- Remove `kubernetes`, `hera` from `pyproject.toml`
- Remove `devops/visual-layer/`, `devops/dependants/argo-workflows/` from the repo (or keep in `deprecated/` for one release)
- Archive K8s cluster backups; shutdown control plane
- Repurpose K8s worker nodes as additional cpu-worker/gpu-worker VMs

### E.8 — Network / firewall matrix

| Source | Destination | Port | Protocol |
|---|---|---|---|
| edge | api | 9901-9903 | TCP |
| api | db (pg) | 5432 | TCP |
| api | broker | 5672 | AMQP |
| api | openfga | 8080 | TCP |
| api | keycloak | 8443 | HTTPS |
| workers | broker | 5672 | AMQP |
| workers | db (pg) | 5432 | TCP |
| workers | storage (NFS) | 2049 | TCP/UDP |
| workers | minio | 9000 | HTTPS |
| workers | external (Camtek training API) | 443 | HTTPS |
| monitor | all hosts | 9100 (node_exporter) | TCP |
| monitor | broker | 15692 (rabbitmq exporter) | TCP |
| monitor | db | 9187 (postgres exporter) | TCP |
| monitor | gpu-workers | 9835 (nvidia exporter) | TCP |
| operators | edge | 443 | HTTPS |
| operators | broker | 15672 (mgmt UI) | HTTPS |
| operators | monitor | 3000 (Grafana) | HTTPS |

### E.9 — Go-live criteria

A deployment is "production-ready" when ALL of the following hold for 7 consecutive days:

1. Nightly full_pipeline_flow smoke succeeds on a 10k-image dataset
2. Nightly enrichment_flow smoke succeeds on GPU pool
3. Zero messages stuck in DLX at morning check (or root-caused and retried)
4. All Prometheus alerts quiet (or intentionally acknowledged)
5. Backup restore drill succeeded in the past 30 days
6. p95 API latency < 500 ms
7. p95 queue wait on `cpu.pipeline` < 60 s during business hours
8. At least one planned rolling deploy executed with zero task loss

---

## Appendix F — VM Hardware Specification

Target: moderate-size Camtek deployment (~5 concurrent pipelines peak, ~50 dataset creations/day, max dataset ~100k images).

All VMs: Ubuntu 22.04 LTS or RHEL 9, ext4 or XFS on root, separate LVM volume for `/var/lib`, swap disabled on worker VMs (OOM-kill is preferable to swap thrashing during ML jobs).

### F.1 — edge VM (nginx)

| Attribute | Spec |
|---|---|
| Count | 2 (active/passive via keepalived VRRP) |
| vCPU | 4 |
| RAM | 8 GiB |
| Disk | 40 GiB SSD (OS + logs) |
| Network | 2x 1 Gbps (bonded) |
| GPU | none |
| Notes | Stateless; snapshots not needed |

### F.2 — api VM (FastAPI `clustplorer`)

| Attribute | Spec |
|---|---|
| Count | 3 |
| vCPU | 8 |
| RAM | 16 GiB |
| Disk | 80 GiB SSD |
| Network | 2x 10 Gbps |
| GPU | none |
| Notes | Stateless. Each VM runs 3 uvicorn instances (4 workers each) = 12 workers/VM, 36 total |

### F.3 — db VM (PostgreSQL primary + standby)

| Attribute | Spec |
|---|---|
| Count | 2 (primary + streaming standby) |
| vCPU | 16 |
| RAM | 64 GiB (shared_buffers = 16 GiB, effective_cache_size = 48 GiB) |
| Disk | 2 TiB NVMe for `$PGDATA`; 4 TiB HDD for WAL archive |
| Network | 2x 10 Gbps |
| GPU | none |
| Notes | Enable `hot_standby=on`, `max_wal_senders=4`, `wal_level=replica` |

### F.4 — broker VM (RabbitMQ)

| Attribute | Spec |
|---|---|
| Count | 3 (quorum queues require odd cluster size) |
| vCPU | 4 |
| RAM | 8 GiB (`vm_memory_high_watermark = 0.6`) |
| Disk | 200 GiB SSD (message persistence) |
| Network | 2x 10 Gbps |
| GPU | none |
| Notes | Enable management, prometheus, shovel plugins |

### F.5 — cpu-worker VM

Two tiers; stepped capacity to handle the resource-tier mapping from `argo_pipeline_creator._compute_cpu_resources`.

#### F.5.a — cpu-worker-standard (most pipelines)

| Attribute | Spec |
|---|---|
| Count | N >= 4 |
| vCPU | 16 |
| RAM | 64 GiB |
| Disk | 500 GiB NVMe for `/var/lib/vl/datasets-staging` + 50 GiB OS |
| Network | 2x 10 Gbps |
| GPU | none |
| Queues subscribed | `cpu.default`, `cpu.pipeline`, `cpu.indexer`, `cpu.reindex` |
| Notes | Handles datasets up to ~50k units. `prefetch_count=1` |

#### F.5.b — cpu-worker-large (handles >50k unit datasets)

| Attribute | Spec |
|---|---|
| Count | N >= 2 |
| vCPU | 32 |
| RAM | 128 GiB |
| Disk | 2 TiB NVMe staging + 50 GiB OS |
| Network | 2x 25 Gbps |
| GPU | none |
| Queues subscribed | `cpu.pipeline.large`, `cpu.reindex.large` |
| Notes | Sized for the top argo_pipeline resource tier (`>=100k` units, 16 CPU / 128 GiB in K8s) |

### F.6 — gpu-worker VM

#### F.6.a — gpu-worker-standard

| Attribute | Spec |
|---|---|
| Count | M >= 2 |
| vCPU | 8 |
| RAM | 32 GiB |
| Disk | 500 GiB NVMe |
| Network | 2x 10 Gbps |
| GPU | 1x NVIDIA L4 / T4 / A10 (24 GiB VRAM) |
| Queues subscribed | `gpu.enrichment`, `gpu.pipeline`, `gpu.reindex` |
| Notes | `nvidia-container-toolkit` if containerised; driver version pinned |

#### F.6.b — gpu-worker-xfer (model fine-tuning)

| Attribute | Spec |
|---|---|
| Count | 1 (initially) |
| vCPU | 32 |
| RAM | 128 GiB |
| Disk | 2 TiB NVMe |
| Network | 2x 25 Gbps |
| GPU | 1x NVIDIA A100 / H100 (40-80 GiB VRAM) |
| Queues subscribed | `gpu.pipeline.xfer` |
| Notes | Sized for XFER path (14 CPU / 96 GiB in K8s) |

### F.7 — storage VM (NFS + MinIO)

| Attribute | Spec |
|---|---|
| Count | 1 (can split NFS and MinIO into 2 VMs) |
| vCPU | 16 |
| RAM | 64 GiB (ZFS ARC cache) |
| Disk | 2 TiB NVMe (cache) + 20 TiB HDD (RAID-Z2 or hardware RAID-6) |
| Network | 2x 25 Gbps (critical — shared-storage bottleneck) |
| GPU | none |
| Notes | Exports: `/mnt/vl/models` (28+ GiB), `/mnt/vl/duckdb` (100+ GiB), `/mnt/vl/data` (1 TiB hot), `/mnt/vl/snapshots` (5+ TiB cold) |

### F.8 — monitor VM

| Attribute | Spec |
|---|---|
| Count | 1 |
| vCPU | 8 |
| RAM | 32 GiB |
| Disk | 1 TiB SSD (metrics + logs retention) |
| Network | 2x 10 Gbps |
| GPU | none |
| Notes | Prometheus, Grafana, Loki, Alertmanager, pgbackrest repo client |

### F.9 — Totals (minimum vs. production-grade)

| Profile | VMs | Total vCPU | Total RAM | Total storage |
|---|---|---|---|---|
| **Minimum (pilot)** | 1 edge, 1 api, 1 db, 1 broker, 2 cpu-worker-std, 1 gpu-worker-std, 1 storage, 1 monitor | 68 | 232 GiB | ~25 TiB |
| **Production** | 2 edge, 3 api, 2 db, 3 broker, 4 cpu-std + 2 cpu-large, 2 gpu-std + 1 gpu-xfer, 1 storage, 1 monitor | 240 | 800 GiB | ~40 TiB |

### F.10 — Scale-out notes

- **First scale signal = queue depth.** Add cpu-worker-standard VMs before any other tier.
- **Second scale signal = GPU queue depth.** Provision gpu-worker-standard VMs.
- **Third scale signal = DB contention.** Before scaling the primary, confirm connection-pool (pgbouncer) is healthy.
- **Storage scaling:** move from single NFS to Ceph/GlusterFS when aggregate read throughput exceeds ~2 GiB/s sustained.

---

*End of document.*
