#!/usr/bin/env python3
"""
Exam Paper Question Extractor (Spatial Proximity Merging Version)
-----------------------------------------------------------------
This script parses digital, searchable exam paper PDFs to identify individual
questions and their sub-parts, and crops them as full-width screenshots.
Instead of relying on isolated text blocks, it uses a Spatial Proximity Merging
algorithm to combine text segments, tall math formulas (fractions, exponents),
and adjacent diagrams (graphs, vectors) into cohesive question boxes.

It excludes headers/footers based on page coordinates, filters out page backgrounds,
omits blank answer lines/working spaces, and dynamically detects boundaries to avoid
over-cropping.

Dependencies:
  pip install pymupdf pillow
"""

import os
import re
import sys
from pathlib import Path
from typing import Optional, Tuple, List

# Gracefully import required external libraries and provide instructions on failure.
try:
    import fitz  # PyMuPDF
except ImportError:
    print(
        "Error: PyMuPDF is not installed. Please install it using 'pip install pymupdf'.",
        file=sys.stderr,
    )
    sys.exit(1)

try:
    from PIL import Image
except ImportError:
    print(
        "Error: Pillow is not installed. Please install it using 'pip install pillow'.",
        file=sys.stderr,
    )
    sys.exit(1)


class Element:
    """
    Represents a layout element extracted from a PDF page (text, image, or drawing).
    Stores coordinates in PDF points (1/72 inch).
    """
    def __init__(self, bbox: Tuple[float, float, float, float], el_type: str, text: str = ""):
        self.x0, self.y0, self.x1, self.y1 = bbox
        self.type = el_type  # 'text', 'image', or 'drawing'
        self.text = text

    @property
    def bbox(self) -> Tuple[float, float, float, float]:
        return (self.x0, self.y0, self.x1, self.y1)

    def __repr__(self):
        return f"Element({self.type}, bbox=({self.x0:.1f}, {self.y0:.1f}, {self.x1:.1f}, {self.y1:.1f}), text={repr(self.text[:20])})"


def sanitize_filename(filename: str) -> str:
    """
    Remove illegal filesystem characters and normalize spaces.

    Args:
        filename: The original string to sanitize.

    Returns:
        A sanitized string safe to use as a file name across OS systems.
    """
    # Replace illegal characters: \ / : * ? " < > | .
    sanitized = re.sub(r'[\\/*?:"<>|.]', '', filename)
    # Replace whitespace sequences with a single underscore
    sanitized = re.sub(r'\s+', '_', sanitized)
    return sanitized.strip("_") or "unnamed_block"


def is_valid_graphic(bbox: Tuple[float, float, float, float], page_width: float, page_height: float) -> bool:
    """
    Filters out background shading, page borders, and drawing elements that
    are too large or completely outside the printable page coordinates.

    Args:
        bbox: Bounding box tuple (x0, y0, x1, y1) in PDF points.
        page_width: Physical width of the page in PDF points.
        page_height: Physical height of the page in PDF points.

    Returns:
        True if the graphic boundary is a valid question diagram element, False otherwise.
    """
    x0, y0, x1, y1 = bbox
    w = x1 - x0
    h = y1 - y0

    # Ignore collapsed/degenerate bounds (e.g. single points where both dimensions are 0, or negative)
    if w < 0 or h < 0:
        return False
    if w == 0 and h == 0:
        return False

    # Ignore page-level borders or background fills (spanning > 90% of page)
    if w > 0.9 * page_width and h > 0.9 * page_height:
        return False

    # Ignore coordinates completely out of bounds
    if x1 < 0 or y1 < 0 or x0 > page_width or y0 > page_height:
        return False

    return True


def is_table_like(text: str) -> bool:
    """
    Checks if a text block exhibits properties of a table row or column structure.
    Typically, table rows have multiple words/digits separated by tabs or multiple spaces.
    """
    cleaned = text.strip()
    if not cleaned:
        return False
    # Match multiple text segments separated by a tab or 3+ spaces (common column separators)
    if '\t' in cleaned or re.search(r'\S+\s{3,}\S+', cleaned):
        return True
    # Match 3 or more short blocks separated by double spaces
    parts = re.split(r'\s{2,}', cleaned)
    if len(parts) >= 3:
        return True
    return False


def is_answer_slot(text: str) -> bool:
    """
    Detects if a text block represents an answer slot or mark allocation
    (e.g., contains '[2]' or dotted/underscore lines).
    These always belong to the end of a question/part and should not be
    absorbed by a subsequent question's look-back loop.
    """
    cleaned = text.strip()
    if not cleaned:
        return False
    # Check for mark allocation brackets, e.g., [2], [1], [12]
    if re.search(r'\[\d+\]', cleaned):
        return True
    # Check for dotted or underscore answer lines
    if re.search(r'\.{5,}', cleaned) or re.search(r'_{5,}', cleaned):
        return True
    return False


def get_sub_part_level(sub_part: Optional[str]) -> int:
    """
    Determines the hierarchical level of a sub-part label.
    - Level 1: Main question
    - Level 2: Alphabetic subpart (e.g. a, b)
    - Level 3: Roman numeral or digit sub-subpart (e.g. i, ii, 1, 2)
    """
    if not sub_part:
        return 1
    # Check roman numerals (i, ii, iii, iv, v, vi, etc.)
    if re.match(r'^[ivx]+$', sub_part, re.IGNORECASE):
        return 3
    # Check digits (1, 2, 3, etc.)
    if sub_part.isdigit():
        return 3
    # Check alphabetic letters (a, b, c, etc.)
    if sub_part.isalpha():
        return 2
    return 2


def detect_question_label(text: str, x0: float) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Analyzes the text block content to check if it represents a main question,
    a subpart, or both at the beginning of the text.

    Args:
        text: The text content of the layout block.
        x0: The left coordinate of the layout block.

    Returns:
        A tuple of (type, main_q_num, sub_part_label):
        - ('both', main_q_num, sub_part_label) if both are found in the block.
        - ('main', main_q_num, None) if only a main question is found.
        - ('sub', None, sub_part_label) if only a subpart is found.
        - (None, None, None) if no pattern matches.
    """
    cleaned = text.strip()
    if not cleaned:
        return None, None, None

    # Pattern 1: Both main question and sub-part on the same starting block (e.g. "Question 1(a)", "Q2 b)", "1\n(a)")
    both_pattern = r'^(?:Question|Q|Q\.)?\s*(\d+)\s*\n?\s*(?:\(([a-zA-Z0-9]+)\)|([a-zA-Z0-9]+)\))\s*'
    both_match = re.match(both_pattern, cleaned, re.IGNORECASE)
    if both_match:
        main_q = both_match.group(1)
        sub_part = both_match.group(2) or both_match.group(3)
        has_prefix = re.match(r'^(?:Question|Q|Q\.)', cleaned, re.IGNORECASE) is not None
        # Verify it's a valid question position (left margin x0 < 70) and reasonable range
        if has_prefix or (x0 < 70 and int(main_q) < 50):
            # Check for range patterns like "11 to 15"
            remaining = cleaned[both_match.end():].strip()
            if remaining:
                first_char = remaining[0]
                if first_char.islower():
                    first_word_match = re.match(r'^([a-zA-Z]+)\b', remaining)
                    if first_word_match:
                        first_word = first_word_match.group(1)
                        if first_word.islower() and first_word not in ('x', 'y', 'z', 'a', 'b', 'c'):
                            return None, None, None
            return 'both', main_q, sub_part

    # Pattern 2: Main question only (e.g., "Question 1", "Q2", "3\nThe equation...")
    main_pattern = r'^(?:Question|Q|Q\.)?\s*(\d+)\b'
    main_match = re.match(main_pattern, cleaned, re.IGNORECASE)
    if main_match:
        main_q = main_match.group(1)
        has_prefix = re.match(r'^(?:Question|Q|Q\.)', cleaned, re.IGNORECASE) is not None
        if has_prefix or (x0 < 70 and int(main_q) < 50):
            # Check the characters after the number to make sure it's not a range like "11 to 15"
            remaining = cleaned[main_match.end():].strip()
            if remaining:
                first_char = remaining[0]
                if first_char.islower():
                    first_word_match = re.match(r'^([a-zA-Z]+)\b', remaining)
                    if first_word_match:
                        first_word = first_word_match.group(1)
                        if first_word.islower() and first_word not in ('x', 'y', 'z', 'a', 'b', 'c'):
                            return None, None, None
            return 'main', main_q, None

    # Pattern 3: Sub-part only (e.g., "(a)", "b)", "(i)", "ii)", "(1)", "2)")
    # We restrict sub-parts to be positioned on the left side of the page (x0 < 200)
    # to avoid false matches on text citations, parentheses, or definitions inside formulas.
    sub_pattern = r'^(?:\(([a-zA-Z0-9]+)\)|([a-zA-Z0-9]+)\))(?:\s+|$)'
    sub_match = re.match(sub_pattern, cleaned)
    if sub_match:
        sub_part = sub_match.group(1) or sub_match.group(2)
        if len(sub_part) <= 3 and x0 < 200:
            return 'sub', None, sub_part

    return None, None, None


def extract_questions_from_pdf(
    pdf_path: str,
    output_dir: str,
    dpi: int = 150,
    vertical_padding: int = 15,
    max_vertical_gap: float = 25.0,
    poppler_path: Optional[str] = None
) -> List[str]:
    """
    Scans a searchable PDF exam paper, identifies questions and their sub-parts,
    merges them using a Spatial Proximity Merging algorithm, and crops screenshots.

    Args:
        pdf_path: Path to the input PDF file.
        output_dir: Directory where the cropped images will be saved.
        dpi: Resolution (dots per inch) to render PDF pages. Default is 150.
        vertical_padding: Pixel padding buffer added to top and bottom of crop.
        max_vertical_gap: Maximum vertical distance in points between consecutive elements
                           to consider them part of the same question crop.
        poppler_path: Optional directory containing Poppler binaries (unused but kept for API parity).

    Returns:
        List of paths to the extracted image files.
    """
    pdf_file = Path(pdf_path)
    if not pdf_file.exists():
        raise FileNotFoundError(f"PDF file not found at {pdf_path}")

    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    print(f"Opening PDF: {pdf_file.name}")
    doc = fitz.open(pdf_path)

    extracted_images = []
    current_main_question = "unknown"

    # Process page-by-page to manage memory footprint and coordinate scaling
    for page_idx in range(len(doc)):
        page_num = page_idx + 1
        page = doc[page_idx]
        print(f"Processing Page {page_num}/{len(doc)}...")

        # 1. Render the current page to a PIL Image at specified DPI
        try:
            zoom = dpi / 72
            matrix = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=matrix)
            page_image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        except Exception as e:
            print(f"Error rendering page {page_num}: {e}")
            continue

        pdf_w = page.rect.width
        pdf_h = page.rect.height
        img_w, img_h = page_image.size

        # Scaling factors from PDF points to Pixels
        scale_x = img_w / pdf_w
        scale_y = img_h / pdf_h

        # 2. Extract and compile page elements (Dual-Track Gathering)
        elements: List[Element] = []

        # Track 1: Text Blocks
        blocks = page.get_text("blocks")
        for b in blocks:
            x0, y0, x1, y1, text, block_no, block_type = b
            if block_type != 0:
                continue
            
            # Rule 3: Strip headers & footers by coordinates (y0 < 50 or y1 > pdf_h - 50)
            if y0 < 50.0 or y1 > (pdf_h - 50.0):
                continue
                
            # Filter out blank answer lines/student working spaces (consisting of dots, underscores, spaces)
            cleaned_text = text.strip()
            if re.match(r'^[._\s-]+$', cleaned_text):
                continue
                
            elements.append(Element((x0, y0, x1, y1), 'text', text))

        # Track 2: Images (Raster graphics)
        try:
            images = page.get_image_info()
            for img in images:
                bbox = img.get("bbox")
                if bbox and is_valid_graphic(bbox, pdf_w, pdf_h):
                    x0, y0, x1, y1 = bbox
                    # Rule 3: Strip headers & footers by coordinates
                    if y0 < 50.0 or y1 > (pdf_h - 50.0):
                        continue
                    elements.append(Element(bbox, 'image', "[Image]"))
        except Exception as e:
            print(f"Warning: Failed to extract images on page {page_num}: {e}")

        # Track 3: Vector drawings (paths, curves, diagrams)
        try:
            drawings = page.get_drawings()
            for dwg in drawings:
                rect = dwg.get("rect")
                if rect:
                    bbox = (rect.x0, rect.y0, rect.x1, rect.y1)
                    if is_valid_graphic(bbox, pdf_w, pdf_h):
                        x0, y0, x1, y1 = bbox
                        # Rule 3: Strip headers & footers by coordinates
                        if y0 < 50.0 or y1 > (pdf_h - 50.0):
                            continue
                        elements.append(Element(bbox, 'drawing', "[Drawing]"))
        except Exception as e:
            print(f"Warning: Failed to extract drawings on page {page_num}: {e}")

        # Sort the gathered elements strictly top-to-bottom by y0 (vertical coordinate)
        elements.sort(key=lambda e: e.y0)

        # 3. Pre-scan the sorted elements to identify which main questions have sub-parts on this page.
        # This helps us avoid creating redundant crops for main question headers.
        main_has_subparts = {}
        current_main = None
        for el in elements:
            if el.type == 'text':
                q_type, main_q, sub_part = detect_question_label(el.text, el.x0)
                if q_type == 'main':
                    current_main = main_q
                    main_has_subparts[current_main] = False
                elif q_type == 'both':
                    current_main = main_q
                    main_has_subparts[current_main] = True
                elif q_type == 'sub':
                    if current_main:
                        main_has_subparts[current_main] = True

        # 4. Spatial Proximity Merging Engine
        elements_count = len(elements)
        prev_crop_bottom = 50.0  # Page-level coordinate marker tracking where the previous crop ended
        parent_y0_by_level = {1: None, 2: None, 3: None}
        
        i = 0
        while i < elements_count:
            el = elements[i]

            # We only initiate crops starting from identifiable question markers
            if el.type != 'text':
                i += 1
                continue

            q_type, main_q, sub_part = detect_question_label(el.text, el.x0)
            if q_type is None:
                i += 1
                continue

            # Update the page-level context variables
            if q_type in ('main', 'both'):
                current_main_question = main_q

            # Determine hierarchy level
            if q_type == 'main':
                current_level = 1
            elif q_type == 'both':
                current_level = 2
            else:
                current_level = get_sub_part_level(sub_part)

            # Initialize running group box coordinates
            group_x0, group_y0, group_x1, group_y1 = el.bbox

            # Check if this is the first sub-part of its hierarchy level (usually 'a', 'i', or '1')
            is_first_part = (sub_part is not None and sub_part.lower() in ('a', 'i', '1'))

            # Decide whether we need to perform local look-back or inherit parent's top coordinate
            inherit_parent = False
            if q_type == 'sub' and is_first_part:
                # Find the parent level
                parent_level = current_level - 1
                # Retrieve the parent y0 coordinate
                parent_y0 = None
                while parent_level >= 1:
                    if parent_y0_by_level.get(parent_level) is not None:
                        parent_y0 = parent_y0_by_level[parent_level]
                        break
                    parent_level -= 1
                
                if parent_y0 is not None:
                    inherit_parent = True
                    group_y0 = parent_y0

            if not inherit_parent:
                # Perform a local look-back to swallow local diagrams/intro text.
                # Stop if we hit the bottom boundary of the previous question crop.
                # Added 0.5-point tolerance to prevent re-absorbing elements exactly on the crop boundary.
                k = i - 1
                while k >= 0:
                    prev_el = elements[k]
                    if prev_el.y1 <= (prev_crop_bottom + 0.5):
                        break
                    # Stop if we hit any text block representing a previous question answer slot
                    # or starts with another question label.
                    if prev_el.type == 'text':
                        if is_answer_slot(prev_el.text):
                            break
                        prev_q_type, _, _ = detect_question_label(prev_el.text, prev_el.x0)
                        if prev_q_type is not None:
                            break
                    # Absorb the element: expand the group bounding box
                    group_x0 = min(group_x0, prev_el.x0)
                    group_y0 = min(group_y0, prev_el.y0)
                    group_x1 = max(group_x1, prev_el.x1)
                    group_y1 = max(group_y1, prev_el.y1)
                    k -= 1

            # Update parent y0 registries
            if q_type == 'main':
                parent_y0_by_level[1] = group_y0
                parent_y0_by_level[2] = None
                parent_y0_by_level[3] = None
            elif q_type == 'both':
                parent_y0_by_level[1] = group_y0
                parent_y0_by_level[2] = group_y0
                parent_y0_by_level[3] = None
            else:
                # Store the coordinate at current level
                parent_y0_by_level[current_level] = group_y0
                # Clear any lower levels to prevent stale coordinates
                for lvl in range(current_level + 1, 4):
                    parent_y0_by_level[lvl] = None

            # --- Deferred Cropping Check ---
            # If the marker is a main question start but it has subparts on this page,
            # we do NOT crop a standalone main question image. We defer and bundle it into Part A.
            if q_type == 'main' and main_has_subparts.get(main_q, False):
                i += 1
                continue

            # Determine appropriate base name
            if q_type == 'main':
                base_name = f"Page{page_num}_Question_{current_main_question}"
            else:
                base_name = f"Page{page_num}_Question_{current_main_question}_part_{sub_part}"

            # --- Look-ahead Loop ---
            # Merge adjacent text rows, diagrams, and math lines below
            j = i + 1
            has_seen_answer_slot = False
            while j < elements_count:
                next_el = elements[j]

                # Check if we should break based on encountering new questions
                if next_el.type == 'text':
                    next_q_type, next_main_q, next_sub_part = detect_question_label(next_el.text, next_el.x0)
                    # Rule 2: ENFORCE A HARD STOP ON MARKERS
                    if next_q_type is not None:
                        break

                # Determine vertical gap limit for this transition (Adaptive Thresholding)
                current_gap_limit = max_vertical_gap
                
                if not has_seen_answer_slot:
                    bottom_el = elements[j - 1]
                    # Refinement 1: Table row detection
                    if (bottom_el.type == 'text' and is_table_like(bottom_el.text)) or (next_el.type == 'text' and is_table_like(next_el.text)):
                        current_gap_limit = 45.0
                    # Refinement 2 (Diagram below): Allow larger gap if next element is a diagram
                    elif next_el.type in ('image', 'drawing'):
                        current_gap_limit = 200.0
                    # Refinement 4 (Multi-figure bridging): If the group already absorbed any diagrams/figures,
                    # relax the gap threshold for text elements to allow bridging multiple figures and labels.
                    elif any(elements[k].type in ('image', 'drawing') for k in range(i, j)):
                        current_gap_limit = 120.0

                # Break condition b: vertical gap exceeds limit
                vertical_gap = next_el.y0 - group_y1
                if vertical_gap > current_gap_limit:
                    break

                # Absorb next element: expand the bounding box group
                group_x0 = min(group_x0, next_el.x0)
                group_y0 = min(group_y0, next_el.y0)
                group_x1 = max(group_x1, next_el.x1)
                group_y1 = max(group_y1, next_el.y1)

                # Set the flag if we just absorbed an answer slot
                if next_el.type == 'text' and is_answer_slot(next_el.text):
                    has_seen_answer_slot = True

                j += 1

            # 5. Image Coordinate Mapping and Cropping
            y0_pixel = group_y0 * scale_y
            y1_pixel = group_y1 * scale_y

            # Rule 4: Apply vertical padding (+/- 15 pixels) and clamp bounds to page size
            crop_y0 = max(0, int(y0_pixel - vertical_padding))
            crop_y1 = min(img_h, int(y1_pixel + vertical_padding))

            # Rule 4: Crop spans the absolute full horizontal width of the page
            crop_x0 = 0
            crop_x1 = img_w

            if crop_y1 <= crop_y0:
                print(f"  [Skip] Invalid vertical coordinate bounds for: {el.text[:30].strip()}...")
                i += 1
                continue

            # Resolve naming conflicts by appending numeric suffixes
            sanitized_name = sanitize_filename(base_name)
            output_filename = f"{sanitized_name}.png"
            output_filepath = out_path / output_filename

            suffix = 1
            while output_filepath.exists():
                output_filename = f"{sanitized_name}_{suffix}.png"
                output_filepath = out_path / output_filename
                suffix += 1

            # Render, crop, and save
            try:
                crop_box = (crop_x0, crop_y0, crop_x1, crop_y1)
                cropped_img = page_image.crop(crop_box)
                cropped_img.save(output_filepath, "PNG")

                extracted_images.append(str(output_filepath))
                print(f"  [Extracted] Saved {output_filename} (y-range: {group_y0:.1f} -> {group_y1:.1f} pt)")
                
                # Keep track of where the last crop ended
                prev_crop_bottom = group_y1
            except Exception as e:
                print(f"  [Error] Failed to crop/save {output_filename}: {e}")

            i += 1

    doc.close()
    print(f"\nProcessing complete! Extracted {len(extracted_images)} questions/parts.")
    return extracted_images


if __name__ == "__main__":
    RENDER_DPI = 150
    PADDING = 15
    MAX_GAP = 25.0  # Rule 1: strict 25 points

    print("Exam Paper Question Extractor Run")
    print("=================================")

    # Parse PDF paths from command-line arguments if provided
    if len(sys.argv) > 1:
        INPUT_PDFS = sys.argv[1:]
    else:
        # Fallback to all PDF files in the current directory if no argument is provided
        INPUT_PDFS = [f for f in os.listdir('.') if f.lower().endswith('.pdf')]
        if INPUT_PDFS:
            print(f"No PDF files specified. Found {len(INPUT_PDFS)} PDF(s) in the current directory.")
        else:
            print("Error: No PDF files specified, and no PDF files found in this directory.")
            print("Usage: python extract.py <pdf_file1> [pdf_file2 ...]")
            sys.exit(1)

    for pdf_path in INPUT_PDFS:
        # Check if the chosen input file exists
        if not os.path.exists(pdf_path):
            print(f"\nError: Could not find input file '{pdf_path}'. Skipping...")
            continue

        print(f"\nProcessing: {pdf_path}")
        print("-" * (12 + len(pdf_path)))

        # Name the output directory after the PDF file (removing .pdf extension)
        OUTPUT_DIRECTORY = Path(pdf_path).stem

        try:
            results = extract_questions_from_pdf(
                pdf_path=pdf_path,
                output_dir=OUTPUT_DIRECTORY,
                dpi=RENDER_DPI,
                vertical_padding=PADDING,
                max_vertical_gap=MAX_GAP
            )
            print(f"Successfully processed {pdf_path}. Extracted {len(results)} images to '{OUTPUT_DIRECTORY}'.")
        except Exception as err:
            print(f"Execution failed for {pdf_path}: {err}")
            import traceback
            traceback.print_exc()
