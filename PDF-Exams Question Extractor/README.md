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

Run the script by passing the path of your exam paper PDF file:

```bash
python extract_exam_questions.py <path_to_your_exam_paper.pdf>
```

### Example

```bash
python extract_exam_questions.py 9709_s21_qp_12.pdf
```

This will create a folder named `9709_s21_qp_12/` containing individual screenshots of every question and subpart.

## License

This project is licensed under a custom **Non-Commercial Personal-Use License**.
- You **can** use, modify, and run this project for your own personal, educational study.
- You **cannot** sell, rent, license, or use this tool as part of any commercial product or service.
- See the [LICENSE](./LICENSE) file for the full text.
