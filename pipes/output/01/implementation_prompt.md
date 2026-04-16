# VL-Camtek On-Prem Migration — Implementation Prompt

**Purpose:** Paste this prompt into a new Claude Code session (or a fresh agent) to drive the implementation of the migration described in [on_prem_pipes_design.md](./on_prem_pipes_design.md).

**Usage:**
- Start a new Claude Code session from the repo root: `c:\visual layer\vl-camtek`
- Paste the entire **Prompt to Claude** section below into the first message
- Claude will read the design doc and the repo, then start with Milestone 0

---

## Context for the human operator

This prompt asks Claude to implement a staged migration from Argo-on-Kubernetes to Dramatiq + RabbitMQ + systemd. The migration is split into **7 milestones**; each milestone produces a mergeable PR and includes a validation checkpoint.

The existing pipeline business logic (`pipeline/`, `vl/`, `vldbaccess/`) must not be modified. Only the dispatch layer is replaced.

Expected artifacts after full completion:
- New package `clustplorer/logic/dispatch/` (6 files)
- Small changes to ~7 call-sites in `clustplorer/web/` and `vl/tasks/`
- Dual-backend feature flag (`DISPATCH_BACKEND=argo|dramatiq|dual`)
- systemd unit files + Ansible/packaging updates
- Tests for each actor
- Docs updated

---

## Prompt to Claude

> You are implementing the migration described in `C:\Users\amita\Desktop\detaction AI\scripts\pipes\output\on_prem_pipes_design.md`.
>
> ### Ground rules (read these carefully before doing anything)
>
> 1. **Do not modify `pipeline/`, `vl/` (except `vl/tasks/dataset_creation/dataset_creation_task_service.py:_terminate_argo_workflow` and `vl/common/settings.py`), or `vldbaccess/`.** The migration's core value is that the business logic stays put. If you think you need to modify those trees, stop and ask.
> 2. **Preserve the existing public API.** Endpoint signatures, request/response schemas, and the `tasks` DB table schema must not change during P0–P3. UI and API clients must keep working with no change.
> 3. **Do not remove Argo code until P4 is reached.** Until then, both backends must coexist behind a feature flag.
> 4. **Write integration tests, not just unit tests.** Each actor must have at least one test that dispatches a message through a real broker (use `pytest` + `dramatiq[testing]` + `testcontainers` RabbitMQ).
> 5. **Follow the project rules in `CLAUDE.md`** — ruff formatting, no docs/helper scripts unless asked, no over-engineering.
> 6. **Commit discipline from `CLAUDE.md`:** never propose a commit until the change has been validated (tests green, or explicit statement of what cannot be validated locally).
> 7. **Make incremental PRs.** One milestone = one PR. Do not combine milestones.
> 8. **Ask before destructive or ambiguous decisions.** Examples: removing a file, changing a public function signature, adding a new dependency not listed in the design doc, deviating from the design doc.
>
> ### Required reading (do this first, in order)
>
> 1. `C:\Users\amita\Desktop\detaction AI\scripts\pipes\pipeAnalysis.md` — current architecture
> 2. `C:\Users\amita\Desktop\detaction AI\scripts\pipes\output\on_prem_pipes_design.md` — target design, especially Appendix D (per-pipe code), Appendix E (deployment), Appendix F (VM specs)
> 3. `c:\visual layer\vl-camtek\CLAUDE.md` — project conventions
> 4. `c:\visual layer\vl-camtek\pipeline\controller\controller.py` + `pipeline_flows.py` — the flows you will be dispatching (do NOT modify)
> 5. `c:\visual layer\vl-camtek\clustplorer\logic\argo_pipeline\argo_pipeline.py` — the module you are replacing
> 6. `c:\visual layer\vl-camtek\clustplorer\web\api_dataset_create_workflow.py` — primary call-site
> 7. `c:\visual layer\vl-camtek\vl\tasks\dataset_creation\dataset_creation_task_service.py` — contains the abort path you will change
>
> After reading, summarise back to me in 10 bullet points your understanding of the scope, confirming the list of files you plan to touch in each milestone.
>
> ### Milestones
>
> #### Milestone 0 — Dependencies and settings (smallest possible PR)
> **Goal:** prove the wheel still builds with new deps.
> - Add to `pyproject.toml`: `dramatiq[rabbitmq,watch] ~= 1.17`, `dramatiq-abort ~= 1.2`, `testcontainers[rabbitmq] ~= 4.7` (dev)
> - Add settings to `vl/common/settings.py`:
>   - `RABBITMQ_URL: str = "amqp://guest:guest@localhost:5672/vl"`
>   - `ABORT_BACKEND_URL: str = "redis://localhost:6379/0"`
>   - `DISPATCH_BACKEND: Literal["argo", "dramatiq", "dual"] = "argo"`
> - Run `ruff format` + `ruff check`
> - Run `./run_tests.sh -k test_settings` (or any equivalent smoke test)
> - Exit criterion: lockfile updated, no import breakage, settings load
>
> #### Milestone 1 — Dispatch scaffolding (no actors yet)
> **Goal:** create the empty package with broker + middleware + routing helpers.
> - Create `clustplorer/logic/dispatch/{__init__.py, broker.py, middleware.py, routing.py, abort.py}` exactly per Appendix D.0 of the design doc.
> - Actor module (`actors.py`) is created but empty (`# actors defined in later milestones`).
> - Unit test: `test_routing.py` covers `needs_gpu` and `priority_for_size` edge cases.
> - Unit test: `test_broker.py` imports `get_broker()` under a mocked RabbitmqBroker.
> - Exit criterion: package imports cleanly; `DISPATCH_BACKEND="argo"` still routes to Argo.
>
> #### Milestone 2 — `nop_flow` + `restore_dataset_flow` (pilot pipes)
> **Goal:** the two lightest pipes travel the full stack end-to-end.
> - Implement `run_nop` and `run_restore` actors per Appendix D.7 and D.8
> - Implement `select_actor` for these two flow types
> - Update `clustplorer/web/api_dataset_snapshots.py` restore/clone endpoints to branch on `Settings.DISPATCH_BACKEND`:
>   - `"argo"` → existing path (unchanged)
>   - `"dramatiq"` → new `dispatch.trigger_pipeline(...)`
>   - `"dual"` → feature-flagged per-tenant (acceptable: just use `dramatiq` for staging tenant IDs for now)
> - Integration test: spin up a RabbitMQ testcontainer, dispatch `run_nop`, assert worker ran and `tasks` row updated
> - Exit criterion: `DISPATCH_BACKEND=dramatiq` + `run_nop.send()` succeeds; staging-tenant restore works through new stack
>
> #### Milestone 3 — Core pipeline actors
> **Goal:** main revenue-critical paths migrate-able.
> - Implement actors: `run_full_pipeline_cpu`, `run_full_pipeline_gpu`, `run_partial_update_cpu`, `run_partial_update_gpu`, `run_reindex_cpu`, `run_reindex_gpu`, `run_enrichment`, `run_indexer`
> - Update call-sites:
>   - `clustplorer/web/api_dataset_create_workflow.py`
>   - `clustplorer/web/api_add_media.py`
>   - `clustplorer/logic/datasets_bl.py` (enrichment branch)
>   - `clustplorer/logic/argo_pipeline/argo_pipeline.py` — add `if Settings.DISPATCH_BACKEND == "dramatiq": return dispatch.trigger_pipeline(...)` early-return
> - `tasks.metadata_` now stores `message_id` (new) alongside `workflow_name` (legacy) — coexist
> - Integration tests per actor
> - Exit criterion: per-flag toggle allows running each pipe through either backend; tests pass under both backends
>
> #### Milestone 4 — Exit-handler middleware and post_success/post_error
> **Goal:** parity with Argo's `onExit`.
> - Implement `run_post_success`, `run_post_error` actors per Appendix D.9/10
> - Wire `ExitHandlerMiddleware` (already stubbed in M1)
> - Integration test: force an actor to raise; assert `run_post_error` was enqueued and ran
> - Integration test: happy-path actor completes; assert `run_post_success` ran
> - Exit criterion: exit handlers fire in both success and failure paths
>
> #### Milestone 5 — Abort + model_training + flywheel
> **Goal:** fill the remaining pipes and replace the kubectl-shell abort.
> - Implement `run_model_training`, `run_flywheel_iteration`
> - Update `clustplorer/web/api_dataset_model_training.py` and flywheel API to dispatch through `trigger_pipeline`
> - Replace `_terminate_argo_workflow` with `_terminate_dispatched_task(message_id)` per Appendix D.14 — but keep the old kubectl path behind `DISPATCH_BACKEND == "argo"`
> - Update `abort_task` in the task service to pick the right termination path based on which metadata key is populated (`workflow_name` → argo, `message_id` → dramatiq)
> - Integration test: dispatch, then abort mid-run; assert task row = ABORTED
> - Exit criterion: abort works under both backends; all 11 pipes have a working Dramatiq path
>
> #### Milestone 6 — Observability, systemd, ops
> **Goal:** make it production-runnable, not just functional.
> - Add Prometheus metrics:
>   - Expose a `/metrics` endpoint on `clustplorer` (`prometheus-fastapi-instrumentator`)
>   - In workers, expose a per-actor metrics server on port `9098` via `prometheus_client.start_http_server`
>   - Metrics: `vl_task_started_total`, `vl_task_completed_total{status}`, `vl_task_duration_seconds` (histogram, labels: pipe, priority)
> - Ship systemd unit files from Appendix A to `devops/on-prem/systemd/` (or repo equivalent)
> - Ship a Docker Compose variant from Appendix B to `devops/on-prem/compose/`
> - Ship a RabbitMQ `definitions.json` bootstrap (vhost, exchanges, queues, policies) to `devops/on-prem/rabbitmq/`
> - Add a CLI entrypoint: `python -m clustplorer.logic.dispatch.cli nop` that fires `run_nop.send()` and waits for completion — the canonical smoke test
> - Exit criterion: a fresh VM can run the full stack from these artifacts + a wheel install
>
> #### Milestone 7 — Decommission (P4)
> **Goal:** remove Argo code. Only start this after the stakeholder confirms 30 days of clean dual-backend operation.
> - Delete: `clustplorer/logic/argo_pipeline/argo_pipeline_creator.py`, `argo_pipeline.py`, `clustplorer/logic/common/hera_utils.py`, `clustplorer/logic/model_training/model_training_argo_manager.py`, `clustplorer/logic/flywheel/flywheel_runner_argo_manager.py`
> - Remove `hera`, `kubernetes` from `pyproject.toml`
> - Remove `VL_ARGO_*` settings from `vl/common/settings.py`
> - Remove the `"argo"` branch from `DISPATCH_BACKEND`; make `"dramatiq"` the only value
> - Remove `workflow_name` from `tasks.metadata_` usage
> - Move `devops/dependants/argo-workflows/` to `deprecated/` (one release grace period) or delete
> - Update `CLAUDE.md` to reflect the new architecture
> - Run full test suite; run ops smoke test (CLI nop dispatch)
> - Exit criterion: no reference to Argo or Kubernetes Python client remains in the codebase; CI is green
>
> ### Quality gates (must pass at every milestone)
>
> - `ruff format` + `ruff check` clean
> - `./run_tests.sh` — full suite green; new tests added for each new module
> - No `TODO`/`XXX` comments introduced without a corresponding ticket
> - No new subprocess shell-outs (use Python clients)
> - No logging of secrets (scan with `gitleaks` pre-commit)
> - Each PR has a 1-paragraph rollback plan in the description
>
> ### Working conventions
>
> - Use `todo` tracking for milestone progress (TodoWrite tool).
> - After each milestone, produce a short (≤10 lines) status summary listing: files added, files modified, tests added, known limitations.
> - When blocked, ask a single concrete question with the two most likely alternatives. Do not speculate in silence.
> - If you discover the design doc is wrong in some detail, flag it and propose an update — do not silently diverge.
> - If a change to `pipeline/`/`vl/`/`vldbaccess/` appears unavoidable, stop and ask before proceeding.
>
> ### First action
>
> Start by:
> 1. Reading the required-reading list above
> 2. Summarising your understanding in 10 bullets
> 3. Listing the files you plan to touch in Milestone 0
> 4. Waiting for my go-ahead before writing code
>
> Do not begin code changes until I say "proceed with Milestone 0."

---

## Appendix — Per-milestone file scorecard (for human tracking)

| Milestone | Files added | Files modified | Tests added | Deletable after P4 |
|---|---|---|---|---|
| M0 | — | `pyproject.toml`, `vl/common/settings.py` | `test_settings.py` extension | — |
| M1 | 6 dispatch files | — | `test_routing.py`, `test_broker.py` | — |
| M2 | — (actors appended) | `api_dataset_snapshots.py`, `argo_pipeline.py` | `test_run_nop.py`, `test_run_restore.py` | — |
| M3 | — | `api_dataset_create_workflow.py`, `api_add_media.py`, `datasets_bl.py`, `argo_pipeline.py` | 8 actor integration tests | — |
| M4 | — | `middleware.py` filled in | `test_exit_handlers.py` | — |
| M5 | — | `api_dataset_model_training.py`, `flywheel`, `dataset_creation_task_service.py` | `test_abort.py`, `test_training_actor.py`, `test_flywheel.py` | — |
| M6 | `devops/on-prem/...`, `dispatch/cli.py` | metrics integration in `clustplorer/web/__init__.py` | `test_metrics.py`, `test_cli.py` | — |
| M7 | — | `CLAUDE.md`, various call-sites | — | argo_pipeline/, hera_utils, model_training_argo_manager, flywheel_runner_argo_manager, devops/dependants/argo-workflows |

---

*End of implementation prompt.*
