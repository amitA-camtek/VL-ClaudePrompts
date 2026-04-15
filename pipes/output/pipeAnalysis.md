# VL-Camtek Pipeline & Task System Analysis

**Codebase:** `c:\visual layer\vl-camtek`
**Analysis date:** 2026-04-15
**Scope:** Deep architectural analysis of "pipes" and "tasks" — how they are defined, configured, triggered, orchestrated on Kubernetes, and monitored.

---

## Executive Summary

VL-Camtek is a semiconductor defect-analysis platform built around **two distinct but interconnected abstractions**:

1. **Pipes (pipelines)** — Long-running, containerized, Kubernetes-orchestrated data processing flows that transform raw images/videos into indexed, embedded, cluster-ready datasets. Orchestrated via **Argo Workflows**.
2. **Tasks** — Lightweight, database-backed units of user-facing work (dataset creation, enrichment, training, etc.) that track the progress and lifecycle of one or more pipeline executions. Managed via a **custom async queue worker** + repository pattern.

Pipes do the heavy lifting (GPU inference, FastDup, DB writes). Tasks are the UI-visible handle the user uses to monitor/abort/retry that work. A single user action ("Create Dataset") creates one Task, which triggers one Argo Workflow containing one or more Pipe steps, which writes status back to the Task row as it progresses.

---

## 1. Pipe and Task Types

### 1.1 Pipe Types

Pipes are defined as **flow functions** composed of ordered **step functions**. Eleven flow types are registered in [pipeline/controller/controller.py:56-68](c:/visual%20layer/vl-camtek/pipeline/controller/controller.py):

| Flow | Purpose |
|------|---------|
| `full_pipeline_flow` | End-to-end: ingest → preprocess → enrich → index → publish |
| `prepare_data_flow` | CPU-only subset: download + split + prep (multi-step mode) |
| `enrichment_flow` | GPU-only: captions, tagging, detection, embedding generation |
| `indexer_flow` | CPU-only subset: metadata + DB writes + publish (multi-step mode) |
| `partial_update_flow` | Add new media to an existing dataset |
| `reindex_dataset_flow` | Re-run indexing over an existing dataset |
| `restore_dataset_flow` | Restore a dataset from a snapshot |
| `model_training_flow` | Process dataset for Camtek model training |
| `nop_flow` | No-op (test/debug) |
| `post_success_flow` | Cleanup on success |
| `post_error_flow` | Cleanup + notifications on failure |

Pipes run inside one of **three container images** (see `pipeline/pipeline-cpu.Dockerfile`, `pipeline/pipeline-gpu.Dockerfile`, `pipeline/preprocess/obf.Dockerfile`):
- **CPU pipeline** — Entry: `python -m pipeline.controller.controller` (default flow: `full_pipeline_flow`)
- **GPU pipeline** — Entry: `python3.10 -m pipeline.preprocess.job` (CUDA/TensorRT base image)
- **Preprocess job** — Standalone preprocessing container

### 1.2 Pipeline Steps (stages inside a flow)

Defined in [pipeline/controller/pipeline_steps.py](c:/visual%20layer/vl-camtek/pipeline/controller/pipeline_steps.py). Each step is a plain function decorated with `@controller_step(...)`:

| Step | Container | Status on entry | Purpose |
|------|-----------|------------------|---------|
| `step_start` | CPU | — | Pipeline initialization marker |
| `step_local_init` | CPU | INDEXING 33% | Create dataset record, set pipeline root |
| `download_data` | CPU | — | Fetch from `SOURCE_URI` (S3, NFS, local) |
| `step_split_data` | CPU | INDEXING | Partition input data |
| `step_enrichment_data_prep` | CPU | INDEXING 35% | Prep images/metadata for GPU stage |
| `step_enrichment` | GPU | INDEXING 50% | Run ML models → embeddings |
| `step_enrichment_consolidation` | CPU | INDEXING 65% | Merge GPU outputs |
| `step_normalize` | CPU | PRE_PROCESSING | Normalize dataset |
| `step_fastdup` | CPU | INDEXING 50% | Duplicate/similar-image detection |
| `step_issues_generator` | CPU | INDEXING | Quality-issue detection |
| `step_exploration` | CPU | INDEXING | Clustering / similarity analysis |
| `step_metadata` | CPU | INDEXING | Metadata aggregation |
| `step_sync_data_to_local` | CPU | SAVING | Write to PostgreSQL (vldbaccess) |
| `step_prepare_for_read` | CPU | SAVING | Build read-optimized indexes |
| `step_publish_media` | CPU | SAVING 50% | Push media to CDN / S3 |
| `step_finalize_dataset_creation` | CPU | READY 100% | Mark dataset READY |
| `step_cleanup` | CPU | — | Remove temp files |
| `handle_error_step` | CPU | ERROR | Send failure notifications |

Steps are grouped into **subflows** in [pipeline/controller/pipeline_flows.py:49-177](c:/visual%20layer/vl-camtek/pipeline/controller/pipeline_flows.py) and composed via dict-merge:

```python
FULL_PIPELINE_STEPS = {**_INIT_SUBFLOW, **_SETUP_SUBFLOW, **_ENRICHMENT_SUBFLOW, **_METADATA_SUBFLOW, **_PUBLISH_SUBFLOW}
```

### 1.3 Preprocess Sub-Steps

Defined in [pipeline/preprocess/pipeline_preprocess.py:749-757](c:/visual%20layer/vl-camtek/pipeline/preprocess/pipeline_preprocess.py):

```python
STEP_NAMES = {
    'prepare_image_data': prepare_image_data,
    'xfer': XferImages(),
    'embed_images_xfer_only': functools.partial(embed_images, xfer_only=True),
    'embed_images': embed_images,
    'clean_images': clean_images,
    'fetch_external_data': fetch_external_data,
    'prepare_dataset': prepare_dataset,
}
```

Section selection via `PREPROCESS_SECTION` env var (`cpu` / `gpu` / `finalize` / `dry-run`) at [pipeline/preprocess/job.py:8-22](c:/visual%20layer/vl-camtek/pipeline/preprocess/job.py).

### 1.4 Task Types

Eight types enumerated in [vldbaccess/tasks/base/enums.py:19-27](c:/visual%20layer/vl-camtek/vldbaccess/tasks/base/enums.py):

| TaskType | Purpose | Concrete class |
|----------|---------|----------------|
| `DATASET_CREATION` | Create a new dataset | `DatasetCreationTask` |
| `MEDIA_ADDITION` | Add media to existing dataset | `MediaAdditionTask` |
| `ENRICHMENT` | Run additional ML enrichment | `EnrichmentTask` |
| `LABEL_PROPAGATION` | Semi-supervised labeling | (service-only) |
| `TRAINING` | Train a model via Camtek | `TrainingTask` |
| `REINDEX` | Re-index a dataset | `ReindexTask` |
| `SNAPSHOT_RESTORE` | Restore from snapshot | `SnapshotRestoreTask` |
| `SNAPSHOT_CLONE` | Clone a snapshot | `SnapshotCloneTask` |

Plus `FlywheelTask` (active-learning loop) at [vl/tasks/flywheel/flywheel_task.py](c:/visual%20layer/vl-camtek/vl/tasks/flywheel/flywheel_task.py).

### 1.5 Task Status Lifecycle

From [vldbaccess/tasks/base/enums.py:4-16](c:/visual%20layer/vl-camtek/vldbaccess/tasks/base/enums.py):

```python
class TaskStatus(str, Enum):
    INITIALIZING
    RUNNING
    COMPLETED      # final
    FAILED         # final, retryable
    ABORTED        # final, retryable
    WAITING_FOR_REVIEW
```

Domain-specific **sub-statuses** layer on top, e.g. `TaskDatasetCreationSubStatus`: UPLOADING, INITIALIZING, PRE_PROCESSING, INDEXING, SAVING. Sub-status is persisted as JSONB (`{"UPLOADING": 100, "INDEXING": 45, ...}`) so the UI can show granular multi-step progress.

---

## 2. Implementation Details

### 2.1 Pipe Implementation — Decorator-Composed Functional Pipelines

**No Airflow, no Celery.** Pipes are plain Python functions composed via two decorators defined in [pipeline/controller/controller_steps/controller_wrappers/impl_controller_wrappers.py:1008-1148](c:/visual%20layer/vl-camtek/pipeline/controller/controller_steps/controller_wrappers/impl_controller_wrappers.py):

```python
@controller_step(
    step_name="NORMALIZE",
    dataset_status=DatasetStatus.PRE_PROCESSING,
    progress=100,
    task_dataset_creation_sub_status=TaskDatasetCreationSubStatus.PRE_PROCESSING,
)
def step_normalize(): ...

@controller_flow(initial_progress=0, success_flow=True)
def full_dataset_pipeline_flow(): ...
```

The decorator automatically wires in:
- Timing (`@timed`)
- Exception logging (`@log_exception_with_args`)
- Dataset-status updates (old enum + new enum)
- Task sub-status + progress updates (scaled by `PROGRESS_OFFSET` + `PROGRESS_SCALE` for multi-step workflows)
- Trace-event recording via `PipelineStatusEventsReporter` (lines 159-707 same file)

**Flow runner** at [pipeline/controller/controller_utils.py:396](c:/visual%20layer/vl-camtek/pipeline/controller/controller_utils.py) iterates an ordered `dict[str, Callable]` and executes steps sequentially.

### 2.2 Task Implementation — Template-Method Base Class + Repository Pattern

Base class: [vl/tasks/base/base_task.py](c:/visual%20layer/vl-camtek/vl/tasks/base/base_task.py) — `AppTaskBase` (abstract, 319 lines).

Eleven abstract hooks each subclass overrides:
- `_get_initial_status`, `_map_to_task_status` (domain-specific status ↔ unified `TaskStatus`)
- `_pre_create`, `_post_create`
- `_pre_start`, `_post_start`
- `_pre_abort`, `_post_abort`
- `_pre_retry`, `_post_retry`
- `_on_status_updated`

Public methods: `create(dto)`, `abort()`, `retry()`, `update_status(...)`.

**Repository pattern:** One `TasksRepository` subclass per task type at [vldbaccess/tasks/](c:/visual%20layer/vl-camtek/vldbaccess/tasks/). Each implements `_update_source_table()` to keep the source-of-truth domain table (e.g. `datasets`) in sync with the `tasks` table.

**Service layer:** One service class per task type exposes the public API surface, e.g. [vl/tasks/dataset_creation/dataset_creation_task_service.py](c:/visual%20layer/vl-camtek/vl/tasks/dataset_creation/dataset_creation_task_service.py) — `create_dataset_task`, `update_task_status`, `abort_task`, `retry_and_trigger_task`.

### 2.3 Queue Worker (separate from the tasks table)

A lightweight **database-as-queue** implementation — not Celery, not RabbitMQ.

- Schema: [vldbaccess/task_queue/dao.py](c:/visual%20layer/vl-camtek/vldbaccess/task_queue/dao.py) — `QueueTask` (id, queue_name, payload JSONB, status, retry_count, max_retries, ...)
- Worker loop: [clustplorer/logic/queue_worker/worker.py](c:/visual%20layer/vl-camtek/clustplorer/logic/queue_worker/worker.py)

```python
async def run_worker(poll_interval_seconds=5.0, shutdown_event=None):
    while True:
        if shutdown_event and shutdown_event.is_set(): break
        if not await run_worker_once():
            await asyncio.sleep(poll_interval_seconds)
```

**Concurrency:** `SELECT ... FOR UPDATE SKIP LOCKED` in `claim_next()` — any number of workers can poll safely. Stale-task recovery if `processed_at < NOW - processing_timeout_seconds` (default 300s).

### 2.4 Async Model

- FastAPI endpoints are `async def`
- Task services use `async with get_async_session(autocommit=True)` — short-lived transactions, each status update durably persisted
- Pipeline container is **synchronous Python** (the steps are long-running CPU/GPU work, not I/O bound)

---

## 3. Triggering Mechanisms

### 3.1 API Triggers

All task/pipeline triggers originate from FastAPI endpoints in `clustplorer/web/`:

| Endpoint | File | Triggers |
|----------|------|----------|
| `POST /api/v1/workflow/dataset/new` | [api_dataset_create_workflow.py:394](c:/visual%20layer/vl-camtek/clustplorer/web/api_dataset_create_workflow.py) | Create dataset record (no pipeline yet) |
| `POST /api/v1/dataset/{id}/data/folder_upload/{trans_id}` | same:854 | Upload files + validate |
| `GET /api/v1/dataset/{id}/process` | same:1070 | Create task + submit Argo workflow |
| `POST /api/v1/dataset/{id}/add_media` | [api_add_media.py:28](c:/visual%20layer/vl-camtek/clustplorer/web/api_add_media.py) | MediaAdditionTask + partial_update_flow |
| `POST /api/v1/tasks/{id}/abort` | [web/tasks/api.py:49](c:/visual%20layer/vl-camtek/clustplorer/web/tasks/api.py) | Abort → `kubectl delete workflow` |
| `POST /api/v1/tasks/{id}/retry` | same:87 | Retry → re-submit Argo workflow |
| `POST /api/v1/dataset/*/training` | [api_dataset_model_training.py](c:/visual%20layer/vl-camtek/clustplorer/web/api_dataset_model_training.py) | TrainingTask |
| `POST /api/v1/flywheel/*` | [api_flywheel.py](c:/visual%20layer/vl-camtek/clustplorer/web/api_flywheel.py) | FlywheelTask |

### 3.2 Scheduled Triggers

Minimal. One CronJob shipped with the Helm chart:
- `pipeline/pipeline_cleanup/cronJob.yaml` — periodic cleanup job

No Celery Beat, no Airflow scheduler.

### 3.3 Event-Driven Triggers

None observed. The system is **request/response + polling**:
- Frontend polls `GET /api/v1/tasks?dataset_id=...` for status
- Argo Workflow pods update the `tasks` table directly via vldbaccess (same PostgreSQL)

### 3.4 Trigger Component Responsibilities

| Component | Role |
|-----------|------|
| `clustplorer` pod (FastAPI) | Receives API call, creates `TasksTable` row, calls `ArgoPipeline.trigger_vl_argo_processing()` |
| `ArgoPipeline` | Builds `WorkflowInfo` → manifest → submits via Kubernetes Python client |
| Argo Workflow Controller | Watches `argoproj.io/v1alpha1` CRDs, schedules pipeline pods |
| Pipeline pod | Runs `pipeline.controller.controller` → executes flow → writes progress to `tasks` table |

---

## 4. Kubernetes Integration

### 4.1 Helm Chart Overview

Chart root: [devops/visual-layer/templates/](c:/visual%20layer/vl-camtek/devops/visual-layer/templates/). Values at [devops/visual-layer/values.yaml](c:/visual%20layer/vl-camtek/devops/visual-layer/values.yaml). Client overrides at [devops/clients/camtek/values.yaml](c:/visual%20layer/vl-camtek/devops/clients/camtek/values.yaml).

### 4.2 Resource Catalog

| Kind | Name | Purpose |
|------|------|---------|
| **Deployment** | `clustplorer` | FastAPI backend (port 9999) — submits workflows |
| **Deployment** | `clustplorer-fe` | React frontend (port 8080) |
| **Deployment** | `image-proxy` | Image serving (on-prem) |
| **Deployment** | `adc-static` | Camtek ADC output server (optional) |
| **StatefulSet** | `postgresql` | DB instance (optional, RWO PVC) |
| **Service (ClusterIP)** | `*-service` | Internal routing for each deployment |
| **Ingress (nginx)** | `visual-layer-ingress` | `/` → FE, `/api` → backend, `/image` → proxy |
| **PVC** | `backend-efs-pvc` | Model storage + pipeline shared volume (RWMany) |
| **PVC** | `duckdb-storage-pvc` | DuckDB datasets (FSX CSI, RWMany, 100Gi) |
| **PVC** | `datasets-storage-pvc` | Dataset staging (hostPath, RWO, 50Gi) |
| **PVC** | `db-csv-exports-pvc` | Model-training CSV exports |
| **PVC** | `model-storage-pvc` | Fine-tuned models (RWMany, 10Gi) |
| **PVC** | `longhorn-data-enc-pvc` | LUKS-encrypted data (on-prem) |
| **PVC** | `ground-truth-pvc` | Ground-truth labels |
| **ConfigMap** | `config` | 113+ backend env vars (Argo, DuckDB, feature flags) |
| **ConfigMap** | `k8s-pipeline-config` | Pipeline-container env (embedder paths, PG URI) |
| **ConfigMap** | `frontend-config` | FE feature flags |
| **Secret** | `storage-key`, `longhorn-crypto-passphrase`, `keycloak-admin` | |
| **Job (Helm hook)** | `db-migration` | Runs `migration.sql` on install/upgrade |
| **Job (manual)** | `hostpath-permissions` | Fix hostPath ownership |
| **ClusterRole** | `pipeline-job-manager` | CRUD on `workflows`, `cronworkflows`, `pods`, `configmaps` |
| **ClusterRole/Role** | `keycloak-secret-reader/writer` | Cross-namespace secret sync |

### 4.3 Argo Workflows

Argo is installed as a separate Helm release at [devops/dependants/argo-workflows/](c:/visual%20layer/vl-camtek/devops/dependants/argo-workflows/) with:
- `namespaced: false` (cluster-wide)
- `auth-mode: server`
- `persistence: archive=false` (no workflow archive DB)

**Dynamic workflow submission** — no pre-defined `WorkflowTemplate`. Manifests are built at runtime in Python.

Submission code at [clustplorer/logic/argo_pipeline/argo_pipeline_creator.py:1002-1021](c:/visual%20layer/vl-camtek/clustplorer/logic/argo_pipeline/argo_pipeline_creator.py):

```python
def submit_argo_workflow(workflow_name: str, workflow_manifest: dict):
    config.load_incluster_config() if "KUBERNETES_SERVICE_HOST" in os.environ else config.load_kube_config()
    api = client.CustomObjectsApi()
    return api.create_namespaced_custom_object(
        group="argoproj.io", version="v1alpha1",
        namespace=Settings.VL_K8S_NAMESPACE,
        plural="workflows", body=workflow_manifest,
    )
```

**Manifest builders:**
- `create_single_step_argo_workflow` (lines 703-814) — whole pipeline in one pod
- `create_combined_partial_update_reindex_workflow` (lines 1024-1181) — multiple steps chained
- Container builders: `create_argo_cpu_container` / `create_argo_gpu_container`

**Higher-level Hera SDK workflows** (training, flywheel, catalog export) at [clustplorer/logic/common/hera_utils.py](c:/visual%20layer/vl-camtek/clustplorer/logic/common/hera_utils.py) — wraps volumes, affinity, tolerations, exit handlers.

### 4.4 Resource Sizing (auto-scaling)

CPU/memory auto-computed from dataset size in [argo_pipeline_creator.py:129-231](c:/visual%20layer/vl-camtek/clustplorer/logic/argo_pipeline/argo_pipeline_creator.py) using units = `n_images + n_objects + n_videos*80`:

| Units | CPU / Memory |
|-------|--------------|
| <1000 | 3 / 6Gi |
| <5000 | 4 / 8Gi |
| <10000 | 8 / 16Gi |
| <50000 | 8 / 32Gi |
| <100000 | 16 / 64Gi |
| ≥100000 | 16 / 128Gi |

GPU tiers: **standard** = 3 CPU / 14Gi / 1 GPU; **XFER (fine-tuning)** = 14 CPU / 96Gi / 1 GPU (requires `ssl=present` toleration).

### 4.5 Scheduling: Affinity + Tolerations

From [argo_pipeline_creator.py:319-380](c:/visual%20layer/vl-camtek/clustplorer/logic/argo_pipeline/argo_pipeline_creator.py):

```yaml
# CPU pipeline
nodeAffinity: role In [cpu-pipeline]
tolerations:
  - {key: role, value: pipeline, effect: NoSchedule}
  - {key: pipeline-size, value: big-node}   # if memory > 48Gi

# GPU pipeline
nodeAffinity: role In [gpu-pipeline, gpu-pipeline-ssl]
tolerations:
  - {key: nvidia.com/gpu, value: present}
  - {key: role, value: pipeline}
  - {key: ssl, value: present}              # XFER only
```

Feature-flag escape hatches for single-node clusters: `VL_K8S_NODE_AFFINITY_ENABLED`, `VL_K8S_NODE_TOLERATIONS_ENABLED`.

### 4.6 Scaling

- **Vertical**: per-workflow resource calc (above).
- **Horizontal on pipelines**: Argo spawns one pod per workflow — parallelism = cluster capacity.
- **HPA**: no Horizontal Pod Autoscaler on `clustplorer` backend (single deployment).
- **KEDA**: not configured. Queue worker relies on long polls, not event-driven scaling.

### 4.7 Pod Role Matrix

| Pod | Role |
|-----|------|
| `clustplorer` | **Scheduler** of workflows (no K8s-level scheduling, just API submission) |
| Argo `workflow-controller` | **Orchestrator** — watches Workflow CRDs, creates pods |
| Pipeline pods (dynamic) | **Executor** of pipe steps |
| `clustplorer` | **Coordinator** of task state (reads/writes `tasks` table) |
| `postgresql` | **State store** for datasets, tasks, queue |

---

## 5. End-to-End Flow: "Create Dataset"

A complete trace of a user creating a new dataset from the UI to completion.

```
┌──────────────┐   POST /api/v1/workflow/dataset/new     ┌─────────────┐
│  Frontend    │───────────────────────────────────────▶│ clustplorer │
│ (React/RTK)  │                                         │  (FastAPI)  │
└──────────────┘                                         └──────┬──────┘
                                                                │
                                                                ▼
                                                         DatasetDB.create()
                                                         → datasets row NEW

User uploads folders (chunked):
POST /api/v1/dataset/{id}/data/folder_upload/{trans_id}
   → S3 put_object → DatasetFolder row UPLOADING
   → last_chunk=True triggers background validation

User clicks "Process":
GET /api/v1/dataset/{id}/process
       ┌──────────────────────────────────────────────────────┘
       ▼
DatasetCreationTaskService.create_dataset_task()
    ├── TasksTable INSERT (task_type=DATASET_CREATION, status=RUNNING)
    └── ArgoPipeline.trigger_vl_argo_processing()
            ├── WorkflowInfo.extract_workflow_info()
            ├── auto-calculate CPU/memory from dataset size
            ├── build manifest (single-step or multi-step)
            └── CustomObjectsApi.create_namespaced_custom_object(group="argoproj.io")
                                         │
                                         ▼
                             ┌─────────────────────────┐
                             │ Argo Workflow Controller│
                             └───────────┬─────────────┘
                                         │
                         ┌───────────────┼───────────────┐
                         ▼               ▼               ▼
                   CPU Pipeline     GPU Pipeline     CPU Pipeline
                    (prepare)       (enrichment)      (indexer)
                         │               │               │
                         └───────────────┴───────────────┘
                               Shared PVC: /data
                                         │
Each @controller_step decorator calls:   │
    PipelineStatusEventsReporter         │
    + task_service.update_task_status()  │
    → UPDATE tasks SET progress_percentage=..., sub_status=... WHERE task_id=...
                                         │
                                         ▼
                             Dataset status = READY
                             Task status = COMPLETED

Frontend polls GET /api/v1/tasks?dataset_id=... every few seconds
```

### 5.1 Abort mid-flight

1. User clicks Cancel → `POST /api/v1/tasks/{id}/abort`
2. `_pre_abort` checks `metadata_.current_step` — if in `COMMIT_PHASE_STEPS` ({WRITE_TO_DB, PREPARE_FOR_READ, PUBLISH_MEDIA, FINALIZE_DATASET_CREATION, CLEANUP}) → HTTP 409 `TaskAbortInCommitPhaseError`
3. Otherwise: `subprocess.run(["kubectl", "delete", "workflow", workflow_name, ...])` at [dataset_creation_task_service.py:237-261](c:/visual%20layer/vl-camtek/vl/tasks/dataset_creation/dataset_creation_task_service.py)
4. Task row → status=ABORTED; dataset row → FATAL_ERROR

### 5.2 Retry

1. `POST /api/v1/tasks/{id}/retry` — only valid for FAILED or ABORTED
2. `_pre_retry` resets dataset to NEW, 0% progress
3. Task row: status=INITIALIZING, `metadata_.retry_count++`, clears `current_step`, saves `last_retry_at` + `previous_status`
4. `_post_retry` re-invokes the pipeline trigger path (same code as initial create)

### 5.3 Data Handoffs Between Pipe Steps

| Data | Format | Location | Producer → Consumer |
|------|--------|----------|---------------------|
| Raw input | S3 objects | `{S3_BUCKET}/{dataset_id}/` | upload API → download step |
| Downloaded files | Local files | `PIPELINE_ROOT/input/` | download → split_data |
| Image metadata | Parquet | `snapshots/image_data.parquet` | enrichment_data_prep → enrichment |
| Embeddings | Binary + CSV | `snapshots/atrain_features.dat` | enrichment → consolidation |
| Duplicates | Parquet | `snapshots/duplicates_data.parquet` | fastdup → issues_generator |
| Clusters | Parquet | `snapshots/clusters.parquet` | exploration → metadata |
| Final records | PostgreSQL rows | `datasets`, `images`, `objects`, ... | sync_data_to_local → prepare_for_read |
| Published media | S3 / CDN | `{S3_BUCKET}/{dataset_id}/thumbnails/` | publish_media → frontend |
| Metrics | JSON | `snapshots/pipeline_metrics.json` | reporter → S3 (observability) |

---

## 6. Orchestration & Patterns

### 6.1 Patterns Observed

| Pattern | Where |
|---------|-------|
| **Pipeline pattern** | `pipeline/controller/` — ordered dict of step functions composed into flows |
| **Template method** | `AppTaskBase` with 11 abstract hooks |
| **Repository** | `TasksRepository` + subclass per task type; mirrors source-of-truth tables |
| **Service layer** | One `*TaskService` per task type wrapping repository + side effects |
| **Factory (implicit)** | Flow registry `flow_map[flow_to_run]()` in `controller.py` |
| **Decorator-based AOP** | `@controller_step`, `@controller_flow` for cross-cutting concerns (timing, logging, status) |
| **Task queue / worker** | `task_queue` table + polling worker with `SELECT FOR UPDATE SKIP LOCKED` |
| **Manifest-as-code** | Argo workflow YAML built programmatically; Hera SDK for higher-level flows |

### 6.2 Orchestration Tools

- **Argo Workflows** — primary orchestrator. Pipelines are dynamically submitted CRDs, not pre-defined templates. Controller handles retries, pod cleanup, exit handlers.
- **Hera SDK** (`hera~=5.23.0`) — used for training, flywheel, model-catalog workflows. Higher-level Python API over the same Argo primitives.
- **Kubernetes Python client** (`kubernetes~=31.0.0`) — for raw CRD submission and `kubectl` fallbacks.
- **No Celery / Airflow / Prefect / Dagster / Temporal.**

### 6.3 Single-step vs Multi-step Workflow Selection

Driven by `VL_ARGO_PIPELINE_STRUCTURE` config:
- `single-step` — entire `full_pipeline_flow` in one CPU pod (no GPU)
- `multi-step` — chained CPU → GPU → CPU across three pod templates, sharing `/data` PVC
- `automatic` — `multi-step` iff `enrichment_config` requires GPU, else `single-step`

Decision in `WorkflowInfo.should_use_multistep()`.

---

## 7. Reliability & Observability

### 7.1 Error Handling

| Layer | Mechanism |
|-------|-----------|
| HTTP | Centralized handler registry [exception_handlers/registry.py](c:/visual%20layer/vl-camtek/clustplorer/web/exception_handlers/registry.py) maps exceptions → HTTP status (404/400/422/409/500) |
| External I/O (OpenFGA, Camtek gRPC) | Custom retry decorator with exponential backoff + jitter at [vl/common/openfga_client.py:26-65](c:/visual%20layer/vl-camtek/vl/common/openfga_client.py) — 3 retries, 1s initial, 2× backoff, ±10% jitter, only on 5xx/timeout |
| Task | `TaskAbortInCommitPhaseError`, `TaskNotInRetryableStateError`, `TaskAlreadyInFinalStateError` at [vl/tasks/exceptions.py](c:/visual%20layer/vl-camtek/vl/tasks/exceptions.py) |
| Pipeline step | `@controller_step` decorator wraps with `@log_exception_with_args` and routes to `handle_error_step` → `post_error_flow` |
| Workflow | Argo `onExit` handlers call `failure-handler` template (e.g., training failure cleanup) |
| Queue | Auto-retry up to `max_retries` with `retry_delay_seconds` cooldown at [task_queue/dao.py:157-179](c:/visual%20layer/vl-camtek/vldbaccess/task_queue/dao.py) |

### 7.2 Retries

- **User-level**: manual via `POST /api/v1/tasks/{id}/retry` — resets dataset + task state, re-submits workflow
- **Queue-level**: automatic via `mark_failed` → flips status back to PENDING if under max_retries
- **Worker crash recovery**: stale `PROCESSING` tasks with `processed_at < NOW - 300s` are reclaimed
- **External API**: exponential backoff in OpenFGA client
- **No dead-letter queue** — failed tasks remain in `tasks` table with status=FAILED, manually retriable

### 7.3 Logging

- Module-scoped loggers: `logger = logging_init.get_vl_logger(__name__)` — names follow `vl.root.<module>`
- Config: YAML at `$VL_HOME/$LOGGING_CONFIG_FILE` (default `flat-logging.yaml`); falls back to `basicConfig(level=Settings.LOG_LEVEL)`
- Init in [vl/common/logging_init.py](c:/visual%20layer/vl-camtek/vl/common/logging_init.py)
- Notable log lines: task create/update/abort/retry; Argo submission with dataset_id + workflow_name; pipeline step entry/exit with timing

### 7.4 Error Tracking

- **Sentry** — optional, gated by `Settings.SENTRY_OPT_OUT`. Setup at [vl/utils/sentry.py:62-123](c:/visual%20layer/vl-camtek/vl/utils/sentry.py). Tags: environment, dataset_id, execution_id, platform, python version. 100% trace sampling.

### 7.5 Monitoring

- **Kubernetes probes**: readinessProbe on `clustplorer` deployment ([clustplorer-deployment.yaml:212-219](c:/visual%20layer/vl-camtek/devops/visual-layer/templates/clustplorer-deployment.yaml))
- **Admin health-check tool**: [devops/vl-admin/vl_admin/common/health_check.py](c:/visual%20layer/vl-camtek/devops/vl-admin/vl_admin/common/health_check.py) — verifies kubectl, pods, services, storage classes, GPU plugin
- **No Prometheus metrics exporters found.** Argo UI (port 2746) is the main visibility into workflow state.
- **Pipeline metrics** written to `snapshots/pipeline_metrics.json` and uploaded to S3 (if `VL_K8S_PIPELINE_ENABLED`)

### 7.6 Status Tracking API

- `GET /api/v1/tasks?dataset_id=...` — paginated list with filter support
- `GET /api/v1/tasks/filters` — distinct filter values (dataset names, task types, created_by)
- Frontend polling (no WebSocket/SSE observed for task status; SSE exists for `/api/vl-chat/stream`)
- Task row carries: `status`, `progress_percentage`, `status_message`, `error_message`, `sub_status` JSONB, `start_time`, `end_time`, `metadata_` (workflow_name, current_step, retry_count)

### 7.7 Failure Scenarios & Recovery

| Scenario | Recovery |
|----------|----------|
| `clustplorer` pod restart | Task rows persisted in PostgreSQL; FE polls resume |
| Argo workflow pod OOM | Argo retries per Workflow spec (retryStrategy); if exhausted → task marked FAILED, user can retry |
| Queue worker crash | Other workers reclaim stale `PROCESSING` tasks after timeout |
| Abort during commit phase | Rejected with HTTP 409 — user must wait for WRITE_TO_DB → FINALIZE to complete |
| Partial data on failure | `post_error_flow` runs via Argo `onExit` → `handle_error_step` → notifications + cleanup |
| DB deadlock | Short transactions + autocommit minimize risk; `SELECT FOR UPDATE SKIP LOCKED` on queue prevents worker contention |
| Node taint/affinity mismatch | Workflow stays Pending — operator must fix node labels or disable `VL_K8S_NODE_AFFINITY_ENABLED` |

### 7.8 Authorization

- **OpenFGA** for fine-grained access control. Client at [vl/common/openfga_client.py](c:/visual%20layer/vl-camtek/vl/common/openfga_client.py)
- Permission enum [vldbaccess/base.py:135-143](c:/visual%20layer/vl-camtek/vldbaccess/base.py): READ, LIST, UPDATE, DELETE, ENRICH, MANAGE_ACCESS, SHARE_DATASETS
- Task listing filters out unauthorized datasets via `UserDB.check_authorized_user_async` in [vl/tasks/task_service.py:21-43](c:/visual%20layer/vl-camtek/vl/tasks/task_service.py)
- Workspace-scoped: every dataset has `organization_id` + `workspace_id` FKs

---

## 8. Key Insights & Potential Improvements

### Strengths
- **Clean separation** between Pipe (compute) and Task (tracking) — each evolves independently
- **Decorator-composed pipelines** keep step code readable while centralizing cross-cutting concerns (timing, status, exceptions)
- **Database-as-queue** avoids introducing Celery/Redis dependencies at the cost of sub-second latency — acceptable for minute-scale pipelines
- **Dynamic Argo manifests** enable per-execution resource sizing without templating hell
- **Commit-phase abort protection** prevents corrupted half-written datasets — non-trivial correctness property
- **Dual-status system** (TaskStatus + domain sub-status) gives the UI both coarse and granular progress

### Weaknesses / Risks
- **No Prometheus/OpenTelemetry metrics** — observability beyond logs is thin; Argo UI is the only workflow-state view
- **No dead-letter queue** — failures accumulate in `tasks` table; bulk retry/triage tooling is manual
- **`subprocess.run(["kubectl", ...])` for abort** — brittle dependency on kubectl binary; could use Kubernetes Python client directly
- **Frontend polls** rather than subscribes — unnecessary DB load at scale; SSE infrastructure already exists for chat
- **No HPA / KEDA** on the worker — vertical scaling only
- **No workflow archive** — cannot inspect old workflows after TTL expiry (Argo `persistence.archive=false`)
- **Mix of Hera SDK and raw manifest builders** — two styles to maintain; consider converging on Hera
- **Settings global singleton** is mutated across step boundaries, making step independence/testability harder

### Improvement Candidates
1. Add Prometheus `/metrics` endpoint on `clustplorer` + Argo metrics scraping
2. Introduce structured JSON logging with correlation IDs (task_id, workflow_name, dataset_id)
3. Replace `subprocess.run(["kubectl",...])` with `CustomObjectsApi.delete_namespaced_custom_object` for symmetry with submission
4. SSE or WebSocket endpoint for task updates — reduce polling load
5. Add workflow archive (enable Argo `persistence.archive=true` with dedicated PG schema) for audit/debug
6. Dead-letter table + admin UI for bulk triage of permanently failed tasks
7. Consider `tenacity` instead of the bespoke retry decorator — already a common Python choice

---

## Appendix A — Key File Reference

| Concern | File |
|---------|------|
| Pipeline flow registry | [pipeline/controller/controller.py](c:/visual%20layer/vl-camtek/pipeline/controller/controller.py) |
| Flow composition | [pipeline/controller/pipeline_flows.py](c:/visual%20layer/vl-camtek/pipeline/controller/pipeline_flows.py) |
| Step implementations | [pipeline/controller/pipeline_steps.py](c:/visual%20layer/vl-camtek/pipeline/controller/pipeline_steps.py) |
| Step/flow decorators | [pipeline/controller/controller_steps/controller_wrappers/impl_controller_wrappers.py](c:/visual%20layer/vl-camtek/pipeline/controller/controller_steps/controller_wrappers/impl_controller_wrappers.py) |
| Preprocess steps | [pipeline/preprocess/pipeline_preprocess.py](c:/visual%20layer/vl-camtek/pipeline/preprocess/pipeline_preprocess.py) |
| K8s job steps | [pipeline/k8s_job_steps/](c:/visual%20layer/vl-camtek/pipeline/k8s_job_steps/) |
| Argo workflow builder | [clustplorer/logic/argo_pipeline/argo_pipeline_creator.py](c:/visual%20layer/vl-camtek/clustplorer/logic/argo_pipeline/argo_pipeline_creator.py) |
| ArgoPipeline trigger | [clustplorer/logic/argo_pipeline/argo_pipeline.py](c:/visual%20layer/vl-camtek/clustplorer/logic/argo_pipeline/argo_pipeline.py) |
| Hera SDK helpers | [clustplorer/logic/common/hera_utils.py](c:/visual%20layer/vl-camtek/clustplorer/logic/common/hera_utils.py) |
| Training workflow | [clustplorer/logic/model_training/model_training_argo_manager.py](c:/visual%20layer/vl-camtek/clustplorer/logic/model_training/model_training_argo_manager.py) |
| Flywheel workflow | [clustplorer/logic/flywheel/flywheel_runner_argo_manager.py](c:/visual%20layer/vl-camtek/clustplorer/logic/flywheel/flywheel_runner_argo_manager.py) |
| Task base class | [vl/tasks/base/base_task.py](c:/visual%20layer/vl-camtek/vl/tasks/base/base_task.py) |
| Task enums | [vldbaccess/tasks/base/enums.py](c:/visual%20layer/vl-camtek/vldbaccess/tasks/base/enums.py) |
| Task DB schema | [vldbaccess/tasks/base/tasks_table.py](c:/visual%20layer/vl-camtek/vldbaccess/tasks/base/tasks_table.py) |
| Task service | [vl/tasks/task_service.py](c:/visual%20layer/vl-camtek/vl/tasks/task_service.py) |
| Dataset creation task | [vl/tasks/dataset_creation/dataset_creation_task_service.py](c:/visual%20layer/vl-camtek/vl/tasks/dataset_creation/dataset_creation_task_service.py) |
| Tasks API | [clustplorer/web/tasks/api.py](c:/visual%20layer/vl-camtek/clustplorer/web/tasks/api.py) |
| Dataset creation API | [clustplorer/web/api_dataset_create_workflow.py](c:/visual%20layer/vl-camtek/clustplorer/web/api_dataset_create_workflow.py) |
| Queue DAO | [vldbaccess/task_queue/dao.py](c:/visual%20layer/vl-camtek/vldbaccess/task_queue/dao.py) |
| Queue worker | [clustplorer/logic/queue_worker/worker.py](c:/visual%20layer/vl-camtek/clustplorer/logic/queue_worker/worker.py) |
| Exception registry | [clustplorer/web/exception_handlers/registry.py](c:/visual%20layer/vl-camtek/clustplorer/web/exception_handlers/registry.py) |
| Logging init | [vl/common/logging_init.py](c:/visual%20layer/vl-camtek/vl/common/logging_init.py) |
| Sentry init | [vl/utils/sentry.py](c:/visual%20layer/vl-camtek/vl/utils/sentry.py) |
| OpenFGA client | [vl/common/openfga_client.py](c:/visual%20layer/vl-camtek/vl/common/openfga_client.py) |
| Helm chart | [devops/visual-layer/templates/](c:/visual%20layer/vl-camtek/devops/visual-layer/templates/) |
| Argo chart | [devops/dependants/argo-workflows/](c:/visual%20layer/vl-camtek/devops/dependants/argo-workflows/) |
| Camtek client values | [devops/clients/camtek/values.yaml](c:/visual%20layer/vl-camtek/devops/clients/camtek/values.yaml) |

---

## Appendix B — Configuration Surface

**Core pipeline env vars** (injected into Argo workflow pods via `k8s-pipeline-config` ConfigMap + per-workflow env block):

| Variable | Purpose |
|----------|---------|
| `FLOW_RUN_ID` | Unique pipeline execution ID (UUID) |
| `DATASET_ID`, `DATASET_NAME`, `USER_ID` | Target entities |
| `PIPELINE_FLOW_TYPE` | PIPELINE / PARTIAL_UPDATE / REINDEX / RESTORE / ENRICHMENT / MODEL_TRAINING |
| `SOURCE_URI` | Input data location (s3://, nfs://, file://) |
| `PREPROCESS_SECTION` | `cpu` / `gpu` / `finalize` / `dry-run` — dispatch inside preprocess container |
| `PREPROCESS_STEPS` | Comma-separated step names |
| `VL_K8S_PIPELINE_ENABLED` | Toggles K8S vs local execution |
| `PREPROCESS_ENRICHMENT_CONFIG` | JSON-serialized enrichment model config |
| `DATASET_SOURCE_DIR` | On-prem local source dir |

**Core backend feature flags** (via `config` ConfigMap):

- `VL_ARGO_PIPELINE_ENABLED` — master toggle
- `VL_ARGO_PIPELINE_STRUCTURE` — `single-step` / `multi-step` / `automatic`
- `VL_K8S_PIPELINE_IMAGE`, `VL_GPU_K8S_PIPELINE_IMAGE` — container images
- `VL_K8S_NAMESPACE` — workflow namespace
- `VL_K8S_NODE_AFFINITY_ENABLED`, `VL_K8S_NODE_TOLERATIONS_ENABLED`
- `ARGO_WORKFLOW_SERVICE_ACCOUNT` — default `workflow-executor`
- `FLYWHEEL_ENABLED`, `DUCKDB_EXPLORATION_ENABLED`, `TRAIN_MODEL_ENABLED`, `MODELS_CATALOG_ENABLED`, `DATASET_CREATION_V2`
- `PG_URI`, `OPENFGA_API_URL`, `DATA_SERVER_GRPC_ENDPOINT`, `CAMTEK_TRAIN_API_ENDPOINT`

---

## Appendix C — Per-Pipe Breakdown: Triggers & On-Prem Requirements

**Added:** 2026-04-15. For each of the 11 pipeline flows registered in [pipeline/controller/controller.py:56-68](c:/visual%20layer/vl-camtek/pipeline/controller/controller.py): what it does, how to trigger it, and the incremental on-prem needs on top of the shared baseline below.

### C.0 Shared Baseline (applies to every pipe)

Before any pipe can run on-prem, the cluster needs:

- **Argo Workflows** (separate Helm release, cluster-scoped, `namespaced: false`, `auth-mode: server`)
- **PostgreSQL** (via `PG_URI`), **Keycloak** (OIDC), **OpenFGA** (authorization)
- **`clustplorer` Deployment** with ClusterRole `pipeline-job-manager` (CRUD on `workflows`, `pods`, `configmaps`)
- **ServiceAccount** `workflow-executor` (configurable via `ARGO_WORKFLOW_SERVICE_ACCOUNT`)
- **`config` ConfigMap** with `VL_ARGO_PIPELINE_ENABLED=true`, `VL_K8S_PIPELINE_IMAGE`, `VL_GPU_K8S_PIPELINE_IMAGE`, `VL_K8S_NAMESPACE`
- **`k8s-pipeline-config` ConfigMap** for pipeline pod env (embedder paths, PG URI)
- Per-workflow env injected by the builder: `FLOW_RUN_ID`, `DATASET_ID`, `USER_ID`, `PIPELINE_FLOW_TYPE`, `SOURCE_URI`

Each pipe below adds its own incremental requirements.

### C.1 `full_pipeline_flow` — end-to-end dataset creation

**Steps:** INIT → SETUP → ENRICHMENT → METADATA → PUBLISH (all 5 subflows) — [pipeline_flows.py:83-89](c:/visual%20layer/vl-camtek/pipeline/controller/pipeline_flows.py)

**Trigger:**
- **API:** `GET /api/v1/dataset/{dataset_id}/process` → [api_dataset_create_workflow.py:1070](c:/visual%20layer/vl-camtek/clustplorer/web/api_dataset_create_workflow.py)
- **Code path:** `process()` → `_process_dataset_creation()` → `ArgoPipeline.trigger_vl_argo_processing()` → `create_single_step_argo_workflow()` (single pod) or multi-step chain
- **Flow type enum:** `PipelineFlowType.PIPELINE` (default)
- **Task class:** `DatasetCreationTask`

**On-prem needs:**
- Full enrichment model set at `backend-efs-pvc` (embedders, captioning, tagging, detection) — ~28 GB
- **GPU node** (`role=gpu-pipeline`, `nvidia.com/gpu=present`) **if** enrichment_config requests ML models. With `VL_ARGO_PIPELINE_STRUCTURE=automatic` the backend auto-picks multi-step when GPU is needed
- **Shared `/data` PVC** (RWMany) if multi-step: CPU → GPU → CPU all mount the same volume
- Largest resource bucket: up to **16 CPU / 128 GiB** for CPU steps on ≥100k-unit datasets
- `datasets-storage-pvc` (RWO, 50Gi) for staging
- `duckdb-storage-pvc` (RWMany, 100Gi) for exploration/indexing

**Single-node escape hatches:** `VL_ARGO_PIPELINE_STRUCTURE=single-step` + `VL_K8S_NODE_AFFINITY_ENABLED=false` + `VL_K8S_NODE_TOLERATIONS_ENABLED=false`.

### C.2 `prepare_data_flow` — CPU-only prep subset

**Steps:** INIT + SETUP + `ENRICHMENT_DATA_PREP` + FINISH (no ML, no DB writes) — [pipeline_flows.py:92-105](c:/visual%20layer/vl-camtek/pipeline/controller/pipeline_flows.py). Two variants: standard and `PREPARE_DATA_STEPS_REINDEX` (reads snapshot from DB instead of downloading).

**Trigger:**
- **Never reached from a dedicated API endpoint.** It is the CPU-half of a multi-step workflow.
- Chosen by the manifest builder when `VL_ARGO_PIPELINE_STRUCTURE=multi-step` (or `automatic` + GPU enrichment present)
- **Flow type enum:** `PipelineFlowType.PIPELINE` or `PipelineFlowType.REINDEX` (switched at runtime — [pipeline_flows.py:213](c:/visual%20layer/vl-camtek/pipeline/controller/pipeline_flows.py))

**On-prem needs:**
- **CPU-only** node — cheapest of the three multi-step pods
- Access to `SOURCE_URI` (S3 / NFS / local)
- Shared `/data` PVC (output feeds the enrichment pod)
- No special env beyond baseline

### C.3 `enrichment_flow` — GPU-only ML inference

**Steps:** INIT + `ENRICHMENT` + FINISH — [pipeline_flows.py:108-112](c:/visual%20layer/vl-camtek/pipeline/controller/pipeline_flows.py). Runs captioning, tagging, detection, embedding generation.

**Trigger:**
- **Internal (multi-step chain).** No dedicated HTTP endpoint on its own.
- **Re-enrichment path:** `PipelineFlowType.ENRICHMENT` can be set when re-running enrichment over existing data — see [datasets_bl.py:334](c:/visual%20layer/vl-camtek/clustplorer/logic/datasets_bl.py)
- **Task class:** `EnrichmentTask` when invoked standalone

**On-prem needs (most demanding pipe):**
- **GPU node** with NVIDIA device plugin installed; labeled `role=gpu-pipeline` (or `gpu-pipeline-ssl` for XFER)
- Taints: `nvidia.com/gpu=present`, `role=pipeline`, (+ `ssl=present` for XFER)
- Resources: standard = **3 CPU / 14 GiB / 1 GPU**; XFER fine-tuning = **14 CPU / 96 GiB / 1 GPU**
- GPU pipeline container image (`VL_GPU_K8S_PIPELINE_IMAGE`) — CUDA/TensorRT base
- `backend-efs-pvc` for model weights
- Shared `/data` PVC to read prep output and write embeddings

### C.4 `indexer_flow` — CPU-only DB write subset

**Steps:** INIT + `ENRICHMENT_CONSOLIDATION` + METADATA + PUBLISH — [pipeline_flows.py:115-120](c:/visual%20layer/vl-camtek/pipeline/controller/pipeline_flows.py). The "close out" half of multi-step.

**Trigger:**
- **Internal (multi-step chain).** No direct API.
- **Flow type enum:** `PipelineFlowType.PIPELINE` or `PipelineFlowType.REINDEX` (REINDEX skips `PUBLISH_MEDIA` — [pipeline_flows.py:243-244](c:/visual%20layer/vl-camtek/pipeline/controller/pipeline_flows.py))

**On-prem needs:**
- CPU node only
- **PostgreSQL write access** (DB inserts happen here)
- `duckdb-storage-pvc` (RWMany, 100Gi) — indexes built here
- `datasets-storage-pvc` for temp
- S3 credentials for `PUBLISH_MEDIA` (thumbnail upload to `{S3_BUCKET}/{dataset_id}/thumbnails/`) — skipped in REINDEX

### C.5 `partial_update_flow` — add media to existing dataset

**Steps:** Full pipeline minus `ISSUE_GENERATOR` — [pipeline_flows.py:123-129](c:/visual%20layer/vl-camtek/pipeline/controller/pipeline_flows.py). Sets `MIN_NUM_OF_IMAGES=2` to allow small batches.

**Trigger:**
- **API:** `POST /api/v1/dataset/{dataset_id}/add_media` → [api_add_media.py:28](c:/visual%20layer/vl-camtek/clustplorer/web/api_add_media.py)
- **Also reachable via:** `_process_add_media()` in [api_dataset_create_workflow.py:1054-1067](c:/visual%20layer/vl-camtek/clustplorer/web/api_dataset_create_workflow.py)
- **Code path:** `trigger_processing(pipeline_flow_type=PARTIAL_UPDATE)` → `ArgoPipeline.trigger_vl_argo_processing()`
- **Manifest builder:** `create_argo_workflow()` or `create_combined_partial_update_reindex_workflow()` when `auto_reindex=True` — [argo_pipeline_creator.py:1024](c:/visual%20layer/vl-camtek/clustplorer/logic/argo_pipeline/argo_pipeline_creator.py)
- **Flow type enum:** `PipelineFlowType.PARTIAL_UPDATE`
- **Task class:** `MediaAdditionTask`

**On-prem needs:** Same as `full_pipeline_flow` (CPU + optional GPU based on enrichment_config). Existing dataset row must exist and be in a state that permits additions.

### C.6 `reindex_dataset_flow` — rebuild indexes over existing dataset

**Steps:** INIT + `STAGE_DATA_FROM_DB` + ENRICHMENT + METADATA + PUBLISH (no download) — [pipeline_flows.py:131-137](c:/visual%20layer/vl-camtek/pipeline/controller/pipeline_flows.py). Marked "DEV only" in the code.

**Trigger:**
- **API:** `POST /api/v1/dataset/{dataset_id}/reindex` → [api_add_media.py:204-253](c:/visual%20layer/vl-camtek/clustplorer/web/api_add_media.py)
- **Flow type enum:** `PipelineFlowType.REINDEX`
- **Manifest builder:** forced `create_single_step_argo_workflow()` (multi-step disabled for REINDEX — [argo_pipeline_creator.py:122](c:/visual%20layer/vl-camtek/clustplorer/logic/argo_pipeline/argo_pipeline_creator.py))
- **Task class:** `ReindexTask`
- Sets `SKIP_EXISTING_ENRICHMENT=False` and clears `PREPROCESS_IMAGE_TRANSFER`

**On-prem needs:**
- Single-pod execution, so one node with enough headroom for the full workload
- Read access to prior PostgreSQL data (staged from DB, not re-downloaded)
- GPU only if `enrichment_config` requests re-enrichment

### C.7 `restore_dataset_flow` — restore / clone from snapshot

**Steps:** START + `RESTORE_BASE_DB_DATA` + `PREPARE_FOR_READ` + `FINALIZE_DATASET_CREATION` + FINISH — [pipeline_flows.py:139-145](c:/visual%20layer/vl-camtek/pipeline/controller/pipeline_flows.py). No ML; DB-only replay.

**Trigger:**
- **API:**
  - `POST /api/v1/dataset/{dataset_id}/snapshot/{snapshot_id}/restore` — in-place
  - `POST /api/v1/dataset/{dataset_id}/snapshot/{snapshot_id}/clone` — creates cloned dataset row
  - Both in [api_dataset_snapshots.py:194-213](c:/visual%20layer/vl-camtek/clustplorer/web/api_dataset_snapshots.py)
- **Requires:** `SNAPSHOT_DATASET_ID` + `SNAPSHOT_DATASET_REVISION_ID` env vars
- **Flow type enum:** `PipelineFlowType.RESTORE`
- **Task class:** `SnapshotRestoreTask` (in-place) or `SnapshotCloneTask` (clone)

**On-prem needs:**
- **CPU-only** — lightest real pipe
- Access to snapshot artifacts — typically under the S3 bucket or `backend-efs-pvc` `snapshots/` directory
- PostgreSQL write access
- `duckdb-storage-pvc`

### C.8 `nop_flow` — no-op smoke test

**Steps:** START + FINISH — [pipeline_flows.py:162-165](c:/visual%20layer/vl-camtek/pipeline/controller/pipeline_flows.py)

**Trigger:**
- **CLI only:** `python -m pipeline.controller.controller --flow-to-run nop_flow` inside a pod/container
- Backend-side `nop_mode` flag on the manifest builder — [argo_pipeline_creator.py:601](c:/visual%20layer/vl-camtek/clustplorer/logic/argo_pipeline/argo_pipeline_creator.py) — used for workflow-structure validation
- **No Task row, no dedicated API endpoint**

**On-prem needs:** nothing beyond a runnable CPU pipeline container. Useful to confirm service account, RBAC, and ConfigMap plumbing before attempting a real dataset.

### C.9 `post_success_flow` — cleanup on success (Argo exit handler)

**Steps:** START + `CLEANUP` + FINISH — [pipeline_flows.py:147-151](c:/visual%20layer/vl-camtek/pipeline/controller/pipeline_flows.py). Removes temp files.

**Trigger:**
- **Never manually.** Wired as Argo workflow **exit handler** at [argo_pipeline_creator.py:789-796](c:/visual%20layer/vl-camtek/clustplorer/logic/argo_pipeline/argo_pipeline_creator.py)
- **Fixed resources:** 4 CPU / 4 GiB, CPU-only
- **No Task, no flow type enum**

**On-prem needs:** CPU image and a CPU node. Piggybacks on the parent workflow's service account + PVCs.

### C.10 `post_error_flow` — failure cleanup + notifications (Argo exit handler)

**Steps:** START + `HANDLE_ERROR` + FINISH — [pipeline_flows.py:154-158](c:/visual%20layer/vl-camtek/pipeline/controller/pipeline_flows.py). Sends notifications, leaves dataset in FATAL_ERROR.

**Trigger:**
- **Never manually.** Argo `onExit` handler — [argo_pipeline_creator.py:800-807](c:/visual%20layer/vl-camtek/clustplorer/logic/argo_pipeline/argo_pipeline_creator.py)
- Fixed 4 CPU / 4 GiB, CPU-only

**On-prem needs:**
- Notification endpoint(s) — admin/email/webhook config used by `handle_error_step`; wired via `config` ConfigMap and `vl/tasks/*/notifications`
- Otherwise same as `post_success_flow`

### C.11 `model_training_flow` — Camtek model training prep + trigger

**Steps:** `CREATE_SNAPSHOT` → `GET_DATASET_FOLDERS` → `CREATE_IMAGE_CLASS_MAPPING` → `UNITE_DB_CSV` → `UNITE_METADATA_JSON` → `TRIGGER_TRAINING_API` — [pipeline_flows.py:168-177](c:/visual%20layer/vl-camtek/pipeline/controller/pipeline_flows.py)

**Trigger:**
- **API:** `POST /api/v1/training` → [api_dataset_model_training.py:90-177](c:/visual%20layer/vl-camtek/clustplorer/web/api_dataset_model_training.py)
- **Code path:** `trigger_training()` → `ModelTrainingArgoPipeline.trigger_model_training_argo_workflow()` → `run_model_training_argo_workflow()` → [model_training_argo_manager.py:65](c:/visual%20layer/vl-camtek/clustplorer/logic/model_training/model_training_argo_manager.py)
- **Manifest builder:** **Hera SDK** (`HeraWorkflowConfig`) — [model_training_argo_manager.py:107-140](c:/visual%20layer/vl-camtek/clustplorer/logic/model_training/model_training_argo_manager.py) — different code path from the raw-manifest builders
- **Task class:** `TrainingTask`
- Fixed 4 CPU / 4 GiB, CPU image

**On-prem needs (Camtek-specific):**
- `CAMTEK_TRAIN_API_ENDPOINT` must be reachable from the cluster — this pipe preps data and kicks off training on the external Camtek Training Service
- `TRAIN_MODEL_ENABLED=true` feature flag
- `db-csv-exports-pvc` for CSV artifacts
- `ground-truth-pvc` if labels are needed
- `model-storage-pvc` (RWMany, 10Gi) for fine-tuned model output

### C.12 Bonus: Flywheel Pipeline (not in the 11, worth noting)

**What:** Active-learning loop combining dataset iteration + training.

**Trigger:**
- **API:** `POST /api/v1/flywheel/*` → [api_flywheel.py](c:/visual%20layer/vl-camtek/clustplorer/web/api_flywheel.py)
- **Manifest:** Hera SDK at [clustplorer/logic/flywheel/flywheel_runner_argo_manager.py](c:/visual%20layer/vl-camtek/clustplorer/logic/flywheel/flywheel_runner_argo_manager.py)
- **Task class:** `FlywheelTask`

**On-prem needs:** everything `model_training_flow` needs + `FLYWHEEL_ENABLED=true` + whatever the inner training cycle requires.

### C.13 Summary Matrix

| Pipe | Trigger path | Flow type enum | CPU | GPU | Task class | Key on-prem extras |
|---|---|---|---|---|---|---|
| `full_pipeline_flow` | `GET /dataset/{id}/process` | `PIPELINE` | ✓ | optional | `DatasetCreationTask` | All PVCs, optional GPU node |
| `prepare_data_flow` | multi-step CPU half | `PIPELINE`/`REINDEX` | ✓ | ✗ | same as parent | Shared `/data` PVC |
| `enrichment_flow` | multi-step GPU half | `ENRICHMENT` | ✗ | ✓ | `EnrichmentTask` | GPU node, NVIDIA plugin, model weights |
| `indexer_flow` | multi-step CPU close | `PIPELINE`/`REINDEX` | ✓ | ✗ | same as parent | PG write, DuckDB PVC, S3 (unless REINDEX) |
| `partial_update_flow` | `POST /dataset/{id}/add_media` | `PARTIAL_UPDATE` | ✓ | optional | `MediaAdditionTask` | Same as full pipeline |
| `reindex_dataset_flow` | `POST /dataset/{id}/reindex` | `REINDEX` | ✓ | optional | `ReindexTask` | Forced single-pod |
| `restore_dataset_flow` | `POST .../snapshot/.../restore\|clone` | `RESTORE` | ✓ | ✗ | `SnapshotRestoreTask` / `SnapshotCloneTask` | Snapshot artifacts + PG |
| `nop_flow` | CLI only | — | ✓ | ✗ | none | Useful smoke test |
| `post_success_flow` | Argo onExit | — | ✓ | ✗ | none | Parent workflow's SA/PVCs |
| `post_error_flow` | Argo onExit | — | ✓ | ✗ | none | Notification wiring |
| `model_training_flow` | `POST /training` | — (Hera) | ✓ | ✗ | `TrainingTask` | `CAMTEK_TRAIN_API_ENDPOINT`, `TRAIN_MODEL_ENABLED`, CSV/model/GT PVCs |
| `flywheel` (bonus) | `POST /flywheel/*` | — (Hera) | ✓ | ✗ | `FlywheelTask` | Everything training needs + `FLYWHEEL_ENABLED` |

---

*End of analysis.*
