# UI Design & Sequence Flow - Dataset Viewer with Tile Drill-Down

## Context

Based on the data analysis from `DATA_ANALYSIS_v2.md`:

- A **dataset** contains full-frame scan images (~1380x1036 px each)
- Each frame can be **tiled on demand** via API into a 14x10 grid of 128x128 px tiles
- Frames come from wafer inspection scans with rich metadata: lot, wafer, recipe,
  classification (OClass), zone, die coordinates, etc.
- The source data lives in `DB.csv` (one row per frame) with `Classes.json` for label lookup

---

## 1. Main Form - Dataset Browser

### Layout

```
+============================================================================+
|  [Logo] Dataset Viewer          [Dataset: MTK-AHJ11236 v]  [Settings]     |
+============================================================================+
|                                                                            |
|  +--SIDEBAR (Grouping)--+  +--MAIN AREA (Frame Grid)--------------------+ |
|  |                       |  |                                            | |
|  | Group By:             |  |  [Search/Filter bar____________] [Export]  | |
|  |  (*) Lot              |  |                                            | |
|  |  ( ) Classification   |  |  Showing 90 frames | 3 groups              | |
|  |  ( ) Recipe           |  |                                            | |
|  |  ( ) Zone             |  |  --- Lot 01 (34 frames) ------[collapse]  | |
|  |  ( ) Wafer Position   |  |  +------+ +------+ +------+ +------+     | |
|  |  ( ) Defect Status    |  |  | img  | | img  | | img  | | img  |     | |
|  |  ( ) Custom...        |  |  | 259793| | 260484| | 260355| | 254723|  | |
|  |                       |  |  | OC:1  | | OC:34 | | OC:1  | | OC:2  |  | |
|  | -----                 |  |  +------+ +------+ +------+ +------+     | |
|  | FILTERS               |  |  +------+ +------+ ...                    | |
|  |                       |  |  | img  | | img  |                        | |
|  | Classification:       |  |  +------+ +------+                        | |
|  |  [x] Pass             |  |                                            | |
|  |  [x] Defects          |  |  --- Lot 02 (28 frames) ------[collapse]  | |
|  |  [x] Critical         |  |  +------+ +------+ +------+ +------+     | |
|  |                       |  |  | img  | | img  | | img  | | img  |     | |
|  | Recipe:               |  |  +------+ +------+ +------+ +------+     | |
|  |  [x] x7.5 Bump PMI   |  |  ...                                      | |
|  |  [x] x3.5 Surface     |  |                                            | |
|  |                       |  |  --- Lot 05 (28 frames) ------[collapse]  | |
|  | Lot:                  |  |  ...                                       | |
|  |  [x] 01               |  |                                            | |
|  |  [x] 02               |  |                                            | |
|  |  [x] 05               |  |                                            | |
|  |                       |  |                                            | |
|  +-----------------------+  +--------------------------------------------+ |
|                                                                            |
+============================================================================+
|  Status: 90 frames loaded | API: Connected | Tiles cached: 0              |
+============================================================================+
```

### Frame Thumbnail Card

Each card in the grid shows:

```
+------------------+
|  [Full frame     |
|   thumbnail]     |
|                  |
|------------------|
| 259793.119486    |  <-- ScanID1.SiteID (short form)
| Lot 01 | R1     |  <-- Lot + Recipe
| Class: Pass (1)  |  <-- OClass label from Classes.json
| Zone 7 | (3,12) |  <-- Zone + Col,Row
+------------------+
```

---

## 2. Grouping Options (Bucket Strategies)

The dataset can be grouped by any field from `DB.csv`. Here are the recommended options:

### Option A: Group by Lot
**Best for:** Batch-level overview, comparing wafers across lots

```
Lot 01  (34 frames)
  |- frame1, frame2, ...
Lot 02  (28 frames)
  |- frame1, frame2, ...
Lot 05  (28 frames)
  |- frame1, frame2, ...
```

### Option B: Group by Classification (OClass)
**Best for:** Defect review, quality analysis, labeling triage

```
Pass (OClass=1)           (72 frames)   [green badge]
Surface (OClass=2)        (8 frames)    [yellow badge]
Solder (OClass=3)         (3 frames)    [orange badge]
Prob (OClass=6)           (2 frames)    [red badge]
Bump Damage (OClass=10)   (5 frames)    [red badge]
```

Uses `Classes.json` to resolve OClass code to label.
Color badges: green=Pass, yellow=Minor, orange=Major, red=Critical.

### Option C: Group by Recipe
**Best for:** Comparing inspection modes, per-recipe analysis

```
x7.5 Bump PMI  (Recipe 1)   (45 frames)
  |- high-magnification bump inspection images
x3.5 Surface   (Recipe 2)   (45 frames)
  |- lower-magnification surface inspection images
```

### Option D: Group by Zone
**Best for:** Spatial analysis, identifying zone-specific defect patterns

```
Zone 7   (30 frames)
Zone 9   (25 frames)
Zone 63  (20 frames)
...other zones...
```

### Option E: Group by Wafer Position (Row-Col Grid)
**Best for:** Wafer map view, spatial defect distribution

```
Visual wafer map layout:
         Col 0    Col 1    Col 2    Col 3    Col 4    Col 5    Col 6    Col 7
Row 0   [frame] [frame]                                       [frame] [frame]
Row 1   [frame] [frame] [frame] [frame] [frame] [frame] [frame] [frame]
...
Row 24  [frame] [frame]                                       [frame] [frame]
```

This is a special "wafer map" view where the grid layout itself IS the grouping.
Each cell = one die. Color = OClass. Click to open frame detail.

### Option F: Group by Defect Status (Binary Pass/Fail)
**Best for:** Quick triage, high-level yield view

```
PASS     (OClass=1, 4, 5)                  (XX frames)  [green]
FAIL     (OClass=2, 3, 6, 10-99)           (XX frames)  [red]
UNCLASSIFIED  (OClass=0 or missing)        (XX frames)  [gray]
```

### Option G: Group by Classification + Lot (Two-Level)
**Best for:** Cross-lot defect comparison

```
Pass
  |- Lot 01 (30 frames)
  |- Lot 02 (25 frames)
  |- Lot 05 (17 frames)
Surface Defect
  |- Lot 01 (2 frames)
  |- Lot 02 (1 frame)
  |- Lot 05 (5 frames)
```

### Option H: Custom Grouping
User selects primary + optional secondary grouping field from a dropdown:
- Primary: Lot / OClass / Recipe / Zone / Row / Col
- Secondary: (none) / Lot / OClass / Recipe / Zone

---

## 3. Frame Detail View (after clicking a frame)

When the user selects a full-frame image from the grid, a detail panel opens.

### Layout

```
+============================================================================+
|  [< Back to Grid]    Frame: 259793.119486.c.-1615541774.1                 |
+============================================================================+
|                                                                            |
|  +--LEFT: Full Frame Image (zoomable)----+  +--RIGHT: Metadata Panel----+ |
|  |                                        |  |                           | |
|  |  +----------------------------------+  |  | Scan ID: 259793.119486   | |
|  |  |                                  |  |  | Hash: -1615541774        | |
|  |  |    FULL FRAME IMAGE              |  |  | Recipe: 1 (x7.5 Bump)   | |
|  |  |    (~1380 x 1036 px)             |  |  | Version: 1               | |
|  |  |                                  |  |  | Lot: 01 | Wafer: 01     | |
|  |  |    [tile grid overlay toggle]    |  |  | Col: 18 | Row: 8        | |
|  |  |                                  |  |  | Zone: 7                  | |
|  |  |    click on a tile region to     |  |  | OClass: 1 (Pass)         | |
|  |  |    request/view that tile        |  |  | Wafer X: 259794.29       | |
|  |  |                                  |  |  | Wafer Y: 119487.37       | |
|  |  +----------------------------------+  |  |                           | |
|  |                                        |  | --- Tile Status ---       | |
|  |  [Show Grid] [Zoom +/-] [Fit]         |  | Total: 140 tiles          | |
|  |                                        |  | Loaded: 0 / 140           | |
|  +----------------------------------------+  | Cached: 0 / 140           | |
|                                               |                           | |
|  +--BOTTOM: Tile Strip (lazy loaded)-------+  | [Load All Tiles]          | |
|  |                                          |  | [Clear Tile Cache]        | |
|  |  +----+ +----+ +----+ +----+ +----+     |  |                           | |
|  |  |x0  | |x103| |x206| |x309| |x412| ... |  | --- Annotations ---       | |
|  |  |y0  | |y0  | |y0  | |y0  | |y0  |     |  | Defects: 0                | |
|  |  +----+ +----+ +----+ +----+ +----+     |  | (no annotations yet)      | |
|  |  row 0 of 10      [scroll -->]           |  |                           | |
|  +------------------------------------------+  +---------------------------+ |
|                                                                            |
+============================================================================+
```

### Full Frame Image Interactions

1. **Grid Overlay Toggle** - draws the 14x10 tile grid over the full frame
2. **Click on Grid Cell** - triggers API call to fetch that specific tile
3. **Zoom** - pan & zoom the full frame image
4. **Hover on Grid Cell** - shows tile coordinate tooltip (e.g. "x618, y412")

### Tile Strip (Bottom)

- Horizontally scrollable strip showing tiles in grid order
- Tiles load **on demand** (lazy) or **batch** via "Load All Tiles"
- Each tile shows its (x, y) label and load status

---

## 4. Sequence Diagrams

### 4.1 App Startup & Dataset Load

```
  User                   Main Form               API Server           DB.csv/Classes.json
   |                        |                        |                        |
   |  Open app              |                        |                        |
   |----------------------->|                        |                        |
   |                        |  GET /datasets         |                        |
   |                        |----------------------->|                        |
   |                        |  [{id, name, lots}]    |                        |
   |                        |<-----------------------|                        |
   |                        |                        |                        |
   |  Select dataset        |                        |                        |
   |  "MTK-AHJ11236"       |                        |                        |
   |----------------------->|                        |                        |
   |                        |  GET /datasets/{id}/frames                     |
   |                        |  ?include=metadata     |                        |
   |                        |----------------------->|                        |
   |                        |                        |  Read DB.csv rows      |
   |                        |                        |  Read Classes.json     |
   |                        |                        |----------------------->|
   |                        |                        |  Parse & join          |
   |                        |                        |<-----------------------|
   |                        |  [{frame_id, lot,      |                        |
   |                        |    recipe, oclass,     |                        |
   |                        |    oclass_label, zone, |                        |
   |                        |    col, row,           |                        |
   |                        |    thumbnail_url}]     |                        |
   |                        |<-----------------------|                        |
   |                        |                        |                        |
   |  Render grid           |                        |                        |
   |  (default: group by Lot)                        |                        |
   |<-----------------------|                        |                        |
```

### 4.2 Change Grouping

```
  User                   Main Form                       State
   |                        |                              |
   |  Click "Group by       |                              |
   |  Classification"       |                              |
   |----------------------->|                              |
   |                        |  Re-bucket frames locally    |
   |                        |  (no API call needed -       |
   |                        |   all metadata already       |
   |                        |   loaded)                    |
   |                        |------------------------------>|
   |                        |                              |
   |                        |  Group frames by OClass:     |
   |                        |  { "Pass(1)": [f1,f3,...],   |
   |                        |    "Surface(2)": [f7,...] }  |
   |                        |<-----------------------------|
   |                        |                              |
   |  Re-render grid        |                              |
   |  with new buckets      |                              |
   |<-----------------------|                              |
```

**Key point:** Grouping is a **client-side** operation. All frame metadata is loaded
upfront; switching groups just re-sorts/re-buckets the same data. No extra API call.

### 4.3 Select Frame & View Detail

```
  User                   Main Form             Frame Detail View         API Server
   |                        |                        |                        |
   |  Click frame card      |                        |                        |
   |  "259793.119486..."    |                        |                        |
   |----------------------->|                        |                        |
   |                        |  Open detail view      |                        |
   |                        |----------------------->|                        |
   |                        |                        |                        |
   |                        |                        |  GET /frames/{id}/image|
   |                        |                        |  (full frame)          |
   |                        |                        |----------------------->|
   |                        |                        |  JPEG binary (~1380x1036)
   |                        |                        |<-----------------------|
   |                        |                        |                        |
   |  Show full frame +     |                        |                        |
   |  metadata panel        |                        |                        |
   |<-----------------------------------------------|                        |
   |                        |                        |                        |
   |  (tiles NOT loaded     |                        |                        |
   |   yet - on demand)     |                        |                        |
```

### 4.4 Request Tiles for a Frame (On-Demand)

```
  User                 Frame Detail View          Tile Cache            API Server
   |                        |                        |                        |
   |  Click tile region     |                        |                        |
   |  (x=618, y=412)       |                        |                        |
   |----------------------->|                        |                        |
   |                        |  Check cache            |                        |
   |                        |  key: "259793_x618_y412"|                       |
   |                        |----------------------->|                        |
   |                        |  MISS                  |                        |
   |                        |<-----------------------|                        |
   |                        |                        |                        |
   |                        |  GET /frames/{id}/tiles?x=618&y=412            |
   |                        |------------------------------------------------>|
   |                        |  JPEG 128x128 tile     |                        |
   |                        |<------------------------------------------------|
   |                        |                        |                        |
   |                        |  Store in cache         |                        |
   |                        |----------------------->|                        |
   |                        |                        |                        |
   |  Show zoomed tile      |                        |                        |
   |  + highlight on grid   |                        |                        |
   |<-----------------------|                        |                        |
```

### 4.5 Load All Tiles (Batch)

```
  User                 Frame Detail View          Tile Cache            API Server
   |                        |                        |                        |
   |  Click [Load All]      |                        |                        |
   |----------------------->|                        |                        |
   |                        |                        |                        |
   |                        |  GET /frames/{id}/tiles                         |
   |                        |  (all 140 tiles)       |                        |
   |                        |------------------------------------------------>|
   |                        |                        |                        |
   |                        |       Tiling pipeline runs (or returns cached): |
   |                        |       - tile_w=128, tile_h=128                  |
   |                        |       - stride=103, overlap=25                  |
   |                        |       - grid: 14x10 = 140 tiles                |
   |                        |       - clip_tiles_to_image=True                |
   |                        |                        |                        |
   |  Show progress bar     |                        |                        |
   |  "Loading tiles..."    |                        |                        |
   |<-----------------------|                        |                        |
   |                        |                        |                        |
   |                        |  Response: {tiles: [   |                        |
   |                        |    {x:0, y:0, url:"..."},                       |
   |                        |    {x:103, y:0, url:"..."},                     |
   |                        |    ...140 entries       |                        |
   |                        |  ]}                    |                        |
   |                        |<------------------------------------------------|
   |                        |                        |                        |
   |                        |  Bulk cache store       |                        |
   |                        |----------------------->|                        |
   |                        |                        |                        |
   |  Render tile strip     |                        |                        |
   |  + grid overlay fills  |                        |                        |
   |<-----------------------|                        |                        |
```

### 4.6 Navigate Between Frames (with tile cache)

```
  User                 Frame Detail View          Tile Cache
   |                        |                        |
   |  Click [Next Frame]    |                        |
   |  or keyboard arrow     |                        |
   |----------------------->|                        |
   |                        |                        |
   |                        |  Current frame tiles   |
   |                        |  stay in cache         |
   |                        |  (keyed by frame_id)   |
   |                        |                        |
   |                        |  Load new frame image  |
   |                        |  (same as 4.3)         |
   |                        |                        |
   |  If user returns to    |                        |
   |  previous frame,       |                        |
   |  tiles load from cache |                        |
   |  (instant, no API)     |                        |
   |<-----------------------|                        |
```

---

## 5. API Contract (Assumed Endpoints)

Based on the data structure in the analysis, the API should expose:

### Dataset Level

| Method | Endpoint | Response | Notes |
|--------|----------|----------|-------|
| GET | `/datasets` | `[{id, name, customer, job, setup}]` | List available datasets |
| GET | `/datasets/{id}` | `{id, name, metadata, frame_count}` | Dataset info from MetaData.json |

### Frame Level

| Method | Endpoint | Response | Notes |
|--------|----------|----------|-------|
| GET | `/datasets/{id}/frames` | `[{frame_id, lot, recipe, recipe_name, oclass, oclass_label, zone, col, row, wafer_x, wafer_y, thumbnail_url}]` | All frames with metadata. Source: DB.csv joined with Classes.json |
| GET | `/frames/{frame_id}/image` | JPEG binary (~1380x1036) | Full-frame original image |

### Tile Level

| Method | Endpoint | Response | Notes |
|--------|----------|----------|-------|
| GET | `/frames/{frame_id}/tiles` | `{tiles: [{x, y, url, width, height}], grid: {cols:14, rows:10, tile_w:128, tile_h:128, stride:103}}` | All 140 tiles for a frame. Triggers tiling pipeline if not cached. |
| GET | `/frames/{frame_id}/tiles?x={X}&y={Y}` | JPEG binary (128x128) | Single tile at position (x,y). |
| GET | `/frames/{frame_id}/tile-status` | `{total:140, cached:N, grid:{...}}` | Check how many tiles are ready without triggering tiling. |

### Annotation Level (Future)

| Method | Endpoint | Response | Notes |
|--------|----------|----------|-------|
| GET | `/frames/{frame_id}/annotations` | COCO annotations array | From `_annotations.coco.json` |
| POST | `/frames/{frame_id}/annotations` | Created annotation | Add defect bounding box |
| GET | `/datasets/{id}/annotations/export` | Full COCO JSON | Export complete dataset |

---

## 6. Data Flow & State Management

### Client-Side State

```
AppState
  |
  +-- dataset: {id, name, metadata}
  |
  +-- frames: [                              <-- loaded once from API
  |     {
  |       frame_id: "259793.119486.c.-1615541774.1",
  |       scan_id: "259793",
  |       site_id: "119486",
  |       hash: "-1615541774",
  |       version: "1",
  |       lot: "01",
  |       recipe: 1,
  |       recipe_name: "x7.5 Bump PMI",
  |       oclass: 1,
  |       oclass_label: "Pass",
  |       zone: 7,
  |       col: 18,
  |       row: 8,
  |       wafer_x: 259794.29,
  |       wafer_y: 119487.37,
  |       thumbnail_url: "/frames/.../thumbnail"
  |     },
  |     ...
  |   ]
  |
  +-- grouping: {
  |     primary: "lot",           <-- current bucket key
  |     secondary: null,          <-- optional two-level grouping
  |     buckets: {                <-- computed client-side from frames[]
  |       "Lot 01": [frame, frame, ...],
  |       "Lot 02": [frame, frame, ...],
  |       "Lot 05": [frame, frame, ...]
  |     }
  |   }
  |
  +-- filters: {
  |     oclass: [1, 2, 3, ...],  <-- active class filters
  |     recipe: [1, 2],
  |     lot: ["01", "02", "05"]
  |   }
  |
  +-- selectedFrame: {
  |     frame_id: "...",
  |     full_image: Blob | null,       <-- loaded on frame select
  |     tiles: {                       <-- loaded on demand
  |       "x0_y0": {url, blob, loaded: true},
  |       "x103_y0": {url, blob: null, loaded: false},
  |       ...
  |     },
  |     grid_overlay_visible: false
  |   }
  |
  +-- tileCache: Map<frame_id, Map<"x{X}_y{Y}", Blob>>
       (persists across frame navigation, cleared on dataset switch)
```

### Re-Bucketing Logic (Client-Side)

```
function groupFrames(frames, groupBy, filters) {
    // 1. Apply filters
    let filtered = frames.filter(f =>
        filters.oclass.includes(f.oclass) &&
        filters.recipe.includes(f.recipe) &&
        filters.lot.includes(f.lot)
    );

    // 2. Group by selected key
    let buckets = {};
    for (let frame of filtered) {
        let key;
        switch (groupBy) {
            case "lot":             key = `Lot ${frame.lot}`; break;
            case "classification":  key = `${frame.oclass_label} (${frame.oclass})`; break;
            case "recipe":          key = `${frame.recipe_name}`; break;
            case "zone":            key = `Zone ${frame.zone}`; break;
            case "position":        key = `Row ${frame.row}`; break;
            case "defect_status":   key = frame.oclass <= 5 ? "PASS" : "FAIL"; break;
        }
        (buckets[key] = buckets[key] || []).push(frame);
    }

    // 3. Sort buckets
    return sortBuckets(buckets, groupBy);
}
```

---

## 7. Tile Management Strategy

### Cache Architecture

```
                         +-------------------+
                         |   Frame Selected  |
                         +--------+----------+
                                  |
                   +--------------+--------------+
                   |                             |
                   v                             v
          +----------------+            +----------------+
          | Full Frame     |            | Tile Grid      |
          | Image Load     |            | Manager        |
          | (always eager) |            | (lazy by       |
          +----------------+            |  default)      |
                                        +-------+--------+
                                                |
                              +-----------------+-----------------+
                              |                 |                 |
                              v                 v                 v
                      +-------------+   +-------------+   +-------------+
                      | Click Tile  |   | Load All    |   | Grid Hover  |
                      | (single)    |   | (batch)     |   | (prefetch?) |
                      +------+------+   +------+------+   +------+------+
                             |                 |                 |
                             v                 v                 v
                      +------------------------------------------------+
                      |              TILE CACHE                         |
                      |                                                |
                      |  Key: "{frame_id}_{x}_{y}"                     |
                      |  Value: JPEG Blob (128x128)                    |
                      |                                                |
                      |  Eviction: LRU per frame (keep last 5 frames) |
                      |  Max size: ~50 MB (5 frames x 140 tiles x     |
                      |            ~5KB avg = ~3.5 MB per frame)      |
                      +------------------------------------------------+
```

### Tile Loading Modes

| Mode | Trigger | API Calls | UX |
|------|---------|-----------|-----|
| **On-demand** (default) | Click tile on grid overlay | 1 per click | Tile appears after ~200ms |
| **Batch** | Click "Load All Tiles" | 1 call (returns 140 tiles) | Progress bar, then all tiles render |
| **Prefetch** (optional) | Hover over grid region | 1 per hovered tile (debounced) | Tile ready when clicked |
| **Cached** | Revisit a frame | 0 (from local cache) | Instant render |

---

## 8. Tile Coordinate Mapping

When the user clicks on the full-frame image with grid overlay enabled,
map the click pixel to a tile coordinate:

```
function pixelToTile(clickX, clickY) {
    // Grid parameters (from tiling_log.txt)
    const TILE_W = 128, TILE_H = 128;
    const STRIDE_X = 103, STRIDE_Y = 103;
    const X_POSITIONS = [0,103,206,309,412,515,618,721,824,927,1030,1133,1236,1252];
    const Y_POSITIONS = [0,103,206,309,412,515,618,721,824,908];

    // Find the tile whose region contains the click
    // (account for display scaling: clickX/Y are in display coords)
    let imageX = clickX * (sourceWidth / displayWidth);
    let imageY = clickY * (sourceHeight / displayHeight);

    // Find closest tile origin
    let tileX = X_POSITIONS.reduce((prev, curr) =>
        Math.abs(curr - imageX) < Math.abs(prev - imageX) ? curr : prev
    );
    let tileY = Y_POSITIONS.reduce((prev, curr) =>
        Math.abs(curr - imageY) < Math.abs(prev - imageY) ? curr : prev
    );

    return { x: tileX, y: tileY };
}
```

---

## 9. Summary - Component Interaction

```
+=============================================================================+
|                          COMPONENT INTERACTION MAP                           |
+=============================================================================+

  +-------------------+          +---------------------+
  | Dataset Selector  |--------->| Frame Grid (Main)   |
  | (top bar)         |  loads   | - grouped by bucket |
  +-------------------+  frames  | - filtered          |
                                 | - thumbnail cards   |
                                 +----------+----------+
                                            |
                         +------------------+------------------+
                         |                                     |
                         v                                     v
              +-------------------+                 +-------------------+
              | Grouping Controls |                 | Filter Panel      |
              | (sidebar radio)   |                 | (sidebar checks)  |
              |                   |  re-bucket      |                   |
              | Lot               |  (client-side,  | OClass filter     |
              | Classification    |  no API call)   | Recipe filter     |
              | Recipe            |                 | Lot filter        |
              | Zone              |                 |                   |
              | Wafer Position    |                 |                   |
              | Defect Status     |                 |                   |
              | Custom (2-level)  |                 |                   |
              +-------------------+                 +-------------------+

                    Frame Grid
                         |
                    click frame
                         |
                         v
              +-----------------------------+
              |    Frame Detail View        |
              |                             |
              |  +----------+ +-----------+ |
              |  | Full     | | Metadata  | |
              |  | Frame    | | Panel     | |
              |  | (zoom,   | | (DB.csv   | |
              |  |  pan,    | |  fields)  | |
              |  |  grid    | |           | |
              |  |  overlay)| |           | |
              |  +----+-----+ +-----------+ |
              |       |                     |
              |  click grid cell            |
              |       |                     |
              |       v                     |
              |  +---------------------+    |
              |  | Tile API Request    |    |
              |  | GET /frames/{id}/   |    |
              |  |   tiles?x=N&y=N    |    |
              |  +----+----------------+    |
              |       |                     |
              |       v                     |
              |  +---------------------+    |
              |  | Tile Cache          |    |
              |  | (LRU, ~5 frames)   |    |
              |  +---------------------+    |
              |       |                     |
              |       v                     |
              |  +---------------------+    |
              |  | Tile Strip          |    |
              |  | (bottom, scroll)    |    |
              |  +---------------------+    |
              |                             |
              +-----------------------------+


  DATA SOURCES:
  
  DB.csv ---------> frame metadata (lot, recipe, oclass, zone, col, row, coords)
  Classes.json ---> oclass code to human label mapping
  MetaData.json --> dataset-level info (customer, job, setup, recipes)
  API -----------> full frame images + on-demand tile generation
  COCO JSON -----> annotations (future, currently empty)
```

---

## 10. Edge Cases & Considerations

| Case | Handling |
|------|----------|
| Frame has no tiles cached | Show empty grid overlay; tiles load on click |
| API tile request fails | Show error icon on grid cell; retry on next click |
| Partial scan (e.g. 26164.142498 with <140 tiles) | Show available tile cells; gray out missing positions |
| Duplicate y908 COCO entries | Deduplicate in client by (frame_id, x, y) key |
| Large dataset (1000+ frames) | Virtual scrolling in frame grid; paginate API |
| Switching grouping with filters active | Re-bucket filtered set only |
| Frame from "after-crop" folder (split data) | API should abstract storage location; same endpoint |
| No annotations yet | Show "No defects labeled" badge; ready for annotation workflow |

---

## 11. Detection AI - UX/UI Form Design

This section covers the **AI-powered defect detection workflow** -- how the user
triggers inference on frames/tiles, reviews results, and provides feedback.

### 11.1 Detection Mode Entry Points

The user can invoke detection AI from three locations:

```
+============================================================================+
| ENTRY POINTS FOR DETECTION AI                                              |
+============================================================================+
|                                                                            |
|  1. DATASET LEVEL (batch)                                                  |
|     Main Grid -> [Run Detection AI] button (top toolbar)                  |
|     Runs on ALL visible (filtered) frames                                 |
|                                                                            |
|  2. FRAME LEVEL (single frame)                                            |
|     Frame Detail View -> [Detect Defects] button                          |
|     Runs on the currently selected full frame                             |
|                                                                            |
|  3. TILE LEVEL (single tile)                                              |
|     Frame Detail View -> right-click tile -> "Run Detection"              |
|     Runs on one 128x128 tile (useful for spot-checking)                   |
|                                                                            |
+============================================================================+
```

### 11.2 Detection AI Control Panel

Appears as a slide-out panel or modal when the user initiates detection.

```
+============================================================================+
|                    DETECTION AI - CONTROL PANEL                            |
+============================================================================+
|                                                                            |
|  Model:  [ RF-DETR v1.0         v ]     Status: Ready                     |
|                                                                            |
|  +--- Scope ----------------------------------------------------------+   |
|  |  (*) All visible frames (72 frames after filters)                  |   |
|  |  ( ) Selected frames only (3 selected)                             |   |
|  |  ( ) Current frame only                                            |   |
|  +--------------------------------------------------------------------+   |
|                                                                            |
|  +--- Detection Settings ---------------------------------------------+   |
|  |                                                                     |   |
|  |  Confidence Threshold:   [====O========] 0.50                       |   |
|  |                          low              high                      |   |
|  |                                                                     |   |
|  |  NMS IoU Threshold:      [========O====] 0.70                       |   |
|  |                                                                     |   |
|  |  Max Detections / Tile:  [ 50    ]                                  |   |
|  |                                                                     |   |
|  |  Target Classes:                                                    |   |
|  |    [x] All Defect Types                                            |   |
|  |    [ ] Surface only                                                |   |
|  |    [ ] Bump only                                                   |   |
|  |    [ ] Custom selection...                                         |   |
|  |                                                                     |   |
|  +--------------------------------------------------------------------+   |
|                                                                            |
|  +--- Tiling Strategy -------------------------------------------------+   |
|  |  Use existing tiles from cache when available:  [x]                 |   |
|  |  Tile parameters: 128x128, stride 103, overlap 25                   |   |
|  |  (read-only, matches training pipeline config)                      |   |
|  +--------------------------------------------------------------------+   |
|                                                                            |
|  Estimated time: ~45 sec for 72 frames (140 tiles each)                   |
|                                                                            |
|            [ Cancel ]                    [ Run Detection ]                  |
|                                                                            |
+============================================================================+
```

### 11.3 Detection Progress View

```
+============================================================================+
|                    DETECTION AI - RUNNING                                   |
+============================================================================+
|                                                                            |
|  Overall Progress:  [================>-----------]  62%                    |
|  Frame 45 / 72     |  ETA: 17 sec                                        |
|                                                                            |
|  +--- Pipeline Stages ------------------------------------------------+   |
|  |                                                                     |   |
|  |  [done] 1. Request tiles for frame   (45/72 frames tiled)          |   |
|  |  [>>>>] 2. Run inference on tiles    (6,160 / 10,080 tiles)        |   |
|  |  [    ] 3. Aggregate tile results    (merging overlapping boxes)    |   |
|  |  [    ] 4. Map back to full frame    (coordinate transform)        |   |
|  |                                                                     |   |
|  +--------------------------------------------------------------------+   |
|                                                                            |
|  +--- Live Feed (last processed frame) --------------------------------+  |
|  |                                                                      |  |
|  |  Frame: 125490.291548.c.77695041.2                                   |  |
|  |  Tiles processed: 140/140                                            |  |
|  |  Detections found: 3                                                 |  |
|  |  +------+------+------+                                             |  |
|  |  | tile | tile | tile |  <-- tiles with detections highlighted       |  |
|  |  | x412 | x515 | x515|                                              |  |
|  |  | y309 | y309 | y412|                                              |  |
|  |  +------+------+------+                                             |  |
|  |                                                                      |  |
|  +----------------------------------------------------------------------+  |
|                                                                            |
|  Defects found so far: 47 across 18 frames                               |
|                                                                            |
|            [ Stop ]                      [ Run in Background ]             |
|                                                                            |
+============================================================================+
```

### 11.4 Detection Results View

After detection completes, the main grid updates with detection badges,
and a results panel appears.

```
+============================================================================+
|  [Logo] Dataset Viewer      [MTK-AHJ11236 v] [Detection Results Active]   |
+============================================================================+
|                                                                            |
|  +--SIDEBAR--------------+  +--MAIN AREA (with detection overlay)-------+ |
|  |                        |  |                                           | |
|  | Group By:              |  |  [Search___________] [Export Results]     | |
|  |  ( ) Lot               |  |                                           | |
|  |  (*) Detection Result  |  |  Showing 72 frames | Detection: RF-DETR  | |
|  |  ( ) Classification    |  |                                           | |
|  |  ( ) Recipe            |  |  --- Defects Found (18 frames) ---        | |
|  |                        |  |  +------+ +------+ +------+ +------+     | |
|  | -----                  |  |  | img  | | img  | | img  | | img  |     | |
|  | DETECTION SUMMARY      |  |  |[!] 3 | |[!] 1 | |[!] 7 | |[!] 2 |   | |
|  |                        |  |  | 0.92 | | 0.67 | | 0.88 | | 0.71 |   | |
|  | Total frames: 72       |  |  +------+ +------+ +------+ +------+    | |
|  | Frames w/ defects: 18  |  |  ...                                     | |
|  | Total detections: 47   |  |                                           | |
|  | Avg confidence: 0.78   |  |  --- Clean (54 frames) ---               | |
|  |                        |  |  +------+ +------+ +------+ +------+     | |
|  | Confidence dist:       |  |  | img  | | img  | | img  | | img  |     | |
|  |  0.9+ :  12 ████       |  |  | [ok] | | [ok] | | [ok] | | [ok] |     | |
|  |  0.7-0.9: 23 ██████   |  |  +------+ +------+ +------+ +------+     | |
|  |  0.5-0.7: 12 ████     |  |  ...                                      | |
|  |                        |  |                                           | |
|  | -----                  |  |                                           | |
|  | CONFIDENCE FILTER      |  |                                           | |
|  | [====O========] 0.50   |  |                                           | |
|  |                        |  |                                           | |
|  | REVIEW STATUS          |  |                                           | |
|  |  [ ] Unreviewed (47)   |  |                                           | |
|  |  [ ] Confirmed (0)     |  |                                           | |
|  |  [ ] Rejected (0)      |  |                                           | |
|  |                        |  |                                           | |
|  +------------------------+  +-------------------------------------------+ |
+============================================================================+
```

**Frame card with detection badge:**

```
+----- defect frame ------+     +----- clean frame -------+
|  [Full frame thumbnail  |     |  [Full frame thumbnail  |
|   with red boxes on     |     |   no overlays]          |
|   detected regions]     |     |                         |
|-------------------------|     |-------------------------|
| 125490.291548           |     | 260355.228367           |
| Lot 01 | R1             |     | Lot 01 | R1             |
| [!] 3 defects           |     | [ok] Clean              |
| max conf: 0.92          |     | AI confidence: 0.99     |
| Status: Unreviewed      |     | Status: --              |
+-------------------------+     +-------------------------+
```

### 11.5 Frame Detail with Detection Overlay

When clicking a frame that has detections:

```
+============================================================================+
|  [< Back]    Frame: 125490.291548    [Prev Defect] [Next Defect] 1/3      |
+============================================================================+
|                                                                            |
|  +--LEFT: Full Frame with Detections-----+  +--RIGHT: Detection Panel---+ |
|  |                                        |  |                           | |
|  |  +----------------------------------+  |  | FRAME METADATA            | |
|  |  |                                  |  |  | Lot: 01 | Recipe: 1      | |
|  |  |    FULL FRAME IMAGE              |  |  | OClass: 1 (Pass)         | |
|  |  |                                  |  |  | Zone: 7                  | |
|  |  |         +--[BOX 1]--+            |  |  |                           | |
|  |  |         | Defect    |            |  |  | AI DETECTIONS (3)         | |
|  |  |         | conf:0.92 |            |  |  |                           | |
|  |  |         +-----------+            |  |  | +--- Detection #1 -----+ | |
|  |  |    +--[BOX 2]--+                 |  |  | | Class: Surface        | | |
|  |  |    | Defect    |                 |  |  | | Confidence: 0.92      | | |
|  |  |    | conf:0.87 | +--[BOX 3]--+  |  |  | | BBox: (412,309,       | | |
|  |  |    +-----------+ | Defect    |  |  |  | |        480,377)       | | |
|  |  |                  | conf:0.71 |  |  |  | | Source tiles:          | | |
|  |  |                  +-----------+  |  |  | |   x412_y309            | | |
|  |  |                                  |  |  | | Status: [Unreviewed v]| | |
|  |  +----------------------------------+  |  | | [ Confirm ] [Reject ] | | |
|  |                                        |  | +----------------------+ | |
|  |  [Grid] [Zoom] [Fit] [Hide Boxes]     |  |                           | |
|  |                                        |  | +--- Detection #2 -----+ | |
|  +----------------------------------------+  | | Class: Surface        | | |
|                                               | | Confidence: 0.87      | | |
|  +--BOTTOM: Detection Tiles-----------------+ | | ...                    | | |
|  |                                           | | +----------------------+ | |
|  |  +------+  +------+  +------+            | |                           | |
|  |  |tile  |  |tile  |  |tile  |            | | +--- Detection #3 -----+ | |
|  |  |x412  |  |x515  |  |x515  |           | | | Class: Bump Damage    | | |
|  |  |y309  |  |y309  |  |y412  |           | | | Confidence: 0.71      | | |
|  |  |[BOX] |  |[BOX] |  |[BOX] |           | | | ...                    | | |
|  |  |0.92  |  |0.87  |  |0.71  |           | | +----------------------+ | |
|  |  +------+  +------+  +------+            | |                           | |
|  |                                           | | [ Confirm All ]          | |
|  |  Showing 3 tiles with detections          | | [ Reject All ]           | |
|  +-------------------------------------------+ | [ Export Annotations ]   | |
|                                               +---------------------------+ |
+============================================================================+
```

### 11.6 Detection Review Workflow

```
  +------------------+         +------------------+         +------------------+
  |   UNREVIEWED     |-------->|    CONFIRMED     |         |    REJECTED      |
  |                  |  user   |                  |         |                  |
  |  AI detected a   |  clicks |  User agrees     |         |  User disagrees  |
  |  defect          |  Confirm|  this is a real   |         |  (false positive)|
  |                  |         |  defect           |         |                  |
  +------------------+         +------------------+         +------------------+
         |                                                          ^
         |                                                          |
         +------ user clicks Reject --------------------------------+
```

Each detection can be:
- **Confirmed** -> saved as COCO annotation (added to `_annotations.coco.json`)
- **Rejected** -> flagged as false positive (used for model retraining)
- **Edited** -> user adjusts bounding box, then confirms (corrected annotation)

---

## 12. Detection AI - Sequence Diagrams

### 12.1 Single Frame Detection (Full Sequence)

```
  User              Frame Detail        API Server         Tiling Service      AI Model (RF-DETR)
   |                    |                    |                    |                    |
   |  Click [Detect     |                    |                    |                    |
   |   Defects]         |                    |                    |                    |
   |------------------->|                    |                    |                    |
   |                    |                    |                    |                    |
   |                    |  POST /frames/{id}/detect                                   |
   |                    |  {confidence: 0.5, nms_iou: 0.7}                            |
   |                    |------------------->|                    |                    |
   |                    |                    |                    |                    |
   |                    |                    |  1. Check tile cache                    |
   |                    |                    |     for frame {id}  |                    |
   |                    |                    |------------------->|                    |
   |                    |                    |                    |                    |
   |                    |                    |  [MISS] Generate   |                    |
   |                    |                    |  140 tiles         |                    |
   |                    |                    |  128x128, stride   |                    |
   |                    |                    |  103, overlap 25   |                    |
   |                    |                    |<-------------------|                    |
   |                    |                    |                    |                    |
   |                    |                    |  2. Send tiles to model                 |
   |                    |                    |  (batch of 140)     |                    |
   |                    |                    |---------------------------------------->|
   |                    |                    |                    |                    |
   |                    |                    |                    |  Run RF-DETR       |
   |                    |                    |                    |  inference on each  |
   |                    |                    |                    |  128x128 tile       |
   |                    |                    |                    |                    |
   |                    |                    |  3. Per-tile results                    |
   |                    |                    |  [{tile_x, tile_y,  |                    |
   |                    |                    |    boxes: [{x1,y1,  |                    |
   |                    |                    |    x2,y2,conf,cls}]}|                    |
   |                    |                    |<----------------------------------------|
   |                    |                    |                    |                    |
   |                    |                    |  4. Post-process:                       |
   |                    |                    |  a) Transform tile-local                |
   |                    |                    |     coords to frame coords              |
   |                    |                    |     box.x1 += tile_x                    |
   |                    |                    |     box.y1 += tile_y                    |
   |                    |                    |                    |                    |
   |                    |                    |  b) Merge overlapping                   |
   |                    |                    |     detections from                     |
   |                    |                    |     adjacent tiles                      |
   |                    |                    |     (NMS on overlap                     |
   |                    |                    |      regions)                           |
   |                    |                    |                    |                    |
   |                    |                    |  c) Filter by                           |
   |                    |                    |     confidence                          |
   |                    |                    |     threshold                           |
   |                    |                    |                    |                    |
   |                    |  Response:         |                    |                    |
   |                    |  {detections: [    |                    |                    |
   |                    |    {bbox, conf,    |                    |                    |
   |                    |     class, tiles}  |                    |                    |
   |                    |  ]}                |                    |                    |
   |                    |<-------------------|                    |                    |
   |                    |                    |                    |                    |
   |  Show detections   |                    |                    |                    |
   |  as overlay boxes  |                    |                    |                    |
   |<-------------------|                    |                    |                    |
```

### 12.2 Batch Detection (Dataset Level)

```
  User              Main Grid            API Server          Queue/Worker
   |                    |                    |                    |
   |  Click [Run        |                    |                    |
   |  Detection AI]     |                    |                    |
   |  (72 frames)       |                    |                    |
   |------------------->|                    |                    |
   |                    |                    |                    |
   |                    |  POST /datasets/{id}/detect                         |
   |                    |  {frame_ids: [...72], confidence: 0.5}              |
   |                    |------------------->|                    |
   |                    |                    |                    |
   |                    |                    |  Create job        |
   |                    |                    |------------------->|
   |                    |                    |                    |
   |                    |  {job_id: "abc-123",                   |
   |                    |   status: "queued"}|                    |
   |                    |<-------------------|                    |
   |                    |                    |                    |
   |  Show progress     |                    |                    |
   |  bar               |                    |                    |
   |<-------------------|                    |                    |
   |                    |                    |                    |
   |                    |  Poll: GET /jobs/{job_id}/status                    |
   |                    |------------------->|                    |
   |                    |  {progress: 45/72, |  Worker processes  |
   |                    |   detections_so_   |  frames in         |
   |                    |   far: 23}         |  parallel batches  |
   |                    |<-------------------|  (8 workers)       |
   |                    |                    |                    |
   |  Update progress   |                    |                    |
   |  "45/72 frames"    |                    |                    |
   |<-------------------|                    |                    |
   |                    |                    |                    |
   |                    |  ... (polling continues) ...            |
   |                    |                    |                    |
   |                    |  {progress: 72/72, |                    |
   |                    |   status: "done",  |                    |
   |                    |   summary: {       |                    |
   |                    |     frames_with_   |                    |
   |                    |     defects: 18,   |                    |
   |                    |     total_         |                    |
   |                    |     detections: 47 |                    |
   |                    |   }}               |                    |
   |                    |<-------------------|                    |
   |                    |                    |                    |
   |  Update grid with  |                    |                    |
   |  detection badges  |                    |                    |
   |  on each frame card|                    |                    |
   |<-------------------|                    |                    |
```

### 12.3 Tile Overlap Merging (Post-Processing Detail)

This is the critical step where per-tile detections become full-frame detections.

```
  Problem: A defect near a tile boundary appears in multiple adjacent tiles.

  Example: defect at frame coords (620, 310) with size ~30x30 px
  
  Tile (x=515, y=206):  detects box at local (105, 104, 128, 128) -> conf 0.87
  Tile (x=618, y=206):  detects box at local (2, 104, 32, 128)    -> conf 0.91
  Tile (x=515, y=309):  detects box at local (105, 1, 128, 25)    -> conf 0.82
  Tile (x=618, y=309):  detects box at local (2, 1, 32, 25)       -> conf 0.89

  Step 1: Transform all boxes to frame coordinates
  +-----------+-----------+
  |tile(515,  |tile(618,  |
  | 206)      | 206)      |
  |      +----+----+      |        4 detections from 4 tiles
  |      |DEFECT   |      |        all refer to the same physical defect
  |------+----+----+------|
  |      |    |    |      |
  |tile(515,  |tile(618,  |
  | 309)      | 309)      |
  +-----------+-----------+
       overlap region
       (25 px wide)

  Step 2: Apply NMS (Non-Maximum Suppression) on overlap regions
  - IoU > 0.7 between any two boxes -> keep highest confidence
  - Result: 1 merged detection at frame coords (620, 310) conf 0.91

  Step 3: Final output per frame
  {
    "frame_id": "125490.291548.c.77695041.2",
    "detections": [
      {
        "bbox": [605, 295, 650, 340],    // frame-level coords [x1,y1,x2,y2]
        "confidence": 0.91,
        "class": "Defect",
        "source_tiles": ["x515_y206", "x618_y206", "x515_y309", "x618_y309"]
      }
    ]
  }
```

### 12.4 Review & Confirm Detection (Annotation Save)

```
  User              Frame Detail        API Server          COCO JSON
   |                    |                    |                    |
   |  Review detection  |                    |                    |
   |  #1 (conf: 0.92)  |                    |                    |
   |                    |                    |                    |
   |  (optional: drag   |                    |                    |
   |   to adjust bbox)  |                    |                    |
   |                    |                    |                    |
   |  Click [Confirm]   |                    |                    |
   |------------------->|                    |                    |
   |                    |                    |                    |
   |                    |  POST /frames/{id}/annotations                      |
   |                    |  {                  |                    |
   |                    |    bbox: [412,309,  |                    |
   |                    |           480,377], |                    |
   |                    |    category_id: 1,  |                    |
   |                    |    confidence: 0.92,|                    |
   |                    |    review: "confirmed",                 |
   |                    |    source: "ai",    |                    |
   |                    |    model: "RF-DETR  |                    |
   |                    |            v1.0"    |                    |
   |                    |  }                  |                    |
   |                    |------------------->|                    |
   |                    |                    |                    |
   |                    |                    |  Add to annotations[]           |
   |                    |                    |  in COCO format:                |
   |                    |                    |  {                              |
   |                    |                    |    "id": next_id,               |
   |                    |                    |    "image_id": frame_coco_id,   |
   |                    |                    |    "category_id": 1,            |
   |                    |                    |    "bbox": [412,309,68,68],     |
   |                    |                    |    "area": 4624,                |
   |                    |                    |    "iscrowd": 0                 |
   |                    |                    |  }                              |
   |                    |                    |------------------->|
   |                    |                    |                    |
   |                    |  {status: "saved", |                    |
   |                    |   annotation_id: N}|                    |
   |                    |<-------------------|                    |
   |                    |                    |                    |
   |  Badge: "Confirmed"|                   |                    |
   |  [green check]     |                    |                    |
   |<-------------------|                    |                    |
```

---

## 13. Detection AI - API Endpoints

| Method | Endpoint | Request | Response |
|--------|----------|---------|----------|
| POST | `/frames/{id}/detect` | `{confidence, nms_iou, max_per_tile, classes}` | `{detections: [{bbox, conf, class, source_tiles}]}` |
| POST | `/datasets/{id}/detect` | `{frame_ids, confidence, nms_iou}` | `{job_id, status: "queued"}` |
| GET | `/jobs/{job_id}/status` | -- | `{progress, total, detections_so_far, status}` |
| GET | `/jobs/{job_id}/results` | -- | `{frames: [{frame_id, detections}]}` |
| POST | `/frames/{id}/annotations` | `{bbox, category_id, confidence, review, source, model}` | `{annotation_id}` |
| PUT | `/annotations/{id}` | `{bbox?, review?, category_id?}` | `{updated}` |
| DELETE | `/annotations/{id}` | -- | `{deleted}` |
| GET | `/datasets/{id}/annotations/export` | `?format=coco` | Full COCO JSON with all confirmed annotations |

---

## 14. End-to-End User Journey

```
  +-----------+     +-----------+     +-----------+     +-----------+
  |  1. LOAD  |---->|  2. BROWSE|---->| 3. DETECT |---->| 4. REVIEW |
  |  Dataset  |     |  & Group  |     |  (AI)     |     |  Results  |
  +-----------+     +-----------+     +-----------+     +-----------+
       |                 |                 |                  |
       |                 |                 |                  |
       v                 v                 v                  v
  Select dataset    Group by lot,    Run RF-DETR on     Review each
  from dropdown.    classification,  all frames or      detection:
  Frames load       recipe, zone,    a single frame.    Confirm, Reject,
  with metadata     wafer position,  Tiles generated    or Edit bbox.
  from DB.csv +     defect status.   on demand via      Confirmed ->
  Classes.json.     Filter by any    API. Model runs    saved as COCO
                    combination.     on 128x128 tiles.  annotation.
                    Client-side      Overlap merging    Rejected ->
                    re-bucketing.    via NMS.           flagged for
                                                        retraining.
       |                 |                 |                  |
       v                 v                 v                  v
  +-----------+     +-----------+     +-----------+     +-----------+
  | 5. EXPORT |     | 6. WAFER  |     | 7. COMPARE|     | 8. RETRAIN|
  | Annotations|    |  MAP VIEW |     |  LOTS     |     |  MODEL    |
  +-----------+     +-----------+     +-----------+     +-----------+
       |                 |                 |                  |
       v                 v                 v                  v
  Export COCO       Spatial view:     Side-by-side      Export confirmed
  JSON with all     color-coded       lot comparison    + rejected as
  confirmed         wafer map         of defect rates,  training data
  annotations       showing defect    grouped by        for next model
  for training.     locations.        classification.   iteration.
```
