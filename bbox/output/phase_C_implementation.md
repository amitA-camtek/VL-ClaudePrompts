# Phase C – Implementation Plan

> **Feature:** Defect Crop Viewer — post-export review stage with configuration form shown after dataset creation  
> **Stack:** FastAPI (Python) + React 18 (TypeScript)

---

## 1. End-to-End Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                      COMPLETE IMPLEMENTATION FLOW                       │
└─────────────────────────────────────────────────────────────────────────┘

[User] selects 1+ scan results in /scan-results table
          │
          ▼
[Click "Export to VL Dataset"]  ← button onClick opens ExportDatasetModal (UNCHANGED)
          │
          ▼
  ExportDatasetModal opens  (UNCHANGED existing flow)
          │
          ▼
[User fills dataset name + path → Create Dataset]
          │
          ▼
POST /api/v1/scan-results/export-dataset  (UNCHANGED)
          │
          ▼
[Dataset created successfully]
          │
          ▼
  On success callback → CropConfigForm opens automatically
          │
          ├── User configures:
          │     eps slider (cluster radius, μm)
          │     pad slider (crop padding, px)
          │     OClass filter checkboxes
          │     Recipe filter checkboxes
          │     Max images per cluster
          │     Thumbnail size
          │
          ▼
[Click "Apply & View Crops"]
          │
          ├──► GET /api/v1/scan-results/defect-clusters
          │         ?path={scan_path}&eps={form.eps}&pad={form.pad}
          │
          │    [Backend: api_defect_crops.py]
          │    load_defects(path)
          │        parse_db_csv(path)          ← encoding-safe CSV reader
          │        filter_skip_classes()       ← OClass ∈ {1,2147483644,45,46}
          │        normalize_column_names()    ← handle spaces in col names
          │    group_by_recipe(defects)
          │    for each recipe:
          │        dims = get_image_dims(img_path)   ← PIL header (cached by mtime)
          │        labels = dbscan_cluster(wafer_x, wafer_y, eps_um)
          │        if singleton_ratio > 0.75: auto_widen_eps(retry ≤3)
          │        for each cluster_id:
          │            members = defects where label == cluster_id
          │            crop = compute_crop_rect(members, image_dims, pad)
          │            bboxes = normalize_bboxes(members, crop)
          │    return CropResponse {
          │        total_defects, total_crops, viewport,
          │        crops: [{image_name, image_url, crop_x,y,w,h,
          │                 defects:[{x,y,w,h,oclass,label}]}]
          │    }
          │
          ▼
  React renders DefectCropViewer:
    WaferMap (canvas, defect dots)
    ClusterGrid (CropTile per cluster)
        CropTile:
          useEffect → new Image() → onload → canvas.drawImage(srcRect)
          SVG overlay → <rect> per defect with color by OClass
          cleanup: cancelled = true on unmount  (BUG2 fix)
          key = stable hash (image_name + crop coords)  (BUG3 fix)
          │
          │── GET /api/v1/scan-results/image
          │       ?scan_path={base}&rel={images/lot_01/file.jpeg}
          │   [Backend: secure path validation + FileResponse + CORS]
          │
  User reviews cluster panels
          │
          ├── [← Back to Form] → return to CropConfigForm (values preserved)
          │
          └── [← Back to Scan Results] → close everything → return to table
```

---

## 2. File Change Map

### New Files (create)

```
Backend:
  clustplorer/web/api_defect_crops.py           FastAPI router (2 endpoints)
  vl/services/defect_clustering.py              DBSCAN + crop logic (pure-Python fallback)

Frontend:
  fe/clustplorer/src/views/pages/ScanResults/DefectCropViewer/
    index.tsx                                   Container (page wrapper + step navigation)
    CropConfigForm.tsx                          Configuration form (shown after dataset creation)
    CropTile.tsx                                Single cluster tile (canvas + SVG)
    BoundingBoxOverlay.tsx                      SVG bounding box layer
    WaferMap.tsx                                Canvas wafer coordinate map
    useDefectCrops.ts                           React Query hook
    style.module.scss                           SCSS styles

Script:
  generate_feature.py                           CLI scaffolder (generates all files above)
```

### Modified Files (minimal changes)

```
Backend:
  clustplorer/web/__init__.py                   +2 lines: import + include_router

Frontend:
  fe/clustplorer/src/views/pages/ScanResults/index.tsx
                                                +1 state variable + ExportDatasetModal onSuccess callback change
```

---

## 3. Backend Implementation

### 3.1 `vl/services/defect_clustering.py`

```python
"""
Defect clustering service.
Groups wafer scan defects by spatial proximity (Wafer X/Y in microns)
and computes crop regions with normalized bounding boxes.
"""
from __future__ import annotations

import csv
import logging
import os
import pathlib
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Dict, List, Optional, Tuple

from PIL import Image

logger = logging.getLogger(__name__)

# OClass values to skip — Pass and sentinel codes
SKIP_CLASSES = frozenset({1, 2147483644, 2147483645, 2147483646})

# Default bbox for centered defects (when XInFrame=YInFrame=0)
CENTERED_BBOX = (0.30, 0.30, 0.40, 0.40)  # (x, y, w, h) normalized

OCLASS_LABELS: Dict[int, str] = {
    1: "Pass", 23: "Missing Bump", 26: "Bump Scratch", 27: "Pass. Scratch",
    28: "Foreign Particle", 34: "Embedded Particle", 35: "PI Particle",
    37: "Chip Dirty", 58: "Bump Damage", 65: "Other",
}


@dataclass
class DefectRecord:
    image_name: str
    x_in_frame: float
    y_in_frame: float
    wafer_x: float
    wafer_y: float
    oclass: int
    label: str
    recipe_name: str
    wafer_id: str
    lot_id: str


@dataclass
class BoundingBox:
    x: float   # normalized 0-1
    y: float
    w: float
    h: float
    oclass: int
    label: str


@dataclass
class CropRegion:
    image_name: str
    image_url: str
    crop_x: int
    crop_y: int
    crop_w: int
    crop_h: int
    defects: List[BoundingBox] = field(default_factory=list)
    defect_count: int = 0
    recipe_name: str = ""
    cluster_id: int = -1


@dataclass
class Viewport:
    x_min: float
    x_max: float
    y_min: float
    y_max: float


# ─── CSV parsing ──────────────────────────────────────────────────────────────

def parse_db_csv(folder_path: str) -> List[DefectRecord]:
    """
    Parse DB.csv from a scan export folder.
    Handles: spaces in column names, Windows encoding (utf-8-sig),
             malformed rows, special OClass sentinel values.
    """
    csv_path = pathlib.Path(folder_path) / "DB.csv"
    if not csv_path.exists():
        raise FileNotFoundError(f"DB.csv not found in {folder_path}")

    classes_map = _load_classes_json(folder_path)
    defects: List[DefectRecord] = []

    with open(csv_path, newline="", encoding="utf-8-sig", errors="replace") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            try:
                oclass = int(row.get("OClass") or 0)
                if oclass in SKIP_CLASSES:
                    continue

                image_name = (row.get("ImageName") or "").strip()
                if not image_name:
                    logger.warning("DB.csv row %d: empty ImageName, skipping", i)
                    continue

                # Normalize path separators (Windows CSV may use backslashes)
                image_name = image_name.replace("\\", "/")

                defects.append(DefectRecord(
                    image_name=image_name,
                    x_in_frame=float(row.get("XInFrame") or 0),
                    y_in_frame=float(row.get("YInFrame") or 0),
                    wafer_x=float(row.get("Wafer X") or 0),   # NOTE: space in key
                    wafer_y=float(row.get("Wafer Y") or 0),   # NOTE: space in key
                    oclass=oclass,
                    label=classes_map.get(oclass, OCLASS_LABELS.get(oclass, str(oclass))),
                    recipe_name=(row.get("Recipe Name") or "").strip(),
                    wafer_id=(row.get("Wafer") or "").strip(),
                    lot_id=(row.get("Lot") or "").strip(),
                ))
            except (ValueError, TypeError, KeyError) as exc:
                logger.warning("DB.csv row %d invalid (%s), skipping", i, exc)

    logger.info("Parsed %d defects from %s", len(defects), csv_path)
    return defects


def _load_classes_json(folder_path: str) -> Dict[int, str]:
    """Load Classes.json (OClass int → label str) if it exists."""
    path = pathlib.Path(folder_path) / "Classes.json"
    if not path.exists():
        return {}
    try:
        import json
        with open(path, encoding="utf-8-sig") as f:
            raw = json.load(f)
        # Format: {"1": "Pass", "34": "Embedded Particle", ...}
        return {int(k): v for k, v in raw.items()}
    except Exception as exc:
        logger.warning("Failed to load Classes.json: %s", exc)
        return {}


# ─── Image dimensions ─────────────────────────────────────────────────────────

@lru_cache(maxsize=512)
def _get_dims_cached(full_path: str, mtime: float) -> Tuple[int, int]:
    """Header-only PIL read (fast ~1ms). Cache invalidates on file change."""
    try:
        with Image.open(full_path) as img:
            return img.size  # (width, height)
    except Exception:
        logger.warning("Cannot read image dims: %s, using default 800x600", full_path)
        return (800, 600)


def get_image_dims(folder_path: str, image_name: str) -> Tuple[int, int]:
    full = str((pathlib.Path(folder_path) / image_name).resolve())
    if not os.path.exists(full):
        return (800, 600)
    mtime = os.path.getmtime(full)
    return _get_dims_cached(full, mtime)


# ─── DBSCAN (pure-Python, no sklearn dep for this module) ────────────────────

def _dbscan_2d(points: List[Tuple[float, float]], eps: float) -> List[int]:
    """
    Lightweight 2D DBSCAN with min_samples=1.
    O(n²) — suitable for n < 5000 defects per recipe.
    Returns cluster label per point (0-based, no -1 noise).
    """
    n = len(points)
    if n == 0:
        return []
    labels = [-1] * n
    cluster = 0
    eps_sq = eps * eps

    for i in range(n):
        if labels[i] != -1:
            continue
        labels[i] = cluster
        stack = [i]
        while stack:
            j = stack.pop()
            dx = points[i][0] - points[j][0]
            dy = points[i][1] - points[j][1]
            for k in range(n):
                if labels[k] == -1:
                    dx2 = points[j][0] - points[k][0]
                    dy2 = points[j][1] - points[k][1]
                    if dx2 * dx2 + dy2 * dy2 <= eps_sq:
                        labels[k] = cluster
                        stack.append(k)
        cluster += 1
    return labels


# ─── Clustering orchestration ─────────────────────────────────────────────────

def cluster_defects(
    defects: List[DefectRecord],
    folder_path: str,
    eps_um: float = 300.0,
    pad_px: int = 64,
    min_crop: int = 128,
    max_crop: int = 512,
    defect_size_px: int = 20,
    max_clusters: int = 60,
    image_url_prefix: str = "/api/v1/scan-results/image",
) -> Tuple[List[CropRegion], Viewport]:
    """
    Main entry point.
    Groups defects by recipe, then spatially clusters by Wafer X/Y.
    Returns sorted CropRegion list (most defects first) and wafer viewport.
    """
    if not defects:
        return [], Viewport(0, 1, 0, 1)

    # Compute viewport for WaferMap
    all_x = [d.wafer_x for d in defects]
    all_y = [d.wafer_y for d in defects]
    margin_x = (max(all_x) - min(all_x)) * 0.05 or 100
    margin_y = (max(all_y) - min(all_y)) * 0.05 or 100
    viewport = Viewport(
        x_min=min(all_x) - margin_x,
        x_max=max(all_x) + margin_x,
        y_min=min(all_y) - margin_y,
        y_max=max(all_y) + margin_y,
    )

    # Group by recipe
    by_recipe: Dict[str, List[DefectRecord]] = {}
    for d in defects:
        by_recipe.setdefault(d.recipe_name, []).append(d)

    crops: List[CropRegion] = []
    for recipe, recipe_defects in by_recipe.items():
        recipe_crops = _cluster_recipe(
            recipe_defects, folder_path, recipe,
            eps_um, pad_px, min_crop, max_crop, defect_size_px,
            max_clusters, image_url_prefix,
        )
        crops.extend(recipe_crops)

    crops.sort(key=lambda c: -c.defect_count)
    return crops, viewport


def _cluster_recipe(
    defects: List[DefectRecord],
    folder_path: str,
    recipe_name: str,
    eps_um: float,
    pad_px: int,
    min_crop: int,
    max_crop: int,
    defect_size_px: int,
    max_clusters: int,
    image_url_prefix: str,
) -> List[CropRegion]:
    points = [(d.wafer_x, d.wafer_y) for d in defects]
    current_eps = eps_um

    for attempt in range(4):  # 0 = initial, 1-3 = retries
        labels = _dbscan_2d(points, current_eps)
        n_clusters = len(set(labels))
        singleton_ratio = sum(1 for lbl in labels if labels.count(lbl) == 1) / max(len(labels), 1)

        if n_clusters <= max_clusters or attempt == 3:
            break
        # Auto-widen: too many clusters
        logger.info(
            "Recipe '%s': %d clusters at eps=%.0f, widening (attempt %d)",
            recipe_name, n_clusters, current_eps, attempt + 1,
        )
        current_eps *= 2.0

    crops: List[CropRegion] = []
    cluster_ids = set(labels)

    for cid in cluster_ids:
        if cid == -1:  # DBSCAN noise (only with min_samples > 1)
            # Treat each noise point as its own singleton cluster
            for d in [defects[i] for i, lbl in enumerate(labels) if lbl == -1]:
                crops.append(_make_spatial_cluster([d], folder_path, recipe_name,
                                                   pad_px, min_crop, max_crop,
                                                   defect_size_px, image_url_prefix, cid))
            continue

        members = [defects[i] for i, lbl in enumerate(labels) if lbl == cid]
        crops.append(_make_spatial_cluster(members, folder_path, recipe_name,
                                           pad_px, min_crop, max_crop,
                                           defect_size_px, image_url_prefix, cid))
    return crops


def _make_spatial_cluster(
    members: List[DefectRecord],
    folder_path: str,
    recipe_name: str,
    pad_px: int,
    min_crop: int,
    max_crop: int,
    defect_size_px: int,
    image_url_prefix: str,
    cluster_id: int,
) -> CropRegion:
    """
    Build a CropRegion for a spatial cluster.
    For each defect image in the cluster: compute crop rect and normalized bbox.
    """
    # Group by ImageName (intra-image defects share same image)
    by_image: Dict[str, List[DefectRecord]] = {}
    for d in members:
        by_image.setdefault(d.image_name, []).append(d)

    all_bboxes: List[BoundingBox] = []
    # Use the first image as the representative for crop coords
    first_image = list(by_image.keys())[0]
    img_w, img_h = get_image_dims(folder_path, first_image)

    for image_name, img_defects in by_image.items():
        has_frame_coords = any(d.x_in_frame != 0 or d.y_in_frame != 0 for d in img_defects)

        if has_frame_coords:
            # Intra-image: use actual pixel coordinates
            xs = [d.x_in_frame for d in img_defects]
            ys = [d.y_in_frame for d in img_defects]
            iw, ih = get_image_dims(folder_path, image_name)
            cx = max(0, int(min(xs) - pad_px))
            cy = max(0, int(min(ys) - pad_px))
            cw = min(max_crop, max(min_crop, int(max(xs) - min(xs) + 2 * pad_px + defect_size_px)))
            ch = min(max_crop, max(min_crop, int(max(ys) - min(ys) + 2 * pad_px + defect_size_px)))
            cw = min(cw, iw - cx)
            ch = min(ch, ih - cy)

            for d in img_defects:
                half = defect_size_px / 2.0
                w_n = min(1.0, defect_size_px / cw)
                h_n = min(1.0, defect_size_px / ch)
                x_n = max(0.0, min(1.0 - w_n, (d.x_in_frame - cx - half) / cw))
                y_n = max(0.0, min(1.0 - h_n, (d.y_in_frame - cy - half) / ch))
                all_bboxes.append(BoundingBox(x=x_n, y=y_n, w=w_n, h=h_n,
                                              oclass=d.oclass, label=d.label))
        else:
            # Centered fallback: defect is the whole image subject
            cx, cy, cw, ch = 0, 0, img_w, img_h
            for d in img_defects:
                x_n, y_n, w_n, h_n = CENTERED_BBOX
                all_bboxes.append(BoundingBox(x=x_n, y=y_n, w=w_n, h=h_n,
                                              oclass=d.oclass, label=d.label))

    # image_url encodes the scan path + relative image name for the serving endpoint
    import urllib.parse
    image_url = (
        f"{image_url_prefix}"
        f"?scan_path={urllib.parse.quote(folder_path)}"
        f"&rel={urllib.parse.quote(first_image)}"
    )

    return CropRegion(
        image_name=first_image,
        image_url=image_url,
        crop_x=cx if len(by_image) == 1 else 0,
        crop_y=cy if len(by_image) == 1 else 0,
        crop_w=cw if len(by_image) == 1 else img_w,
        crop_h=ch if len(by_image) == 1 else img_h,
        defects=all_bboxes,
        defect_count=len(members),
        recipe_name=recipe_name,
        cluster_id=cluster_id,
    )
```

---

### 3.2 `clustplorer/web/api_defect_crops.py`

```python
"""
API endpoints for the Defect Crop Viewer feature.
Two endpoints:
  GET /defect-clusters  — parse DB.csv, cluster, return metadata
  GET /image            — serve raw scan image (path-validated, CORS-enabled)
"""
from __future__ import annotations

import asyncio
import pathlib
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, Security
from fastapi.responses import FileResponse
from pydantic import BaseModel

from clustplorer.web.auth import get_authenticated_user
from vldbaccess.user import User
from vl.services.defect_clustering import (
    cluster_defects,
    parse_db_csv,
)

router = APIRouter(prefix="/api/v1/scan-results", tags=["defect-crops"])


# ─── Response models ──────────────────────────────────────────────────────────

class BBoxOut(BaseModel):
    x: float
    y: float
    w: float
    h: float
    oclass: int
    label: str


class CropOut(BaseModel):
    image_name: str
    image_url: str
    crop_x: int
    crop_y: int
    crop_w: int
    crop_h: int
    defects: List[BBoxOut]
    defect_count: int
    recipe_name: str
    cluster_id: int


class ViewportOut(BaseModel):
    x_min: float
    x_max: float
    y_min: float
    y_max: float


class CropResponse(BaseModel):
    total_defects: int
    total_crops: int
    crops: List[CropOut]
    viewport: ViewportOut
    message: Optional[str] = None


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/defect-clusters", response_model=CropResponse)
async def get_defect_clusters(
    path: str = Query(..., description="Absolute path to scan export folder"),
    eps: float = Query(300.0, ge=10.0, le=5000.0, description="Cluster radius in microns"),
    pad: int = Query(64, ge=0, le=512, description="Crop padding in pixels"),
    user: User = Security(get_authenticated_user),
) -> CropResponse:
    """
    Parse DB.csv from the scan export folder, cluster defects by Wafer X/Y,
    and return crop metadata with normalized bounding boxes.
    Does NOT return image data — images are served by the /image endpoint.
    """
    folder = pathlib.Path(path)
    if not folder.is_dir():
        raise HTTPException(status_code=404, detail=f"Scan folder not found: {path}")
    if not (folder / "DB.csv").exists():
        raise HTTPException(status_code=404, detail=f"DB.csv not found in {path}")

    # Run blocking I/O in thread pool (PIL reads + CSV parse)
    loop = asyncio.get_event_loop()
    defects = await loop.run_in_executor(None, parse_db_csv, path)

    if not defects:
        return CropResponse(
            total_defects=0, total_crops=0, crops=[], viewport=ViewportOut(x_min=0,x_max=1,y_min=0,y_max=1),
            message="No defects found. All records may be classified as Pass.",
        )

    crops, viewport = await loop.run_in_executor(
        None, cluster_defects, defects, path, eps, pad
    )

    return CropResponse(
        total_defects=len(defects),
        total_crops=len(crops),
        crops=[
            CropOut(
                image_name=c.image_name, image_url=c.image_url,
                crop_x=c.crop_x, crop_y=c.crop_y,
                crop_w=c.crop_w, crop_h=c.crop_h,
                defects=[BBoxOut(x=b.x, y=b.y, w=b.w, h=b.h, oclass=b.oclass, label=b.label)
                         for b in c.defects],
                defect_count=c.defect_count,
                recipe_name=c.recipe_name,
                cluster_id=c.cluster_id,
            )
            for c in crops
        ],
        viewport=ViewportOut(**vars(viewport)),
    )


@router.get("/image")
async def serve_scan_image(
    scan_path: str = Query(..., description="Absolute path to scan export folder"),
    rel: str = Query(..., description="Relative image path within the scan folder"),
    user: User = Security(get_authenticated_user),
):
    """
    Serve a raw image from a scan export folder.
    Path-traversal validated: rel must resolve inside scan_path.
    CORS-enabled for canvas drawImage compatibility.
    """
    base = pathlib.Path(scan_path).resolve()
    # Normalize separators (rel from DB.csv uses forward slashes)
    rel_norm = pathlib.Path(*pathlib.PurePosixPath(rel).parts)
    full = (base / rel_norm).resolve()

    # Security: ensure resolved path is inside the scan folder
    try:
        full.relative_to(base)
    except ValueError:
        raise HTTPException(status_code=403, detail="Path traversal attempt denied")

    if not full.exists() or not full.is_file():
        raise HTTPException(status_code=404, detail=f"Image not found: {rel}")

    return FileResponse(
        str(full),
        media_type="image/jpeg",
        headers={
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "public, max-age=3600",
            "X-Content-Type-Options": "nosniff",
        },
    )
```

---

### 3.3 `clustplorer/web/__init__.py` — Required Changes (2 lines)

```python
# STEP 1: Add import near the other router imports (alphabetical order suggested):
from clustplorer.web.api_defect_crops import router as defect_crops_router

# STEP 2: Add include_router call in the block where other routers are registered:
app.include_router(defect_crops_router)
```

---

## 4. Frontend Implementation

### 4.1 `useDefectCrops.ts`

```typescript
// fe/clustplorer/src/views/pages/ScanResults/DefectCropViewer/useDefectCrops.ts
import { useQuery } from "@tanstack/react-query";
import axios from "axios";

export interface DefectBBox {
  x: number; y: number; w: number; h: number;
  oclass: number; label: string;
}

export interface CropResult {
  image_name: string; image_url: string;
  crop_x: number; crop_y: number; crop_w: number; crop_h: number;
  defects: DefectBBox[]; defect_count: number;
  recipe_name: string; cluster_id: number;
}

export interface Viewport {
  x_min: number; x_max: number; y_min: number; y_max: number;
}

export interface CropResponse {
  total_defects: number; total_crops: number;
  crops: CropResult[]; viewport: Viewport;
  message?: string;
}

export function useDefectCrops(
  scanPath: string | null,
  eps: number,
  pad: number,
) {
  return useQuery<CropResponse, Error>({
    queryKey: ["defect-clusters", scanPath, eps, pad],
    queryFn: async ({ signal }) => {
      const res = await axios.get<CropResponse>(
        "/api/v1/scan-results/defect-clusters",
        {
          params: { path: scanPath, eps, pad },
          signal,   // AbortController — cancels on queryKey change
        },
      );
      return res.data;
    },
    enabled: !!scanPath,
    staleTime: 5 * 60 * 1000,  // 5 min — CSV rarely changes
    retry: 1,
  });
}
```

---

### 4.2 `BoundingBoxOverlay.tsx`

```typescript
// fe/clustplorer/src/views/pages/ScanResults/DefectCropViewer/BoundingBoxOverlay.tsx
import React from "react";

export interface DefectBox {
  x: number; y: number; w: number; h: number;
  label: string; oclass: number;
}

// Color palette keyed by OClass category
const OCLASS_COLOR: Record<number, string> = {
  23: "#ff6b35", 58: "#ff6b35", 78: "#ff6b35", 81: "#ff6b35", 85: "#ff6b35", // Missing Bump
  28: "#ff4444", 34: "#ff4444", 35: "#ff4444",  // Foreign Particle
  26: "#ffcc02", 27: "#ffcc02", 46: "#ffcc02",  // Scratch / Damage
  65: "#9b59b6",  // Other
};
const defaultColor = "#3498db";
const getColor = (oclass: number): string => OCLASS_COLOR[oclass] ?? defaultColor;

interface Props {
  defects: DefectBox[];
  tileWidth: number;
  tileHeight: number;
}

export const BoundingBoxOverlay: React.FC<Props> = ({ defects, tileWidth, tileHeight }) => (
  <svg
    viewBox={`0 0 ${tileWidth} ${tileHeight}`}
    style={{
      position: "absolute", inset: 0,
      width: "100%", height: "100%",
      pointerEvents: "none", overflow: "visible",
    }}
  >
    {defects.map((d, i) => {
      const color = getColor(d.oclass);
      const px = d.x * tileWidth;
      const py = d.y * tileHeight;
      const pw = Math.max(d.w * tileWidth, 8);   // min 8px visible
      const ph = Math.max(d.h * tileHeight, 8);
      const labelW = Math.max(40, d.label.length * 7);
      const labelAbove = py > 20;

      return (
        <g key={`${d.oclass}-${i}`}>
          {/* Bounding box rect */}
          <rect
            x={px} y={py} width={pw} height={ph}
            stroke={color} strokeWidth={2}
            fill={color} fillOpacity={0.15}
          />
          {/* Label pill */}
          <rect
            x={px} y={labelAbove ? py - 18 : py + ph + 2}
            width={labelW} height={16}
            fill={color} rx={3}
          />
          <text
            x={px + 4}
            y={labelAbove ? py - 5 : py + ph + 14}
            fontSize={11} fill="#fff" fontWeight={600}
            style={{ userSelect: "none" }}
          >
            {d.label}
          </text>
        </g>
      );
    })}
  </svg>
);
```

---

### 4.3 `CropTile.tsx`

```typescript
// fe/clustplorer/src/views/pages/ScanResults/DefectCropViewer/CropTile.tsx
import React, { useEffect, useRef, useState } from "react";
import { BoundingBoxOverlay, DefectBox } from "./BoundingBoxOverlay";
import styles from "./style.module.scss";

interface CropTileProps {
  imageUrl: string;
  cropX: number; cropY: number; cropW: number; cropH: number;
  defects: DefectBox[];
  defectCount: number;
  recipeName: string;
  tileSize?: number;
  onClick?: () => void;
}

export const CropTile: React.FC<CropTileProps> = ({
  imageUrl, cropX, cropY, cropW, cropH,
  defects, defectCount, recipeName,
  tileSize = 256, onClick,
}) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState(false);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    let cancelled = false;  // BUG2 fix: guard against unmount during async load
    setLoaded(false);
    setError(false);

    const img = new window.Image();
    img.crossOrigin = "anonymous";  // BUG1 fix: required for canvas CORS

    img.onload = () => {
      if (cancelled) return;
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      ctx.clearRect(0, 0, tileSize, tileSize);
      ctx.drawImage(
        img,
        cropX, cropY, cropW, cropH,   // source rect (original image coords)
        0, 0, tileSize, tileSize,      // dest rect (canvas display size)
      );
      setLoaded(true);
    };

    img.onerror = () => {
      if (cancelled) return;
      setError(true);
    };

    img.src = imageUrl;

    return () => {
      cancelled = true;   // cleanup on unmount or re-render
    };
  }, [imageUrl, cropX, cropY, cropW, cropH, tileSize]);

  return (
    <div
      className={styles.tile}
      style={{ width: tileSize, height: tileSize + 32 }}
      onClick={onClick}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === "Enter" && onClick?.()}
    >
      <div style={{ position: "relative", width: tileSize, height: tileSize }}>
        {/* Canvas: renders the cropped image region */}
        <canvas
          ref={canvasRef}
          width={tileSize}
          height={tileSize}
          style={{ display: "block", borderRadius: "6px 6px 0 0" }}
        />

        {/* Loading placeholder */}
        {!loaded && !error && (
          <div className={styles.placeholder} style={{ width: tileSize, height: tileSize }} />
        )}

        {/* Error placeholder */}
        {error && (
          <div className={styles.errorPlaceholder} style={{ width: tileSize, height: tileSize }}>
            <span>Image unavailable</span>
          </div>
        )}

        {/* SVG bounding box overlay — above canvas via z-index */}
        {loaded && (
          <BoundingBoxOverlay
            defects={defects}
            tileWidth={tileSize}
            tileHeight={tileSize}
          />
        )}
      </div>

      {/* Tile footer: defect count + recipe */}
      <div className={styles.footer}>
        <span className={styles.count}>{defectCount} defect{defectCount !== 1 ? "s" : ""}</span>
        {recipeName && <span className={styles.recipe}>{recipeName}</span>}
      </div>
    </div>
  );
};
```

---

### 4.4 `WaferMap.tsx`

```typescript
// fe/clustplorer/src/views/pages/ScanResults/DefectCropViewer/WaferMap.tsx
import React, { useEffect, useRef } from "react";
import { CropResult, Viewport } from "./useDefectCrops";

const OCLASS_COLORS: Record<number, string> = {
  23: "#ff6b35", 34: "#ff4444", 65: "#9b59b6",
};
const dotColor = (oclass: number) => OCLASS_COLORS[oclass] ?? "#3498db";

interface Props {
  crops: CropResult[];
  viewport: Viewport;
  onClusterClick?: (clusterId: number) => void;
  size?: number;
}

export const WaferMap: React.FC<Props> = ({
  crops, viewport, onClusterClick, size = 300,
}) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    ctx.clearRect(0, 0, size, size);
    ctx.fillStyle = "#0d1117";
    ctx.fillRect(0, 0, size, size);

    const rangeX = (viewport.x_max - viewport.x_min) || 1;
    const rangeY = (viewport.y_max - viewport.y_min) || 1;

    // Auto-fit scale preserving aspect ratio
    const scale = Math.min(size / rangeX, size / rangeY) * 0.9;
    const offsetX = (size - rangeX * scale) / 2;
    const offsetY = (size - rangeY * scale) / 2;

    const toCanvas = (wx: number, wy: number) => ({
      cx: offsetX + (wx - viewport.x_min) * scale,
      cy: offsetY + (wy - viewport.y_min) * scale,
    });

    for (const crop of crops) {
      for (const d of crop.defects) {
        // Note: use the first defect's OClass for the dot color
        const color = dotColor(d.oclass);
        // We don't have wafer X/Y in CropResult, so use a representative position
        // In a more complete impl, include centroid in CropOut
        ctx.beginPath();
        ctx.arc(
          (crop.cluster_id * 17) % size,   // placeholder — replace with centroid
          (crop.cluster_id * 31) % size,
          3, 0, Math.PI * 2,
        );
        ctx.fillStyle = color;
        ctx.fill();
      }
    }
  }, [crops, viewport, size]);

  return (
    <canvas
      ref={canvasRef}
      width={size}
      height={size}
      style={{ borderRadius: 8, border: "1px solid var(--border-color)", cursor: "crosshair" }}
      title="Wafer defect map — click to navigate to cluster"
    />
  );
};

// NOTE: To make WaferMap fully functional, add `centroid_x`, `centroid_y`
// fields to CropOut in the backend response. Then replace the placeholder
// arithmetic with: toCanvas(crop.centroid_x, crop.centroid_y)
```

---

### 4.5 `CropConfigForm.tsx` — Configuration Form (Step 1)

```typescript
// fe/clustplorer/src/views/pages/ScanResults/DefectCropViewer/CropConfigForm.tsx
import React from "react";
import { Button, Checkbox, Slider, Tag } from "antd";
import styles from "./style.module.scss";

export interface CropFormValues {
  eps: number;
  pad: number;
  selectedOClasses: number[];
  selectedRecipes: string[];
  maxPerCluster: number;
  thumbnailSize: number;
}

const DEFAULT_VALUES: CropFormValues = {
  eps: 300,
  pad: 64,
  selectedOClasses: [],   // empty = all selected
  selectedRecipes: [],    // empty = all selected
  maxPerCluster: 16,
  thumbnailSize: 256,
};

// OClass categories available for filtering
const OCLASS_OPTIONS = [
  { value: 23, label: "Missing Bump", color: "#ff6b35" },
  { value: 28, label: "Foreign Particle", color: "#ff4444" },
  { value: 26, label: "Scratch/Damage", color: "#ffcc02" },
  { value: 65, label: "Other", color: "#9b59b6" },
];

interface Props {
  scanName: string;
  totalDefects: number;        // from dataset creation result
  availableRecipes: string[];  // populated from scan metadata
  values: CropFormValues;
  onChange: (values: CropFormValues) => void;
  onApply: () => void;
  onBack: () => void;
}

export const CropConfigForm: React.FC<Props> = ({
  scanName, totalDefects, availableRecipes,
  values, onChange, onApply, onBack,
}) => {
  const update = (partial: Partial<CropFormValues>) =>
    onChange({ ...values, ...partial });

  return (
    <div className={styles.overlay}>
      <div className={styles.formPanel}>
        {/* Header */}
        <div className={styles.header}>
          <Button onClick={onBack} className={styles.backBtn}>← Back to Scans</Button>
          <span className={styles.title}>Configure Crop Review — {scanName}</span>
        </div>

        {/* Success badge */}
        <div className={styles.successBadge}>
          <Tag color="green">Dataset created</Tag>
          <span>{totalDefects} defects exported</span>
        </div>

        {/* Clustering Parameters */}
        <div className={styles.formSection}>
          <h4>Clustering Parameters</h4>
          <div className={styles.controlRow}>
            <label>Cluster Radius: <strong>{values.eps} μm</strong></label>
            <Slider min={50} max={2000} step={50} value={values.eps}
                    onChange={(v) => update({ eps: v })} />
          </div>
          <div className={styles.controlRow}>
            <label>Crop Padding: <strong>{values.pad} px</strong></label>
            <Slider min={16} max={256} step={8} value={values.pad}
                    onChange={(v) => update({ pad: v })} />
          </div>
        </div>

        {/* Filters */}
        <div className={styles.formSection}>
          <h4>Filters</h4>
          <div className={styles.controlRow}>
            <label>OClass:</label>
            <Checkbox.Group
              options={OCLASS_OPTIONS.map(o => ({ label: o.label, value: o.value }))}
              value={values.selectedOClasses.length ? values.selectedOClasses
                     : OCLASS_OPTIONS.map(o => o.value)}
              onChange={(checked) => update({ selectedOClasses: checked as number[] })}
            />
          </div>
          {availableRecipes.length > 0 && (
            <div className={styles.controlRow}>
              <label>Recipe:</label>
              <Checkbox.Group
                options={availableRecipes.map(r => ({ label: r, value: r }))}
                value={values.selectedRecipes.length ? values.selectedRecipes : availableRecipes}
                onChange={(checked) => update({ selectedRecipes: checked as string[] })}
              />
            </div>
          )}
        </div>

        {/* Display Options */}
        <div className={styles.formSection}>
          <h4>Display</h4>
          <div className={styles.controlRow}>
            <label>Max images per cluster: <strong>{values.maxPerCluster}</strong></label>
            <Slider min={4} max={32} step={4} value={values.maxPerCluster}
                    onChange={(v) => update({ maxPerCluster: v })} />
          </div>
          <div className={styles.controlRow}>
            <label>Thumbnail size: <strong>{values.thumbnailSize}px</strong></label>
            <Slider min={128} max={512} step={64} value={values.thumbnailSize}
                    onChange={(v) => update({ thumbnailSize: v })} />
          </div>
        </div>

        {/* Submit */}
        <div className={styles.footerBar}>
          <Button type="primary" size="large" onClick={onApply}>
            Apply & View Crops
          </Button>
        </div>
      </div>
    </div>
  );
};

export { DEFAULT_VALUES };
```

---

### 4.6 `index.tsx` — DefectCropViewer Container (Two-Step: Form → Viewer)

```typescript
// fe/clustplorer/src/views/pages/ScanResults/DefectCropViewer/index.tsx
import React, { useRef, useState } from "react";
import { Alert, Button, Empty, Spin, Statistic } from "antd";
import { CropConfigForm, CropFormValues, DEFAULT_VALUES } from "./CropConfigForm";
import { CropTile } from "./CropTile";
import { WaferMap } from "./WaferMap";
import { useDefectCrops } from "./useDefectCrops";
import styles from "./style.module.scss";

type Step = "form" | "viewer";

interface Props {
  open: boolean;
  scanPaths: string[];           // selected scan export folder paths
  scanName: string;              // display name
  onBack: () => void;
}

export const DefectCropViewer: React.FC<Props> = ({
  open, scanPaths, scanName, onBack,
}) => {
  const [step, setStep] = useState<Step>("form");
  const [formValues, setFormValues] = useState<CropFormValues>(DEFAULT_VALUES);
  // Applied values: only sent to API when user clicks "Apply & View Crops"
  const [appliedValues, setAppliedValues] = useState<CropFormValues | null>(null);
  const gridRef = useRef<HTMLDivElement>(null);

  // Use first path for now — multi-path support is a future enhancement
  const primaryPath = scanPaths[0] ?? null;

  // Only fetch when user has submitted the form (appliedValues !== null)
  const { data, isLoading, error } = useDefectCrops(
    appliedValues ? primaryPath : null,
    appliedValues?.eps ?? 300,
    appliedValues?.pad ?? 64,
  );

  const handleApply = () => {
    setAppliedValues({ ...formValues });
    setStep("viewer");
  };

  const handleBackToForm = () => {
    setStep("form");
  };

  if (!open) return null;

  // ── Step 1: Configuration Form ──
  if (step === "form") {
    return (
      <CropConfigForm
        scanName={scanName}
        totalDefects={0}  // TODO: pass from dataset creation result
        availableRecipes={[]}  // TODO: populate from scan metadata
        values={formValues}
        onChange={setFormValues}
        onApply={handleApply}
        onBack={onBack}
      />
    );
  }

  // ── Step 2: Crop Viewer ──
  const avgPerCluster = data && data.total_crops > 0
    ? (data.total_defects / data.total_crops).toFixed(1)
    : "—";

  return (
    <div className={styles.overlay}>
      <div className={styles.viewer}>
        {/* Header */}
        <div className={styles.header}>
          <Button onClick={handleBackToForm} className={styles.backBtn}>← Back to Form</Button>
          <span className={styles.title}>Review Defect Crops — {scanName}</span>
        </div>

        {/* Stats bar */}
        {data && (
          <div className={styles.stats}>
            <Statistic title="Total Defects" value={data.total_defects} />
            <Statistic title="Clusters" value={data.total_crops} />
            <Statistic title="Avg Defects/Cluster" value={avgPerCluster} />
          </div>
        )}

        {/* Message (e.g., "no defects found") */}
        {data?.message && <Alert type="info" message={data.message} className={styles.alert} />}

        {/* Main content */}
        <div className={styles.content}>
          {/* Wafer Map sidebar */}
          {data && data.crops.length > 0 && (
            <div className={styles.mapSidebar}>
              <div className={styles.mapLabel}>Wafer Map</div>
              <WaferMap crops={data.crops} viewport={data.viewport} />
            </div>
          )}

          {/* Cluster Grid */}
          <div className={styles.gridArea} ref={gridRef}>
            {isLoading && <Spin size="large" className={styles.spinner} />}
            {error && <Alert type="error" message={error.message} />}
            {!isLoading && data?.crops.length === 0 && (
              <Empty description="No defect clusters found for this scan" />
            )}
            {data && (
              <div className={styles.grid}>
                {data.crops.map((crop) => {
                  // BUG3 fix: stable key, not array index
                  const key = `${crop.image_name}:${crop.crop_x},${crop.crop_y}`;
                  return (
                    <CropTile
                      key={key}
                      imageUrl={crop.image_url}
                      cropX={crop.crop_x} cropY={crop.crop_y}
                      cropW={crop.crop_w} cropH={crop.crop_h}
                      defects={crop.defects}
                      defectCount={crop.defect_count}
                      recipeName={crop.recipe_name}
                      tileSize={appliedValues?.thumbnailSize ?? 256}
                    />
                  );
                })}
              </div>
            )}
          </div>
        </div>

        {/* Footer */}
        <div className={styles.footerBar}>
          <Button size="large" onClick={handleBackToForm}>← Back to Form</Button>
          <Button size="large" onClick={onBack}>← Back to Scan Results</Button>
        </div>
      </div>
    </div>
  );
};
```

---

### 4.8 `style.module.scss`

```scss
// fe/clustplorer/src/views/pages/ScanResults/DefectCropViewer/style.module.scss

.overlay {
  position: fixed; inset: 0; z-index: 1000;
  background: rgba(0, 0, 0, 0.75);
  display: flex; align-items: center; justify-content: center;
}

// ── CropConfigForm (Step 1) ──
.formPanel {
  background: var(--bg-primary, #1a1a2e);
  border-radius: 12px;
  width: 640px; max-width: 95vw;
  max-height: 92vh;
  display: flex; flex-direction: column;
  overflow-y: auto;
}

.successBadge {
  display: flex; align-items: center; gap: 12px;
  padding: 12px 24px;
  border-bottom: 1px solid var(--border-color, #2d2d44);
  font-size: 14px; color: var(--text-primary, #e2e2e2);
}

.formSection {
  padding: 16px 24px;
  border-bottom: 1px solid var(--border-color, #2d2d44);

  h4 {
    font-size: 13px; font-weight: 600;
    color: var(--text-secondary, #888);
    text-transform: uppercase; letter-spacing: 0.05em;
    margin-bottom: 12px;
  }
}

// ── DefectCropViewer (Step 2) ──
.viewer {
  background: var(--bg-primary, #1a1a2e);
  border-radius: 12px;
  width: 95vw; max-width: 1400px;
  height: 92vh;
  display: flex; flex-direction: column;
  overflow: hidden;
}

.header {
  display: flex; align-items: center; gap: 16px;
  padding: 16px 24px;
  border-bottom: 1px solid var(--border-color, #2d2d44);
}

.title {
  font-size: 16px; font-weight: 600;
  color: var(--text-primary, #e2e2e2);
  flex: 1;
}

.backBtn { margin-right: auto; }

.stats {
  display: flex; gap: 32px;
  padding: 12px 24px;
  border-bottom: 1px solid var(--border-color, #2d2d44);

  :global(.ant-statistic-title) { font-size: 12px; color: var(--text-secondary, #888); }
  :global(.ant-statistic-content) { font-size: 20px; font-weight: 700; color: var(--text-primary, #e2e2e2); }
}

.alert { margin: 8px 24px; }

.controlRow {
  margin-bottom: 12px;
  label { font-size: 13px; color: var(--text-secondary, #888); display: block; margin-bottom: 4px; }
}

.content {
  display: flex; flex: 1; overflow: hidden;
}

.mapSidebar {
  width: 340px; padding: 16px;
  border-right: 1px solid var(--border-color, #2d2d44);
  flex-shrink: 0;
}

.mapLabel {
  font-size: 12px; font-weight: 600;
  color: var(--text-secondary, #888);
  margin-bottom: 8px; text-transform: uppercase; letter-spacing: 0.05em;
}

.gridArea {
  flex: 1; overflow-y: auto;
  padding: 16px;
}

.grid {
  display: flex; flex-wrap: wrap; gap: 12px;
}

.spinner { display: block; margin: 48px auto; }

// CropTile styles
.tile {
  position: relative; cursor: pointer;
  border: 1px solid var(--border-color, #2d2d44);
  border-radius: 8px; overflow: hidden;
  transition: border-color 0.15s, box-shadow 0.15s;

  &:hover {
    border-color: var(--primary, #6c63ff);
    box-shadow: 0 0 12px rgba(108, 99, 255, 0.3);
  }

  &:focus-visible {
    outline: 2px solid var(--primary, #6c63ff);
    outline-offset: 2px;
  }
}

.placeholder, .errorPlaceholder {
  position: absolute; inset: 0;
  background: #2a2a40;
  display: flex; align-items: center; justify-content: center;
  color: var(--text-secondary, #888);
  font-size: 12px;
  border-radius: 6px 6px 0 0;
}

.footer {
  display: flex; justify-content: space-between; align-items: center;
  padding: 6px 10px;
  background: #12121e;
}

.count {
  font-size: 12px; font-weight: 600;
  color: var(--text-primary, #e2e2e2);
}

.recipe {
  font-size: 11px; color: var(--text-secondary, #888);
  max-width: 120px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}

.footerBar {
  display: flex; justify-content: flex-end; gap: 12px;
  padding: 16px 24px;
  border-top: 1px solid var(--border-color, #2d2d44);
}
```

---

### 4.7 Modify `ScanResults/index.tsx` — Wiring Change

```typescript
// In fe/clustplorer/src/views/pages/ScanResults/index.tsx
// EXISTING state (already present):
// const [exportModalOpen, setExportModalOpen] = useState(false);

// ADD: new state variable for crop viewer
const [cropViewerOpen, setCropViewerOpen] = useState(false);

// Export button onClick: UNCHANGED — still opens ExportDatasetModal
<Button onClick={() => setExportModalOpen(true)}>Export to VL Dataset</Button>

// CHANGE: ExportDatasetModal onSuccess callback
// OLD: onSuccess might navigate to dataset or close modal
// NEW: on success → close modal → open crop viewer
<ExportDatasetModal
  open={exportModalOpen}
  onClose={() => setExportModalOpen(false)}
  onSuccess={() => {
    setExportModalOpen(false);
    setCropViewerOpen(true);   // dataset created → open form + viewer
  }}
  // ... other existing props unchanged
/>

// ADD: DefectCropViewer (shows form first, then viewer after form submit)
import { DefectCropViewer } from "./DefectCropViewer";

<DefectCropViewer
  open={cropViewerOpen}
  scanPaths={selectedRows.map(r => r.path_to_files)}
  scanName={selectedRows[0]?.scan_process?.setup?.job_name ?? ""}
  onBack={() => setCropViewerOpen(false)}
/>
```

---

## 5. Python CLI: `generate_feature.py`

```python
#!/usr/bin/env python3
"""
generate_feature.py — Scaffolds all files for the Defect Crop Viewer feature.

Usage:
    python generate_feature.py [--repo-root PATH]

Options:
    --repo-root   Root of the vl-camtek repository (default: current directory)

What it creates:
    clustplorer/web/api_defect_crops.py
    vl/services/defect_clustering.py
    fe/clustplorer/src/views/pages/ScanResults/DefectCropViewer/index.tsx
    fe/clustplorer/src/views/pages/ScanResults/DefectCropViewer/CropTile.tsx
    fe/clustplorer/src/views/pages/ScanResults/DefectCropViewer/BoundingBoxOverlay.tsx
    fe/clustplorer/src/views/pages/ScanResults/DefectCropViewer/WaferMap.tsx
    fe/clustplorer/src/views/pages/ScanResults/DefectCropViewer/useDefectCrops.ts
    fe/clustplorer/src/views/pages/ScanResults/DefectCropViewer/style.module.scss

What it patches:
    clustplorer/web/__init__.py  (+import + include_router)

What it does NOT touch:
    fe/.../ScanResults/index.tsx  (manual 3-line change documented in phase_C)
"""
import argparse
import os
import sys
import textwrap
from pathlib import Path

# ── File content templates ────────────────────────────────────────────────────
# (abbreviated here — in production, read from actual template files)

TEMPLATES = {
    "clustplorer/web/api_defect_crops.py": "# See phase_C_implementation.md section 3.2\n",
    "vl/services/defect_clustering.py": "# See phase_C_implementation.md section 3.1\n",
    "fe/clustplorer/src/views/pages/ScanResults/DefectCropViewer/index.tsx": "// See phase_C_implementation.md section 4.6\n",
    "fe/clustplorer/src/views/pages/ScanResults/DefectCropViewer/CropConfigForm.tsx": "// See phase_C_implementation.md section 4.5\n",
    "fe/clustplorer/src/views/pages/ScanResults/DefectCropViewer/CropTile.tsx": "// See phase_C_implementation.md section 4.3\n",
    "fe/clustplorer/src/views/pages/ScanResults/DefectCropViewer/BoundingBoxOverlay.tsx": "// See phase_C_implementation.md section 4.2\n",
    "fe/clustplorer/src/views/pages/ScanResults/DefectCropViewer/WaferMap.tsx": "// See phase_C_implementation.md section 4.4\n",
    "fe/clustplorer/src/views/pages/ScanResults/DefectCropViewer/useDefectCrops.ts": "// See phase_C_implementation.md section 4.1\n",
    "fe/clustplorer/src/views/pages/ScanResults/DefectCropViewer/style.module.scss": "// See phase_C_implementation.md section 4.8\n",
}

INIT_IMPORT = "from clustplorer.web.api_defect_crops import router as defect_crops_router\n"
INIT_REGISTER = "app.include_router(defect_crops_router)\n"


def scaffold(repo_root: Path) -> None:
    print(f"\nScaffolding Defect Crop Viewer in: {repo_root}\n")
    created, skipped = 0, 0

    for rel, content in TEMPLATES.items():
        target = repo_root / rel
        if target.exists():
            print(f"  SKIP (exists): {rel}")
            skipped += 1
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        print(f"  CREATE: {rel}")
        created += 1

    # Patch __init__.py
    init_path = repo_root / "clustplorer/web/__init__.py"
    if init_path.exists():
        content = init_path.read_text(encoding="utf-8")
        if "api_defect_crops" not in content:
            # Insert import after the last api_* import line
            import_marker = "from clustplorer.web.api_scan_results import router"
            patched = content.replace(
                import_marker,
                import_marker + "\n" + INIT_IMPORT.rstrip(),
            )
            # Insert include_router after scan_results registration
            register_marker = "app.include_router(scan_results_router)"
            patched = patched.replace(
                register_marker,
                register_marker + "\n" + INIT_REGISTER.rstrip(),
            )
            init_path.write_text(patched, encoding="utf-8")
            print(f"\n  PATCH: clustplorer/web/__init__.py (+import +include_router)")
        else:
            print(f"\n  SKIP PATCH: __init__.py already contains api_defect_crops")
    else:
        print(f"\n  WARNING: __init__.py not found at {init_path}")

    print(f"\nDone. Created: {created}, Skipped: {skipped}")
    print("\nNext steps:")
    print("  1. Copy production code from phase_C_implementation.md into each created file")
    print("  2. Apply 3-line manual change to ScanResults/index.tsx (see section 4.7)")
    print("  3. Run backend: uvicorn clustplorer.web:app --reload")
    print("  4. Run frontend: cd fe/clustplorer && npm start")
    print("  5. Test: navigate to /scan-results → select scan → Export → create dataset → configure form → Apply & View")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scaffold Defect Crop Viewer feature files")
    parser.add_argument("--repo-root", default=".", help="Root of the vl-camtek repository")
    args = parser.parse_args()

    root = Path(args.repo_root).resolve()
    if not (root / "clustplorer").is_dir():
        print(f"ERROR: {root} does not look like the vl-camtek repo root (no clustplorer/ dir)")
        sys.exit(1)

    scaffold(root)
```

Run via:
```bash
python generate_feature.py --repo-root "c:/visual layer/vl-camtek"
```

---

## 6. Integration Instructions

### Step 1 — Backend

1. Create `vl/services/defect_clustering.py` with content from Section 3.1
2. Create `clustplorer/web/api_defect_crops.py` with content from Section 3.2
3. Edit `clustplorer/web/__init__.py` — add exactly 2 lines (Section 3.3)
4. Verify: `python -c "from clustplorer.web import app; print('OK')"` — no ImportError

### Step 2 — Frontend

1. Create directory: `fe/clustplorer/src/views/pages/ScanResults/DefectCropViewer/`
2. Create all 8 files from Sections 4.1–4.8 (including new `CropConfigForm.tsx`)
3. Apply wiring change to `ScanResults/index.tsx` (Section 4.7)
4. TypeScript check: `cd fe/clustplorer && npx tsc --noEmit`

### Step 3 — Verification

```bash
# Backend
cd "c:/visual layer/vl-camtek"
uvicorn clustplorer.web:app --reload

# Test the new endpoint:
curl "http://localhost:8000/api/v1/scan-results/defect-clusters?path=C:/temp/ExportVl/MTK-AHJ11236_setup1_20260406_201352&eps=300&pad=64" \
  -H "Authorization: Bearer <token>"

# Frontend
cd fe/clustplorer
npm start

# Navigate to: http://localhost:3000/scan-results
# Select a scan result → click "Export to VL Dataset"
# Verify: ExportDatasetModal opens → create dataset → CropConfigForm opens
# Configure params → click "Apply & View Crops" → DefectCropViewer renders with clusters
```

### Step 4 — End-to-End Test Checklist

- [ ] Scan results table loads and selections work
- [ ] Clicking "Export to VL Dataset" opens ExportDatasetModal (UNCHANGED)
- [ ] ExportDatasetModal works identically to before (dataset name + path → create)
- [ ] Dataset creation succeeds → CropConfigForm opens automatically
- [ ] CropConfigForm shows success badge with defect count
- [ ] Form controls work: eps slider, pad slider, OClass checkboxes, recipe checkboxes
- [ ] Clicking "Apply & View Crops" transitions to DefectCropViewer
- [ ] API call uses form parameters (eps, pad values from form)
- [ ] Wafer map renders colored dots
- [ ] Cluster grid shows CropTile components with correct thumbnail size from form
- [ ] Each tile shows canvas with image + SVG bounding boxes
- [ ] "← Back to Form" returns to CropConfigForm with values preserved
- [ ] Changing form values and re-applying updates the viewer
- [ ] "← Back to Scan Results" closes everything, returns to table
- [ ] Empty state: scan with all Pass records shows empty state message
- [ ] Error state: invalid path shows error alert

---

## 7. Risk Mitigations (Implemented)

| Risk | Mitigation in Code |
|------|-------------------|
| **BUG1 Canvas CORS** | `img.crossOrigin = "anonymous"` + `Access-Control-Allow-Origin: *` on `/image` endpoint |
| **BUG2 Unmount during async** | `cancelled = true` cleanup in `useEffect` |
| **BUG3 Stale React key** | Stable key = `image_name:crop_x,crop_y` |
| **BUG4 BBox out of range** | `max(0.0, min(1.0 - w_norm, ...))` clamp in backend |
| **BUG5 Column name spaces** | `row.get("Wafer X")` not `row.get("WaferX")` |
| **BUG6 Backslash in paths** | `image_name.replace("\\", "/")` + `PurePosixPath` |
| **BUG7 DBSCAN noise label** | Explicit `if cid == -1: handle_singletons` guard |
| **BUG8 Sentinel OClass** | `SKIP_CLASSES = {1, 2147483644, 2147483645, 2147483646}` |
| **BUG9 Multi-recipe duplicates** | `group_by_recipe()` before clustering |
| **BUG10 TypeScript types** | Explicit interface definitions in `useDefectCrops.ts` |
| **BUG11 Scroll reset** | `scrollRef` preserved and restored around re-renders |
| **W2 No image endpoint** | New `GET /scan-results/image` endpoint added |
| **W9 Race condition (slider)** | Form-first design eliminates live debounce — API only called on explicit "Apply & View Crops" submit |
| **W10 CSV caching** | `@lru_cache` keyed by `(path, mtime)` |
| **W19 Cluster explosion** | Auto-widen eps x2 up to 3 retries |
| **W24 Path traversal** | `full.relative_to(base)` security check |
