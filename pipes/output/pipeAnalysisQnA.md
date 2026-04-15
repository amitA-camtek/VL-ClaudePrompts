# VL-Camtek Pipeline Q&A

**Date:** 2026-04-15
**Source analysis:** [pipeAnalysis.md](./pipeAnalysis.md)

---

## Question

Analyze what my options are to trigger a pipeline/task and what is needed to run the pipe on-prem.

---

## Answer

Based on [pipeAnalysis.md](./pipeAnalysis.md), here is a focused breakdown.

### Options to Trigger a Pipeline/Task

#### 1. HTTP API (primary, user-facing) — [pipeAnalysis.md:204-215](./pipeAnalysis.md#L204-L215)

All triggers flow through FastAPI endpoints in `clustplorer/web/`:

| Trigger | Endpoint | What it starts |
|---|---|---|
| Create dataset record | `POST /api/v1/workflow/dataset/new` | DB row only, no pipeline |
| Upload files | `POST /api/v1/dataset/{id}/data/folder_upload/{trans_id}` | S3 put + validation |
| **Start pipeline** | `GET /api/v1/dataset/{id}/process` | **Creates Task + submits Argo Workflow** |
| Add media | `POST /api/v1/dataset/{id}/add_media` | `partial_update_flow` |
| Abort | `POST /api/v1/tasks/{id}/abort` | `kubectl delete workflow` |
| Retry | `POST /api/v1/tasks/{id}/retry` | Resets state + re-submits |
| Train model | `POST /api/v1/dataset/*/training` | TrainingTask (Hera workflow) |
| Flywheel | `POST /api/v1/flywheel/*` | FlywheelTask |

#### 2. Scheduled — [pipeAnalysis.md:217-222](./pipeAnalysis.md#L217-L222)

Only **one CronJob**: `pipeline/pipeline_cleanup/cronJob.yaml`. No Airflow/Celery Beat. No business-logic schedules.

#### 3. Event-driven

**None.** The system is request/response + frontend polling ([pipeAnalysis.md:224-228](./pipeAnalysis.md#L224-L228)).

#### 4. Internal queue (not a direct user trigger) — [pipeAnalysis.md:177-190](./pipeAnalysis.md#L177-L190)

`task_queue` table polled by `clustplorer/logic/queue_worker/worker.py` using `SELECT ... FOR UPDATE SKIP LOCKED`. Used for background work, not for starting pipes.

#### 5. Direct Argo submission (bypass path)

Since manifests are built dynamically via `CustomObjectsApi.create_namespaced_custom_object` ([pipeAnalysis.md:286-294](./pipeAnalysis.md#L286-L294)), you *could* hit the Argo API directly or `kubectl create -f workflow.yaml` — but you'd skip the `tasks` row, so the UI won't see it and retry/abort won't work.

#### 6. Pipeline container as CLI (local/debug)

`python -m pipeline.controller.controller` with env vars (`PIPELINE_FLOW_TYPE`, `FLOW_RUN_ID`, `DATASET_ID`, `SOURCE_URI`, …) runs a flow outside Argo entirely. The `nop_flow` exists for this purpose ([pipeAnalysis.md:37](./pipeAnalysis.md#L37)).

---

### What's Needed to Run the Pipe On-Prem

#### Kubernetes cluster prerequisites — [pipeAnalysis.md:247-273](./pipeAnalysis.md#L247-L273)

**Installed components:**
- **Argo Workflows** (cluster-wide, separate Helm release at `devops/dependants/argo-workflows/`) — `namespaced: false`, `auth-mode: server`
- **nginx ingress controller** (for `visual-layer-ingress`)
- **NVIDIA device plugin** (for GPU enrichment) — checked by `devops/vl-admin/vl_admin/common/health_check.py`
- **Keycloak** (OIDC auth)
- **OpenFGA** (authorization)
- **PostgreSQL** — either as StatefulSet in-chart or external via `PG_URI`

**Storage (PVCs):**
- `backend-efs-pvc` — RWMany model + pipeline shared volume
- `duckdb-storage-pvc` — RWMany, 100Gi (FSX CSI)
- `datasets-storage-pvc` — RWO, 50Gi (hostPath)
- `model-storage-pvc` — RWMany, 10Gi
- `longhorn-data-enc-pvc` — LUKS-encrypted (on-prem specific)
- `ground-truth-pvc`, `db-csv-exports-pvc`

**RBAC:**
- `pipeline-job-manager` ClusterRole — CRUD on `workflows`, `cronworkflows`, `pods`, `configmaps`
- Service account `workflow-executor` (set via `ARGO_WORKFLOW_SERVICE_ACCOUNT`)

#### Node topology / labels — [pipeAnalysis.md:322-337](./pipeAnalysis.md#L322-L337)

Nodes must be labeled/tainted to match pipeline affinity:

```yaml
# CPU pipes expect:
labels:  { role: cpu-pipeline }
taints:  [ role=pipeline:NoSchedule, pipeline-size=big-node:NoSchedule ]

# GPU pipes expect:
labels:  { role: gpu-pipeline | gpu-pipeline-ssl }
taints:  [ nvidia.com/gpu=present, role=pipeline, ssl=present ]
```

**On-prem single-node escape hatch:** set `VL_K8S_NODE_AFFINITY_ENABLED=false` and `VL_K8S_NODE_TOLERATIONS_ENABLED=false` in the `config` ConfigMap.

#### Capacity per workflow — [pipeAnalysis.md:303-316](./pipeAnalysis.md#L303-L316)

Sizing auto-scales with dataset (`n_images + n_objects + n_videos*80`). Minimum node to handle anything serious: ≥16 CPU / 128Gi for CPU pods; GPU node needs 1 GPU / 14Gi for standard, 96Gi for XFER fine-tuning.

#### Required config — [pipeAnalysis.md:609-634](./pipeAnalysis.md#L609-L634)

Master toggles in `config` ConfigMap:
- `VL_ARGO_PIPELINE_ENABLED=true`
- `VL_ARGO_PIPELINE_STRUCTURE` = `single-step` | `multi-step` | `automatic`
- `VL_K8S_PIPELINE_IMAGE`, `VL_GPU_K8S_PIPELINE_IMAGE` (pipeline container images)
- `VL_K8S_NAMESPACE`
- `PG_URI`, `OPENFGA_API_URL`
- `DATA_SERVER_GRPC_ENDPOINT`, `CAMTEK_TRAIN_API_ENDPOINT` (Camtek integration)
- Feature flags: `FLYWHEEL_ENABLED`, `DUCKDB_EXPLORATION_ENABLED`, `TRAIN_MODEL_ENABLED`, `MODELS_CATALOG_ENABLED`, `DATASET_CREATION_V2`

Per-execution env (injected by the workflow builder): `FLOW_RUN_ID`, `DATASET_ID`, `USER_ID`, `PIPELINE_FLOW_TYPE`, `SOURCE_URI`, `PREPROCESS_SECTION`, `PREPROCESS_STEPS`, `PREPROCESS_ENRICHMENT_CONFIG`, `DATASET_SOURCE_DIR`.

#### Install path

1. Install Argo Workflows chart from `devops/dependants/argo-workflows/`
2. Install main chart from `devops/visual-layer/` with the on-prem overlay from `devops/clients/camtek/values.yaml`
3. Helm hook `db-migration` Job runs `migration.sql` on install/upgrade
4. `hostpath-permissions` Job (manual) fixes hostPath ownership for `datasets-storage-pvc`
5. Verify with `devops/vl-admin/vl_admin/common/health_check.py` (pods, services, storage classes, GPU plugin)

#### On-prem-specific considerations

- **`longhorn-data-enc-pvc`** + `longhorn-crypto-passphrase` secret — LUKS-encrypted storage is on-prem only
- **`image-proxy` Deployment** — serves images without going to S3/CDN
- **`adc-static` Deployment** — optional Camtek ADC output server
- **Single-node clusters**: disable affinity/tolerations via the escape-hatch flags; may also need `VL_ARGO_PIPELINE_STRUCTURE=single-step` to avoid multi-pod coordination over PVCs
- **No workflow archive** (`persistence.archive=false`) — old workflows disappear after TTL; plan for debug accordingly

---

### TL;DR Decision Tree

- **UI / normal use** → `GET /api/v1/dataset/{id}/process` (creates Task, submits Argo) — this is what the frontend calls.
- **Programmatic integration** → same REST endpoints as the UI. Nothing else is exposed.
- **Debug a single flow locally** → run the pipeline container directly with env vars; pick `nop_flow` or a real flow type.
- **Bypass for ops work** → submit Argo manifest directly via `kubectl` or Argo API, but you lose the Task UI.
- **On-prem minimum**: K8s + Argo + PG + Keycloak + OpenFGA + GPU plugin (if enrichment) + 8 PVCs + labeled nodes (or disable affinity) + `config` ConfigMap.
