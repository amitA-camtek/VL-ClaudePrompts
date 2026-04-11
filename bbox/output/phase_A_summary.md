# Phase A – System Understanding Summary

> **Project:** vl-camtek — Wafer Defect Inspection & Dataset Management Platform  
> **Feature:** Defect Crop Viewer (intermediate stage between ScanResult selection and dataset export)

---

## 1. Architecture Overview

```
┌──────────────────────────────────────────────────────────────────────────┐
│                         SYSTEM ARCHITECTURE                              │
│                                                                          │
│  ┌─────────────────────────────────────────────────────────────────────┐ │
│  │                   Camtek AOI System (Hardware)                      │ │
│  │   Wafer Scanner ──► Defect Detection ──► Classification ──► Export │ │
│  │   (EAGLET_106739)    (optical/laser)      (99+ OClass codes)        │ │
│  └──────────────────────────┬──────────────────────────────────────────┘ │
│                             │  gRPC (DataServerClient)                   │
│                             ▼                                            │
│  ┌─────────────────────────────────────────────────────────────────────┐ │
│  │               vl-camtek Backend (FastAPI + Python)                  │ │
│  │                                                                     │ │
│  │  clustplorer/web/         <- API endpoints (25+ routers)           │ │
│  │  vl/services/             <- Business logic                        │ │
│  │  vl/tasks/                <- Async background workers              │ │
│  │  vldbaccess/              <- ORM models + DB access                │ │
│  │  providers/camtek/        <- gRPC client to Camtek Data Server     │ │
│  │                                                                     │ │
│  │  DB: PostgreSQL (metadata, datasets, users)                        │ │
│  │      DuckDB (analytical queries)                                   │ │
│  │  Storage: S3 / local filesystem (images, exports)                  │ │
│  └──────────────────────────┬──────────────────────────────────────────┘ │
│                             │  REST/JSON  (axios, React Query)           │
│                             ▼                                            │
│  ┌─────────────────────────────────────────────────────────────────────┐ │
│  │              vl-camtek Frontend (React 18 + TypeScript)             │ │
│  │                                                                     │ │
│  │  fe/clustplorer/src/                                                │ │
│  │    views/pages/ScanResults/     <- TARGET: insert crop viewer here │ │
│  │    views/pages/DataPage/        <- Dataset exploration             │ │
│  │    views/pages/DatasetCreation/ <- Dataset creation wizard         │ │
│  │    redux/                       <- State management                │ │
│  └─────────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Backend – Key Modules and Responsibilities

| Module | File | Responsibility |
|--------|------|----------------|
| **Scan Results API** | `clustplorer/web/api_scan_results.py` | List wafer scans, export ADC to dataset, repository management |
| **Dataset API** | `clustplorer/web/api_datasets.py` | CRUD for datasets, status polling |
| **Image API** | `clustplorer/web/api_image.py` | Serve dataset images by `dataset_id/image_id` |
| **Dataset Creation API** | `clustplorer/web/api_dataset_create_workflow.py` | Folder upload, validation, preview generation |
| **Dataset BL** | `clustplorer/logic/datasets_bl.py` | Trigger processing pipeline, validation |
| **Dataset Creation Task** | `vl/tasks/dataset_creation/` | Multi-stage async worker: ingest → index → cluster → enrich |
| **Process Folder Task** | `vl/tasks/process_dataset_folder_task/` | Parse DB.csv, extract metadata, generate previews |
| **Camtek Provider** | `providers/camtek/DataServerClient/` | gRPC calls: list scans, export ADC, validate recipes |
| **DB Models** | `vldbaccess/` | SQLAlchemy models: Dataset, DatasetFolder, User, Cluster |

### Framework Details
- **Runtime:** FastAPI 0.115+ with Uvicorn ASGI server
- **ORM:** SQLAlchemy 2.x async sessions
- **Auth:** OpenFGA row-level access control + `Security(get_authenticated_user)` on all endpoints
- **Task orchestration:** Argo Workflows (K8s) or local async workers
- **Router registration:** Each `api_*.py` file defines `router = APIRouter(...)`, registered in `clustplorer/web/__init__.py` via `app.include_router(router)`

---

## 3. Frontend – Component Structure

```
fe/clustplorer/src/
├── views/
│   ├── pages/
│   │   ├── ScanResults/                   <- TARGET: insert crop viewer here
│   │   │   ├── index.tsx                  <- Main scan results table
│   │   │   ├── ExportDatasetModal.tsx     <- Existing export modal (keep unchanged)
│   │   │   └── RepositoriesModal/         <- Repository management
│   │   ├── DataPage/
│   │   │   ├── ImageView/
│   │   │   │   └── ImageSection/
│   │   │   │       ├── BoundingBox/       <- REUSE: existing bbox component
│   │   │   │       │   └── index.tsx
│   │   │   │       └── IssuesBoundingBox/
│   │   │   │           └── index.tsx
│   │   │   └── ...
│   │   └── DatasetCreationPage/
│   └── components/
│       ├── ROISquare/
│       ├── ImageWithFallback/
│       └── ...
├── redux/                                 <- Redux slices per feature
│   ├── datasets/
│   ├── singleDataset/
│   └── ...
└── App.tsx                                <- Route definitions
```

### State Management
- **Redux Toolkit** — application-level state (datasets list, current dataset, filters, modals, user)
- **TanStack React Query** — server state (API calls, caching, background polling, mutations)
- **Local `useState`** — UI-only state (open/close modals, selected rows, form values)
- Pattern: new feature uses React Query for API data, local state for UI interactions

### Styling
- **SCSS Modules** (`.module.scss`) for all components — scoped, no global leakage
- **Ant Design 5** component library (Button, Modal, Table, Spin, Alert, Slider, Statistic)
- **Bootstrap utilities** for grid/responsive layout
- CSS variables for theme tokens (e.g., `var(--text-color-on-primary)`, `var(--pure-white)`)

---

## 4. DB.csv – Schema Deep Dive

The central data source for the new feature. Located in each scan export folder as `DB.csv`.

### Column Reference (18 columns, verified from actual export)

| # | Column | Type | Example | Notes |
|---|--------|------|---------|-------|
| 1 | `ImageName` | String | `images/lot_01/259793.119486.c.-1615541774.1.jpeg` | Relative path from scan folder root. Filename encodes wafer coords. |
| 2 | `Tool` | String | `EAGLET_106739` | Machine identifier |
| 3 | `Job Name` | String | `MTK-AHJ11236` | Project/job name (**space in column name**) |
| 4 | `Setup Name` | String | `setup1` | Test configuration (**space in column name**) |
| 5 | `Recipe` | Integer | `1`, `2` | Recipe numeric ID |
| 6 | `Recipe Name` | String | `x7.5 Bump PMI` | Human-readable recipe (**space in column name**) |
| 7 | `Wafer` | String | `01`, `02` | Wafer ID within lot |
| 8 | `Lot` | String | `lot` | Lot identifier |
| 9 | `Col` | Integer | `0`–`7` | Die column index |
| 10 | `Row` | Integer | `0`–`24` | Die row index |
| 11 | `Mode` | String | `Color` | Imaging mode |
| 12 | `OClass` | Integer | `1`, `34`, `65` | **Defect class code.** 1=Pass. See Classes.json for all 99+ codes. |
| 13 | `Index` | Integer | `0`, `134217728` | Die index (unique per wafer) |
| 14 | `Wafer X` | Float (μm) | `259794.2874` | **Absolute X on wafer in microns** (**space in column name**) |
| 15 | `Wafer Y` | Float (μm) | `119487.3653` | **Absolute Y on wafer in microns** (**space in column name**) |
| 16 | `XInFrame` | Integer | `0` | Pixel X of defect within frame image |
| 17 | `YInFrame` | Integer | `0` | Pixel Y of defect within frame image |
| 18 | `Zone` | Integer | `7`, `9`, `63` | Inspection zone ID |

> **Critical:** Column names contain spaces (`"Wafer X"`, `"Job Name"`, etc.).  
> Always access with exact string: `row.get("Wafer X")`, NOT `row.get("WaferX")`.

### Verified Data Profile (Real Export)

```
Export: MTK-AHJ11236_setup1_20260406_201352
─────────────────────────────────────────────
Total rows:          180 defect records
Unique ImageNames:   180  (1 defect per image in this export)
XInFrame unique:     {0}  (ALL ZERO – see Constraint C1)
YInFrame unique:     {0}  (ALL ZERO – see Constraint C1)
Recipes:             2  (x7.5 Bump PMI, x3.5 Surface)
Wafers:              2  (lot_01: 90 imgs, lot_02: 90 imgs)
Image sizes:         161 KB – 272 KB per JPEG
Total images:        ~44 MB
```

### OClass Filter Reference

| OClass | Label | Treatment |
|--------|-------|-----------|
| `1` | Pass | **SKIP** |
| `23` | Missing Bump type 1 | Show |
| `34` | Foreign Particle / Embedded | Show |
| `58` | Bump damage / Missing Bump type 2 | Show |
| `65` | Other | Show |
| `2147483644` | EBR | **SKIP** (sentinel) |
| `2147483645` | Null | **SKIP** (sentinel) |
| `2147483646` | Mark | **SKIP** (sentinel) |

```python
SKIP_CLASSES = {1, 2147483644, 2147483645, 2147483646}
```

---

## 5. Coordinate System Diagram

```
Wafer Coordinate System (microns)
┌──────────────────────────────────────────────────────────────────┐
│                         Physical Wafer                           │
│                                                                  │
│  Wafer X range in dataset: ~105,000 – 505,000 μm               │
│  Wafer Y range in dataset: ~33,000  – 450,000 μm               │
│                                                                  │
│   Each ● = one row in DB.csv (one defect, one image)            │
│                                                                  │
│     ●   ●               ●                                        │
│         ●   ●●     ●                                             │
│                 ●●●  ●     ●●                                    │
│        ●                        ●                                │
│                  ●  ●                                            │
│                                                                  │
│  Die pitch: ~100–300 μm                                          │
│  Recommended clustering eps: 300–500 μm                         │
└──────────────────────────────────────────────────────────────────┘

Per-Image Coordinate System (pixels)
┌──────────────────────────────────────────────────────────────────┐
│  Frame Image (e.g. 800×600 px)                                   │
│  Filename: 259793.119486.c.-1615541774.1.jpeg                    │
│                                                                  │
│  IN THIS DATASET: XInFrame=0, YInFrame=0 for all rows           │
│  → defect is the subject of the entire close-up image            │
│  → use centered fallback bounding box (40% of W/H)              │
│                                                                  │
│  IN FUTURE DATASETS (XInFrame/YInFrame populated):              │
│  ┌─────────────────────────────────┐                             │
│  │                                 │                             │
│  │     (XInFrame, YInFrame)        │                             │
│  │          ┌──────┐               │                             │
│  │          │defect│  <- pixel bbox│                             │
│  │          └──────┘               │                             │
│  │                                 │                             │
│  └─────────────────────────────────┘                             │
└──────────────────────────────────────────────────────────────────┘
```

---

## 6. Data Flow Diagrams

### 6.1 Current Flow (Before New Feature)

```
[User] selects scan results in /scan-results
    │
    ▼
[Click "Export to VL Dataset"]
    │
    ▼
ExportDatasetModal (dataset name + export path)
    │
    ▼
POST /api/v1/scan-results/export-dataset
    │ validates: same recipe, ManReClassify consistent
    ▼
gRPC: DataServerClient.export_adc(paths, export_path)
    │ creates: DB.csv + Classes.json + MetaData.json + images/
    ▼
Backend detects new export folder (timestamp-based)
    │
    ▼
ProcessDatasetFolderTask
    │ reads DB.csv → metadata, classes, preview URLs
    │ triggers DatasetCreationTaskService
    ▼
DatasetCreationTaskService
    │ ingest → index (FAISS) → cluster → enrich
    ▼
Dataset READY in PostgreSQL
    │
    ▼
[User navigates to /dataset/{id}/data]
```

### 6.2 New Flow (With Defect Crop Viewer Inserted)

```
[User] selects scan results in /scan-results
    │
    ▼
[Click "Export to VL Dataset"]  (button behavior changed)
    │
    ▼
DefectCropViewer Modal opens
    │
    ├── GET /api/v1/scan-results/defect-clusters
    │       ?path={scan_path}&eps=300&pad=64
    │
    │   Backend:
    │   parse_db_csv(path)
    │       └── filter OClass ∉ SKIP_CLASSES
    │       └── normalize column names (handle spaces)
    │   group_by_recipe(defects)
    │   for each recipe:
    │       get_image_dims(image_path)  <- PIL header read (cached)
    │       dbscan_cluster(wafer_x, wafer_y, eps_um=300)
    │       if all_singletons: retry with eps*2 (max 3x)
    │       for each cluster:
    │           compute_crop_rect(cluster, pad=64)
    │           clamp to image bounds
    │           normalize_bboxes(defects, crop_rect)
    │   return CropResponse{viewport, total_defects, total_crops, crops[]}
    │
    ├── User sees: Wafer Map + Cluster Grid
    │   - can adjust eps slider (debounced 400ms)
    │   - can adjust pad slider
    │
    ▼
[Click "Confirm & Create Dataset"]
    │
    ▼
ExportDatasetModal  (UNCHANGED – same as before)
    │
    ▼
POST /api/v1/scan-results/export-dataset  (UNCHANGED)
    │
    ▼
... (same pipeline as current flow) ...
    │
    ▼
[User navigates to /dataset/{id}/data]
```

---

## 7. API Communication Summary

### Existing Endpoints (no changes)

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/v1/scan-results` | List scan results with filters |
| `POST` | `/api/v1/scan-results/export-dataset` | Export scan(s) as VL dataset |
| `GET` | `/api/v1/scan-results/repositories` | List scan repositories |

### New Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/v1/scan-results/defect-clusters` | Parse DB.csv, spatial cluster by Wafer X/Y, return crop metadata |
| `GET` | `/api/v1/scan-results/image` | Serve raw scan images securely (path-traversal validated) |

---

## 8. Constraints and Assumptions

| ID | Constraint / Assumption | Source / Evidence |
|----|------------------------|-------------------|
| C1 | **XInFrame = YInFrame = 0** for all rows in this export. Use Wafer X/Y for spatial clustering; use centered bounding box fallback. | Verified: 180/180 rows |
| C2 | **1 image = 1 defect** in this dataset. "Multiple bboxes per crop" is achieved by spatial grouping of nearby images, not within one image. | 180 unique ImageNames |
| C3 | **Wafer X/Y are in microns.** DBSCAN eps must be in microns (e.g., 300μm ≈ 1–3 die pitches). | DB.csv value scale |
| C4 | **Column names have spaces:** `"Wafer X"`, `"Wafer Y"`, `"Job Name"`, etc. Use exact strings. | DB.csv header |
| C5 | **Multiple recipes per export** — cluster per recipe to avoid cross-recipe duplication. | MetaData.json: 2 recipes |
| C6 | **Special OClass sentinels** (2147483644/45/46) must be skipped like OClass=1. | Classes.json |
| C7 | **Pillow 12.0.0** available — use for header-only dimension extraction. | requirements.txt |
| C8 | **scikit-learn 1.7.2** available — DBSCAN can use sklearn or pure-Python fallback. | requirements.txt |
| C9 | **scipy 1.15.3** available — can use cKDTree for auto-eps computation. | requirements.txt |
| C10 | **Crop viewer is preview-only** — it does not change what gets exported (original images always exported). | Design decision |
| C11 | **Path traversal must be validated** — `path` query param is user-controlled. | Security audit |
| C12 | **Router registration in `__init__.py`** requires 2 manual additions: import + `include_router`. | Code review |
| C13 | Images are JPEG on local disk at the scan export path. | Verified: 180 `.jpeg` files |

---

## 9. Existing Components Available for Reuse

| Component | Location | Reuse Strategy |
|-----------|----------|----------------|
| `BoundingBox` | `fe/.../DataPage/ImageView/ImageSection/BoundingBox/index.tsx` | Reference scaling formula: `left = bbox[0] * widthRatio / 100` |
| `IssuesBoundingBox` | Same directory | Reference label collision-avoidance logic |
| `ExportDatasetModal` | `fe/.../ScanResults/ExportDatasetModal.tsx` | No changes — open after crop viewer confirm |
| `ImageWithFallback` | `fe/.../components/ImageWithFallback/` | Wrap scan images for broken-link fallback |
| `ROISquare` | `fe/.../components/ROISquare/ROISquare.tsx` | Reference for centered indicator styling |
| `vl-cropper.css` | `fe/.../DataPage/ImageView/ImageSection/vl-cropper.css` | Reference for crop-related CSS patterns |
| Auth: `get_authenticated_user` | `clustplorer/web/auth.py` | Apply to all new endpoints exactly as in `api_scan_results.py` |
| Ant Design: `Spin`, `Alert`, `Slider`, `Statistic`, `Empty` | Already installed | Use for loading/error/empty states in crop viewer |
