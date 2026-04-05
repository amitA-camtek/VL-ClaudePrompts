# Prompt Series 02 — Feature: Enable Classification After Label Propagation

> **Feature name:** `enableClassificationAfterLabelPropagation`  
> **Purpose:** Send these prompts to Claude in order, one at a time.  
> Each prompt builds on the previous response.  
> At the end Claude will evaluate all solutions and produce a single design+plan document using the `system.md` template.

---

## Background (read before sending any prompt)

**Current behavior:**  
After label propagation runs, images receive propagated labels. At that point, the system does **not** allow re-classification of those images — the classify action is blocked or unavailable.

**Desired behavior:**  
A new toggle button ("Enable Classification After Label Propagation") should allow the user to re-enable classification on already-propagated images.

**UI spec:**
- Location: top-right corner of the screen, next to the existing "Train Model" button
- Visibility rule: only shown when `dataset` is ready AND `flywheelStatus === "COMPLETED"`
- Behavior: toggle on/off; toggled state persists in the database
- Stack: React (frontend) + Python (backend)

---

## Prompt 1 — Understand the Current Label Propagation & Classification Flow

```
I need to add a new feature to our system. Before proposing solutions, I need you to deeply understand the relevant existing code.

**Feature context:**
After label propagation runs, images receive propagated labels.
Currently, classification cannot be re-triggered on those images after propagation is complete.
We want to introduce a toggle that enables/disables the ability to re-classify images after label propagation.

Please explore the codebase and answer the following:

1. **Label propagation flow** — what triggers label propagation? Trace the full call chain:
   - Which UI component / button triggers it?
   - Which API endpoint is called (method + path)?
   - Which Python handler handles it?
   - What does it write to the DB? Which table(s) and field(s)?
   - What is the final state of an image record after propagation? List all relevant fields.

2. **Classification flow** — how is initial classification triggered?
   - Which UI component / button triggers it?
   - Which API endpoint (method + path)?
   - Which Python handler?
   - What DB fields does it read/write?

3. **`flywheelStatus` field** — where is this field stored (table name, field name)?
   - What are all its possible values?
   - What sets it to `"COMPLETED"`?
   - Where is it read on the frontend?

4. **Dataset "ready" state** — what exactly does "dataset is ready" mean in the data model?
   - Which field(s) and table determine this?
   - Where is this checked on the frontend?

5. **"Train Model" button** — which React component renders it? What is its exact location in the file?

If anything is unclear, mark it with [UNCLEAR].
```

---

## Prompt 2 — Identify All Touch Points for the New Feature

```
Based on what you found in prev Prompt, now list ALL the places in code that will need to change to implement the "Enable Classification After Label Propagation" toggle.

Produce a table like this:

| Layer | File path | Exact location (function / component / line range) | Change needed | Risk |
|-------|-----------|-----------------------------------------------------|---------------|------|

Cover at minimum:
- Database: new field or new table to persist the toggle state
- Backend model / ORM: update to reflect DB change
- Backend API: new or modified endpoint to read/write the toggle state
- Backend classification logic: guard that checks the toggle before allowing re-classification
- Frontend store / state: where the toggle state is held in React
- Frontend API call: fetch and update the toggle state
- Frontend component: the toggle button itself (where it lives next to "Train Model")
- Frontend visibility logic: the condition `dataset ready AND flywheelStatus === "COMPLETED"`

If there are other touch points, add them.
If anything is unclear, mark it with [UNCLEAR].
```

---

## Prompt 3 — Propose Multiple Solutions

```
Now propose **3 distinct solutions** for implementing the "Enable Classification After Label Propagation" toggle.

The solutions should differ meaningfully in their approach — for example:
- Where the toggle state is stored (new column on existing table vs. new table vs. a settings/config table)
- How the backend enforces the toggle (middleware vs. handler-level guard vs. service-layer check)
- How the frontend reads the toggle state (on-demand fetch vs. included in existing dataset/flywheel status response vs. global app config endpoint)

For each solution, provide:

### Solution [N]: [Short Name]

**Summary:** One paragraph describing the approach.

**Database changes:**
- Exact table name(s) affected
- New column name, type, default value, nullable?
- Migration strategy (Alembic revision? raw SQL?)

**Backend changes:**
- New or modified endpoints (method + path + request body + response body)
- New or modified Python functions/classes
- Where the toggle is enforced (which function checks it before classification runs)

**Frontend changes:**
- New or modified React component(s) (file path + component name)
- New or modified API call(s)
- State management changes (store slice / context)
- Exact render condition for the toggle button

**Risks & downsides:**

**Estimated complexity:** Low / Medium / High

If anything is unclear, mark it with [UNCLEAR].
```

---

## Prompt 4 — Evaluate Solutions & Select the Best One

```
Now evaluate the 3 solutions you proposed against these criteria:

| Criterion | Weight |
|-----------|--------|
| Minimal blast radius — fewest files changed | High |
| No breaking changes to existing API contracts | High |
| Toggle state survives server restarts (persisted in DB) | Required |
| Toggle is per-dataset (not global) | Required |
| Easy to test (unit + integration) | Medium |
| Easy to revert if the feature is disabled | Medium |
| Performance — no extra DB query on every classify request | Medium |

Produce a scoring table:

| Criterion | Solution 1 | Solution 2 | Solution 3 |
|-----------|------------|------------|------------|
| ... | | | |
| **Total** | | | |

Then declare a winner and explain why in 3–5 sentences.

Name the winning solution **"The Chosen Approach"** — all subsequent prompts will build on it.

If anything is unclear, mark it with [UNCLEAR].
```

---

## Prompt 5 — Detailed Backend Design (The Chosen Approach)

```
Using The Chosen Approach, produce the full backend design.

**Database schema change:**
- Write the exact Alembic migration `upgrade()` and `downgrade()` functions (Python).
- Specify: table name, column name, type, default, nullable, index (if any).

**ORM model update:**
- Show the exact lines to add to the SQLAlchemy (or other ORM) model class.

**API contract:**
For each new or modified endpoint, provide:
```
METHOD /exact/path
Request headers: ...
Request body (JSON): { field: type, ... }
Response body (JSON): { field: type, ... }
HTTP status codes: 200 / 400 / 404 / 409 / ...
Auth required: yes/no
```

**Business logic:**
- Show the exact Python function that checks the toggle before allowing classification.
- Show where in the existing call chain this check is inserted.
- What happens when classification is attempted and the toggle is OFF? (error code, message)

**Tests to write:**
- List unit test cases (function name + what it tests).
- List integration test cases (endpoint + scenario).

If anything is unclear, mark it with [UNCLEAR].
```

---

## Prompt 6 — Detailed Frontend Design (The Chosen Approach)

```
Using The Chosen Approach, produce the full frontend design.

**New component: Toggle button**
- File path (where to create it)
- Component name
- Props interface (TypeScript types)
- Exact render condition: `dataset?.status === "[EXACT_VALUE]" && flywheelStatus === "COMPLETED"`
- Position: right of the "Train Model" button — show the exact JSX/TSX insertion point in the parent component
- Visual design: describe the toggle (checked = classification enabled, unchecked = disabled; label text; disabled appearance when condition is not met)

**State management:**
- Where is `enableClassificationAfterLabelPropagation` stored? (which store slice / context / local state)
- Initial value and how it is loaded (on component mount? as part of dataset fetch?)
- How it is updated when the user toggles

**API integration:**
- Exact fetch call to GET the current toggle state (endpoint, when called, how result is stored)
- Exact fetch call to PUT/PATCH the toggle state when the user changes it (endpoint, payload, optimistic update strategy)
- Error handling: what happens if the API call fails?

**Tests to write:**
- List unit test cases for the toggle component (scenario + expected behavior).
- List integration test cases (simulate user toggling → API called → state updated).

If anything is unclear, mark it with [UNCLEAR].
```

---

## Prompt 7 — Step-by-Step Implementation Plan

```
Now produce a sequenced, day-by-day implementation plan for The Chosen Approach.

Format each task as:

| # | Task | Layer | File(s) | Depends on | Done when |
|---|------|-------|---------|------------|-----------|

Order the tasks so that:
1. Database migration runs first
2. Backend model + logic changes follow
3. Backend API endpoint is added/modified
4. Backend tests are written and passing
5. Frontend state & API integration follows
6. Frontend toggle component is added
7. Frontend tests are written and passing
8. End-to-end smoke test is described

Also flag:
- Any task that requires a deployment / DB migration to run before another PR can merge
- Any task that can be done in parallel by a second developer

If anything is unclear, mark it with [UNCLEAR].
```

---

## Final Prompt — Produce the Feature Design Document

```
You now have a complete design for the "Enable Classification After Label Propagation" feature.

After your analysis, produce a **single Markdown document** structured exactly as the `systemTemplate.md` template.
Be thorough. If something is unclear, mark it with `[UNCLEAR]` rather than guessing.
Do NOT summarize broadly — go deep. I need specifics: exact service names, exact endpoint paths, exact port numbers, exact DB field names, exact component file paths.

Use this template exactly:

---

# ClassificationAfterLabelPropagation.md — Enable Classification After Label Propagation — Feature Design

> Last updated: [DATE]
> Feature branch: [branch name]

## 1. Project Overview
[Describe the feature, why it exists, and what problem it solves]

## 2. Repository Structure
[Show only the files that will be created or modified]

## 3. Services Inventory
[Backend service: entry point, port, DB, relevant env vars]
[Frontend: entry point, dev port, build tool]

## 4. Communication Map
### 4.1 Synchronous (HTTP REST)
[New/modified endpoints for the toggle state]
### 4.2 Asynchronous (Events / Queues)
[Any events emitted or consumed as a result of toggle change]

## 5. Domain Entities & Ownership
[New or modified DB entities and their fields]

## 6. External Dependencies
[Any new dependencies introduced]

## 7. Auth & Security
[How the new endpoint is protected, who can change the toggle]

## 8. Infrastructure & DevOps
[Migration steps, feature flag, rollback plan]

## 9. Key Business Flows
[Flow: User enables classification after propagation]
[Flow: User attempts to classify after propagation when toggle is OFF]

## 10. Architecture Risks & Notes
[Risks of the chosen approach, edge cases]

## 11. Conventions & Standards
[Naming of new field, new component, new endpoint — must match existing conventions]

## 12. Glossary
[Label Propagation, flywheelStatus, enableClassificationAfterLabelPropagation]

---

Fill every section completely based on what you have learned in prev Prompts.
```

---

## Implementation Prompt — Write the Real Code

> **Send this prompt AFTER the Final Prompt above is complete and you are satisfied with the design document.**  
> Paste the full design document into `[PASTE DESIGN DOCUMENT HERE]` before sending.

```
You are now going to implement the "Enable Classification After Label Propagation" feature end-to-end.

Here is the approved design document:

ClassificationAfterLabelPropagation.md


**Instructions — follow these exactly:**

1. **Database migration** — write the complete Alembic migration file.
   - File path: follow the exact convention of existing migrations in this project.
   - Include `upgrade()` and `downgrade()`.
   - Do not change any existing columns.

2. **Backend model** — show the exact diff (lines to add) to the existing ORM model.
   - Do not rewrite the whole file. Show only the lines that change, with 3 lines of context above and below.

3. **Backend endpoint** — implement the new or modified API endpoint(s).
   - Follow the exact coding style, decorator pattern, and error-handling pattern used in existing route files.
   - Include the Pydantic request/response schemas.
   - Do not add any endpoint that was not in the design document.

4. **Backend guard / service logic** — implement the toggle check in the classification service.
   - Show the exact diff. Do not rewrite functions that don't change.
   - If the toggle is OFF and classification is attempted, return the exact HTTP status and error message from the design document.

5. **Frontend API client** — add the GET and PATCH calls for the toggle state.
   - Follow the exact pattern of existing API calls in the project (same fetch wrapper / axios instance / React Query hook style).

6. **Frontend state** — add the toggle state to the store or context.
   - Show only the lines that change, with context.

7. **Frontend toggle component** — create the new component file.
   - TypeScript + React functional component.
   - Use the same UI library (component imports) already used in the project — do not introduce new dependencies.
   - The component must:
     - Be invisible when `dataset` is not ready OR `flywheelStatus !== "COMPLETED"`
     - Call the PATCH endpoint on change
     - Show a loading state while the API call is in flight
     - Show an error toast / message if the API call fails (use the same toast/notification pattern as the rest of the app)

8. **Parent component edit** — show the exact JSX lines to add the toggle component next to the "Train Model" button.
   - Show exact insertion point with 3 lines of context above and below.

9. **Tests** — write all tests listed in the design document.
   - Backend: pytest style, follow existing test file conventions.
   - Frontend: follow existing test file conventions (Jest + React Testing Library or Vitest).

**Output format:**
For each file, output a fenced code block with the language tag and file path in the header comment:

```python
# backend/alembic/versions/xxxx_add_enable_classification_toggle.py
[full file content]
```

```typescript
// frontend/src/components/ClassificationToggle.tsx
[full file content]
```

For diffs (cases 2, 4, 6, 8), use a unified diff block:

```diff
# backend/app/models/dataset.py
 [unchanged line]
 [unchanged line]
+[added line]
 [unchanged line]
```

**Rules:**
- Do NOT invent field names, component names, or endpoint paths that differ from the design document.
- Do NOT add features beyond what is in the design document.
- Do NOT change unrelated files.
- If you are unsure about a detail that was marked [UNCLEAR] in the design document, stop and ask before writing code.
- After writing all files, print a checklist:

  - [ ] Alembic migration written
  - [ ] ORM model updated
  - [ ] Backend endpoint(s) implemented
  - [ ] Backend guard logic implemented
  - [ ] Frontend API calls added
  - [ ] Frontend state updated
  - [ ] Toggle component created
  - [ ] Parent component updated
  - [ ] Backend tests written
  - [ ] Frontend tests written
```
