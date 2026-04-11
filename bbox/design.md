

You are a senior full-stack engineer specializing in **React (frontend)** and **Python (backend)**, with strong experience in **computer vision workflows and UI/UX design**.

Your task is to analyze an existing system and design + implement a new intermediate feature based on the current codebase.

---

## **🎯 Goal**

Create an **intermediate stage** between:

* Selecting a `scanResult`
* Generating a dataset

### This stage must:

* Display images from the `scanResult` use the information from C:\Users\amita\Desktop\detaction AI\scripts\scan\scanResault.md and "C:\Users\amita\Desktop\detaction AI\scripts\scan\ScanResualt after"
* Perform **image cropping (client-side or server-side – you decide)**
* Load defect data from `db.csv` include in the
* Each record in `db.csv` contains **relative coordinates (x, y)** of defects
* Render **bounding boxes around each defect**

---

## **🆕 Additional Core Requirement (IMPORTANT)**

* Each cropped tile must display **multiple bounding boxes when possible**
* The system should:

  * **Maximize the number of defects shown per crop**
  * Avoid creating crops with a single defect if multiple nearby defects can fit in the same crop
* This implies:

  * A **grouping/clustering strategy** for defects before cropping
  * Smart crop region selection based on defect density

### Claude must:

* Propose and implement a **defect clustering algorithm**, such as:

  * Distance-based grouping
  * Grid/bin packing
  * Sliding window / tiling strategy
* Clearly explain:

  * How crops are computed
  * How many defects per crop are expected
  * Trade-offs between crop size and defect density

---

## **🧠 Phase A – System Understanding**

Analyze the provided codebase and identify:

### **Backend (Python)**

* Framework (Flask / FastAPI / Django)
* How `db.csv` is stored and accessed
* Existing endpoints and services
* Image handling logic (if exists)

### **Frontend (React)**

* Component structure
* State management (Redux / Context / hooks)
* Styling system (CSS / Tailwind / MUI / etc.)
* Existing image display components

### **Communication**

* API structure (REST / gRPC)
* Data contracts between client and server

---

### **Output (phase_A_summary.md)**

* Architecture overview
* Key modules and responsibilities
* Data flow diagram (text-based)
* Constraints and assumptions

---

## **🧩 Phase B – Solution Design**

Propose **at least 2 approaches**, for example:

* **Option 1:** Client-side cropping (Canvas API in React)
* **Option 2:** Server-side cropping (Python using OpenCV / PIL)

---

### For each solution include:

* Architecture diagram
* Data flow
* Bounding box calculation:

  ```
  absoluteX = relativeX * imageWidth
  absoluteY = relativeY * imageHeight
  ```

---

### ✅ NEW: Cropping Strategy Design

For each solution, include:

* **Defect grouping method**
* **Crop generation algorithm**
* Strategy to:

  * Maximize bounding boxes per crop
  * Avoid overlap redundancy
  * Handle edge cases (dense vs sparse defects)

Examples to consider:

* Clustering (e.g., distance threshold)
* Fixed-size sliding window
* Dynamic crop expansion around clusters

---

### **Comparison**

* Performance
* Complexity
* Scalability
* Maintainability
* UX responsiveness

---

### **UX/UI Design (React-focused)**

Design how this appears in the UI:

* Multiple bounding boxes per image tile
* Clear visual distinction between boxes
* Zoom / hover interactions (optional)
* Suggested components:

  * `ScanResultViewer`
  * `ImageCropper`
  * `BoundingBoxOverlay`
  * `DefectClusterView`

---

### **Output (phase_B_design.md)**

* Comparison table
* Final recommended approach
* Clear explanation of cropping + clustering logic
* UX/UI proposal

---

## **⚙️ Phase C – Implementation Plan**

### **1. Flow Diagrams**

```
scanResult → load images → fetch CSV → cluster defects → generate crops → render tiles → dataset
```

---

### **2. Backend Implementation (Python)**

Use **FastAPI (preferred) or Flask**.

Include:

* Endpoint to fetch scan images
* Endpoint to fetch parsed `db.csv`
* **Defect clustering module**
* **Crop generation logic**
* Optional: image cropping endpoint

---

### **3. Frontend Implementation (React)**

Use **functional components + hooks**.

Include:

* Image/tile viewer
* Bounding box overlay (SVG or Canvas)
* Rendering multiple boxes per tile
* Coordinate transformation logic
* Efficient rendering (avoid re-renders)

---

### **4. Change Map**

Explicitly list:

* Files to modify
* New files to create
* API changes
* Risk areas

---

### **Output (phase_C_implementation.md)**

* Code snippets (production-quality)
* File structure
* Integration instructions

---

## **🤖 Final Step – Code Generation Script**

Write a **Python CLI script** that:

* Generates backend + frontend code
* Implements clustering + cropping logic
* Can run via:

```bash
python generate_feature.py
```

---

## **⚠️ Constraints**

* MUST follow existing React design system
* Prefer React hooks (no class components)
* Keep backend clean and modular
* Avoid unnecessary dependencies
* Ensure scalability

---

## **💡 Technical Expectations**

### Bounding Boxes

* Must scale correctly with image resizing
* Support multiple boxes per tile

### Cropping Logic

* Must prioritize **defect density per crop**
* Avoid redundant crops
* Deterministic behavior preferred

### Edge Cases

* No defects
* Extremely dense defects
* Sparse defects
* Out-of-bound coordinates

---

## **🧾 Output Format Requirements**

Claude must:

* Think step-by-step
* Clearly separate phases
* Output **3 markdown files**:

  * `C:\Users\amita\Desktop\detaction AI\scripts\bbox\output\phase_A_summary.md`
  * `C:\Users\amita\Desktop\detaction AI\scripts\bbox\output\phase_B_design.md`
  * `C:\Users\amita\Desktop\detaction AI\scripts\bbox\output\phase_C_implementation.md`

---
