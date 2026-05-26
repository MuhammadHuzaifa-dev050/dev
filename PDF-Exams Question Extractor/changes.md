# Summary of Changes - Exam Paper Question Extractor

We have significantly upgraded the question extractor script to handle complex exam layouts, multi-figure structures, math expressions, tables, and nested question parts (such as roman numeral sub-parts).

Below is a detailed breakdown of the enhancements, fixes, and architectural changes implemented.

---

## 1. Spatial Proximity Merging Engine
- **Old Behavior**: Relied on isolated text blocks, which caused equations, formulas (fractions, exponents), and diagrams to be split into separate, incomplete crops.
- **New Behavior**: Implemented a **Dual-Track Gathering** process that scans for text, drawings, and raster images. The layout elements are sorted top-to-bottom and dynamically merged using adaptive vertical gap thresholds.

## 2. Strict Boundary Constraints & Over-cropping Avoidance
- **Strict Vertical Gap**: Set `MAX_VERTICAL_GAP` to a strict **25 points**. This closes the crop box immediately when encountering the blank answer space/student working area.
- **Hard Stop on Markers**: The look-ahead loop terminates instantly when encountering *any* new question number or sub-part identifier (e.g. `(b)`, `(ii)`, `Question 13`, etc.). This prevents two distinct questions or parts from sharing the same cropped image.

## 3. Coordinate-Based Header & Footer Filtering
- **Old Behavior**: Relied on simple keyword matches that frequently failed or let header/footer lines bleed into the question crops.
- **New Behavior**: Implemented a strict coordinate filter that strips out all elements situated in header/footer zones (`y0 < 50.0 pt` or `y1 > Page Height - 50.0 pt`).

## 4. Table & Grid Line Recovery
- **Old Behavior**: Discarded straight horizontal drawing lines (height = 0) and vertical lines (width = 0), splitting tables and histograms in half.
- **New Behavior**: Modified the graphic validation check to only ignore collapsed elements when *both* dimensions are zero (points) or negative, fully retaining all table cell lines and histogram grid drawings.

## 5. Table Range Alphanumeric Filtering
- **Old Behavior**: Number ranges like `"11 to 15"` at the left margin of tables were misidentified as main question markers (e.g. Question 11).
- **New Behavior**: Refined the regex validation in `detect_question_label` to reject numbers followed by lowercase words on the same line (like `"to"`, `"goals"`, etc.).

## 6. Hierarchical Parent-Coordinate Tracking
- **Old Behavior**: Prepending the parent question introduction to the first sub-part (`part_a`, `part_i`) always fell back to the main question coordinate. This caused sub-parts under part `(b)` to incorrectly prepend part `(a)`'s diagrams.
- **New Behavior**: Added a level classification system (Level 1: Main Q, Level 2: alphabetical parts, Level 3: roman numeral parts) and a registry to track coordinates per level. A sub-part now prepends its immediate hierarchical parent (e.g., `(i)` inherits the start coordinate of `(b)`).

## 7. Answer-Slot-Aware Look-Ahead & Multi-Figure Bridging
- **Old Behavior**: Rigid gap limits caused questions containing multiple figures separated by text to be cut in half.
- **New Behavior**: Added state tracking for answer slots:
  - **Before the answer slot is reached**: The gap limit is relaxed to `200.0 pt` for diagrams and `120.0 pt` for bridging text, ensuring multiple figures are successfully merged.
  - **Once the answer slot is reached**: The gap limit reverts to `25.0 pt` strictly, preserving multi-line answer lines but immediately stopping before blank working spaces.
