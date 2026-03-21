import tempfile
import shutil
from pathlib import Path

from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from grade_worksheet import grade

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://sashabadov.github.io",
        "http://localhost",
        "http://localhost:3000",
        "http://127.0.0.1",
    ],
    allow_methods=["POST", "OPTIONS"],
    allow_headers=["*"],
)

MAX_BYTES = 10 * 1024 * 1024  # 10 MB


@app.get("/")
def health():
    return {"status": "ok"}


@app.post("/grade")
async def grade_endpoint(
    worksheet: UploadFile = File(...),
    answer_key: UploadFile | None = File(default=None),
    cols: int | None = Form(default=None),
):
    ws_bytes = await worksheet.read()
    if len(ws_bytes) > MAX_BYTES:
        raise HTTPException(422, detail="Worksheet exceeds 10 MB limit.")

    ak_bytes = None
    if answer_key and answer_key.filename:
        ak_bytes = await answer_key.read()
        if len(ak_bytes) > MAX_BYTES:
            raise HTTPException(422, detail="Answer key exceeds 10 MB limit.")

    tmpdir = tempfile.mkdtemp()
    try:
        ws_path = Path(tmpdir) / "worksheet.pdf"
        ws_path.write_bytes(ws_bytes)

        ak_path = None
        if ak_bytes:
            ak_path = Path(tmpdir) / "answer_key.pdf"
            ak_path.write_bytes(ak_bytes)

        out_path = Path(tmpdir) / "graded.pdf"

        try:
            grade(
                worksheet_pdf=str(ws_path),
                answer_key_pdf=str(ak_path) if ak_path else None,
                output_pdf=str(out_path),
                expected_cols=cols,
                scale=3,
                verbose=False,
            )
        except Exception as exc:
            raise HTTPException(422, detail=str(exc))

        return Response(
            content=out_path.read_bytes(),
            media_type="application/pdf",
            headers={"Content-Disposition": 'attachment; filename="graded.pdf"'},
        )
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
