# Data Analysis v2 - Scan Folder `b2de9dd1-1c90-4ce9-8414-2b3f5d3431ba`

## Overview

This folder is the **output of an RF-DETR Training Pipeline tiling stage**. It contains
image tiles cropped from 90 semiconductor wafer inspection scans, plus three metadata
files that describe the tiling process, catalog every tile in COCO format, and track
pipeline progress.

| Metric                | Value                                |
|-----------------------|--------------------------------------|
| Folder UUID           | `b2de9dd1-1c90-4ce9-8414-2b3f5d3431ba` |
| Total files           | 7,383                                |
| JPEG tiles            | 7,380                                |
| JSON files            | 2 (`progress.json`, `_annotations.coco.json`) |
| TXT files             | 1 (`tiling_log.txt`)                 |
| Unique scans (local)  | 53                                   |
| Scans in COCO JSON    | 90 (includes tiles in sibling folder)|
| Pipeline              | RF-DETR Training Pipeline v1.0.0     |
| Processing time       | 43 seconds                           |
| Processed on          | 2026-04-19 15:41:04 - 15:41:47      |

---

## File Descriptions

### 1. JPEG Tiles (7,380 files)

Microscopic wafer inspection images cropped from larger scan frames.

**Filename format:**
```
{ScanID1}.{SiteID}.c.{Hash}.{Version}_x{X}_y{Y}_slot{SLOT}.jpeg
```

| Field   | Example             | Meaning                                         |
|---------|---------------------|-------------------------------------------------|
| ScanID1 | `26164`            | Primary scan/wafer identifier                   |
| SiteID  | `153740`           | Die/site index on the wafer                     |
| `c`     | `c`                 | Constant literal (crop marker)                  |
| Hash    | `928396196`        | Signed int32 content hash (can be negative)     |
| Version | `2`                | Revision number (1 or 2)                        |
| X       | `618`              | X pixel offset of tile in the source image      |
| Y       | `412`              | Y pixel offset of tile in the source image      |
| SLOT    | `10`               | Scanner slot (constant = 10 for all files)      |

**Tile grid parameters** (from `tiling_log.txt`):
- Tile size: **128 x 128** pixels
- Stride: **103 px** (overlap = 25 px)
- Grid: **14 columns x 10 rows = 140 tiles** per scan
- X positions: 0, 103, 206, 309, 412, 515, 618, 721, 824, 927, 1030, 1133, 1236, 1252
- Y positions: 0, 103, 206, 309, 412, 515, 618, 721, 824, 908

**Scan breakdown in this folder:**
- 52 complete scans (140 tiles each) = 7,280 tiles
- 1 partial scan (`26164.142498.c.-291707291.2`) = 100 tiles
- Total: **7,380 tiles**

---

### 2. `_annotations.coco.json` (COCO Format Annotation File)

The central metadata file linking all tiles to a defect detection dataset.

**Structure:**
```json
{
  "info": {},
  "licenses": [],
  "categories": [
    { "id": 1, "name": "Defect", "supercategory": "none" }
  ],
  "images": [
    { "id": 0, "file_name": "105639.33124...jpeg", "width": 128, "height": 128 },
    ...
  ],
  "annotations": []
}
```

| Field        | Content                                                     |
|--------------|-------------------------------------------------------------|
| categories   | 1 category: **"Defect"** (id=1)                            |
| images       | **13,860 entries** (12,600 unique + 1,260 duplicated y908)  |
| annotations  | **Empty list** (0 defect annotations - no labeled defects)  |
| Image IDs    | Sequential 0 - 13,859                                      |

**Key observations:**
- The COCO JSON catalogs **all 90 scans** (12,600 unique tiles), not just the 53 in this folder
- The 37 scans whose tiles reside in the sibling `after-crop/` folder are also indexed here
- The **bottom-edge row** (y=908) has **duplicate entries** (each tile listed twice with different IDs)
  - 90 scans x 14 x-positions = 1,260 duplicates
  - This is likely a tiling edge-case bug where the last row is generated from both the regular stride and the edge-clipping logic
- **Annotations are empty** - this is a freshly tiled dataset awaiting defect labeling

---

### 3. `tiling_log.txt` (Processing Log)

Full execution log of the tiling pipeline run.

**Key parameters extracted:**

| Parameter          | Value                                                                     |
|--------------------|---------------------------------------------------------------------------|
| tile_w / tile_h    | 128 x 128                                                                |
| overlap            | 25 (stride = 103)                                                        |
| chunk_size         | 1024                                                                      |
| num_workers        | 8                                                                         |
| slot_id            | 10                                                                        |
| clip_tiles_to_image| True                                                                      |
| use_masking        | Requested but **disabled** (masks folder not found)                       |
| use_support        | Requested but **disabled** (vcam_path missing)                            |
| scan_result_path   | `C:\AI.Service\...\DatasetSR\MTK-AHJ11236\setup1\lot\05`                |
| masks_dir          | `\media\ai-ubuntu\data3\PCMP_2.3um_VCAM\Hawk X10\masks\...\10`         |
| vcam_path          | `\media\ai-ubuntu\data3\...\KRHawk_HBM4eCMPx10_S10 - Scan 2D`          |
| mode               | `full_wafer` (images directly in split_dir)                               |
| Total frames       | 90                                                                        |
| Tiles written      | 13,860                                                                    |
| Original defects   | 0                                                                         |
| Processing time    | 43 seconds                                                                |

**Warnings/Errors:**
- `vcam_path` does not exist (Linux path on Windows machine) - support creation disabled
- masks folder not found - masking disabled

---

### 4. `progress.json` (Pipeline Progress Tracker)

Tracks the two-stage pipeline execution for UI/monitoring.

| Stage              | Weight | Status | Duration   |
|--------------------|--------|--------|------------|
| read_scan_results  | 30%    | done   | ~0 seconds |
| create_tiles       | 70%    | done   | 43 seconds |
| **Overall**        | 100%   | done   | 43 seconds |

---

## Relationship Between the Two Folders

The `b2de9dd1` folder and the sibling `after-crop/` folder are **parts of the same dataset**.

| Aspect                 | `b2de9dd1-...` folder   | `after-crop/` folder  | Combined      |
|------------------------|-------------------------|-----------------------|---------------|
| Unique scan IDs        | 53                      | 38                    | **90**        |
| JPEG tiles             | 7,380                   | 5,220                 | **12,600**    |
| Complete scans (140)   | 52                      | 37                    | 89            |
| Has COCO JSON          | Yes (master)            | No                    | -             |
| Has tiling_log.txt     | Yes                     | No                    | -             |
| Has progress.json      | Yes                     | No                    | -             |

**Shared scan:** `26164.142498.c.-291707291.2` exists in **both** folders but with
**non-overlapping tiles** that together form a complete 140-tile grid:

| Folder       | X positions                                          | Tiles |
|--------------|------------------------------------------------------|-------|
| after-crop   | 0, 103, 1030, 1133                                  | 40    |
| b2de9dd1     | 206, 309, 412, 515, 618, 721, 824, 927, 1236, 1252 | 100   |
| **Combined** | all 14 positions                                     | **140** |

---

## Data Relationship Diagram

```
+======================================================================================+
|                         DATA RELATIONSHIP DIAGRAM                                     |
|               RF-DETR Training Pipeline - Tiling Output                               |
+======================================================================================+

  +-----------------------------------------------------------------------+
  |                    SCAN SOURCE (Input)                                 |
  |  Path: C:\AI.Service\...\DatasetSR\MTK-AHJ11236\setup1\lot\05       |
  |  Product: MTK-AHJ11236 | Setup: 1 | Lot: 05                          |
  |  Mode: full_wafer | Slot: 10                                          |
  |  Total frames: 90 scan images                                         |
  +-----------------------------------+-----------------------------------+
                                      |
                          tiling pipeline (8 workers)
                          tile=128x128, stride=103, overlap=25
                                      |
                                      v
  +-----------------------------------------------------------------------+
  |              OUTPUT: b2de9dd1-1c90-4ce9-8414-2b3f5d3431ba             |
  |                                                                       |
  |  +--------------------+   +------------------+   +-----------------+  |
  |  | _annotations.      |   | tiling_log.txt   |   | progress.json   |  |
  |  | coco.json          |   |                  |   |                 |  |
  |  |                    |   | Pipeline args,   |   | Stage tracking: |  |
  |  | COCO dataset with: |   | warnings, stats  |   | read_scan (0s)  |  |
  |  | - 1 category       |   | - tile params    |   | create_tiles    |  |
  |  |   ("Defect")       |   | - 90 frames      |   |   (43s)         |  |
  |  | - 13,860 image     |   | - 13,860 tiles   |   | status: done    |  |
  |  |   entries           |   | - 0 defects      |   |                 |  |
  |  | - 0 annotations    |   |                  |   |                 |  |
  |  +--------+-----------+   +------------------+   +-----------------+  |
  |           |                                                           |
  |   references ALL 12,600 unique tiles                                  |
  |   (+ 1,260 duplicate y908 entries)                                    |
  |           |                                                           |
  |           +----+--------------------------------------------+         |
  |           |    |                                            |         |
  |           v    v                                            v         |
  |  +-----------------+                         +--------------------+   |
  |  | 7,380 JPEG      |                         | 5,220 JPEG tiles   |  |
  |  | tiles (local)   |                         | (in "after-crop/") |  |
  |  |                 |                         |                    |  |
  |  | 53 scan IDs     |                         | 38 scan IDs        |  |
  |  | 52 complete     |                         | 37 complete        |  |
  |  | 1 partial (100) |                         | 1 partial (40)     |  |
  |  +-----------------+                         +--------------------+   |
  |           |                                            |              |
  |           +--------- shared scan 26164.142498 --------+              |
  |                    (split: 100 + 40 = 140 tiles)                      |
  +-----------------------------------------------------------------------+


  DETAILED TILE STRUCTURE (per scan):
  
  Source scan image (~1380 x 1036 px)
  +---------+---------+---------+-- --+---------+---------+
  | x0,y0   | x103,y0 | x206,y0 |    |x1236,y0 |x1252,y0 |  <-- 14 columns
  | 128x128 | 128x128 | 128x128 |    | 128x128 | 128x128 |
  +---------+---------+---------+-- --+---------+---------+
  | x0,y103 | x103,   | x206,   |    |         |         |
  |         | y103    | y103    |    |         |         |
  +---------+---------+---------+-- --+---------+---------+
  :         :         :         :    :         :         :  <-- 10 rows
  +---------+---------+---------+-- --+---------+---------+
  | x0,y908 | x103,   | x206,   |    |x1236,   |x1252,   |
  |  (edge) | y908    | y908    |    | y908    | y908    |
  +---------+---------+---------+-- --+---------+---------+
                                                    ^
                            25px overlap between tiles
                            edge tiles (x1252, y908) shifted inward


  FILE CROSS-REFERENCES:
  
  _annotations.coco.json                    JPEG files
  ========================                  ==========
  
  images[0].file_name  ---- references ---> 105639...x0_y0_slot10.jpeg
  images[0].id = 0                          (128x128 px tile)
  images[0].width = 128
  images[0].height = 128
       |
       v
  annotations[] = empty                     No bounding box labels yet
  (awaiting defect labeling)                (dataset is unlabeled)
       |
       v
  categories[0] = "Defect"                  Single class for future labeling
  

  ENTITY RELATIONSHIPS:
  
  [Lot/Wafer MTK-AHJ11236]
       |
       +--1:N--> [90 Scan Frames]  (slot 10, full_wafer mode)
                      |
                      +--1:N--> [140 Tiles per scan]  (14x10 grid, 128x128 px)
                      |              |
                      |              +--1:1--> [JPEG File]
                      |              +--N:1--> [COCO images[] entry]
                      |
                      +--1:1--> [COCO images[] group]  (140 unique + 14 duplicate y908)
  
  [_annotations.coco.json]
       |
       +-- images[]      --1:1--> [JPEG file_name]  (12,600 unique tiles)
       +-- annotations[] --empty  (no labeled defects)
       +-- categories[]  --1-->   "Defect" class
  
  [tiling_log.txt]  -- documents --> pipeline parameters & execution stats
  [progress.json]   -- tracks    --> pipeline stage completion


  DATA SPLIT ACROSS FOLDERS:
  
  COCO JSON (13,860 entries = 12,600 unique)
  =============================================
  |                                           |
  |  53 scan IDs          37 scan IDs         |
  |  (7,380 tiles)        (5,180 tiles)       |
  |        |                    |              |
  |        v                    v              |
  |  b2de9dd1/ folder    "after-crop/" folder  |
  |                                           |
  |       1 scan ID split between both:        |
  |       26164.142498 (100 + 40 tiles)        |
  =============================================
  
  NOTE: The COCO JSON has a known issue where the bottom-edge
  row (y=908) is duplicated for all 90 scans, adding 1,260
  extra entries (13,860 total instead of 12,600 unique).
```

---

## Known Issues

1. **Duplicate y908 entries in COCO JSON** - Every scan's bottom-edge row (14 tiles at y=908)
   appears twice with different image IDs. This produces 13,860 total entries instead of 
   12,600 unique tiles. Likely caused by both regular-stride and edge-clipping logic
   generating the same tile.

2. **Missing Linux paths** - The `vcam_path` and `masks_dir` reference Linux mount points
   (`\media\ai-ubuntu\...`) that don't exist on the Windows machine where the pipeline ran.
   This disabled both masking and support tile creation.

3. **Split data across folders** - Tiles are distributed between `b2de9dd1/` and `after-crop/`
   with one scan (`26164.142498`) split between both. The COCO JSON in `b2de9dd1/` references
   all tiles from both locations.

4. **Empty annotations** - The dataset has 0 defect annotations (original defects: 0 from the
   scan results). The COCO JSON is a skeleton ready for future labeling.
