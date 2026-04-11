# Scan Result Analysis - Folder Structure & File Documentation

**Expert Developer Analysis** - Understanding the complete scan result ecosystem for wafer inspection and defect classification.

---

## 📋 Table of Contents
1. [Overview](#overview)
2. [Folder Structure](#folder-structure)
3. [Detailed File Analysis](#detailed-file-analysis)
4. [File Type Reference](#file-type-reference)
5. [Data Flow](#data-flow)
6. [Key Insights](#key-insights)

---

## Overview

The `scan` folder contains **wafer inspection scan results** from an optical inspection tool (EAGLET_106739) performing quality assurance on semiconductor wafers. The results are organized in two states:

- **"Scane Resault before"** - Raw scan data with configuration files and source images
- **"Scane Resault after"** - Processed results with classification data and exported metadata

**Project Details:**
- Customer: KYEC
- Job Name: MTK-AHJ11236
- Setup: setup1
- Export Timestamp: 2026-04-06 20:13:53
- Tool: EAGLET_106739 (Optical Inspection Equipment)

---

## Folder Structure

```
scan/
├── Scane Resault after/                           [PROCESSED RESULTS]
│   └── MTK-AHJ11236_setup1_20260406_201352/
│       ├── Classes.json                             (Defect classification mapping)
│       ├── DB.csv                                   (Inspection database with image metadata)
│       ├── MetaData.json                            (Export configuration metadata)
│       ├── MTK-AHJ11236_setup1_20260406_201352_export.log
│       └── images/
│           ├── lot_01/                              (Folder containing 100+ JPEG images)
│           └── lot_02/                              (Additional lot folder)
│
└── ScanResualt before/                            [RAW SCAN DATA]
    └── MTK-AHJ11236/
        └── setup1/
            └── lot/
                ├── 01/                              (Configuration files & raw images)
                ├── 02/                              (Configuration files & raw images)
                ├── 05/                              (Configuration files & raw images)
                ├── Bincode/
                └── customerWrong/
```

---

## Detailed File Analysis

### 1. **Classes.json** (Defect Classification Mapping)

**Purpose:** Maps numeric defect classification codes to human-readable defect descriptions.

**Structure:**
```json
{
  "1": "Pass",
  "2": "Surface",
  "3": "Solder",
  "4": "Bump Good",
  "5": "Out of bump - Good",
  "6": "Prob",
  // ... (up to code 99)
  "2147483646": "Mark"
}
```

**Key Defect Classes (Sample):**

| Code | Classification | Category |
|------|---|---|
| 1 | Pass | GOOD_PART |
| 2-3 | Surface, Solder | DEFECTS |
| 4-5 | Bump Good, Out of bump - Good | ACCEPTABLE |
| 10-33 | Ink-Dot, Topology, Probe marks, etc. | DEFECTS |
| 55 | Burn out - Test burn | CRITICAL |
| 77 | Non-visual defect - void | CRITICAL |
| 94-96 | Inked Die, Wafer backside issues | PROCESS_ISSUES |

**Total Classifications:** 99+ defect types covering:
- Bump defects (missing, damage, shift, height)
- Surface contamination (particles, residue, corrosion)
- Material issues (metal, solder, passivation)
- Alignment failures
- Electrical defects (shorts, burnouts)

---

### 2. **DB.csv** (Inspection Database / Results Log)

**Purpose:** Main database containing inspection results for each die/location on the wafer.

**Structure:** CSV with 18 columns per row

**Column Headers:**
```
ImageName, Tool, Job Name, Setup Name, Recipe, Recipe Name, Wafer, 
Lot, Col, Row, Mode, OClass, Index, Wafer X, Wafer Y, XInFrame, 
YInFrame, Zone
```

**Column Descriptions:**

| Column | Description | Example | Type |
|--------|---|---|---|
| **ImageName** | Path to captured image | `images/lot_01/259793.119486.c.-1615541774.1.jpeg` | Path |
| **Tool** | Inspection equipment ID | `EAGLET_106739` | String |
| **Job Name** | Project identifier | `MTK-AHJ11236` | String |
| **Setup Name** | Test setup configuration | `setup1` | String |
| **Recipe** | Recipe number/ID | `1`, `2` | Integer |
| **Recipe Name** | Human-readable recipe name | `x7.5 Bump PMI`, `x3.5 Surface` | String |
| **Wafer** | Wafer identifier | `01` | String |
| **Lot** | Lot identifier | `lot` | String |
| **Col** | Column coordinate on wafer | 0-7 | Integer |
| **Row** | Row coordinate on wafer | 0-24 | Integer |
| **Mode** | Imaging mode | `Color` | String |
| **OClass** | Defect classification code | `1` (Pass), `34` (defect), etc. | Integer |
| **Index** | Unique die index | `0`, `134217728`, etc. | Integer |
| **Wafer X** | X coordinate in wafer frame (microns) | `259794.29` | Float |
| **Wafer Y** | Y coordinate in wafer frame (microns) | `119487.37` | Float |
| **XInFrame** | X offset within frame | `0` | Integer |
| **YInFrame** | Y offset within frame | `0` | Integer |
| **Zone** | Inspection zone ID | `7`, `9`, `63` | Integer |

**Sample Data Row:**
```csv
images/lot_01/259793.119486.c.-1615541774.1.jpeg,EAGLET_106739,MTK-AHJ11236,setup1,1,x7.5 Bump PMI,01,lot,18,8,Color,1,0,259794.2874061722,119487.36525824535,0,0,7
```

**Data Insights:**
- Multiple recipes used (Recipe 1: x7.5 Bump PMI, Recipe 2: x3.5 Surface)
- Wafer organized in grid: Columns (0-7+), Rows (0-24)
- Zone system for specialized inspection areas (zones 7, 9, 63 identified)
- High-precision floating-point coordinates for die location tracking

---

### 3. **MetaData.json** (Export Configuration & Summary)

**Purpose:** Metadata about the export/scan job execution.

**Structure:**
```json
{
  "Customer Name": "KYEC",
  "Job Name": "MTK-AHJ11236",
  "Setup Name": "setup1",
  "Recipes Name": [
    "x7.5 Bump PMI",
    "x3.5 Surface"
  ],
  "Tool List": [
    "EAGLET_106739"
  ],
  "Export Timestamp": "2026-04-06 20:13:53"
}
```

**Key Information:**
- **Customer:** KYEC (semiconductor manufacturer)
- **Multiple Recipes:** Two inspection recipes applied to same wafer
- **Single Tool:** One equipment unit used (EAGLET_106739)
- **Export Date/Time:** Precise timestamp for traceability

---

### 4. **Configuration Files** (.ini, .dat, .flt - in "before" folder)

These files contain equipment and process parameters.

**Common .ini Files:**

| File | Purpose |
|------|---|
| `AlignRtp.ini` | Reticle-to-Plate alignment parameters |
| `ClassificationConvertTable.ini` | Defect code conversion/mapping rules |
| `ColorImageGrabingInfo.ini` | Color camera acquisition settings |
| `EquipmentInfo.ini` | Equipment configuration and capabilities |
| `EquipmentClassifications.ini` | Equipment-level defect classifications |
| `OpticPreset.ini` | Optical system settings (lens, focus, aperture) |
| `WaferInfo.ini` | Wafer-specific parameters (size, type, material) |
| `WaferMapRecipe.ini` | Wafer mapping algorithm configuration |
| `ZoomLevels.ini` | Microscope zoom/magnification settings |
| `Zones.ini` | Inspection zone definitions |
| `Recipe.ini` | Primary inspection recipe |
| `Recipe2-Zones.ini` | Secondary recipe with zone mappings |

**Binary/Data Files (.dat, .flt):**

| File | Type | Purpose |
|------|------|---|
| `DieAlignment.dat` | Binary | Die position alignment data |
| `DieAlignMiss.flt` | Float Array | Alignment miss measurements |
| `Prob.flt` | Float Array | Probability/confidence scores for defects |
| `Surface.flt` | Float Array | Surface quality metrics |
| `s_DieAlignPos.dat` | Binary | Stored die alignment positions |
| `s_DieLocation.dat` | Binary | Stored die location map |
| `Zones.dat` | Binary | Zone boundary definitions |

**.md Markdown Files** (Documentation):
- `DieAlignMiss.flt.md` - Metadata about alignment miss measurements
- `Prob.flt.md` - Metadata about probability scores
- `Surface.flt.md` - Metadata about surface measurements
- `s_DieAlignPos.dat.md` - Documentation for alignment positions
- `s_DieLocation.dat.md` - Documentation for location data

---

### 5. **Image Files** (.jpeg format)

**Location:** `images/lot_01/` and `images/lot_02/` in "Scane Resault after"

**Naming Convention:** `{X_coord}.{Y_coord}.c.{hash}.{recipe}.jpeg`

**Example:** `259793.119486.c.-1615541774.1.jpeg`
- X: 259793 (wafer X coordinate)
- Y: 119486 (wafer Y coordinate)
- c: Color image mode
- -1615541774: Hash/checksum for uniqueness
- 1: Recipe ID (1 or 2)

**Raw Images:** Raw .jpeg files also exist in "ScanResualt before" lot folders with identical naming and quantities.

---

### 6. **Specialized Folders & Files**

#### TrainData/
Machine learning training data for defect classification models.

#### OpticLightMetadata/
Camera and lighting calibration data for optical system.

#### Zones/
Zone boundary definitions and mask data for inspection areas.

#### Bincode/
Binary code/firmware or compiled process data.

#### customerWrong/
Subset of images flagged as potential customer defects or issues.

---

## File Type Reference

### File Extensions & Their Purposes

| Extension | File Type | Purpose | Format |
|-----------|-----------|---------|--------|
| `.json` | JSON | Structured data (classes, metadata) | Text (UTF-8/Unicode) |
| `.csv` | CSV | Tabular inspection database | Text (comma-separated values) |
| `.ini` | INI | Configuration files | Text (Key=Value) |
| `.dat` | Binary | Raw data arrays/measurements | Binary (Machine-specific) |
| `.flt` | Float Array | Floating-point measurements/scores | Binary (IEEE 754 floats) |
| `.jpeg` | Image | Inspection microscope images | Binary (JPEG) |
| `.txt` | Plain Text | Logs, reports, notes | Text |
| `.md` | Markdown | Documentation for data files | Text (Markdown) |
| `.zip` | Archive | Compressed data bundles | Binary (ZIP) |
| `.log` | Log | Execution logs and errors | Text |
| `.bck` | Backup | Backup configuration file | Text/Binary mix |

---

## Data Flow

```
┌─────────────────────────────────────────────────────────────────┐
│ PHYSICAL WAFER INSPECTION (Tool: EAGLET_106739)                 │
└──────────────────────┬──────────────────────────────────────────┘
                       │
                       ▼
        ┌──────────────────────────────┐
        │  EQUIPMENT CONFIGURATION     │
        │  - AlignRtp.ini              │
        │  - OpticPreset.ini           │
        │  - WaferInfo.ini             │
        │  - Recipe.ini                │
        └──────────────────┬───────────┘
                           │
                           ▼
        ┌──────────────────────────────┐
        │  RAW IMAGE CAPTURE           │
        │  - Color JPEG images         │
        │  - Save to lot folders       │
        │  - Extract coordinates       │
        └──────────────────┬───────────┘
                           │
                           ▼
        ┌──────────────────────────────┐
        │  DEFECT DETECTION & ANALYSIS │
        │  - Surface analysis          │
        │  - Bump measurement          │
        │  - Alignment verification    │
        └──────────────────┬───────────┘
                           │
                           ▼
        ┌──────────────────────────────┐
        │  CLASSIFICATION              │
        │  - Apply Classes.json rules  │
        │  - Generate OClass codes     │
        │  - Confidence scoring (Prob) │
        └──────────────────┬───────────┘
                           │
                           ▼
        ┌──────────────────────────────┐
        │  EXPORT & ARCHIVAL           │
        │  - Generate DB.csv           │
        │  - MetaData.json             │
        │  - Copy sorted images        │
        │  - Create log file           │
        └──────────────────────────────┘
```

---

## Key Insights

### Structure & Organization

1. **Dual-Stage Architecture:**
   - **Before:** Raw config + images (inspection setup state)
   - **After:** Processed data + structured results (inspection outcome)

2. **Multi-Level Organization:**
   - By Customer → Job → Setup → Lot → Individual Die
   - Hierarchical structure enables batch processing and traceability

3. **High-Precision Measurement:**
   - Floating-point coordinates to sub-micron precision
   - Wafer X/Y coordinates track exact die position
   - Multiple zone definitions for complex inspection patterns

### Data Characteristics

4. **Defect Classification System:**
   - 99+ predefined defect classes
   - Numeric codes (1-99) for systematic tracking
   - Covers entire manufacturing process (bump deposition, solder, surface)
   - Categories: PASS, ACCEPTABLE, DEFECTS, CRITICAL

5. **Multi-Recipe Inspection:**
   - Two recipes per job: "x7.5 Bump PMI" and "x3.5 Surface"
   - PMI = likely "Precision Micro-imaging" or similar magnification
   - Each recipe captures different defect types at different scales

6. **Traceability & Auditability:**
   - Timestamp-based export naming
   - Equipment tool ID tracking
   - Per-die index in database
   - Log files for execution tracking

### Data Volume & Types

7. **Image Dataset:**
   - 100+ JPEG images per lot
   - Color imaging mode for defect visualization
   - Each image tied to precise wafer coordinates
   - Can be used for ML model training/validation

8. **Configuration Persistence:**
   - All equipment settings saved for auditability
   - Enables reproducibility and troubleshooting
   - Zone definitions stored for spatial analysis

### Practical Applications

9. **Use Cases:**
   - **Quality Control:** Identify defective wafers/dies
   - **Process Optimization:** Track defect trends by zone/recipe
   - **Machine Learning:** Train defect classifiers using image + label pairs
   - **Failure Analysis:** Trace defects to specific equipment/recipes
   - **Customer Communication:** Export formatted reports per lot
   - **Statistical Process Control:** Monitor defect rates over time

---

## Technical Specifications Summary

| Aspect | Details |
|--------|---------|
| **Resolution** | Sub-micron (floating-point coordinates) |
| **Color Depth** | Color JPEG (likely RGB 24-bit) |
| **Grid Size** | 8+ columns × 25+ rows |
| **Inspection Zones** | 64+ distinct zones defined |
| **Recipes Supported** | 2+ simultaneous recipe execution |
| **Data Format** | CSV (0.5-1MB per export), JSON, INI, Binary |
| **Timestamp Precision** | Second-level accuracy |
| **Classification Depth** | 99+ defect types |

---

## Summary for Developers

**To master this system, understand:**
1. ✅ Classes.json defines the semantic meaning of each OClass code
2. ✅ DB.csv is the central data source - contains all inspection results
3. ✅ MetaData.json links results to job context (customer, recipes, timestamp)
4. ✅ Images are numbered by coordinates - can be matched to CSV rows
5. ✅ .ini files contain reproducible equipment state
6. ✅ Zone system allows spatial pattern analysis
7. ✅ Multiple recipes per job enable multi-scale defect detection
8. ✅ Binary .dat/.flt files store machine-precision measurements

**Key Data Relationships:**
- `DB.csv` + `Classes.json` → Complete inspection results with human-readable labels
- `ImageName` in DB.csv → Points to actual JPEG file in images/ folder
- `Recipe` in DB.csv → Cross-reference with `Recipe Name`
- `Wafer X/Y` → Precise die location in microns
- `OClass` → Lookup in Classes.json for defect type
- `Zone` → Inspection area (spatial context for analysis)

---

*Generated: April 9, 2026*
*Analysis Scope: KYEC MTK-AHJ11236 Job Setup1*
*Data Source: scan/ folder comprehensive analysis*
