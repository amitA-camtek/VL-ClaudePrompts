# system.md — Visual Layer (Camtek) System Knowledge Base
> Last updated: 2026-04-05
> Generated from: /home/ubuntu/vl_camtek

---

## 1. Project Overview
- **Type:** `monorepo`
- **Primary language(s):** `Python 3.10 (backend, pipeline, ML), TypeScript 4.9 (frontend)`
- **Primary framework(s):** `FastAPI 0.115.6 (backend), React 18.2 with CRA (frontend), SQLAlchemy async (ORM), Ant Design 5.11 (UI)`
- **Short description:** Visual Layer is a visual data management platform for exploring, curating, and improving image/video datasets at scale. It provides similarity clustering, data quality issue detection, label propagation (active learning), model training integration, and multi-tenant workspace management. The Camtek deployment is a customer-specific on-premises variant with gRPC-based model training integration and auth disabled by default.

---

## 2. Repository Structure
```
vl_camtek/
├── clustplorer/                  # Main backend API (FastAPI)
│   ├── web/                      #   API routers (34 files, ~177 endpoints)
│   ├── logic/                    #   Business logic (data ingestion, flywheel, queue worker)
│   ├── clustplorer_models/       #   Pydantic request/response models
│   ├── auth/                     #   Auth utilities
│   ├── middlewares/              #   ASGI middleware (timing)
│   ├── utils/                    #   Backend utilities
│   └── templates/                #   HTML templates (backoffice)
├── clustplorer-be/               # DB schema definitions
│   ├── Dockerfile                #   Backend Docker image
│   ├── db.sql                    #   Initial PostgreSQL schema (45+ tables)
│   ├── db.duckdb.sql             #   DuckDB mirror schema
│   ├── db.roles.sql              #   PostgreSQL role definitions
│   └── normal.sql                #   Normalization SQL
├── fe/                           # Frontend
│   ├── clustplorer/              #   React 18 SPA (CRA + TypeScript)
│   │   ├── src/
│   │   │   ├── App.tsx           #     Root component + router
│   │   │   ├── index.tsx         #     Entry point
│   │   │   ├── redux/            #     Redux Toolkit store (8 slices)
│   │   │   ├── views/            #     Pages, components, modals, providers
│   │   │   ├── hooks/            #     Custom hooks (40 files)
│   │   │   ├── vl-api/           #     Auto-generated OpenAPI client (React Query)
│   │   │   ├── contexts/         #     React contexts (UserConfig, Stats, Accordion)
│   │   │   └── helpers/          #     Constants, utilities, axios config
│   │   ├── package.json
│   │   └── .env.development
│   ├── Dockerfile                #   Frontend Docker image (Node → nginx)
│   ├── keycloak-theme/           #   Custom Keycloak login theme
│   └── init-substitute-config.sh #   Runtime env var injection
├── vl/                           # Shared core library
│   ├── common/                   #   Settings, logging, auth clients (Keycloak, OpenFGA)
│   ├── algo/                     #   ML algorithms (clustering, embeddings, label propagation, outliers)
│   ├── tasks/                    #   Task management (dataset creation, training, enrichment, flywheel)
│   ├── utils/                    #   Image utilities, CVAT, email, async ZIP
│   └── annotation/               #   Annotation parsing
├── vldbaccess/                   # Database access layer (50+ DAOs)
│   ├── connection_manager.py     #   SQLAlchemy async engine (psycopg)
│   ├── duckdb_connection_manager.py # DuckDB federated queries
│   ├── base.py                   #   DeclarativeBase, enums, type mappings
│   ├── task_queue/               #   PostgreSQL-based message queue
│   ├── datasets/                 #   Dataset DAOs
│   ├── users/                    #   User DAOs
│   └── migrations/               #   Migration verification
├── vldbmigration/                # DB migration job runner
│   └── main.py                   #   Pipeline-to-DB sync job
├── pipeline/                     # Data processing pipeline
│   ├── service/                  #   Pipeline FastAPI service (3 endpoints)
│   ├── controller/               #   Pipeline orchestration & notifications
│   ├── preprocess/               #   CPU/GPU preprocessing steps
│   ├── k8s_job_steps/            #   Kubernetes job step definitions
│   ├── common/                   #   Pipeline utilities (S3, email, fastdup)
│   └── pipeline_cleanup/         #   Cleanup jobs
├── image_proxy/                  # Image proxy service (FastAPI)
│   ├── service.py                #   S3 proxy / local file serving
│   └── __main__.py               #   Entry point (port 9998)
├── fastdup_runner/               # FastDup standalone runner
│   ├── run.py                    #   CLI entry point
│   └── fastdup_runner_server/    #   Local FastAPI server + bundled frontend
├── providers/                    # Customer-specific providers
│   └── camtek/
│       └── TrainClient/          #   gRPC client for Camtek training service
│           ├── Protos/           #     Proto definitions (train.proto, inference.proto)
│           └── python_client/    #     Generated gRPC stubs + client wrapper
├── tests/                        # pytest test suite (40+ test files)
├── devops/                       # Infrastructure & deployment
│   ├── visual-layer/             #   Helm chart (44 K8s templates, values.yaml)
│   ├── dependants/               #   External service Helm configs
│   │   ├── keycloak/             #     OIDC identity provider
│   │   ├── openfga/              #     Fine-grained authorization
│   │   ├── argo-workflows/       #     Async job execution
│   │   ├── ingress-nginx/        #     Ingress controller
│   │   ├── cert-manager/         #     TLS certificate management
│   │   └── grafana-loki/         #     Log aggregation (optional)
│   ├── env/                      #   Per-environment Helm overrides
│   │   ├── k3s/values.yaml       #     On-prem K3s config
│   │   └── staging/values.yaml   #     Staging config
│   ├── clients/camtek/           #   Camtek client overrides
│   ├── scripts/                  #   Install scripts (vl-k3s-install.sh, etc.)
│   └── vl-admin/                 #   CLI tool for install/manage/diagnose
├── triton_inference/             # NVIDIA Triton model repository
├── customers/camtek/             # Camtek-specific scripts (labels, annotations)
├── bin/                          # Precompiled similarity binaries (macOS ARM, Ubuntu ARM/x86)
├── .github/workflows/            # GitHub Actions (2 manual workflows)
├── Makefile                      # Dev environment bootstrap
├── setup.py                      # Python package metadata
├── requirements.txt              # Main Python dependencies
├── migration.sql                 # PostgreSQL incremental migrations
├── migration.dev.sql             # Staging-only migrations
├── json-logging.yaml             # JSON log format config
├── flat-logging.yaml             # Flat text log format config
├── ruff.toml                     # Python linter config
└── run_tests.sh                  # Test runner script
```

---

## 3. Services Inventory

### Clustplorer API (Backend)
- **Type:** `API`
- **Language & Framework:** `Python 3.10 / FastAPI 0.115.6 / Uvicorn 0.34.0`
- **Responsibility:** Main backend — serves all REST API endpoints for the frontend. Handles dataset CRUD, data exploration (VQL queries via DuckDB), user management, access control, data ingestion, flywheel/label propagation orchestration, model training triggers, export, and admin settings.
- **Entry point:** `clustplorer/web/__init__.py` (line 260: `app = create_app(lifespan=clustplorer_lifespan)`) — runner: `clustplorer/web/runner.py`
- **Port:** `9999` (CLI arg, convention from Dockerfile/K8s)
- **Database/Storage:** PostgreSQL 16 (primary, via SQLAlchemy async + psycopg), DuckDB (analytics, in-process with VSS extension), AWS S3 (object storage via boto3)
- **Key env vars:**
  - `PG_URI` — PostgreSQL connection string (secret)
  - `OIDC_CLIENT_ID` / `OIDC_CLIENT_SECRET` — Keycloak OIDC credentials (secret)
  - `OIDC_INTERNAL_BASE_URL` — Internal Keycloak URL (default: `http://keycloak:8080`)
  - `OPENFGA_API_URL` / `OPENFGA_STORE_ID` / `OPENFGA_MODEL_ID` — OpenFGA authorization
  - `TEXT_EMBEDDING_SERVICE_BASE_URI` — Embedding microservice URL
  - `S3_ARTIFACTS_BUCKET_NAME` — S3 bucket for dataset storage
  - `RUN_MODE` — `ONPREM` or `CLOUD`
  - `DISABLE_AUTH` — Kill switch for authentication (default: `false`)
  - `QUEUE_WORKER_ENABLED` — Enable PostgreSQL queue worker
  - `DUCKDB_DATASETS_DIR` / `DUCKDB_THREADS` / `DUCKDB_MEMORY_LIMIT_GB` — DuckDB config
  - `FASTAPI_DEBUG_MODE` — Debug mode flag
- **Start command:** `python -m clustplorer.web.runner -H 0.0.0.0 -p 9999`

### Clustplorer Frontend
- **Type:** `Frontend`
- **Language & Framework:** `TypeScript 4.9 / React 18.2 / CRA (react-scripts 5.0.1) / Ant Design 5.11`
- **Responsibility:** Single-page application for dataset exploration, creation, curation, label propagation, model catalog, workspace management, and task monitoring.
- **Entry point:** `fe/clustplorer/src/index.tsx`
- **Port:** `3000` (CRA dev server), `8080` (nginx production)
- **Database/Storage:** None (stateless, calls backend API)
- **Key env vars:**
  - `REACT_APP_API_ENDPOINT` — Backend API base URL
  - `REACT_APP_ENVIRONMENT` — `ON-PREM`, `STAGING`, etc.
  - `REACT_APP_IS_AUTHENTICATION_DISABELED` — Toggle auth enforcement (note: typo is intentional in codebase)
  - `REACT_APP_MODE` — `FD2` for fastdup standalone mode
  - `REACT_APP_GITHUB_CLIENT_ID` / `REACT_APP_GOOGLE_CLIENT_ID` — OAuth client IDs
  - `REACT_APP_GA4_ID` / `REACT_APP_AMPLITUDE_KEY` — Analytics
  - `REACT_APP_COPILOTKIT_PUBLIC_KEY` — AI chat integration
  - `REACT_APP_DATASET_CREATION_FROM_UI_ENABLED` — Feature toggle
- **Start command:** `npm start` (dev), `npm run build` (prod → nginx serves static files)

### Pipeline Service
- **Type:** `Worker / API`
- **Language & Framework:** `Python 3.10 / FastAPI`
- **Responsibility:** Runs dataset processing pipelines — preprocessing, feature extraction, similarity indexing, DuckDB materialization. Executes as K8s Jobs (Argo Workflows) or as a local FastAPI service behind Caddy.
- **Entry point:** `pipeline/service/pipeline_service.py` (line 30: `app = FastAPI()`)
- **Port:** Not externally exposed (internal via Caddy at `http://cd:2080` or Argo Job)
- **Database/Storage:** PostgreSQL (direct via `vldbaccess`), DuckDB (writes materialized views), S3 (reads/writes dataset files)
- **Key env vars:**
  - `DATASET_ID` / `USER_ID` / `DATASET_NAME` — Per-job context (set at runtime)
  - `VL_K8S_PIPELINE_ENABLED` — Enable K8s job mode
  - `HOST_OS` — Host OS for path resolution (`Darwin` / `Linux`)
  - `ADD_MEDIA_ENABLED` — Enable add-media endpoint
- **Start command:** Called via Argo Workflow or `GET http://cd:2080/api/v1/process?path=...`

### Image Proxy
- **Type:** `API`
- **Language & Framework:** `Python 3.10 / FastAPI`
- **Responsibility:** Serves images to the frontend — proxies from S3 (proxy mode) or serves from local filesystem (local-serving mode). Supports range requests for video streaming.
- **Entry point:** `image_proxy/__main__.py`
- **Port:** `9998` (default), `8080` (in Docker)
- **Database/Storage:** AWS S3 (proxy mode) or local filesystem (local-serving mode)
- **Key env vars:**
  - `IMAGE_PROXY_SERVE_MODE` — `proxy` or `local-serving`
  - `IMAGE_PROXY_BASE_PATH` — URL base path (default: `/image`)
  - `IMAGE_PROXY_ROOT_PATH` — Local filesystem root (default: `/images`)
- **Start command:** `python -m image_proxy --host 0.0.0.0 --port 9998`

### PostgreSQL 16
- **Type:** `Database`
- **Language & Framework:** `PostgreSQL 16 + pgvector 0.8.0`
- **Responsibility:** Primary relational database. Stores all entities (users, datasets, images, clusters, tasks, access control), serves as the message queue broker (`task_queue` table), and provides vector similarity via pgvector.
- **Entry point:** `pg.Dockerfile` (based on `quay.io/sclorg/postgresql-16`)
- **Port:** `5432`
- **Database/Storage:** PostgreSQL data directory
- **Key env vars:**
  - Standard PG env vars (`POSTGRESQL_USER`, `POSTGRESQL_PASSWORD`, `POSTGRESQL_DATABASE`)
- **Start command:** PostgreSQL default entrypoint

### DB Migration Job
- **Type:** `Cron / Job`
- **Language & Framework:** `Python 3.10`
- **Responsibility:** Syncs pipeline processing results (images, clusters, embeddings) from pipeline output into PostgreSQL. Runs as a K8s Job after pipeline completion.
- **Entry point:** `vldbmigration/main.py`
- **Port:** None (batch job)
- **Database/Storage:** PostgreSQL (writes), pipeline output files (reads)

### FastDup Runner
- **Type:** `API / Worker`
- **Language & Framework:** `Python 3.10 / FastAPI`
- **Responsibility:** Standalone CLI tool and optional local web server for running fastdup visual analysis. Includes a bundled frontend for GUI mode.
- **Entry point:** `fastdup_runner/run.py` (CLI), `fastdup_runner/fastdup_runner_server/` (server)
- **Port:** Dynamic (CLI arg)
- **Database/Storage:** Local filesystem

### VL Admin CLI
- **Type:** `CLI Tool`
- **Language & Framework:** `Python / Bash`
- **Responsibility:** On-premises installation, management, diagnostics, and uninstallation of the Visual Layer platform.
- **Entry point:** `devops/vl-admin/setup.py`
- **Port:** None
- **Start command:** `vl-admin install`, `vl-admin manage`, `vl-admin diagnose`

---

## 4. Communication Map

### 4.1 Synchronous (HTTP REST / gRPC / GraphQL)

| Source | Target | Protocol | Endpoint / Method | Auth | Description |
|--------|--------|----------|-------------------|------|-------------|
| Frontend | Clustplorer API | REST | `GET /api/v1/datasets` | `SESSION` cookie | List all datasets for authenticated user |
| Frontend | Clustplorer API | REST | `GET /api/v1/explore/{datasetId}?threshold=&entity_type=&labels=&vql=` | `SESSION` cookie | Main data exploration with VQL filters (DuckDB queries) |
| Frontend | Clustplorer API | REST | `POST /api/v1/workflow/dataset/new` | `SESSION` cookie | Create new dataset |
| Frontend | Clustplorer API | REST | `POST /api/v1/dataset/{id}/data/folder_upload/{transId}` | `SESSION` cookie | Upload file chunks (250 files/batch) |
| Frontend | Clustplorer API | REST | `GET /api/v1/dataset/{id}/process` | `SESSION` cookie | Trigger pipeline processing |
| Frontend | Clustplorer API | REST | `PUT /api/v1/flywheel/{datasetId}/start/{seedId}` | `SESSION` cookie | Start label propagation cycle |
| Frontend | Clustplorer API | REST | `POST /api/v1/training` | `SESSION` cookie | Trigger model training |
| Frontend | Clustplorer API | REST | `GET /api/v1/dataset/{id}/export_entities_async` | `SESSION` cookie | Request async dataset export |
| Frontend | Clustplorer API | REST | `GET /api/v1/user-config?dataset_id=` | `SESSION` cookie | Fetch feature flags and workspace config |
| Frontend | Clustplorer API | REST | `GET /api/v1/healthcheck` | None | Periodic health check |
| Frontend | GitHub API | REST (redirect) | `GET github.com/login/oauth/authorize` | Client ID in URL | OAuth login flow |
| Frontend | Google Identity | SDK | Google Sign-In widget | Client ID | Google OAuth |
| Clustplorer API | Pipeline Service (via Caddy) | REST | `GET http://cd:2080/api/v1/process?path=&dataset_id=&task_id=` | None (internal) | Trigger dataset processing (docker-compose env) |
| Clustplorer API | Pipeline Service (direct) | Internal call | `datasets_bl.trigger_processing()` | N/A | Trigger processing (K8s/Argo env — no HTTP) |
| Clustplorer API | Keycloak | REST | `GET {OIDC_INTERNAL_BASE_URL}/realms/visual-layer/.well-known/openid-configuration` | None | OIDC discovery document |
| Clustplorer API | Keycloak | REST | `GET {OIDC_INTERNAL_BASE_URL}/realms/visual-layer/protocol/openid-connect/certs` | None | JWKS keys for JWT validation |
| Clustplorer API | Keycloak | REST | `POST .../protocol/openid-connect/token` | Client credentials | Token exchange on OIDC callback |
| Clustplorer API | Keycloak Admin | REST | `GET/POST/PUT/DELETE /admin/realms/visual-layer/users/*` | User bearer token | Admin user CRUD |
| Clustplorer API | OpenFGA | REST | `POST {OPENFGA_API_URL}/stores/{storeId}/check` | None (internal network) | Authorization check (per-request) |
| Clustplorer API | OpenFGA | REST | `POST {OPENFGA_API_URL}/stores/{storeId}/write` | None (internal network) | Grant/revoke access tuples |
| Clustplorer API | OpenFGA | REST | `POST {OPENFGA_API_URL}/stores/{storeId}/list-objects` | None (internal network) | List accessible datasets for user |
| Clustplorer API | Embedding Service | REST | `POST {TEXT_EMBEDDING_SERVICE_BASE_URI}/generate_image_embedding` | None (internal) | Generate image embedding vector for visual search |
| Clustplorer API | GitHub API | REST | `POST github.com/login/oauth/access_token` | Client secret | Exchange OAuth code for token |
| Clustplorer API | GitHub API | REST | `GET api.github.com/user` | Bearer token | Fetch GitHub user profile |
| Clustplorer API | SendGrid | REST | SendGrid API | `EMAIL_API_KEY` | Send pipeline completion/error emails |
| Clustplorer API | Slack | REST | `POST {BUG_REPORT_SLACK_WEBHOOK_URL}` | Webhook URL auth | Bug report notifications |
| Clustplorer API | CVAT | REST | CVAT REST API | `CVAT_USERNAME` / `CVAT_PASSWORD` | Import annotation tasks |
| Image Proxy | AWS S3 | AWS SDK | `s3.get_object(Bucket, Key)` | IAM credentials | Stream images to frontend |
| Pipeline (Argo Job) | Camtek Train Service | gRPC (unary) | `TrainService/StartTrain` | None [UNCLEAR] | Initiate model training |
| Pipeline (Argo Job) | Camtek Train Service | gRPC (server-stream) | `TrainService/WatchTrainStatus` | None [UNCLEAR] | Monitor training progress |
| Pipeline (Argo Job) | Camtek Inference Service | gRPC (bidi-stream) | `InferenceService/InferenceSession` | None [UNCLEAR] | Run inference during pipeline |
| Pipeline Service | PostgreSQL | SQLAlchemy | Direct DB access via `vldbaccess` | Connection string | Read/write datasets, images, clusters (bypasses API) |

### 4.2 Asynchronous (Events / Queues)

| Producer | Consumer(s) | Broker / Mechanism | Topic / Queue | Message Schema | Description |
|----------|-------------|-------------------|---------------|----------------|-------------|
| `api_dataset_export.py` | In-process BackgroundTask | FastAPI `BackgroundTasks` | N/A (fire-and-forget) | `(dataset_id, user, export_task_id, filters)` | Async dataset export — writes ZIP to S3, updates `export_task` table |
| `api_models_catalog.py` | In-process BackgroundTask | FastAPI `BackgroundTasks` | N/A | `(model_id, export_task_id)` | Model export |
| `api_flywheel.py` | In-process BackgroundTask | FastAPI `BackgroundTasks` | N/A | `(dataset_id, flow_id)` | Generate evaluation report HTML |
| `api_data_ingestion.py` | In-process BackgroundTask | FastAPI `BackgroundTasks` | N/A | `(user, s3_uri, dataset_id)` | S3 preview generation |
| `api_data_ingestion.py` | In-process BackgroundTask | FastAPI `BackgroundTasks` | N/A | `(dataset_id, archive_path)` | Archive (ZIP/TAR) extraction |
| `api_dataset_create_workflow.py` | In-process BackgroundTask | FastAPI `BackgroundTasks` | N/A | `(transaction_id, dataset_id, user)` | Post-upload folder processing (validation, metadata, previews) |
| Pipeline Service | In-process BackgroundTask | FastAPI `BackgroundTasks` | N/A | `(path, name, dataset_id, serve_mode, config, flow_type, task_id)` | Pipeline execution (CPU-bound, holds mutex) |
| `api_data_ingestion.py` | Frontend (polls) | PostgreSQL `events` table | `DatasetInitialized`, `FilesUploadStart`, `FilesChunkUploaded`, `FilesUploadCompleted`, `AnnotationsValid`, `AnnotationsInvalid`, `S3Connected`, `LimitExceeded`, `ServerFailure` | `{event_type, dataset_id, payload: JSONB}` | Dataset creation event log — FE polls `GET /api/v1/ingestion/{id}/status?offset=` |
| Pipeline controller | PostgreSQL `datasets.status` | Direct DB write | Dataset status transitions | `status` enum: `NEW→INITIALIZING→UPLOADING→PRE_PROCESSING→SAVING→INDEXING→READY` (or `FATAL_ERROR`) | FE polls `GET /api/v1/datasets/{id}/creation-status` every ~5s |
| Export handler | PostgreSQL `export_task` | Direct DB write | Export status | `{status: INIT→IN_PROGRESS→COMPLETED/FAILED, download_uri, progress}` | FE polls `GET /api/v1/dataset/{id}/export_status` every 2s |
| Queue Worker (future) | Queue Worker | PostgreSQL `task_queue` table (`SELECT FOR UPDATE SKIP LOCKED`, 5s poll) | [No handlers registered yet] | `{queue_name: str, payload: JSONB, max_retries: int}` | Infrastructure built but no production handlers wired |
| Pipeline controller | User (email) | SendGrid HTTP API | Email template | `{subject, body, recipient}` | Pipeline completion/error notification |

---

## 5. Domain Entities & Ownership

| Entity | Owner Service | Storage | Key Fields |
|--------|--------------|---------|------------|
| `Organization` | Clustplorer API | PostgreSQL `organizations` | `id (UUID), name, created_at` |
| `Workspace` | Clustplorer API | PostgreSQL `workspaces` | `id (UUID), name, organization_id (FK), created_at` |
| `User` | Clustplorer API + Keycloak | PostgreSQL `users` / Keycloak realm | `id (UUID), email, display_name, user_origin, sessions_invalidated_at` |
| `UserOrganization` | Clustplorer API | PostgreSQL `user_organizations` | `user_id, organization_id, role` |
| `UserWorkspace` | Clustplorer API | PostgreSQL `user_workspaces` | `user_id, workspace_id, role` |
| `ApiKey` | Clustplorer API | PostgreSQL `api_keys` | `id, user_id, key_hash, name, created_at` |
| `Access` | Clustplorer API + OpenFGA | PostgreSQL `access` / OpenFGA tuples | `id, dataset_id, user_id, operation (READ/LIST/UPDATE/DELETE/ENRICH/MANAGE_ACCESS/SHARE_DATASETS)` |
| `Dataset` | Clustplorer API / Pipeline | PostgreSQL `datasets` | `id (UUID), name, status (13-state enum), status_new, workspace_id, source_uri, source_type, serve_mode, embedding_config, enrichment_models, creation_context, created_at, s3_path` |
| `DatasetFolder` | Clustplorer API | PostgreSQL `dataset_folders` | `id (UUID), dataset_id, folder_name, path, status (UPLOADING/VALIDATING/VALID/INVALID), total_files, uploaded_files, metadata (JSON), preview_urls, selected, batch_id` |
| `Image` | Pipeline | PostgreSQL `images` | `id, dataset_id, file_path, file_name, width, height` |
| `Object` | Pipeline | PostgreSQL `objects` | `id, dataset_id, label` |
| `ObjectToImage` | Pipeline | PostgreSQL `objects_to_images` | `object_id, image_id, bbox (bounding box coordinates)` |
| `Cluster` | Pipeline | PostgreSQL `clusters` | `id, dataset_id` |
| `SimilarityCluster` | Pipeline | PostgreSQL `similarity_clusters` | `id, dataset_id` |
| `FlatSimilarityCluster` | Pipeline | PostgreSQL `flat_similarity_clusters` (partitioned) | Denormalized cluster view for DuckDB queries |
| `FlatMediaAttributes` | Pipeline | PostgreSQL `flat_media_attributes` (partitioned) | Denormalized media attributes for DuckDB queries |
| `Label` | Pipeline | PostgreSQL `labels` | `id, name, dataset_id` |
| `LabelCategory` | Clustplorer API | PostgreSQL `label_categories` | `id, name, dataset_id` |
| `Tag` | Clustplorer API | PostgreSQL `tags` | `id, name` |
| `MediaToTag` | Clustplorer API | PostgreSQL `media_to_tags` | `media_id, tag_id` |
| `MediaToCaption` | Pipeline | PostgreSQL `media_to_captions` | `media_id, caption_text` |
| `MediaToUniquenessScore` | Pipeline | PostgreSQL `media_to_uniqueness_score` | `media_id, score (float)` |
| `IssueType` | Pipeline | PostgreSQL `issue_type` | `id, name, severity (HIGH=0/MEDIUM=1/LOW=2)` |
| `ImageVector` | Pipeline | PostgreSQL `image_vector` | `image_id, vector (embedding)` |
| `QueryImage` | Clustplorer API | PostgreSQL `query_image` | `id, dataset_id, image_data` |
| `Task` | Clustplorer API | PostgreSQL `tasks` | `id, dataset_id, task_type (DATASET_CREATION/MEDIA_ADDITION/ENRICHMENT/LABEL_PROPAGATION/TRAINING/CUSTOM_METADATA/REINDEX), task_status (INITIALIZING/RUNNING/COMPLETED/FAILED/ABORTED/WAITING_FOR_REVIEW), progress, error_message` |
| `TaskQueue` | Queue Worker | PostgreSQL `task_queue` | `id (UUID), queue_name, payload (JSONB), status (PENDING/PROCESSING/COMPLETED/FAILED), retry_count, max_retries, created_at, processed_at, error_message` |
| `TrainingTask` | Clustplorer API | PostgreSQL `training_tasks` | `id, dataset_id, user_id, model_name, status (INIT/IN_PROGRESS/COMPLETED/FAILED/CANCELLED)` |
| `ExportTask` | Clustplorer API | PostgreSQL `export_task` | `id, dataset_id, user_id, entities_count, status (INIT/IN_PROGRESS/COMPLETED/FAILED/REJECTED), download_uri, result_message, progress` |
| `ModelsCatalog` | Clustplorer API | PostgreSQL `models_catalog` | `id, name, type, version, file_path` |
| `LpSeed` | Clustplorer API | PostgreSQL `lp_seed` | `id, dataset_id` |
| `LpSeedSamples` | Clustplorer API | PostgreSQL `lp_seed_samples` | `id, seed_id, media_id, label_category_id` |
| `LpFlow` | Clustplorer API | PostgreSQL `lp_flow` | `id, seed_id, status (INIT/RUNNING/PAUSED_FOR_REVIEW/COMPLETED/FAILED/ABORTED), cycle_number` |
| `LpCycleResults` | Flywheel Runner | PostgreSQL `lp_cycle_results` | `id, flow_id, media_id, predicted_label, confidence` |
| `Revision` | Clustplorer API | PostgreSQL `revisions` | `id, dataset_id, name, created_at` |
| `Fragment` | Clustplorer API | PostgreSQL `fragments` | `id, content_hash` |
| `FlowRun` | Pipeline | PostgreSQL `flow_runs` | `id, pipeline_flow, status, dataset_id` |
| `Event` | Clustplorer API | PostgreSQL `events` | `serial_n, dataset_id, event_type, event (JSONB), trans_id` |
| `SavedView` | Clustplorer API | PostgreSQL `saved_views` | `id, dataset_id, name, filters_json` |
| `AuditLog` | Clustplorer API | PostgreSQL `audit_log` | `id, user_id, action, entity_id, timestamp` |

---

## 6. External Dependencies

| Name | Type | Used By | Purpose |
|------|------|---------|---------|
| Keycloak | Identity Provider (OIDC) | Clustplorer API, Frontend | User authentication, JWT issuance, SSO, user management. Realm: `visual-layer`. Internal URL: `http://keycloak:8080` |
| OpenFGA | Authorization Service (ReBAC) | Clustplorer API | Fine-grained relationship-based access control. Store per environment: `visual-layer-{ENV_NAME}` |
| AWS S3 | Object Storage | Clustplorer API, Pipeline, Image Proxy | Dataset image storage, export files, model artifacts |
| GitHub OAuth | Identity Provider | Frontend, Clustplorer API | Social login (cloud deployments) |
| Google OAuth | Identity Provider | Frontend, Clustplorer API | Social login (cloud deployments) |
| SendGrid | Email API | Pipeline (via `vl/utils/email_notifier.py`) | Pipeline completion/error notification emails (dynamic templates) |
| Slack | Webhook | Clustplorer API | Bug report notifications via `BUG_REPORT_SLACK_WEBHOOK_URL` |
| CVAT | Annotation Tool | Clustplorer API (via `vl/utils/cvat.py`) | Import video annotation tasks and labels |
| Embedding Service | ML Microservice | Clustplorer API (via `vl/common/image_embedding_service.py`) | Image-to-vector embeddings for visual similarity search. URL: `TEXT_EMBEDDING_SERVICE_BASE_URI` |
| Camtek Train Service | gRPC Service | Pipeline (via `providers/camtek/TrainClient/`) | Customer-specific model training and inference. Endpoint: `CAMTEK_TRAIN_API_ENDPOINT` (default: `localhost:5000`) |
| NVIDIA Triton | Inference Server | Pipeline GPU | Serve ML models for batch inference during pipeline processing |
| Argo Workflows | Workflow Engine | Clustplorer API, Pipeline | Orchestrate multi-step pipeline jobs on Kubernetes |
| Amplitude | Analytics | Frontend | Product analytics and user behavior tracking |
| Google Analytics (GA4) | Analytics | Frontend | Web analytics (disabled for `ON_PREM`) |
| Sentry | Error Tracking | Clustplorer API | Error monitoring (opt-out by default: `SENTRY_OPT_OUT=True`) |
| CopilotKit | AI Chat | Frontend, Clustplorer API | AI assistant chat integration. Feature-flagged: `VL_CHAT_ENABLED` |

---

## 7. Auth & Security
- **Auth mechanism:** Multi-layered, checked in order: (1) API Key via `Authorization: Bearer <JWT>` → (2) Session cookie (`SESSION`) → (3) VL_AUTH cookie (legacy Terrogence/Codex) → (4) Keycloak OIDC JWT → (5) Anonymous fallback or HTTP 401
- **Token format:** Keycloak-issued JWT, RS256/RS384/RS512 signed, validated against JWKS endpoint. Session cookies are encrypted UUIDs with `max_age=604800` (7 days).
- **Token issuer:** Keycloak realm `visual-layer` — issuer URL dynamically constructed from `X-Forwarded-*` headers for on-prem deployments
- **Inter-service auth:** None — internal services (OpenFGA, Keycloak admin, Embedding Service, Pipeline) communicate over internal K8s network without additional auth headers (network-level trust)
- **CORS:** `allow_origins=["*"]`, `allow_credentials=True`, `allow_methods=["*"]`, `allow_headers=["*"]` — permissive; Nginx ingress expected to restrict origins in production
- **Public endpoints (no auth required):**
  - `GET /api/v1/healthcheck`
  - `GET /api/v1/version`
  - `GET /api/v1/oidc/login`
  - `GET /api/v1/oidc/callback`
  - `GET /api/v1/github-sso`
  - `POST /api/v1/google-sso`
  - `GET /backoffice`

---

## 8. Infrastructure & DevOps
- **Container orchestration:** K3s (single-node Kubernetes) for on-prem; no docker-compose. Helm chart at `devops/visual-layer/` with 44 K8s templates.
- **CI/CD:** GitHub Actions (manual `workflow_dispatch` only, self-hosted runner). Workflows:
  - `.github/workflows/create-k3s-release-onprem-runner.yml` — builds 6 Docker images, optional PyArmor obfuscation, packages release ZIP
  - `.github/workflows/build-keycloak-theme.yml` — Keycloak theme build
  - No automated test/merge pipeline found [UNCLEAR — may exist in separate CI system]
- **Environments:** `k3s` (on-prem) | `staging` | `camtek` (client override with auth disabled). Differentiated via layered Helm values files: `devops/env/{env}/values.yaml` + `devops/clients/{client}/values.yaml` → rendered into K8s ConfigMap with 150+ env vars.
- **Secrets management:**
  - Build time: AWS Secrets Manager (Docker Hub creds, PG passwords)
  - Runtime: K8s Secrets (Keycloak admin password, OIDC client secret, PG connection string)
  - Code: `ConfigValue(secret=True)` in `vl/common/settings.py` masks values in logs
- **Observability:**
  - Logging: `python-json-logger` (JSON format via `json-logging.yaml`) or flat text (`flat-logging.yaml`), loaded via `vl/common/logging_init.py`
  - Metrics: `starlette_prometheus~=0.9.0` — Prometheus `/metrics` endpoint [UNCLEAR — exact mount not confirmed]
  - Request timing: `clustplorer/middlewares/timing_middleware.py` — logs every request with `elapsed_ms`
  - Error tracking: Sentry (`SENTRY_PROJ` DSN, opt-out by default)
  - Tracing: None (no OpenTelemetry/Jaeger/Datadog found)
  - Log aggregation: Grafana Loki available as optional dependency (`devops/dependants/grafana-loki/`)

---

## 9. Key Business Flows

### Flow: Dataset Creation (On-Prem V3 Workflow)
```
[1] User clicks "New Dataset"
    → FE: DatasetCreationPage mounts, Redux dispatches fetchNewDataset()

[2] FE → POST /api/v1/workflow/dataset/new { name, source_type }
    → BE: new_dataset() → DatasetDB.create(status=NEW, status_new=DRAFT)
    → returns { dataset_id }

[3] User drags folder of images
    → FE → GET /api/v1/dataset/{id}/data/folder_upload_transaction?folder_name=...&total_files=N
    → BE: creates DatasetFolder(status=UPLOADING), updates Dataset.status → UPLOADING
    → returns { trans_id }

[4] FE chunks files (250/batch), uploads sequentially:
    → POST /api/v1/dataset/{id}/data/folder_upload/{transId}?last_chunk=0 { multipart files }
    → BE: upload each file to S3 (s3://{bucket}/{env}/uploads/{dataset_id}/{folder}/{file})
    → updates DatasetFolder.uploaded_files counter every 1%

[5] Final chunk: POST ...?last_chunk=1
    → BE: BackgroundTasks.add_task(_process_dataset_folder_background_task)
    → Background: validates folder (requires db.csv, metadata.json, classes.json),
      extracts metadata, generates previews
    → DatasetFolder.status: UPLOADING → VALIDATING → VALID (or INVALID)

[6] FE polls GET /api/v1/dataset/{id}/folders_metadata every 5s
    → stops when all folders reach VALID or INVALID

[7] User selects folders, clicks "Process"
    → FE → POST /api/v1/dataset/{id}/select_folders { folder_ids }
    → BE: validates metadata consistency (Job/Setup/Recipe must match across folders)

[8] FE → GET /api/v1/dataset/{id}/process
    → BE: creates DatasetCreationTask(status=RUNNING)
    → triggers Argo Workflow (K8s) or Pipeline via Caddy (docker-compose)
    → Dataset.status_new → INDEXING

[9] FE polls GET /api/v1/datasets/{id}/creation-status every ~5s
    → stops when status = READY or FATAL_ERROR
```
Side effects: `datasets` (insert + status updates), `dataset_folders` (insert + updates), `tasks` (insert + updates), S3 writes (all images), Argo Workflow submitted, email notification on completion/error.

### Flow: Data Exploration (VQL Search)
```
[1] User navigates to /dataset/{id}/data
    → FE: DataPage mounts, dispatches parallel API calls

[2] FE → GET /api/v1/explore/{id}/exploration_metadata?threshold=0
    → BE: returns item counts, available thresholds

[3] FE → GET /api/v1/explore/{id}?threshold=0&entity_type=IMAGES&page=1&page_size=50
    → BE: SimilarityClusterDB.similarity_clusters_by_dataset(ExplorationContext)
    → DuckDB queries on partitioned flat_similarity_clusters
    → returns paginated clusters with 18 preview images each

[4] FE: CardsView renders similarity cluster grid

[5] User applies filters (labels, issues, tags, text search)
    → URL query params updated → FE re-dispatches explore call with VQL filters
    → BE: re-queries DuckDB with new ExplorationContext

[6] User clicks cluster → FE → GET /api/v1/explore/{id}/similarity_cluster/{clusterId}
    → User clicks image → FE → GET /api/v1/dataset_image/{id}/{imageId} + /links + /labels + /issues

[7] Visual similarity search: POST /api/v1/dataset/{id}/search-image-similarity { image }
    → BE: calls Embedding Service → DuckDB VSS vector search → returns ranked results
```
Side effects: None (read-only). DuckDB in-memory analytics queries.

### Flow: Label Propagation (Flywheel / Active Learning)
```
[1] User opens Labels panel → LabelPropagation component mounts
    → FE → PUT /api/v1/flywheel/{datasetId}/seed
    → BE: creates LpSeed record → returns { seed_id }

[2] User adds label categories and drags images into seed classes
    → FE → PUT .../seed/{seedId}/label_category_id { categories }
    → FE → POST .../seed/{seedId} { media_ids[], label_category_id }
    → BE: inserts into LpSeedSamples

[3] User clicks "Start"
    → FE → PUT /api/v1/flywheel/{datasetId}/start/{seedId}
    → BE: creates LpFlow(status=INIT), creates FlywheelTask
    → launches Flywheel.run_svm() as background/Argo task → returns { flow_id }

[4] Background: trains CalibratedClassifierCV(LinearSVC) on seed embeddings
    → predicts on unlabeled media, selects top-N by confidence
    → writes predictions to ReviewSamplesCluster
    → LpFlow.status → PAUSED_FOR_REVIEW

[5] FE polls every 3-5s: GET .../status/{flowId} + GET .../stats/{flowId}
    → detects PAUSED_FOR_REVIEW → shows review UI

[6] User reviews predictions: ACCEPT / REJECT / MANUAL reclassify
    → FE → PUT .../review/{flowId}/{sampleId} { result: ACCEPTED|REJECTED }
    → BE: stores review decision

[7] User clicks "Next Cycle"
    → FE → GET .../cycle/{flowId}
    → BE: retrains SVM with expanded labeled set (accepted = positive, rejected = negative)
    → back to [4], cycle_number incremented

[8] User clicks "Apply Results"
    → FE → PUT .../apply/{flowId}
    → BE: writes predicted labels to dataset → LpFlow.status → COMPLETED
```
Side effects: `lp_seed`, `lp_seed_samples`, `lp_flow`, `lp_cycle_results`, review results. SVM model trained in-memory each cycle. On apply: bulk writes to media labels/tags.

### Flow: Model Training (Camtek gRPC)
```
[1] User navigates to /models-catalog
    → FE → GET /api/v1/training/models → list available architectures
    → FE → GET /api/v1/training/tasks → list past training tasks

[2] User selects dataset + model, clicks "Train"
    → FE → POST /api/v1/training { dataset_id, model_name }
    → BE: validates (dataset exists, authorized, train-worthy, no parallel training)
    → creates TrainingTask(status=INIT) + unified Task record
    → triggers Argo Workflow: ModelTrainingArgoPipeline
    → updates TrainingTask.status → IN_PROGRESS → returns 202 { task_id }

[3] Argo job pod: calls Camtek Train Service via gRPC
    → train_client.start_train(StartTrainRequest) → returns train_identifier
    → train_client.watch_train_status(train_id) → stream TrainStatusResponse
    → updates TrainingTask progress in DB periodically

[4] FE polls GET /api/v1/training/tasks/{taskId}
    → tracks progress until COMPLETED or FAILED

[5] Training completes → model registered in models_catalog table
    OR: User clicks "Cancel" → PATCH /api/v1/training/tasks/{taskId} { action: cancel }
    → BE: gRPC stop_train() → status → CANCELLED
```
Side effects: `training_tasks` (insert + updates), `tasks` (unified tracking), `models_catalog` (on success), Argo Workflow pod, gRPC calls to external Camtek service.

### Flow: Dataset Export (Async)
```
[1] User selects images via checkboxes → Cart tracks selectedExportIDs in Redux
[2] User clicks "Export" → ExportModal opens

[3] FE → GET /api/v1/dataset/{id}/export_entities_async?entity_ids=[...]&format=csv
    → BE: creates ExportTask(status=INIT)
    → BackgroundTasks.add_task(_export_from_context_async_detached_task)
    → returns { export_task_id }

[4] Background: queries entities, fetches images from S3, packages ZIP
    → ExportTask: INIT → IN_PROGRESS → COMPLETED (with download_uri)

[5] FE polls GET /api/v1/dataset/{id}/export_status?export_task_id= every 2s
    → detects COMPLETED → triggers browser download
    → BE serves StreamingResponse (ZIP) or S3 presigned URL redirect
```
Side effects: `export_task` (insert + updates), S3 reads (all selected images), ZIP assembled.

---

## 10. Architecture Risks & Notes

| Risk | Location | Severity | Suggested Fix |
|------|----------|----------|---------------|
| CORS allows all origins with credentials | `clustplorer/web/__init__.py` line ~253: `allow_origins=["*"]` | High | Restrict to known domains; rely on ingress-level CORS only if backend is never directly exposed |
| Internal services have no auth | OpenFGA, Keycloak admin, Embedding Service, Pipeline — all called without auth tokens | Medium | Acceptable if K8s NetworkPolicy restricts pod-to-pod traffic; otherwise add service mesh or mutual TLS |
| Pipeline shares DB directly | Pipeline reads/writes PostgreSQL via `vldbaccess` — bypasses API layer entirely | Medium | Acceptable for performance; ensure schema migrations are coordinated between API and pipeline deployments |
| PostgreSQL queue worker has no handlers | `clustplorer/logic/queue_worker/handlers/` contains only `__init__.py` | Low | Infrastructure is ready but unused; BackgroundTasks handles all async work currently |
| No automated CI test pipeline | Only manual `workflow_dispatch` workflows found | High | Add PR-triggered test workflow (pytest, eslint, type-check) to catch regressions before merge |
| Anonymous user fallback | When `DISABLE_AUTH=true`, unauthenticated requests get `DEFAULT_WEB_USER` | Medium | Ensure `DISABLE_AUTH` is never true in production; add startup warning |
| Camtek deployment has auth disabled | `devops/clients/camtek/values.yaml`: `disableAuth: true`, `oidc.enabled: false` | High | Acceptable only if network is physically isolated; add network-level access control |
| No request correlation IDs | No distributed tracing or correlation ID propagation across services | Medium | Add OpenTelemetry with trace context propagation |
| SingleDataset Redux slice is very large | `redux/SingleDataset/reducer.ts` — 50+ state fields, heavy actions | Low | Consider splitting into smaller slices (filters, navigation, metadata) for maintainability |
| Secrets in Helm values | Keycloak admin password has `default="admin"` in settings.py | Medium | Ensure production overrides all defaults; consider external secret operator |
| SSE endpoint handler not found | `/api/vl-chat/stream` is referenced in GZip exclusion but handler location is unknown | Low | May be mounted conditionally or from external package [UNCLEAR] |

---

## 11. Conventions & Standards
- **Naming conventions:**
  - Services: `kebab-case` directories (e.g. `clustplorer-be`, `image-proxy`)
  - Python packages: `snake_case` (e.g. `vldbaccess`, `fastdup_runner`)
  - API endpoints: `/api/v1/{resource}` with `snake_case` paths (e.g. `/api/v1/dataset/{id}/export_entities_async`)
  - Env vars: `SCREAMING_SNAKE_CASE` (e.g. `DUCKDB_MEMORY_LIMIT_GB`)
  - Database tables: `snake_case` (e.g. `similarity_clusters`, `media_to_tags`)
  - React components: `PascalCase` (e.g. `DatasetInventory`, `AssetPreviewCard`)
  - Redux slices: `camelCase` (e.g. `singleDataset`, `createDataset`)
  - Helm values: `camelCase` (e.g. `modelTraining.apiEndpoint`)
  - Kafka topics: N/A (no message broker)
- **Error handling:** FastAPI exception handlers in `clustplorer/web/exception_handlers/`. HTTP errors return standard FastAPI `HTTPException` with `status_code` + `detail` string. Frontend auto-logouts on 401/403 via interceptors.
- **Testing approach:** pytest with pytest-xdist (parallel) and pytest-cov (coverage). Test files in `tests/` (40+ files). Frontend: Jest + Testing Library. Storybook for component library (`npm run storybook` on port 6006).
- **Branching strategy:** Release branches: `camtek-release/{version}` (created by CI). [UNCLEAR — day-to-day branching strategy not documented in repo]
- **Code style:**
  - Python: `ruff` linter (config in `ruff.toml`)
  - TypeScript: ESLint + Prettier (config in `package.json`), Husky pre-commit hooks
  - Python formatting: [UNCLEAR — no black/isort config found, ruff may handle formatting]
- **API versioning:** All endpoints under `/api/v1/`. No v2 endpoints found.
- **OpenAPI codegen:** Frontend auto-generates React Query hooks from backend OpenAPI schema via `@openapi-codegen/cli`. Generated files in `fe/clustplorer/src/vl-api/`.
- **Feature flags:** Backend feature flags delivered via `GET /api/v1/user-config` (per-dataset). Frontend consumes via `useFeatureFlagService(featureKey)` hook returning `{ show: boolean, enabled: boolean }`. Behaviors: `SHOW`, `GREY_OUT`, or hidden.

---

## 12. Glossary

| Term | Definition |
|------|------------|
| VQL | Visual Query Language — the filter/query system used in the data exploration page, composed from URL query parameters (labels, issues, tags, text, similarity thresholds) |
| Flywheel | The active learning loop: user labels seed samples → SVM trains → predicts on unlabeled data → user reviews predictions → model retrains. Also called Label Propagation (LP) |
| LP | Label Propagation — synonym for Flywheel; uses `CalibratedClassifierCV(LinearSVC)` trained on image embeddings |
| DuckDB | In-process analytical database used for fast data exploration queries. Attached to PostgreSQL via federated queries, with VSS extension for vector similarity search |
| pgvector | PostgreSQL extension (0.8.0) providing vector data type and similarity operators for embedding storage |
| PVLD | Pre-Validated Dataset — a dataset with known-good data used as a sample or template |
| Seed | In flywheel/LP context: the initial set of user-labeled examples used to train the first SVM model |
| Flow | In flywheel context: a single label propagation run (may span multiple cycles). Tracked by `LpFlow` record |
| Cycle | One iteration of the flywheel: SVM trains → predicts → user reviews. Multiple cycles per flow |
| Enrichment | The process of adding ML-generated metadata to a dataset (captions, object detection, embeddings) via the pipeline |
| Similarity Cluster | A group of visually similar images, computed during pipeline indexing. Core unit of the exploration UI |
| Flat Response | A simplified API response format where clusters are flattened into individual media items |
| Serve Mode | Controls how images are stored/served: `proxy` (S3 streaming), `local-serving` (filesystem), `reduce_disk_space`, `skip_thumbnails` |
| Argo Workflow | Kubernetes-native workflow engine used to orchestrate multi-step pipeline jobs (preprocessing → feature extraction → indexing) |
| OpenFGA | Open Fine-Grained Authorization — a relationship-based authorization system (Google Zanzibar model). Stores tuples like `user:X viewer dataset:Y` |
| ReBAC | Relationship-Based Access Control — the authorization model used by OpenFGA |
| K3s | Lightweight Kubernetes distribution used for on-premises single-node deployments |
| Caddy | Reverse proxy used in docker-compose environments to route requests to the pipeline service (internal URL: `http://cd:2080`) |
| ConfigValue | Custom class in `vl/common/settings.py` that reads environment variables with type coercion, default values, and secret masking |
| BackgroundTasks | FastAPI's built-in mechanism for fire-and-forget async work within the same process (used for exports, folder processing, pipeline triggers) |
| task_queue | PostgreSQL table implementing a message queue pattern with `SELECT FOR UPDATE SKIP LOCKED` for concurrent consumption. Infrastructure is built but no production handlers are registered |
| PyArmor | Python code obfuscation tool — optionally applied during CI builds for on-prem releases (270-day default expiration) |
| Batch | In dataset creation: a group of files uploaded together. In add-media flow: a set of new images being added to an existing dataset. Tracked by `media_batches` table |
| Snapshot | A point-in-time copy of a dataset's state, stored via `revisions` and `fragments` tables. Supports restore and clone operations |
| BFF | Backend For Frontend — not used in this architecture; the Clustplorer API serves both browser and programmatic clients |
| DLQ | Dead-Letter Queue — not implemented; the `task_queue` retries up to `max_retries` then marks as FAILED |
