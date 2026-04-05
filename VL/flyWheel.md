# Flywheel Mechanism Overview

## What is Flywheel?

The flywheel is a **semi-automated label propagation system** that leverages user-provided seed labels to iteratively expand annotations across a dataset with minimal user effort. It combines machine learning with active learning—asking users to review high-uncertainty predictions.

---

## Architecture & Key Components

### **Core Files**

| File | Purpose |
|------|---------|
| `vldbaccess/flywheel_db.py` | Database layer - manages flows, cycles, results |
| `vl/tasks/flywheel/flywheel_task.py` | Task definition & status mapping |
| `vl/tasks/flywheel/flywheel_task_service.py` | Task service for CRUD operations |
| `clustplorer/logic/flywheel/base_flywheel_runner.py` | Runner logic - orchestrates cycle loop |
| `clustplorer/logic/feature_manager/calculators/dataset_calculator.py` | Feature flags for UI |
| `vl/algo/label_propagation/flywheel.py` | Core algorithm (Flywheel.run_cycle) |
| `vl/algo/label_propagation/flywheel_configuration.py` | Configuration settings |

---

## How Flywheel Works: Client → Execution Flow

### **1. Client Initiates Flywheel**

```python
# Called via API endpoint
await start_flywheel_run(
    dataset_id=dataset_id,
    user_id=user_id,
    seed_id=seed_id,
    flywheel_configuration=config  # Optional
)
```

**Backend Actions:**
- ✓ Validates seed has ≥2 labels with minimum samples per label (`FLYWHEEL_REQUIRED_SEED_SAMPLES_PER_LABEL`)
- ✓ Creates `LpFlow` record linking:
  - Dataset
  - Seed annotation set
  - Label categories
  - Total media count
  - Flywheel configuration
- ✓ Creates `ProcessingTask` with status `INIT`
- ✓ Creates `FlywheelTask` via `FlywheelTaskService.create_flywheel_task()`
- ✓ Populates initial seed samples into `LpCycleResults` table with `source='SEED'`

**Database Tables Involved:**
- `LpFlow` - Flow metadata
- `ProcessingTask` - Async task tracking
- `FlywheelTask` - Flywheel-specific task info
- `LpCycleResults` - Result history per cycle

---

### **2. Task Execution (Background Job)**

`BaseFlywheelRunner.__call__()` executes (triggered by task queue):

```python
def __call__(
    self,
    pre_cycle_handler=None,
    cycle_result_handler=None,
):
    flow = self._get_flow()
    context = self._get_context(flow.label_ids)
    completed = False
    
    while not completed:
        # Cycle loop runs until done or user review needed
        sure_set, question_set, completed = self._run(
            context=context,
            processing_task_id=processing_task_id,
            pre_cycle_handler=pre_cycle_handler,
            cycle_result_handler=cycle_result_handler,
            n_questions_asked=n_questions_asked,
            flywheel_configuration=flow.flywheel_configuration,
        )
        
        if question_set:
            # Pause for user review
            break
```

**Per-Cycle Logic:**
1. Runs `Flywheel.run_cycle()` → produces:
   - `sure_set`: High-confidence auto-labels (≥ confidence threshold)
   - `question_set`: Uncertain samples needing user review
   - `completed`: Flag indicating goal reached or budget exhausted

2. Publishes results to `LpCycleResults` via `publish_result()`

3. **If questions exist:**
   - Sets task status → `PAUSED_FOR_REVIEW`
   - Stops execution
   - Waits for user annotations

4. **If completed:**
   - Calls `_apply_results()` (see Step 4 below)

---

### **3. User Review**

Client polls for review questions:

```python
# GET /flywheel/review/{flow_id}
# Returns question samples grouped by label
{
    "label_id": "...",
    "samples": [
        {"media_id": "...", "confidence": 0.65, "suggested_label": "defect"},
        {"media_id": "...", "confidence": 0.72, "suggested_label": "ok"}
    ]
}
```

User submits review results:

```python
await submit_sample_review(
    flow_id=flow_id,
    sample_ids=[...],
    review_result=ReviewResult.CORRECT  # or INCORRECT | REASSIGN | IGNORE
)
```

**Backend Actions:**
- Updates `LpCycleResults.result` (e.g., `CORRECT`, `INCORRECT`)
- Updates `sure` flag based on result
- Ready to resume next cycle

---

### **4. Completion**

When goal is met (e.g., `total_annotated >= goal`):

```python
await handle_apply_model_to_dataset_request(flow_id)
```

**Backend Actions:**
- Checks if goal achieved
- Calls `apply_results_to_db()`:
  - Creates snapshot fragment (`FragmentType.FLYWHEEL`)
  - Inserts all flywheel labels into `labels` table with `source_id='vl_flywheel_v00'`
  - Updates enrichment model metadata (train-worthy flag)
  - Marks `ProcessingTask` → `COMPLETED`
  - Cleans temporary workdir

---

## UI Feature Flag Integration

In `dataset_calculator.py`:

```python
# Note: FLYWHEEL is handled by FlywheelFeatureCalculator with tri-state logic
# (HIDE if disabled, GREY_OUT if tasks running or not ready, SHOW otherwise)

self._add_feature(
    features,
    Features.TRAIN_WORTHY,
    feature_checks.flywheel_results_train_worthy(user, dataset),
)
```

**Tri-State Logic:**
- **HIDE**: Flywheel disabled for organization/user
- **GREY_OUT**: Flywheel tasks running or not ready (no valid seed)
- **SHOW**: Ready to start/resume

---

## Client Role Summary

| Step | Client Action | Backend Response |
|------|--------------|------------------|
| **1. Start** | POST `/flywheel/start` with `seed_id` | Creates flow + task, returns `flow_id` |
| **2. Monitor** | GET `/flywheel/status/{flow_id}` | Returns `INIT`, `RUNNING`, `PAUSED_FOR_REVIEW`, `COMPLETED` |
| **3. Get Questions** | GET `/flywheel/review/{flow_id}` | Returns uncertain samples grouped by label |
| **4. Submit Reviews** | POST `/flywheel/review` with answers | Updates results, auto-resumes if all answered |
| **5. Apply** | POST `/flywheel/apply/{flow_id}` | Persists all labels to dataset |
| **6. Check Readiness** | GET `/features` (includes `FLYWHEEL`) | Returns tri-state feature visibility |

---

## Flywheel Status States

From `FlywheelStatus` enum:

- **INIT** → Initializing
- **RESUME_FLOW** → Resuming from pause
- **PAUSED_FOR_REVIEW** → Waiting for user annotations
- **APPLY_MODEL_TO_DATASET** → Applying results to dataset
- **COMPLETED** → Done
- **REJECTED** → User aborted

---

## Key Configuration

From `Settings`:

```python
Settings.FLYWHEEL_REQUIRED_SEED_SAMPLES_PER_LABEL  # Min samples per label to start
Settings.FLYWHEEL_BASE_CONFIGURATION  # Default run config
Settings.FLYWHEEL_TEMP_DIR  # Temp working directory
```

---

## Summary

**The Flywheel is an iterative label propagation loop:**

1. **Client** uploads seed labels (manually annotated subset)
2. **Backend** validates seed quality and creates flow
3. **Algorithm** runs cycles: labels high-confidence samples automatically, flags uncertain ones for review
4. **User** reviews uncertain predictions (active learning)
5. **Backend** incorporates feedback, continues cycles until goal/budget reached
6. **Client** applies finalized labels to dataset

**Benefits:**
- Reduces manual annotation burden by 70-80%
- Leverages existing labels to expand coverage
- Incorporates user feedback in real-time
- Transparent uncertainty quantification
