# Worksheet Grader — Project Context

## Overview

A web application that automatically grades arithmetic worksheet PDFs.
The user uploads a student worksheet (and optionally an answer key), and
receives an annotated PDF in return with colour-coded boxes around every
problem, a ✓/✗ mark, and the correct answer filled in.

---

## Current State

A working Python script (`grade_worksheet.py`) already exists and handles
the full grading pipeline. The task is to wrap it in a web interface.

### What the script does

1. Renders the worksheet PDF to a PIL image at 3× scale
2. Detects the problem grid by scanning for horizontal underlines (the
   addition/operation lines beneath each problem)
3. Obtains correct answers — either by OCR-ing a provided answer-key PDF,
   or by OCR-ing the operands and solving the arithmetic itself
4. OCR-s the student's handwritten answers
5. Draws colour-coded annotations on each problem cell:
   - **Green box + ✓** — correct answer
   - **Red box + ✗ + correct answer in red** — wrong answer
   - **Blue box + correct answer in blue** — blank / unanswered
6. Fills in the score at the top of the page
7. Saves the annotated image as a PDF

### Supported operations
Addition (+), Subtraction (−), Multiplication (×), Division (÷)

### Key dependencies
```
pypdfium2   # PDF rendering
Pillow      # image processing
img2pdf     # saving annotated image back to PDF
pytesseract # OCR (wraps the Tesseract binary)
numpy       # pixel array operations
```
Tesseract binary must also be installed on the server:
- Ubuntu/Debian: `sudo apt-get install tesseract-ocr`
- macOS: `brew install tesseract`

### Script interface
```bash
# With answer key (most accurate):
python grade_worksheet.py worksheet.pdf answer_key.pdf -o graded.pdf

# Without answer key (script solves problems itself):
python grade_worksheet.py worksheet.pdf -o graded.pdf

# Force column count if auto-detection is unreliable:
python grade_worksheet.py worksheet.pdf answer_key.pdf --cols 5
```

### Python API (importable)
```python
from grade_worksheet import grade

score, total = grade(
    worksheet_pdf  = "worksheet.pdf",
    answer_key_pdf = "answer_key.pdf",   # optional, pass None to omit
    output_pdf     = "graded.pdf",
    expected_cols  = None,               # int or None for auto-detect
    scale          = 3,                  # render scale, 3 is recommended
    verbose        = True,
)
```

### Known OCR limitations
Tesseract occasionally misreads certain digit combinations from the
specific italic font used in Math-Drills.com answer-key PDFs (e.g. "77"
read as "7", "86" read as "36"). These are inherent to Tesseract's neural
net engine at small font sizes. Accuracy on the tested worksheet is ~22/25
correct answers identified. Providing a high-quality answer-key PDF
improves accuracy over letting the script compute answers from operand OCR.

---

## Proposed Architecture

```
┌─────────────────────────────┐        ┌──────────────────────────────┐
│   GitHub Pages (frontend)   │        │   Render.com (backend)       │
│                             │        │                              │
│  Static HTML / CSS / JS     │  HTTP  │  FastAPI application         │
│  ─ drag-and-drop upload UI  │ ──────▶│  ─ POST /grade endpoint      │
│  ─ progress indicator       │        │  ─ runs grade_worksheet.py   │
│  ─ download graded PDF      │◀───────│  ─ returns annotated PDF     │
└─────────────────────────────┘        └──────────────────────────────┘
```

Both the frontend and backend can live in the **same GitHub repository**,
deployed independently:
- `./frontend/` → GitHub Pages
- `./backend/`  → Render (auto-deploys on push to main)

---

## Backend Specification

### Technology
- **Framework:** FastAPI
- **Host:** Render.com (free tier, deploys directly from GitHub)
- **Runtime:** Python 3.11+

### Endpoint

```
POST /grade
Content-Type: multipart/form-data

Fields:
  worksheet   (file, required)  — student worksheet PDF
  answer_key  (file, optional)  — answer key PDF
  cols        (int, optional)   — override column auto-detection
```

**Success response** `200 OK`
```
Content-Type: application/pdf
Content-Disposition: attachment; filename="graded.pdf"
Body: raw PDF bytes
```

**Error response** `422 Unprocessable Entity`
```json
{ "detail": "Could not detect problem grid. Try specifying --cols." }
```

### Implementation notes
- Use `python-multipart` for file uploads in FastAPI
- Write uploaded files to a `tempfile.TemporaryDirectory` — clean up after
  each request
- Set a reasonable file-size limit (e.g. 10 MB) to prevent abuse
- Configure CORS to allow requests from the GitHub Pages domain:
  `https://<your-username>.github.io`

### Render deployment
- Add a `render.yaml` (or configure via the Render dashboard):
  - Build command: `pip install -r requirements.txt && apt-get install -y tesseract-ocr`
  - Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
- Render's free tier spins down after 15 minutes of inactivity, causing a
  ~30-second cold start on the first request. Acceptable for this use case.

### `requirements.txt`
```
fastapi
uvicorn[standard]
python-multipart
pypdfium2
Pillow
img2pdf
pytesseract
numpy
```

---

## Frontend Specification

### Technology
- Plain HTML + CSS + vanilla JavaScript (no framework required)
- Hosted on GitHub Pages from the `./frontend/` directory (or a `gh-pages`
  branch)

### User flow
1. User lands on the page
2. Drags and drops (or clicks to select) the **worksheet PDF**
3. Optionally adds an **answer key PDF**
4. Clicks **Grade**
5. Sees a progress spinner while the backend processes
6. Browser automatically downloads `graded.pdf` on success
7. On error, a friendly message is shown

### Key implementation details

**Calling the backend:**
```javascript
const formData = new FormData();
formData.append("worksheet",  worksheetFile);
if (answerKeyFile) {
  formData.append("answer_key", answerKeyFile);
}

const response = await fetch("https://<your-render-app>.onrender.com/grade", {
  method: "POST",
  body: formData,
});

if (response.ok) {
  const blob = await response.blob();
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement("a");
  a.href     = url;
  a.download = "graded.pdf";
  a.click();
} else {
  const err = await response.json();
  showError(err.detail);
}
```

**CORS:** The backend must include the GitHub Pages origin in its CORS
`allow_origins` list. During development, also allow `http://localhost`.

**Cold-start UX:** Because Render's free tier has cold starts, show a
message like *"First request may take ~30 seconds while the server wakes
up…"* if the request takes more than 5 seconds.

---

## Repository Structure

```
worksheet-grader/
├── backend/
│   ├── main.py                 # FastAPI app + /grade endpoint
│   ├── grade_worksheet.py      # Existing grading script (copy here)
│   ├── requirements.txt
│   └── render.yaml             # Render deployment config
├── frontend/
│   ├── index.html
│   ├── style.css
│   └── app.js
└── README.md
```

---

## Suggested Build Order

1. **Set up the repo** — create the structure above, copy in
   `grade_worksheet.py`
2. **Build the FastAPI backend** — `main.py` with the `/grade` endpoint,
   test locally with `uvicorn main:app --reload`
3. **Deploy backend to Render** — connect the GitHub repo, confirm the
   `/grade` endpoint is reachable
4. **Build the frontend** — static HTML/JS page, point `fetch()` at the
   live Render URL
5. **Enable GitHub Pages** — set source to `./frontend/` in repo settings
6. **Test end-to-end** — upload the sample worksheets, confirm graded PDF
   downloads correctly
7. **Polish** — loading states, error handling, mobile layout

---

## Sample Test Files

The script was developed and tested against:
- `2-Digit_Plus_2-Digit_Addition_With_Some_Regrouping__25_Questions___A_.pdf`
  (student worksheet, 5×5 grid, mix of answered and blank problems)
- `2-Digit_Plus_2-Digit_Addition_With_Some_Regrouping__25_Questions__answers.pdf`
  (answer key, green printed answers)

Both are from Math-Drills.com. Use these as your primary integration test
inputs.
