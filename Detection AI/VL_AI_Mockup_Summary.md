# VL-AI Mockup v1 - Presentation Summary

## Overview

The **VL-AI** presentation (29 slides) defines the end-to-end user journey and UI mockups for an **AI-powered defect detection platform** built on top of the VL (Visual Inspection / Wafer-Level) system. The platform enables semiconductor / electronics inspection engineers to create datasets from scan results, annotate defects, train object-detection models, deploy them for inference, and continuously monitor accuracy over time.

The presentation is divided into three parts:
1. **Flow Diagrams** (Slides 1-14) - Eight detailed user flows describing every step of the lifecycle.
2. **User Stories** (Slide 6-7 notes) - Step-by-step narratives for each flow.
3. **UI Mockups** (Slides 15-29) - Twelve pixel-level screen designs showing the dark-themed UI.

---

## Full Lifecycle Pipeline

The system follows a six-phase pipeline with iterative feedback loops:

```
Dataset Creation --> Annotation & Labeling --> Propagation Loop --> Training & Evaluation --> Deployment & Rules --> Inference & Reporting
```

### Phase 1: Dataset Creation
### Phase 2: Annotation & Labeling
### Phase 3: Propagation (Active Learning) Loop
### Phase 4: Training & Evaluation
### Phase 5: Post-Model Rules & Deployment
### Phase 6: Offline Inference, Dynamic Reports & Comparison

---

## Flow 1 - Dataset Creation (Slide 7)

**Goal:** From the home screen to a ready-to-annotate dataset workspace.

| Step | Action | Details |
|------|--------|---------|
| 1 | Open All Datasets | Home screen shows a card grid. Each card has a **type badge** (ADC = blue, AI Detection = purple) and a **status badge** (READY / DRAFT / ERROR). Filter by Type, Job, Status, or search by name. |
| 2 | Click "+ New Dataset" | Opens a 3-step wizard with a left-side step panel. |
| 3 | Select Dataset Type | Two options: **ADC Classification** (classify pre-detected defect tiles, one defect per image, JPEG color input) or **AI Detection** (detect & classify defects in full scan images, multiple defects per image, TIFF B&W input, bounding boxes + class labels). Type cannot be changed after creation. |
| 4 | Select Scan Results | Auto-filtered to show only TIFF-compatible SRs. Incompatible SRs are greyed out with a tooltip (e.g., "No TIFF"). Multi-select with checkboxes. Footer shows: "N scan results selected (X tiles total)". |
| 5 | Configure Dataset | Enter dataset name (auto-suggested). Optional toggle: "Use detection annotation" for auto-proposed initial bounding boxes. Click "Create Dataset" - a tile-break job starts in background, then Annotation Workspace opens automatically. |

---

## Flow 2 - Annotation & Labeling (Slide 8)

**Goal:** Manual defect annotation inside the Annotation Workspace.

| Step | Action | Details |
|------|--------|---------|
| 1 | Navigate Tile Queue | Left panel shows Unlabeled / Labeled sub-tabs. Thumbnails with tile number + defect count. Jump input for Tile/Frame/Die #. Filter pills (Has BBox, Class, Split). Mini wafer map for spatial navigation. |
| 2 | View the Tile | Center canvas shows B&W TIFF image. Toggle to Support Image (neighbor die, cyan border) for comparison. Zoom/pan controls. |
| 3 | Draw Bounding Boxes | Click-and-drag on canvas. Multiple boxes per tile supported. Resize via corner handles. Delete via BBox list or "Delete all annotations". |
| 4 | Assign Defect Class | Right Inspector panel - dropdown per bbox. Each bbox can have its own class (e.g., Surface, Via, Solder, Big Surface, Good). Bbox outline color reflects class. |
| 5 | Set Split | Allocate tile to Train / Validation / Test in the Inspector. Or bulk-assign later via Dataset tab. |
| 6 | Save and Continue | Click "Save DB" to persist. Tile moves to Labeled queue. Repeat for more tiles. |
| 7 | Review in Dataset Tab | Cross-tile defect table with columns: Tile #, Class (color pill), Split (inline editable), BBox WxH, Area, Die (X,Y), Confidence, Actions. Bulk reassignment and Auto-allocate available. |

---

## Flow 3 - Propagation / Active Learning Loop (Slide 9)

**Goal:** Accelerate annotation using an iterative semi-supervised approach.

| Step | Action | Details |
|------|--------|---------|
| 1 | Annotate Seed Tiles | Manually annotate a representative sample (recommended: 10-30 tiles per class). |
| 2 | Click "Propagate" | A mini detection model trains on labeled seeds, then runs on all unlabeled tiles proposing annotations. Progress shown in Task Manager. |
| 3 | Stats Bar Appears | Shows: "Cycle N - Auto-labeled: X tiles, Edge Cases: Y, Manually labeled: Z". Updates after each cycle. |
| 4 | Review Edge Cases | Orange-badged Edge Cases tab shows uncertain tiles with AI-proposed class + confidence %. Dashed orange bboxes distinguish AI proposals from confirmed annotations. Review bar: **Agree** / **Reclassify** (dropdown) / **Not a defect**. |
| 5 | Manual Refinement | User can correct any tile at any time. Corrections persist and feed into next cycle. |
| 6 | Propagate Again | Model retrains on updated labels (seeds + confirmed + corrections). Cycle counter increments. Repeat until satisfied. |
| 7 | Proceed to Train Model | When edge cases are minimal, click "Train Model" (green button) to trigger full production training. |

---

## Flow 4 - Group Splits & Train Model (Slide 10)

**Goal:** Finalize train/val/test allocation and launch production training.

| Step | Action | Details |
|------|--------|---------|
| 1 | Open Group Splits Modal | From Dataset tab, click "Auto-allocate". |
| 2 | Configure Split Method | **Method:** Global percentage (recommended) or Manual per-tile. **Strategy:** Stratified by class (recommended) or Random. |
| 3 | Set Percentages | Three sliders (Train/Val/Test) totaling 100%. Default: 70/15/15. Live preview table shows per-class sample counts. |
| 4 | Review Warnings | Red rows flag classes below minimum validation samples (e.g., "Via class has fewer than 10 validation samples"). |
| 5 | Click Train Model | Opens "Start Training Job" modal. |
| 6 | Configure Training Job | **Backbone/Architecture:** e.g., RF-DETR Nano. **Dataset version:** auto-stamped (read-only). **Model name:** user-entered. **Advanced:** Epochs, Learning Rate, Batch size. Job summary shows tile counts and class count. Optional: "Validate only" mode. |
| 7 | Start Training | Job appears in Task Manager. When complete, model appears in Models Catalog with status DONE and F1 score. |

---

## Flow 5 - Evaluate & Iterate (Slide 11)

**Goal:** Review model accuracy, find misclassifications, and iteratively improve.

| Step | Action | Details |
|------|--------|---------|
| 1 | Open Evaluate & Report | From Models Catalog, click "View" on a DONE job. |
| 2 | Confusion Matrix | 5x5 heatmap (Actual vs Predicted). Green diagonal = correct, red off-diagonal = errors. Raw counts shown. |
| 3 | Confidence Threshold | Slider (default 0.35). Updates confusion matrix and metrics live. |
| 4 | Per-Class Metrics | Table: Precision, Recall, F1-score, sample count per class. Low-F1 classes highlighted. Horizontal accuracy bar chart. Overall F1 badge (e.g., F1: 91.2%). |
| 5 | Misclassifications | Table of False Negatives / False Positives with tile #, class, score. "Go annotate" action jumps to tile in Annotation Workspace. |
| 6 | Iterate | Fix annotations -> Propagate -> Review edge cases -> Retrain -> Compare F1 scores. Repeat until accuracy targets are met. |

---

## Flow 6 - Post-Model Rules & Models Catalog (Slide 12)

**Goal:** Configure post-inference rules to refine raw model output.

| Step | Action | Details |
|------|--------|---------|
| 1 | Open Models Catalog | Two tabs: Training Jobs / Validation Jobs. Table shows: name, model, dataset, status (DONE/RUNNING/ERROR), F1, date. |
| 2 | Select a Model | Highlight a DONE row. Action buttons: View / Deploy. |
| 3 | Post-Model Rules Panel | Opens automatically for selected model. Shows active rules applied after inference. |
| 4 | Configure Rules | Rule types: **Score threshold** (min confidence per class), **Merge overlapping** (IoU threshold), **Min bbox area** (noise filter), **Max class count** (per image limit). Each rule has class selector, value, and on/off toggle. |
| 5 | Save & Re-deploy | Model re-registered with updated rules. All future inference runs apply rules automatically. |

---

## Flow 7 - Offline Inference (Slide 13)

**Goal:** Run the deployed model on new scan results and review predictions.

| Step | Action | Details |
|------|--------|---------|
| 1 | Configure Inference Job | Select Model, select Scan Results (new SRs), set Confidence threshold. Click "Run Inference". |
| 2 | Monitor Progress | Progress bar + Task Manager. Live stats: Detections, Agree, Disagree, Pending. |
| 3 | Review Predictions | Canvas shows tile with model bboxes (solid = confirmed, dashed = AI proposal). Support image alongside. Right panel: tile info + bbox list. |
| 4 | Agree or Disagree | **Agree all** (accepts predictions), **Disagree** (marks as incorrect), **Reclassify** (correct a specific detection). Tile strip at bottom: green border = agreed, red = disagreed. |
| 5 | Disagreements Logged | Every disagree is stored with: SR name, tile #, AI-predicted class, user correction, confidence score. Feeds into Dynamic Report. |

---

## Flow 8 - Dynamic Report & Comparison Platform (Slide 14)

**Goal:** Monitor model accuracy over time and compare models for deployment decisions.

### Dynamic Report
| Step | Action | Details |
|------|--------|---------|
| 1 | Open Inference Dynamic Report | Left panel shows inference runs (SR name, date, tile count, accuracy %, disagree count). |
| 2 | Select Inference Runs | Multi-select + "Update Report". |
| 3 | Accuracy Trend | Line chart: Agree% per SR over time. Drift warning badge if accuracy drops beyond threshold. |
| 4 | Per-Class Accuracy | Bar chart: agree % per class. Low accuracy = red bars. |
| 5 | Disagree Log | Table: SR, tile #, AI-predicted class, user correction, confidence score. |
| 6 | Act on Drift | Either adjust Post-Model Rules or retrain on new data. |

### Comparison Platform
| Step | Action | Details |
|------|--------|---------|
| 7 | Open Comparison Platform | Three modes: **Model vs Model**, **Model vs Ground Truth**, **Algorithm vs Model**. |
| 8 | Compare | Select Baseline + Comparison items + Scan Result. Results: side-by-side confusion matrices, Delta panel (green = improved, red = regressed), tile-level diff examples. |
| 9 | Deploy Winner | Click "Deploy -> Catalog" to set winning model as active. Losing model archived. Deployment logged with comparison justification. |

---

## UI Mockups (Screens 1-12)

| Screen | Name | Key Elements |
|--------|------|-------------|
| 1 | Dataset Inventory | Card grid with type badges (ADC blue, Detection purple), status badges (READY/DRAFT/ERROR), filter chips, "+ New Dataset" button. |
| 2a | Create Dataset: Select Type | 3-step wizard. Two cards: ADC Classification vs AI Detection with descriptions. |
| 2b | Create Dataset: Select Scan Results | Filterable table of SRs with TIFF compatibility check. Multi-select with running tile count. Incompatible SRs show "No TIFF" warning. |
| 3 | Annotate Workspace (Annotation Mode) | Full-width filter toolbar. Die selection on wafer map filters tile list. TIFF B&W tile canvas. Propagation cycle stats bar. Tile queue with thumbnails. |
| 3b | Tile Editor Modal | Full-screen modal with enlarged tile (B&W), selected bbox (orange handles), support image (cyan border). Action bar: Add BBox, Delete, Assign Class, Resize, Undo/Redo. Defect table below (x,y,w,h, area, split, confidence). |
| 4 | Dataset Tab (Cross-Tile Review) | Sortable defect table. Inline split dropdown per row. "Go to tile" button. Bulk reassignment bar. Auto-allocate triggers Group Splits modal. |
| 5 | Annotate Workspace (Propagation Review) | Edge Cases tab (orange badge). AI proposals with dashed orange bboxes. Review bar: Agree / Reclassify / Not a defect. Cycle stats tracking. |
| 6 | Group Splits / Allocation Modal | Global percentage sliders (Train 70% / Val 15% / Test 15%). Stratified by class option. Split preview table per class with warnings for low sample counts. |
| 7 | Train Model Modal | Select backbone (RF-DETR Nano), dataset version (auto-stamped), model name. Advanced config (Epochs, LR, Batch). Validate-only option. Job summary. |
| 8 | Evaluate & Report | 5x5 confusion matrix heatmap. Live confidence threshold slider. Per-class Precision/Recall/F1 table. Class accuracy bar chart. Misclassification table with "Go annotate" links. F1 badge (91.2%). |
| 9 | Models Catalog + Post-Model Rules | Training jobs table with status/F1/date. Right panel: Post-Model Rules editor (score threshold, merge overlapping, min bbox area, max class count). Toggle on/off per rule. "Save Rules -> Re-deploy". |
| 10 | Offline Inference | Left: model + SR selection + confidence slider. Right: tile canvas with prediction bboxes. Agree-all / Disagree / Reclassify controls. Tile strip with green/red borders. |
| 11 | Inference Dynamic Report | Inference run selector. Accuracy-over-time line chart. Per-class accuracy bars. Disagreements log table. Drift detection badge (-1.4% vs baseline). Accuracy calculation: agree% = 1 - (disagrees/total). |
| 12 | Comparison Platform | Three modes (Model vs Model / Model vs GT / Algorithm vs Model). Side-by-side confusion matrices. Delta panel with metric changes (green/red arrows). Tile-level diff thumbnails. "Deploy v2 -> Catalog" button. |

---

## Defect Classes Used in Mockups

The example dataset (Samsung_HCB_v12) uses 5 defect classes:
- **Good** (green) - No defect
- **Surface** (orange) - Surface-level defects
- **Via** (blue) - Via-related defects
- **Solder** (purple) - Solder defects
- **Big Surface** (red) - Large surface defects

---

## Key Design Decisions & Features

1. **Two Dataset Types:** ADC Classification (single-class per tile, JPEG) vs AI Detection (multi-class with bounding boxes, TIFF B&W). Type is locked at creation time.

2. **Active Learning Loop:** The propagation mechanism uses a mini-model trained on seed annotations to propose labels for unlabeled tiles, dramatically reducing manual effort. Edge cases are surfaced for human review.

3. **Iterative Refinement:** Every stage feeds back - misclassifications from evaluation link directly to the annotation workspace for correction, then re-propagation and retraining.

4. **Post-Model Rules:** A rule engine applied after inference allows fine-tuning without retraining (confidence thresholds, IoU merge, bbox area filters, class count limits).

5. **Drift Detection:** The Dynamic Report tracks model accuracy across inference runs over time, alerting when accuracy drops below baseline.

6. **Model Comparison:** Three comparison modes (Model vs Model, Model vs Ground Truth, Algorithm vs Model) with delta metrics and tile-level diff examples support data-driven deployment decisions.

7. **Dark Theme UI:** All mockups use a dark theme with color-coded elements for defect classes, split assignments, and status indicators.

8. **Architecture:** RF-DETR Nano is shown as the default backbone, suggesting a real-time object detection approach optimized for edge/nano deployment scenarios.

---

*Summary generated from VL_AI_Mockup - ver1.pptx (29 slides, 19 images)*
