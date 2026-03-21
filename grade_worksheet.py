#!/usr/bin/env python3
"""
grade_worksheet.py — Extensible arithmetic worksheet grader
============================================================
Automatically detects and grades arithmetic problems on a PDF worksheet.
Draws a colour-coded box around every problem, places a ✓ or ✗ in the
top-right corner, and writes the correct answer in the answer space.

Colour coding
-------------
  Green  = correct answer
  Red    = wrong answer  (correct answer shown below student's work)
  Blue   = blank / unanswered  (correct answer filled in)

Supported operations
--------------------
  Addition (+), Subtraction (−), Multiplication (×), Division (÷)

Usage
-----
  # With an answer-key PDF (most accurate):
  python grade_worksheet.py worksheet.pdf answer_key.pdf -o graded.pdf

  # Without answer key — script solves every problem itself:
  python grade_worksheet.py worksheet.pdf -o graded.pdf

  # Force a specific column count (useful if auto-detection is off):
  python grade_worksheet.py worksheet.pdf answer_key.pdf --cols 5

Dependencies
------------
  pip install pypdfium2 pillow img2pdf pytesseract numpy
  # plus the Tesseract binary:
  #   Ubuntu/Debian : sudo apt-get install tesseract-ocr
  #   macOS         : brew install tesseract
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

import img2pdf
import numpy as np
import pypdfium2 as pdfium
from PIL import Image, ImageDraw, ImageFont

try:
    import pytesseract
    _TESS_OK = True
except ImportError:
    _TESS_OK = False


# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

RENDER_SCALE = 3          # render PDF at 3× — good balance of speed vs quality

# All offsets are expressed at RENDER_SCALE = 3; they are multiplied by
# `scale / 3` at runtime so the script works at any render scale.
_BOX_TOP    = -145        # px above the addition/operation underline
_BOX_BOTTOM = +130        # px below the addition/operation underline
_BOX_PAD    =  12         # horizontal padding around each column span

GREEN = (  0, 150,   0)
RED   = (210,  30,  30)
BLUE  = ( 20, 100, 210)

_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "arial.ttf",
]


# ─────────────────────────────────────────────────────────────────────────────
# 1.  Arithmetic solver
# ─────────────────────────────────────────────────────────────────────────────

def solve(top: int, bottom: int, op: str) -> int | float | None:
    """Return the correct answer for a two-operand arithmetic problem."""
    op = op.strip()
    if op == "+":
        return top + bottom
    if op in ("-", "−", "–"):
        return top - bottom
    if op in ("×", "x", "X", "*", "·"):
        return top * bottom
    if op in ("÷", "/", "//"):
        if bottom == 0:
            return None
        result = top / bottom
        return int(result) if result == int(result) else round(result, 2)
    return None


def _detect_op(text: str) -> str:
    """Infer the arithmetic operator from an OCR string (e.g. '+ 13')."""
    for sym in ("×", "x", "X", "*", "·"):
        if sym in text:
            return "×"
    for sym in ("÷", "//"):
        if sym in text:
            return "÷"
    for sym in ("-", "−", "–"):
        if sym in text:
            return "-"
    return "+"   # default — addition worksheets are the most common


# ─────────────────────────────────────────────────────────────────────────────
# 2.  Grid detection  (finds the operation underlines automatically)
# ─────────────────────────────────────────────────────────────────────────────

def _spans_in_row(row: np.ndarray, threshold: int, min_span: int) -> list[tuple[int, int]]:
    spans, in_span, start = [], False, 0
    for x, px in enumerate(row):
        if px < threshold and not in_span:
            in_span, start = True, x
        elif px >= threshold and in_span:
            in_span = False
            if x - start >= min_span:
                spans.append((start, x))
    return spans


def _cluster_rows(row_spans: dict[int, list]) -> list[tuple[int, list]]:
    """Merge adjacent rows that share the same horizontal-line pattern."""
    sorted_ys = sorted(row_spans)
    clusters: list[tuple[int, list]] = []
    cur_ys    = [sorted_ys[0]]
    cur_spans = row_spans[sorted_ys[0]]

    for y in sorted_ys[1:]:
        spans = row_spans[y]
        same = (
            y - cur_ys[-1] <= 3
            and len(spans) == len(cur_spans)
            and all(abs(a[0] - b[0]) < 10 for a, b in zip(spans, cur_spans))
        )
        if same:
            cur_ys.append(y)
        else:
            clusters.append((int(np.median(cur_ys)), cur_spans))
            cur_ys, cur_spans = [y], spans

    clusters.append((int(np.median(cur_ys)), cur_spans))
    return clusters


def find_operation_lines(
    arr: np.ndarray,
    min_span: int = 100,
    threshold: int = 150,
) -> list[tuple[int, list[tuple[int, int]]]]:
    """
    Scan every pixel row for long dark horizontal segments.

    Returns a list of (y_center, [(x_start, x_end), …]) — one entry per
    cluster of rows that share the same column-span pattern.
    """
    row_spans: dict[int, list] = {}
    for y in range(arr.shape[0]):
        spans = _spans_in_row(arr[y], threshold, min_span)
        if spans:
            row_spans[y] = spans
    if not row_spans:
        return []
    return _cluster_rows(row_spans)


def select_problem_lines(
    clusters: list[tuple[int, list]],
    expected_cols: int | None = None,
) -> tuple[list[int], list[tuple[int, int]]]:
    """
    From all detected horizontal lines pick the ones that are the
    operation underlines (i.e. repeated rows with a consistent column count).

    Returns (sorted_line_ys, col_spans).
    """
    by_count: dict[int, list] = {}
    for y, spans in clusters:
        by_count.setdefault(len(spans), []).append((y, spans))

    if expected_cols and expected_cols in by_count:
        candidates = by_count[expected_cols]
    else:
        best_n = max(
            (n for n in by_count if n >= 2),
            key=lambda n: len(by_count[n]),
        )
        candidates = by_count[best_n]

    ys    = sorted(y for y, _ in candidates)
    spans = candidates[0][1]   # all candidates share the same spans
    return ys, spans


# ─────────────────────────────────────────────────────────────────────────────
# 3.  OCR
# ─────────────────────────────────────────────────────────────────────────────

def _preprocess_for_ocr(
    img: Image.Image,
    box: tuple[int, int, int, int],
    mode: str = "printed",       # "printed" | "handwritten" | "coloured"
) -> Image.Image:
    """
    Crop, threshold, upscale, and pad an image region for Tesseract.

    mode="printed"      — black printed text (threshold at 230)
    mode="handwritten"  — faint pencil (threshold at 252, very aggressive)
    mode="coloured"     — coloured ink on white (non-white pixel detection)
    """
    crop = img.crop(box)
    arr  = np.array(crop)

    if mode == "coloured":
        # Any channel that is noticeably dark → ink pixel
        mask = (arr[:, :, 0] < 200) | (arr[:, :, 1] < 200) | (arr[:, :, 2] < 200)
    elif mode == "handwritten":
        lum  = np.array(Image.fromarray(arr).convert("L"))
        mask = lum < 252
    else:  # printed
        lum  = np.array(Image.fromarray(arr).convert("L"))
        mask = lum < 230

    binary = np.where(mask, 0, 255).astype(np.uint8)
    im = Image.fromarray(binary)

    # Upscale — Tesseract works best at ~150–300 dpi equivalent
    w, h = im.size
    scale = max(4, 300 // max(h, 1))
    im = im.resize((w * scale, h * scale), Image.LANCZOS)

    # Add generous white border so characters aren't clipped
    padded = Image.new("L", (im.width + 60, im.height + 60), 255)
    padded.paste(im, (30, 30))
    return padded


def _ocr_image(im: Image.Image) -> int | None:
    """
    Run Tesseract with several PSM modes and return the most-voted integer,
    or None if nothing legible is found.
    """
    if not _TESS_OK:
        return None

    votes: list[int] = []
    cfg_base = "-c tessedit_char_whitelist=0123456789"
    for psm in (7, 8, 6, 13):
        raw = pytesseract.image_to_string(im, config=f"--psm {psm} {cfg_base}")
        raw = raw.strip().replace(" ", "").replace("\n", "")
        try:
            votes.append(int(raw))
        except ValueError:
            pass

    if not votes:
        return None
    return Counter(votes).most_common(1)[0][0]


def ocr_region(
    img: Image.Image,
    box: tuple[int, int, int, int],
    mode: str = "printed",
) -> int | None:
    """High-level: preprocess a region then OCR it, returning an int or None."""
    im = _preprocess_for_ocr(img, box, mode)
    return _ocr_image(im)


# ─────────────────────────────────────────────────────────────────────────────
# 4.  Extract answers from answer-key PDF
# ─────────────────────────────────────────────────────────────────────────────

def extract_key_answers(
    key_img: Image.Image,
    line_ys: list[int],
    col_spans: list[tuple[int, int]],
    bot: int,
    pad: int,
) -> list[list[int | None]]:
    """
    OCR the answer area (below the operation line) from the answer-key image.
    The answer key typically has green/red printed numbers → mode="coloured".
    """
    answers: list[list[int | None]] = []
    for line_y in line_ys:
        row: list[int | None] = []
        for x1, x2 in col_spans:
            box = (x1 - pad, line_y + 5, x2 + pad, line_y + bot - pad)
            row.append(ocr_region(key_img, box, mode="coloured"))
        answers.append(row)
    return answers


# ─────────────────────────────────────────────────────────────────────────────
# 5.  Extract student answers from worksheet
# ─────────────────────────────────────────────────────────────────────────────

def extract_student_answers(
    ws_img: Image.Image,
    line_ys: list[int],
    col_spans: list[tuple[int, int]],
    bot: int,
    pad: int,
) -> list[list[int | None]]:
    """
    OCR the answer area on the student worksheet.
    Uses aggressive threshold for faint pencil marks.
    Extra horizontal padding ensures narrow digits like '1' are not clipped.
    """
    answers: list[list[int | None]] = []
    for line_y in line_ys:
        row: list[int | None] = []
        for x1, x2 in col_spans:
            # Extra 15 px on each side to catch digits near column edges
            box = (x1 - pad - 15, line_y + 5, x2 + pad + 15, line_y + bot - pad)
            row.append(ocr_region(ws_img, box, mode="handwritten"))
        answers.append(row)
    return answers


# ─────────────────────────────────────────────────────────────────────────────
# 6.  Compute correct answers by OCR-ing operands then solving
# ─────────────────────────────────────────────────────────────────────────────

def compute_correct_answers(
    ws_img: Image.Image,
    line_ys: list[int],
    col_spans: list[tuple[int, int]],
    top_offset: int,
    pad: int,
) -> list[list[int | None]]:
    """
    When no answer-key PDF is provided: OCR both operand lines in each cell
    and compute the answer programmatically.
    """
    answers: list[list[int | None]] = []
    half = (-top_offset) // 2

    for line_y in line_ys:
        row: list[int | None] = []
        for x1, x2 in col_spans:
            cl = x1 - pad
            cr = x2 + pad
            top_box = (cl, line_y + top_offset,      cr, line_y + top_offset + half)
            bot_box = (cl, line_y + top_offset + half, cr, line_y - 5)

            raw_top = ocr_region(ws_img, top_box, mode="printed")
            raw_bot_img = _preprocess_for_ocr(ws_img, bot_box, mode="printed")
            # Also grab the raw text to detect the operator symbol
            raw_bot_str = ""
            if _TESS_OK:
                raw_bot_str = pytesseract.image_to_string(
                    raw_bot_img, config="--psm 7"
                ).strip()
            op      = _detect_op(raw_bot_str)
            raw_bot = _ocr_image(raw_bot_img)

            if raw_top is not None and raw_bot is not None:
                row.append(solve(raw_top, raw_bot, op))
            else:
                row.append(None)
        answers.append(row)
    return answers


# ─────────────────────────────────────────────────────────────────────────────
# 7.  Drawing helpers
# ─────────────────────────────────────────────────────────────────────────────

def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    return ImageFont.load_default()


def _draw_centered(
    draw: ImageDraw.ImageDraw,
    text: str,
    cx: int,
    cy: int,
    font,
    color: tuple,
) -> None:
    bb = draw.textbbox((0, 0), text, font=font)
    w, h = bb[2] - bb[0], bb[3] - bb[1]
    draw.text((cx - w // 2, cy - h // 2), text, fill=color, font=font)


def annotate_cell(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],   # left, top, right, bottom
    ans_cy: int,                       # y-centre of the answer zone
    is_correct: bool | None,           # True / False / None (blank)
    correct_answer: int | float | None,
    font_mark,
    font_ans,
) -> None:
    """Draw the coloured border, ✓/✗ mark, and correct answer for one cell."""
    left, top, right, bottom = box
    cx = (left + right) // 2

    colour = GREEN if is_correct is True else (RED if is_correct is False else BLUE)
    mark   = ("✓" if is_correct is True else "✗") if is_correct is not None else None

    # Coloured border
    draw.rectangle([left, top, right, bottom], outline=colour, width=5)

    # ✓/✗ mark in top-right corner with white backing so it's always legible
    if mark is not None:
        mb  = draw.textbbox((0, 0), mark, font=font_mark)
        mw  = mb[2] - mb[0]
        mx  = right - mw - 4
        my  = top   + 4
        draw.rectangle([mx - 2, my, right - 2, my + mw + 4], fill="white")
        draw.text((mx, my), mark, fill=colour, font=font_mark)

    # Correct answer in the answer zone (always shown unless student was correct)
    if correct_answer is not None and is_correct is not True:
        _draw_centered(draw, str(correct_answer), cx, ans_cy, font_ans, colour)


def _write_score(
    draw: ImageDraw.ImageDraw,
    img_w: int,
    img_h: int,
    score: int,
    total: int,
    font,
) -> None:
    """Write the numeric score near the top-right score field."""
    sx = int(img_w * 0.79)
    sy = int(img_h * 0.068)
    bb = draw.textbbox((0, 0), str(score), font=font)
    fw, fh = bb[2] - bb[0], bb[3] - bb[1]
    draw.rectangle([sx - 4, sy - 4, sx + fw + 4, sy + fh + 4], fill="white")
    draw.text((sx, sy), str(score), fill=RED, font=font)


# ─────────────────────────────────────────────────────────────────────────────
# 8.  Main grading pipeline
# ─────────────────────────────────────────────────────────────────────────────

def grade(
    worksheet_pdf: str,
    answer_key_pdf: str | None = None,
    output_pdf: str = "graded_worksheet.pdf",
    expected_cols: int | None = None,
    scale: int = RENDER_SCALE,
    verbose: bool = True,
) -> tuple[int, int]:
    """
    Full grading pipeline.

    Parameters
    ----------
    worksheet_pdf   : path to the student's worksheet PDF
    answer_key_pdf  : optional path to the answer-key PDF
    output_pdf      : where to write the annotated PDF
    expected_cols   : override automatic column detection
    scale           : render scale (higher = sharper but slower)
    verbose         : print progress to stdout

    Returns
    -------
    (score, total)  : number of correct answers and total problems
    """

    # ── Scale all offsets to the chosen render scale ──────────────────────
    f   = scale / 3
    bto = int(_BOX_TOP    * f)
    bbo = int(_BOX_BOTTOM * f)
    bp  = int(_BOX_PAD    * f)

    # ── Render worksheet to a PIL image ───────────────────────────────────
    ws_doc  = pdfium.PdfDocument(worksheet_pdf)
    ws_page = ws_doc[0]
    ws_img  = ws_page.render(scale=scale).to_pil().convert("RGB")
    ws_arr  = np.array(ws_img.convert("L"))

    if verbose:
        print(f"Worksheet image: {ws_img.width}×{ws_img.height} px "
              f"(scale={scale})")

    # ── Detect the problem grid ────────────────────────────────────────────
    min_span = max(50, int(100 * f))
    clusters = find_operation_lines(ws_arr, min_span=min_span, threshold=150)
    line_ys, col_spans = select_problem_lines(clusters, expected_cols)

    n_rows, n_cols = len(line_ys), len(col_spans)
    if verbose:
        print(f"Detected grid  : {n_rows} row(s) × {n_cols} col(s)")
        print(f"  Operation line y-values : {line_ys}")
        print(f"  Column x-spans          : {col_spans}")

    # ── Obtain correct answers ─────────────────────────────────────────────
    if answer_key_pdf:
        key_img = pdfium.PdfDocument(answer_key_pdf)[0]\
                        .render(scale=scale).to_pil().convert("RGB")
        correct = extract_key_answers(key_img, line_ys, col_spans, bbo, bp)
        if verbose:
            print("Correct answers (key PDF OCR):")
    else:
        correct = compute_correct_answers(ws_img, line_ys, col_spans, bto, bp)
        if verbose:
            print("Correct answers (computed):")

    if verbose:
        for r, row in enumerate(correct):
            print(f"  Row {r + 1}: {row}")

    # ── OCR student answers ────────────────────────────────────────────────
    student = extract_student_answers(ws_img, line_ys, col_spans, bbo, bp)
    if verbose:
        print("Student answers (OCR):")
        for r, row in enumerate(student):
            print(f"  Row {r + 1}: {row}")

    # ── Annotate the worksheet image ───────────────────────────────────────
    draw      = ImageDraw.Draw(ws_img)
    font_mark = _load_font(int(44 * f))
    font_ans  = _load_font(int(40 * f))
    font_scr  = _load_font(int(44 * f))

    score, attempted = 0, 0

    for r, line_y in enumerate(line_ys):
        for c, (x1, x2) in enumerate(col_spans):
            ca = correct[r][c] if r < len(correct) and c < len(correct[r]) else None
            sa = student[r][c] if r < len(student) and c < len(student[r]) else None

            box    = (x1 - bp, line_y + bto, x2 + bp, line_y + bbo)
            ans_cy = line_y + int(65 * f)

            if sa is None:
                is_correct = None
            else:
                attempted += 1
                is_correct = (sa == ca)
                if is_correct:
                    score += 1

            annotate_cell(draw, box, ans_cy, is_correct, ca, font_mark, font_ans)

    total = n_rows * n_cols
    _write_score(draw, ws_img.width, ws_img.height, score, total, font_scr)

    if verbose:
        print(f"\nScore: {score}/{total}  (attempted {attempted}/{total})")

    # ── Save annotated PDF ─────────────────────────────────────────────────
    tmp_png = Path(output_pdf).with_suffix("._tmp.png")
    ws_img.save(tmp_png)

    w_pt = ws_page.get_width()
    h_pt = ws_page.get_height()
    with open(output_pdf, "wb") as fh:
        fh.write(img2pdf.convert(
            str(tmp_png),
            layout_fun=img2pdf.get_layout_fun(
                (img2pdf.in_to_pt(w_pt / 72), img2pdf.in_to_pt(h_pt / 72))
            ),
        ))
    tmp_png.unlink(missing_ok=True)

    print(f"Saved → {output_pdf}")
    return score, total


# ─────────────────────────────────────────────────────────────────────────────
# 9.  CLI entry-point
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(
        description="Grade an arithmetic worksheet PDF and produce an annotated copy.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("worksheet",
        help="Student worksheet PDF")
    p.add_argument("answer_key", nargs="?", default=None,
        help="Answer-key PDF (optional; problems are solved automatically if omitted)")
    p.add_argument("-o", "--output", default="graded_worksheet.pdf",
        help="Output PDF path  [default: graded_worksheet.pdf]")
    p.add_argument("--cols", type=int, default=None, metavar="N",
        help="Expected number of problem columns (auto-detected if omitted)")
    p.add_argument("--scale", type=int, default=RENDER_SCALE, metavar="S",
        help=f"Render scale factor  [default: {RENDER_SCALE}]")
    p.add_argument("-q", "--quiet", action="store_true",
        help="Suppress progress messages")
    args = p.parse_args()

    if not Path(args.worksheet).exists():
        sys.exit(f"Error: worksheet not found: {args.worksheet}")
    if args.answer_key and not Path(args.answer_key).exists():
        sys.exit(f"Error: answer key not found: {args.answer_key}")

    grade(
        worksheet_pdf  = args.worksheet,
        answer_key_pdf = args.answer_key,
        output_pdf     = args.output,
        expected_cols  = args.cols,
        scale          = args.scale,
        verbose        = not args.quiet,
    )


if __name__ == "__main__":
    main()
