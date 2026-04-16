# VL-Camtek On-Premises Pipeline Execution Design

**Version:** 1.0
**Date:** 2026-04-16
**Author:** Architecture Team
**Status:** Design Document — Ready for Engineering Review

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Current State Analysis](#2-current-state-analysis)
3. [On-Prem Execution Strategies Per Pipe](#3-on-prem-execution-strategies-per-pipe)
   - 3.1 [Strategy Overview](#31-strategy-overview)
   - 3.2 [Full Pipeline Flow](#32-full-pipeline-flow)
   - 3.3 [Enrichment Flow (GPU)](#33-enrichment-flow-gpu)
   - 3.4 [Indexer / Prepare Data Flows](#34-indexer--prepare-data-flows)
   - 3.5 [Partial Update Flow](#35-partial-update-flow)
   - 3.6 [Reindex Dataset Flow](#36-reindex-dataset-flow)
   - 3.7 [Restore Dataset Flow](#37-restore-dataset-flow)
   - 3.8 [Model Training Flow](#38-model-training-flow)
   - 3.9 [Flywheel Flow](#39-flywheel-flow)
   - 3.10 [Post-Success / Post-Error Flows](#310-post-success--post-error-flows)
   - 3.11 [Strategy Comparison Matrix](#311-strategy-comparison-matrix)
4. [Selected Architecture: Detailed HLD](#4-selected-architecture-detailed-hld)
   - 4.1 [Architecture Principles](#41-architecture-principles)
   - 4.2 [Component Inventory](#42-component-inventory)
   - 4.3 [Block Diagram](#43-block-diagram)
   - 4.4 [Process Manager Design](#44-process-manager-design)
   - 4.5 [Worker Pool Design](#45-worker-pool-design)
   - 4.6 [Communication Patterns](#46-communication-patterns)
   - 4.7 [Storage Architecture](#47-storage-architecture)
   - 4.8 [End-to-End Flow Diagrams](#48-end-to-end-flow-diagrams)
   - 4.9 [Sequence Diagrams](#49-sequence-diagrams)
   - 4.10 [Deployment Model](#410-deployment-model)
5. [Migration Plan](#5-migration-plan)
   - 5.1 [Migration Phases](#51-migration-phases)
   - 5.2 [Phase 0 — Foundation](#52-phase-0--foundation)
   - 5.3 [Phase 1 — Process Manager](#53-phase-1--process-manager)
   - 5.4 [Phase 2 — GPU Worker](#54-phase-2--gpu-worker)
   - 5.5 [Phase 3 — Hera Flows (Training, Flywheel)](#55-phase-3--hera-flows-training-flywheel)
   - 5.6 [Phase 4 — Full Cutover](#56-phase-4--full-cutover)
   - 5.7 [Code Changes Required](#57-code-changes-required)
   - 5.8 [Transitional Architecture](#58-transitional-architecture)
   - 5.9 [Data Migration](#59-data-migration)
   - 5.10 [Risks and Mitigation](#510-risks-and-mitigation)
   - 5.11 [Rollback Plan](#511-rollback-plan)
6. [Operational Design](#6-operational-design)
   - 6.1 [Deployment and Release Strategy](#61-deployment-and-release-strategy)
   - 6.2 [Monitoring and Logging](#62-monitoring-and-logging)
   - 6.3 [Error Handling and Retry Mechanisms](#63-error-handling-and-retry-mechanisms)
   - 6.4 [Scaling Strategy](#64-scaling-strategy)
   - 6.5 [Backup and Disaster Recovery](#65-backup-and-disaster-recovery)
7. [Appendices](#7-appendices)
   - A. [File Change Manifest](#a-file-change-manifest)
   - B. [Environment Variable Mapping](#b-environment-variable-mapping)
   - C. [Capacity Planning Reference](#c-capacity-planning-reference)

---

## 1. Executive Summary

This document presents a production-ready design for migrating VL-Camtek's pipeline execution from **Kubernetes + Argo Workflows** to a fully **on-premises deployment without Kubernetes or any managed cloud orchestration**.

### Current State

The platform runs 11 pipeline flows (+ Flywheel) orchestrated by Argo Workflows inside Kubernetes. Pipelines are dynamically submitted as Argo CRDs from the `clustplorer` FastAPI backend. Steps execute in CPU and GPU containers, sharing data via Kubernetes PVCs, and writing progress to PostgreSQL.

### Target State

Replace Argo Workflows and Kubernetes pod scheduling with:

- A **Process Manager** (systemd-managed Python service) that replaces the Argo Workflow Controller
- **Direct subprocess execution** of pipeline flows on bare-metal / VM workers
- **PostgreSQL-backed job queue** (extending the existing `task_queue` table) for work distribution
- **NFS shared filesystem** replacing Kubernetes PVCs
- **systemd** for process lifecycle, restart policies, and resource limits

### Why This Approach

The existing codebase already contains the key insight that makes this migration tractable: **pipelines are plain Python functions**, not Argo-specific constructs. The `pipeline/controller/controller.py` entry point accepts `--flow-to-run` and executes the flow as a sequential Python process. Argo is used only for:

1. Pod scheduling (replaced by Process Manager + systemd)
2. Resource limits (replaced by systemd cgroups)
3. Multi-step pod chaining (replaced by sequential subprocess calls)
4. Exit handlers (replaced by Process Manager try/finally)
5. Volume mounting (replaced by NFS mounts)

The pipeline code itself — `@controller_step` decorators, `@controller_flow`, status updates to PostgreSQL, the entire `vl/` business logic — **requires zero changes**.

---

## 2. Current State Analysis

### 2.1 Architecture Summary

```
┌──────────────┐      ┌─────────────┐      ┌──────────────────────┐
│   Frontend   │─────▶│ clustplorer  │─────▶│  Argo Workflow       │
│  (React/RTK) │      │  (FastAPI)   │      │  Controller (K8s)    │
└──────────────┘      └──────┬───────┘      └──────────┬───────────┘
                             │                         │
                      TasksTable INSERT         Pod scheduling
                      Manifest build            Volume mounting
                      CRD submission            Resource limits
                             │                         │
                             │              ┌──────────┴───────────┐
                             │              │                      │
                             │         CPU Pods              GPU Pods
                             │         (pipeline/            (pipeline/
                             │          controller)           preprocess)
                             │              │                      │
                             │              └──────────┬───────────┘
                             │                         │
                             ▼                         ▼
                      ┌──────────────┐         Shared PVCs
                      │  PostgreSQL  │         (/data, /models)
                      └──────────────┘
```

### 2.2 What Kubernetes Provides Today

| K8s Capability | How It's Used | Replacement Needed |
|---|---|---|
| **Pod scheduling** | Argo creates pods for each workflow step | Process Manager dispatches subprocesses |
| **Resource limits** | Per-pod CPU/memory from `WorkflowInfo._compute_cpu_resources()` | systemd `MemoryMax=` / `CPUQuota=` cgroups |
| **Node affinity** | `role=cpu-pipeline` / `role=gpu-pipeline` labels | Worker role assignment (CPU vs GPU machines) |
| **PVC (RWMany)** | `/data` shared between CPU→GPU→CPU pods | NFS mount (same path) |
| **PVC (RWO)** | `datasets-storage-pvc`, `duckdb-storage-pvc` | Local disk or NFS |
| **ConfigMap** | `config`, `k8s-pipeline-config` env injection | `.env` files or env var injection |
| **Secrets** | `storage-key`, `keycloak-admin` | Vault, SOPS, or filesystem secrets |
| **CRD submission** | `CustomObjectsApi.create_namespaced_custom_object()` | Process Manager API |
| **Exit handlers** | `onExit` → `post_success_flow` / `post_error_flow` | try/finally in Process Manager |
| **Health probes** | readinessProbe on clustplorer | systemd watchdog + health endpoint |
| **Service discovery** | ClusterIP Services | DNS / static config / Consul |
| **Ingress** | nginx ingress controller | nginx/Caddy reverse proxy |

### 2.3 What Stays Unchanged

These components are Kubernetes-agnostic and require **no migration work**:

- All pipeline step logic (`pipeline/controller/pipeline_steps.py`)
- All flow compositions (`pipeline/controller/pipeline_flows.py`)
- The `@controller_step` / `@controller_flow` decorators
- The entire `vl/` business logic layer
- The entire `vldbaccess/` database access layer
- PostgreSQL database (tasks, datasets, images, objects, etc.)
- The queue worker (`clustplorer/logic/queue_worker/worker.py`)
- The `task_queue` DAO (`vldbaccess/task_queue/dao.py`)
- OpenFGA authorization
- Keycloak authentication
- Camtek gRPC clients (`providers/camtek/`)
- Sentry error tracking
- All enrichment models and inference code
- Frontend (React/TypeScript)

---

## 3. On-Prem Execution Strategies Per Pipe

### 3.1 Strategy Overview

Four candidate strategies are evaluated. Not every strategy fits every pipe — the matrix below shows which apply.

| Strategy | Description | Best For |
|---|---|---|
| **A. Process Manager + Subprocess** | A long-running Python service polls `task_queue`, forks pipeline as subprocess, monitors lifecycle | All flows — primary strategy |
| **B. Celery + Redis** | Celery workers consume from Redis broker, execute pipeline flows as Celery tasks | High-throughput, many concurrent pipelines |
| **C. Prefect / Airflow** | Workflow orchestrator manages DAGs of pipeline steps | Complex multi-step DAGs with branching |
| **D. Cron + Script** | cron triggers periodic pipeline runs | Scheduled-only flows (cleanup, health) |

### 3.2 Full Pipeline Flow

**`full_pipeline_flow`** — End-to-end dataset creation (INIT → SETUP → ENRICHMENT → METADATA → PUBLISH)

#### Approach A: Process Manager + Subprocess (SELECTED)

The Process Manager receives a trigger from the FastAPI backend (via `task_queue` INSERT), claims the job, and forks:

```bash
python -m pipeline.controller.controller --flow-to-run full_pipeline_flow
```

with all required env vars (`DATASET_ID`, `FLOW_RUN_ID`, `SOURCE_URI`, etc.) passed to the subprocess environment.

For **multi-step** (CPU → GPU → CPU):
1. Process Manager runs `prepare_data_flow` subprocess on a CPU worker
2. On success, runs `enrichment_flow` subprocess on a GPU worker
3. On success, runs `indexer_flow` subprocess on a CPU worker
4. On failure at any step, runs `post_error_flow`
5. On success of all steps, runs `post_success_flow`

```
Process Manager (on management node)
    │
    ├── subprocess: prepare_data_flow     [CPU worker, cgroup-limited]
    │       └── writes to /data/pipeline/{flow_run_id}/
    │
    ├── subprocess: enrichment_flow       [GPU worker, via SSH or local]
    │       └── reads/writes /data/pipeline/{flow_run_id}/
    │
    ├── subprocess: indexer_flow          [CPU worker, cgroup-limited]
    │       └── reads /data/pipeline/{flow_run_id}/, writes to PostgreSQL
    │
    └── finally: post_success_flow OR post_error_flow
```

**Pros:**
- Minimal code changes — pipeline code runs identically
- Full control over process lifecycle (kill, pause, priority)
- systemd cgroups enforce resource limits without containers
- NFS shared directory replaces PVC seamlessly
- Exit handler logic is a simple try/finally
- No new infrastructure dependencies

**Cons:**
- Custom Process Manager must be built and maintained
- No built-in DAG visualization (must build or use logs)
- Subprocess error handling must be explicit

**Operational complexity:** Medium — one new service to maintain
**Scalability:** Horizontal (add more worker machines) + Vertical (cgroup limits)
**Fault tolerance:** Process Manager persists state in PostgreSQL; systemd restarts on crash
**Maintainability:** High — uses existing pipeline code as-is

#### Approach B: Celery + Redis

Define each flow as a Celery task. Multi-step flows become Celery chains:

```python
from celery import chain
chain(
    prepare_data_flow.s(dataset_id=..., flow_run_id=...),
    enrichment_flow.s(),
    indexer_flow.s(),
).apply_async()
```

**Pros:**
- Mature, battle-tested distributed task queue
- Built-in retry, rate limiting, monitoring (Flower)
- Horizontal scaling via worker processes
- Canvas API for chaining, grouping, chords

**Cons:**
- Introduces Redis dependency (new infrastructure)
- Celery workers must be configured for both CPU and GPU routing
- Pipeline steps are synchronous, long-running (minutes to hours) — Celery's strength is shorter tasks
- Celery worker memory management is tricky for 128GB workloads
- Serialization overhead for large payloads
- Two queue systems (existing `task_queue` + Celery/Redis) — conceptual overhead

**Operational complexity:** High — Redis HA, Celery worker management, Flower monitoring
**Scalability:** Good horizontal scaling, but long-running tasks underutilize workers
**Fault tolerance:** Redis persistence (AOF/RDB), Celery acks_late
**Maintainability:** Medium — well-documented but adds dependency surface

#### Approach C: Prefect

Define flows as Prefect flows with tasks:

```python
@prefect.flow
def full_pipeline():
    prepare_data_flow()
    enrichment_flow()
    indexer_flow()
```

**Pros:**
- DAG visualization out of the box
- Built-in retry, caching, logging
- Prefect Server (self-hosted) for orchestration UI
- Infrastructure blocks for resource management

**Cons:**
- Introduces Prefect Server + database + agent as new infrastructure
- Pipeline code would need to be wrapped in Prefect decorators (conflicts with existing `@controller_step`)
- Two decorator systems competing for control of status updates
- Overkill for the sequential nature of most flows (no branching DAGs)
- Prefect agents still need deployment infrastructure

**Operational complexity:** High — Prefect Server, agents, database
**Scalability:** Good, but adds complexity for what are mostly linear pipelines
**Fault tolerance:** Good built-in retry and state management
**Maintainability:** Low — decorator collision with existing system, significant refactoring

#### SELECTED: Approach A — Process Manager + Subprocess

**Justification:** The existing pipeline code is already a standalone Python entry point (`python -m pipeline.controller.controller`). It needs no Celery serialization, no Prefect decorators, no Redis — just a process that runs it with the right environment variables. The Process Manager is a thin wrapper (~500 lines) around `subprocess.Popen` + PostgreSQL state tracking, leveraging the existing `task_queue` table.

---

### 3.3 Enrichment Flow (GPU)

**`enrichment_flow`** — GPU-intensive ML inference (captioning, tagging, detection, embeddings)

#### Approach A: Process Manager + Local GPU Subprocess (SELECTED)

If the GPU is on the same machine as the Process Manager (or a dedicated GPU worker), the flow runs as a direct subprocess:

```bash
python3.10 -m pipeline.preprocess.job
```

with `PREPROCESS_SECTION=gpu` and `CUDA_VISIBLE_DEVICES` set appropriately.

For **remote GPU workers**, the Process Manager SSHs to the GPU machine:

```bash
ssh gpu-worker-01 "cd /opt/vl-camtek && \
  env DATASET_ID=... FLOW_RUN_ID=... PREPROCESS_SECTION=gpu \
  python3.10 -m pipeline.preprocess.job"
```

**Pros:**
- Direct GPU access without container overhead
- NVIDIA driver + CUDA managed by OS packages (simpler than K8s device plugin)
- `CUDA_VISIBLE_DEVICES` for GPU isolation between concurrent jobs
- Lower latency than container startup

**Cons:**
- GPU worker must have all Python dependencies installed natively
- Multiple concurrent GPU jobs need careful `CUDA_VISIBLE_DEVICES` partitioning
- SSH-based remote execution adds key management overhead

#### Approach B: Docker Containers (no orchestration)

Run the GPU pipeline in Docker containers without Kubernetes:

```bash
docker run --gpus '"device=0"' \
  -v /data/pipeline:/data \
  -v /opt/models:/models \
  --env-file /etc/vl/pipeline.env \
  vl-gpu-pipeline:latest \
  python3.10 -m pipeline.preprocess.job
```

**Pros:**
- Environment isolation (dependency conflicts avoided)
- Exact same container images as current K8s deployment
- `--gpus` flag for GPU passthrough (nvidia-container-toolkit)
- Reproducible builds

**Cons:**
- Docker daemon dependency
- Container startup overhead (~5-15 seconds per launch)
- nvidia-container-toolkit must be installed and configured
- Volume mounts must match NFS paths

#### SELECTED: Approach A for single-GPU setups, Approach B for multi-GPU / shared GPU machines

**Justification:** For most on-prem deployments, a dedicated GPU machine with native Python + CUDA is simpler and eliminates container overhead. For environments with multiple GPU cards or shared GPU machines, Docker with `--gpus` provides isolation.

---

### 3.4 Indexer / Prepare Data Flows

**`prepare_data_flow`** — CPU-only data preparation
**`indexer_flow`** — CPU-only DB writes + indexing

These are the CPU bookends of the multi-step chain. They run as subprocesses of the Process Manager, identical to how `full_pipeline_flow` runs in single-step mode.

#### Approach A: Process Manager Subprocess (SELECTED)

```bash
# Prepare
python -m pipeline.controller.controller --flow-to-run prepare_data_flow

# Index
python -m pipeline.controller.controller --flow-to-run indexer_flow
```

Resource limits via systemd-run:

```bash
systemd-run --scope -p MemoryMax=32G -p CPUQuota=800% \
  python -m pipeline.controller.controller --flow-to-run indexer_flow
```

#### Approach D: Cron-Based (Not Selected)

These flows are never triggered independently by users — they are internal steps of multi-step workflows. Cron scheduling makes no sense here.

#### SELECTED: Approach A

---

### 3.5 Partial Update Flow

**`partial_update_flow`** — Add media to existing dataset

Same as `full_pipeline_flow` but without the Issues Generator step. Can also use `create_combined_partial_update_reindex_workflow` which chains partial_update → reindex.

#### Approach A: Process Manager + Subprocess (SELECTED)

Identical to full pipeline. For the combined variant:

```
Process Manager:
    1. subprocess: partial_update_flow
    2. if auto_reindex: subprocess: reindex_dataset_flow
```

This sequential chaining replaces the Argo `create_combined_partial_update_reindex_workflow`.

#### Approach B: Celery Chain

```python
chain(partial_update.s(...), reindex.s(...)).apply_async()
```

Not selected — same rationale as Section 3.2.

#### SELECTED: Approach A

---

### 3.6 Reindex Dataset Flow

**`reindex_dataset_flow`** — Rebuild indexes over existing dataset (forced single-pod in current system)

#### Approach A: Process Manager + Subprocess (SELECTED)

Already forced single-step in the current codebase (`argo_pipeline_creator.py:122`), so this maps 1:1 to a single subprocess:

```bash
python -m pipeline.controller.controller --flow-to-run reindex_dataset_flow
```

#### Approach D: Cron-Based

Could be scheduled for periodic re-indexing. Viable as a secondary trigger mechanism but not a replacement for API-triggered reindexing.

#### SELECTED: Approach A (with optional cron trigger for scheduled re-indexes)

---

### 3.7 Restore Dataset Flow

**`restore_dataset_flow`** — Restore / clone from snapshot. DB-only, no ML. Lightest real pipe.

#### Approach A: Process Manager + Subprocess (SELECTED)

```bash
python -m pipeline.controller.controller --flow-to-run restore_dataset_flow
```

Lightweight enough to run on the management node itself.

#### Approach B: In-Process Execution

Since restore is DB-only and fast, it could run in-process within the FastAPI backend:

```python
# In the API handler, instead of queuing:
from pipeline.controller.controller import main
main(flow_to_run="restore_dataset_flow")
```

**Not selected** — violates separation of concerns and would block the API event loop.

#### SELECTED: Approach A

---

### 3.8 Model Training Flow

**`model_training_flow`** — Prepare data + trigger Camtek Training Service via gRPC

Currently uses **Hera SDK** (not raw manifest builders). Steps: snapshot → folders → mapping → CSV → metadata JSON → gRPC trigger.

#### Approach A: Process Manager + Subprocess (SELECTED)

The training flow is already a sequential Python pipeline. It runs as:

```bash
python -m pipeline.controller.controller --flow-to-run model_training_flow
```

The Camtek Training Service is an **external** gRPC endpoint — it remains unchanged. The pipeline only prepares data and calls `TrainService.StartTrain()`.

#### Approach C: Airflow DAG

Training workflows could benefit from Airflow's monitoring and retry UI. However:
- Only ~6 sequential steps, no branching
- Would require Airflow infrastructure (scheduler, webserver, metadata DB)
- Overkill for a linear pipeline

#### SELECTED: Approach A

---

### 3.9 Flywheel Flow

**Flywheel** — Active-learning loop combining dataset iteration + training. Currently uses Hera SDK.

#### Approach A: Process Manager + Loop Coordinator (SELECTED)

The Flywheel is a loop: prepare → train → evaluate → decide → repeat. The Process Manager runs each iteration as a subprocess sequence, with loop logic in the coordinator:

```
Process Manager Flywheel Coordinator:
    while not converged:
        subprocess: prepare_flywheel_data
        subprocess: model_training_flow
        subprocess: evaluate_model
        decision = check_convergence()
```

The coordinator persists loop state (iteration count, metrics) in the `tasks` table JSONB `metadata_` field — exactly as today.

#### SELECTED: Approach A

---

### 3.10 Post-Success / Post-Error Flows

**`post_success_flow`** — Cleanup temp files (Argo onExit handler)
**`post_error_flow`** — Error notifications + dataset status update (Argo onExit handler)

#### Approach A: Process Manager try/finally (SELECTED)

These are not independent pipes — they are exit handlers. In the Process Manager, they become:

```python
try:
    run_pipeline_subprocess(flow="full_pipeline_flow", ...)
    run_pipeline_subprocess(flow="post_success_flow", ...)
except Exception:
    run_pipeline_subprocess(flow="post_error_flow", ...)
```

No queue, no scheduling — just structured error handling.

#### SELECTED: Approach A (integrated into Process Manager lifecycle)

---

### 3.11 Strategy Comparison Matrix

| Criteria | A: Process Manager | B: Celery+Redis | C: Prefect/Airflow | D: Cron |
|---|---|---|---|---|
| **New infrastructure** | None (PostgreSQL already exists) | Redis + Flower | Prefect Server + DB + Agent | crontab only |
| **Code changes** | ~500 lines new (Process Manager) + ~200 lines modified (trigger path) | ~300 lines new (tasks) + ~500 lines modified + Redis config | ~800 lines refactored (decorator collision) | ~100 lines (scripts) |
| **Pipeline code changes** | **Zero** | Minor (Celery task wrappers) | Major (Prefect decorator conflict) | Zero |
| **Multi-step chaining** | Sequential subprocess calls | Celery canvas (chain) | DAG definition | N/A |
| **GPU support** | Direct subprocess + `CUDA_VISIBLE_DEVICES` | Celery GPU routing queues | Prefect infrastructure blocks | N/A |
| **Resource limits** | systemd cgroups | Celery `--max-memory-per-child` (limited) | Agent resource config | ulimit |
| **Monitoring** | Custom + Prometheus + logs | Flower + Prometheus | Built-in UI | Logs only |
| **Horizontal scaling** | Add workers + NFS mounts | Add Celery workers | Add agents | N/A |
| **Fault tolerance** | PostgreSQL state + systemd restart | Redis persistence + acks_late | Prefect state machine | None |
| **Operational complexity** | **Low-Medium** | **High** | **High** | **Very Low** |
| **Fit for VL-Camtek** | **Excellent** | Good | Poor (decorator conflict) | Poor (not event-driven) |

**Overall Selection: Strategy A — Process Manager + Subprocess** for all pipes.

---

## 4. Selected Architecture: Detailed HLD

### 4.1 Architecture Principles

1. **Preserve pipeline code unchanged** — The `pipeline/` module runs identically on-prem
2. **PostgreSQL as single source of truth** — Jobs, tasks, datasets, queue — all in one DB
3. **NFS as shared filesystem** — Replaces all K8s PVCs
4. **systemd for lifecycle** — Process management, restart, resource limits
5. **Minimal new code** — Extend existing patterns (task_queue, Settings) rather than introducing new frameworks
6. **Gradual migration** — Both systems can coexist during transition

### 4.2 Component Inventory

| Component | Type | Runs On | Purpose |
|---|---|---|---|
| **clustplorer** | FastAPI service | App Server | API backend, task creation, pipeline triggers |
| **clustplorer-fe** | React SPA | App Server (nginx) | Frontend |
| **Process Manager** | Python service (systemd) | Management Node | Claims jobs from queue, dispatches subprocess pipelines |
| **CPU Worker** | Python subprocess | CPU Worker Node(s) | Executes CPU pipeline flows |
| **GPU Worker** | Python subprocess | GPU Worker Node | Executes GPU pipeline flows |
| **Queue Worker** | Python async service | App Server | Existing `run_worker()` for lightweight queue tasks |
| **PostgreSQL** | Database | DB Server | All persistent state |
| **DuckDB** | Embedded DB | CPU Worker Node(s) | Analytics / exploration queries |
| **OpenFGA** | Authorization service | App Server | Fine-grained access control |
| **Keycloak** | Identity provider | App Server | OIDC authentication |
| **NFS Server** | File server | Storage Node | Shared pipeline data, models, datasets |
| **nginx** | Reverse proxy | App Server | Route /api, /, /image |
| **image-proxy** | Image server | App Server | Image serving for frontend |

### 4.3 Block Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                         ON-PREM NETWORK                             │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │                      APP SERVER (VM 1)                        │  │
│  │                                                               │  │
│  │  ┌──────────┐  ┌─────────────┐  ┌──────────┐  ┌───────────┐ │  │
│  │  │  nginx   │  │ clustplorer  │  │  Queue   │  │ Keycloak  │ │  │
│  │  │ (reverse │──│  (FastAPI    │  │  Worker  │  │ (OIDC)    │ │  │
│  │  │  proxy)  │  │   :9999)    │  │ (async)  │  │           │ │  │
│  │  └────┬─────┘  └──────┬──────┘  └──────────┘  └───────────┘ │  │
│  │       │               │                                       │  │
│  │  ┌────┴─────┐  ┌──────┴──────┐  ┌───────────┐               │  │
│  │  │ Frontend │  │  OpenFGA    │  │ image-    │               │  │
│  │  │ (React)  │  │ (AuthZ)    │  │ proxy     │               │  │
│  │  └──────────┘  └─────────────┘  └───────────┘               │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                              │                                      │
│                    API calls │ (task_queue INSERT)                   │
│                              ▼                                      │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │                   MANAGEMENT NODE (VM 2)                      │  │
│  │                                                               │  │
│  │  ┌─────────────────────────────────────────────────────────┐ │  │
│  │  │              PROCESS MANAGER (systemd)                   │ │  │
│  │  │                                                         │ │  │
│  │  │  ┌──────────┐  ┌───────────┐  ┌──────────────────────┐ │ │  │
│  │  │  │  Queue   │  │ Dispatcher│  │ Lifecycle Manager   │ │ │  │
│  │  │  │  Poller  │──│ (route to │──│ (track subprocesses, │ │ │  │
│  │  │  │ (SELECT  │  │  CPU/GPU  │  │  enforce limits,    │ │ │  │
│  │  │  │  FOR     │  │  worker)  │  │  run exit handlers) │ │ │  │
│  │  │  │  UPDATE  │  │           │  │                     │ │ │  │
│  │  │  │  SKIP    │  └───────────┘  └──────────────────────┘ │ │  │
│  │  │  │  LOCKED) │                                           │ │  │
│  │  │  └──────────┘                                           │ │  │
│  │  └─────────────────────────────────────────────────────────┘ │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                    │                        │                        │
│        subprocess  │               subprocess (SSH)                  │
│                    ▼                        ▼                        │
│  ┌────────────────────────┐  ┌────────────────────────────────┐    │
│  │   CPU WORKER NODE(S)   │  │      GPU WORKER NODE           │    │
│  │       (VM 3+)          │  │         (VM 4)                 │    │
│  │                        │  │                                │    │
│  │  python -m pipeline.   │  │  python3.10 -m pipeline.       │    │
│  │  controller.controller │  │  preprocess.job                │    │
│  │                        │  │                                │    │
│  │  Resources:            │  │  Resources:                    │    │
│  │  - Up to 16 CPU        │  │  - NVIDIA GPU(s)              │    │
│  │  - Up to 128GB RAM     │  │  - 14 CPU / 96GB RAM          │    │
│  │  - systemd cgroup      │  │  - CUDA 12.x + TensorRT       │    │
│  │    limits              │  │  - Model weights (~28GB)       │    │
│  └───────────┬────────────┘  └──────────────┬─────────────────┘    │
│              │                               │                      │
│              └───────────┬───────────────────┘                      │
│                          ▼                                          │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │                    NFS SERVER (VM 5)                           │  │
│  │                                                               │  │
│  │  /data/pipeline/{flow_run_id}/    ← per-execution workdir    │  │
│  │  /data/models/                    ← ML model weights (28GB)  │  │
│  │  /data/datasets/                  ← dataset staging           │  │
│  │  /data/duckdb/                    ← DuckDB files              │  │
│  │  /data/exports/                   ← CSV exports               │  │
│  │  /data/snapshots/                 ← dataset snapshots         │  │
│  │  /data/ground-truth/              ← ground-truth labels       │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                          │                                          │
│                          ▼                                          │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │                    DB SERVER (VM 6)                            │  │
│  │                                                               │  │
│  │  PostgreSQL 15+ (with pgvector extension)                     │  │
│  │  - datasets, images, objects, issues, clusters                │  │
│  │  - tasks, task_queue                                          │  │
│  │  - flow_run_settings                                          │  │
│  │  - embeddings (halfvec)                                       │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │              EXTERNAL: Camtek Services                        │  │
│  │  - Data Server (gRPC :5050)  — scan results                  │  │
│  │  - Training Service (gRPC)   — model training                │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### 4.4 Process Manager Design

The Process Manager is the central new component. It replaces Argo Workflow Controller.

#### Responsibilities

1. **Poll** the `pipeline_jobs` table (new, extends `task_queue` pattern) for pending pipeline work
2. **Dispatch** the correct flow as a subprocess on the appropriate worker (CPU or GPU)
3. **Monitor** subprocess health (stdout/stderr streaming, exit codes, timeout)
4. **Enforce** resource limits via systemd-run cgroups
5. **Chain** multi-step flows (prepare → enrich → index)
6. **Run exit handlers** (post_success_flow / post_error_flow)
7. **Update** task status in PostgreSQL on step transitions
8. **Handle abort** requests (SIGTERM → subprocess, with commit-phase protection)

#### Database Schema Extension

```sql
-- New table: pipeline_jobs (extends the task_queue pattern)
CREATE TABLE pipeline_jobs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id         UUID REFERENCES tasks(id),
    dataset_id      UUID NOT NULL,
    flow_type       VARCHAR(64) NOT NULL,  -- full_pipeline_flow, enrichment_flow, etc.
    pipeline_structure VARCHAR(16) NOT NULL DEFAULT 'automatic', -- single-step, multi-step, automatic
    status          VARCHAR(16) NOT NULL DEFAULT 'PENDING',
        -- PENDING, DISPATCHED, RUNNING, STEP_COMPLETE, COMPLETED, FAILED, ABORTED
    current_step    VARCHAR(64),           -- prepare_data, enrichment, indexer, etc.
    worker_id       VARCHAR(128),          -- hostname of executing worker
    pid             INTEGER,               -- OS process ID on worker
    env_json        JSONB NOT NULL,        -- all env vars for the pipeline
    resource_config JSONB,                 -- {cpu: "8", memory: "32Gi"}
    requires_gpu    BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    error_message   TEXT,
    retry_count     INTEGER DEFAULT 0,
    max_retries     INTEGER DEFAULT 2
);

CREATE INDEX idx_pipeline_jobs_status ON pipeline_jobs(status);
CREATE INDEX idx_pipeline_jobs_task ON pipeline_jobs(task_id);
```

#### Process Manager Pseudocode

```python
# process_manager/manager.py (new file, ~500 lines)

class PipelineProcessManager:
    """
    Replaces Argo Workflow Controller for on-prem execution.
    Runs as a systemd service on the management node.
    """

    def __init__(self, config: ProcessManagerConfig):
        self.config = config
        self.active_jobs: dict[UUID, subprocess.Popen] = {}
        self.db = PipelineJobsDAO()

    async def run(self):
        """Main loop — poll for jobs, dispatch, monitor."""
        while not self.shutdown_event.is_set():
            # 1. Claim next pending job
            job = await self.db.claim_next_job(
                worker_id=self.hostname,
                gpu_available=self.config.has_gpu,
            )
            if job is None:
                await asyncio.sleep(self.config.poll_interval)
                continue

            # 2. Dispatch
            asyncio.create_task(self._execute_job(job))

    async def _execute_job(self, job: PipelineJob):
        """Execute a pipeline job with lifecycle management."""
        try:
            if job.pipeline_structure == 'multi-step' and job.requires_gpu:
                await self._execute_multistep(job)
            else:
                await self._execute_single_step(job)

            # Success exit handler
            await self._run_exit_handler(job, "post_success_flow")
            await self.db.mark_completed(job.id)

        except Exception as e:
            # Error exit handler
            await self._run_exit_handler(job, "post_error_flow")
            await self.db.mark_failed(job.id, str(e))

    async def _execute_single_step(self, job: PipelineJob):
        """Run entire pipeline in one subprocess."""
        env = self._build_env(job)
        cmd = [
            "systemd-run", "--scope",
            f"-p", f"MemoryMax={job.resource_config.get('memory', '32G')}",
            f"-p", f"CPUQuota={int(job.resource_config.get('cpu', '8')) * 100}%",
            sys.executable, "-m", "pipeline.controller.controller",
            "--flow-to-run", job.flow_type,
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self.active_jobs[job.id] = proc
        await self.db.update_pid(job.id, proc.pid)
        returncode = await proc.wait()
        del self.active_jobs[job.id]
        if returncode != 0:
            stderr = await proc.stderr.read()
            raise PipelineExecutionError(f"Exit code {returncode}: {stderr.decode()}")

    async def _execute_multistep(self, job: PipelineJob):
        """Run CPU→GPU→CPU chain."""
        steps = [
            ("prepare_data_flow", False),   # CPU
            ("enrichment_flow", True),       # GPU
            ("indexer_flow", False),          # CPU
        ]
        for flow_name, needs_gpu in steps:
            await self.db.update_step(job.id, flow_name)
            if needs_gpu:
                await self._run_on_gpu_worker(job, flow_name)
            else:
                await self._run_subprocess(job, flow_name)

    async def _run_on_gpu_worker(self, job: PipelineJob, flow_name: str):
        """Execute on GPU worker via SSH or local subprocess."""
        if self.config.gpu_worker_host == "localhost":
            await self._run_subprocess(job, flow_name, gpu=True)
        else:
            await self._run_ssh_subprocess(
                host=self.config.gpu_worker_host,
                job=job, flow_name=flow_name,
            )

    async def handle_abort(self, job_id: UUID):
        """Abort a running pipeline (replaces kubectl delete workflow)."""
        proc = self.active_jobs.get(job_id)
        if proc:
            proc.send_signal(signal.SIGTERM)
            try:
                await asyncio.wait_for(proc.wait(), timeout=30)
            except asyncio.TimeoutError:
                proc.kill()
```

### 4.5 Worker Pool Design

#### Worker Types

| Worker Type | Hardware | Software | Role |
|---|---|---|---|
| **CPU Worker** | 16+ cores, 128GB RAM, SSD | Python 3.10, pipeline deps, NFS client | Runs `prepare_data_flow`, `indexer_flow`, `full_pipeline_flow` (single-step), `restore_dataset_flow`, `model_training_flow` |
| **GPU Worker** | 8+ cores, 96GB RAM, NVIDIA GPU (24GB+ VRAM) | Python 3.10, CUDA 12.x, TensorRT, PyTorch, NFS client | Runs `enrichment_flow`, XFER fine-tuning |
| **Management Node** | 4 cores, 16GB RAM | Process Manager, Python 3.10 | Job dispatch, monitoring, exit handlers |

#### Concurrency Model

```
Management Node
    └── Process Manager (1 instance, systemd)
            ├── Async event loop (poll + dispatch)
            ├── Active job tracker (dict[UUID, Popen])
            └── Configurable concurrency:
                  max_concurrent_cpu_jobs = 3  (per CPU worker)
                  max_concurrent_gpu_jobs = 1  (per GPU card)
```

The Process Manager tracks active jobs and enforces concurrency limits. If all slots are full, new jobs remain PENDING until a slot opens.

#### Worker Registration

Workers are statically configured (no dynamic discovery needed for on-prem):

```yaml
# /etc/vl/process_manager.yaml
workers:
  cpu:
    - host: cpu-worker-01
      max_concurrent: 3
      memory_gb: 128
      cpu_cores: 16
    - host: cpu-worker-02
      max_concurrent: 2
      memory_gb: 64
      cpu_cores: 8
  gpu:
    - host: gpu-worker-01
      max_concurrent: 1   # per GPU card
      gpu_count: 1
      gpu_memory_gb: 24
      memory_gb: 96
      cpu_cores: 14
```

### 4.6 Communication Patterns

```
┌──────────────────────────────────────────────────────────────┐
│                    COMMUNICATION MAP                          │
│                                                              │
│  Frontend ──HTTP──▶ nginx ──HTTP──▶ clustplorer (FastAPI)    │
│                                          │                   │
│                                   SQL INSERT                 │
│                                          ▼                   │
│                                   pipeline_jobs table        │
│                                          │                   │
│                                   SQL POLL (SELECT FOR       │
│                                   UPDATE SKIP LOCKED)        │
│                                          ▼                   │
│                                   Process Manager            │
│                                     │          │             │
│                            subprocess│    SSH + │subprocess   │
│                                     ▼          ▼             │
│                              CPU Worker    GPU Worker         │
│                                     │          │             │
│                              SQL (via│vldbaccess)             │
│                                     ▼          ▼             │
│                                   PostgreSQL                 │
│                                                              │
│  Pipeline ──NFS──▶ /data/pipeline/{flow_run_id}/             │
│  Steps         (Parquet, images, embeddings)                 │
│                                                              │
│  Pipeline ──gRPC──▶ Camtek Data Server                       │
│  Training ──gRPC──▶ Camtek Training Service                  │
│                                                              │
│  SYNC patterns:                                              │
│    • API → DB: synchronous (task creation)                   │
│    • DB → Process Manager: async poll (5s interval)          │
│    • Process Manager → Worker: subprocess (blocking)         │
│    • Worker → DB: synchronous (vldbaccess)                   │
│    • Worker → NFS: synchronous (filesystem I/O)              │
│    • Frontend → API: poll (task status, 3-5s interval)       │
└──────────────────────────────────────────────────────────────┘
```

### 4.7 Storage Architecture

#### NFS Mount Map (replaces K8s PVCs)

| K8s PVC | NFS Path | Mount On | Mode | Size |
|---|---|---|---|---|
| `backend-efs-pvc` | `/data/models` | All workers | ro | ~28 GB |
| `duckdb-storage-pvc` | `/data/duckdb` | CPU workers | rw | 100 GB |
| `datasets-storage-pvc` | `/data/datasets` | CPU workers | rw | 50 GB |
| `db-csv-exports-pvc` | `/data/exports` | CPU workers | rw | 10 GB |
| `model-storage-pvc` | `/data/trained-models` | CPU workers | rw | 10 GB |
| `ground-truth-pvc` | `/data/ground-truth` | CPU workers | rw | 10 GB |
| (pipeline workdir) | `/data/pipeline/{flow_run_id}` | All workers | rw | dynamic |

#### NFS Server Configuration

```bash
# /etc/exports (on NFS server)
/data/models         *(ro,sync,no_subtree_check,no_root_squash)
/data/duckdb         cpu-worker-*(rw,sync,no_subtree_check,no_root_squash)
/data/datasets       cpu-worker-*(rw,sync,no_subtree_check,no_root_squash)
/data/pipeline       *(rw,sync,no_subtree_check,no_root_squash)
/data/exports        cpu-worker-*(rw,sync,no_subtree_check,no_root_squash)
/data/trained-models cpu-worker-*(rw,sync,no_subtree_check,no_root_squash)
/data/ground-truth   cpu-worker-*(rw,sync,no_subtree_check,no_root_squash)
```

#### Worker fstab

```bash
# /etc/fstab (on each worker)
nfs-server:/data/models         /data/models         nfs4 ro,hard,intr 0 0
nfs-server:/data/pipeline       /data/pipeline       nfs4 rw,hard,intr 0 0
nfs-server:/data/duckdb         /data/duckdb         nfs4 rw,hard,intr 0 0
nfs-server:/data/datasets       /data/datasets       nfs4 rw,hard,intr 0 0
nfs-server:/data/exports        /data/exports        nfs4 rw,hard,intr 0 0
nfs-server:/data/trained-models /data/trained-models nfs4 rw,hard,intr 0 0
nfs-server:/data/ground-truth   /data/ground-truth   nfs4 rw,hard,intr 0 0
```

### 4.8 End-to-End Flow Diagrams

#### Flow 1: Dataset Creation (Single-Step)

```
User clicks "Process"
        │
        ▼
┌──────────────────┐
│ POST /dataset/   │
│ {id}/process     │
└────────┬─────────┘
         │
         ▼
┌──────────────────────────────────────────────┐
│ clustplorer API handler                       │
│                                              │
│  1. TasksTable INSERT (DATASET_CREATION)     │
│  2. pipeline_jobs INSERT:                    │
│     flow_type = "full_pipeline_flow"         │
│     pipeline_structure = "single-step"       │
│     env_json = {DATASET_ID, FLOW_RUN_ID,     │
│                 SOURCE_URI, USER_ID, ...}    │
│     requires_gpu = false                     │
│     resource_config = auto-calculated        │
│  3. Return task_id to frontend               │
└────────┬─────────────────────────────────────┘
         │
         │  (5 seconds later, poll cycle)
         ▼
┌──────────────────────────────────────────────┐
│ Process Manager                              │
│                                              │
│  1. SELECT ... FOR UPDATE SKIP LOCKED        │
│     FROM pipeline_jobs WHERE status=PENDING  │
│  2. Claim job → status = DISPATCHED          │
│  3. Choose CPU worker (round-robin / least   │
│     loaded)                                  │
│  4. Fork subprocess:                         │
│     systemd-run --scope                      │
│       -p MemoryMax=32G -p CPUQuota=800%      │
│       python -m pipeline.controller.         │
│       controller --flow-to-run               │
│       full_pipeline_flow                     │
│  5. Update job: status=RUNNING, pid=12345    │
└────────┬─────────────────────────────────────┘
         │
         ▼
┌──────────────────────────────────────────────┐
│ CPU Worker Subprocess                        │
│                                              │
│  step_start                                  │
│  step_local_init         → tasks: INDEXING 33%│
│  download_data                               │
│  step_split_data                             │
│  step_enrichment_data_prep → INDEXING 35%    │
│  step_enrichment           → INDEXING 50%    │
│  step_enrichment_consolidation → INDEXING 65%│
│  step_normalize                              │
│  step_fastdup              → INDEXING 50%    │
│  step_issues_generator                       │
│  step_exploration                            │
│  step_metadata                               │
│  step_sync_data_to_local   → SAVING         │
│  step_prepare_for_read     → SAVING         │
│  step_publish_media        → SAVING 50%     │
│  step_finalize_dataset_creation → READY 100%│
│  step_cleanup                                │
│                                              │
│  (Each step updates tasks table via          │
│   @controller_step decorator — unchanged)    │
└────────┬─────────────────────────────────────┘
         │
         │ exit code 0
         ▼
┌──────────────────────────────────────────────┐
│ Process Manager                              │
│                                              │
│  1. Run post_success_flow (cleanup)          │
│  2. Update pipeline_jobs: COMPLETED          │
│  3. Log completion + metrics                 │
└──────────────────────────────────────────────┘
```

#### Flow 2: Dataset Creation (Multi-Step with GPU)

```
Process Manager claims job (pipeline_structure=multi-step, requires_gpu=true)
        │
        ▼
┌──────────────────────────────────────────────────────────────┐
│ Phase 1: PREPARE DATA (CPU Worker)                           │
│                                                              │
│  systemd-run --scope -p MemoryMax=16G                        │
│    python -m pipeline.controller.controller                  │
│    --flow-to-run prepare_data_flow                           │
│                                                              │
│  Writes: /data/pipeline/{flow_run_id}/input/                 │
│          /data/pipeline/{flow_run_id}/snapshots/             │
│                                                              │
│  Exit code 0 → Process Manager advances to Phase 2          │
└────────┬─────────────────────────────────────────────────────┘
         │
         ▼
┌──────────────────────────────────────────────────────────────┐
│ Phase 2: ENRICHMENT (GPU Worker)                             │
│                                                              │
│  ssh gpu-worker-01 "                                         │
│    cd /opt/vl-camtek &&                                      │
│    CUDA_VISIBLE_DEVICES=0                                    │
│    PREPROCESS_SECTION=gpu                                    │
│    python3.10 -m pipeline.preprocess.job                     │
│  "                                                           │
│                                                              │
│  Reads:  /data/pipeline/{flow_run_id}/snapshots/             │
│  Writes: /data/pipeline/{flow_run_id}/snapshots/             │
│          atrain_features.dat, embeddings, captions, tags     │
│                                                              │
│  Exit code 0 → Process Manager advances to Phase 3          │
└────────┬─────────────────────────────────────────────────────┘
         │
         ▼
┌──────────────────────────────────────────────────────────────┐
│ Phase 3: INDEXER (CPU Worker)                                │
│                                                              │
│  systemd-run --scope -p MemoryMax=64G                        │
│    python -m pipeline.controller.controller                  │
│    --flow-to-run indexer_flow                                │
│                                                              │
│  Reads:  /data/pipeline/{flow_run_id}/snapshots/             │
│  Writes: PostgreSQL (images, objects, embeddings, clusters)  │
│          /data/duckdb/{dataset_id}/                           │
│                                                              │
│  Exit code 0 → Process Manager runs exit handler             │
└────────┬─────────────────────────────────────────────────────┘
         │
         ▼
┌──────────────────────────────────────────────────────────────┐
│ Exit handler: post_success_flow                              │
│  - Remove /data/pipeline/{flow_run_id}/                      │
│  - Update pipeline_jobs: COMPLETED                           │
└──────────────────────────────────────────────────────────────┘
```

#### Flow 3: Model Training

```
POST /api/v1/training
        │
        ▼
clustplorer → TrainingTask INSERT → pipeline_jobs INSERT
        │       (flow_type = "model_training_flow")
        │
        ▼ (poll)
Process Manager → subprocess on CPU Worker:
        │
        ▼
┌─────────────────────────────────────────┐
│ model_training_flow                      │
│                                         │
│  step_create_snapshot                   │
│      └── DuckDB: snapshot dataset       │
│  step_get_dataset_folders               │
│      └── Query folder structure         │
│  step_create_image_class_mapping        │
│      └── Map images → class labels      │
│  step_unite_db_csv                      │
│      └── Generate training CSV          │
│  step_unite_metadata_json               │
│      └── Create metadata JSON           │
│  step_trigger_training_api              │
│      └── gRPC: TrainService.StartTrain()│
│          → Camtek Training Service      │
└─────────────────────────────────────────┘
```

### 4.9 Sequence Diagrams

#### Sequence: API → Process Manager → Worker → DB

```
Frontend          clustplorer         PostgreSQL        Process Manager     CPU Worker
   │                  │                   │                   │                │
   │ POST /process    │                   │                   │                │
   │─────────────────▶│                   │                   │                │
   │                  │ INSERT tasks      │                   │                │
   │                  │──────────────────▶│                   │                │
   │                  │ INSERT            │                   │                │
   │                  │ pipeline_jobs     │                   │                │
   │                  │──────────────────▶│                   │                │
   │  202 {task_id}   │                   │                   │                │
   │◀─────────────────│                   │                   │                │
   │                  │                   │                   │                │
   │                  │                   │ SELECT...FOR      │                │
   │                  │                   │ UPDATE SKIP LOCKED│                │
   │                  │                   │◀──────────────────│                │
   │                  │                   │                   │                │
   │                  │                   │ claim job         │                │
   │                  │                   │──────────────────▶│                │
   │                  │                   │                   │                │
   │                  │                   │                   │ subprocess     │
   │                  │                   │                   │ fork           │
   │                  │                   │                   │───────────────▶│
   │                  │                   │                   │                │
   │                  │                   │ UPDATE tasks      │                │
   │                  │                   │ (progress 33%)    │                │
   │                  │                   │◀───────────────────────────────────│
   │                  │                   │                   │                │
   │ GET /tasks       │                   │                   │                │
   │─────────────────▶│                   │                   │                │
   │                  │ SELECT tasks      │                   │                │
   │                  │──────────────────▶│                   │                │
   │ {progress: 33%}  │                   │                   │                │
   │◀─────────────────│                   │                   │                │
   │                  │                   │                   │                │
   │  ... (polling continues) ...        │                   │                │
   │                  │                   │                   │                │
   │                  │                   │ UPDATE tasks      │                │
   │                  │                   │ (status=COMPLETED)│                │
   │                  │                   │◀───────────────────────────────────│
   │                  │                   │                   │                │
   │                  │                   │                   │ exit code 0    │
   │                  │                   │                   │◀───────────────│
   │                  │                   │                   │                │
   │                  │                   │ UPDATE            │                │
   │                  │                   │ pipeline_jobs     │                │
   │                  │                   │ (COMPLETED)       │                │
   │                  │                   │◀──────────────────│                │
```

#### Sequence: Abort Flow

```
Frontend          clustplorer         PostgreSQL        Process Manager     CPU Worker
   │                  │                   │                   │                │
   │ POST /tasks/     │                   │                   │                │
   │ {id}/abort       │                   │                   │                │
   │─────────────────▶│                   │                   │                │
   │                  │                   │                   │                │
   │                  │ Check current_step│                   │                │
   │                  │──────────────────▶│                   │                │
   │                  │                   │                   │                │
   │                  │ (not in commit    │                   │                │
   │                  │  phase)           │                   │                │
   │                  │                   │                   │                │
   │                  │ UPDATE            │                   │                │
   │                  │ pipeline_jobs     │                   │                │
   │                  │ status=ABORTING   │                   │                │
   │                  │──────────────────▶│                   │                │
   │                  │                   │                   │                │
   │  202 Accepted    │                   │ (next poll sees   │                │
   │◀─────────────────│                   │  ABORTING)        │                │
   │                  │                   │──────────────────▶│                │
   │                  │                   │                   │                │
   │                  │                   │                   │ SIGTERM        │
   │                  │                   │                   │───────────────▶│
   │                  │                   │                   │                │
   │                  │                   │                   │ (graceful      │
   │                  │                   │                   │  shutdown)     │
   │                  │                   │                   │◀───────────────│
   │                  │                   │                   │                │
   │                  │                   │ UPDATE tasks      │                │
   │                  │                   │ status=ABORTED    │                │
   │                  │                   │◀──────────────────│                │
```

### 4.10 Deployment Model

#### Option A: Bare-Metal / VMs (RECOMMENDED)

| Node | Type | Count | Hardware |
|---|---|---|---|
| App Server | VM | 1 | 8 CPU, 32GB RAM, 100GB SSD |
| Management Node | VM | 1 | 4 CPU, 16GB RAM, 50GB SSD |
| CPU Worker | Bare Metal / VM | 1-3 | 16 CPU, 128GB RAM, 500GB SSD |
| GPU Worker | Bare Metal | 1 | 14 CPU, 96GB RAM, NVIDIA GPU (24GB+), 500GB SSD |
| DB Server | VM | 1 | 8 CPU, 32GB RAM, 1TB NVMe (PostgreSQL) |
| NFS Server | VM / NAS | 1 | 4 CPU, 16GB RAM, 2TB HDD/SSD |

**Minimum viable** (single-node): All on one machine (32+ CPU, 128GB+ RAM, 1 GPU). Set `gpu_worker_host: localhost` in Process Manager config.

#### Option B: Consolidated (Smaller Deployments)

| Node | Colocation |
|---|---|
| **Node 1** | App Server + Management Node + CPU Worker |
| **Node 2** | GPU Worker + NFS Server |
| **Node 3** | DB Server |

Minimum 3 nodes. Node 2 must have NVIDIA GPU.

#### systemd Unit Files

```ini
# /etc/systemd/system/vl-clustplorer.service
[Unit]
Description=VL Clustplorer FastAPI Backend
After=network.target postgresql.service
Requires=postgresql.service

[Service]
Type=simple
User=vl-service
Group=vl-service
WorkingDirectory=/opt/vl-camtek
EnvironmentFile=/etc/vl/clustplorer.env
ExecStart=/opt/vl-camtek/.venv/bin/uvicorn clustplorer.web:app \
    --host 0.0.0.0 --port 9999 --workers 4
Restart=always
RestartSec=5
MemoryMax=8G
CPUQuota=400%

[Install]
WantedBy=multi-user.target
```

```ini
# /etc/systemd/system/vl-process-manager.service
[Unit]
Description=VL Pipeline Process Manager
After=network.target postgresql.service
Requires=postgresql.service

[Service]
Type=simple
User=vl-pipeline
Group=vl-pipeline
WorkingDirectory=/opt/vl-camtek
EnvironmentFile=/etc/vl/process_manager.env
ExecStart=/opt/vl-camtek/.venv/bin/python -m process_manager.manager
Restart=always
RestartSec=10
WatchdogSec=60

[Install]
WantedBy=multi-user.target
```

```ini
# /etc/systemd/system/vl-queue-worker.service
[Unit]
Description=VL Queue Worker
After=network.target postgresql.service

[Service]
Type=simple
User=vl-service
Group=vl-service
WorkingDirectory=/opt/vl-camtek
EnvironmentFile=/etc/vl/clustplorer.env
ExecStart=/opt/vl-camtek/.venv/bin/python -m clustplorer.logic.queue_worker
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

---

## 5. Migration Plan

### 5.1 Migration Phases

```
Phase 0          Phase 1            Phase 2           Phase 3          Phase 4
Foundation       Process Manager    GPU Worker         Hera Flows       Full Cutover
(2 weeks)        (3 weeks)          (2 weeks)          (2 weeks)        (1 week)
                                                                        
Infrastructure   Replace Argo for   Multi-step with    Training +       Remove K8s
setup, NFS,      single-step CPU    GPU enrichment     Flywheel         dependencies
DB migration,    flows              on GPU worker      on Process       entirely
env config                                             Manager
                                                                        
┌──────────┐    ┌──────────────┐   ┌──────────────┐  ┌────────────┐  ┌───────────┐
│ Both      │    │ Single-step  │   │ Multi-step   │  │ All flows  │  │ K8s       │
│ systems   │───▶│ on Process   │──▶│ CPU+GPU on   │─▶│ on Process │─▶│ removed   │
│ available │    │ Manager      │   │ Proc Manager │  │ Manager    │  │           │
└──────────┘    └──────────────┘   └──────────────┘  └────────────┘  └───────────┘
```

### 5.2 Phase 0 — Foundation (2 weeks)

**Goal:** Set up on-prem infrastructure so both systems can run in parallel.

#### Tasks

1. **Provision servers** (VMs or bare metal per Section 4.10)
2. **Install base OS packages** on all nodes:
   ```bash
   # All nodes
   apt-get install -y python3.10 python3.10-venv nfs-common postgresql-client

   # GPU Worker additionally
   apt-get install -y nvidia-driver-535 nvidia-cuda-toolkit
   # Verify: nvidia-smi
   ```
3. **Set up NFS server** and mount on all workers (per Section 4.7)
4. **Deploy PostgreSQL** (or reuse existing if accessible):
   ```bash
   # Install pgvector extension
   apt-get install -y postgresql-15-pgvector
   ```
5. **Run database migration** to add `pipeline_jobs` table:
   ```sql
   -- Migration file: vldbmigration/migrations/xxx_add_pipeline_jobs.sql
   CREATE TABLE pipeline_jobs ( ... );  -- Schema from Section 4.4
   ```
6. **Deploy clustplorer** as systemd service (per Section 4.10)
7. **Deploy frontend** via nginx
8. **Copy model weights** to NFS: `/data/models/` (~28GB)
9. **Deploy Keycloak + OpenFGA** (or connect to existing instances)
10. **Create `.env` files** mapping all ConfigMap values (Appendix B)
11. **Set `VL_K8S_PIPELINE_ENABLED=false`** to disable Argo submission path

#### Validation

- `GET /api/v1/health` returns 200
- Frontend loads and authenticates via Keycloak
- NFS mounts accessible from all workers: `ls /data/models/`
- PostgreSQL reachable from all workers: `psql $PG_URI -c "SELECT 1"`

### 5.3 Phase 1 — Process Manager (3 weeks)

**Goal:** Single-step CPU flows execute via Process Manager instead of Argo.

#### Tasks

1. **Implement Process Manager** (`process_manager/` module, ~500 lines):
   - `manager.py` — main loop, job claiming, dispatch
   - `dispatcher.py` — subprocess execution with systemd-run
   - `config.py` — YAML config loader
   - `dao.py` — `pipeline_jobs` table DAO

2. **Modify trigger path** in clustplorer:
   - Replace `ArgoPipeline.trigger_vl_argo_processing()` with `pipeline_jobs` INSERT
   - File: `clustplorer/logic/argo_pipeline/argo_pipeline.py`
   - Change: ~50 lines modified

3. **Modify abort path**:
   - Replace `subprocess.run(["kubectl", "delete", "workflow", ...])` with `pipeline_jobs` status update
   - File: `vl/tasks/dataset_creation/dataset_creation_task_service.py`
   - Change: ~20 lines modified

4. **Install pipeline dependencies** on CPU worker:
   ```bash
   cd /opt/vl-camtek
   python3.10 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

5. **Deploy Process Manager** as systemd service

6. **Test flows:**
   - `nop_flow` — smoke test
   - `restore_dataset_flow` — lightweight DB-only
   - `full_pipeline_flow` (single-step, no GPU enrichment)
   - `reindex_dataset_flow`

#### Validation

- Create a small dataset (< 1000 images) without enrichment
- Verify task status progresses from INITIALIZING → RUNNING → COMPLETED
- Verify dataset status reaches READY
- Verify `/data/pipeline/{flow_run_id}/` is cleaned up after success
- Test abort mid-flight
- Test retry after induced failure (kill -9 the worker process)

### 5.4 Phase 2 — GPU Worker (2 weeks)

**Goal:** Multi-step flows (CPU → GPU → CPU) execute via Process Manager.

#### Tasks

1. **Install GPU pipeline dependencies** on GPU worker:
   ```bash
   # CUDA, PyTorch, TensorRT, model weights
   pip install torch==2.5.1 torchvision==0.20.1
   pip install ultralytics transformers
   # etc. (from pipeline-gpu.Dockerfile requirements)
   ```

2. **Configure SSH access** from Management Node → GPU Worker:
   ```bash
   ssh-keygen -t ed25519 -f /home/vl-pipeline/.ssh/id_ed25519
   ssh-copy-id vl-pipeline@gpu-worker-01
   ```

3. **Extend Process Manager** with multi-step dispatch:
   - `_execute_multistep()` method
   - `_run_on_gpu_worker()` via SSH
   - GPU worker configuration in YAML

4. **Test enrichment flow** end-to-end:
   - Dataset with enrichment_config requesting GPU models
   - Verify embeddings generated
   - Verify multi-step chaining (prepare → enrich → index)

#### Validation

- Create dataset with caption + tagging enrichment
- Verify GPU utilization: `nvidia-smi` shows active process
- Verify embeddings in PostgreSQL (pgvector)
- Verify NFS handoff: CPU writes to `/data/pipeline/`, GPU reads it, CPU reads GPU output

### 5.5 Phase 3 — Hera Flows (Training, Flywheel) (2 weeks)

**Goal:** Training and Flywheel flows work without Hera SDK / Argo.

#### Tasks

1. **Implement model_training_flow dispatch** in Process Manager:
   - The flow is already a sequential Python pipeline — just dispatch as subprocess
   - Remove Hera SDK workflow wrapper (`model_training_argo_manager.py`)
   - Direct subprocess: `--flow-to-run model_training_flow`

2. **Implement Flywheel loop coordinator** in Process Manager:
   - Loop logic extracted from `flywheel_runner_argo_manager.py`
   - Sequential subprocess calls with convergence check

3. **Test Camtek gRPC connectivity** from CPU worker:
   - `CAMTEK_TRAIN_API_ENDPOINT` reachable
   - `DATA_SERVER_GRPC_ENDPOINT` reachable

#### Validation

- Trigger training from UI
- Verify CSV export to `/data/exports/`
- Verify gRPC call to Camtek Training Service succeeds
- Verify training task status updates in UI

### 5.6 Phase 4 — Full Cutover (1 week)

**Goal:** Remove all Kubernetes dependencies.

#### Tasks

1. **Remove Argo Workflow dependencies** from clustplorer:
   - Delete `clustplorer/logic/argo_pipeline/argo_pipeline_creator.py` (or guard behind feature flag)
   - Delete `clustplorer/logic/common/hera_utils.py` (or guard)
   - Remove `kubernetes` and `hera` from `requirements.txt`

2. **Remove K8s-specific Settings**:
   - `VL_K8S_PIPELINE_ENABLED` → always False (or remove)
   - `VL_ARGO_PIPELINE_ENABLED` → always False
   - `VL_K8S_NAMESPACE`, `ARGO_WORKFLOW_SERVICE_ACCOUNT` → unused

3. **Decommission Argo Workflows** Helm release

4. **Decommission Kubernetes cluster** (if solely used for VL-Camtek)

5. **Update Helm chart** or replace with Ansible/shell deploy scripts

#### Validation

- Full regression test: create dataset (small + large), add media, reindex, restore, train
- Abort + retry flows
- Verify no Kubernetes API calls in logs

### 5.7 Code Changes Required

| File | Change | Lines | Phase |
|---|---|---|---|
| **NEW: `process_manager/manager.py`** | Process Manager main loop | ~200 | 1 |
| **NEW: `process_manager/dispatcher.py`** | Subprocess dispatch + systemd-run | ~150 | 1 |
| **NEW: `process_manager/config.py`** | YAML config loader | ~50 | 1 |
| **NEW: `process_manager/dao.py`** | pipeline_jobs DAO | ~100 | 1 |
| **NEW: `vldbmigration/.../pipeline_jobs.sql`** | DB migration | ~30 | 0 |
| `clustplorer/logic/argo_pipeline/argo_pipeline.py` | Replace `trigger_vl_argo_processing()` with DB insert | ~50 modified | 1 |
| `vl/tasks/dataset_creation/dataset_creation_task_service.py` | Replace kubectl abort with DB status update | ~20 modified | 1 |
| `vl/tasks/*/..._task_service.py` | Same abort pattern change for each task type | ~60 modified | 1 |
| `clustplorer/logic/model_training/model_training_argo_manager.py` | Replace Hera workflow with pipeline_jobs insert | ~40 modified | 3 |
| `clustplorer/logic/flywheel/flywheel_runner_argo_manager.py` | Replace Hera workflow with pipeline_jobs insert | ~40 modified | 3 |
| `vl/common/settings.py` | Add Process Manager settings | ~10 added | 1 |

**Total:** ~500 lines new code, ~220 lines modified. **Zero changes to pipeline step logic.**

### 5.8 Transitional Architecture

During Phases 1-3, both systems coexist:

```
                    ┌──────────────────────┐
                    │     clustplorer      │
                    │                      │
                    │  if ON_PREM_MODE:    │
                    │    INSERT pipeline_  │──── Process Manager ── subprocess
                    │    jobs              │
                    │  else:               │
                    │    submit Argo CRD   │──── Argo Controller ── K8s pods
                    └──────────────────────┘
```

A feature flag `VL_ON_PREM_PIPELINE_ENABLED` controls which path is taken. This allows per-flow migration:

```python
# In argo_pipeline.py (transitional)
if Settings.VL_ON_PREM_PIPELINE_ENABLED:
    PipelineJobsDAO.create_job(...)  # New path
else:
    create_argo_workflow(...)         # Old path
```

### 5.9 Data Migration

| Data | Migration Strategy |
|---|---|
| **PostgreSQL data** | `pg_dump` / `pg_restore` if moving to new server. Zero-downtime option: streaming replication. |
| **Model weights** | `rsync` from K8s PVC to NFS: `rsync -av /k8s-pvc/models/ nfs-server:/data/models/` |
| **DuckDB files** | `rsync` from K8s PVC to NFS |
| **Dataset files** | `rsync` from S3/PVC to NFS (or keep S3 access if available) |
| **Snapshots** | Copy from K8s PVC to NFS |
| **In-flight pipelines** | Wait for completion before cutover. No in-flight migration — clean boundary. |

### 5.10 Risks and Mitigation

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| **NFS performance bottleneck** | Medium | High | Use NFS v4.1 with parallel NFS (pNFS). SSD-backed NFS server. Benchmark with `fio` before migration. Fallback: local SSD + rsync for large datasets. |
| **GPU driver incompatibility** | Low | High | Pin exact NVIDIA driver + CUDA versions to match current GPU Dockerfile. Test on identical hardware before migration. |
| **Python dependency conflicts** | Medium | Medium | Use exact `requirements.txt` from Dockerfiles. Isolated venvs per node type (CPU vs GPU). |
| **SSH connection failures** | Low | Medium | SSH KeepAlive + AutoSSH for long-running sessions. Fallback: Process Manager + GPU Worker on same node. |
| **Concurrent job resource contention** | Medium | Medium | systemd cgroups enforce per-job limits. Process Manager enforces `max_concurrent_jobs` per worker. |
| **Process Manager single point of failure** | Medium | High | systemd auto-restart (RestartSec=10). PostgreSQL-persisted state survives Process Manager restart. Standby Process Manager on second node (active-passive with DB lock). |
| **Large dataset (100k+ images) OOM** | Low | High | Resource tiers from `_compute_cpu_resources()` map directly to systemd cgroup MemoryMax. Validated with same thresholds. |

### 5.11 Rollback Plan

Each phase has an independent rollback:

| Phase | Rollback Action | Time to Rollback |
|---|---|---|
| Phase 0 | Revert `VL_K8S_PIPELINE_ENABLED=true`. All infra stays as-is on K8s. | < 1 minute (env var change) |
| Phase 1 | Set `VL_ON_PREM_PIPELINE_ENABLED=false`. Argo path resumes. | < 1 minute |
| Phase 2 | Same as Phase 1 — GPU flows fall back to Argo GPU pods. | < 1 minute |
| Phase 3 | Same — training/flywheel fall back to Hera SDK path. | < 1 minute |
| Phase 4 | Redeploy Argo Workflows Helm chart. Re-enable Argo settings. | ~30 minutes |

**Critical rule:** Do not decommission Kubernetes (Phase 4) until all flows have run successfully on-prem for at least 2 weeks in production.

---

## 6. Operational Design

### 6.1 Deployment and Release Strategy

#### Code Deployment

```bash
# Deployment script (Ansible or shell)
# Runs on all nodes

# 1. Pull latest code
cd /opt/vl-camtek
git pull origin main

# 2. Update dependencies
source .venv/bin/activate
pip install -r requirements.txt

# 3. Run database migrations
python -m vldbmigration.migrate

# 4. Restart services (rolling)
sudo systemctl restart vl-clustplorer
sudo systemctl restart vl-process-manager
sudo systemctl restart vl-queue-worker
```

#### Rolling Update Strategy

1. Stop Process Manager (wait for active jobs to complete or reach checkpoint)
2. Deploy new code to all nodes
3. Run DB migrations
4. Start Process Manager
5. Restart clustplorer (Uvicorn supports graceful reload)

#### Blue-Green (if needed)

Not recommended for initial deployment — the system is stateful (PostgreSQL). If needed, use PostgreSQL streaming replication for read-only green environment validation.

### 6.2 Monitoring and Logging

#### Logging Stack

```
┌──────────────┐     ┌────────────────┐     ┌──────────────┐
│ All Services │────▶│ journald       │────▶│ Promtail     │
│ (stdout/     │     │ (systemd)      │     │ (log shipper)│
│  stderr)     │     └────────────────┘     └──────┬───────┘
└──────────────┘                                    │
                                                    ▼
                                            ┌──────────────┐
                                            │    Loki       │
                                            │ (log storage) │
                                            └──────┬───────┘
                                                    │
                                                    ▼
                                            ┌──────────────┐
                                            │   Grafana     │
                                            │ (dashboards)  │
                                            └──────────────┘
```

**Alternative (simpler):** Direct journald + `journalctl` queries. No additional stack needed.

```bash
# View Process Manager logs
journalctl -u vl-process-manager -f

# View pipeline subprocess logs (tagged by flow_run_id)
journalctl -u vl-process-manager --grep="FLOW_RUN_ID=abc123"

# View clustplorer API logs
journalctl -u vl-clustplorer -f --since "1 hour ago"
```

#### Structured Logging

Existing logging (`vl/common/logging_init.py`) supports JSON format via `flat-logging.yaml` config. Enhance with:

```python
# Add correlation IDs to all pipeline log lines
logger.info("Step completed", extra={
    "flow_run_id": Settings.FLOW_RUN_ID,
    "dataset_id": Settings.DATASET_ID,
    "task_id": task_id,
    "step": step_name,
    "duration_seconds": elapsed,
})
```

#### Metrics (Prometheus)

Add a `/metrics` endpoint to both clustplorer and Process Manager:

```python
# Metrics to expose
pipeline_jobs_total          {flow_type, status}    # counter
pipeline_jobs_active         {flow_type, worker}    # gauge
pipeline_step_duration_seconds {step_name}          # histogram
pipeline_job_duration_seconds  {flow_type}          # histogram
worker_cpu_usage_percent     {worker}               # gauge
worker_memory_usage_bytes    {worker}               # gauge
gpu_utilization_percent      {worker}               # gauge (from nvidia-smi)
task_queue_depth             {queue_name}            # gauge
```

Scrape with Prometheus (self-hosted). Dashboard in Grafana.

#### Health Checks

```python
# Process Manager health endpoint (HTTP on management node)
GET /health → {
    "status": "healthy",
    "active_jobs": 2,
    "workers": {"cpu-01": "online", "gpu-01": "online"},
    "last_poll_at": "2026-04-16T10:30:05Z",
    "uptime_seconds": 86400
}
```

systemd watchdog (`WatchdogSec=60`) ensures the Process Manager is periodically pinging systemd. If it deadlocks, systemd restarts it.

#### Alerting Rules

| Alert | Condition | Severity |
|---|---|---|
| Process Manager Down | systemd unit inactive for > 2 min | Critical |
| Pipeline Job Stuck | pipeline_jobs.status = RUNNING AND started_at < NOW - 6h | Warning |
| Worker Unreachable | SSH connection fails 3 consecutive times | Critical |
| GPU OOM | nvidia-smi shows 95%+ memory, process killed | Warning |
| PostgreSQL Disk > 80% | df -h | Warning |
| NFS Latency > 50ms | NFS IOPS monitoring | Warning |
| Task Queue Depth > 50 | SELECT count(*) FROM task_queue WHERE status='PENDING' | Warning |

### 6.3 Error Handling and Retry Mechanisms

#### Layer 1: Pipeline Step Level (UNCHANGED)

The existing `@controller_step` decorator handles:
- Exception logging (`@log_exception_with_args`)
- Dataset status → FATAL_ERROR on unhandled exception
- Task status → FAILED
- Trace event recording

This works identically on-prem.

#### Layer 2: Process Manager Level (NEW)

```python
class ProcessManager:
    async def _execute_job(self, job: PipelineJob):
        try:
            await self._run_pipeline(job)
            await self._run_exit_handler(job, "post_success_flow")
            await self.db.mark_completed(job.id)
        except PipelineExecutionError as e:
            if job.retry_count < job.max_retries:
                await self.db.mark_for_retry(job.id, str(e))
                # Job goes back to PENDING with retry_count++
                # Next poll cycle will re-claim it
            else:
                await self._run_exit_handler(job, "post_error_flow")
                await self.db.mark_failed(job.id, str(e))
        except Exception as e:
            # Unexpected error — fail immediately
            await self.db.mark_failed(job.id, f"Unexpected: {e}")
```

#### Layer 3: Worker Crash Recovery

If a worker process dies (OOM, hardware failure):

1. Process Manager's `proc.wait()` returns non-zero exit code
2. Pipeline step's `@controller_step` may have already set task to FAILED
3. Process Manager marks `pipeline_jobs` row as FAILED
4. If Process Manager itself crashes, systemd restarts it
5. On restart, Process Manager scans for `RUNNING` jobs with no live process → marks them FAILED

#### Layer 4: Stale Job Recovery

```sql
-- Run periodically (every 5 minutes) by Process Manager
UPDATE pipeline_jobs
SET status = 'FAILED',
    error_message = 'Stale job: no heartbeat for 10 minutes'
WHERE status = 'RUNNING'
  AND started_at < NOW() - INTERVAL '10 minutes'
  AND id NOT IN (SELECT job_id FROM active_heartbeats);
```

### 6.4 Scaling Strategy

#### Vertical Scaling

- **CPU Worker:** Add RAM/CPU to handle larger datasets. systemd cgroups enforce per-job limits.
- **GPU Worker:** Upgrade GPU (e.g., A100 40GB → A100 80GB). Multiple GPU cards with `CUDA_VISIBLE_DEVICES` isolation.
- **PostgreSQL:** Add RAM for larger shared_buffers, NVMe for I/O.

#### Horizontal Scaling

```
Current (single worker per type):

  Process Manager ──▶ CPU Worker 01 ──▶ NFS
                  └──▶ GPU Worker 01

Scaled (multiple workers):

  Process Manager ──▶ CPU Worker 01 ──▶ NFS
                  ├──▶ CPU Worker 02 ──▶ NFS
                  ├──▶ CPU Worker 03 ──▶ NFS
                  ├──▶ GPU Worker 01
                  └──▶ GPU Worker 02
```

Adding a CPU worker:
1. Provision VM with Python + NFS mounts
2. Add to `process_manager.yaml` workers list
3. Restart Process Manager (or hot-reload config)

Adding a GPU worker:
1. Provision bare metal with NVIDIA GPU + drivers + CUDA + Python
2. Copy SSH keys
3. Add to `process_manager.yaml`
4. Restart Process Manager

#### Process Manager HA

For high availability, run two Process Manager instances:

```
Process Manager A (active)  ──▶ Claims jobs via SELECT FOR UPDATE SKIP LOCKED
Process Manager B (standby) ──▶ Also polls, but A claims first (SKIP LOCKED)
```

`SELECT FOR UPDATE SKIP LOCKED` ensures only one manager processes each job. Both can be active simultaneously — PostgreSQL handles contention.

### 6.5 Backup and Disaster Recovery

#### PostgreSQL

```bash
# Daily full backup
pg_dump -Fc $PG_URI > /backup/pg/vl-camtek-$(date +%Y%m%d).dump

# Continuous WAL archiving (point-in-time recovery)
# postgresql.conf:
archive_mode = on
archive_command = 'cp %p /backup/pg/wal/%f'
```

**RPO:** < 5 minutes (WAL archiving)
**RTO:** < 30 minutes (restore from dump + replay WAL)

#### NFS Data

```bash
# Daily incremental backup of critical data
rsync -avz --delete /data/models/ /backup/nfs/models/
rsync -avz --delete /data/duckdb/ /backup/nfs/duckdb/
rsync -avz --delete /data/snapshots/ /backup/nfs/snapshots/

# Pipeline workdirs are ephemeral — no backup needed
# /data/pipeline/{flow_run_id}/ is cleaned up after completion
```

#### Configuration

```bash
# All config files in version control
/etc/vl/clustplorer.env
/etc/vl/process_manager.env
/etc/vl/process_manager.yaml
/etc/systemd/system/vl-*.service

# Backed up via Ansible playbook or git repo
```

#### Disaster Recovery Procedure

| Scenario | Recovery |
|---|---|
| **Single worker failure** | Process Manager detects via subprocess exit. Job marked FAILED, user retries. New worker provisioned. |
| **NFS server failure** | All pipeline jobs stall (NFS hard mount). Restore from backup to new NFS server. Update fstab. Resume. |
| **PostgreSQL failure** | Restore from pg_dump + WAL. RPO < 5 min. All services reconnect automatically (connection retry). |
| **Management Node failure** | systemd restarts Process Manager. If node is dead, start Process Manager on standby node. Jobs in RUNNING state recovered via stale-job detection. |
| **Complete site failure** | Restore PostgreSQL from offsite backup. Rsync NFS data from offsite. Reprovision nodes. Deploy code. ~4-8 hours RTO. |

---

## 7. Appendices

### A. File Change Manifest

```
NEW FILES:
  process_manager/
  ├── __init__.py
  ├── __main__.py          # Entry point
  ├── manager.py           # Main event loop (~200 lines)
  ├── dispatcher.py        # Subprocess execution (~150 lines)
  ├── config.py            # YAML config loader (~50 lines)
  ├── dao.py               # pipeline_jobs DAO (~100 lines)
  └── health.py            # Health check HTTP endpoint (~50 lines)

  vldbmigration/migrations/
  └── NNN_add_pipeline_jobs.sql  (~30 lines)

  deploy/
  ├── systemd/
  │   ├── vl-clustplorer.service
  │   ├── vl-process-manager.service
  │   ├── vl-queue-worker.service
  │   └── vl-frontend.service
  ├── nginx/
  │   └── vl-camtek.conf
  └── env/
      ├── clustplorer.env.template
      └── process_manager.env.template

MODIFIED FILES:
  clustplorer/logic/argo_pipeline/argo_pipeline.py
    → trigger_vl_argo_processing() → INSERT pipeline_jobs

  vl/tasks/dataset_creation/dataset_creation_task_service.py
    → _pre_abort(): subprocess.run(["kubectl"...]) → UPDATE pipeline_jobs

  vl/tasks/media_addition/media_addition_task_service.py
    → Same abort pattern change

  clustplorer/logic/model_training/model_training_argo_manager.py
    → Replace Hera workflow with pipeline_jobs INSERT

  clustplorer/logic/flywheel/flywheel_runner_argo_manager.py
    → Replace Hera workflow with pipeline_jobs INSERT

  vl/common/settings.py
    → Add VL_ON_PREM_PIPELINE_ENABLED, PROCESS_MANAGER_* settings

DELETED FILES (Phase 4 only):
  clustplorer/logic/argo_pipeline/argo_pipeline_creator.py  (or feature-gated)
  clustplorer/logic/common/hera_utils.py                    (or feature-gated)
```

### B. Environment Variable Mapping

**K8s ConfigMap `config` → `/etc/vl/clustplorer.env`**

| K8s ConfigMap Key | .env Key | Notes |
|---|---|---|
| `PG_URI` | `PG_URI` | Same |
| `OPENFGA_API_URL` | `OPENFGA_API_URL` | Same |
| `VL_ARGO_PIPELINE_ENABLED` | `VL_ARGO_PIPELINE_ENABLED=false` | Disabled |
| `VL_K8S_PIPELINE_ENABLED` | `VL_K8S_PIPELINE_ENABLED=false` | Disabled |
| `VL_ON_PREM_PIPELINE_ENABLED` | `VL_ON_PREM_PIPELINE_ENABLED=true` | NEW |
| `DATA_SERVER_GRPC_ENDPOINT` | `DATA_SERVER_GRPC_ENDPOINT` | Same |
| `CAMTEK_TRAIN_API_ENDPOINT` | `CAMTEK_TRAIN_API_ENDPOINT` | Same |
| `FLYWHEEL_ENABLED` | `FLYWHEEL_ENABLED` | Same |
| `TRAIN_MODEL_ENABLED` | `TRAIN_MODEL_ENABLED` | Same |
| `DUCKDB_EXPLORATION_ENABLED` | `DUCKDB_EXPLORATION_ENABLED` | Same |
| `S3_BUCKET` | `S3_BUCKET` | Or use local path |
| `VL_HOME` | `VL_HOME=/opt/vl-camtek/.vl` | Same |
| `LOG_LEVEL` | `LOG_LEVEL` | Same |
| `SENTRY_DSN` | `SENTRY_DSN` | Optional |

**K8s ConfigMap `k8s-pipeline-config` → `/etc/vl/pipeline.env`** (passed to subprocess)

| Key | Value | Notes |
|---|---|---|
| `PIPELINE_ROOT` | `/data/pipeline` | NFS mount |
| `VL_MODEL_PATH` | `/data/models` | NFS mount (ro) |
| `DUCKDB_STORAGE_PATH` | `/data/duckdb` | NFS mount |
| `DATASET_SOURCE_DIR` | `/data/datasets` | NFS mount |
| `DB_CSV_EXPORT_DIR` | `/data/exports` | NFS mount |
| `MODEL_STORAGE_DIR` | `/data/trained-models` | NFS mount |
| `GROUND_TRUTH_DIR` | `/data/ground-truth` | NFS mount |

**Process Manager config → `/etc/vl/process_manager.yaml`**

```yaml
poll_interval_seconds: 5
max_concurrent_cpu_jobs: 3
max_concurrent_gpu_jobs: 1
stale_job_timeout_seconds: 600
gpu_worker_host: gpu-worker-01   # or "localhost" for single-node
gpu_worker_user: vl-pipeline
ssh_key_path: /home/vl-pipeline/.ssh/id_ed25519

workers:
  cpu:
    - host: localhost
      max_concurrent: 3
  gpu:
    - host: gpu-worker-01
      max_concurrent: 1

resource_defaults:
  cpu:
    memory_max: "32G"
    cpu_quota: "800%"
  gpu:
    memory_max: "96G"
    cpu_quota: "1400%"
```

### C. Capacity Planning Reference

#### Per-Pipeline Resource Requirements (from `_compute_cpu_resources()`)

| Dataset Size (units) | CPU Cores | Memory | Disk (est.) | Duration (est.) |
|---|---|---|---|---|
| < 1,000 | 3 | 6 GB | 10 GB | 5-15 min |
| 1,000 - 5,000 | 4 | 8 GB | 25 GB | 15-45 min |
| 5,000 - 10,000 | 8 | 16 GB | 50 GB | 30-90 min |
| 10,000 - 50,000 | 8 | 32 GB | 100 GB | 1-3 hours |
| 50,000 - 100,000 | 16 | 64 GB | 200 GB | 3-6 hours |
| > 100,000 | 16 | 128 GB | 500 GB | 6-12 hours |

**Units** = `n_images + n_objects + (n_videos * 80)`

#### GPU Requirements

| Mode | CPU | Memory | GPU VRAM | Use Case |
|---|---|---|---|---|
| Standard enrichment | 3 | 14 GB | 24 GB | Captioning, tagging, detection, embeddings |
| XFER fine-tuning | 14 | 96 GB | 24-40 GB | Transfer learning, custom embeddings |

#### Storage Sizing

| Path | Size | Growth Rate | Retention |
|---|---|---|---|
| `/data/models` | 28 GB | Slow (new model releases) | Permanent |
| `/data/pipeline` | 0-500 GB | Ephemeral (cleaned after each pipeline) | None (auto-cleanup) |
| `/data/duckdb` | 100 GB base | ~1 GB per dataset | Permanent |
| `/data/datasets` | 50 GB base | ~500 MB per dataset | Permanent |
| PostgreSQL | 50 GB base | ~100 MB per dataset (with embeddings) | Permanent |

#### Concurrent Pipeline Capacity

| Node Configuration | Max Concurrent Pipelines | Max Dataset Size |
|---|---|---|
| Single node (32 CPU, 128 GB) | 1 large or 3 small | 100k+ units |
| 2 CPU workers (16 CPU, 128 GB each) | 2 large or 6 small | 100k+ units each |
| 3 CPU workers + 1 GPU worker | 3 large CPU + 1 GPU | Full capacity |

### D. Per-Pipe File Changes and Code

This appendix details **every file that must be created or modified** for each pipe, with the exact before/after code.

---

#### D.0 Shared Infrastructure Changes (All Pipes Depend On These)

##### NEW FILE: `process_manager/__init__.py`

```python
# empty
```

##### NEW FILE: `process_manager/__main__.py`

```python
import asyncio
from process_manager.manager import PipelineProcessManager
from process_manager.config import load_config

def main():
    config = load_config()
    manager = PipelineProcessManager(config)
    asyncio.run(manager.run())

if __name__ == "__main__":
    main()
```

##### NEW FILE: `process_manager/dao.py`

```python
"""DAO for the pipeline_jobs table — mirrors vldbaccess/task_queue/dao.py pattern."""

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from uuid import UUID

import sqlalchemy as sa

from vl.common.logging_helpers import get_vl_logger
from vldbaccess.connection_manager import get_async_session

logger = get_vl_logger(__name__)


@dataclass
class PipelineJob:
    id: UUID
    task_id: Optional[UUID]
    dataset_id: UUID
    flow_type: str
    pipeline_structure: str
    status: str
    current_step: Optional[str]
    worker_id: Optional[str]
    pid: Optional[int]
    env_json: dict
    resource_config: Optional[dict]
    requires_gpu: bool
    created_at: datetime
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    error_message: Optional[str]
    retry_count: int
    max_retries: int


class PipelineJobsDAO:

    @staticmethod
    async def create_job(
        task_id: UUID | None,
        dataset_id: UUID,
        flow_type: str,
        pipeline_structure: str,
        env_json: dict,
        requires_gpu: bool = False,
        resource_config: dict | None = None,
        max_retries: int = 2,
    ) -> UUID:
        async with get_async_session(autocommit=True) as session:
            result = await session.execute(
                sa.text("""
                    INSERT INTO pipeline_jobs
                        (task_id, dataset_id, flow_type, pipeline_structure,
                         env_json, requires_gpu, resource_config, max_retries)
                    VALUES
                        (:task_id, :dataset_id, :flow_type, :pipeline_structure,
                         CAST(:env_json AS jsonb), :requires_gpu,
                         CAST(:resource_config AS jsonb), :max_retries)
                    RETURNING id
                """),
                {
                    "task_id": task_id,
                    "dataset_id": dataset_id,
                    "flow_type": flow_type,
                    "pipeline_structure": pipeline_structure,
                    "env_json": json.dumps(env_json),
                    "requires_gpu": requires_gpu,
                    "resource_config": json.dumps(resource_config) if resource_config else None,
                    "max_retries": max_retries,
                },
            )
            job_id = result.scalar()
        logger.info(f"Created pipeline job {job_id}: flow={flow_type}, dataset={dataset_id}")
        return job_id

    @staticmethod
    async def claim_next_job(
        worker_id: str,
        gpu_available: bool = False,
        stale_timeout_seconds: int = 600,
    ) -> Optional[PipelineJob]:
        gpu_filter = "" if gpu_available else "AND requires_gpu = FALSE"
        async with get_async_session(autocommit=True) as session:
            result = await session.execute(
                sa.text(f"""
                    UPDATE pipeline_jobs
                    SET status = 'DISPATCHED', worker_id = :worker_id, started_at = NOW()
                    WHERE id = (
                        SELECT id FROM pipeline_jobs
                        WHERE (status = 'PENDING')
                           OR (status = 'DISPATCHED'
                               AND started_at < NOW() - INTERVAL '1 second' * :stale_timeout)
                           {gpu_filter}
                        ORDER BY created_at ASC
                        LIMIT 1
                        FOR UPDATE SKIP LOCKED
                    )
                    RETURNING *
                """),
                {"worker_id": worker_id, "stale_timeout": stale_timeout_seconds},
            )
            row = result.fetchone()
            if row is None:
                return None
            return PipelineJob(**row._mapping)

    @staticmethod
    async def update_status(job_id: UUID, status: str, **kwargs) -> None:
        sets = ["status = :status"]
        params: dict = {"job_id": job_id, "status": status}
        for key, val in kwargs.items():
            sets.append(f"{key} = :{key}")
            params[key] = val
        async with get_async_session(autocommit=True) as session:
            await session.execute(
                sa.text(f"UPDATE pipeline_jobs SET {', '.join(sets)} WHERE id = :job_id"),
                params,
            )

    @staticmethod
    async def mark_completed(job_id: UUID) -> None:
        await PipelineJobsDAO.update_status(job_id, "COMPLETED", completed_at=sa.text("NOW()"))

    @staticmethod
    async def mark_failed(job_id: UUID, error_message: str) -> None:
        await PipelineJobsDAO.update_status(
            job_id, "FAILED", error_message=error_message, completed_at=sa.text("NOW()")
        )

    @staticmethod
    async def mark_aborting(job_id: UUID) -> None:
        await PipelineJobsDAO.update_status(job_id, "ABORTING")

    @staticmethod
    async def get_job_by_task_id(task_id: UUID) -> Optional[PipelineJob]:
        async with get_async_session() as session:
            result = await session.execute(
                sa.text("""
                    SELECT * FROM pipeline_jobs
                    WHERE task_id = :task_id
                    ORDER BY created_at DESC LIMIT 1
                """),
                {"task_id": task_id},
            )
            row = result.fetchone()
            return PipelineJob(**row._mapping) if row else None
```

##### NEW FILE: `vldbmigration/migrations/NNN_add_pipeline_jobs.sql`

```sql
CREATE TABLE IF NOT EXISTS pipeline_jobs (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id           UUID,
    dataset_id        UUID NOT NULL,
    flow_type         VARCHAR(64) NOT NULL,
    pipeline_structure VARCHAR(16) NOT NULL DEFAULT 'automatic',
    status            VARCHAR(16) NOT NULL DEFAULT 'PENDING',
    current_step      VARCHAR(64),
    worker_id         VARCHAR(128),
    pid               INTEGER,
    env_json          JSONB NOT NULL,
    resource_config   JSONB,
    requires_gpu      BOOLEAN DEFAULT FALSE,
    created_at        TIMESTAMPTZ DEFAULT NOW(),
    started_at        TIMESTAMPTZ,
    completed_at      TIMESTAMPTZ,
    error_message     TEXT,
    retry_count       INTEGER DEFAULT 0,
    max_retries       INTEGER DEFAULT 2
);

CREATE INDEX idx_pipeline_jobs_status ON pipeline_jobs(status);
CREATE INDEX idx_pipeline_jobs_task ON pipeline_jobs(task_id);
CREATE INDEX idx_pipeline_jobs_dataset ON pipeline_jobs(dataset_id);
```

##### MODIFIED FILE: `vl/common/settings.py` (lines ~529-548)

```python
# ADD after line 548 (after VL_K8S_NODE_TOLERATIONS_ENABLED):

    # On-prem pipeline settings
    VL_ON_PREM_PIPELINE_ENABLED: ConfigValue = ConfigValue(str2bool, False)
    VL_PIPELINE_MIN_CPU: ConfigValue = ConfigValue(int, default=None)
    VL_PIPELINE_MIN_MEMORY_GB: ConfigValue = ConfigValue(int, default=None)
```

---

#### D.1 `full_pipeline_flow` — Dataset Creation

**Trigger chain:** `GET /api/v1/dataset/{id}/process` → `_process_dataset_creation()` → `trigger_processing()` → `ArgoPipeline.trigger_vl_argo_processing()`

##### MODIFIED FILE: `clustplorer/logic/datasets_bl.py` (lines 360-396)

**BEFORE** (current Argo path):
```python
    if is_vl_argo_pipeline_enabled(user, pipeline_flow_type, internal_params):
        logger.info("invoke dataset creation using Argo %s", ds)
        job_name = ArgoPipeline.trigger_vl_argo_processing(
            user, ds,
            selected_folders_names=selected_folders_names,
            internal_params=internal_params,
            enrichment_config=enrichment_config,
            pipeline_flow_type=pipeline_flow_type,
            partial_update_batch_id=partial_update_batch_id,
            resource_configuration=resource_configuration,
            embedding_config=embedding_config,
            task_id=task_id,
            task_type=task_type,
            auto_reindex=auto_reindex,
            snapshot_dataset_id=snapshot_dataset_id,
            snapshot_revision_id=snapshot_revision_id,
            restore_in_place=restore_in_place,
        )
        if job_name:
            DatasetDB.update(
                ds.dataset_id,
                creation_context=DatasetCreationContext(invocation_type=InvocationType.ARGO_WORKFLOW, ref=job_name),
            )
            if task_id:
                await _update_task_workflow_info(
                    task_id, job_name, InvocationType.ARGO_WORKFLOW, pipeline_flow_type, restore_in_place
                )
    else:
        logger.error(
            "No pipeline execution method available. Both K8s and Argo pipelines are disabled for user %s, dataset %s",
            user.user_id, ds.dataset_id,
        )
        raise ValueError("No pipeline execution method available. Please enable K8s or Argo pipeline support.")
```

**AFTER** (on-prem path added):
```python
    if Settings.VL_ON_PREM_PIPELINE_ENABLED:
        logger.info("invoke dataset creation using on-prem Process Manager for %s", ds)
        from process_manager.dao import PipelineJobsDAO
        from clustplorer.logic.argo_pipeline.argo_pipeline import ArgoPipeline

        workflow_info = ArgoPipeline.extract_workflow_info(
            user=user, ds=ds,
            selected_folders_names=selected_folders_names,
            enrichment_config=enrichment_config,
            pipeline_flow_type=pipeline_flow_type,
            partial_update_batch_id=partial_update_batch_id,
            resource_configuration=resource_configuration,
            embedding_config=embedding_config,
            task_id=task_id, task_type=task_type,
            snapshot_dataset_id=snapshot_dataset_id,
            snapshot_revision_id=snapshot_revision_id,
            restore_in_place=restore_in_place,
        )

        # Determine flow name
        flow_type_map = {
            PipelineFlowType.PARTIAL_UPDATE: "partial_update_flow",
            PipelineFlowType.REINDEX: "reindex_dataset_flow",
            PipelineFlowType.RESTORE: "restore_dataset_flow",
            PipelineFlowType.ENRICHMENT: "enrichment_flow",
        }
        flow_name = flow_type_map.get(pipeline_flow_type, "full_pipeline_flow")

        structure = "multi-step" if workflow_info.should_use_multistep() else "single-step"

        env_vars = {
            "FLOW_RUN_ID": workflow_info.flow_run_id,
            "DATASET_ID": str(ds.dataset_id),
            "DATASET_NAME": ds.display_name,
            "USER_ID": str(user.user_id),
            "SOURCE_URI": ds.source_uri or "",
            "PIPELINE_FLOW_TYPE": pipeline_flow_type.value,
            "TASK_ID": str(task_id) if task_id else "",
            "TASK_TYPE": task_type or "",
        }
        if selected_folders_names:
            env_vars["SELECTED_FOLDERS"] = ",".join(selected_folders_names)
        if enrichment_config:
            env_vars["PREPROCESS_ENRICHMENT_CONFIG"] = enrichment_config.model_dump_json()
        if partial_update_batch_id:
            env_vars["PARTIAL_UPDATE_BATCH_ID"] = str(partial_update_batch_id)
        if snapshot_dataset_id:
            env_vars["SNAPSHOT_DATASET_ID"] = str(snapshot_dataset_id)
        if snapshot_revision_id:
            env_vars["SNAPSHOT_DATASET_REVISION_ID"] = str(snapshot_revision_id)

        # Handle combined partial_update + reindex
        if pipeline_flow_type == PipelineFlowType.PARTIAL_UPDATE and auto_reindex:
            flow_name = "partial_update_flow+reindex_dataset_flow"  # Process Manager splits

        job_id = await PipelineJobsDAO.create_job(
            task_id=task_id,
            dataset_id=ds.dataset_id,
            flow_type=flow_name,
            pipeline_structure=structure,
            env_json=env_vars,
            requires_gpu=workflow_info.requires_gpu,
            resource_config=workflow_info.cpu_resources,
        )
        logger.info(f"Created pipeline job {job_id} for dataset {ds.dataset_id}")

        DatasetDB.update(
            ds.dataset_id,
            creation_context=DatasetCreationContext(
                invocation_type=InvocationType.ARGO_WORKFLOW,  # reuse enum for now
                ref=str(job_id),
            ),
        )
        if task_id:
            await _update_task_workflow_info(
                task_id, str(job_id), InvocationType.ARGO_WORKFLOW, pipeline_flow_type, restore_in_place
            )

    elif is_vl_argo_pipeline_enabled(user, pipeline_flow_type, internal_params):
        # ... existing Argo path (unchanged) ...
        logger.info("invoke dataset creation using Argo %s", ds)
        job_name = ArgoPipeline.trigger_vl_argo_processing(
            user, ds,
            selected_folders_names=selected_folders_names,
            internal_params=internal_params,
            enrichment_config=enrichment_config,
            pipeline_flow_type=pipeline_flow_type,
            partial_update_batch_id=partial_update_batch_id,
            resource_configuration=resource_configuration,
            embedding_config=embedding_config,
            task_id=task_id,
            task_type=task_type,
            auto_reindex=auto_reindex,
            snapshot_dataset_id=snapshot_dataset_id,
            snapshot_revision_id=snapshot_revision_id,
            restore_in_place=restore_in_place,
        )
        if job_name:
            DatasetDB.update(
                ds.dataset_id,
                creation_context=DatasetCreationContext(invocation_type=InvocationType.ARGO_WORKFLOW, ref=job_name),
            )
            if task_id:
                await _update_task_workflow_info(
                    task_id, job_name, InvocationType.ARGO_WORKFLOW, pipeline_flow_type, restore_in_place
                )
    else:
        logger.error("No pipeline execution method available for user %s, dataset %s", user.user_id, ds.dataset_id)
        raise ValueError("No pipeline execution method available.")
```

**Impact:** This single change in `datasets_bl.py:trigger_processing()` covers **all standard flows**: `full_pipeline_flow`, `partial_update_flow`, `reindex_dataset_flow`, `restore_dataset_flow`, and `enrichment_flow` — because they all route through this function.

---

#### D.2 `full_pipeline_flow` / `partial_update_flow` / `reindex_dataset_flow` / `restore_dataset_flow` — Abort

##### MODIFIED FILE: `vl/tasks/dataset_creation/dataset_creation_task_service.py` (lines 132-261)

The `_terminate_argo_workflow` method must be replaced. **Only this file** has the kubectl call — other task services (media_addition, enrichment, reindex, snapshot_restore, snapshot_clone) do **not** have their own abort-workflow logic; they rely on the API layer calling this service.

**BEFORE** (lines 147-149 in `abort_task`):
```python
        workflow_name = (existing_task.metadata_ or {}).get("workflow_name")
        if workflow_name:
            DatasetCreationTaskService._terminate_argo_workflow(workflow_name)
            logger.info(f"Service: Terminated Argo workflow {workflow_name}")
```

**AFTER:**
```python
        workflow_name = (existing_task.metadata_ or {}).get("workflow_name")
        if workflow_name:
            if Settings.VL_ON_PREM_PIPELINE_ENABLED:
                await DatasetCreationTaskService._terminate_pipeline_job(workflow_name)
            else:
                DatasetCreationTaskService._terminate_argo_workflow(workflow_name)
            logger.info(f"Service: Terminated workflow {workflow_name}")
```

**ADD** new method (after `_terminate_argo_workflow`):
```python
    @staticmethod
    async def _terminate_pipeline_job(job_ref: str) -> None:
        """Terminate an on-prem pipeline job by marking it ABORTING in the DB.
        The Process Manager will detect this status and send SIGTERM."""
        from process_manager.dao import PipelineJobsDAO
        try:
            job_id = UUID(job_ref)
            await PipelineJobsDAO.mark_aborting(job_id)
            logger.info(f"Marked pipeline job {job_id} as ABORTING")
        except (ValueError, Exception) as e:
            logger.warning(f"Failed to abort pipeline job {job_ref}: {e}")
```

**Files that need NO abort changes** (confirmed by reading the code):
- `vl/tasks/media_addition/media_addition_task_service.py` — no workflow termination logic
- `vl/tasks/enrichment/enrichment_task_service.py` — no workflow termination logic
- `vl/tasks/reindex/reindex_task_service.py` — no workflow termination logic
- `vl/tasks/snapshot_restore/snapshot_restore_task_service.py` — no workflow termination logic
- `vl/tasks/snapshot_clone/snapshot_clone_task_service.py` — no workflow termination logic
- `vl/tasks/training/training_task_service.py` — no workflow termination logic

---

#### D.3 Task Cleanup Watchdog

##### MODIFIED FILE: `clustplorer/logic/task_cleanup.py` (lines 193-302)

The Argo watchdog must be extended to also monitor on-prem pipeline jobs.

**ADD** new function (alongside existing `cleanup_orphaned_argo_tasks`):

```python
async def cleanup_orphaned_onprem_tasks() -> int:
    """Check pipeline_jobs table for stuck/orphaned jobs and sync task status."""
    if not Settings.VL_ON_PREM_PIPELINE_ENABLED:
        return 0

    async with get_async_session() as session:
        # Find tasks that are RUNNING but whose pipeline_job is COMPLETED/FAILED
        result = await session.execute(
            sa.text("""
                SELECT t.task_id, t.status as task_status,
                       pj.id as job_id, pj.status as job_status, pj.error_message
                FROM tasks t
                JOIN pipeline_jobs pj ON pj.task_id = t.task_id
                WHERE t.status IN ('RUNNING', 'INITIALIZING')
                  AND pj.status IN ('COMPLETED', 'FAILED')
                  AND NOT t.deleted
            """)
        )
        rows = result.fetchall()

    cleaned = 0
    for row in rows:
        if row.job_status == "COMPLETED":
            await mark_task_as_completed(row.task_id)
            cleaned += 1
        elif row.job_status == "FAILED":
            await mark_task_as_failed(row.task_id, row.error_message or "Pipeline job failed")
            cleaned += 1

    if cleaned:
        logger.info(f"On-prem watchdog synced {cleaned} task(s)")
    return cleaned
```

**MODIFY** `_watchdog_loop` (line 293-302):
```python
async def _watchdog_loop():
    """Periodically check for orphaned tasks and clean them up."""
    while True:
        try:
            cleaned = await cleanup_orphaned_argo_tasks()
            cleaned += await cleanup_orphaned_onprem_tasks()  # ADD THIS LINE
            if cleaned > 0:
                logger.info(f"Watchdog cleaned up {cleaned} orphaned task(s)")
        except Exception:
            logger.exception("Task watchdog encountered an error")
        await asyncio.sleep(SCAN_INTERVAL)
```

**MODIFY** `start_argo_task_watchdog` (line 284-290) to also start when on-prem is enabled:
```python
def start_argo_task_watchdog() -> None:
    if not Settings.VL_ARGO_PIPELINE_ENABLED and not Settings.VL_ON_PREM_PIPELINE_ENABLED:
        logger.debug("No pipeline enabled, skipping watchdog")
        return
    logger.info("Task Cleanup Watchdog scheduled (interval: %ds)", SCAN_INTERVAL)
    asyncio.create_task(_watchdog_loop())
```

---

#### D.4 `model_training_flow` — Training

**Trigger chain:** `POST /api/v1/training` → `trigger_training()` → `ModelTrainingArgoPipeline.trigger_model_training_argo_workflow()` → `model_training_argo_manager.run_model_training_argo_workflow()` → `submit_argo_workflow()`

##### MODIFIED FILE: `clustplorer/logic/model_training/model_training_argo_pipeline.py` (lines 16-62)

**BEFORE:**
```python
    @staticmethod
    def trigger_model_training_argo_workflow(
        user: User, dataset: Dataset, training_task_id: str, model_name: str,
    ) -> str | None:
        # ...
        try:
            workflow_name = model_training_argo_manager.run_model_training_argo_workflow(
                training_task_id=training_task_id,
                model_name=model_name,
                dataset_id=str(dataset.dataset_id),
                dataset_name=dataset.display_name,
                user_id=str(user.user_id),
                user_email=getattr(user, "email", None),
            )
            return workflow_name
        except Exception as e:
            logger.error(f"Failed to create model training Argo workflow: {e}", exc_info=True)
            raise e
```

**AFTER:**
```python
    @staticmethod
    async def trigger_model_training_workflow(
        user: User, dataset: Dataset, training_task_id: str, model_name: str,
    ) -> str | None:
        if Settings.VL_ON_PREM_PIPELINE_ENABLED:
            from process_manager.dao import PipelineJobsDAO
            env_vars = {
                "TRAINING_TASK_ID": training_task_id,
                "MODEL_NAME": model_name,
                "DATASET_ID": str(dataset.dataset_id),
                "DATASET_NAME": dataset.display_name,
                "USER_ID": str(user.user_id),
                "PIPELINE_FLOW_TYPE": "model_training",
                "STEPS_TO_EXECUTE": "START-FINISH",
            }
            if getattr(user, "email", None):
                env_vars["USER_EMAIL"] = user.email
            job_id = await PipelineJobsDAO.create_job(
                task_id=None,  # Training uses its own task table
                dataset_id=dataset.dataset_id,
                flow_type="model_training_flow",
                pipeline_structure="single-step",
                env_json=env_vars,
                requires_gpu=False,
                resource_config={"cpu": "4", "memory": "4Gi"},
            )
            logger.info(f"Created on-prem training job {job_id}")
            return str(job_id)
        else:
            # Existing Argo path
            try:
                workflow_name = model_training_argo_manager.run_model_training_argo_workflow(
                    training_task_id=training_task_id,
                    model_name=model_name,
                    dataset_id=str(dataset.dataset_id),
                    dataset_name=dataset.display_name,
                    user_id=str(user.user_id),
                    user_email=getattr(user, "email", None),
                )
                return workflow_name
            except Exception as e:
                logger.error(f"Failed to create model training Argo workflow: {e}", exc_info=True)
                raise e
```

##### MODIFIED FILE: `clustplorer/web/api_dataset_model_training.py` (line 147)

**BEFORE:**
```python
            workflow_name = ModelTrainingArgoPipeline.trigger_model_training_argo_workflow(
                user=user, dataset=dataset,
                training_task_id=str(training_task.id), model_name=trigger_task.model,
            )
```

**AFTER:**
```python
            workflow_name = await ModelTrainingArgoPipeline.trigger_model_training_workflow(
                user=user, dataset=dataset,
                training_task_id=str(training_task.id), model_name=trigger_task.model,
            )
```

---

#### D.5 Flywheel Flow

**Trigger chain:** `POST /api/v1/flywheel/*` → `run_flywheel()` → `submit_argo_workflow()`

##### MODIFIED FILE: `clustplorer/logic/flywheel/flywheel_runner_argo_manager.py` (lines 45-145)

**ADD** on-prem branch at top of `run_flywheel()`:

```python
async def run_flywheel(
    dataset_id: UUID, flow_id: UUID, flow_root=None,
    pre_cycle_handler=None, cycle_result_handler=None,
    run_mode: FlywheelStatus = FlywheelStatus.RESUME_FLOW,
    cycle_number: int | None = None,
):
    if Settings.VL_ON_PREM_PIPELINE_ENABLED:
        from process_manager.dao import PipelineJobsDAO
        mount_path = "/data"
        env_vars = {
            "DATASET_ID": str(dataset_id),
            "FLOW_ID": str(flow_id),
            "RUN_MODE": str(run_mode.value),
            "FLOW_ROOT": str(os.path.join(mount_path, "flywheel")),
            "PIPELINE_FLOW_TYPE": "flywheel",
        }
        if cycle_number is not None:
            env_vars["CYCLE_NUMBER"] = str(cycle_number)

        job_id = await PipelineJobsDAO.create_job(
            task_id=None,
            dataset_id=dataset_id,
            flow_type="flywheel",
            pipeline_structure="single-step",
            env_json=env_vars,
            requires_gpu=False,
            resource_config={"cpu": "4", "memory": "4Gi"},
        )
        logger.info(f"Created on-prem flywheel job {job_id}")

        # Update task metadata for watchdog
        try:
            flow = await LpFlow.get_by_id_(flow_id)
            if flow.processing_task_id:
                await FlywheelTaskService.update_task_metadata_by_reference_id(
                    reference_id=flow.processing_task_id,
                    metadata_update={"workflow_name": str(job_id), "invocation_type": "OnPremPipeline"},
                )
        except Exception as e:
            logger.warning(f"Failed to update flywheel task metadata: {e}")
        return

    # ... existing Argo path below (unchanged) ...
    assert Settings.PIPELINE_DATA_VOLUME_CONFIG is not None
    # ... rest of existing code ...
```

---

#### D.6 `nop_flow` / `post_success_flow` / `post_error_flow`

**No file changes required.** These flows are either:
- **`nop_flow`:** CLI-only, runs directly as `python -m pipeline.controller.controller --flow-to-run nop_flow` on any worker node for smoke testing. No trigger code to change.
- **`post_success_flow` / `post_error_flow`:** Not triggered by API — they are exit handlers invoked by the Process Manager's try/finally logic (new code in `process_manager/manager.py`).

---

#### D.7 Per-Pipe Summary Table

| Pipe | Files Modified | Files Created | Lines Changed | Phase |
|---|---|---|---|---|
| **All (shared)** | `vl/common/settings.py` | `process_manager/{__init__,__main__,dao,manager,dispatcher,config,health}.py`, `vldbmigration/.../pipeline_jobs.sql` | ~3 modified, ~550 new | 0-1 |
| **full_pipeline_flow** | `clustplorer/logic/datasets_bl.py` | — | ~60 added (on-prem branch in `trigger_processing`) | 1 |
| **partial_update_flow** | same as above (routes through `trigger_processing`) | — | 0 additional | 1 |
| **reindex_dataset_flow** | same as above | — | 0 additional | 1 |
| **restore_dataset_flow** | same as above | — | 0 additional | 1 |
| **enrichment_flow** | same as above | — | 0 additional | 2 |
| **prepare_data_flow / indexer_flow** | none (internal to Process Manager multi-step logic) | — | 0 | 2 |
| **Abort (all flows)** | `vl/tasks/dataset_creation/dataset_creation_task_service.py` | — | ~15 modified + ~10 new method | 1 |
| **Watchdog** | `clustplorer/logic/task_cleanup.py` | — | ~30 new function + ~5 modified | 1 |
| **model_training_flow** | `clustplorer/logic/model_training/model_training_argo_pipeline.py`, `clustplorer/web/api_dataset_model_training.py` | — | ~35 modified | 3 |
| **flywheel** | `clustplorer/logic/flywheel/flywheel_runner_argo_manager.py` | — | ~30 added (on-prem branch) | 3 |
| **nop_flow** | none | — | 0 | — |
| **post_success/error_flow** | none (handled by Process Manager) | — | 0 | 1 |

---

### E. Deployment Plan for On-Prem Pipes

#### E.1 Deployment Architecture Overview

```
┌──────────────────────────────────────────────────────────────────────┐
│                     DEPLOYMENT TOPOLOGY                              │
│                                                                      │
│  ┌─────────────────────────┐     ┌─────────────────────────┐        │
│  │   APP SERVER (VM 1)     │     │  MGMT + CPU WORKER      │        │
│  │                         │     │     (VM 2)              │        │
│  │  Services:              │     │                         │        │
│  │  • vl-clustplorer       │     │  Services:              │        │
│  │  • vl-queue-worker      │     │  • vl-process-manager   │        │
│  │  • vl-frontend (nginx)  │     │                         │        │
│  │  • keycloak             │     │  Runs pipelines as      │        │
│  │  • openfga              │     │  systemd-run scoped     │        │
│  │  • image-proxy          │     │  subprocesses           │        │
│  │                         │     │                         │        │
│  │  Deployed via:          │     │  Deployed via:          │        │
│  │  systemd + nginx conf   │     │  systemd + git pull     │        │
│  └─────────────────────────┘     └─────────────────────────┘        │
│                                                                      │
│  ┌─────────────────────────┐     ┌─────────────────────────┐        │
│  │   GPU WORKER (VM 3)     │     │  DB + NFS SERVER        │        │
│  │                         │     │     (VM 4)              │        │
│  │  Software:              │     │                         │        │
│  │  • Python 3.10 + venv   │     │  Services:              │        │
│  │  • CUDA 12.x + TensorRT │     │  • PostgreSQL 15        │        │
│  │  • NVIDIA Driver 535+   │     │  • NFS Server (nfsd)    │        │
│  │  • Pipeline code (git)  │     │                         │        │
│  │                         │     │  Storage:               │        │
│  │  Triggered via:         │     │  • /data/ (2TB+)        │        │
│  │  SSH from Process Mgr   │     │  • /var/lib/postgresql   │        │
│  └─────────────────────────┘     └─────────────────────────┘        │
└──────────────────────────────────────────────────────────────────────┘
```

#### E.2 Deployment Steps Per Node

##### Step 1: DB + NFS Server (VM 4) — Deploy First

```bash
# 1. Install PostgreSQL
apt-get install -y postgresql-15 postgresql-15-pgvector

# 2. Configure PostgreSQL
cat >> /etc/postgresql/15/main/postgresql.conf <<EOF
listen_addresses = '*'
max_connections = 200
shared_buffers = 8GB
work_mem = 256MB
maintenance_work_mem = 2GB
wal_level = replica
archive_mode = on
EOF

# 3. Allow network access
echo "host all all 10.0.0.0/8 md5" >> /etc/postgresql/15/main/pg_hba.conf
systemctl restart postgresql

# 4. Create database and extensions
sudo -u postgres psql -c "CREATE DATABASE vl_camtek;"
sudo -u postgres psql -d vl_camtek -c "CREATE EXTENSION IF NOT EXISTS pgvector;"
sudo -u postgres psql -d vl_camtek -c "CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\";"

# 5. Run schema migrations
cd /opt/vl-camtek && python -m vldbmigration.migrate

# 6. Setup NFS
apt-get install -y nfs-kernel-server
mkdir -p /data/{models,pipeline,duckdb,datasets,exports,trained-models,ground-truth,snapshots}
chown -R 1000:1000 /data/

cat >> /etc/exports <<EOF
/data/models         *(ro,sync,no_subtree_check,no_root_squash)
/data/pipeline       *(rw,sync,no_subtree_check,no_root_squash)
/data/duckdb         *(rw,sync,no_subtree_check,no_root_squash)
/data/datasets       *(rw,sync,no_subtree_check,no_root_squash)
/data/exports        *(rw,sync,no_subtree_check,no_root_squash)
/data/trained-models *(rw,sync,no_subtree_check,no_root_squash)
/data/ground-truth   *(rw,sync,no_subtree_check,no_root_squash)
/data/snapshots      *(rw,sync,no_subtree_check,no_root_squash)
EOF
exportfs -ra
systemctl enable --now nfs-kernel-server

# 7. Copy model weights
rsync -avP <source>/models/ /data/models/
```

##### Step 2: App Server (VM 1) — Deploy Second

```bash
# 1. Install base packages
apt-get install -y python3.10 python3.10-venv nfs-common nginx

# 2. Mount NFS (read-only for app server — no pipeline work here)
mkdir -p /data/models
echo "nfs-server:/data/models /data/models nfs4 ro,hard,intr 0 0" >> /etc/fstab
mount -a

# 3. Clone code and create venv
git clone <repo> /opt/vl-camtek
cd /opt/vl-camtek
python3.10 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 4. Create env files
cp deploy/env/clustplorer.env.template /etc/vl/clustplorer.env
# Edit: PG_URI, OPENFGA_API_URL, VL_ON_PREM_PIPELINE_ENABLED=true, etc.

# 5. Deploy systemd services
cp deploy/systemd/vl-clustplorer.service /etc/systemd/system/
cp deploy/systemd/vl-queue-worker.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now vl-clustplorer vl-queue-worker

# 6. Deploy nginx
cp deploy/nginx/vl-camtek.conf /etc/nginx/sites-available/
ln -s /etc/nginx/sites-available/vl-camtek.conf /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx

# 7. Deploy frontend
cd /opt/vl-camtek/fe/clustplorer
npm install && npm run build
# nginx serves the build output

# 8. Deploy Keycloak + OpenFGA (or point to existing)
```

##### Step 3: Management + CPU Worker Node (VM 2) — Deploy Third

```bash
# 1. Install packages
apt-get install -y python3.10 python3.10-venv nfs-common openssh-client

# 2. Mount all NFS volumes
mkdir -p /data/{models,pipeline,duckdb,datasets,exports,trained-models,ground-truth,snapshots}
cat >> /etc/fstab <<EOF
nfs-server:/data/models         /data/models         nfs4 ro,hard,intr 0 0
nfs-server:/data/pipeline       /data/pipeline       nfs4 rw,hard,intr 0 0
nfs-server:/data/duckdb         /data/duckdb         nfs4 rw,hard,intr 0 0
nfs-server:/data/datasets       /data/datasets       nfs4 rw,hard,intr 0 0
nfs-server:/data/exports        /data/exports        nfs4 rw,hard,intr 0 0
nfs-server:/data/trained-models /data/trained-models nfs4 rw,hard,intr 0 0
nfs-server:/data/ground-truth   /data/ground-truth   nfs4 rw,hard,intr 0 0
nfs-server:/data/snapshots      /data/snapshots      nfs4 rw,hard,intr 0 0
EOF
mount -a

# 3. Clone code and create venv
git clone <repo> /opt/vl-camtek
cd /opt/vl-camtek
python3.10 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 4. Create service user
useradd -r -s /bin/bash -m vl-pipeline

# 5. Setup SSH key for GPU worker
sudo -u vl-pipeline ssh-keygen -t ed25519 -f /home/vl-pipeline/.ssh/id_ed25519 -N ""
# Copy public key to GPU worker: ssh-copy-id vl-pipeline@gpu-worker-01

# 6. Create config files
cp deploy/env/process_manager.env.template /etc/vl/process_manager.env
cp deploy/process_manager.yaml.template /etc/vl/process_manager.yaml
# Edit: PG_URI, worker hosts, GPU config

# 7. Deploy Process Manager
cp deploy/systemd/vl-process-manager.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now vl-process-manager
```

##### Step 4: GPU Worker (VM 3) — Deploy Fourth

```bash
# 1. Install NVIDIA drivers + CUDA
apt-get install -y nvidia-driver-535 nvidia-cuda-toolkit-12-0
# Verify: nvidia-smi

# 2. Install Python and packages
apt-get install -y python3.10 python3.10-venv nfs-common

# 3. Mount NFS
mkdir -p /data/{models,pipeline}
cat >> /etc/fstab <<EOF
nfs-server:/data/models   /data/models   nfs4 ro,hard,intr 0 0
nfs-server:/data/pipeline /data/pipeline nfs4 rw,hard,intr 0 0
EOF
mount -a

# 4. Clone code and create GPU venv
git clone <repo> /opt/vl-camtek
cd /opt/vl-camtek
python3.10 -m venv .venv-gpu
source .venv-gpu/bin/activate
pip install -r requirements-gpu.txt  # GPU-specific deps
pip install torch==2.5.1 torchvision==0.20.1
pip install ultralytics transformers flash-attn==2.8.3

# 5. Create service user (same as management node)
useradd -r -s /bin/bash -m vl-pipeline
# Add SSH authorized key from management node

# 6. Verify GPU enrichment works
cd /opt/vl-camtek
source .venv-gpu/bin/activate
python -c "import torch; print(torch.cuda.is_available())"  # Should print True
```

#### E.3 Deployment Verification Checklist

| Check | Command | Expected |
|---|---|---|
| PostgreSQL accessible | `psql $PG_URI -c "SELECT 1"` | Returns 1 |
| NFS mounted on CPU worker | `df -h /data/models` | Shows NFS mount |
| NFS mounted on GPU worker | `df -h /data/models` | Shows NFS mount |
| API health | `curl http://app-server:9999/api/v1/health` | 200 OK |
| Frontend loads | Browser → `http://app-server/` | Login page |
| Process Manager running | `systemctl status vl-process-manager` | active (running) |
| Queue Worker running | `systemctl status vl-queue-worker` | active (running) |
| SSH to GPU worker | `sudo -u vl-pipeline ssh gpu-worker-01 hostname` | Returns hostname |
| GPU visible | `ssh gpu-worker-01 nvidia-smi` | Shows GPU |
| Smoke test (nop_flow) | Create nop_flow pipeline_jobs row | Completes in <10s |
| Small dataset creation | UI: upload 10 images, click Process | Dataset reaches READY |

#### E.4 Release/Update Procedure

```bash
#!/bin/bash
# deploy.sh — run from management node
# Usage: ./deploy.sh [app|worker|all]

set -e
TARGET=${1:-all}
NODES_APP="app-server"
NODES_CPU="cpu-worker-01"
NODES_GPU="gpu-worker-01"

deploy_node() {
    local node=$1
    echo "=== Deploying to $node ==="
    ssh $node "cd /opt/vl-camtek && git pull origin main"
    ssh $node "cd /opt/vl-camtek && source .venv/bin/activate && pip install -q -r requirements.txt"
}

if [[ "$TARGET" == "app" || "$TARGET" == "all" ]]; then
    deploy_node $NODES_APP
    ssh $NODES_APP "sudo systemctl restart vl-clustplorer vl-queue-worker"
fi

if [[ "$TARGET" == "worker" || "$TARGET" == "all" ]]; then
    # Wait for active pipelines to finish
    echo "Waiting for active pipeline jobs to complete..."
    ssh $NODES_CPU "cd /opt/vl-camtek && source .venv/bin/activate && \
        python -c \"
import asyncio
from process_manager.dao import PipelineJobsDAO
async def wait():
    while True:
        from vldbaccess.connection_manager import get_async_session
        async with get_async_session() as s:
            r = await s.execute(__import__('sqlalchemy').text(
                \\\"SELECT count(*) FROM pipeline_jobs WHERE status IN ('RUNNING','DISPATCHED')\\\"
            ))
            if r.scalar() == 0: break
        await asyncio.sleep(5)
        print('Waiting for active jobs...')
asyncio.run(wait())
\""

    deploy_node $NODES_CPU
    ssh $NODES_CPU "sudo systemctl restart vl-process-manager"

    deploy_node $NODES_GPU
fi

# Run migrations
ssh $NODES_APP "cd /opt/vl-camtek && source .venv/bin/activate && python -m vldbmigration.migrate"

echo "=== Deployment complete ==="
```

---

### F. VM Specifications

#### F.1 Production Configuration (Recommended)

| VM | Role | vCPU | RAM | Storage | GPU | OS | Network |
|---|---|---|---|---|---|---|---|
| **VM 1** | App Server | 8 | 32 GB | 100 GB SSD (OS) | None | Ubuntu 22.04 LTS | 1 Gbps |
| **VM 2** | Mgmt + CPU Worker | 16 | 128 GB | 500 GB NVMe (OS+scratch) | None | Ubuntu 22.04 LTS | 10 Gbps (NFS) |
| **VM 3** | GPU Worker | 14 | 96 GB | 500 GB NVMe | NVIDIA A10 (24GB) or A100 (40GB) | Ubuntu 22.04 LTS | 10 Gbps (NFS) |
| **VM 4** | DB + NFS Server | 8 | 32 GB | 1 TB NVMe (PostgreSQL) + 2 TB SSD (NFS /data/) | None | Ubuntu 22.04 LTS | 10 Gbps |

**Total:** 46 vCPU, 288 GB RAM, ~4.1 TB storage, 1 GPU

#### F.2 Minimum Viable Configuration (Development/Small Scale)

| VM | Role | vCPU | RAM | Storage | GPU | OS |
|---|---|---|---|---|---|---|
| **VM 1** | App + Mgmt + CPU Worker | 16 | 64 GB | 500 GB SSD | None | Ubuntu 22.04 LTS |
| **VM 2** | GPU Worker | 8 | 48 GB | 250 GB SSD | NVIDIA T4 (16GB) | Ubuntu 22.04 LTS |
| **VM 3** | DB + NFS | 4 | 16 GB | 1 TB HDD | None | Ubuntu 22.04 LTS |

**Total:** 28 vCPU, 128 GB RAM, ~1.75 TB storage, 1 GPU

**Limitation:** Max dataset size ~10k units (constrained by 64GB RAM on CPU worker).

#### F.3 Single-Node Configuration (Absolute Minimum)

| VM | Role | vCPU | RAM | Storage | GPU | OS |
|---|---|---|---|---|---|---|
| **VM 1** | Everything | 32 | 128 GB | 2 TB NVMe | NVIDIA A10 (24GB) | Ubuntu 22.04 LTS |

Set `gpu_worker_host: localhost` in Process Manager config. PostgreSQL runs locally. NFS replaced by local filesystem.

**Limitation:** No fault isolation. GPU and CPU pipelines compete for resources.

#### F.4 Scaled Configuration (High Throughput)

| VM | Role | Count | vCPU | RAM | Storage | GPU |
|---|---|---|---|---|---|---|
| **App Server** | API + Frontend | 2 (HA) | 8 | 32 GB | 100 GB SSD | None |
| **Management** | Process Manager | 2 (HA) | 4 | 16 GB | 50 GB SSD | None |
| **CPU Worker** | Pipeline execution | 3 | 16 | 128 GB | 500 GB NVMe | None |
| **GPU Worker** | Enrichment | 2 | 14 | 96 GB | 500 GB NVMe | A100 (40GB) |
| **DB Primary** | PostgreSQL | 1 | 16 | 64 GB | 2 TB NVMe | None |
| **DB Replica** | Read replica | 1 | 8 | 32 GB | 2 TB NVMe | None |
| **NFS Server** | Shared storage | 1 | 4 | 16 GB | 4 TB SSD RAID | None |

**Total:** 12 VMs, 166 vCPU, 804 GB RAM, 2 GPUs

**Capacity:** 6 concurrent CPU pipelines + 2 concurrent GPU enrichments. Can process 100k+ unit datasets in parallel.

#### F.5 Software Requirements Per VM

| Software | App Server | Mgmt/CPU Worker | GPU Worker | DB/NFS Server |
|---|---|---|---|---|
| Ubuntu 22.04 LTS | Required | Required | Required | Required |
| Python 3.10 | Required | Required | Required | — |
| pip/venv | Required | Required | Required | — |
| NFS client | — | Required | Required | — |
| NFS server | — | — | — | Required |
| PostgreSQL 15 | — | Client only | Client only | Server |
| pgvector | — | — | — | Required |
| nginx | Required | — | — | — |
| NVIDIA Driver 535+ | — | — | Required | — |
| CUDA Toolkit 12.x | — | — | Required | — |
| TensorRT 8.x | — | — | Required | — |
| PyTorch 2.5.1 | — | — | Required | — |
| FFmpeg | — | Required | Required | — |
| s5cmd | — | Required | — | — |
| openssh-server | — | — | Required | — |
| systemd (default) | Required | Required | — | Required |

#### F.6 Network Requirements

| Source | Destination | Port | Protocol | Purpose |
|---|---|---|---|---|
| App Server | DB Server | 5432 | TCP | PostgreSQL |
| App Server | Keycloak | 8080 | TCP | OIDC auth |
| App Server | OpenFGA | 8081 | TCP | Authorization |
| CPU Worker | DB Server | 5432 | TCP | vldbaccess |
| CPU Worker | NFS Server | 2049 | TCP/UDP | NFS v4 |
| GPU Worker | NFS Server | 2049 | TCP/UDP | NFS v4 |
| Mgmt Node | GPU Worker | 22 | TCP | SSH subprocess dispatch |
| CPU Worker | Camtek Data Server | 5050 | TCP | gRPC (scan results) |
| CPU Worker | Camtek Training | configurable | TCP | gRPC (training) |
| Frontend | App Server | 443/80 | TCP | HTTPS/HTTP (nginx) |

---

*End of document.*
