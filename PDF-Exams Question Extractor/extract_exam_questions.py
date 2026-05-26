#!/usr/bin/env python3
"""
Exam Paper Question Extractor
-----------------------------
This script parses digital, searchable exam paper PDFs to identify individual
questions and their sub-parts, and crops them as full-width screenshots.
It uses PyMuPDF (fitz) for text layout analysis and page rendering at 150 DPI,
and Pillow (PIL) for cropping the images.

Python Dependencies:
- Install the required packages via pip:
  `pip install pymupdf pillow`
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


def sanitize_filename(filename: str) -> str:
    """
    Remove illegal filesystem characters and normalize spaces.

    Args:
        filename: The original string to sanitize.

    Returns:
        A sanitized string safe to use as a file name across OS filesystems.
    """
    # Replace illegal characters: \ / : * ? " < > | .
    sanitized = re.sub(r'[\\/*?:"<>|.]', '', filename)
    # Replace whitespace sequences with a single underscore
    sanitized = re.sub(r'\s+', '_', sanitized)
    return sanitized.strip("_") or "unnamed_block"


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
    # Clean leading/trailing spaces for parsing
    cleaned = text.strip()
    if not cleaned:
        return None, None, None

    # Pattern 1: Both main question and sub-part on the same starting block (e.g. "Question 1(a)", "Q2 b)", "1\n(a)")
    both_pattern = r'^(?:Question|Q|Q\.)?\s*(\d+)\s*\n?\s*(?:\(([a-zA-Z0-9]+)\)|([a-zA-Z0-9]+)\))\s*'
    both_match = re.match(both_pattern, cleaned, re.IGNORECASE)
    if both_match:
        main_q = both_match.group(1)
        sub_part = both_match.group(2) or both_match.group(3)
        # Verify it's a valid question position (left margin x0 < 55) or has explicit prefix
        has_prefix = re.match(r'^(?:Question|Q|Q\.)', cleaned, re.IGNORECASE) is not None
        if has_prefix or (x0 < 55 and int(main_q) < 30):
            return 'both', main_q, sub_part

    # Pattern 2: Main question only (e.g., "Question 1", "Q2", "3\nThe equation...")
    main_pattern = r'^(?:Question|Q|Q\.)?\s*(\d+)\b'
    main_match = re.match(main_pattern, cleaned, re.IGNORECASE)
    if main_match:
        main_q = main_match.group(1)
        has_prefix = re.match(r'^(?:Question|Q|Q\.)', cleaned, re.IGNORECASE) is not None
        if has_prefix or (x0 < 55 and int(main_q) < 30):
            return 'main', main_q, None

    # Pattern 3: Sub-part only (e.g., "(a)", "b)", "(i)", "ii)", "(1)", "2)")
    # Matches starting parenthetical/bracketed letters, digits, or roman numerals
    # followed by space or end-of-line. We limit length of subpart to 3 chars to avoid year matches.
    sub_pattern = r'^(?:\(([a-zA-Z0-9]+)\)|([a-zA-Z0-9]+)\))(?:\s+|$)'
    sub_match = re.match(sub_pattern, cleaned)
    if sub_match:
        sub_part = sub_match.group(1) or sub_match.group(2)
        if len(sub_part) <= 3:
            return 'sub', None, sub_part

    return None, None, None


def extract_questions_from_pdf(
    pdf_path: str,
    output_dir: str,
    dpi: int = 150,
    vertical_padding: int = 10,
    poppler_path: Optional[str] = None
) -> List[str]:
    """
    Scans a searchable PDF exam paper, identifies questions and their sub-parts,
    and crops them as full-width screenshots.

    Args:
        pdf_path: Path to the input PDF file.
        output_dir: Directory where the cropped images will be saved.
        dpi: Resolution (dots per inch) to render PDF pages. Default is 150.
        vertical_padding: Pixel padding buffer added to top and bottom of crop.
        poppler_path: Optional directory containing Poppler binaries (specifically for Windows).

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
        print(f"Processing Page {page_num}/{len(doc)}...")

        # 1. Render the current page to a PIL Image at specified DPI using PyMuPDF (fitz)
        try:
            page = doc[page_idx]
            zoom = dpi / 72
            matrix = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=matrix)
            page_image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        except Exception as e:
            print(f"Error rendering page {page_num}: {e}")
            continue

        # 2. Retrieve page sizes for scaling factor calculation
        page = doc[page_idx]
        pdf_w = page.rect.width
        pdf_h = page.rect.height
        img_w, img_h = page_image.size

        # Programmatically calculate scaling factors
        scale_x = img_w / pdf_w
        scale_y = img_h / pdf_h

        # 3. Retrieve text blocks from PyMuPDF layout analyzer
        # Blocks format: (x0, y0, x1, y1, "text", block_no, block_type)
        blocks = page.get_text("blocks")

        # Sort blocks logically: top-to-bottom first, then left-to-right
        blocks.sort(key=lambda b: (b[1], b[0]))

        for block in blocks:
            x0, y0, x1, y1, text, block_no, block_type = block

            # Evaluate only text blocks (block_type 0)
            if block_type != 0:
                continue

            text_str = text.strip()
            if not text_str:
                continue

            # Detect if this block is a main question, a subpart, or both
            q_type, main_q, sub_part = detect_question_label(text_str, x0)

            if q_type is None:
                continue  # Not identified as a question start block, skip

            # 4. Context-aware file serialization naming
            if q_type == 'main':
                current_main_question = main_q
                base_name = f"Page{page_num}_Question_{current_main_question}"
            elif q_type == 'both':
                current_main_question = main_q
                base_name = f"Page{page_num}_Question_{current_main_question}_part_{sub_part}"
            elif q_type == 'sub':
                base_name = f"Page{page_num}_Question_{current_main_question}_part_{sub_part}"
            else:
                continue

            # Sanitize the output filename to ensure it is OS-safe
            sanitized_name = sanitize_filename(base_name)
            output_filename = f"{sanitized_name}.png"
            output_filepath = out_path / output_filename

            # 5. Coordinate Mapping & Cropping Constraints
            # Vertical Coordinates: Map PDF point coordinates to rendered pixels
            y0_pixel = y0 * scale_y
            y1_pixel = y1 * scale_y

            # Add vertical padding and clamp to the image bounds
            crop_y0 = max(0, int(y0_pixel - vertical_padding))
            crop_y1 = min(img_h, int(y1_pixel + vertical_padding))

            # Horizontal Coordinates: Crop the FULL WIDTH of the page (0 to image width)
            crop_x0 = 0
            crop_x1 = img_w

            # Verify the coordinates define a valid vertical box
            if crop_y1 <= crop_y0:
                print(f"  [Skip] Invalid height coords for: {text_str[:30]}...")
                continue

            # Crop and save the image slice
            try:
                crop_box = (crop_x0, crop_y0, crop_x1, crop_y1)
                cropped_img = page_image.crop(crop_box)
                cropped_img.save(output_filepath, "PNG")

                extracted_images.append(str(output_filepath))
                print(f"  [Extracted] Saved block {block_no} -> {output_filename}")
            except Exception as e:
                print(f"  [Error] Failed to crop/save block {block_no}: {e}")

    doc.close()
    print(f"\nProcessing complete! Extracted {len(extracted_images)} questions/parts.")
    return extracted_images


if __name__ == "__main__":
    # Example usage configuration
    RENDER_DPI = 150
    PADDING = 10
    
    # On Windows, define the path to your Poppler bin folder if it is not in your system PATH
    # Example: "C:\\Program Files\\poppler-23.08.0\\Library\\bin"
    POPPLER_BIN_PATH = None

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
            print("Usage: python extract_exam_questions.py <pdf_file1> [pdf_file2 ...]")
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
                poppler_path=POPPLER_BIN_PATH
            )
            print(f"Successfully processed {pdf_path}. Extracted {len(results)} images to '{OUTPUT_DIRECTORY}'.")
        except Exception as err:
            print(f"Execution failed for {pdf_path}: {err}")
