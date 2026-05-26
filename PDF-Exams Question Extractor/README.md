# PDF-Exams Question Extractor

An automated utility that parses digital, searchable exam paper PDFs to identify individual questions and their sub-parts, and crops them as full-width screenshots.

## Features

- **Built-in PDF Rendering**: Uses PyMuPDF (`fitz`) for layout analysis and rendering, eliminating the need for external tools like Poppler.
- **Auto-Detection**: Automatically identifies main question numbers (e.g. `1`, `2`, `3`) and sub-parts (e.g. `(a)`, `(b)`, `(i)`) based on left-margin alignment.
- **Smart Directory Naming**: Creates output directories named after the processed PDF file.
- **Full-Width Screenshots**: Crops each question block across the full width of the page with clean vertical padding.

## Requirements

Ensure you have Python 3 installed. Install the Python dependencies with:

```bash
pip install -r requirements.txt
```

## Usage

You can process a single PDF, multiple PDFs, or let the script auto-process all PDFs in the current directory:

### Process a Single File
```bash
python extract_exam_questions.py <path_to_your_exam_paper.pdf>
```

### Process Multiple Files
```bash
python extract_exam_questions.py exam1.pdf exam2.pdf exam3.pdf
```

### Process All PDFs in Current Directory
If you run the script without any arguments, it will automatically detect and process all `.pdf` files present in the current folder:
```bash
python extract_exam_questions.py
```

Each PDF file processed will have its own output folder named after the PDF stem (e.g. `9709_s21_qp_12/`) containing its respective cropped question screenshots.

## License

This project is licensed under a custom **Non-Commercial Personal-Use License**.
- You **can** use, modify, and run this project for your own personal, educational study.
- You **cannot** sell, rent, license, or use this tool as part of any commercial product or service.
- See the [LICENSE](./LICENSE) file for the full text.
