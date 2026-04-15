# AI Presentations Summary

## Presentation 1: AI_VL.pptx — "AI Detection Model: User Story & UI Mockups"

This is a detailed **product specification** for building an end-to-end **AI defect detection workflow** on the **Visual Layer (VL)** platform for **Camtek's AOI (Automated Optical Inspection)** team.

It defines **8 sequential flows**:

| Flow | Purpose |
|------|---------|
| **1 — Load SR Data** | Ingest TIFF images + `db.csv` from AOI scan results into VL; auto-cluster by visual similarity |
| **2 — Explore & QA** | Browse clusters, detect outliers/duplicates/quality issues, spatial navigation (Wafer → Die → Frame → Tile) |
| **3 — Annotate** | Draw bounding boxes on defect tiles, assign classes (Surface, Particle, Via, Scratch), toggle B&W/Color, edge-exclusion |
| **4 — Auto-Annotation** | Run a pre-trained detection model on unannotated tiles; review predictions via Accept/Edit/Reject workflow |
| **5 — Train/Val/Test Split** | Allocate annotations into 70/20/10 splits (Random, Stratified, or Manual); lock test set |
| **6 — Train Model** | Launch detection training (YOLOv8 / Faster R-CNN) with configurable hyperparameters; track in Task Manager |
| **7 — Evaluate Model** | Validate on held-out test set with mAP, Precision, Recall, F1, Confusion Matrix; navigate to misclassified tiles |
| **8 — Iterate & Retrain** | Improve weak classes, retrain, compare model versions side-by-side in Model Catalog, deploy to production |

The final slide includes a **Gap Severity Summary** categorizing missing features by priority (Critical / High / Medium), noting that annotation capabilities, defect data model restructuring, and auto-annotation pipeline are the most critical gaps.

---

## Presentation 2: AI Classification Annotation.pptx — "AI Classification/Annotation Tool"

This is a more **implementation-focused spec** for a standalone annotation and model lifecycle tool. It covers:

**Model Life Cycle:** Data prep → Training → Evaluation → Offline Inference → Model Comparison → Production deployment.

**Key Features:**
- Single app for data preparation, training, and validation
- Two input modes: **online** (Scan Results) and **offline** (vcam)
- Iterative training from algorithm annotations to AI annotations
- Multi-BIN classification, support images (neighbor die comparison), wafer/die/frame spatial views
- Offline mode: scan vcam and export report + flt file
- Post-model rules, dynamic test reports, comparison reports

**9 Flows defined:**

| Flow | Purpose |
|------|---------|
| **1** | Load scan result TIFFs into DB, navigate to exact tile |
| **2** | Draw/edit/delete bounding boxes, assign classes, B&W/Color toggle, save to DB |
| **3** | Inspect defect table (col, row, area, width, bbox, die/wafer coordinates), navigate via table clicks |
| **4** | Allocate tiles to Train/Validation/Test sets with configurable test percentage |
| **5** | Spatial navigation: Wafer → Die → Frame → Tile with zoom, jump, and edge-exclusion filters |
| **6** | Close the loop: train model, review confusion matrix, iterate on misclassified tiles, retrain |
| **7** | Post-model rules: add BIN-based rules to models in the Model Catalog |
| **8** | Offline inference: run trained model on new unlabeled data, human verification (Agree/Disagree), compute accuracy |
| **9** | Model comparison: compare two models on the same dataset (Baseline vs Candidate), spatial matching, select best for deployment |

---

## Key Differences

- **AI_VL** is designed around the **Visual Layer platform**, with rich UI mockups and acceptance criteria — it's a product-level spec for integrating detection into VL.
- **AI Classification Annotation** is more of a **standalone tool spec** with additional features like offline vcam scanning, post-model rules, model comparison (Baseline vs Candidate), and human verification workflows.
- Both share the same core loop (load data → annotate → split → train → evaluate → iterate), but the second presentation adds **inference verification**, **model comparison**, and **post-model rules** as distinct flows.

---

## Flow 2 — Explore Dataset & Quality Assessment: Detailed Requirements

### Goal

Understand the dataset before annotation — identify quality issues, surface mislabeled images, and prioritize annotation effort. The user must be able to assess data quality and defect distribution without opening a single image manually.

---

### REQ-2.1 — Explore Tab Entry Point

**Description:** When the user opens a dataset, the **Explore** tab is the primary landing view for data investigation.

| Requirement | Detail |
|---|---|
| REQ-2.1.1 | The Explore tab is accessible from the dataset sidebar alongside **Data** and **Models Jobs** tabs |
| REQ-2.1.2 | The header bar displays: dataset name, total image count, creation date, and status badge (`READY` / `DRAFT` / `ERROR`) |
| REQ-2.1.3 | A **search bar** ("Search by labels") allows free-text search across OClass names from `Classes.json` (e.g., typing "Bump" filters to all Bump-related classes) |
| REQ-2.1.4 | A **Reset** button clears all active filters and returns to the full unfiltered view |
| REQ-2.1.5 | An **Add Filter** dropdown exposes all available filter categories (Class, Quality, Zone, Recipe, Wafer, Col, Row, Tag) |

**Data mapping (DB.csv):**
- Total image count = number of rows in DB.csv (e.g., 180 defect records)
- Dataset name derived from `MetaData.json` → Job Name + Setup Name (e.g., "MTK-AHJ11236 — setup1")
- Label search matches against `Classes.json` display names mapped from DB.csv `OClass` column

---

### REQ-2.2 — Cluster View

**Description:** Auto-generated visual similarity clusters allow the user to quickly identify patterns, group similar defects, and spot outliers without reading individual records.

| Requirement | Detail |
|---|---|
| REQ-2.2.1 | On dataset creation (Flow 1), VL runs a clustering algorithm that groups images by visual similarity |
| REQ-2.2.2 | Cluster View is the default view in the Explore tab, toggled via a **view switcher** icon (`⊞ Cluster View` / `☷ Table/Tile View`) |
| REQ-2.2.3 | Each cluster displays as a card showing: representative thumbnail, cluster size (image count), and dominant OClass label |
| REQ-2.2.4 | Clicking a cluster expands it to show all member images in a thumbnail grid |
| REQ-2.2.5 | Clusters that contain mixed OClass values are visually flagged as potential mislabel candidates |
| REQ-2.2.6 | The user can select one or more clusters and apply bulk actions: **Tag for exclusion**, **Tag for review**, **Reclassify** |
| REQ-2.2.7 | Cluster membership persists — re-opening the Explore tab shows the same clusters until a re-cluster is triggered |

**Data mapping (DB.csv):**
- Clustering input: the JPEG images referenced in the `ImageName` column (e.g., `images/lot_01/259793.119486.c.-1615541774.1.jpeg`)
- Cluster labels derived from `OClass` column mapped through `Classes.json` (e.g., OClass `1` → "Pass", `30` → "PI Contamination", `34` → "Foreign Particle after CP")
- With 97.8% of images classified as "Pass" (OClass=1), clustering should reveal sub-groups within "Pass" that may actually be distinct defect types requiring reclassification

---

### REQ-2.3 — Table / Tile View

**Description:** A split-panel view with an image viewer on the left and a defects data table on the right, enabling record-by-record inspection and navigation.

#### REQ-2.3.1 — Tile Image Viewer (Left Panel)

| Requirement | Detail |
|---|---|
| REQ-2.3.1.1 | Displays the current tile's defect image loaded from the `ImageName` path in DB.csv |
| REQ-2.3.1.2 | Supports JPEG and TIFF image formats |
| REQ-2.3.1.3 | Overlays bounding boxes on the image for each defect annotation (if annotations exist), color-coded by class |
| REQ-2.3.1.4 | Tile navigation controls: **Prev Tile** / **Next Tile** buttons, and a position indicator showing current tile index (e.g., "Tile 7 / 230 (Die 3,4 — Frame 12)") |
| REQ-2.3.1.5 | The position indicator derives from DB.csv: Die position = `Col`,`Row` columns; Frame is computed from spatial grouping of `Wafer X`/`Wafer Y` coordinates |
| REQ-2.3.1.6 | Zoom and pan controls for high-resolution image inspection |
| REQ-2.3.1.7 | B&W / Color toggle to switch image rendering mode (from DB.csv `Mode` column — currently all "Color") |

#### REQ-2.3.2 — Defects Table (Right Panel)

| Requirement | Detail |
|---|---|
| REQ-2.3.2.1 | Each row represents one defect on the current tile, with columns: **ID**, **Class**, **X (px)**, **Y (px)**, **W (px)**, **H (px)**, **Conf.** |
| REQ-2.3.2.2 | The **Class** column shows the human-readable name from `Classes.json` (not the numeric OClass ID) |
| REQ-2.3.2.3 | Clicking a row in the table highlights the corresponding bounding box on the tile image |
| REQ-2.3.2.4 | The table supports sorting by any column (e.g., sort by Conf. to find low-confidence detections) |
| REQ-2.3.2.5 | The table supports filtering by class name, confidence range, or defect size (W/H) |
| REQ-2.3.2.6 | Multiple defects per tile are supported — each with its own independent class assignment |

**Data mapping (DB.csv):**
- **ID** = `Index` column (unique defect identifier, e.g., `0`, `134217728`)
- **Class** = `OClass` mapped through `Classes.json` (e.g., `1` → "Pass", `34` → "Foreign Particle after CP - Embedded foreign material")
- **X, Y** = `Wafer X`, `Wafer Y` for wafer-level position, or `XInFrame`, `YInFrame` for frame-level position (note: XInFrame/YInFrame are 0 in current data — pixel-level defect coordinates may need to be extracted from the image or a separate annotation source)
- **Conf.** = confidence score from the AOI algorithm or AI model (not present in current DB.csv — this is a field that auto-annotation/inference will populate)

---

### REQ-2.4 — Insights Panel

**Description:** A collapsible side panel that provides at-a-glance dataset health metrics and defect distribution summaries.

| Requirement | Detail |
|---|---|
| REQ-2.4.1 | The Insights Panel opens alongside the Cluster View or Table/Tile View without replacing it |
| REQ-2.4.2 | **Duplicate count**: number of visually duplicate or near-duplicate images detected during clustering |
| REQ-2.4.3 | **Outlier count**: number of images that don't fit any cluster well (high distance from cluster centroid) |
| REQ-2.4.4 | **Dark image count**: number of images flagged by quality analysis as too dark for reliable annotation |
| REQ-2.4.5 | **Defect distribution bar chart**: horizontal bars showing image count per OClass, labeled with class names from `Classes.json` |
| REQ-2.4.6 | Clicking a bar in the distribution chart filters the main view to show only images of that class |
| REQ-2.4.7 | All counts update dynamically when filters are applied (e.g., filtering to Recipe 2 recalculates all metrics for that subset) |

**Data mapping (DB.csv):**
- Distribution bars for this dataset: Pass (176), PI Contamination (2), Foreign Particle after CP (2)
- The heavy class imbalance (97.8% Pass) should be visually prominent — the Insights Panel helps the user immediately see that annotation effort should focus on the minority classes
- Breakdown by Recipe: Recipe 1 "x7.5 Bump PMI" (6 images), Recipe 2 "x3.5 Surface" (174 images)
- Breakdown by Wafer: Wafer 01 (90 images), Wafer 02 (90 images — identical defect set, indicating the same defects were exported for both wafers)

---

### REQ-2.5 — Filters

**Description:** A composable filter system that allows the user to narrow the dataset view across multiple dimensions simultaneously.

#### REQ-2.5.1 — Class Outliers Filter

| Requirement | Detail |
|---|---|
| REQ-2.5.1.1 | Activating the **Class Outliers** filter surfaces images whose visual appearance is inconsistent with their assigned OClass label |
| REQ-2.5.1.2 | A **confidence slider** (0.0 – 1.0) controls the sensitivity: lower threshold = more images flagged as potential mislabels |
| REQ-2.5.1.3 | Outlier detection compares the image's cluster membership against its OClass — if an image labeled "Pass" (OClass=1) clusters with "PI Contamination" (OClass=30) images, it is flagged |
| REQ-2.5.1.4 | Flagged images appear with a visual indicator (e.g., orange border or warning icon) in both Cluster View and Table/Tile View |

#### REQ-2.5.2 — Quality Issues Filter

| Requirement | Detail |
|---|---|
| REQ-2.5.2.1 | The **Quality Issues** filter provides sub-toggles for: **Blur**, **Dark**, **Bright** |
| REQ-2.5.2.2 | Each sub-toggle independently filters images flagged with that quality issue |
| REQ-2.5.2.3 | Quality analysis runs automatically during dataset creation (Flow 1) and assigns quality flags per image |
| REQ-2.5.2.4 | Images failing quality checks are shown with severity indicators (e.g., yellow = marginal, red = unusable) |

#### REQ-2.5.3 — Data-Driven Filters (from DB.csv columns)

| Filter | Source Column | Values (this dataset) | Behavior |
|---|---|---|---|
| **Recipe** | `Recipe` / `Recipe Name` | `x7.5 Bump PMI`, `x3.5 Surface` | Filter to images from one or more recipes |
| **Wafer** | `Wafer` | `01`, `02` | Filter to a specific wafer |
| **Zone** | `Zone` | `7`, `9`, `63` | Filter to a specific inspection zone |
| **Col** | `Col` | `0`–`21` | Filter to a die column range |
| **Row** | `Row` | `0`–`25` | Filter to a die row range |
| **OClass** | `OClass` | `1`, `30`, `34` (mapped to names via Classes.json) | Filter to one or more AOI classification labels |
| **Tag** | User-assigned | `Exclude`, `Review`, custom tags | Filter by user-applied tags |

| Requirement | Detail |
|---|---|
| REQ-2.5.3.1 | Multiple filters are composable (AND logic) — e.g., Recipe = "x3.5 Surface" AND Zone = 63 AND OClass = 1 |
| REQ-2.5.3.2 | Active filters are shown as removable chips/badges above the image grid |
| REQ-2.5.3.3 | Applying any filter immediately updates: (a) the thumbnail grid, (b) the Insights Panel counts, (c) the Cluster View groupings |
| REQ-2.5.3.4 | Filter state persists during the session — switching between Cluster View and Table/Tile View does not reset filters |

---

### REQ-2.6 — Tagging & Exclusion

**Description:** The user can tag individual images or bulk-tag filtered sets to control which images enter the annotation queue.

| Requirement | Detail |
|---|---|
| REQ-2.6.1 | Right-click an image or select multiple images → context menu offers: **Tag as Exclude**, **Tag for Review**, **Add Custom Tag** |
| REQ-2.6.2 | Bulk tagging: apply a tag to all currently filtered/visible images in one action |
| REQ-2.6.3 | Images tagged as **Exclude** are removed from the annotation queue (Flow 3) and are not eligible for training allocation (Flow 5) |
| REQ-2.6.4 | Images tagged as **Review** are flagged for engineer review — they remain visible but are highlighted with a review indicator |
| REQ-2.6.5 | Tags are persisted to the database and survive session restarts |
| REQ-2.6.6 | A tag summary is shown in the Insights Panel: count of excluded, review, and custom-tagged images |
| REQ-2.6.7 | Tags can be removed — untagging an excluded image returns it to the annotation queue |

---

### REQ-2.7 — Spatial Navigation: Wafer → Die → Frame → Tile

**Description:** A hierarchical drill-down navigation from wafer-level overview to individual tile-level inspection, driven by the coordinate system in DB.csv.

#### REQ-2.7.1 — Wafer Map View

| Requirement | Detail |
|---|---|
| REQ-2.7.1.1 | Displays a 2D wafer map with the die grid layout (Col 0–21 × Row 0–25 for this dataset) |
| REQ-2.7.1.2 | Each die cell is color-coded by defect status: **Good** (no defects / only Pass), **Defects** (contains non-Pass OClass), **Selected** (currently focused die) |
| REQ-2.7.1.3 | Defect count per die is shown as a heat overlay or numeric badge |
| REQ-2.7.1.4 | Hovering over a die shows a tooltip: Die(Col, Row), defect count, dominant class |
| REQ-2.7.1.5 | Clicking a die navigates to the **Die View** for that position |
| REQ-2.7.1.6 | The wafer map respects active filters — if filtered to Recipe 2 only, dies with only Recipe 1 defects appear as "Good" |
| REQ-2.7.1.7 | Wafer selector dropdown allows switching between wafers (e.g., Wafer 01 / Wafer 02) |

**Data mapping (DB.csv):**
- Die grid built from unique `Col`/`Row` combinations
- Defect markers placed using `Wafer X` (range 26,165–303,025 µm) and `Wafer Y` (range 22,260–305,021 µm) coordinates
- Hotspot dies at edges: Col 0 (rows 10–13) and Row 25 (cols 10–11) have 10 defects each
- Color derived from `OClass`: die with only OClass=1 (Pass) → Good; die containing OClass=30 or 34 → Defects

#### REQ-2.7.2 — Die View

| Requirement | Detail |
|---|---|
| REQ-2.7.2.1 | Shows the layout of the selected die with frame boundaries and defect position markers |
| REQ-2.7.2.2 | Breadcrumb navigation updates: `Wafer → Die (Col, Row)` (e.g., `Wafer → Die (3,4)`) |
| REQ-2.7.2.3 | Defect markers are color-coded by class (BIN colors from `Classes.json`) |
| REQ-2.7.2.4 | Clicking a defect marker or frame region navigates to the **Frame View** |
| REQ-2.7.2.5 | Defect positions within the die are computed from `Wafer X`/`Wafer Y` relative to the die origin |

#### REQ-2.7.3 — Frame View

| Requirement | Detail |
|---|---|
| REQ-2.7.3.1 | Shows the selected frame divided into tiles with defect markers at tile positions |
| REQ-2.7.3.2 | Breadcrumb updates: `Wafer → Die (Col, Row) → Frame N` |
| REQ-2.7.3.3 | A color/BIN legend is shown (e.g., Good / Pass / PI Contamination / Foreign Particle) |
| REQ-2.7.3.4 | Clicking a tile marker navigates to the **Tile View** and loads the defect image |
| REQ-2.7.3.5 | Frame-level defect positions use `XInFrame`/`YInFrame` when available (note: currently 0 in this dataset — fallback to computing from `Wafer X`/`Wafer Y` relative to frame origin) |

#### REQ-2.7.4 — Tile View (Annotation Workspace entry)

| Requirement | Detail |
|---|---|
| REQ-2.7.4.1 | Displays the tile image with any existing bounding box annotations overlaid |
| REQ-2.7.4.2 | Breadcrumb updates: `Wafer → Die (Col, Row) → Frame N → Tile M` |
| REQ-2.7.4.3 | Navigation: **Prev Tile** / **Next Tile** with tile counter (e.g., "Tile 7 / 230") |
| REQ-2.7.4.4 | From here the user can enter the full Annotation Workspace (Flow 3) to draw/edit bounding boxes |
| REQ-2.7.4.5 | The tile's defect table (REQ-2.3.2) is shown alongside the image |

**End-to-end navigation example (this dataset):**
1. Wafer Map → see hotspot at Die (0, 10) with 10 defects
2. Click Die (0, 10) → Die View shows defect positions within that die
3. Click a frame region → Frame View shows tile markers
4. Click tile → Tile View loads `images/lot_01/26163.131595.c.67609716.2.jpeg` (OClass=1, Recipe "x3.5 Surface", Zone 63)

---

### REQ-2.8 — Defect Distribution & Insights Bars

**Description:** Visual analytics showing how defects are distributed across classes, recipes, zones, and spatial positions.

| Requirement | Detail |
|---|---|
| REQ-2.8.1 | **Per-class distribution**: horizontal bar chart in Insights Panel showing image count per OClass. For this dataset: Pass=176, PI Contamination=2, Foreign Particle=2 |
| REQ-2.8.2 | **Per-recipe breakdown**: grouped or stacked bars showing defect counts per recipe. For this dataset: x3.5 Surface=174, x7.5 Bump PMI=6 |
| REQ-2.8.3 | **Per-zone breakdown**: defect counts by inspection zone. For this dataset: Zone 63=174, Zone 9=4, Zone 7=2 |
| REQ-2.8.4 | **Spatial heatmap**: overlay on wafer map showing defect density per die region, highlighting edge-die concentrations |
| REQ-2.8.5 | All distribution views update dynamically when filters are applied |
| REQ-2.8.6 | Clicking any bar or heatmap segment acts as a filter — narrows the main view to that subset |
| REQ-2.8.7 | **Class imbalance warning**: when any class has fewer than a configurable threshold (e.g., <50 images), display a warning badge indicating insufficient samples for training |

**Data-driven insight for this dataset:**
- Class imbalance is extreme: 97.8% Pass vs 1.1% PI Contamination vs 1.1% Foreign Particle
- The Insights bars should make this immediately visible so the user knows to either: (a) collect more data for minority classes, (b) apply oversampling/augmentation strategies, or (c) re-annotate "Pass" images that may actually contain defects the AOI missed

---

### Acceptance Criteria Summary

| ID | Criterion | Verification |
|---|---|---|
| AC-2.1 | Outlier and quality issue counts visible before annotation starts | Insights Panel loads with duplicate, outlier, dark counts on first Explore tab open |
| AC-2.2 | Spatial navigation Wafer → Die → Frame → Tile works end-to-end | User can click through all 4 levels and arrive at a tile image with its defect table |
| AC-2.3 | Filtered view updates dynamically in thumbnail grid and Insights Panel | Applying any filter immediately recalculates counts and re-renders the image grid |
| AC-2.4 | Tagged images excluded from annotation queue | Images tagged "Exclude" do not appear in Flow 3 annotation workflows or Flow 5 allocation |
| AC-2.5 | Cluster View groups images by visual similarity | Clusters are generated on dataset creation; visually similar defects appear in the same cluster |
| AC-2.6 | Table/Tile View shows defect-level data per tile | Table displays ID, Class, X, Y, W, H, Conf. with row-click-to-highlight on the image |
| AC-2.7 | Class outlier filter surfaces mislabeled images | Adjusting confidence slider reveals images whose visual cluster differs from their OClass label |
| AC-2.8 | Quality filter flags blur/dark/bright images | Each quality sub-toggle independently filters and counts affected images |
| AC-2.9 | Multi-filter composition works | Stacking Recipe + Zone + OClass filters produces correct AND-logic intersection |
| AC-2.10 | Distribution bars reflect real data | Bar chart for this dataset shows Pass=176, PI Contamination=2, Foreign Particle=2 matching DB.csv |

---

## Flow 2 — UI Component to Requirement Mapping & Gap Analysis

This section maps every UI element visible in the AI_VL.pptx Flow 2 mockup slides (Slide 7: Cluster View | Table/Tile View, Slide 8: Spatial Navigation) to the detailed requirements above, and identifies gaps where either the UI has no requirement or a requirement has no UI representation.

---

### UI Component Inventory — Slide 7 (Cluster View | Table/Tile View)

#### A. Left Sidebar Icon Bar

The mockup shows a vertical icon sidebar with 8 icons acting as global navigation:

| Icon | UI Label | Mapped Requirement | Status |
|---|---|---|---|
| V | App logo / Home | — | **GAP-01**: No requirement defines what the logo/home icon does (e.g., return to Dataset Inventory from Flow 1) |
| ⊞ | Cluster View shortcut | REQ-2.2.2 | Covered — part of view toggle |
| ☷ | Table / Tile View shortcut | REQ-2.2.2 | Covered — part of view toggle |
| ◎ | Spatial Navigation (Wafer Map) | REQ-2.7 | **GAP-02**: The sidebar shows a dedicated icon for spatial navigation as a top-level entry point. The requirements only describe spatial navigation as a drill-down from the Explore tab. No requirement exists for a **sidebar shortcut** that opens the Wafer Map directly |
| ⊙ | Unknown — possibly Insights / Analytics | REQ-2.4? | **GAP-03**: This icon has no documented function. If it opens the Insights Panel, that should be specified. If it's a different feature (e.g., dashboard, analytics), it needs a requirement |
| ⚙ | Settings | — | **GAP-04**: No requirement for dataset-level or app-level settings accessible from the Explore view. What settings are configurable here? (e.g., clustering parameters, quality thresholds, display preferences) |
| 📖 | Documentation / Help | — | **GAP-05**: No requirement for contextual help or documentation access. Low priority but present in the UI |
| 👤 | User Profile / Account | — | **GAP-06**: No requirement for user identity display. Relevant because annotations must record annotator ID (per Flow 3 acceptance criteria: "annotator ID, timestamp, source=manual") |

#### B. Dataset Header Bar

| UI Element | Mockup Content | Mapped Requirement | Status |
|---|---|---|---|
| Dataset name | "Luna For App" | REQ-2.1.2 | Covered |
| ⓘ Info button | Click icon next to name | — | **GAP-07**: The ⓘ button appears next to the dataset name. No requirement defines what it shows. Expected: dataset metadata popup (source SR folder, MetaData.json fields: customer, job, setup, recipes, tool, export timestamp, total image/object/video counts) |
| Image count | "Images 22.5K" | REQ-2.1.2 | Covered |
| Creation date | "Created 5 Days Ago" | REQ-2.1.2 | Covered |
| Status badge | "Ready" | REQ-2.1.2 | Covered |

#### C. Tab Bar

| UI Element | Mockup Content | Mapped Requirement | Status |
|---|---|---|---|
| Models Jobs tab | "✦ Models Jobs" | — | Out of scope for Flow 2 (belongs to Flow 6/7). Covered in requirements but the ✦ icon suggests AI-specific content |
| Data tab | "Data" | — | Out of scope for Flow 2 (belongs to Flow 1 data management) |
| Explore tab | "Explore" (active) | REQ-2.1.1 | Covered |

#### D. Filter / Toolbar Bar

| UI Element | Mockup Content | Mapped Requirement | Status |
|---|---|---|---|
| Content type label | "Images" | — | **GAP-08**: The label "Images" implies the ability to switch between content types (Images / Objects / Videos — also referenced in the Dataset Inventory slide showing "Image / Object / Video counts"). No requirement covers switching the Explore view between these content types |
| Search box | "Search by labels" | REQ-2.1.3 | Covered |
| Reset button | "↺ Reset ▾" | REQ-2.1.4 | Partial — **GAP-09**: The ▾ caret on the Reset button suggests a dropdown menu (e.g., "Reset filters", "Reset view", "Reset tags"). The requirement only describes a simple reset-all action. Dropdown options need specification |
| Add Filter | "‡‡ Add Filter ▾" | REQ-2.1.5 | Covered |
| Filtered count | "22,541 images" | — | **GAP-10**: This count appears in the filter bar and should reflect the **currently filtered** image count, not just the total. No requirement distinguishes between total count (header) and filtered count (filter bar). Requirement needed: "The filter bar shows the count of currently visible images after all filters are applied. Format: `N images` or `N of M images` when filters are active" |

#### E. View Toggle

| UI Element | Mockup Content | Mapped Requirement | Status |
|---|---|---|---|
| Cluster View toggle | "⊞ Cluster View" | REQ-2.2.2 | Covered |
| Table/Tile View toggle | "☷ Table / Tile View" | REQ-2.2.2 | Covered |
| Toggle description | "Switch between views using the toggle" | REQ-2.2.2 | Covered |

#### F. Cluster View (when active)

| UI Element | Mockup Content | Mapped Requirement | Status |
|---|---|---|---|
| Cluster grouping | "Defects grouped by visual similarity" | REQ-2.2.1, REQ-2.2.3 | Covered |
| Cluster cards | (shown as description, no detailed mockup) | REQ-2.2.3 | Partial — **GAP-11**: The mockup shows the Cluster View as a label/description only. No detailed cluster card design is provided. Missing UI details: cluster card layout (thumbnail grid? single representative image?), cluster count badge, expand/collapse behavior, cluster selection (checkbox? click?) for bulk actions |
| Cluster pagination / scrolling | Not shown | — | **GAP-12**: With potentially thousands of clusters (22.5K images), no requirement or UI element addresses pagination, virtual scrolling, or lazy loading for the cluster grid |
| Cluster sorting | Not shown | — | **GAP-13**: No UI element or requirement for sorting clusters (by size, by class homogeneity, by outlier score). The user needs a way to prioritize which clusters to review first |

#### G. Table / Tile View — Tile Image Viewer (Left Panel)

| UI Element | Mockup Content | Mapped Requirement | Status |
|---|---|---|---|
| Tile image display | "[Tile Image — TIFF]" | REQ-2.3.1.1, REQ-2.3.1.2 | Covered |
| Annotation overlays | "Surface #1", "Surface #2", "Via #3" with bounding boxes | REQ-2.3.1.3 | Partial — **GAP-14**: The mockup shows annotation labels on the image in the format `ClassName #N` (e.g., "Surface #1"). No requirement specifies the label format for annotation overlays on the tile image. Requirement needed: "Each bounding box overlay shows a label with `ClassName #SequentialIndex` positioned at the top-left corner of the box, color-coded by class" |
| Prev Tile button | "◀ Prev Tile" | REQ-2.3.1.4 | Covered |
| Next Tile button | "Next Tile ▶" | REQ-2.3.1.4 | Covered |
| Tile position indicator | "Tile 7 / 230 (Die 3,4 — Frame 12)" | REQ-2.3.1.4, REQ-2.3.1.5 | Covered |
| Zoom / Pan controls | Not shown in mockup | REQ-2.3.1.6 | **GAP-15**: Requirement exists but no UI element is shown in the mockup. Need to define: zoom buttons (+/-), scroll-to-zoom, pan via drag, fit-to-window button, zoom percentage indicator |
| B&W / Color toggle | Not shown in this slide (shown in Flow 3 slide) | REQ-2.3.1.7 | Covered (in Flow 3 UI) but **GAP-16**: Not present in the Explore tab's Table/Tile View. Should it be available here during exploration, or only in the Annotation Workspace? Needs clarification |

#### H. Table / Tile View — Defects Table (Right Panel)

| UI Element | Mockup Content | Mapped Requirement | Status |
|---|---|---|---|
| Table header | "Defects in this tile" | REQ-2.3.2 | Covered |
| Column: ID | "1", "2", "3" | REQ-2.3.2.1 | Covered |
| Column: Class | "Surface", "Surface", "Via" | REQ-2.3.2.1, REQ-2.3.2.2 | Covered |
| Column: X (px) | "312", "774", "663" | REQ-2.3.2.1 | Covered |
| Column: Y (px) | "184", "453", "204" | REQ-2.3.2.1 | Covered |
| Column: W (px) | "224", "204", "184" | REQ-2.3.2.1 | Covered |
| Column: H (px) | "280", "320", "241" | REQ-2.3.2.1 | Covered |
| Column: Conf. | "0.94", "0.88", "0.79" | REQ-2.3.2.1 | Covered |
| Row click → highlight | Not visually shown but implied | REQ-2.3.2.3 | Covered (requirement exists) |
| Column sorting | Not shown in mockup | REQ-2.3.2.4 | **GAP-17**: Requirement exists but no sort indicators (▲/▼) are shown in the table header UI. Need to define: clickable column headers with ascending/descending sort icons |
| Table filtering | Not shown in mockup | REQ-2.3.2.5 | **GAP-18**: Requirement exists but no filter controls are shown in the table UI. Need to define: filter row below headers, or column-level filter dropdowns |
| Annotation source column | Not shown | — | **GAP-19**: No column distinguishes annotation source (Manual / Auto / AOI). This is critical because Flow 4 auto-annotations are "shown in distinct color" and users need to know which annotations are from the original AOI OClass vs. manual vs. auto-annotation. Requirement needed: add `Source` column with values: `AOI`, `Manual`, `Auto` |
| Annotation status column | Not shown | — | **GAP-20**: No column shows annotation review status (Pending / Reviewed / Accepted / Rejected). Flow 4 defines Accept/Edit/Reject workflow. The table should reflect this status |

---

### UI Component Inventory — Slide 8 (Spatial Navigation)

#### I. Breadcrumb Navigation Bar

| UI Element | Mockup Content | Mapped Requirement | Status |
|---|---|---|---|
| Breadcrumb trail | "Wafer → Die (3,4) → Frame 12 → Tile 7 ●" | REQ-2.7.2.2, REQ-2.7.3.2, REQ-2.7.4.2 | Partial — **GAP-21**: No requirement specifies that breadcrumb segments are **clickable for backward navigation**. The user should be able to click "Die (3,4)" from the Tile view to jump back to Die View without going through Wafer Map again. Requirement needed: "Each breadcrumb segment is a clickable link. Clicking a parent level navigates back to that view while preserving the selection context" |
| Active level indicator | "● " dot on Tile 7 | — | **GAP-22**: The ● dot indicates the current active level. No requirement defines visual indication of the active navigation level in the breadcrumb |

#### J. Wafer Map Panel

| UI Element | Mockup Content | Mapped Requirement | Status |
|---|---|---|---|
| Wafer map grid | Die cells arranged in wafer layout | REQ-2.7.1.1 | Covered |
| Legend: Good | Green color | REQ-2.7.1.2 | Covered |
| Legend: Defects | Red/orange color | REQ-2.7.1.2 | Covered |
| Legend: Selected | Blue/highlight color | REQ-2.7.1.2 | Covered |
| Die click → drill-down | Click die to open Die View | REQ-2.7.1.5 | Covered |
| Wafer zoom | Not shown | — | **GAP-23**: No zoom controls shown for the wafer map. With a 22×26 die grid, zooming into dense regions is needed. The AI Classification Annotation.pptx Flow 5 mentions "User can zoom in/out on the wafer." Requirement needed: add zoom/pan to wafer map |
| Wafer selector | Not shown | REQ-2.7.1.7 | **GAP-24**: Requirement exists for wafer selector dropdown but it is not visible in the mockup. Need UI placement (e.g., dropdown above the wafer map: "Wafer: 01 ▾") |

#### K. Die View Panel

| UI Element | Mockup Content | Mapped Requirement | Status |
|---|---|---|---|
| Die layout | "Die View — Die (3, 4)" with frame markers | REQ-2.7.2.1 | Covered |
| Defect markers | ● dots positioned within die | REQ-2.7.2.3 | Covered |
| Frame boundaries | Implied by marker grid layout | REQ-2.7.2.1 | Partial — **GAP-25**: The mockup shows markers (●) but does not clearly show frame boundary lines. Requirement says "frame boundaries" but the UI doesn't explicitly draw them. Need to define: are frames shown as rectangular regions within the die? Are they numbered? |
| Marker click → drill-down | Click marker to open Frame/Tile | REQ-2.7.2.4 | Covered |
| Marker color by class | Not explicitly color-varied in mockup | REQ-2.7.2.3 | **GAP-26**: Requirement says markers are color-coded by class, but the mockup shows uniform ● markers. Need to confirm: do markers use the same BIN color scheme as the wafer map legend? |

#### L. Tile / Annotation Workspace Panel

| UI Element | Mockup Content | Mapped Requirement | Status |
|---|---|---|---|
| Tile image | "[Tile Image — TIFF]" | REQ-2.7.4.1 | Covered |
| Bounding boxes on image | "Bounding boxes drawn on tile image" | REQ-2.7.4.1 | Covered |
| Defects table | Not shown in slide 8 | REQ-2.7.4.5 | **GAP-27**: The spatial navigation slide shows the tile image but NOT the defects table alongside it. The Table/Tile View (slide 7) shows the table. Need to clarify: when arriving at a tile via spatial navigation, is the defects table visible or does the user need to switch to Table/Tile View? |

---

### Elements in Requirements But NOT in Any UI Mockup

These requirements are defined in the user story (slide 6) and the requirements document but have **no visual representation** in the mockup slides:

| Missing UI | Requirements | Impact |
|---|---|---|
| **Insights Panel** | REQ-2.4.1 – REQ-2.4.7 | **GAP-28 (Critical)**: The Insights Panel (duplicates, outliers, dark image counts, distribution bars) is a core part of the user story (step 2, 7) and acceptance criteria but has no mockup. Need: panel layout, position (right sidebar? overlay?), open/close trigger, metric card design, bar chart design |
| **Class Outliers filter + confidence slider** | REQ-2.5.1.1 – REQ-2.5.1.4 | **GAP-29 (Critical)**: User story step 3 describes this as a key interaction but no UI shows where the slider lives, how outlier images are highlighted, or how the filter integrates with the Add Filter dropdown |
| **Quality Issues filter (blur/dark/bright)** | REQ-2.5.2.1 – REQ-2.5.2.4 | **GAP-30 (High)**: User story step 4 describes this filter but no UI shows the sub-toggles or quality severity indicators |
| **Tagging controls** | REQ-2.6.1 – REQ-2.6.7 | **GAP-31 (High)**: User story step 5 describes tagging for exclusion/review but no UI shows: right-click context menu, tag buttons, tag badges on images, bulk tag controls, tag summary in Insights |
| **Active filter chips/badges** | REQ-2.5.3.2 | **GAP-32 (Medium)**: Requirements describe removable filter chips above the image grid. No UI mockup shows this. Need: chip design (label + X close button), placement (between filter bar and image grid) |
| **Defect distribution bars** | REQ-2.8.1 – REQ-2.8.7 | **GAP-33 (High)**: Part of the Insights Panel gap. Distribution bars per class/recipe/zone and spatial heatmap have no visual mockup |
| **Class imbalance warning** | REQ-2.8.7 | **GAP-34 (Medium)**: Warning badge for classes with insufficient samples has no UI representation |

---

### Elements in UI Mockup But NOT in Requirements

These UI elements are visible in the mockups but have no corresponding requirement:

| UI Element | Location | Proposed Requirement |
|---|---|---|
| **Sidebar icon bar** (8 icons) | Left edge, all slides | **GAP-35**: Need REQ-2.0 — Global Navigation Sidebar. Define each icon's function: Home, Cluster View, Table/Tile View, Spatial Navigation, Insights/Analytics, Settings, Help, User Profile. Specify which icons are contextual (dataset must be open) vs. always available |
| **ⓘ Info button** on dataset name | Header bar | **GAP-07**: Need REQ-2.1.6 — Dataset Info Popup. Clicking ⓘ displays a popup/modal with: source SR folder path, MetaData.json fields (customer, job, setup, recipes, tool), creation timestamp, image/defect counts, dataset version |
| **"Images" content type label** | Filter bar | **GAP-08**: Need REQ-2.1.7 — Content Type Selector. If the dataset contains images, objects (detected defects), and videos, the user should be able to switch the Explore view between these types. This aligns with the Dataset Inventory showing "Image / Object / Video counts" |
| **Tile position format** "Die 3,4 — Frame 12" | Tile navigation | Partially covered in REQ-2.3.1.5 but **GAP-36**: The format convention needs explicit specification: `Tile N / Total (Die Col,Row — Frame F)`. Define how Frame number is derived from the spatial hierarchy |
| **Annotation label format** "Surface #1" | Tile image overlay | **GAP-14**: Need REQ-2.3.1.8 — Annotation Overlay Labels. Each bounding box shows `ClassName #SequentialIndex` at the top-left of the box, color-matching the box border |

---

### Gap Summary — Prioritized

#### Critical Gaps (Block core workflow)

| Gap ID | Description | Affected Requirements | Recommendation |
|---|---|---|---|
| **GAP-28** | No UI mockup for Insights Panel | REQ-2.4 | Design mockup showing: panel position (right sidebar), open/close button, metric cards (duplicates, outliers, dark), distribution bar chart, dynamic count updates |
| **GAP-29** | No UI mockup for Class Outliers filter + confidence slider | REQ-2.5.1 | Design mockup showing: slider control within the filter panel or Insights Panel, visual indicator on flagged images (orange border), integration with the Add Filter workflow |
| **GAP-19** | Defects table missing `Source` column (AOI/Manual/Auto) | REQ-2.3.2 | Add `Source` column to the table schema. Values: `AOI` (from DB.csv OClass), `Manual` (human-drawn), `Auto` (model inference). Color-code rows by source |
| **GAP-10** | No filtered image count in filter bar | REQ-2.1 | Show `N of M images` when filters are active; show `M images` when no filters. The mockup shows "22,541 images" which should dynamically update |

#### High Gaps (Degrade user experience)

| Gap ID | Description | Affected Requirements | Recommendation |
|---|---|---|---|
| **GAP-30** | No UI mockup for Quality Issues filter | REQ-2.5.2 | Design filter sub-panel with toggle switches: Blur (on/off), Dark (on/off), Bright (on/off). Show count per quality issue type. Add severity color to image thumbnails |
| **GAP-31** | No UI mockup for Tagging controls | REQ-2.6 | Design: (a) right-click context menu on image thumbnails with tag options, (b) tag toolbar button for bulk actions, (c) tag badge overlay on image thumbnails, (d) tag filter in Add Filter dropdown |
| **GAP-33** | No UI mockup for distribution bars / analytics | REQ-2.8 | Design within the Insights Panel: horizontal bar chart per OClass, clickable bars that act as filters, class imbalance warning badges |
| **GAP-02** | Sidebar spatial nav icon has no requirement | REQ-2.7 | Add REQ-2.7.0: "A spatial navigation icon (◎) in the left sidebar provides direct access to the Wafer Map view from any screen within the dataset" |
| **GAP-20** | Defects table missing annotation review status | REQ-2.3.2 | Add `Status` column: `Pending`, `Reviewed`, `Accepted`, `Rejected`. Critical for Flow 4 auto-annotation review workflow |
| **GAP-21** | Breadcrumb segments not specified as clickable | REQ-2.7 | Add REQ-2.7.5: "Each segment in the breadcrumb bar (Wafer → Die → Frame → Tile) is a clickable link that navigates back to that hierarchy level, preserving the parent selection context" |
| **GAP-23** | No zoom controls for wafer map | REQ-2.7.1 | Add REQ-2.7.1.8: "Wafer map supports zoom in/out (scroll wheel or +/- buttons) and pan (click-drag) for inspecting dense die regions" |

#### Medium Gaps (Polish and completeness)

| Gap ID | Description | Affected Requirements | Recommendation |
|---|---|---|---|
| **GAP-07** | ⓘ info button behavior undefined | REQ-2.1 | Add REQ-2.1.6: "Clicking the ⓘ icon next to the dataset name opens a metadata popup showing: SR folder path, customer, job, setup, recipes, tool, export timestamp, image format, total counts" |
| **GAP-08** | Content type selector ("Images") undefined | REQ-2.1 | Add REQ-2.1.7: "A content type toggle (Images / Objects / Videos) in the filter bar switches the Explore view between available data types" |
| **GAP-12** | No cluster pagination / virtual scrolling | REQ-2.2 | Add REQ-2.2.8: "Cluster View supports virtual scrolling or pagination for datasets exceeding 100 clusters. Loading indicator shown during cluster computation" |
| **GAP-13** | No cluster sorting | REQ-2.2 | Add REQ-2.2.9: "Cluster View supports sorting by: cluster size (largest first), class homogeneity (most mixed first), outlier score (most anomalous first)" |
| **GAP-14** | Annotation label format on image unspecified | REQ-2.3.1 | Add REQ-2.3.1.8: "Each bounding box overlay displays a label `ClassName #N` (e.g., 'Surface #1') at the top-left corner, color-coded to match the box border color" |
| **GAP-15** | Zoom/pan UI controls not shown | REQ-2.3.1 | Define zoom UI: +/- buttons, scroll-to-zoom, fit-to-window button, zoom percentage indicator, pan via click-drag |
| **GAP-16** | B&W/Color toggle missing from Explore view | REQ-2.3.1 | Clarify: should the toggle be available in Explore's Table/Tile View, or only in Flow 3's Annotation Workspace? Recommend: make it available in both |
| **GAP-17** | Table sort indicators not shown | REQ-2.3.2 | Add sort arrow icons (▲/▼) to each column header. Default sort: by ID ascending |
| **GAP-18** | Table filter controls not shown | REQ-2.3.2 | Add per-column filter: dropdowns for Class, range sliders for numeric columns (X, Y, W, H, Conf.) |
| **GAP-24** | Wafer selector not shown in UI | REQ-2.7.1 | Add dropdown above wafer map: "Wafer: 01 ▾" with options from DB.csv Wafer column |
| **GAP-25** | Frame boundaries not clearly shown in Die View | REQ-2.7.2 | Clarify Die View design: draw frame boundary rectangles within the die layout, numbered (Frame 1, Frame 2, …) |
| **GAP-26** | Marker colors in Die View not differentiated | REQ-2.7.2 | Show markers using the same BIN color legend from the wafer map. Add a legend to the Die View panel |
| **GAP-27** | Defects table not shown alongside tile in spatial nav | REQ-2.7.4 | Clarify: when user arrives at tile via Wafer→Die→Frame→Tile, does the defects table auto-appear or must the user switch to Table/Tile View? |
| **GAP-32** | Active filter chips not shown | REQ-2.5.3 | Design filter chip bar between the filter toolbar and the image grid. Each chip shows filter name + value + X close button |
| **GAP-34** | Class imbalance warning not shown | REQ-2.8 | Design warning badge on the distribution bar chart: "⚠ < 50 samples" next to classes below threshold |
| **GAP-35** | Sidebar icon bar has no requirement | — | Add REQ-2.0: Global Navigation Sidebar defining all 8 icon functions |
| **GAP-36** | Tile position format not standardized | REQ-2.3.1 | Define format convention: `Tile N / Total (Die Col,Row — Frame F)` — derive Frame from spatial grouping |

#### Low Gaps (Nice to have)

| Gap ID | Description | Recommendation |
|---|---|---|
| **GAP-04** | Settings icon undefined | Define what dataset/app settings are configurable (clustering parameters, quality thresholds, default view) |
| **GAP-05** | Help/Documentation icon undefined | Link to contextual help for the Explore tab features |
| **GAP-06** | User profile icon undefined | Show logged-in user name/role; relevant because annotations record annotator ID |
| **GAP-09** | Reset button dropdown undefined | Define dropdown options: "Reset all filters", "Reset view to default", "Reset tags" — or simplify to single-action button |
| **GAP-22** | Active breadcrumb level indicator (●) undefined | Define visual styling: bold text + dot indicator for current level, regular text for parent levels |

---

### Coverage Matrix

| Requirement Group | UI Elements in Mockup | Coverage | Open Gaps |
|---|---|---|---|
| **REQ-2.1** — Explore Tab Entry | Header, tabs, search, reset, add filter | 80% | GAP-07, GAP-08, GAP-09, GAP-10 |
| **REQ-2.2** — Cluster View | View toggle, cluster description | 40% | GAP-11, GAP-12, GAP-13 (no detailed cluster card UI) |
| **REQ-2.3** — Table/Tile View | Tile image, nav controls, defects table | 75% | GAP-14, GAP-15, GAP-16, GAP-17, GAP-18, GAP-19, GAP-20 |
| **REQ-2.4** — Insights Panel | **None** | **0%** | GAP-28 (Critical — entire panel missing from mockups) |
| **REQ-2.5** — Filters | Add Filter button only | 15% | GAP-29, GAP-30, GAP-32 (no outlier/quality/chip UI) |
| **REQ-2.6** — Tagging | **None** | **0%** | GAP-31 (entire tagging UI missing from mockups) |
| **REQ-2.7** — Spatial Navigation | Wafer map, die view, breadcrumb, tile | 70% | GAP-21, GAP-23, GAP-24, GAP-25, GAP-26, GAP-27 |
| **REQ-2.8** — Distribution & Insights | **None** | **0%** | GAP-33, GAP-34 (covered only if Insights Panel is designed) |

**Overall Flow 2 UI coverage: ~45%** — The core browsing and navigation structures are represented in the mockup, but the analytical and quality-assessment features that make Flow 2 distinct from a simple image browser (Insights Panel, outlier detection, quality filters, tagging) have **no UI design** yet.

---

### Recommended Next Steps

1. **Design the Insights Panel mockup** (GAP-28, GAP-33, GAP-34) — this is the highest-value gap since it enables the core goal: "Understand the dataset before annotation"
2. **Design the filter interaction mockup** (GAP-29, GAP-30, GAP-32) — show how Class Outliers slider, Quality Issues toggles, and active filter chips integrate with the existing filter bar
3. **Design the tagging interaction mockup** (GAP-31) — show context menu, bulk tag toolbar, tag badges on images
4. **Add missing table columns** (GAP-19, GAP-20) — `Source` and `Status` columns are essential for the annotation lifecycle
5. **Detail the Cluster View card design** (GAP-11, GAP-12, GAP-13) — the current mockup only labels it; need actual card layout with thumbnails, counts, and interaction patterns
6. **Finalize the sidebar icon functions** (GAP-35, GAP-02, GAP-03) — define the global navigation model so all flows share a consistent sidebar

---

## Flow 2 Spatial Navigation — UI to Requirement Mapping & Gap Analysis

The Spatial Navigation form (Wafer → Die → Frame → Tile) is defined in **AI_VL.pptx Slide 8** and **reused across 7 flows** in both presentations. This analysis maps every UI element from Slide 8 to the requirements, then cross-references the additional UI details that other flows contribute to the same shared form.

### Where the Spatial Navigation Form Is Reused

| Flow | Source | How It Uses Spatial Navigation |
|---|---|---|
| **Flow 2** — Explore (AI_VL Slide 8) | Primary mockup | Full Wafer → Die → Frame → Tile drill-down for dataset exploration |
| **Flow 3** — Annotate (AI_VL Slide 9–10) | Entry point | "Navigate to tile via spatial wafer/die/frame view"; breadcrumb `Die (3,4) > Frame 12 > Tile 7` persists in Annotation Workspace |
| **Flow 7** — Evaluate (AI_VL Slide 17) | Navigation from report | "Navigate misclassified tiles directly from report to Annotation Workspace" |
| **Flow 8** — Iterate (AI_VL Slide 19) | Filtered navigation | "Filter dataset by those classes in Explore tab → find unannotated tiles" |
| **Flow 1** — Load SR (Annotation.pptx Slide 5) | Tile navigation | "Tiles list / Frames list / Dice list" left nav + "Jump tiles\frames\dice" input |
| **Flow 5** — Visual Nav (Annotation.pptx Slide 9) | Dedicated spatial flow | Full Wafer → Die → Frame → Tile with zoom, jump, sort/filter, edge-exclusion |
| **Flow 9** — Model Comparison (Annotation.pptx Slide 14) | Comparison overlay | "Visualize agreement and differences across wafer, die, and frame levels" |
| **Slide 24** — Wafer/Die View spec (Annotation.pptx) | Standalone UI spec | Tooltip details, table-plot linkage, scan/unscanned colors |

---

### UI Component Inventory — AI_VL.pptx Slide 8

#### M. Breadcrumb Navigation Bar

| UI Element | Mockup Content | Mapped Requirement | Status |
|---|---|---|---|
| Level 1 | "Wafer" | REQ-2.7.1 | Covered — but **GAP-S01**: No requirement for "Wafer" as clickable text that returns to full wafer map from any deeper level |
| Separator | "▶" between levels | — | **GAP-S02**: Separator character (▶) is a visual detail. Not blocking, but breadcrumb rendering should be specified: separator style, spacing, truncation for deep hierarchies |
| Level 2 | "Die (3,4)" | REQ-2.7.2.2 | Covered |
| Level 3 | "Frame 12" | REQ-2.7.3.2 | Covered |
| Level 4 + indicator | "Tile 7 ●" | REQ-2.7.4.2 | Partial — the ● dot marks active level (already noted as GAP-22) |
| Clickable backward nav | Not shown but implied by ▶ separators | — | **GAP-S03** (= GAP-21 restated): Each breadcrumb level must be a clickable link for backward navigation. Clicking "Die (3,4)" from Tile view jumps back to Die View. Clicking "Wafer" returns to full wafer map. This is critical for fast navigation without going step-by-step backward |
| Flow 3 breadcrumb variant | AI_VL Slide 10: "Die (3,4) > Frame 12 > Tile 7" | REQ-2.7.4.2 | **GAP-S04**: Flow 3 uses ">" separator instead of "▶", and omits "Wafer" level. Need to define: when inside Annotation Workspace, does the breadcrumb still include the Wafer level? Is the format consistent across flows? Recommend: always show full 4-level breadcrumb `Wafer > Die(Col,Row) > Frame N > Tile M` regardless of entry point |

#### N. Wafer Map Panel

| UI Element | Mockup Content | Mapped Requirement | Status |
|---|---|---|---|
| Panel title | "Wafer Map" | REQ-2.7.1.1 | Covered |
| Legend: "Good" | Green/neutral color | REQ-2.7.1.2 | Covered |
| Legend: "Defects" | Red/alert color | REQ-2.7.1.2 | Covered |
| Legend: "Selected" | Blue/highlight color | REQ-2.7.1.2 | Covered |
| Die grid cells | Shown as rectangular cells in wafer layout | REQ-2.7.1.1 | Covered |
| Die click → drill-down | Implied (user story step 6) | REQ-2.7.1.5 | Covered |
| Zoom controls | Not shown in AI_VL mockup | — | **GAP-S05** (= GAP-23): No zoom/pan UI. However, **Annotation.pptx Flow 5 Step 1** explicitly states: "User can zoom in/out on the wafer as needed." Requirement needed: zoom buttons (+/−), scroll-to-zoom, pan via click-drag, fit-to-window |
| Wafer selector | Not shown | REQ-2.7.1.7 | **GAP-S06** (= GAP-24): Requirement exists but no UI placement. Need: dropdown or tab bar above wafer map: "Wafer: 01 ▾" |
| Scanned/unscanned die coloring | Not shown in AI_VL | — | **GAP-S07**: **Annotation.pptx Slide 24** specifies: "Wafer plot will show all the dice in the wafer. Different colors to scan\unscanned dice." The current requirements only define Good/Defects/Selected states. Need a 4th state: **Unscanned** (grey/empty) for dies not covered by the SR |
| Defect count badge per die | Not shown | REQ-2.7.1.3 | **GAP-S08**: Requirement exists (heat overlay or numeric badge) but no UI shows it. Need to define: is it a number inside the die cell? A color gradient? Both? |
| Hover tooltip | Not shown in AI_VL | REQ-2.7.1.4 | **GAP-S09**: Requirement exists. **Annotation.pptx Slide 24** provides specifics: "When hovering over a defect show tool tip with defect data – col\row\data\id." Need to reconcile: is the tooltip on the die cell or on individual defect markers within the die? Recommend both: die-level tooltip shows summary (Col,Row, defect count, top class); defect-level tooltip shows (col, row, OClass, Index) |
| BIN coloring for defects | Not shown in AI_VL | — | **GAP-S10**: **Annotation.pptx Slide 24** specifies: "Defects colors by classification." **Annotation.pptx Flow 5** specifies: "Defects are shown by BIN (Good/Surface/Via)." The AI_VL mockup shows only 3 states (Good/Defects/Selected) at the die level, but individual defect markers within a die should use BIN colors. Need to define: die-level uses 3-state coloring (Good/Defects/Selected), while defect markers within wafer overview use BIN-specific colors from `Classes.json` |
| Table ↔ wafer linked selection | Not shown in AI_VL | — | **GAP-S11**: **Annotation.pptx Slide 24** specifies: "Table and wafer\die view are connected. When selecting row in the table the defect is highlighted in the plot and vice versa." No requirement covers this bidirectional linkage between the defects table (REQ-2.3.2) and the wafer/die map. This is a critical interaction pattern |
| Train data visualization | Not shown | — | **GAP-S12**: **Annotation.pptx Flow 5** specifies wafer map shows "col\row positions of defects **for train**" and die view shows "defect markers **for train**." This implies the wafer map can filter to show only training-allocated images. Need requirement: spatial views can be filtered by allocation subset (Train/Val/Test) |

#### O. Die View Panel

| UI Element | Mockup Content | Mapped Requirement | Status |
|---|---|---|---|
| Panel title | "Die View — Die (3, 4)" | REQ-2.7.2.1, REQ-2.7.2.2 | Covered |
| Defect markers | 6× ● dots in a grid pattern | REQ-2.7.2.1 | Covered |
| Marker color | All same color in mockup | REQ-2.7.2.3 | **GAP-S13** (= GAP-26): Mockup shows uniform black ● markers. Requirement says color-coded by class. Need to reconcile: markers should use BIN color scheme. **Annotation.pptx Flow 5 Step 2** confirms: die shows "defect markers" implying colored markers |
| Frame boundaries | Not drawn in mockup | REQ-2.7.2.1 | **GAP-S14** (= GAP-25): The 6 markers are arranged in a grid that implies frame regions, but no frame boundary lines or frame numbers are drawn. **Annotation.pptx Flow 5 Step 3** says "Frame is divided into tiles" confirming frames are a spatial region within the die. Need: draw rectangular frame boundaries as labeled regions within the die, with markers inside them |
| Marker click → drill-down | Implied (user story) | REQ-2.7.2.4 | Covered — **Annotation.pptx Flow 5 Step 2** confirms: "Press on marker will show the tile, and the frame, beneath the plot" |
| Die layout reference | Not shown | — | **GAP-S15**: **Annotation.pptx Flow 5** says die view shows layout "as in die edit." This implies there is a separate "die edit" layout definition (possibly from the recipe/setup configuration) that defines frame positions within a die. No requirement documents how the die layout (frame grid within a die) is defined or imported |
| "Show frame" toggle | Not in AI_VL | — | **GAP-S16**: **Annotation.pptx Flow 1 Step 2** mentions a "show frame" button that toggles between tile view and frame view. This toggle is not represented in the AI_VL mockup or in requirements. Need: a toggle/button in Die View or Tile View that switches between showing individual tile vs. the full frame containing multiple tiles |

#### P. Frame View (Missing from Slide 8)

| UI Element | Mockup Content | Mapped Requirement | Status |
|---|---|---|---|
| Frame View panel | **NOT SHOWN** in Slide 8 | REQ-2.7.3 | **GAP-S17 (Critical)**: The breadcrumb shows 4 levels (Wafer → Die → Frame → Tile) but the mockup only shows 3 panels: Wafer Map, Die View, and Tile/Annotation Workspace. **The Frame View is entirely missing from the UI mockup.** The user story describes 4 levels, the breadcrumb shows "Frame 12", but no panel visualizes the frame level. **Annotation.pptx Flow 5 Step 3** defines it: "Frame view: Frame is divided into tiles with defect positions. A Color/Bin legend is visible. Press on tiles' marker will show the tile." Need: add Frame View panel showing tile grid within a frame, with defect markers and BIN legend |
| Color/BIN legend in frame | — | REQ-2.7.3.3 | Covered in requirement but no mockup (part of GAP-S17) |
| Tile markers in frame | — | REQ-2.7.3.4 | Covered in requirement but no mockup (part of GAP-S17) |

#### Q. Tile / Annotation Workspace Panel

| UI Element | Mockup Content | Mapped Requirement | Status |
|---|---|---|---|
| Panel title | "Tile — Annotation Workspace" | REQ-2.7.4.1, REQ-2.7.4.4 | Covered |
| Tile image | "[Tile Image — TIFF]" | REQ-2.7.4.1 | Covered |
| Bounding boxes | "Bounding boxes drawn on tile image" | REQ-2.7.4.1 | Covered |
| Defects table alongside | Not shown in Slide 8 | REQ-2.7.4.5 | **GAP-S18** (= GAP-27): Tile panel in spatial nav view shows only the image, not the defects table. In Table/Tile View (Slide 7) the table is shown. Need to clarify: when arriving via spatial navigation, does the defects table auto-appear or must user switch view? |
| Prev/Next Tile | Not shown in Slide 8 (shown in Slide 7) | REQ-2.7.4.3 | **GAP-S19**: The Prev/Next navigation is shown in Table/Tile View (Slide 7) but absent from the spatial navigation's Tile panel (Slide 8). When user drills down to a tile via spatial nav, can they navigate to adjacent tiles? Or must they go back to Die/Frame View? |
| Transition to annotation mode | Implied by "Annotation Workspace" label | REQ-2.7.4.4 | Partial — **GAP-S20**: No UI element (button or toggle) is shown to explicitly enter annotation mode from the spatial nav tile view. Is the workspace always in annotation mode? Or is there a "read-only explore" vs. "edit annotation" toggle? Flow 3 Slide 10 shows the full annotation toolbar (Draw Box, Select, Delete, Edge Excl., B&W/Color, Save DB). These tools are absent from Slide 8. Need to define: does the tile panel in spatial nav include the annotation toolbar, or is it a read-only preview with a separate "Enter Annotation Mode" action? |

---

### Cross-Flow Features Missing from AI_VL.pptx Slide 8 Requirements

These UI elements and behaviors are described in other flows (primarily **AI Classification Annotation.pptx**) but apply to the same spatial navigation form and are **not covered** by the current requirements:

#### R. Jump Navigation

| Source | Description | Mapped Requirement | Status |
|---|---|---|---|
| Annotation.pptx Flow 1 Step 2 | "Jump tiles\frames\dice – enter number to jump" input field. User types a tile/frame/die ID and presses Go | — | **GAP-S21 (High)**: No requirement exists for a jump-to control. This is a critical efficiency feature for datasets with thousands of tiles. Requirement needed: at each spatial level (Wafer, Die, Frame, Tile), a numeric input field + Go button allows direct jump to a specific index. Format: "Jump to: [___] Go" |
| Annotation.pptx Flow 5 Step 4 | "At any level, user can: Jump tiles\frames\dice – enter number to jump" | — | Confirms GAP-S21 applies at all levels |

#### S. List-Based Navigation (Left Nav)

| Source | Description | Mapped Requirement | Status |
|---|---|---|---|
| Annotation.pptx Flow 1 Step 2 | "Tiles list / Frames list / Dice list in the left nav" — scrollable lists for Tiles Gallery view, Frame View, Die View | — | **GAP-S22 (High)**: No requirement for list-based navigation panels alongside the spatial map. This is an alternative to the visual map: a scrollable list of all tiles, frames, or dice with sortable columns. The user can click any list item to navigate directly. Need: left sidebar with 3 collapsible lists (Tiles, Frames, Dice), each showing index + defect count + class breakdown |

#### T. Sort & Filter by Col/Row at Spatial Level

| Source | Description | Mapped Requirement | Status |
|---|---|---|---|
| Annotation.pptx Flow 5 Step 4 | "Support sort + filter by col\row to quickly navigate across dense regions" | REQ-2.5.3 (partial) | **GAP-S23 (Medium)**: The data-driven filters (REQ-2.5.3) cover Col/Row filtering for the Explore tab image grid. But no requirement specifies sort/filter controls **within the spatial navigation views themselves** (e.g., filter the wafer map to show only defects in Col 0–5, or sort the die list by defect count). Need: filter/sort controls local to the spatial navigation panels |

#### U. Edge Exclusion in Spatial Context

| Source | Description | Mapped Requirement | Status |
|---|---|---|---|
| Annotation.pptx Flow 5 Step 4 | "Configure and apply 'Exclude defects at tiles edge' to filter out boxes near tile borders" | — | **GAP-S24 (Medium)**: Edge exclusion is mentioned in Flow 3 (annotation) requirements but not in spatial navigation requirements. When navigating spatially, the user should be able to toggle edge-exclusion to hide defects near tile borders. This affects defect count badges and markers in all spatial views. Need: global toggle "Exclude edge defects" with configurable margin (pixels), applied across wafer map / die view / frame view counts |

#### V. Tile ↔ Frame View Toggle

| Source | Description | Mapped Requirement | Status |
|---|---|---|---|
| Annotation.pptx Flow 1 Step 2 | "Button – 'show frame'. User can toggle between tile and frame view" | — | **GAP-S16** (already noted): A toggle that switches the canvas between showing a single tile and showing the full frame (with the tile highlighted within it). This provides context about where the tile sits within the frame. Need: "Show Frame" / "Show Tile" toggle button in the tile view toolbar |
| Annotation.pptx Flow 5 Step 3 | "Move from tile to frame view, keep defect box" | — | Extends GAP-S16: when toggling from tile to frame view, all annotation bounding boxes must be preserved and repositioned correctly within the frame coordinate system |

#### W. Bidirectional Table ↔ Plot Linkage

| Source | Description | Mapped Requirement | Status |
|---|---|---|---|
| Annotation.pptx Slide 24 | "Table and wafer\die view are connected. When selecting row in the table the defect is highlighted in the plot and vice versa" | — | **GAP-S11** (already noted): Selecting a defect in the table highlights it in the wafer/die plot, and clicking a defect marker in the plot selects the corresponding table row. This is a master-detail linkage pattern. Need: REQ-2.7.6 — Table-Plot Bidirectional Selection |

#### X. Model Comparison Spatial Overlay

| Source | Description | Mapped Requirement | Status |
|---|---|---|---|
| Annotation.pptx Flow 9 | "Visualize agreement and differences across wafer, die, and frame levels" | — | **GAP-S25 (Medium)**: The spatial navigation views must support an overlay mode for model comparison. Two result sets (Baseline vs. Candidate) are displayed simultaneously with match/mismatch/adder markers on the wafer map, die view, and frame view. This extends the spatial form with a comparison layer. Low priority for Flow 2 but needs architecture consideration now since it reuses the same views |

---

### Spatial Navigation Gap Summary — Prioritized

#### Critical Gaps

| Gap ID | Description | Recommendation |
|---|---|---|
| **GAP-S17** | Frame View panel entirely missing from mockup | Design a 4th panel between Die View and Tile View: shows tile grid within a frame, defect markers with BIN colors, Color/BIN legend. The breadcrumb already references "Frame 12" but nothing visualizes it |
| **GAP-S11** | Table ↔ wafer/die plot bidirectional selection not specified | Add REQ-2.7.6: selecting a table row highlights the defect in the spatial plot; clicking a defect marker selects the table row. This is confirmed as a requirement by Annotation.pptx Slide 24 |
| **GAP-S03** | Breadcrumb backward navigation not clickable | Add REQ-2.7.5: each breadcrumb segment is a clickable link. Clicking "Wafer" returns to full wafer map; clicking "Die (3,4)" returns to die view |

#### High Gaps

| Gap ID | Description | Recommendation |
|---|---|---|
| **GAP-S21** | No jump-to navigation control | Add REQ-2.7.7: at each spatial level, provide a numeric input "Jump to: [___] Go" for direct navigation to a specific tile/frame/die index |
| **GAP-S22** | No list-based navigation (left nav) | Add REQ-2.7.8: left sidebar with collapsible Tiles list, Frames list, Dice list — each showing index, defect count, class breakdown. Scrollable and sortable. Clicking an item navigates to that level |
| **GAP-S05** | No zoom/pan controls for wafer map | Add REQ-2.7.1.8: wafer map supports zoom (scroll wheel, +/− buttons), pan (click-drag), fit-to-window |
| **GAP-S07** | No "Unscanned" die state color | Add 4th die state to REQ-2.7.1.2: **Unscanned** (grey/empty) for dies not covered by the scan recipe |
| **GAP-S20** | Unclear transition from spatial-nav tile view to annotation mode | Define whether the tile panel in spatial nav is read-only or includes annotation tools. Recommend: spatial nav tile is read-only preview with an "Open in Annotation Workspace" button that transitions to Flow 3 with full toolbar |
| **GAP-S16** | No "Show Frame" / "Show Tile" toggle | Add REQ-2.7.9: toggle button switches tile view between single-tile and full-frame context. Bounding boxes persist when toggling |

#### Medium Gaps

| Gap ID | Description | Recommendation |
|---|---|---|
| **GAP-S04** | Breadcrumb format inconsistent between flows ("▶" vs ">", Wafer level present/absent) | Standardize: always show 4-level breadcrumb `Wafer > Die(Col,Row) > Frame N > Tile M` with ">" separator. Bold the active level. Consistent across Flow 2, 3, 7, 8 |
| **GAP-S08** | Defect count badge per die — no UI shown | Define: numeric badge in top-right corner of die cell, or color gradient fill by density |
| **GAP-S09** | Tooltip content differs between presentations | Standardize: die-level tooltip = `Die(Col,Row) — N defects — top class: ClassName`; defect-level tooltip = `Col: X, Row: Y, Class: Name, ID: Index` |
| **GAP-S10** | BIN coloring scope undefined (die-level vs defect-level) | Define 2-tier system: die cells use 4-state (Good/Defects/Selected/Unscanned); individual defect markers within any view use BIN-specific colors from `Classes.json` |
| **GAP-S12** | Spatial views not filterable by train/val/test allocation | Add REQ-2.7.10: wafer map, die view, and frame view support filter by allocation subset (Train/Val/Test/Unallocated) |
| **GAP-S13** | Die View markers not color-differentiated in mockup | Confirm BIN coloring applies. Add legend to Die View matching wafer-level BIN legend |
| **GAP-S14** | Frame boundary lines not drawn in Die View | Draw rectangular frame regions within die, labeled (Frame 1, Frame 2, …). Markers appear inside their frame region |
| **GAP-S15** | Die layout source (frame grid definition) not documented | Document: die layout (frame grid geometry) is imported from recipe/setup configuration during dataset creation (Flow 1). If unavailable, default to a single-frame die |
| **GAP-S18** | Defects table not shown alongside tile in spatial nav | Show defects table below or beside tile image in spatial nav tile view (read-only). Or provide an expand/collapse toggle |
| **GAP-S19** | No Prev/Next Tile navigation in spatial nav tile view | Add Prev/Next Tile buttons to the spatial nav tile panel, scoped to tiles within the current die/frame context |
| **GAP-S23** | No sort/filter controls local to spatial views | Add filter dropdowns to wafer map (by recipe, zone, class) and sort options to die/frame lists (by defect count, by class) |
| **GAP-S24** | Edge exclusion not accessible from spatial views | Add "Exclude edge defects" toggle to spatial navigation toolbar. When active, recalculate all counts and hide edge defects from markers |
| **GAP-S25** | Model comparison overlay not planned | Architectural note: spatial views must support dual-overlay mode for Flow 9 comparison. Consider this in the component design now |

#### Low Gaps

| Gap ID | Description | Recommendation |
|---|---|---|
| **GAP-S02** | Breadcrumb separator character not specified | Use ">" consistently. Minor styling detail |
| **GAP-S06** | Wafer selector UI placement not defined | Dropdown above wafer map: "Wafer: 01 ▾" |

---

### Spatial Navigation Coverage Matrix

| Component | AI_VL Slide 8 UI | Requirements (REQ-2.7) | Other Flow References | Coverage | Key Gaps |
|---|---|---|---|---|---|
| **Breadcrumb** | 4 levels shown | REQ-2.7.2.2, 2.7.3.2, 2.7.4.2 | Flow 3 variant | 60% | S01, S02, S03, S04 (clickable, format, consistency) |
| **Wafer Map** | Die grid + 3-state legend | REQ-2.7.1.1–2.7.1.7 | Slide 24, Flow 5 | 55% | S05, S06, S07, S08, S09, S10, S11, S12 (zoom, states, tooltips, linkage) |
| **Die View** | Title + 6 markers | REQ-2.7.2.1–2.7.2.5 | Flow 5 Step 2 | 50% | S13, S14, S15, S16 (colors, frames, layout, toggle) |
| **Frame View** | **Not shown** | REQ-2.7.3.1–2.7.3.5 | Flow 5 Step 3 | **0%** | S17 (entire panel missing from mockup) |
| **Tile View** | Image + bbox description | REQ-2.7.4.1–2.7.4.5 | Flow 3 Slide 10 | 40% | S18, S19, S20 (table, prev/next, annotation mode) |
| **Jump Navigation** | Not shown | None | Flow 1, Flow 5 | **0%** | S21 (no requirement at all) |
| **List Navigation** | Not shown | None | Flow 1 | **0%** | S22 (no requirement at all) |
| **Sort/Filter in spatial** | Not shown | Partial (REQ-2.5.3) | Flow 5 Step 4 | 20% | S23 (controls local to spatial views) |
| **Edge Exclusion** | Not shown | Partial (Flow 3) | Flow 5 Step 4 | 10% | S24 (not in spatial context) |

**Overall Spatial Navigation coverage: ~35%** — The wafer map and basic drill-down are mocked up, but the Frame View is completely absent, and efficiency features (jump, lists, sort/filter, edge exclusion) confirmed by the Annotation.pptx have no UI or requirements in the AI_VL spec.

---

## Real Scan Result Data Analysis

**Source:** `scan/Scane Resault after/MTK-AHJ11236_setup1_20260406_201352/`

### Scan Result Folder Structure

The SR (Scan Result) output folder that feeds into Flow 1 contains:

| File / Folder | Description |
|---|---|
| `DB.csv` | Defect database — one row per detected defect with coordinates, classification, and image path |
| `Classes.json` | Full class taxonomy — maps numeric OClass IDs to human-readable defect names (100+ classes) |
| `MetaData.json` | Scan metadata — customer, job, setup, recipes, tool list, export timestamp |
| `images/` | Defect images organized in subfolders by lot (`images/lot_01/`, `images/lot_02/`, …) |
| `*.log` | Export log file |

### MetaData.json — Scan Identity

| Field | Value |
|---|---|
| Customer | **KYEC** |
| Job Name | **MTK-AHJ11236** |
| Setup Name | **setup1** |
| Recipes | `x7.5 Bump PMI` (Recipe 1), `x3.5 Surface` (Recipe 2) |
| Tool | `EAGLET_106739` |
| Export Timestamp | 2026-04-06 20:13:53 |

### DB.csv Schema (18 Columns)

| # | Column | Type | Description | Example |
|---|--------|------|-------------|---------|
| 1 | `ImageName` | string | Relative path to defect image | `images/lot_01/259793.119486.c.-1615541774.1.jpeg` |
| 2 | `Tool` | string | Inspection tool ID | `EAGLET_106739` |
| 3 | `Job Name` | string | Job identifier | `MTK-AHJ11236` |
| 4 | `Setup Name` | string | Setup name | `setup1` |
| 5 | `Recipe` | int | Recipe number (maps to Recipe Name) | `1` or `2` |
| 6 | `Recipe Name` | string | Human-readable recipe name | `x7.5 Bump PMI`, `x3.5 Surface` |
| 7 | `Wafer` | string | Wafer number within the lot | `01`, `02` |
| 8 | `Lot` | string | Lot identifier | `lot` |
| 9 | `Col` | int | Die column position on wafer | `0`–`21` |
| 10 | `Row` | int | Die row position on wafer | `0`–`25` |
| 11 | `Mode` | string | Image capture mode | `Color` |
| 12 | `OClass` | int | Original AOI classification (key into Classes.json) | `1` (Pass), `30`, `34` |
| 13 | `Index` | int | Unique defect index | `0`, `134217728`, … |
| 14 | `Wafer X` | float | X coordinate on wafer (microns) | `259794.29` |
| 15 | `Wafer Y` | float | Y coordinate on wafer (microns) | `119487.37` |
| 16 | `XInFrame` | float | X offset within frame | `0` |
| 17 | `YInFrame` | float | Y offset within frame | `0` |
| 18 | `Zone` | int | Inspection zone ID | `7`, `9`, `63` |

### Dataset Statistics

| Metric | Value |
|---|---|
| **Total defect records** | 180 |
| **Wafers scanned** | 2 (lot_01, lot_02 — 90 defects each, identical defect set) |
| **Die grid extent** | Col 0–21, Row 0–25 |
| **Wafer coordinate range** | X: 26,165 – 303,025 µm, Y: 22,260 – 305,021 µm |
| **Image format** | JPEG (not TIFF — differs from presentation spec) |

### Defect Distribution by Recipe

| Recipe # | Recipe Name | Defect Count | % of Total |
|---|---|---|---|
| 2 | x3.5 Surface | 174 | 96.7% |
| 1 | x7.5 Bump PMI | 6 | 3.3% |

### Defect Distribution by OClass (AOI Classification)

| OClass ID | Class Name (from Classes.json) | Count | % of Total |
|---|---|---|---|
| 1 | Pass | 176 | 97.8% |
| 30 | PI Contamination - Passivation defects - waivable | 2 | 1.1% |
| 34 | Foreign Particle after CP - Embedded foreign material | 2 | 1.1% |

### Defect Distribution by Zone

| Zone | Count | % of Total |
|---|---|---|
| 63 | 174 | 96.7% |
| 9 | 4 | 2.2% |
| 7 | 2 | 1.1% |

### Top Die Positions by Defect Count (Col, Row)

| Col, Row | Defect Count |
|---|---|
| 11, 25 | 10 |
| 10, 25 | 10 |
| 1, 7 | 10 |
| 0, 12 | 10 |
| 0, 11 | 10 |
| 0, 10 | 10 |
| 2, 5 | 6 |
| 0, 13 | 6 |

Edge dice (Col 0, Row 25) have the highest defect concentrations — consistent with typical wafer edge yield loss patterns.

### Classes.json — Full Defect Taxonomy (100+ Classes)

The taxonomy defines classes from semiconductor inspection covering:
- **Bump defects:** Pass, Bump Good, Missing Bump (types 1–5), Bump damage, Bump scratch, Bump discoloration, Irregular Bump, Bump shift, Bump others
- **Surface defects:** Surface, Passivation Scratch/Peeling/Crack, PI Contamination/Damage/Bubble/Shrinkage, Chip dirty
- **Particle defects:** Foreign Particle after CP, PI Particle, Al Particle, Sensor Particle
- **Probe marks:** Probe mark too big, Probe mark shift, Missing Probe Mark
- **Pad defects:** Pad Discolor/Contamination/Abnormal/Bubble/Black spots, F Pad
- **Metal/material:** Metal residue, Metal corrosion, UBM Residue, Solder Residue, Flux Residue
- **Process defects:** BCB Distortion, BCB-PI under develop, DFR Residue, Burn out, Arcing
- **Special classes:** Mark (ID 2147483646), Null (ID 2147483645), EBR (ID 2147483644)
- **Size-based bins:** 10um, 20um, 50um

### How This Maps to the Presentation Flows

**Flow 1 (Load SR Data):**
- The SR folder path the user provides is a folder like `MTK-AHJ11236_setup1_20260406_201352/`
- VL validates job/setup/recipe from `MetaData.json` (not just the folder structure)
- `DB.csv` provides the per-image AOI classification labels (OClass) that become the initial "image badges"
- `Classes.json` provides the full class taxonomy that populates the defect class panel
- Images are JPEG format (the presentations reference TIFF — this real data shows JPEG is also used)
- Multiple lots (lot_01, lot_02) from the same production run are combined into one dataset

**Flow 2 (Explore & QA):**
- The die grid (Col 0–21, Row 0–25) defines the spatial navigation structure: Wafer → Die(Col,Row) → Frame → Tile
- Wafer X/Y coordinates enable precise defect positioning on the wafer map
- Quality assessment should flag the heavy edge-die concentration (Col 0 and Row 25 hotspots)
- 97.8% of defects classified as "Pass" by AOI — a model should learn to distinguish real defects (OClass 30, 34) from false positives

**Flow 3 (Annotate) / Flow 4 (Auto-Annotation):**
- The 100+ class taxonomy from `Classes.json` is the annotation class panel
- OClass values from DB.csv serve as pre-labels (source=AOI) that annotators can accept, edit, or reclassify
- Current data shows only 3 OClass values used out of 100+ available — most classes will be assigned during manual annotation

**Flow 5 (Spatial Navigation):**
- Die positions from DB.csv `Col`/`Row` columns map directly to the wafer/die/frame views
- Zone column groups defects by inspection region (Zone 63 = Surface recipe area, Zone 7/9 = Bump PMI areas)
- `XInFrame`/`YInFrame` are both 0 in this export — frame-level positioning may require additional processing

**Flow 7 (Post-Model Rules):**
- BIN-based rules can leverage the full `Classes.json` taxonomy
- Rules can map OClass groupings (e.g., all "Missing Bump" types 1–5 → single "Missing Bump" BIN)

**Flow 8 (Offline Inference) / Flow 9 (Model Comparison):**
- New scan datasets follow the same folder structure (DB.csv + Classes.json + MetaData.json + images/)
- The `Index` column provides unique defect IDs for spatial matching between model predictions
- Recipe separation (Bump PMI vs Surface) means models may need to be trained per-recipe or the recipe must be a feature
