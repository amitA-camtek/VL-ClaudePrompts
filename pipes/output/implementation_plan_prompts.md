# VL-Camtek On-Prem Migration — Implementation Plan with Claude Prompts

**Purpose:** Step-by-step implementation plan. Each step includes a Claude Code prompt that can be copy-pasted to execute the work.

**Prerequisites:**
- Read `on_prem_pipes_design.md` in full before starting
- Have the vl-camtek repo checked out
- Working PostgreSQL instance accessible

---

## Table of Contents

1. [Step 1 — Database Migration](#step-1--database-migration)
2. [Step 2 — Pipeline Jobs DAO](#step-2--pipeline-jobs-dao)
3. [Step 3 — Process Manager Core](#step-3--process-manager-core)
4. [Step 4 — Modify Trigger Path (datasets_bl.py)](#step-4--modify-trigger-path)
5. [Step 5 — Modify Abort Path](#step-5--modify-abort-path)
6. [Step 6 — Update Task Cleanup Watchdog](#step-6--update-task-cleanup-watchdog)
7. [Step 7 — Process Manager Subprocess Dispatcher](#step-7--process-manager-subprocess-dispatcher)
8. [Step 8 — Process Manager Multi-Step + GPU Support](#step-8--process-manager-multi-step--gpu-support)
9. [Step 9 — Model Training On-Prem Path](#step-9--model-training-on-prem-path)
10. [Step 10 — Flywheel On-Prem Path](#step-10--flywheel-on-prem-path)
11. [Step 11 — Settings and Configuration](#step-11--settings-and-configuration)
12. [Step 12 — systemd Unit Files and Deployment Scripts](#step-12--systemd-unit-files-and-deployment-scripts)
13. [Step 13 — Process Manager Health Endpoint](#step-13--process-manager-health-endpoint)
14. [Step 14 — Integration Testing](#step-14--integration-testing)

---

## Step 1 — Database Migration

**Goal:** Create the `pipeline_jobs` table in PostgreSQL.

**Files to create:**
- `vldbmigration/migrations/NNN_add_pipeline_jobs.sql`

### Claude Prompt

```
Read the file `C:\Users\amita\Desktop\detaction AI\scripts\pipes\output\on_prem_pipes_design.md`, specifically the section "NEW FILE: vldbmigration/migrations/NNN_add_pipeline_jobs.sql" in Appendix D.0.

Then look at the existing migration files in `vldbmigration/migrations/` to determine the correct sequence number for the new migration file.

Create the migration file with the exact schema from the design doc:
- pipeline_jobs table with columns: id, task_id, dataset_id, flow_type, pipeline_structure, status, current_step, worker_id, pid, env_json, resource_config, requires_gpu, created_at, started_at, completed_at, error_message, retry_count, max_retries
- Include all three indexes (status, task_id, dataset_id)
- Use gen_random_uuid() for the default id
- Match the existing migration style/format used in this project

Do NOT run the migration — just create the file.
```

---

## Step 2 — Pipeline Jobs DAO

**Goal:** Create the data access layer for `pipeline_jobs`, following the existing `task_queue/dao.py` pattern.

**Files to create:**
- `process_manager/__init__.py`
- `process_manager/dao.py`

### Claude Prompt

```
I'm building an on-prem pipeline execution system for the VL-Camtek project. Read these files for context:

1. `vldbaccess/task_queue/dao.py` — the existing TaskQueueDAO pattern we want to follow
2. `vldbaccess/connection_manager.py` — how DB sessions work (get_async_session)
3. `C:\Users\amita\Desktop\detaction AI\scripts\pipes\output\on_prem_pipes_design.md` — Appendix D.0, the PipelineJobsDAO code

Create `process_manager/__init__.py` (empty) and `process_manager/dao.py` following the design doc code exactly. The DAO should:

1. Follow the exact same pattern as TaskQueueDAO: @staticmethod async methods, get_async_session(autocommit=True), sa.text() for raw SQL
2. Implement these methods:
   - create_job(task_id, dataset_id, flow_type, pipeline_structure, env_json, requires_gpu, resource_config, max_retries) -> UUID
   - claim_next_job(worker_id, gpu_available, stale_timeout_seconds) -> Optional[PipelineJob] using SELECT FOR UPDATE SKIP LOCKED
   - update_status(job_id, status, **kwargs)
   - mark_completed(job_id)
   - mark_failed(job_id, error_message)
   - mark_aborting(job_id)
   - get_job_by_task_id(task_id) -> Optional[PipelineJob]
3. Use a PipelineJob dataclass (same pattern as QueueTask in task_queue/dao.py)
4. Use `vl.common.logging_helpers.get_vl_logger` for logging

Place these files in the repo root at `process_manager/`.
```

---

## Step 3 — Process Manager Core

**Goal:** Build the main Process Manager service that polls pipeline_jobs and dispatches subprocesses.

**Files to create:**
- `process_manager/__main__.py`
- `process_manager/manager.py`
- `process_manager/config.py`

### Claude Prompt

```
I'm building the Process Manager for VL-Camtek's on-prem pipeline execution. This service replaces Argo Workflow Controller.

Read these files for context:
1. `process_manager/dao.py` — the PipelineJobsDAO we just created
2. `clustplorer/logic/queue_worker/worker.py` — the existing queue worker pattern (poll + process loop)
3. `pipeline/controller/controller.py` — the pipeline entry point that the Process Manager will invoke as subprocess
4. `C:\Users\amita\Desktop\detaction AI\scripts\pipes\output\on_prem_pipes_design.md` — Section 4.4 Process Manager Design

Create three files:

### process_manager/config.py
- Load YAML config from path specified by env var PROCESS_MANAGER_CONFIG (default /etc/vl/process_manager.yaml)
- Dataclass ProcessManagerConfig with fields: poll_interval_seconds, max_concurrent_cpu_jobs, max_concurrent_gpu_jobs, stale_job_timeout_seconds, gpu_worker_host, gpu_worker_user, ssh_key_path, workers (list), resource_defaults
- Provide sensible defaults for single-node deployment

### process_manager/manager.py
- Class PipelineProcessManager with async run() main loop
- Poll pipeline_jobs table using PipelineJobsDAO.claim_next_job()
- On claiming a job: spawn asyncio task for _execute_job(job)
- _execute_job: determine single-step vs multi-step, dispatch accordingly
- For single-step: call _execute_single_step() which runs subprocess
- Track active jobs in dict[UUID, asyncio.subprocess.Process]
- Enforce max_concurrent limits (check before claiming)
- Handle shutdown gracefully via asyncio.Event
- After job completes: run post_success_flow or post_error_flow as exit handler
- Periodically check for ABORTING jobs and send SIGTERM to the subprocess
- On startup, scan for stale RUNNING/DISPATCHED jobs and mark them FAILED
- Use systemd watchdog notification if WatchdogSec is set (sd_notify)

### process_manager/__main__.py
- Entry point that loads config and runs PipelineProcessManager

The subprocess command for a pipeline is:
  python -m pipeline.controller.controller --flow-to-run {flow_type}

Environment variables for the subprocess come from job.env_json merged with the pipeline.env base config.

Resource limits should be enforced via systemd-run --scope when available on Linux.

Keep the code clean, well-logged, and production-ready. Target ~350-400 lines total across the three files.
```

---

## Step 4 — Modify Trigger Path

**Goal:** Modify `trigger_processing()` in `datasets_bl.py` to route to Process Manager when `VL_ON_PREM_PIPELINE_ENABLED=true`.

**Files to modify:**
- `clustplorer/logic/datasets_bl.py`

### Claude Prompt

```
I need to modify the pipeline trigger path in VL-Camtek to support on-prem execution without Kubernetes.

Read these files:
1. `clustplorer/logic/datasets_bl.py` — the trigger_processing() function (lines 305-396)
2. `clustplorer/logic/argo_pipeline/argo_pipeline.py` — ArgoPipeline.extract_workflow_info() and trigger_vl_argo_processing()
3. `process_manager/dao.py` — PipelineJobsDAO.create_job()
4. `vl/common/settings.py` — Settings class (around line 529-548)
5. `C:\Users\amita\Desktop\detaction AI\scripts\pipes\output\on_prem_pipes_design.md` — Appendix D.1

Modify `clustplorer/logic/datasets_bl.py` function `trigger_processing()` (lines 360-396):

1. Add a NEW branch at the top (before the existing Argo check) that checks `Settings.VL_ON_PREM_PIPELINE_ENABLED`
2. When on-prem is enabled:
   - Use ArgoPipeline.extract_workflow_info() to compute workflow_info (reuse existing logic for resource calculation, GPU detection, etc.)
   - Map pipeline_flow_type to flow name: PARTIAL_UPDATE -> "partial_update_flow", REINDEX -> "reindex_dataset_flow", RESTORE -> "restore_dataset_flow", ENRICHMENT -> "enrichment_flow", else -> "full_pipeline_flow"
   - Determine pipeline_structure via workflow_info.should_use_multistep()
   - Build env_vars dict with: FLOW_RUN_ID, DATASET_ID, DATASET_NAME, USER_ID, SOURCE_URI, PIPELINE_FLOW_TYPE, TASK_ID, TASK_TYPE, and optional SELECTED_FOLDERS, PREPROCESS_ENRICHMENT_CONFIG, PARTIAL_UPDATE_BATCH_ID, SNAPSHOT_DATASET_ID, SNAPSHOT_DATASET_REVISION_ID
   - For combined partial_update+reindex (auto_reindex=True): set flow_type to "partial_update_flow+reindex_dataset_flow"
   - Call PipelineJobsDAO.create_job() with all the data
   - Update DatasetDB.creation_context and task metadata (same as existing Argo path)
3. Keep the existing Argo path as the `elif` branch (unchanged)
4. Keep the final `else` error case

The key principle: ZERO changes to pipeline step code. We're only changing how jobs are dispatched, not how they execute.
```

---

## Step 5 — Modify Abort Path

**Goal:** Replace `kubectl delete workflow` with a DB status update for on-prem abort.

**Files to modify:**
- `vl/tasks/dataset_creation/dataset_creation_task_service.py`

### Claude Prompt

```
I need to modify the task abort logic to support on-prem pipelines (no kubectl).

Read these files:
1. `vl/tasks/dataset_creation/dataset_creation_task_service.py` — the abort_task() method (lines 132-168) and _terminate_argo_workflow() (lines 237-261)
2. `process_manager/dao.py` — PipelineJobsDAO.mark_aborting()
3. `vl/common/settings.py` — Settings.VL_ON_PREM_PIPELINE_ENABLED
4. `C:\Users\amita\Desktop\detaction AI\scripts\pipes\output\on_prem_pipes_design.md` — Appendix D.2

Make these changes to `dataset_creation_task_service.py`:

1. In abort_task() (around line 148-150), change the workflow termination to check for on-prem mode:
   - If Settings.VL_ON_PREM_PIPELINE_ENABLED: call a new async method _terminate_pipeline_job(workflow_name)
   - Else: call existing _terminate_argo_workflow(workflow_name) (unchanged)

2. Add a new static async method _terminate_pipeline_job(job_ref: str) that:
   - Parses job_ref as UUID
   - Calls PipelineJobsDAO.mark_aborting(job_id)
   - Logs the action
   - Catches ValueError (invalid UUID) and other exceptions gracefully

3. Since abort_task is currently sync but _terminate_pipeline_job needs to be async, make abort_task check if we need the async path. The simplest approach: since abort_task is already called from an async API endpoint, make the on-prem path use asyncio.

Keep _terminate_argo_workflow completely unchanged as the fallback path.
No other task service files need changes — only DatasetCreationTaskService has the kubectl call.
```

---

## Step 6 — Update Task Cleanup Watchdog

**Goal:** Extend the watchdog to also monitor on-prem pipeline jobs.

**Files to modify:**
- `clustplorer/logic/task_cleanup.py`

### Claude Prompt

```
I need to extend the Argo task cleanup watchdog to also handle on-prem pipeline jobs.

Read these files:
1. `clustplorer/logic/task_cleanup.py` — the full file (all 303 lines)
2. `process_manager/dao.py` — PipelineJobsDAO
3. `C:\Users\amita\Desktop\detaction AI\scripts\pipes\output\on_prem_pipes_design.md` — Appendix D.3

Make these changes to `task_cleanup.py`:

1. Add a new async function cleanup_orphaned_onprem_tasks() -> int:
   - Skip if not Settings.VL_ON_PREM_PIPELINE_ENABLED
   - Query for tasks that are RUNNING/INITIALIZING but whose pipeline_job is COMPLETED or FAILED
   - Use a SQL JOIN between tasks and pipeline_jobs tables
   - For each found: mark_task_as_completed or mark_task_as_failed (reusing existing functions)
   - Return count of cleaned tasks

2. Modify _watchdog_loop() (line 293):
   - After calling cleanup_orphaned_argo_tasks(), also call cleanup_orphaned_onprem_tasks()
   - Sum both results for the log

3. Modify start_argo_task_watchdog() (line 284):
   - Start the watchdog if EITHER VL_ARGO_PIPELINE_ENABLED OR VL_ON_PREM_PIPELINE_ENABLED is true
   - (Currently only starts for Argo)

Keep all existing Argo watchdog code completely unchanged.
```

---

## Step 7 — Process Manager Subprocess Dispatcher

**Goal:** Implement the actual subprocess execution logic with resource limits and log streaming.

**Files to create/modify:**
- `process_manager/dispatcher.py`

### Claude Prompt

```
I need to build the subprocess dispatcher for the VL-Camtek Process Manager. This is the component that actually executes pipeline flows as OS subprocesses.

Read these files for context:
1. `process_manager/manager.py` — the Process Manager that will call this dispatcher
2. `process_manager/config.py` — ProcessManagerConfig with worker definitions
3. `pipeline/controller/controller.py` — the entry point (python -m pipeline.controller.controller --flow-to-run ...)
4. `clustplorer/logic/argo_pipeline/argo_pipeline_creator.py` lines 129-232 — the _compute_cpu_resources() logic we need to match for systemd cgroup limits

Create `process_manager/dispatcher.py` with:

### class PipelineDispatcher:

1. async run_subprocess(job, flow_name, env_overrides=None, gpu=False) -> int:
   - Build the command: ["python", "-m", "pipeline.controller.controller", "--flow-to-run", flow_name]
   - Build environment: merge base pipeline env (from /etc/vl/pipeline.env or similar) with job.env_json and env_overrides
   - On Linux, wrap with systemd-run --scope for resource limits:
     systemd-run --scope -p MemoryMax={memory} -p CPUQuota={cpu_percent}%
   - On non-Linux (dev), skip systemd-run
   - Create asyncio subprocess with stdout=PIPE, stderr=PIPE
   - Stream stdout/stderr to logger with [job_id] prefix
   - Return exit code
   - Store process reference for abort support

2. async run_ssh_subprocess(host, user, ssh_key, job, flow_name, env_overrides=None) -> int:
   - Build SSH command: ssh -i {key} -o StrictHostKeyChecking=no {user}@{host} "cd /opt/vl-camtek && env VAR1=val1 ... python -m ..."
   - For GPU enrichment, the entry point is different: python3.10 -m pipeline.preprocess.job
   - Same logging pattern as local subprocess
   - Handle SSH connection failures gracefully

3. async abort_process(job_id) -> bool:
   - Look up active process by job_id
   - Send SIGTERM, wait 30s, then SIGKILL if needed
   - Return True if process was found and signaled

4. get_resource_limits(resource_config) -> tuple[str, str]:
   - Convert resource_config {"cpu": "8", "memory": "32Gi"} to systemd format
   - MemoryMax: "32Gi" -> "32G"
   - CPUQuota: "8" cores -> "800%"

The dispatcher should be stateless except for the active_processes dict. Keep it ~150 lines.
```

---

## Step 8 — Process Manager Multi-Step + GPU Support

**Goal:** Add multi-step pipeline chaining (CPU -> GPU -> CPU) to the Process Manager.

**Files to modify:**
- `process_manager/manager.py`

### Claude Prompt

```
I need to extend the Process Manager to support multi-step pipeline execution (the CPU -> GPU -> CPU chain that currently uses Argo's multi-template workflows).

Read these files:
1. `process_manager/manager.py` — current implementation
2. `process_manager/dispatcher.py` — the subprocess dispatcher
3. `clustplorer/logic/argo_pipeline/argo_pipeline_creator.py` lines 703-814 (single-step) and 1024-1181 (combined workflow) — to understand the current multi-step structure
4. `pipeline/controller/pipeline_flows.py` — flow definitions, especially PREPARE_DATA_STEPS, ENRICHMENT_STEPS, INDEXER_FLOW_STEPS

Add to PipelineProcessManager._execute_job():

1. Check if job.pipeline_structure == "multi-step" AND job.requires_gpu:
   - If yes: call _execute_multistep(job)
   - If no: call _execute_single_step(job) (existing)

2. _execute_multistep(job) should:
   a. Run prepare_data_flow on CPU worker (local subprocess)
   b. On success, run enrichment_flow on GPU worker (SSH subprocess)
      - Set PREPROCESS_SECTION=gpu in env
      - Use python3.10 -m pipeline.preprocess.job as entry point
   c. On success, run indexer_flow on CPU worker (local subprocess)
   d. Each step updates job.current_step in pipeline_jobs table
   e. If any step fails, run post_error_flow and mark job FAILED
   f. If all succeed, run post_success_flow and mark job COMPLETED

3. Handle the combined flow type "partial_update_flow+reindex_dataset_flow":
   - Run partial_update_flow first
   - Then run reindex_dataset_flow second
   - Both on CPU worker (single-step each, possibly with GPU enrichment)

4. The GPU worker SSH details come from ProcessManagerConfig.workers.gpu[0]

Keep the existing single-step path unchanged. The multi-step is an extension.
```

---

## Step 9 — Model Training On-Prem Path

**Goal:** Route model training to Process Manager instead of Hera/Argo.

**Files to modify:**
- `clustplorer/logic/model_training/model_training_argo_pipeline.py`
- `clustplorer/web/api_dataset_model_training.py`

### Claude Prompt

```
I need to add an on-prem execution path for model training flows, bypassing the Hera SDK and Argo.

Read these files:
1. `clustplorer/logic/model_training/model_training_argo_pipeline.py` — ModelTrainingArgoPipeline class (full file, 63 lines)
2. `clustplorer/logic/model_training/model_training_argo_manager.py` — run_model_training_argo_workflow() with env vars (full file, 173 lines)
3. `clustplorer/web/api_dataset_model_training.py` — trigger_training() endpoint (lines 90-183)
4. `process_manager/dao.py` — PipelineJobsDAO.create_job()
5. `C:\Users\amita\Desktop\detaction AI\scripts\pipes\output\on_prem_pipes_design.md` — Appendix D.4

Make these changes:

1. In `model_training_argo_pipeline.py`, modify trigger_model_training_argo_workflow to:
   - Make it async (add `async def`)
   - Check Settings.VL_ON_PREM_PIPELINE_ENABLED at the top
   - If on-prem: build env_vars dict from the same variables in model_training_argo_manager.get_environment_variables(), then call PipelineJobsDAO.create_job() with flow_type="model_training_flow", requires_gpu=False, resource_config={"cpu": "4", "memory": "4Gi"}
   - If not on-prem: call existing Argo path (unchanged)
   - Return the job_id (as string) or workflow_name

2. In `api_dataset_model_training.py` (line 147):
   - Change the call to await (since we made the method async):
     `workflow_name = await ModelTrainingArgoPipeline.trigger_model_training_workflow(...)`
   - The endpoint is already async, so this is safe

Keep the existing Argo code path intact as the fallback. The model_training_argo_manager.py file does NOT need changes — it's only used in the Argo path.
```

---

## Step 10 — Flywheel On-Prem Path

**Goal:** Route flywheel workflows to Process Manager instead of Hera/Argo.

**Files to modify:**
- `clustplorer/logic/flywheel/flywheel_runner_argo_manager.py`

### Claude Prompt

```
I need to add an on-prem execution path for flywheel workflows.

Read these files:
1. `clustplorer/logic/flywheel/flywheel_runner_argo_manager.py` — run_flywheel() function (full file, 145 lines)
2. `process_manager/dao.py` — PipelineJobsDAO.create_job()
3. `C:\Users\amita\Desktop\detaction AI\scripts\pipes\output\on_prem_pipes_design.md` — Appendix D.5

Modify `flywheel_runner_argo_manager.py` function run_flywheel():

1. Add an on-prem check at the very top of the function (before the existing assert statements):
   - If Settings.VL_ON_PREM_PIPELINE_ENABLED:
     - Build env_vars from the same variables used in get_command(): DATASET_ID, FLOW_ID, RUN_MODE, FLOW_ROOT, PIPELINE_FLOW_TYPE="flywheel"
     - If cycle_number is not None, add CYCLE_NUMBER
     - Call PipelineJobsDAO.create_job() with flow_type="flywheel", requires_gpu=False
     - Update task metadata with workflow_name=str(job_id), invocation_type="OnPremPipeline" (same pattern as existing lines 132-144 but with job_id)
     - Return early

2. Keep the entire existing Argo path after the on-prem block (unchanged)

The flywheel Process Manager implementation will use the command:
  python3 -m clustplorer.logic.flywheel.flywheel_runner_manager --dataset-id ... --flow-id ... --run-mode ... --flow-root ...
This is the same command the Hera workflow runs inside the container.
```

---

## Step 11 — Settings and Configuration

**Goal:** Add new Settings entries and create configuration templates.

**Files to modify:**
- `vl/common/settings.py`

**Files to create:**
- `deploy/env/clustplorer.env.template`
- `deploy/env/process_manager.env.template`
- `deploy/process_manager.yaml.template`

### Claude Prompt

```
I need to add configuration support for the on-prem pipeline system.

Read these files:
1. `vl/common/settings.py` — the Settings class, especially lines 529-548 (K8s pipeline settings)
2. `C:\Users\amita\Desktop\detaction AI\scripts\pipes\output\on_prem_pipes_design.md` — Appendix B (Environment Variable Mapping)

Make these changes:

1. In `vl/common/settings.py`, after line 548 (after VL_K8S_NODE_TOLERATIONS_ENABLED), add:
```python
    # On-prem pipeline settings
    VL_ON_PREM_PIPELINE_ENABLED: ConfigValue = ConfigValue(str2bool, False)
```
   That's the only setting needed in the main Settings class. The Process Manager has its own YAML config.

2. Create `deploy/env/clustplorer.env.template` with all the environment variables from Appendix B, with placeholder values and comments explaining each.

3. Create `deploy/env/process_manager.env.template` with:
   - PG_URI
   - PROCESS_MANAGER_CONFIG=/etc/vl/process_manager.yaml
   - LOG_LEVEL=INFO

4. Create `deploy/process_manager.yaml.template` with the YAML config from Appendix B, including worker definitions, poll interval, concurrency limits, GPU config, resource defaults.

Use comments to explain what each value does and when to change it.
```

---

## Step 12 — systemd Unit Files and Deployment Scripts

**Goal:** Create systemd service files and deployment scripts.

**Files to create:**
- `deploy/systemd/vl-clustplorer.service`
- `deploy/systemd/vl-process-manager.service`
- `deploy/systemd/vl-queue-worker.service`
- `deploy/systemd/vl-frontend.service`
- `deploy/nginx/vl-camtek.conf`
- `deploy/deploy.sh`

### Claude Prompt

```
I need to create deployment infrastructure for the on-prem VL-Camtek installation.

Read:
1. `C:\Users\amita\Desktop\detaction AI\scripts\pipes\output\on_prem_pipes_design.md` — Section 4.10 (systemd Unit Files) and Appendix E (Deployment Plan)

Create these files:

1. `deploy/systemd/vl-clustplorer.service` — FastAPI backend on port 9999, uvicorn with 4 workers, MemoryMax=8G, restart always
2. `deploy/systemd/vl-process-manager.service` — Process Manager with WatchdogSec=60, restart always, RestartSec=10
3. `deploy/systemd/vl-queue-worker.service` — Queue worker, restart always
4. `deploy/systemd/vl-frontend.service` — (optional, nginx serves the built frontend)
5. `deploy/nginx/vl-camtek.conf` — nginx config that proxies:
   - / -> React frontend static files
   - /api -> clustplorer:9999
   - /image -> image-proxy (if configured)
   Include proper WebSocket/SSE support headers for potential future use.

6. `deploy/deploy.sh` — deployment script per Appendix E.4:
   - Accepts target argument: app, worker, all
   - For worker deployment: waits for active pipeline jobs to complete before restarting
   - Pulls code, installs deps, runs migrations, restarts services
   - Includes validation checks after deployment

All systemd services should:
- Run as dedicated service users (vl-service or vl-pipeline)
- Use EnvironmentFile for configuration
- Have proper ordering (After=network.target postgresql.service)
- Include Description and Install sections
```

---

## Step 13 — Process Manager Health Endpoint

**Goal:** Add a simple HTTP health check endpoint to the Process Manager.

**Files to create:**
- `process_manager/health.py`

### Claude Prompt

```
I need a simple HTTP health endpoint for the Process Manager service.

Read:
1. `process_manager/manager.py` — to understand the Process Manager's state
2. `C:\Users\amita\Desktop\detaction AI\scripts\pipes\output\on_prem_pipes_design.md` — Section 6.2 Health Checks

Create `process_manager/health.py`:

1. Use aiohttp (lightweight) or just asyncio raw HTTP to serve a single endpoint
2. GET /health returns JSON:
   - status: "healthy" or "degraded"
   - active_jobs: count of currently running jobs
   - workers: dict of worker_id -> "online"/"offline" (check via SSH ping or last heartbeat)
   - last_poll_at: ISO timestamp of last successful DB poll
   - uptime_seconds: time since startup
   - pending_jobs: count of PENDING jobs in pipeline_jobs table
3. GET /metrics (optional, Prometheus format) with:
   - pipeline_jobs_total{flow_type, status}
   - pipeline_jobs_active{flow_type, worker}

4. Integrate it into the Process Manager's main loop (run HTTP server as background task)
5. Listen on port 8090 (configurable)

Keep it simple — ~50 lines. This is for operational monitoring, not a full API.
```

---

## Step 14 — Integration Testing

**Goal:** Validate the entire on-prem pipeline system end-to-end.

### Claude Prompt

```
I need to create integration test scripts for the on-prem pipeline system.

Read:
1. `C:\Users\amita\Desktop\detaction AI\scripts\pipes\output\on_prem_pipes_design.md` — Section 5.3 Phase 1 Validation and Appendix E.3 Deployment Verification Checklist
2. `process_manager/dao.py` — PipelineJobsDAO
3. `pipeline/controller/controller.py` — flow_map

Create a test script `process_manager/tests/test_integration.py` that:

1. test_nop_flow():
   - Insert a pipeline_jobs row with flow_type="nop_flow"
   - Wait up to 60s for status to change to COMPLETED
   - Assert it completed without error

2. test_create_job_and_claim():
   - Create a job via PipelineJobsDAO.create_job()
   - Claim it via PipelineJobsDAO.claim_next_job()
   - Assert the claimed job matches
   - Assert status is DISPATCHED

3. test_abort_flow():
   - Insert a job, wait for RUNNING status
   - Mark as ABORTING
   - Wait for ABORTED or FAILED status
   - Assert the subprocess was terminated

4. test_stale_job_recovery():
   - Insert a job and manually set status=RUNNING, started_at=NOW()-20min
   - Wait for Process Manager's stale detection
   - Assert job is marked FAILED

5. test_resource_limits():
   - Create job with resource_config={"cpu": "2", "memory": "4Gi"}
   - Verify systemd-run scope is created (check journalctl)

These tests require a running PostgreSQL and Process Manager. Use pytest with async support (pytest-asyncio). Skip GPU tests if no GPU is available.
```

---

## Execution Order

```
Phase 0 (Foundation):
  Step 1  → Database migration
  Step 11 → Settings + config templates
  Step 12 → systemd + deployment scripts

Phase 1 (Process Manager — CPU flows):
  Step 2  → Pipeline Jobs DAO
  Step 3  → Process Manager core
  Step 7  → Subprocess dispatcher
  Step 4  → Modify trigger path
  Step 5  → Modify abort path
  Step 6  → Update watchdog
  Step 13 → Health endpoint
  Step 14 → Integration tests

Phase 2 (GPU support):
  Step 8  → Multi-step + GPU dispatch

Phase 3 (Training + Flywheel):
  Step 9  → Model training on-prem path
  Step 10 → Flywheel on-prem path
```

---

## Notes for Claude

- **Always read the target file before modifying it.** The prompts reference line numbers from the analysis date (2026-04-16); the code may have changed.
- **Preserve all existing Argo code** behind the feature flag. Never delete the Argo path — it's the rollback.
- **Follow existing patterns**: use `get_vl_logger(__name__)`, `get_async_session(autocommit=True)`, `sa.text()` for SQL, dataclasses for DTOs.
- **Test before committing**: per CLAUDE.md, every change must be manually tested or verified before proposing a commit.
- **The pipeline step code (`pipeline/controller/`, `pipeline/preprocess/`, `pipeline/k8s_job_steps/`) must NOT be modified.** The entire point of this architecture is that pipelines run identically — only the dispatch mechanism changes.
