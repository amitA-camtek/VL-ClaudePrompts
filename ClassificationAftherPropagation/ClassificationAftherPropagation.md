# ClassificationAfterLabelPropagation.md — Enable Classification After Label Propagation — Feature Design

> Last updated: 2026-04-05
> Feature branch: `feature/allow-reclassification-after-lp`

---

## 1. Project Overview

**Feature:** Per-dataset toggle to enable or disable model re-training after label propagation (flywheel) has completed.

**Problem:** After label propagation runs and images receive propagated labels, classification (model training) cannot be re-triggered on those images. Once a training task completes for a dataset, there is no mechanism to run a second training job — the "Train Model" button remains enabled but the backend has no guard against unintended re-runs, and there is no user control over whether re-training should be allowed.

**Solution:** Add a boolean flag `allow_reclassification` to the existing `FlywheelModelMetadata` (stored in the `datasets.enrichment_models` JSONB column). When `false` (the default), the backend rejects `POST /api/v1/training` with HTTP 409 if a COMPLETED training task already exists for the dataset. When `true`, re-training is permitted. A new `PATCH` endpoint allows users with UPDATE permission to toggle the flag. The frontend renders a `<Switch>` control adjacent to the "Train Model" button, visible only after the first training completes.

**Approach chosen:** Extend `FlywheelModelMetadata` inside the existing JSONB column — no schema migration, no new database column, minimal blast radius (6 files changed on backend, 5 on frontend).

---

## 2. Repository Structure

Files created or modified (relative to repo root):

```
vl_camtek/
├── vl/
│   └── common/
│       └── models/
│           └── enrichment_models.py                          # MODIFIED — add allow_reclassification field
├── clustplorer/
│   ├── logic/
│   │   ├── feature_checks.py                                # MODIFIED — add is_reclassification_allowed()
│   │   ├── flywheel/
│   │   │   └── base_flywheel_runner.py                      # MODIFIED — preserve toggle on re-apply
│   │   └── model_training/
│   │       └── validation.py                                # MODIFIED — add check_reclassification_allowed()
│   └── web/
│       ├── api_flywheel.py                                  # MODIFIED — add PATCH endpoint
│       └── api_dataset_model_training.py                    # MODIFIED — insert guard in trigger_training()
├── vldbaccess/
│   └── training_tasks_dao.py                                # MODIFIED — add get_training_tasks_by_dataset_and_status()
├── tests/
│   └── test_reclassification_toggle.py                      # CREATED — unit + integration tests
├── fe/
│   └── clustplorer/
│       └── src/
│           └── views/
│               └── components/
│                   └── ContainerHeader/
│                       └── TrainModel/
│                           ├── ReclassificationToggle.tsx    # CREATED — toggle switch component
│                           ├── useReclassificationSetting.ts # CREATED — mutation hook
│                           ├── TrainModel.tsx                # MODIFIED — wire toggle + derive props
│                           ├── TrainModelButton.tsx          # MODIFIED — updated disable logic + tooltip
│                           └── TrainModel.module.scss        # MODIFIED — toggle styles
```

---

## 3. Services Inventory

### Clustplorer API (Backend)
- **Entry point:** `clustplorer/web/__init__.py` (line ~260: `app = create_app(lifespan=clustplorer_lifespan)`)
- **Runner:** `clustplorer/web/runner.py`
- **Port:** `9999` (CLI arg `-p`, convention from Dockerfile/K8s)
- **Database:** PostgreSQL 16 (pgvector 0.8.0) — toggle stored in `datasets.enrichment_models` JSONB column
- **Relevant env vars:**
  - `PG_URI` — PostgreSQL connection string
  - `SKIP_FLYWHEEL_VALIDATION` — if `true`, bypasses the train-worthy check entirely (existing; also bypasses reclassification guard)
  - `TRAIN_MODEL_ENABLED` — global feature flag for training (existing)
  - `TRAIN_MODEL_ENABLED_EMAILS` — email allowlist for training (existing)
- **No new env vars introduced.**

### Clustplorer Frontend
- **Entry point:** `fe/clustplorer/src/index.tsx`
- **Dev port:** `3000` (CRA dev server)
- **Build tool:** `react-scripts 5.0.1` (Create React App)
- **API base URL:** `process.env.REACT_APP_API_ENDPOINT` (e.g. `http://localhost:9999` in dev)
- **No new env vars introduced.**

---

## 4. Communication Map

### 4.1 Synchronous (HTTP REST)

| Source | Target | Protocol | Method + Path | Auth | Status Codes | Description |
|--------|--------|----------|---------------|------|-------------|-------------|
| Frontend (`ReclassificationToggle`) | Clustplorer API | REST | `PATCH /api/v1/flywheel/{dataset_id}/reclassification-setting` | `SESSION` cookie / Bearer JWT | 200, 400, 403, 404, 422 | **NEW.** Update `allow_reclassification` flag in FLYWHEEL metadata |
| Frontend (`TrainModelButton`) | Clustplorer API | REST | `POST /api/v1/training` | `SESSION` cookie / Bearer JWT | 202, 403, 404, 409, 422, 500 | **MODIFIED.** Existing endpoint; new 409 response when toggle is off and completed training exists |
| Frontend (`TrainModel`) | Clustplorer API | REST | `GET /api/v1/training/tasks?dataset_id={id}` | `SESSION` cookie / Bearer JWT | 200 | **UNCHANGED.** Existing endpoint; used to derive `hasCompletedTraining` from `task.status === "COMPLETED"` |
| Frontend (dataset load) | Clustplorer API | REST | `GET /api/v1/explore/{dataset_id}/exploration_metadata` | `SESSION` cookie / Bearer JWT | 200 | **UNCHANGED.** Returns `dataset.enrichment_models` which includes the toggle value; no additional fetch needed |

### 4.2 Asynchronous (Events / Queues)

| Producer | Consumer | Mechanism | Description |
|----------|----------|-----------|-------------|
| `_apply_results()` in `base_flywheel_runner.py` | — | Direct DB write | **MODIFIED.** On flywheel re-apply, preserves previous `allow_reclassification` value in the new `FlywheelModelMetadata` written to `datasets.enrichment_models` JSONB |

No new events, queues, or async flows are introduced. The `PATCH` endpoint is synchronous and returns immediately after the JSONB update.

---

## 5. Domain Entities & Ownership

### Modified: `FlywheelModelMetadata` (Pydantic model, not a DB table)

**Location:** [vl/common/models/enrichment_models.py](vl/common/models/enrichment_models.py#L75)

| Field | Type | Default | New? | Description |
|-------|------|---------|------|-------------|
| `train_worthy` | `bool` | `False` | No | Whether flywheel labeling goal was met |
| `stats` | `dict \| None` | `None` | No | Flywheel progress statistics |
| `allow_reclassification` | `bool` | `False` | **Yes** | Whether re-training is allowed after first completed training |

**Storage:** Nested inside the `datasets` table's `enrichment_models` JSONB column at path:
```
datasets.enrichment_models
  → enrichment_models (dict keyed by EnrichmentModelStep)
    → FLYWHEEL (EnrichmentModel)
      → metadata (FlywheelModelMetadata)
        → allow_reclassification (bool)
```

**Lifecycle:**
1. Field does not exist until first flywheel apply
2. Set to `False` on first flywheel apply (via Pydantic default)
3. User changes it via `PATCH /api/v1/flywheel/{id}/reclassification-setting`
4. Preserved across subsequent flywheel re-applies by `_apply_results()`

### Unchanged: `training_tasks` table

| Column | Type | Relevance |
|--------|------|-----------|
| `id` | `UUID PK` | Used to identify tasks |
| `dataset_id` | `UUID` | Filtered by new DAO method |
| `status` | `TrainingTaskStatus` (`INIT`, `IN_PROGRESS`, `COMPLETED`, `FAILED`, `CANCELLED`) | New DAO checks for `COMPLETED` status specifically |

No schema change to this table. A new static method `get_training_tasks_by_dataset_and_status()` is added to `TrainingTasksDAO` to query it.

---

## 6. External Dependencies

**No new external dependencies introduced.**

- No new Python packages
- No new npm packages (Ant Design `Switch` and `Tooltip` are already available in `antd@5.11`)
- No new infrastructure services
- No new environment variables

---

## 7. Auth & Security

### New endpoint: `PATCH /api/v1/flywheel/{dataset_id}/reclassification-setting`

- **Authentication:** Same as all flywheel endpoints — `get_authorized_user` FastAPI dependency, which validates `SESSION` cookie or `Authorization: Bearer <JWT>` header through the multi-auth chain (API key → session → VL_AUTH → Keycloak OIDC)
- **Authorization:** Requires `AccessOperation.UPDATE` on the dataset. Enforced by explicit `UserDB.check_authorized_user(user, dataset_id, [AccessOperation.UPDATE])` check in the handler. Returns 403 if denied.
- **Input validation:** Pydantic `ReclassificationSettingRequest` model ensures `allow_reclassification` is a boolean. FastAPI returns 422 for malformed requests.
- **CORS:** No change — inherits the existing `allow_origins=["*"]` configuration from the app-level CORS middleware.
- **Rate limiting:** None (consistent with all other endpoints in the codebase).
- **No sensitive data:** The toggle is a simple boolean with no PII or secret implications.

### Modified endpoint: `POST /api/v1/training`

- **No auth changes.** The new `check_reclassification_allowed()` guard runs after existing auth checks (operation permission + dataset access + train-worthy validation).
- **New error response:** HTTP 409 with `detail: "Re-classification after label propagation is disabled for this dataset"`. This does not leak sensitive information.

---

## 8. Infrastructure & DevOps

### Migration steps

**None required.** The toggle is stored in the existing `datasets.enrichment_models` JSONB column. JSONB columns accept arbitrary keys without schema changes. The Pydantic model provides the schema contract with a `False` default for backward compatibility.

Optional data backfill (not required — Pydantic default handles missing keys):
```sql
UPDATE datasets
SET enrichment_models = jsonb_set(
    enrichment_models,
    '{enrichment_models,FLYWHEEL,metadata,allow_reclassification}',
    'false'::jsonb
)
WHERE enrichment_models->'enrichment_models'->'FLYWHEEL'->'metadata' IS NOT NULL;
```

### Feature flag

No new feature flag. The toggle is per-dataset and self-contained:
- If `allow_reclassification` is missing from JSONB → defaults to `False` → re-training blocked (conservative)
- If `SKIP_FLYWHEEL_VALIDATION` env var is `true` → reclassification guard is bypassed entirely (existing escape hatch)
- If `TRAIN_MODEL_ENABLED` is `false` → the entire Train Model button is hidden, toggle never rendered

### Rollback plan

1. **Revert backend PR:** Remove the `allow_reclassification` field from `FlywheelModelMetadata`, remove the guard from `trigger_training()`, remove the PATCH endpoint. Orphaned `allow_reclassification` keys in JSONB are silently ignored by Pydantic (`model_config` does not have `extra = "forbid"`) [UNCLEAR — verify that `FlywheelModelMetadata` does not forbid extra fields; if it does, set `extra = "ignore"` before reverting].
2. **Revert frontend PR:** Remove `ReclassificationToggle.tsx`, `useReclassificationSetting.ts`, revert `TrainModel.tsx` and `TrainModelButton.tsx` changes. No build artifacts to clean up.
3. **No data migration needed on rollback.** JSONB keys with `allow_reclassification` remain but are inert.

### Deploy order

1. **Backend PR first** (tasks 1–9) — must be deployed before frontend because the frontend calls the new PATCH endpoint.
2. **Frontend PR second** (tasks 10–16) — can be deployed any time after backend is live.
3. No database migration step between deployments.

---

## 9. Key Business Flows

### Flow: User enables re-classification after label propagation

```
Preconditions:
  - Dataset status: READY
  - Flywheel (label propagation) has been applied (FLYWHEEL key exists in enrichment_models)
  - At least one training task with status COMPLETED exists for the dataset

[1] User sees ContainerHeader with "Train Model" button DISABLED
    → TrainModelButton reads dataset.enrichment_models.enrichment_models.FLYWHEEL.metadata.allow_reclassification
    → Value is false (or undefined → defaults to false)
    → disabled = !hasFlywheel || (hasCompletedTraining && !allowReclassification) → true
    → Tooltip shows: "Enable 'Allow Re-Training' to train again"

[2] User sees ReclassificationToggle with <Switch> UNCHECKED
    → ReclassificationToggle visible because hasCompletedFlywheel=true AND hasCompletedTraining=true
    → Ant Design Switch checked={false}
    → Label text: "Allow Re-Training"

[3] User clicks the Switch
    → onChange(true) fires
    → useReclassificationSetting.toggle(true) called
    → axios.patch("${API_BASE}/api/v1/flywheel/${datasetId}/reclassification-setting",
        { allow_reclassification: true })

[4] Backend: PATCH /api/v1/flywheel/{dataset_id}/reclassification-setting
    → Handler validates: dataset exists (404 if not), user has UPDATE access (403 if not),
      FLYWHEEL metadata exists (400 if not)
    → Reads dataset.enrichment_models via DatasetDB.get_by_id()
    → Navigates to enrichment_models.get_model_step(FLYWHEEL).metadata
    → Sets metadata.allow_reclassification = true
    → Calls DatasetDB.update(dataset_id, enrichment_models=updated_config)
    → PostgreSQL: UPDATE datasets SET enrichment_models = $1 WHERE id = $2
    → Returns 200: { dataset_id: "...", allow_reclassification: true }

[5] Frontend: onSuccess callback
    → invalidateActiveQueryByOperationId(queryClient, "getDatasetApiV1DatasetsDatasetIdGet")
    → invalidateActiveQueryByOperationId(queryClient, "getExplorationMetadataApiV1ExploreDatasetIdExplorationMetadataGet")
    → These invalidations trigger React Query to re-fetch the dataset
    → notification.success({ message: "Model re-training enabled" })

[6] Redux store updates with fresh dataset containing allow_reclassification=true
    → TrainModel re-renders
    → TrainModelButton: disabled = !hasFlywheel || (true && !true) = false → ENABLED
    → ReclassificationToggle: Switch checked={true}
    → User can now click "Train Model" to trigger a second training
```

### Flow: User attempts to train when toggle is OFF (blocked)

```
Preconditions:
  - Dataset status: READY
  - Flywheel applied, allow_reclassification=false (default)
  - One training task with status COMPLETED exists

[1] User bypasses frontend (curl / API client):
    POST /api/v1/training
    Body: { "dataset_id": "<uuid>", "model": "some_model" }

[2] Backend handler trigger_training() executes:
    → check_operation_permission("training") → ALLOWED (no blocking tasks)
    → DatasetDB.get_by_id(dataset_id) → dataset found
    → UserDB.check_authorized_user() → authorized
    → is_dataset_train_worthy(dataset, user) → True (flywheel goal met)
    → check_reclassification_allowed(dataset, dataset_id):
      → is_reclassification_allowed(dataset) → False
        (enrichment_models.FLYWHEEL.metadata.allow_reclassification == False)
      → TrainingTasksDAO.get_training_tasks_by_dataset_and_status(dataset_id, COMPLETED)
        → SQL: SELECT id FROM training_tasks
                WHERE dataset_id = :dataset_id AND status = 'COMPLETED' LIMIT 1
        → Returns 1 row
      → RAISES HTTPException(status_code=409,
          detail="Re-classification after label propagation is disabled for this dataset")

[3] Response: HTTP 409
    { "detail": "Re-classification after label propagation is disabled for this dataset" }

[4] No training_tasks row created. No Argo workflow triggered. No side effects.
```

### Flow: First training (always allowed regardless of toggle)

```
Preconditions:
  - Flywheel applied, allow_reclassification=false (default)
  - NO training tasks exist for this dataset

[1] POST /api/v1/training → trigger_training()
    → check_reclassification_allowed(dataset, dataset_id):
      → is_reclassification_allowed(dataset) → False
      → TrainingTasksDAO.get_training_tasks_by_dataset_and_status(dataset_id, COMPLETED)
        → Returns 0 rows
      → Guard PASSES (no completed training to block)
    → Proceeds to create training_tasks row, trigger Argo workflow
    → Returns 202: { task_id: "..." }
```

### Flow: Flywheel re-apply preserves toggle

```
Preconditions:
  - Dataset has allow_reclassification=true (user previously enabled it)
  - User runs flywheel again on the same dataset

[1] Flywheel cycle completes → _apply_results(processing_task_id)
[2] base_flywheel_runner.py reads previous FLYWHEEL metadata:
    → previous_flywheel = enrichment_config.enrichment_models.get(EnrichmentModelStep.FLYWHEEL)
    → previous_allow_reclassification = previous_flywheel.metadata.allow_reclassification → True
[3] Constructs new FlywheelModelMetadata:
    → FlywheelModelMetadata(
        stats=..., train_worthy=...,
        allow_reclassification=True  ← preserved from previous
      )
[4] Writes updated enrichment_models to datasets table
[5] User's preference survives the re-apply
```

---

## 10. Architecture Risks & Notes

| Risk | Severity | Mitigation |
|------|----------|------------|
| **Toggle resets on flywheel re-apply** if preservation code is missing or buggy | High | Explicit test `test_apply_results_preserves_allow_reclassification` covers this. The preservation reads from the previous `EnrichmentModel` object before overwriting, so a null-safe fallback to `False` is included. |
| **JSONB nesting depth** — `dataset.enrichment_models.enrichment_models.FLYWHEEL.metadata.allow_reclassification` is 5 levels deep | Medium | Acceptable for a per-dataset flag read only in 2 places (toggle component + validation function). Any deeper and it should be a column. |
| **SQL queryability** — querying "all datasets with reclassification enabled" requires a JSONB path expression | Low | Not a current requirement. If needed: `WHERE enrichment_models->'enrichment_models'->'FLYWHEEL'->'metadata'->>'allow_reclassification' = 'true'`. No index needed for the current feature. |
| **No optimistic update on toggle** — switch shows loading spinner during round trip | Low | Round trip is ~100ms (single JSONB update). The alternative (optimistic update on deeply nested JSONB in React Query cache) is fragile and not worth the complexity. |
| **Frontend `any` typing on `enrichment_models`** — no compile-time safety on nested paths | Medium | The `Dataset` interface in `types.ts` types `enrichment_models` as `{ enrichment_models: any }`. The `ReclassificationToggle` receives the metadata via a typed prop interface, which provides runtime safety at the component boundary. Full type safety would require a `Dataset` type overhaul [UNCLEAR — this is pre-existing tech debt, not introduced by this feature]. |
| **`Pydantic extra fields on rollback`** — if `FlywheelModelMetadata` forbids extra fields, orphaned `allow_reclassification` keys would cause deserialization errors after revert | Medium | Verified: `FlywheelModelMetadata` extends `BaseModel` with no `model_config = ConfigDict(extra="forbid")`. Pydantic v2 default is `extra="ignore"`, so orphaned keys are silently dropped. |
| **Race condition: PATCH toggle + concurrent flywheel re-apply** — if a user toggles while flywheel is writing `_apply_results`, the JSONB update could be overwritten | Low | The flywheel runner reads the previous value and carries it forward. If the toggle PATCH lands between the flywheel's read and write, the flywheel will carry forward the old value. This is a narrow window and the user can re-toggle. No locking is necessary for this UX. |
| **No operation permission integration** — the `TrainingPermissionChecker` does not check the toggle | Low | By design. The permission checker runs on `GET /api/v1/user_config` to determine SHOW/HIDE/GREY_OUT for the feature flag. Adding a check there would require an async DAO call (completed tasks query) on every user-config load for every dataset. Instead, the guard lives only in `trigger_training()` and the frontend button disable logic. |

---

## 11. Conventions & Standards

### Naming

| Item | Name | Convention followed |
|------|------|-------------------|
| Pydantic field | `allow_reclassification` | `snake_case`, matches `train_worthy` sibling field in `FlywheelModelMetadata` |
| API endpoint | `PATCH /api/v1/flywheel/{dataset_id}/reclassification-setting` | `kebab-case` path, under `/flywheel/` prefix matching all flywheel endpoints, `PATCH` for partial update |
| Request model | `ReclassificationSettingRequest` | PascalCase, `*Request` suffix matching `TrainingTriggerRequest` |
| Response model | `ReclassificationSettingResponse` | PascalCase, `*Response` suffix matching `TriggerTrainingResponse` |
| Python helper | `is_reclassification_allowed()` | `snake_case`, `is_*` boolean predicate, in `feature_checks.py` alongside `flywheel_results_train_worthy()` |
| Python guard | `check_reclassification_allowed()` | `snake_case`, `check_*` raising function, in `validation.py` alongside `is_dataset_train_worthy()` |
| DAO method | `get_training_tasks_by_dataset_and_status()` | `snake_case`, `get_*_by_*` query pattern matching `get_inprogress_tasks()` |
| React component | `ReclassificationToggle` | PascalCase, in `TrainModel/` directory alongside `TrainModelButton` |
| React hook | `useReclassificationSetting` | `camelCase` with `use` prefix, in `TrainModel/` directory alongside `useTriggerTraining` |
| SCSS class | `.reclassificationToggle`, `.reclassificationLabel` | `camelCase`, inside `.TrainModel` block matching `.trainModelButton` |
| Test file | `test_reclassification_toggle.py` | `snake_case`, `test_*` prefix, in `tests/` directory |

### Error codes

| Code | Meaning | Used by |
|------|---------|---------|
| 200 | Toggle updated | `PATCH .../reclassification-setting` |
| 400 | Flywheel not applied to dataset | `PATCH .../reclassification-setting` |
| 403 | User lacks UPDATE permission | `PATCH .../reclassification-setting` |
| 404 | Dataset not found | `PATCH .../reclassification-setting` |
| 409 | Re-classification disabled + completed training exists | `POST /api/v1/training` (new response) |
| 422 | Invalid request body | `PATCH .../reclassification-setting` (Pydantic) |

---

## 12. Glossary

| Term | Definition |
|------|------------|
| **Label Propagation (LP)** | The active learning loop (also called "Flywheel") where a user labels seed samples, an SVM model propagates labels to unlabeled images, and the user reviews predictions iteratively. Implemented in `vl/algo/label_propagation/flywheel.py`. |
| **Flywheel** | Synonym for Label Propagation. The multi-cycle loop of: seed → train SVM → predict → review → retrain. Managed by `BaseFlywheelRunner` in `clustplorer/logic/flywheel/base_flywheel_runner.py`. |
| **`flywheelStatus`** | The current state of a flywheel run. Stored as `result_message` (TEXT) in the `processing_tasks` table, linked via `lp_flow.processing_task_id`. Possible values: `INIT`, `RUNNING`, `PAUSED_FOR_REVIEW`, `RESUME_FLOW`, `CYCLE_RUN_FAILURE`, `APPLY_MODEL_TO_DATASET`, `FAILED`, `ABORTED`, `COMPLETED`. Read on the frontend via `GET /api/v1/flywheel/{dataset_id}`. |
| **`allow_reclassification`** | The new boolean field on `FlywheelModelMetadata` (default `False`). Controls whether a second `POST /api/v1/training` is allowed after a COMPLETED training exists. Stored in `datasets.enrichment_models` JSONB at path `.enrichment_models.FLYWHEEL.metadata.allow_reclassification`. |
| **Classification** | In this codebase, synonymous with "model training." There is no separate "classify" endpoint. Training is triggered via `POST /api/v1/training`, which creates an Argo Workflow that calls the Camtek gRPC training service. |
| **Re-classification** | A second (or subsequent) model training run on a dataset that already has a COMPLETED training task. This is the capability gated by the `allow_reclassification` toggle. |
| **Train-worthy** | A dataset property indicating that the flywheel labeling goal has been fully met (`FlywheelModelMetadata.train_worthy == True`). Prerequisite for training. Checked by `flywheel_results_train_worthy()` in `feature_checks.py`. |
| **`enrichment_models`** | JSONB column on the `datasets` table storing a dict of `EnrichmentModelStep → EnrichmentModel`. Keys include `FLYWHEEL`, `CAPTION_IMAGES`, `IMAGE_TAGGING`, etc. The FLYWHEEL entry's `metadata` field holds `FlywheelModelMetadata`. |
| **`EnrichmentModelStep.FLYWHEEL`** | Enum key identifying the flywheel enrichment in the `enrichment_models` dict. Defined in `vl/common/models/enrichment_models.py`. |
| **`_apply_results()`** | Method on `BaseFlywheelRunner` that writes flywheel predictions to the `labels` table, updates `datasets.enrichment_models` with new `FlywheelModelMetadata`, regenerates `flat_similarity_clusters`, and sets dataset status back to READY. The preservation logic for `allow_reclassification` is added here. |
| **`TrainingTasksDAO`** | Data Access Object for the `training_tasks` table. Located in `vldbaccess/training_tasks_dao.py`. New method `get_training_tasks_by_dataset_and_status()` added to query completed tasks. |
| **Operation Permission** | Backend-only guard system (`clustplorer/logic/operation_permissions/`) that checks task-level blocking and feature flags. The reclassification guard is intentionally NOT integrated here to avoid an extra DB query on every permission evaluation. |
