# Arithmetic Worksheet Grader

Automatically grades arithmetic worksheet PDFs. Upload a student worksheet (and optionally an answer key) and receive an annotated PDF with colour-coded boxes, ✓/✗ marks, and correct answers filled in.

## Repository structure

```
arithmetic-grader/
├── grade_worksheet.py      # standalone CLI / importable grading pipeline
├── backend/
│   ├── main.py             # FastAPI app — POST /grade endpoint
│   ├── grade_worksheet.py  # copy of the grading script (used by the server)
│   ├── requirements.txt
│   └── render.yaml         # Render.com deployment config
├── frontend/
│   ├── index.html
│   ├── style.css
│   └── app.js
└── README.md
```

## Local development

### Backend

```bash
cd backend
pip install -r requirements.txt        # also needs: brew install tesseract (macOS)
uvicorn main:app --reload --port 8000
```

Test with curl:
```bash
curl -X POST http://localhost:8000/grade \
  -F "worksheet=@worksheet.pdf" \
  -o graded.pdf
```

### Frontend

```bash
python -m http.server 3000 --directory frontend
# open http://localhost:3000
```

For local end-to-end testing, temporarily set `BACKEND_URL = "http://localhost:8000/grade"` in `frontend/app.js`.

## Deployment

### Backend → Render.com

1. Push this repository to GitHub.
2. Create a new **Web Service** on [render.com](https://render.com), connect the repo, and select the `render.yaml` config (or configure manually with the same build/start commands).
3. Note the assigned service URL (e.g. `https://arithmetic-grader-backend.onrender.com`).

### Frontend → GitHub Pages

In the repo Settings → Pages, set source to branch `main`, folder `/frontend`.

### Configuration (two placeholders to fill in)

| File | Placeholder | Replace with |
|---|---|---|
| `backend/main.py` | `<YOUR-GITHUB-USERNAME>` | Your GitHub username (for CORS) |
| `frontend/app.js` | `<your-render-app>` | Your Render service name |

After filling in both values, commit and push — Render auto-deploys on push to `main`.

## Known limitations

- OCR accuracy is ~22/25 on tested worksheets. Providing an answer-key PDF improves results over letting the script solve problems from operand OCR.
- Render's free tier spins down after 15 minutes of inactivity, causing a ~30-second cold start on the first request.
