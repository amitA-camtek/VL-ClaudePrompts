# Phase B – Solution Design

> **Feature:** Defect Crop Viewer — intermediate stage between ScanResult selection and dataset export

---

## 1. Problem Restatement

Given a scan export folder containing:
- `DB.csv` — 18-column table, one row per defect, with `Wafer X`/`Wafer Y` coordinates (microns)
- `images/` — one JPEG per defect row (close-up of the defect location)

**Goal:** Present an intermediate UI stage that:
1. Groups spatially nearby defects into clusters
2. Renders each cluster as a tile showing **multiple defects and bounding boxes together**
3. Lets the user review and then confirm export to dataset

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
│                     │  GET        │  GET /defect-clusters            │
│  [Export to VL]  ──────────────▶  │  1. parse_db_csv()               │
│       button        │             │  2. filter_defects()             │
│                     │             │  3. get_image_dims() [PIL cache] │
│  DefectCropViewer   │  JSON only  │  4. group_by_recipe()            │
│  ─────────────────  │◀────────────│  5. dbscan_cluster() [Wafer X/Y] │
│  Wafer Map          │             │  6. auto_widen_eps() if needed   │
│  Cluster Grid       │             │  7. compute_crop_rects()         │
│   CropTile          │             │  8. normalize_bboxes()           │
│    ├── canvas       │             │  → CropResponse{}                │
│    │   drawImage()  │  GET image  │                                  │
│    │   (src clip)   │─────────────▶  GET /scan-results/image        │
│    └── SVG overlay  │             │  → FileResponse (JPEG)           │
│        <rect> bbox  │◀────────────│    + CORS header                 │
│                     │             │    + Cache-Control: 1hr          │
│  [Confirm & Export] │             └──────────────────────────────────┘
│       button        │
│         │           │
│  ExportDatasetModal │
│  (UNCHANGED)        │
└─────────────────────┘
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

```
┌──────────────────────────────────────────────────────────────────────┐
│  [←] Back    Preview Defect Crops — MTK-AHJ11236   [? Help]         │
│─────────────────────────────────────────────────────────────────────│
│  180 defects  │  24 clusters  │  avg 7.5 defects/cluster            │
│─────────────────────────────────────────────────────────────────────│
│  Clustering Controls:                                                │
│  Cluster Radius:  [──●──────────────] 300μm                         │
│  Crop Padding:    [────●────────────] 64px                          │
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
│          [← Back]           [Confirm & Create Dataset →]            │
└──────────────────────────────────────────────────────────────────────┘
```

### Component Tree

```
DefectCropViewer (new: fe/.../ScanResults/DefectCropViewer/)
├── CropViewerHeader
│   ├── Back button
│   ├── Title (scan name)
│   └── Stats bar (Statistic components)
├── ClusteringControls
│   ├── eps Slider (Ant Design Slider, debounced)
│   └── pad Slider
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

**ClusteringControls:**
- Eps slider: range 50–2000μm, step 50, default 300
- Pad slider: range 16–256px, step 8, default 64
- Both debounced 400ms before triggering API refetch
- Show unit labels (μm, px)

### Interaction Design

```
User Action               System Response
──────────────────────────────────────────────────────────────
Hover CropTile            → highlight corresponding cluster on WaferMap
Click WaferMap cluster    → scroll CropGrid to that cluster
Change eps slider         → debounced 400ms → refetch → grid updates (preserve scroll)
Click [Confirm & Export]  → close DefectCropViewer → open ExportDatasetModal
Click [← Back]           → close DefectCropViewer → return to scan results table
Click single defect tile  → full-screen image preview (Ant Design Modal)
```

---

## 8. Design Decision: Crop Viewer Effect on Dataset Content

> **Q: Does the crop viewer change what gets exported to the dataset?**

**Answer: No — in v1.** The crop viewer is preview-only. The dataset export always uses the original full images from the scan export folder. This is consistent with the existing pipeline and does not require changes to `export-dataset` API.

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
| **State management** | React Query (server data) + local useState (slider values, modal open) |
| **UI integration** | Intercept "Export to VL Dataset" button → crop viewer → existing ExportDatasetModal |
| **Backward compatibility** | Zero changes to existing export flow, API, or ExportDatasetModal |
