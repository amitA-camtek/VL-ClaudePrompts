Here’s a refined prompt tailored specifically for **React (with TypeScript)** that you can give to Claude:

---

### Prompt for Claude

Build a **Wafer Navigator UI component** using **React + TypeScript**. This component should simulate a semiconductor wafer inspection interface.

---

### Core Requirements

#### 1. Layout

* Create a two-panel layout:

  * **Left:** Wafer Map
  * **Right:** Die Detail View

Use flexbox or grid for layout.

---

#### 2. Wafer Map (Left Panel)

* Render a **circular wafer grid** using SVG or divs.
* Each cell represents a **die**.
* Only render dies inside the circular boundary.
* Each die should:

  * Display a **defect count**
  * Be **color-coded** based on defect severity:

    * Green (0–1)
    * Yellow (2–3)
    * Red (4+)
* Add wafer tabs at the top:

  * "Wafer 01", "Wafer 02"

#### Interaction

* Clicking a die:

  ```ts
  onDieClick(die: Die): void
  ```
* Updates the selected die in state and refreshes the right panel.

---

#### 3. Die Map (Right Panel)

* Displays details for the selected die:

  * Title: `Die (x, y)`
  * Defect count

* Render a **scatter plot (SVG)** of defects:

  * Each defect has:

    * x, y coordinates
    * type: `"Surface"` or `"Bump"`

* Use:

  * Different colors for each defect type
  * A legend

* Include axis labels in micrometers (µm)

---

#### 4. Data Model

```ts
type Defect = {
  id: string;
  x: number;
  y: number;
  type: "Surface" | "Bump";
};

type Die = {
  id: string;
  x: number;
  y: number;
  defectCount: number;
  defects: Defect[];
};

type Wafer = {
  id: string;
  name: string;
  dies: Die[];
};
```

---

#### 5. Component Structure

* `WaferNavigator` (parent container)
* `WaferTabs`
* `WaferMap`
* `DieMap`

Use React hooks for state management.

---

#### 6. Behavior

* Default: no die selected
* Clicking a die → updates right panel
* Switching wafer:

  * resets selected die
* Add hover highlight for dies

---

#### 7. Styling

* Dark UI theme
* Subtle grid + glow effects
* Rounded containers
* Highlight selected die
* use the style of the app

You may use:

* CSS modules, styled-components, or plain CSS

---

#### 8. Storybook

Create stories:

* `Default`
* `MultipleWafers`
* `HighDefectDensity`
* `NoSelection`

Add controls for:

* Switching wafers
* Selecting dies

---

#### 9. Constraints

* React + TypeScript only
* Use the stlye of the application
* Functional components
* No heavy chart libraries (use SVG)
* Clean, modular, reusable code

---

#### 10. Output

Return:

1. Full React component code
2. Mock data
3. Storybook stories
4. Styles

---

#### Bonus (optional)

* Zoom/pan wafer
* Tooltip on hover
* Smooth transitions

