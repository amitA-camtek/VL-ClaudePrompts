# Claude Prompt: Dataset Creation from Scan Results - Investigation & Design

## CONTEXT

You are assisting in designing a **dataset creation pipeline** for the Visual Layer (VL) platform, using scan results from wafer inspection equipment (EAGLET_106739). The platform is a visual data management system for exploring, curating, and improving image datasets, with integrated label propagation, model training, and clustering capabilities.

### System Context
- **Platform:** Visual Layer (VL) - FastAPI backend, React frontend, PostgreSQL + DuckDB
- **Use Case:** Transform semiconductor wafer inspection results into a structured dataset
- **Source Data:** Scan results containing images, metadata, defect classifications, and coordinates
- **Goal:** Enable users to review, label, and propagate labels on defect data

### Source Data Structure (from scanResult.md)
```
Scan Results (After Processing):
├── Classes.json          → 99+ defect classification codes (e.g., "Pass", "Surface", "Solder", "Bump", etc.)
├── DB.csv               → Inspection database (18 columns per row): ImageName, OClass, Wafer X/Y, Zone, Recipe, etc.
├── MetaData.json        → Export metadata (Customer, Job, Setup, Timestamp)
└── images/
    ├── lot_01/          → 100+ JPEG images (color mode)
    └── lot_02/          → Additional lot folder
```

**Key Data Relationships:**
- Each row in DB.csv maps to one image in images/ folder
- OClass (classification code) → lookup in Classes.json → human-readable label
- Wafer X/Y → precise die location (sub-micron coordinates)
- ImageName → physical path to JPEG file
- Recipe → inspection recipe used ("x7.5 Bump PMI", "x3.5 Surface", etc.)
- Zone → inspection zone ID (spatial context)

---

## REQUIREMENTS

### Requirement 1: Create Dataset from Scan Results
Design a process that:
- Ingests scan results (Classes.json, DB.csv, MetaData.json, images/)
- Creates a structured dataset in VL platform
- Preserves metadata (wafer coordinates, zone, recipe, equipment info)
- Associates classification labels with images as Ground Truth (GT)
- Enables dataset exploration and curation in VL frontend

---

### Requirement 2: Pre-Processing Before Dataset Creation
Before the dataset is usable, implement the following data handling workflows:

#### 2.1: Show Both Images Side-by-Side (Color/Greyscale)
**Objective:** Enable users to view complementary image representations simultaneously

**Context:**
- Scan results contain color JPEG images
- Some wafers may have greyscale variants available or derivable
- Users need visual comparison for validation and defect analysis

**Questions to Address:**
- How to load and cache both color and greyscale versions?
- What happens if greyscale is missing?
- UI layout and interaction model for side-by-side display
- Performance considerations (lazy loading, thumbnails vs full-res)

---

#### 2.2: Load Full Images and Dynamically Crop GT Defect Areas
**Objective:** Display full wafer die images with dynamically cropped Ground Truth (GT) defect regions

**Context:**
- Full images are loaded as base layer (original inspection image)
- GT defect areas are identified from metadata/annotations
- Users need to crop and zoom into ROI (Region of Interest) around defects
- Same ROI must be displayable on both color and greyscale versions

**Questions to Address:**
- How are GT defect areas defined? (Bounding boxes, contours, pixel masks?)
- What is the source of GT annotation? (From Classes.json + OClass? From manual markup?)
- Cropping algorithm: center on defect + padding? Fixed size or adaptive?
- Performance: precompute crops or generate on-the-fly?
- Coordinate space: image coordinates vs wafer coordinates?

---

#### 2.3: UI Crop - Multiple Bboxes on Single Tile
**Objective:** Show as many bounding boxes as possible on a single cropped image tile in the UI

**Specific Requirements:**
- Defect areas represented as bounding boxes (bboxes)
- Multiple bboxes per image tile (when possible)
- Maximize the number of visible bboxes per crop
- Optimize visual clarity and overlap handling

**Questions to Address:**
- Bbox source: how are they extracted from scan data?
- Packing algorithm: how to fit multiple bboxes without excessive overlap?
- Visual design: how to distinguish multiple defect types on one tile?
- Interaction: zoom/pan behavior when multiple bboxes are present?
- Size constraints: tile dimensions, bbox minimum/maximum sizes?

---

#### 2.4: Label Propagation Crop - Optimized for ML Features
**Objective:** Generate specialized crops for label propagation that differ from UI crops

**Specific Requirements:**
- Crop centered on each bbox with padding
- Optimized for feature extraction (embedding generation)
- Input to label propagation SVM model (active learning cycle)
- May differ from UI crop implementation (different padding, size, preprocessing)

**Questions to Address:**
- Padding strategy: fixed pixel size vs percentage of bbox?
- Crop size: standardized (e.g., 256×256) or variable?
- Preprocessing: normalization, enhancement before feature extraction?
- Feature extraction: which layers of model? Which embedding model?
- Caching: cache crops for reuse across label propagation cycles?
- Performance: batch generation vs on-demand?

---

## INVESTIGATION TASKS

Before proposing design, investigate AND DOCUMENT your findings for:

### A. Data Integration Architecture
1. **How does VL handle dataset creation from external sources?**
   - Study `api_dataset_create_workflow.py` (if available in codebase)
   - Identify the standard ingestion pipeline structure
   - Determine where custom scan result parsing fits

2. **What is the expected dataset schema in VL?**
   - Image entities: what metadata is stored?
   - Label structure: how are classifications stored? (categorical, hierarchical, multi-label?)
   - Ground Truth (GT) annotations: how are they represented in VL?
   - Bbox/ROI storage: does VL have native support for bounding boxes?

3. **How does VL handle metadata preservation?**
   - Custom metadata fields: are they supported?
   - Wafer coordinates, recipe, zone info: where stored?
   - Auditability: how to track data provenance?

### B. Image Handling & Display
1. **Image storage & serving in VL**
   - S3 integration: how are images uploaded and served?
   - Image proxy service: caching, format conversion capabilities?
   - Multi-version support: can a single image have multiple file representations (color, greyscale)?

2. **Frontend image display capabilities**
   - Side-by-side viewer component: does one exist? How to implement?
   - Full-image + ROI display: existing patterns in VL frontend?
   - Zoom/pan interactions: how implemented in current viewers?

3. **Crop generation requirements**
   - On-the-fly vs precomputed: performance vs space trade-offs?
   - Coordinate systems: image pixels vs wafer coordinates?
   - Integration with image proxy or pipeline preprocessor?

### C. Label Propagation Integration
1. **Current label propagation flow in VL**
   - How does VL train SVM classifiers?
   - What is the expected input format for embeddings?
   - Feature extraction: which embedding model(s) are used?
   - How are predictions presented to users for review?

2. **Crop requirements for label propagation**
   - Does VL preprocess crops before feature extraction?
   - Are crops cached or generated per prediction cycle?
   - How to ensure consistency between UI crops and LP crops?

3. **Active learning UI in VL**
   - Review interface: how are predictions shown side-by-side with confidence scores?
   - Accept/reject mechanism: how stored and tracked?
   - Cycle progression: how to manage multiple refinement rounds?

### D. Performance & Scalability
1. **Data size expectations**
   - Scan results: ~100-500 images per job
   - Typical image resolution: ? (infer from JPEG filenames & inspection equipment specs)
   - Crop generation throughput: target rate?
   - Concurrent users: expected load?

2. **Pipeline bottlenecks**
   - Is image loading the bottleneck or feature extraction?
   - How to handle off-peak vs peak usage?
   - Caching strategy recommendations?

---

## DESIGN REQUIREMENTS

### Primary Design Goal
Create a **minimal but complete design** that:
1. ✅ Integrates scan results into VL as a structured dataset
2. ✅ Implements the 4 pre-processing workflows (2.1 - 2.4) with clear separation of concerns
3. ✅ Supports both UI-driven exploration AND ML-optimized label propagation
4. ✅ Maintains performance under realistic scan result dataset sizes (100-1000 images)
5. ✅ Works within VL's existing architecture (FastAPI backend, React frontend, S3 storage, DuckDB analytics)

### Design Output Should Include
- **Architecture Diagram:** System components and data flow
- **Component Specifications:** Role of backend, frontend, image proxy, pipeline
- **Data Models:** Schema for storing dataset, images, labels, crops
- **Processing Pipeline:** Steps for ingesting scan results
- **API Contracts:** Endpoints for dataset creation, crop retrieval, crop list
- **Frontend Components:** UI patterns for 2.1, 2.2, 2.3, 2.4
- **Performance Assumptions:** Caching strategy, cache invalidation, scaling constraints
- **Alternative Designs:** (See section below)

---

## ALTERNATIVE DESIGN REQUEST

Propose **3 distinct architectural approaches** for handling crops (Requirement 2.3 and 2.4):

### Approach A: Pre-compute All Crops at Ingestion Time
- Generate all crops (UI + LP) during dataset creation
- Store crops in S3 alongside originals
- **Trade-offs:** ↑ Storage, ↑ Initial latency, ↓ Runtime latency
- **When to use:** Small datasets, slow network, high query rate

### Approach B: Generate Crops On-Demand with Caching
- Generate crops at request time, cache in Redis/memory
- Cache invalidation strategy on label updates
- **Trade-offs:** ↔ Storage (moderate), ↔ Runtime latency, ↑ Complexity
- **When to use:** Medium datasets, moderate query rate, memory available

### Approach C: Stream Crops via Pipeline Worker
- Use existing VL pipeline service Worker to batch-generate crops asynchronously
- Poll for readiness, serve on-demand with fallback to slow path
- **Trade-offs:** ↓ Storage, ↑ Complexity, Async UI state management
- **When to use:** Large datasets, resource-constrained environments, batch optimization

**For each approach, provide:**
- Implementation complexity (easy/medium/hard)
- Resource requirements (CPU, Memory, Storage)
- API changes needed
- Frontend state management implications
- Scalability characteristics (# of images, # of concurrent users)

---

## DELIVERABLES EXPECTED FROM CLAUDE

1. **Design Investigation Summary** (1-2 pages)
   - Key findings from investigation tasks (A-D)
   - Gaps in understanding & assumptions made
   - Recommended reading/files to reference

2. **Primary Design Specification** (3-5 pages)
   - Architecture overview with diagrams (Mermaid or ASCII)
   - Data flow for ingestion → dataset → UI/LP usage
   - Component responsibilities
   - Database schema (entities, relationships)
   - API specification (endpoints, request/response)
   - Frontend component architecture
   - Implementation roadmap (phases/milestones)

3. **Alternative Designs** (1-2 pages per approach)
   - High-level overview
   - Comparison table (complexity, resources, scalability)
   - Pros/cons vs primary design
   - Recommendation for when to use each

4. **Risk & Mitigation** (1 page)
   - Technical risks (performance, data consistency, coordinate space mismatches)
   - Operational risks (user adoption, debugging complexity)
   - Mitigation strategies

5. **Next Steps** (1 page)
   - Recommended prototype scope
   - Dependencies for implementation
   - Validation criteria

---

## CONTEXT FILES PROVIDED

- System.md - VL platform architecture (services, APIs, data models, business flows)
- ScanResult.md - Scan result structure, file types, data relationships

---

## TONE & APPROACH

- **Be thorough but direct:** Assume reader understands software architecture
- **Leverage system.md heavily:** Reference existing VL patterns, APIs, data models
- **Be specific about scan data:** Use real file names, field names, typical data sizes from scanResult.md
- **Highlight unknowns:** If something is not clear from provided docs, state the assumption explicitly
- **Focus on designer perspective:** How would you pitch this to the product/engineering team?

---

**Start your analysis with: "# Dataset Creation Design - Investigation & Recommendations"**

Then proceed with investigation findings, primary design, alternatives, and next steps.
