# Phase B – Solution Design

> **Feature:** Defect Crop Viewer — post-export review stage with configuration form shown after dataset creation

---

## 1. Problem Restatement

Given a scan export folder containing:
- `DB.csv` — 18-column table, one row per defect, with `Wafer X`/`Wafer Y` coordinates (microns)
- `images/` — one JPEG per defect row (close-up of the defect location)

**Goal:** Present a post-export review UI that:
1. Opens automatically after dataset creation
2. Presents a configuration form (clustering parameters, filtering options) before rendering
3. Groups spatially nearby defects into clusters based on form settings
4. Renders each cluster as a tile showing **multiple defects and bounding boxes together**

**Key insight discovered in analysis:** `XInFrame=YInFrame=0` for all rows in the real data. Each image is a close-up of a single defect. Therefore, "multiple bounding boxes per crop" means **showing multiple nearby defect images together in one cluster panel**, not multiple boxes within a single image.

---

## 2. Option 1 — Server-Side Cropping (Python + PIL)

### Architecture

```
Client                              Server (FastAPI)
  │                                      │
  │── POST /crop-defects ───────────────▶│
  │   {path, scan_id, eps, pad}          │
  │                                      │ 1. parse DB.csv
  │                                      │ 2. filter OClass
  │                                      │ 3. DBSCAN per recipe
  │                                      │ 4. compute crop rects
  │                                      │ 5. PIL.Image.crop() each region
  │                                      │ 6. base64-encode patches
  │◀── [{crop_b64, bboxes, metadata}] ───│
  │                                      │
  │  React renders <img src="data:..."/> │
  │  SVG overlay for bboxes              │
```

### Data Flow

```
DB.csv
  │ parse + filter
  ▼
DefectRecord[] (wafer_x, wafer_y, image_name, oclass)
  │ group by recipe, then DBSCAN
  ▼
Cluster[] (list of DefectRecords per spatial group)
  │ for each cluster: PIL.Image.open, crop, base64-encode
  ▼
CropResponse { crops: [{b64_image, bboxes[], metadata}] }
  │ REST response
  ▼
React: render <img src={`data:image/jpeg;base64,${b64}`} />
       SVG <rect> per bbox
```

### Bounding Box Calculation

Since images are individual defect close-ups (XInFrame=0):
```
For single-defect images:
  bbox_x = 0.3  (centered at 30% from left)
  bbox_y = 0.3  (centered at 30% from top)
  bbox_w = 0.4  (40% of image width)
  bbox_h = 0.4  (40% of image height)

For multi-defect images (XInFrame/YInFrame populated):
  absoluteX = relativeX * imageWidth    (where relativeX = XInFrame / imageWidth)
  absoluteY = relativeY * imageHeight
  bbox_x = (XInFrame - crop_x) / crop_w    [normalized 0-1]
  bbox_y = (YInFrame - crop_y) / crop_h
```

### Crop Generation Algorithm

```
Input: cluster of N defect images
       each image at (wafer_x_i, wafer_y_i) with image size (w_i, h_i)

For spatial clusters (Wafer X/Y grouping):
  - Display images side-by-side in a grid panel
  - Each image maintains its own bbox (centered for this dataset)
  - Composite crop = grid of individual image thumbnails

For intra-image clustering (future: when XInFrame/YInFrame populated):
  - crop_x = min(XInFrame_i) - pad
  - crop_y = min(YInFrame_i) - pad
  - crop_w = max(XInFrame_i) - min(XInFrame_i) + 2*pad + defect_size
  - crop_h = max(YInFrame_i) - min(YInFrame_i) + 2*pad + defect_size
  - All clamped to [0, imageW] x [0, imageH]
  - Minimum: 128x128, Maximum: 512x512
```

### Pros & Cons

| Aspect | Evaluation |
|--------|-----------|
| **Image quality** | Pixel-perfect — server reads the exact file |
| **Backend complexity** | High — PIL operations, base64 encoding, memory management |
| **Network payload** | Large — base64 JPEG for every tile (~300KB * N tiles) |
| **Frontend complexity** | Low — just `<img src="data:...">` |
| **Caching** | Hard — base64 payload not cached by browser |
| **Scalability** | Poor at 5000+ defects — server memory and latency spike |
| **Suitability** | Best for offline/batch processing; overkill for interactive viewer |

---

## 3. Option 2 — Client-Side Cropping (React Canvas API)

### Architecture

```
Client (React)                      Server (FastAPI)
  │                                      │
  │── GET /defect-clusters ─────────────▶│
  │   ?path=…&eps=300&pad=64             │ 1. parse DB.csv
  │                                      │ 2. filter OClass
  │                                      │ 3. DBSCAN by Wafer X/Y
  │                                      │ 4. compute crop rects
  │                                      │ 5. return metadata ONLY (no images)
  │◀── CropResponse (JSON, no images) ───│
  │                                      │
  │  For each cluster tile:              │
  │  const img = new Image()             │
  │  img.src = "/api/v1/scan-results/    │
  │             image?scan_path=…&       │── GET /scan-results/image ──▶│
  │             rel=images/lot_01/…"     │◀── StreamingResponse ─────────│
  │                                      │
  │  canvas.drawImage(img,               │
  │    srcX, srcY, srcW, srcH,           │
  │    0, 0, tileW, tileH)               │
  │                                      │
  │  SVG overlay for bboxes              │
```

### Data Flow

```
React mounts DefectCropViewer
  │ useQuery: GET /defect-clusters
  ▼
CropResponse{crops: [{image_name, image_url, crop_x,y,w,h, defects[]}]}
  │ React renders CropTile per crop
  ▼
CropTile mounts
  │ useEffect: new Image() → img.onload → canvas.drawImage(srcRect → dstRect)
  ▼
canvas shows cropped region
  │ SVG layer on top → <rect> per defect bbox
  ▼
User sees: cropped tile with colored bounding boxes
```

### Bounding Box Calculation

```
Backend returns (per defect in cluster):
  x_norm = (XInFrame - crop_x) / crop_w   [0–1]
  y_norm = (YInFrame - crop_y) / crop_h   [0–1]
  w_norm = defect_size / crop_w            [0–1]
  h_norm = defect_size / crop_h            [0–1]

Frontend SVG rendering:
  px = x_norm * tileW   (tile display width in pixels)
  py = y_norm * tileH
  pw = w_norm * tileW
  ph = h_norm * tileH

  absoluteX = relativeX * imageWidth   (for verification/debug)
  absoluteY = relativeY * imageHeight
```

### Canvas Source-Rect Clipping

```javascript
// Canvas drawImage with source-rect clipping:
ctx.drawImage(
  img,
  crop_x, crop_y, crop_w, crop_h,   // source rect (pixels in original image)
  0, 0, tileW, tileH                 // destination rect (canvas display size)
);
// Scales the crop region to fill the entire canvas tile
```

### Pros & Cons

| Aspect | Evaluation |
|--------|-----------|
| **Image quality** | Good — browser handles JPEG decode natively |
| **Backend complexity** | Low — only serves metadata JSON + raw image files |
| **Network payload** | Efficient — images lazy-loaded on demand via browser cache |
| **Frontend complexity** | Medium — canvas lifecycle, async onload, cleanup |
| **Caching** | Excellent — browser caches individual image files |
| **Scalability** | Good — images lazy-loaded, canvas renders only visible tiles |
| **Suitability** | Best for interactive viewer; aligns with existing React patterns |

---

## 4. Recommended Approach — Hybrid (Option 2 with Enhancements)

### Why Hybrid?
- **Server** handles all data processing (CSV parsing, clustering, math) — no heavy computation in browser
- **Client** handles all rendering (canvas + SVG) — leverages browser image cache, avoids base64 bloat
- **Fallback:** if canvas is unavailable, degrade to `<img>` with CSS `object-fit: none; object-position: -Xpx -Ypx`

### Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────────┐
│                     RECOMMENDED: HYBRID ARCHITECTURE                     │
└──────────────────────────────────────────────────────────────────────────┘

React Client                        FastAPI Backend
┌─────────────────────┐             ┌──────────────────────────────────┐
│  ScanResults/       │             │  api_defect_crops.py             │
│  index.tsx          │             │  ─────────────────────────────── │
│                     │             │                                  │
│  [Export to VL]     │             │  POST /export-dataset            │
│       button        │             │  (UNCHANGED — existing flow)     │
│         │           │             │                                  │
│  ExportDatasetModal │             │                                  │
│  (UNCHANGED)        │             │                                  │
│         │           │             │                                  │
│  Dataset created ✓  │             │                                  │
│         │           │             │                                  │
│         ▼           │             │                                  │
│  CropConfigForm     │             │                                  │
│  ─────────────────  │             │                                  │
│  eps slider (μm)    │             │                                  │
│  pad slider (px)    │             │                                  │
│  OClass filter      │             │                                  │
│  Recipe filter      │             │                                  │
│  [Apply & View] btn │             │                                  │
│         │           │  GET        │  GET /defect-clusters            │
│         ▼           ──────────────▶  1. parse_db_csv()               │
│  DefectCropViewer   │             │  2. filter_defects()             │
│  ─────────────────  │  JSON only  │  3. get_image_dims() [PIL cache] │
│  Wafer Map          │◀────────────│  4. group_by_recipe()            │
│  Cluster Grid       │             │  5. dbscan_cluster() [Wafer X/Y] │
│   CropTile          │             │  6. auto_widen_eps() if needed   │
│    ├── canvas       │             │  7. compute_crop_rects()         │
│    │   drawImage()  │  GET image  │  8. normalize_bboxes()           │
│    │   (src clip)   │─────────────▶  → CropResponse{}                │
│    └── SVG overlay  │             │                                  │
│        <rect> bbox  │◀────────────│  GET /scan-results/image        │
│                     │             │  → FileResponse (JPEG)           │
│  [← Back to Scans]  │             │    + CORS header                 │
│       button        │             │    + Cache-Control: 1hr          │
└─────────────────────┘             └──────────────────────────────────┘
```

---

## 5. Clustering Algorithm Design

### Two-Level Strategy

```
Level 1: Intra-Image Clustering  (when XInFrame/YInFrame != 0)
─────────────────────────────────────────────────────────────
Group defects sharing the same ImageName.
For each image with N>1 defects:
  - DBSCAN on (XInFrame, YInFrame) in pixels
  - eps_px = 50px (tunable)
  - Compute crop rect around cluster + padding

Level 2: Spatial Clustering  (primary: when XInFrame=YInFrame=0)
──────────────────────────────────────────────────────────────────
Group images whose wafer positions are physically close.
For all defects from the same recipe:
  - DBSCAN on (Wafer X, Wafer Y) in microns
  - eps_um = 300μm (default, auto-tunable)
  - Display cluster as grid of N images, each with its bbox
```

### Spatial Clustering Diagram

```
Wafer coordinate space (μm):

● = defect (one per image)

  105000μm         205000μm         305000μm
     │                │                │
     ▼                ▼                ▼
    ●  ●             ●●●              ●
     ●               ●●
    ●                  ●●              ●●●

     Cluster A        Cluster B       Cluster C
     (3 defects)      (5 defects)     (4 defects)
     eps=300μm        all within      300μm radius
                      150μm of each
```

### DBSCAN Parameters

```python
# Primary parameters
eps_um    = 300.0   # micron radius — groups defects ~1-3 die pitches apart
min_samples = 1     # every defect gets assigned (no noise points discarded)

# Auto-widening if cluster count > threshold
MAX_CLUSTERS = 60
RETRY_FACTOR = 2.0   # double eps on retry
MAX_RETRIES  = 3     # give up after 3x expansion

# Intra-image (future use)
eps_px = 50          # pixel radius within one frame image
```

### Crop Region Calculation

```
For spatial clusters (display as grid):
  - No single "crop rect" needed
  - Each image in cluster shown at thumbnail size (e.g., 128×128)
  - Cluster panel = responsive grid, 2–4 columns

For intra-image clusters (when XInFrame/YInFrame populated):
  xs = [defect.XInFrame for defect in cluster]
  ys = [defect.YInFrame for defect in cluster]

  crop_x = max(0, min(xs) - padding)
  crop_y = max(0, min(ys) - padding)
  crop_w = clamp(max(xs) - min(xs) + 2*padding + defect_size,
                 min_crop=128, max_crop=512)
  crop_h = clamp(max(ys) - min(ys) + 2*padding + defect_size,
                 min_crop=128, max_crop=512)

  # Never exceed image boundaries
  crop_w = min(crop_w, image_w - crop_x)
  crop_h = min(crop_h, image_h - crop_y)
```

### BBox Normalization Within a Crop

```
For each defect d in cluster (intra-image mode):
  half = defect_size / 2

  x_norm = clamp((d.XInFrame - crop_x - half) / crop_w, 0.0, 1.0 - w_norm)
  y_norm = clamp((d.YInFrame - crop_y - half) / crop_h, 0.0, 1.0 - h_norm)
  w_norm = clamp(defect_size / crop_w, 0.01, 1.0)
  h_norm = clamp(defect_size / crop_h, 0.01, 1.0)

For centered fallback (XInFrame=YInFrame=0):
  x_norm = 0.30
  y_norm = 0.30
  w_norm = 0.40
  h_norm = 0.40
```

### Edge Cases

| Case | Handling |
|------|---------|
| **0 defects** (all Pass) | Return `total_defects=0`, frontend shows `<Empty>` component |
| **1 defect** (no clustering possible) | Single-item cluster — shown with centered bbox |
| **All singletons** (eps too small) | Auto-widen eps x2, retry up to 3 times, notify user |
| **Dense cluster** (100+ defects) | Cap display at 16 images per cluster panel, show "+N more" badge |
| **Sparse defects** | Large eps recommended — user can adjust slider |
| **Out-of-bound XInFrame** | Clamp crop rect to `[0, image_w] x [0, image_h]` |
| **Missing image file** | Log warning, use grey placeholder tile (don't crash) |
| **Malformed CSV row** | Skip row with warning log, continue |
| **Multiple recipes** | Cluster separately per recipe; recipe shown as label on tile |

---

## 6. Option Comparison Table

| Criterion | Option 1 (Server Crop) | Option 2 (Client Canvas) | **Recommended Hybrid** |
|-----------|----------------------|------------------------|----------------------|
| **Performance** | Slow at scale (PIL per request) | Fast (browser parallel loads) | **Fast** (lazy load) |
| **Network** | Heavy (base64 images in JSON) | Efficient (separate image requests) | **Efficient** |
| **Frontend complexity** | Low | Medium (canvas lifecycle) | **Medium** (manageable) |
| **Backend complexity** | High (PIL + encoding) | Low | **Low** (metadata only) |
| **Image caching** | None (base64 in JSON) | Excellent (browser HTTP cache) | **Excellent** |
| **Bounding box accuracy** | Server-computed, exact | Client-computed, exact | **Server-computed, exact** |
| **Scalability** | Poor (>500 tiles) | Good | **Good + pagination** |
| **Maintainability** | Poor (image encoding in API) | Good | **Good** |
| **UX responsiveness** | Laggy (one big request) | Smooth (streaming loads) | **Smooth** |
| **CORS complexity** | None | Need CORS on image endpoint | **One-time setup** |
| **Browser support** | Any | All modern (Canvas 2D) | **All modern** |

**Winner: Hybrid (server metadata + client rendering)**

---

## 7. UX/UI Design

### Screen Layout

**Step 1 — Configuration Form (shown immediately after dataset creation):**

```
┌──────────────────────────────────────────────────────────────────────┐
│  [←] Back to Scans    Configure Crop Review — MTK-AHJ11236 [? Help] │
│─────────────────────────────────────────────────────────────────────│
│  ✓ Dataset created successfully    180 defects exported              │
│─────────────────────────────────────────────────────────────────────│
│                                                                      │
│  Clustering Parameters:                                              │
│  ────────────────────                                                │
│  Cluster Radius:  [──●──────────────] 300μm                         │
│  Crop Padding:    [────●────────────] 64px                          │
│                                                                      │
│  Filters:                                                            │
│  ────────                                                            │
│  OClass:  [☑ All] ☑ Missing Bump  ☑ Foreign Particle  ☑ Scratch    │
│  Recipe:  [☑ All] ☑ Recipe_A  ☑ Recipe_B  ☑ Recipe_C               │
│                                                                      │
│  Display:                                                            │
│  ────────                                                            │
│  Max images per cluster:  [──●──────] 16                            │
│  Thumbnail size:          [────●────] 256px                         │
│                                                                      │
│                     [Apply & View Crops]                             │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

**Step 2 — Crop Viewer (shown after user submits the form):**

```
┌──────────────────────────────────────────────────────────────────────┐
│  [←] Back to Form     Review Defect Crops — MTK-AHJ11236   [? Help] │
│─────────────────────────────────────────────────────────────────────│
│  ✓ Dataset created    180 defects  │  24 clusters  │  avg 7.5/cluster│
│─────────────────────────────────────────────────────────────────────│
│  WAFER MAP                   │  CLUSTER GRID                         │
│  ┌───────────────────────┐   │  ┌─────────────┐  ┌─────────────┐   │
│  │ ● ●  ●                │   │  │[IMG][■][IMG]│  │[IMG][■]     │   │
│  │  ●●●●   ●             │   │  │[IMG][■]     │  │ Cluster #2  │   │
│  │     ●●  ●  ●          │   │  │ Cluster #1  │  │ 2 defects   │   │
│  │  ●       ●●           │   │  │ 4 defects   │  └─────────────┘   │
│  └───────────────────────┘   │  └─────────────┘                     │
│  (click cluster → highlight) │  ┌─────────────┐  ┌─────────────┐   │
│                              │  │ [IMG][■][■] │  │  ...        │   │
│                              │  │ Cluster #3  │  └─────────────┘   │
│                              │  │ 3 defects   │                     │
│                              │  └─────────────┘                     │
│─────────────────────────────────────────────────────────────────────│
│          [← Back to Form]          [← Back to Scan Results]         │
└──────────────────────────────────────────────────────────────────────┘
```

### Component Tree

```
DefectCropPage (new: fe/.../ScanResults/DefectCropPage/)
├── CropConfigForm (Step 1 — shown first after dataset creation)
│   ├── FormHeader
│   │   ├── Back to Scans button
│   │   ├── Title (scan name)
│   │   └── Success badge ("Dataset created — 180 defects")
│   ├── ClusteringParams (Ant Design Form section)
│   │   ├── eps Slider (range 50–2000μm, default 300)
│   │   └── pad Slider (range 16–256px, default 64)
│   ├── FilterParams (Ant Design Form section)
│   │   ├── OClass Checkbox Group (select/deselect defect classes)
│   │   └── Recipe Checkbox Group (select/deselect recipes)
│   ├── DisplayParams (Ant Design Form section)
│   │   ├── maxPerCluster Slider (4–32, default 16)
│   │   └── thumbnailSize Slider (128–512px, default 256)
│   └── [Apply & View Crops] button → transitions to Step 2
│
└── DefectCropViewer (Step 2 — shown after form submission)
    ├── CropViewerHeader
    │   ├── Back to Form button (returns to CropConfigForm with preserved values)
    │   ├── Title (scan name)
    │   └── Stats bar (defect count, cluster count, avg per cluster)
    ├── WaferMap
    │   └── <canvas> (all defect dots, colored by OClass, auto-fit viewport)
    └── ClusterGrid
        └── CropTile (per cluster) [reused/extended]
            ├── ClusterPanel (N images side by side)
            │   └── SingleImageTile (per defect in cluster)
            │       ├── <canvas> drawImage(srcRect → tile)
            │       └── BoundingBoxOverlay (SVG)
            │           └── <rect> + <text> per defect
            └── ClusterBadge (defect count, OClass breakdown)
```

### Visual Design Specifications

**CropTile:**
- Size: 256×256px (spatial cluster) or variable for intra-image
- Background: `#1a1a2e` (dark, matches industrial UI theme)
- Border: `1px solid var(--border-color)`, `border-radius: 8px`
- Hover: `border-color: var(--primary)`, `box-shadow: 0 0 8px rgba(primary, 0.4)`
- Badge: bottom-right corner, shows "N defects", color by max-severity OClass

**BoundingBoxOverlay (SVG):**
- Rect: 2px stroke, semi-transparent fill (30% opacity)
- Color per OClass category:
  - Pass (1): hidden
  - Missing Bump (23, 58, 78, 81, 85): `#ff6b35` (orange)
  - Foreign Particle (28, 34, 35): `#ff4444` (red)
  - Scratch/Damage (26, 27, 46): `#ffcc02` (yellow)
  - Other (65): `#9b59b6` (purple)
  - Default: `#3498db` (blue)
- Label: OClass short name, 11px, bold, colored background pill
- Label position: above bbox if space, below if near top edge

**WaferMap canvas:**
- Size: 300×300px (fixed sidebar)
- Background: `#0d1117`
- Defect dots: 4px radius circles, colored by OClass
- Clusters highlighted on hover/click with glow
- Auto-fit: `scale = min(300/range_x, 300/range_y) * 0.9` (10% margin)
- Hover tooltip: cluster ID + defect count

**CropConfigForm:**
- Eps slider: range 50–2000μm, step 50, default 300
- Pad slider: range 16–256px, step 8, default 64
- OClass checkbox group: all selected by default, maps to defect class categories
- Recipe checkbox group: all selected by default, populated from DB.csv distinct recipes
- Max images per cluster slider: range 4–32, step 4, default 16
- Thumbnail size slider: range 128–512px, step 64, default 256
- No debounced API calls — form values stored locally, API called only on "Apply & View Crops" submit
- Show unit labels (μm, px) on sliders

### Interaction Design

```
User Action                     System Response
──────────────────────────────────────────────────────────────────────
FORM STEP (CropConfigForm):
Adjust eps/pad sliders          → values stored in local form state (no API call yet)
Toggle OClass/Recipe checkboxes → values stored in local form state
Click [Apply & View Crops]      → GET /defect-clusters with form params → transition to viewer

VIEWER STEP (DefectCropViewer):
Hover CropTile                  → highlight corresponding cluster on WaferMap
Click WaferMap cluster          → scroll CropGrid to that cluster
Click single defect tile        → full-screen image preview (Ant Design Modal)
Click [← Back to Form]         → return to CropConfigForm (form values preserved)
Click [← Back to Scan Results] → close entire page → return to scan results table
```

### Trigger: When Does the Form & Viewer Open?

```
User Flow:
1. User selects scan result in ScanResults table
2. User clicks "Export to VL Dataset" button
3. ExportDatasetModal opens (UNCHANGED existing flow)
4. User configures export and clicks "Create Dataset"
5. Dataset is created successfully
6. On success callback → CropConfigForm opens automatically
7. User configures clustering params, filters, and display options
8. User clicks "Apply & View Crops"
9. GET /defect-clusters is called with form parameters
10. DefectCropViewer renders with clustered results
11. User can click "← Back to Form" to adjust settings and re-render
12. User clicks "← Back to Scan Results" to return
```

---

## 8. Design Decision: Crop Viewer Relationship to Dataset Export

> **Q: Does the crop viewer affect the dataset export?**

**Answer: No.** The crop viewer is a **post-export review tool**. The dataset is already created by the time the form and viewer open. The existing export flow (`ExportDatasetModal` → `POST /export-dataset`) remains completely unchanged. The form + viewer simply provides a configurable visual review of the defects that were included in the dataset.

> **Q: When does the form open?**

**Answer:** Immediately after the dataset is successfully created. The `ExportDatasetModal`'s success callback triggers `CropConfigForm` to open, passing the scan path and dataset metadata as props. The user configures clustering/filter/display parameters in the form, then clicks "Apply & View Crops" to trigger the API call and render the `DefectCropViewer`.

> **Q: Why show a form before the viewer instead of rendering immediately?**

**Answer:** Showing the configuration form first gives the user control over clustering parameters and filters **before** the potentially expensive `/defect-clusters` API call is made. This avoids wasted computation with default parameters the user doesn't want. The user can also navigate back from the viewer to the form to adjust settings and re-render without re-creating the dataset.

**Future v2 option (out of scope):** If the use case requires exporting only the cropped patches (as ML training tiles), a new `include_crops=true` parameter can be added to `POST /export-dataset`, which would instruct the backend to apply PIL crops before writing to the export folder. This doubles the implementation scope and is deferred.

---

## 9. Final Recommended Solution Summary

| Aspect | Decision |
|--------|----------|
| **Cropping location** | Client-side (canvas drawImage with source rect) |
| **Clustering location** | Server-side (Python DBSCAN on Wafer X/Y) |
| **Primary coordinates** | Wafer X/Y (microns) for spatial grouping |
| **Fallback bbox** | Centered 40% of image (when XInFrame=YInFrame=0) |
| **Eps unit** | Microns (μm), default 300, user-adjustable 50–2000 |
| **Multiple bboxes strategy** | Spatial clustering → cluster panel with N images side-by-side |
| **Image serving** | New `GET /scan-results/image` endpoint (path-validated, CORS-enabled) |
| **State management** | React Query (server data) + local useState (form values, step navigation) |
| **UI integration** | Existing export flow unchanged → dataset created → CropConfigForm opens → user submits → DefectCropViewer renders |
| **Backward compatibility** | Zero changes to existing export flow, API, or ExportDatasetModal |
