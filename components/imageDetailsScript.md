Create a React component for an image annotation tool with bounding box drawing functionality.

Requirements:

1. Layout:
- use the style of the system.
- Left side: display an image.
- Overlay a transparent drawing layer on top of the image (canvas or div).
- Right/top: an "Image Details" panel showing:
  - ID
  - Dimensions
  - Captured date
  - Camera
- Bottom: a table titled "Defects in this tile" with columns:
  Class, X (px), Y (px), W (px), H (px), Conf,
  the table contains the defects

2. defects Bounding Box (Defects) tool Functionality:
- the defects (Bounding Box) shell display on the image and on the table
- User can click and drag on the image to draw Bounding Box.
- Bounding Box should:
  - Be visible with a bright outline (e.g., green)
  - Store coordinates (x, y, width, height)
- Allow multiple boxes.
- Show boxes persistently after drawing.
- allow selecting and deleting a Bounding Box.

3. State Management:
- Store bounding boxes in React state.
- Each box should include:
  {
    id,
    x,
    y,
    width,
    height,
    class (default "Surface"),
    confidence (mock value)
  }

4. Interaction:
- Mouse down → start drawing
- Mouse move → update rectangle
- Mouse up → finalize box
- Coordinates should be relative to the image

5. Table Sync:
- The table should dynamically display all bounding boxes.
- Each row reflects one box.

6. Tech Constraints:
- Use functional React components with hooks.
- No external drawing libraries (no fabric.js, no konva).
- Use plain HTML5 canvas or absolutely positioned divs.
- Keep code clean and modular.

7. Styling:
- Use CSS (or Tailwind if preferred).
- Dark theme:
  - Background: dark navy/gray
  - Accent: teal/green for boxes
- Make it look like a professional inspection/annotation tool.

8. Deliverables:
- Full working React component (single file is fine).
- Include styles.
- Include sample image URL.
- Code should be runnable in a standard React app.

Bonus:
- Add a "Clear All" button
- Add simple box labels rendered on top of each rectangle