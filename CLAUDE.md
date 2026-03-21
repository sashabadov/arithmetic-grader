# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Install dependencies
```bash
pip install pypdfium2 pillow img2pdf pytesseract numpy
brew install tesseract  # macOS; Ubuntu: sudo apt-get install tesseract-ocr
```

### Run grader (CLI)
```bash
# With answer key
python grade_worksheet.py worksheet.pdf answer_key.pdf -o graded.pdf

# Without answer key (script solves problems itself)
python grade_worksheet.py worksheet.pdf -o graded.pdf

# Force column count if auto-detection is wrong
python grade_worksheet.py worksheet.pdf answer_key.pdf --cols 5
```

### Python API
```python
from grade_worksheet import grade
score, total = grade(
    worksheet_pdf="worksheet.pdf",
    answer_key_pdf="answer_key.pdf",  # or None
    output_pdf="graded.pdf",
    expected_cols=None,  # int or None for auto-detect
    scale=3,
)
```

## Architecture

Single-script pipeline in `grade_worksheet.py` with 8 phases:

1. **PDF Rendering** — PDF → high-res PIL image (scale=3 recommended)
2. **Grid Detection** — scans pixel rows for dark horizontal segments (operation/underlines), clusters them to find problem boundaries and column layout
3. **OCR Setup** — three preprocessing modes: `"printed"` (threshold 230), `"handwritten"` (threshold 252, aggressive for faint pencil), `"coloured"` (non-white pixel detection); all modes upscale and pad before Tesseract
4. **Answer Extraction** — OCR the answer key PDF if provided (coloured mode); otherwise OCR operands and compute answers arithmetically
5. **Student Answer OCR** — handwritten mode, with multi-PSM voting (PSM 7/8/6/13) for reliability
6. **Annotation Drawing** — green box+✓ (correct), red box+✗+correct answer (wrong), blue box+correct answer (blank); score written at top
7. **PDF Export** — annotated PIL image → PDF at original dimensions

### Key design choices
- All pixel offsets are expressed at `RENDER_SCALE=3` and scaled at runtime: `actual = nominal * (user_scale / 3)`. Box extents: top=−145px, bottom=+130px relative to operation line.
- OCR uses majority voting across PSM modes to reduce Tesseract variability.
- Known accuracy: ~22/25 on test worksheets; main failure mode is Tesseract misreading italic/handwritten digits.

## Planned expansion (see PROJECT_CONTEXT.md)

The project is being extended into a web app:
- **Backend**: FastAPI on Render — `POST /grade` endpoint wrapping the `grade()` function
- **Frontend**: Static HTML/CSS/JS on GitHub Pages — drag-and-drop upload, progress indicator, auto-download of graded PDF
- Planned repo structure: `backend/` (FastAPI + `grade_worksheet.py` + `requirements.txt` + `render.yaml`) and `frontend/` (`index.html`, `style.css`, `app.js`)
