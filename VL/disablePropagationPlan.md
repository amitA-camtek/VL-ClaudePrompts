# Disable Label Propagation - Complete Implementation Plan

**TL;DR**: Implement granular control over label propagation stages (SVM, Similarity, Mislabel Detection) by adding 4 boolean configuration flags to `FlywheelConfiguration`, updating the algorithm to respect these flags, and exposing controls via API and optional frontend UI.

**Total Implementation Time**: ~3-4 hours
**Difficulty**: Medium
**Impact**: Allows users to run flywheel with only selected propagation stages enabled

---

## Phase 1: Backend Configuration Model - Add Control Flags

**File**: vl/algo/label_propagation/flywheel_configuration.py

**What**: Add 4 boolean flags to `FlywheelConfiguration` class to control which propagation stages execute

**Changes**:

Add these fields to the `BaseFlywheelConfiguration` class (around line 8, before the validator):

```python
# Control flags for label propagation stages
enable_label_propagation: bool = True  # Master switch: if False, disable entire propagation
enable_svm_propagation: bool = True    # Control SVM model training and predictions
enable_similarity_propagation: bool = True  # Control similarity-based label propagation
enable_mislabel_detection: bool = True  # Control mislabel detection filtering
```

**Rationale**: 
- `enable_label_propagation`: Master switch allows quick disable of entire pipeline
- `enable_svm_propagation`: Users can run similarity-only or other combinations
- `enable_similarity_propagation`: Users can run SVM-only propagation
- `enable_mislabel_detection`: Users can disable noise filtering for raw candidate review

**Test**: Verify the fields are present in configuration objects:
```bash
python3 -c "from vl.algo.label_propagation.flywheel_configuration import FlywheelConfiguration; c = FlywheelConfiguration(number_of_entities=100); print(c.enable_label_propagation)"
# Should output: True
```

---

## Phase 2: Algorithm Updates - Respect Configuration Flags

**File**: vl/algo/label_propagation/flywheel.py

**What**: Update `run_cycle()` method to check configuration flags before executing each stage

**Changes**:

Find the `run_cycle` method (line 380) and make these modifications:

**2a) Add master switch check at the beginning** (after line 389, before the SVM runs):

```python
# Check master enable flag
if not self.config.enable_label_propagation:
    logger.info("Label propagation disabled in configuration, skipping cycle")
    return {}, {}, True
```

**2b) Make SVM run conditional** (line 397 - update the first run_svm call):

Replace:
```python
if force_apply_model_to_dataset or n_questions_asked >= self.config.q_budget:
    # ... existing code
    sure_set, score_indices_svm, scores_svm = self.run_svm(...)
```

With:
```python
if force_apply_model_to_dataset or n_questions_asked >= self.config.q_budget:
    # ... existing code
    if self.config.enable_svm_propagation:
        sure_set, score_indices_svm, scores_svm = self.run_svm(
            prev_set, not_set, ignore_set, self.context.number_of_entities
        )
    else:
        sure_set, score_indices_svm, scores_svm = {}, None, None
        logger.info("SVM propagation disabled in configuration")
```

**2c) Make SVM + Similarity + Mislabel conditional** (line 410-422):

Replace:
```python
else:
    next_set1, score_indices_svm, scores_svm = self.run_svm(...)
    mislabel_conf = self.run_mislabel_detection(prev_set, next_set1)
    sure_set1, next_set1 = self.adjust_by_mislabel_conf(mislabel_conf, next_set1)

    # similarity
    next_set2 = self.run_similarity(...)
    mislabel_conf = self.run_mislabel_detection(prev_set, next_set2)
    sure_set2, next_set2 = self.adjust_by_mislabel_conf(mislabel_conf, next_set2)
```

With:
```python
else:
    sure_set1, next_set1, score_indices_svm, scores_svm = {}, {}, None, None
    
    # SVM propagation stage
    if self.config.enable_svm_propagation:
        next_set1, score_indices_svm, scores_svm = self.run_svm(
            prev_set, not_set, ignore_set, self.config.select_per_iteration
        )
        if self.config.enable_mislabel_detection:
            mislabel_conf = self.run_mislabel_detection(prev_set, next_set1)
            sure_set1, next_set1 = self.adjust_by_mislabel_conf(mislabel_conf, next_set1)
        else:
            sure_set1 = {}
            logger.info("Mislabel detection disabled for SVM results")
    else:
        logger.info("SVM propagation disabled in configuration")

    # Similarity propagation stage
    next_set2 = {}
    if self.config.enable_similarity_propagation:
        next_set2 = self.run_similarity(prev_set, not_set, ignore_set)
        if self.config.enable_mislabel_detection:
            mislabel_conf = self.run_mislabel_detection(prev_set, next_set2)
            sure_set2, next_set2 = self.adjust_by_mislabel_conf(mislabel_conf, next_set2)
        else:
            sure_set2 = {}
            logger.info("Mislabel detection disabled for Similarity results")
    else:
        sure_set2 = {}
        logger.info("Similarity propagation disabled in configuration")
```

**2d) Combine results safely**:

After the above section, update:
```python
sure_set = {c: list(set(sure_set1.get(c, []) + sure_set2.get(c, []))) for c in prev_set}
```

**Test**: Create a custom configuration and verify stages are skipped:
```python
from vl.algo.label_propagation.flywheel_configuration import FlywheelConfiguration

# Test with only SVM enabled
config = FlywheelConfiguration(
    number_of_entities=100,
    enable_svm_propagation=True,
    enable_similarity_propagation=False,
    enable_mislabel_detection=True
)
print(f"SVM: {config.enable_svm_propagation}, Similarity: {config.enable_similarity_propagation}")
# Should output: SVM: True, Similarity: False
```

---

## Phase 3: API Endpoint Enhancement

**File**: clustplorer/web/api_flywheel.py

**What**: Update the `/api/v1/flywheel/{dataset_id}/start/{seed_id}` endpoint to accept and save configuration flags

**Current Endpoint** (line ~300):
```python
@router.put("/api/v1/flywheel/{dataset_id}/start/{seed_id}", tags=["flywheel"])
async def start_flywheel_run(
    request: Request,
    response: Response,
    dataset_id: UUID,
    seed_id: UUID,
    user: Annotated[User, Security(get_authorized_user, use_cache=False)],
    flywheel_configuration: BaseFlywheelConfiguration | None = None,
    background_tasks: BackgroundTasks = BackgroundTasks(),
) -> FlyWheelRunStatus:
```

**No changes needed to endpoint** - it already accepts `flywheel_configuration: BaseFlywheelConfiguration | None`

Because we added the boolean fields to `BaseFlywheelConfiguration`, they're now automatically accepted by the endpoint as optional fields with defaults (all True).

**What the endpoint does**:
1. Accepts optional `flywheel_configuration` in request body
2. Passes it to `flywheel_db.start_flywheel_run()`
3. That function stores config as JSON in database
4. BaseFlywheelRunner loads it before running cycles

**Test with cURL**:

Test 1 - SVM only (disable similarity):
```bash
curl -X PUT http://localhost:8000/api/v1/flywheel/{dataset_id}/start/{seed_id} \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "questions_ratio": 0.1,
    "enable_svm_propagation": true,
    "enable_similarity_propagation": false,
    "enable_mislabel_detection": true,
    "enable_label_propagation": true
  }'
```

Test 2 - Disable all propagation (manual only):
```bash
curl -X PUT http://localhost:8000/api/v1/flywheel/{dataset_id}/start/{seed_id} \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "questions_ratio": 0.1,
    "enable_label_propagation": false
  }'
```

Test 3 - Default (all enabled):
```bash
curl -X PUT http://localhost:8000/api/v1/flywheel/{dataset_id}/start/{seed_id} \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "questions_ratio": 0.1
  }'
```

**Verify**: In database, check that config_json is stored:
```sql
SELECT id, config_json FROM lp_flow ORDER BY created_at DESC LIMIT 1;
```

Should show JSON with boolean flags included.

---

## Phase 4: Optional - Redux State Management (Frontend)

If you want a UI toggle for these settings, implement Redux state management.

**File**: fe/clustplorer/src/redux/slices/flywheelConfigSlice.ts

Create this new file:

```typescript
import { createSlice, PayloadAction } from '@reduxjs/toolkit';
import type { RootState } from '../store';

export interface FlywheelConfigState {
  enableLabelPropagation: boolean;
  enableSvmPropagation: boolean;
  enableSimilarityPropagation: boolean;
  enableMislabelDetection: boolean;
  questionsRatio: number;
  maxCycles: number;
  isDirty: boolean;
  advancedMode: boolean;
}

const initialState: FlywheelConfigState = {
  enableLabelPropagation: true,
  enableSvmPropagation: true,
  enableSimilarityPropagation: true,
  enableMislabelDetection: true,
  questionsRatio: 0.1,
  maxCycles: 10,
  isDirty: false,
  advancedMode: false,
};

const flywheelConfigSlice = createSlice({
  name: 'flywheelConfig',
  initialState,
  reducers: {
    toggleLabelPropagation: (state) => {
      state.enableLabelPropagation = !state.enableLabelPropagation;
      state.isDirty = true;
    },
    toggleSvmPropagation: (state) => {
      state.enableSvmPropagation = !state.enableSvmPropagation;
      state.isDirty = true;
    },
    toggleSimilarityPropagation: (state) => {
      state.enableSimilarityPropagation = !state.enableSimilarityPropagation;
      state.isDirty = true;
    },
    toggleMislabelDetection: (state) => {
      state.enableMislabelDetection = !state.enableMislabelDetection;
      state.isDirty = true;
    },
    setQuestionsRatio: (state, action: PayloadAction<number>) => {
      state.questionsRatio = action.payload;
      state.isDirty = true;
    },
    setMaxCycles: (state, action: PayloadAction<number>) => {
      state.maxCycles = action.payload;
      state.isDirty = true;
    },
    applyPreset: (state, action: PayloadAction<'manual-only' | 'svm-only' | 'default' | 'aggressive'>) => {
      switch (action.payload) {
        case 'manual-only':
          state.enableLabelPropagation = false;
          break;
        case 'svm-only':
          state.enableSvmPropagation = true;
          state.enableSimilarityPropagation = false;
          state.enableMislabelDetection = true;
          break;
        case 'default':
          state.enableLabelPropagation = true;
          state.enableSvmPropagation = true;
          state.enableSimilarityPropagation = true;
          state.enableMislabelDetection = true;
          break;
        case 'aggressive':
          state.enableLabelPropagation = true;
          state.enableSvmPropagation = true;
          state.enableSimilarityPropagation = true;
          state.enableMislabelDetection = false; // Skip filtering for more candidates
          break;
      }
      state.isDirty = true;
    },
    resetToDefaults: (state) => {
      Object.assign(state, initialState);
      state.isDirty = false;
    },
    markClean: (state) => {
      state.isDirty = false;
    },
    toggleAdvancedMode: (state) => {
      state.advancedMode = !state.advancedMode;
    },
  },
});

export const {
  toggleLabelPropagation,
  toggleSvmPropagation,
  toggleSimilarityPropagation,
  toggleMislabelDetection,
  setQuestionsRatio,
  setMaxCycles,
  applyPreset,
  resetToDefaults,
  markClean,
  toggleAdvancedMode,
} = flywheelConfigSlice.actions;

export const selectFlywheelConfig = (state: RootState) => state.flywheelConfig;

export const selectConfigPayload = (state: RootState) => ({
  enableLabelPropagation: state.flywheelConfig.enableLabelPropagation,
  enableSvmPropagation: state.flywheelConfig.enableSvmPropagation,
  enableSimilarityPropagation: state.flywheelConfig.enableSimilarityPropagation,
  enableMislabelDetection: state.flywheelConfig.enableMislabelDetection,
  questionsRatio: state.flywheelConfig.questionsRatio,
});

export default flywheelConfigSlice.reducer;
```

---

## Phase 5: Integration into Redux Store

**File**: fe/clustplorer/src/redux/store.ts

Find the store configuration and add the new reducer:

```typescript
import flywheelConfigReducer from './slices/flywheelConfigSlice';

const store = configureStore({
  reducer: {
    // ... existing reducers
    flywheelConfig: flywheelConfigReducer,
  },
});

export type RootState = ReturnType<typeof store.getState>;
export type AppDispatch = typeof store.dispatch;
```

---

## Phase 6: localStorage Persistence Utility

**File**: fe/clustplorer/src/utils/configPersistence.ts

Create this new utility file:

```typescript
import type { FlywheelConfigState } from '../redux/slices/flywheelConfigSlice';

const STORAGE_KEY = 'flywheel_config';

export function saveConfigToLocalStorage(config: FlywheelConfigState): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(config));
  } catch (error) {
    console.error('Failed to save config to localStorage:', error);
  }
}

export function loadConfigFromLocalStorage(): Partial<FlywheelConfigState> | null {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    return stored ? JSON.parse(stored) : null;
  } catch (error) {
    console.error('Failed to load config from localStorage:', error);
    return null;
  }
}

export function clearConfigFromLocalStorage(): void {
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch (error) {
    console.error('Failed to clear config from localStorage:', error);
  }
}
```

---

## Phase 7: React Component - Configuration Panel

**File**: fe/clustplorer/src/components/Flywheel/FlywheelConfigPanel.tsx

Create this new React component:

```typescript
import React, { useEffect } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import {
  toggleLabelPropagation,
  toggleSvmPropagation,
  toggleSimilarityPropagation,
  toggleMislabelDetection,
  setQuestionsRatio,
  applyPreset,
  resetToDefaults,
  selectFlywheelConfig,
  selectConfigPayload,
  markClean,
} from '../../redux/slices/flywheelConfigSlice';
import { saveConfigToLocalStorage, loadConfigFromLocalStorage } from '../../utils/configPersistence';
import { apiClient } from '../../utils/apiClient';
import './FlywheelConfigPanel.css';

interface FlywheelConfigPanelProps {
  datasetId: string;
  seedId: string;
  onStartFlywheel?: () => void;
}

export const FlywheelConfigPanel: React.FC<FlywheelConfigPanelProps> = ({
  datasetId,
  seedId,
  onStartFlywheel,
}) => {
  const dispatch = useDispatch();
  const config = useSelector(selectFlywheelConfig);
  const configPayload = useSelector(selectConfigPayload);
  const [isLoading, setIsLoading] = React.useState(false);
  const [advancedMode, setAdvancedMode] = React.useState(false);

  // Load config from localStorage on mount
  useEffect(() => {
    const saved = loadConfigFromLocalStorage();
    if (saved) {
      // Note: Dispatch individual actions to update Redux state
      if (saved.enableLabelPropagation === false) {
        dispatch(toggleLabelPropagation());
      }
      if (saved.enableSvmPropagation === false) {
        dispatch(toggleSvmPropagation());
      }
      if (saved.enableSimilarityPropagation === false) {
        dispatch(toggleSimilarityPropagation());
      }
      if (saved.enableMislabelDetection === false) {
        dispatch(toggleMislabelDetection());
      }
    }
  }, [dispatch]);

  const handleSaveAndStart = async () => {
    setIsLoading(true);
    try {
      // Save to localStorage
      saveConfigToLocalStorage(config);

      // Send to API
      const response = await apiClient.put(
        `/api/v1/flywheel/${datasetId}/start/${seedId}`,
        configPayload
      );

      dispatch(markClean());
      
      if (onStartFlywheel) {
        onStartFlywheel();
      }
    } catch (error) {
      console.error('Failed to start flywheel:', error);
      alert('Failed to start flywheel: ' + (error as Error).message);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="flywheel-config-panel">
      <h2>Flywheel Configuration</h2>

      {/* Master Control */}
      <div className="config-section master-toggle">
        <div className="toggle-group">
          <label>
            <input
              type="checkbox"
              checked={config.enableLabelPropagation}
              onChange={() => dispatch(toggleLabelPropagation())}
              className="toggle-checkbox"
            />
            <span className="toggle-label">Enable Label Propagation</span>
          </label>
          <span className="info-badge">Master Switch</span>
        </div>
      </div>

      {/* Sub-controls (only enabled if master is on) */}
      {config.enableLabelPropagation && (
        <>
          <div className="config-section">
            <h3>Propagation Stages</h3>
            
            <div className="toggle-group">
              <label>
                <input
                  type="checkbox"
                  checked={config.enableSvmPropagation}
                  onChange={() => dispatch(toggleSvmPropagation())}
                  className="toggle-checkbox"
                />
                <span className="toggle-label">SVM-based Propagation</span>
              </label>
              <span className="tooltip">Uses trained SVM model to propagate labels</span>
            </div>

            <div className="toggle-group">
              <label>
                <input
                  type="checkbox"
                  checked={config.enableSimilarityPropagation}
                  onChange={() => dispatch(toggleSimilarityPropagation())}
                  className="toggle-checkbox"
                />
                <span className="toggle-label">Similarity-based Propagation</span>
              </label>
              <span className="tooltip">Uses similarity clusters to propagate labels</span>
            </div>

            <div className="toggle-group">
              <label>
                <input
                  type="checkbox"
                  checked={config.enableMislabelDetection}
                  onChange={() => dispatch(toggleMislabelDetection())}
                  className="toggle-checkbox"
                />
                <span className="toggle-label">Mislabel Detection Filter</span>
              </label>
              <span className="tooltip">Filters out likely mislabeled candidates</span>
            </div>
          </div>

          {/* Quick Presets */}
          <div className="config-section">
            <h3>Quick Presets</h3>
            <div className="preset-buttons">
              <button 
                className="preset-btn"
                onClick={() => dispatch(applyPreset('svm-only'))}
              >
                SVM Only
              </button>
              <button 
                className="preset-btn"
                onClick={() => dispatch(applyPreset('default'))}
              >
                Standard
              </button>
              <button 
                className="preset-btn"
                onClick={() => dispatch(applyPreset('aggressive'))}
              >
                Aggressive
              </button>
            </div>
          </div>

          {/* Questions Ratio */}
          <div className="config-section">
            <label>
              Questions Ratio:
              <input
                type="range"
                min="0.01"
                max="0.5"
                step="0.01"
                value={config.questionsRatio}
                onChange={(e) => dispatch(setQuestionsRatio(parseFloat(e.target.value)))}
                className="slider"
              />
              <span className="value">{(config.questionsRatio * 100).toFixed(1)}%</span>
            </label>
          </div>
        </>
      )}

      {/* Action Buttons */}
      <div className="config-actions">
        <button
          onClick={handleSaveAndStart}
          disabled={isLoading || !config.isDirty}
          className="btn-primary"
        >
          {isLoading ? 'Starting...' : 'Save & Start Flywheel'}
        </button>
        <button
          onClick={() => dispatch(resetToDefaults())}
          className="btn-secondary"
        >
          Reset to Defaults
        </button>
      </div>

      {/* Status */}
      {config.isDirty && <div className="status-dirty">Unsaved changes</div>}
    </div>
  );
};
```

---

## Phase 8: CSS Styling

**File**: fe/clustplorer/src/components/Flywheel/FlywheelConfigPanel.css

```css
.flywheel-config-panel {
  max-width: 500px;
  padding: 20px;
  border: 1px solid #ddd;
  border-radius: 8px;
  background: #f9f9f9;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
}

.flywheel-config-panel h2 {
  margin: 0 0 20px 0;
  font-size: 18px;
  color: #222;
}

.config-section {
  margin-bottom: 20px;
  padding: 15px;
  background: white;
  border-radius: 6px;
  border-left: 4px solid #007bff;
}

.master-toggle {
  background: #e7f3ff;
  border-left-color: #0066cc;
}

.config-section h3 {
  margin: 0 0 12px 0;
  font-size: 14px;
  font-weight: 600;
  color: #333;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.toggle-group {
  display: flex;
  align-items: center;
  margin-bottom: 10px;
  gap: 12px;
}

.toggle-group label {
  display: flex;
  align-items: center;
  cursor: pointer;
  flex: 1;
}

.toggle-checkbox {
  width: 20px;
  height: 20px;
  cursor: pointer;
  accent-color: #4caf50;
}

.toggle-label {
  margin-left: 8px;
  font-size: 14px;
  color: #222;
  user-select: none;
}

.toggle-checkbox:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.tooltip {
  font-size: 12px;
  color: #666;
  margin-left: auto;
  white-space: nowrap;
}

.preset-buttons {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
  margin-bottom: 10px;
}

.preset-btn {
  padding: 8px 12px;
  font-size: 12px;
  font-weight: 600;
  border: 1px solid #ddd;
  border-radius: 4px;
  background: white;
  cursor: pointer;
  transition: all 0.2s;
}

.preset-btn:hover {
  border-color: #007bff;
  background: #e7f3ff;
}

.slider {
  width: 100%;
  height: 4px;
  border-radius: 2px;
  background: #ddd;
  outline: none;
  margin: 10px 0;
  cursor: pointer;
  -webkit-appearance: none;
  appearance: none;
}

.slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: #4caf50;
  cursor: pointer;
  transition: background 0.2s;
}

.slider::-webkit-slider-thumb:hover {
  background: #45a049;
}

.slider::-moz-range-thumb {
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: #4caf50;
  cursor: pointer;
  border: none;
}

.value {
  margin-left: 10px;
  font-weight: 600;
  color: #007bff;
  min-width: 40px;
  text-align: right;
}

.config-actions {
  display: flex;
  gap: 10px;
  margin-top: 20px;
}

.btn-primary, .btn-secondary {
  flex: 1;
  padding: 10px 16px;
  font-size: 14px;
  font-weight: 600;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-primary {
  background: #007bff;
  color: white;
}

.btn-primary:hover:not(:disabled) {
  background: #0056b3;
}

.btn-primary:disabled {
  background: #ccc;
  cursor: not-allowed;
}

.btn-secondary {
  background: white;
  color: #333;
  border: 1px solid #ddd;
}

.btn-secondary:hover {
  background: #f0f0f0;
}

.status-dirty {
  margin-top: 10px;
  padding: 8px 10px;
  background: #fff3cd;
  color: #856404;
  border-radius: 4px;
  font-size: 12px;
  text-align: center;
}

.info-badge {
  display: inline-block;
  padding: 2px 8px;
  background: #dcf0ff;
  color: #0066cc;
  border-radius: 3px;
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  margin-left: auto;
}
```

---

## Phase 9: Testing & Verification

### Backend Testing

**Step 1: Test Configuration Loading**
```bash
# Start your backend
cd c:\V-L\vl-camtek
python -m pytest tests/ -k flywheel -v
```

**Step 2: Test with cURL - Manual Only**
```bash
# Replace {dataset_id}, {seed_id} with actual IDs
DATASET_ID="..."
SEED_ID="..."
TOKEN="..."

curl -X PUT http://localhost:8000/api/v1/flywheel/${DATASET_ID}/start/${SEED_ID} \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${TOKEN}" \
  -d '{
    "questions_ratio": 0.1,
    "enable_label_propagation": false
  }' | jq .
```

**Step 3: Verify in Database**
```sql
SELECT id, config_json FROM lp_flow ORDER BY created_at DESC LIMIT 1 \G
```

Should see:
```json
{
  "enable_label_propagation": false,
  "enable_svm_propagation": true,
  "enable_similarity_propagation": true,
  "enable_mislabel_detection": true,
  ...other fields...
}
```

**Step 4: Check Logs During Cycle**
```bash
# Watch logs while flywheel runs
docker logs -f <backend_container> | grep -i "propagation\|disabled"
```

Should see messages like:
```
Label propagation disabled in configuration, skipping cycle
SVM propagation disabled in configuration
Similarity propagation disabled in configuration
```

### Frontend Testing (If UI Implemented)

**Step 1: Mount Component in Page**

In your Flywheel page component:
```typescript
<FlywheelConfigPanel
  datasetId={datasetId}
  seedId={seedId}
  onStartFlywheel={() => refetch()}
/>
```

**Step 2: Test Toggles**
- Click master toggle - should disable sub-controls
- Click sub-toggles - should update isDirty state
- Change questions ratio - should update isDirty

**Step 3: Test localStorage**
- Click "Save & Start" button
- Reload page
- Config should be restored from localStorage

**Step 4: Test Presets**
- Click each preset button
- Verify toggles update correctly

**Step 5: F12 Browser Network**
- Watch Network tab
- Click "Save & Start"
- Should see PUT request to `/api/v1/flywheel/{dataset_id}/start/{seed_id}`
- Request body should include boolean flags

---

## Rollback Plan

If something goes wrong:

1. **Revert Code Changes**:
   ```bash
   git checkout vl/algo/label_propagation/flywheel_configuration.py
   git checkout vl/algo/label_propagation/flywheel.py
   git checkout clustplorer/web/api_flywheel.py
   # And any frontend files
   ```

2. **Reset Database** (if config values are problematic):
   ```bash
   # Backup first!
   # Then clear recent lp_flow records or reset config_json to NULL
   UPDATE lp_flow SET config_json = NULL WHERE created_at > NOW() - INTERVAL 1 HOUR;
   ```

3. **Clear localStorage** (frontend):
   App will use defaults if localStorage is cleared

---

## Success Criteria

- Configuration flags appear in API requests and database
- Algorithm checks flags before executing stages
- Logs show stages being skipped when disabled
- Results differ based on enabled stages (fewer labels with less propagation)
- Frontend toggle saves to localStorage
- Can start flywheel with custom config via API

---

## Next Steps

1. Execute Phase 1-3 (Backend core functionality)
2. Test with cURL (verify API behavior)
3. Execute Phase 4-8 (Optional frontend - only if you want UI)
4. Run Phase 9 tests (Full validation)

**Questions?**
If the algorithm doesn't respect flags correctly, add print statements in flywheel.py to debug the config values being passed.
