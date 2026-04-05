# Plan: Add User-Configurable Label Propagation Toggle

**TL;DR:** Add a user preference that allows users to enable/disable label propagation features throughout the application. The preference will be stored in the database, fetched on app initialization, and can be toggled via UI. When disabled, all label propagation UI components and scenarios will be hidden/disabled.

## Current Architecture

- Label propagation is controlled by `clustplorer/logic/feature_checks.py` (`flywheel_enabled` function at line 234)
- Currently checks: global `Settings.FLYWHEEL_ENABLED` OR user email in allowlist
- Feature config is returned via `clustplorer/web/service.py` (`/api/v1/user_config` endpoint at line 52)
- Frontend uses `fe/clustplorer/src/hooks/useFeatureFlagService.tsx` hook

## Key Components That Handle Label Propagation

### Frontend Components:
- **Main Component:** `fe/clustplorer/src/views/components/LabelPropagation/index.tsx` - The main label propagation component
- **Disabled State:** `fe/clustplorer/src/views/components/LabelPropagation/DisabledLabelPropagation/index.tsx`
- **Modal:** `fe/clustplorer/src/views/modals/EvaluateLabelPropagationModal/index.tsx`
- **Toggle Buttons:** `fe/clustplorer/src/views/components/ViewToggleButtons/index.tsx` (has `showLabelPropagation` prop at line 46)

### Hooks:
- `fe/clustplorer/src/hooks/LabelPropagation/useLabelPropagation.tsx` - Main label propagation logic
- `fe/clustplorer/src/hooks/LabelPropagation/useSeed.tsx` - Seed management
- `fe/clustplorer/src/hooks/LabelPropagation/useStepsConfig.tsx` - Steps configuration

### Redux:
- `fe/clustplorer/src/redux/SingleDataset/selectors.ts` (line 1571) - Already has `getIsLabelPropagationEnabled` selector!

### Backend:
- `clustplorer/logic/feature_checks.py` (line 234) - `flywheel_enabled()` function
- `clustplorer/logic/feature_manager/calculators/flywheel_calculator.py` (line 20) - FlywheelFeatureCalculator
- `vl/common/settings.py` (line 251) - FLYWHEEL_ENABLED setting

## Implementation Steps

### 1. Database: Add User Preference Storage

- Add `label_propagation_enabled` field to user preferences/settings table
- Create migration to add the column (default: `true` for backward compatibility)
- Update user model in `vldbaccess/user.py` or create a separate user preferences DAO

**Files to modify:**
- Create new migration file in `vldbmigration/` directory
- Update `vldbaccess/user.py` or create `vldbaccess/user_preferences.py`

### 2. Backend API: Get Preference

Update `clustplorer/logic/feature_checks.py` (line 234) `flywheel_enabled()` to check user preference:

```python
def flywheel_enabled(user: User, dataset: Dataset) -> bool:
    # Check user preference first
    if not user.get_preference('label_propagation_enabled', default=True):
        return False
    
    # Existing checks...
    if dataset.embedding_config is None:
        return False  # embeddings are required to run flywheel
    elif Settings.FLYWHEEL_ENABLED:
        return True
    else:
        return user.email in Settings.FLYWHEEL_ENABLED_EMAILS
```

**Files to modify:**
- `clustplorer/logic/feature_checks.py`

### 3. Backend API: Set Preference

Create new endpoint in `clustplorer/web/service.py` or new API file:
- `PATCH /api/v1/user/preferences` - Update user preferences
- Accept JSON body: `{"label_propagation_enabled": true/false}`
- Update user preferences in database
- Return updated preferences

**Files to create/modify:**
- `clustplorer/web/api_user_preferences.py` (new) OR
- Update `clustplorer/web/service.py` with new endpoint

### 4. Frontend: Fetch Preference on App Init

- The preference will automatically come through `/api/v1/user_config` endpoint (already called on app init)
- Redux selector `fe/clustplorer/src/redux/SingleDataset/selectors.ts` (line 1571) `getIsLabelPropagationEnabled` already exists
- Ensure the user preference is included in the response from the backend

**Files to verify:**
- `fe/clustplorer/src/redux/SingleDataset/selectors.ts` - verify selector works with new data
- App initialization code - verify `/api/v1/user_config` is called

### 5. Frontend: Add UI Toggle

Add toggle in Settings page or User menu:
- Use `useSelector(getIsLabelPropagationEnabled)` to get current value
- On toggle change, call `PATCH /api/v1/user/preferences` API
- Update Redux state after successful API call

**Files to modify:**
- Create Settings page component OR
- Add to existing User menu/profile page
- Create API hook: `fe/clustplorer/src/hooks/useUpdateUserPreferences.tsx`
- Update Redux actions: `fe/clustplorer/src/redux/SingleDataset/actions.ts` (or create user preferences actions)

### 6. Frontend: Disable Label Propagation UI

Update components to check the flag before rendering label propagation features:

**Primary Component:**
- `fe/clustplorer/src/views/components/LabelPropagation/index.tsx` (line 56) - Already checks `LabelPropagationBehavior.enabled`

**Other Components to Check:**
- Hide label propagation button in navigation/tabs where it appears
- Hide `fe/clustplorer/src/views/modals/EvaluateLabelPropagationModal/index.tsx` modal when flag is disabled
- Hide label propagation toggle in `fe/clustplorer/src/views/components/ViewToggleButtons/index.tsx` (line 46) - already has `showLabelPropagation` conditional
- Disable annotation workflows that trigger label propagation
- Search for all usages of label propagation and add conditional checks

**Pattern to use:**
```typescript
import { useSelector } from "react-redux";
import { getIsLabelPropagationEnabled } from "redux/SingleDataset/selectors";

const isLabelPropagationEnabled = useSelector(getIsLabelPropagationEnabled);

if (!isLabelPropagationEnabled) {
  // Hide or disable label propagation features
  return null;
}
```

## Verification Checklist

- [ ] Toggle the setting in UI → verify database is updated
- [ ] Refresh page → verify setting persists
- [ ] Disable setting → verify all label propagation UI is hidden
- [ ] Enable setting → verify label propagation UI appears
- [ ] Test in annotation workflow → verify label propagation scenarios respect the flag
- [ ] Test during dataset exploration
- [ ] Test in data page with enrichment cards
- [ ] Verify API endpoint returns correct preference
- [ ] Verify preference updates are saved to database

## Design Decisions

1. **Store preference at user level** (not dataset level) - user has global control across all datasets
2. **Default to `true`** for backward compatibility - existing users will see no change
3. **Use existing feature flag infrastructure** (`/api/v1/user_config`) rather than separate API for fetching
4. **Create separate endpoint for updating** preferences (`PATCH /api/v1/user/preferences`)
5. **Backend controls the preference** - frontend only displays/updates based on backend response

## Additional Considerations

### Backend Tasks:
- Task type `LABEL_PROPAGATION` exists in `vldbaccess/tasks/base/enums.py`
- Flywheel task service manages label propagation tasks
- Consider if running tasks should be handled when user disables the flag

### Security:
- Ensure user can only update their own preferences
- Validate input when updating preferences

### Performance:
- Preference check should be fast (cached in user object)
- No additional database queries per request if cached properly

### Error Handling:
- Handle API failures gracefully when updating preferences
- Show user-friendly error messages
- Rollback UI state if API call fails
