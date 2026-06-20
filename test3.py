#!/usr/bin/env python3
"""
EIL PDF Field Extractor (with OCR fallback)
--------------------------------------------
Reads regex patterns from a JSON file, extracts fields from one or more PDFs,
and saves results to a CSV file.

Strategy per page:
  1. pdfplumber  → fast native text extraction
  2. If a page has no/little text → OCR via pytesseract (Tesseract 5)

Usage:
    python test3.py -j eil.json -p "D:\Test\Technical.pdf" -o "D:\Test\output.csv"
    python test3.py -j eil.json -p /folder/with/pdfs/ -o "D:\Test\output.csv"
    python test3.py -j eil.json -p "D:\Test\Technical.pdf" -o "D:\Test\output.csv" --ocr-dpi 300 --lang eng
    python test3.py -j eil.json -p "D:\Test\Technical.pdf" -o "D:\Test\output.csv" --no-ocr
"""

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# ── Dependency checks ──────────────────────────────────────────────────────────

try:
    import pdfplumber
except ImportError:
    print("ERROR: pdfplumber not installed.  Run: pip install pdfplumber")
    sys.exit(1)

try:
    from PIL import Image
    import pytesseract
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False

PDFTOPPM_AVAILABLE = shutil.which("pdftoppm") is not None


# ── OCR helpers ────────────────────────────────────────────────────────────────

def _ocr_page_image(image: "Image.Image", lang: str) -> str:
    """Run Tesseract on a PIL image and return extracted text."""
    config = "--oem 3 --psm 6"          # LSTM engine, assume uniform block of text
    return pytesseract.image_to_string(image, lang=lang, config=config)


def _rasterize_pdf_page(pdf_path: str, page_no: int, dpi: int, tmpdir: str) -> "Image.Image | None":
    """
    Convert a single PDF page to a PIL Image using pdftoppm.
    page_no is 1-based.
    """
    prefix = os.path.join(tmpdir, "page")
    cmd = [
        "pdftoppm",
        "-jpeg",
        "-r", str(dpi),
        "-f", str(page_no),
        "-l", str(page_no),
        pdf_path,
        prefix,
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        print(f"    [OCR] pdftoppm failed for page {page_no}: {e.stderr.decode()[:120]}")
        return None

    # pdftoppm zero-pads based on total page count; find what it produced
    files = sorted(Path(tmpdir).glob("page-*.jpg"))
    if not files:
        return None
    img = Image.open(str(files[-1]))
    # Clean up so next page doesn't pick up stale files
    for f in files:
        f.unlink(missing_ok=True)
    return img


# ── Text extraction ────────────────────────────────────────────────────────────

MIN_TEXT_CHARS = 50   # fewer chars on a page → treat as scanned, trigger OCR

def extract_text_from_pdf(
    pdf_path: str,
    use_ocr: bool = True,
    ocr_lang: str = "eng",
    ocr_dpi: int = 300,
) -> tuple[str, str]:
    """
    Extract text from every page of a PDF.

    Returns:
        (full_text, extraction_method)
        extraction_method: "native" | "ocr" | "mixed" | "failed"
    """
    text_parts = []
    methods_used = set()

    can_ocr = use_ocr and OCR_AVAILABLE and PDFTOPPM_AVAILABLE

    try:
        with pdfplumber.open(pdf_path) as pdf:
            total_pages = len(pdf.pages)

            with tempfile.TemporaryDirectory() as tmpdir:
                for page_no, page in enumerate(pdf.pages, start=1):
                    native_text = page.extract_text() or ""

                    if len(native_text.strip()) >= MIN_TEXT_CHARS:
                        # Good native text – use it
                        text_parts.append(native_text)
                        methods_used.add("native")

                    elif can_ocr:
                        # Scanned / image page → OCR
                        img = _rasterize_pdf_page(pdf_path, page_no, ocr_dpi, tmpdir)
                        if img:
                            ocr_text = _ocr_page_image(img, ocr_lang)
                            text_parts.append(ocr_text)
                            methods_used.add("ocr")
                            img.close()
                        else:
                            # Rasterization failed; keep whatever native gave us
                            text_parts.append(native_text)
                            methods_used.add("native")

                    else:
                        # OCR disabled or unavailable – use whatever we got
                        text_parts.append(native_text)
                        methods_used.add("native")

    except Exception as e:
        print(f"  [WARNING] Could not read '{pdf_path}': {e}")
        return "", "failed"

    if not methods_used:
        return "", "failed"

    method = "mixed" if len(methods_used) > 1 else methods_used.pop()
    return "\n".join(text_parts), method


# ── Field matching ─────────────────────────────────────────────────────────────

def match_field(pattern: str, text: str) -> str:
    """Apply one regex; return first captured group or '' if no match."""
    try:
        m = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        if m:
            groups = [g for g in m.groups() if g is not None]
            return groups[0].strip() if groups else m.group(0).strip()
    except re.error as e:
        print(f"  [WARNING] Bad regex '{pattern}': {e}")
    return ""


def extract_fields(text: str, patterns: dict) -> dict:
    """Apply all patterns. Missing → empty string."""
    return {field: match_field(pat, text) for field, pat in patterns.items()}


# ── PDF discovery ──────────────────────────────────────────────────────────────

def collect_pdfs(inputs: list) -> list:
    found = []
    for inp in inputs:
        p = Path(inp)
        if p.is_dir():
            found.extend(sorted(p.rglob("*.pdf")))
        elif p.suffix.lower() == ".pdf" and p.is_file():
            found.append(p)
        else:
            print(f"  [WARNING] Skipping '{inp}' – not a PDF or directory.")
    seen, unique = set(), []
    for f in found:
        key = f.resolve()
        if key not in seen:
            seen.add(key)
            unique.append(f)
    return unique


# ── CLI ────────────────────────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Extract fields from PDF(s) using regex patterns from a JSON file.\n"
            "Automatically falls back to OCR for scanned/image pages."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-j", "--json", required=True, metavar="PATTERNS_JSON",
                        help="JSON file with field→regex mappings.")
    parser.add_argument("-p", "--pdfs", required=True, nargs="+", metavar="PDF_OR_DIR",
                        help="PDF file(s) or folder(s) to process.")
    parser.add_argument("-o", "--output", default="output.csv", metavar="OUTPUT_CSV",
                        help="Output CSV path (default: output.csv).")
    parser.add_argument("--encoding", default="utf-8-sig",
                        help="CSV encoding (default: utf-8-sig, Excel-safe).")
    parser.add_argument("--no-ocr", action="store_true",
                        help="Disable OCR fallback entirely.")
    parser.add_argument("--lang", default="eng", metavar="TESSERACT_LANG",
                        help="Tesseract language code (default: eng). "
                             "Use 'eng+hin' for multi-language, etc.")
    parser.add_argument("--ocr-dpi", type=int, default=300, metavar="DPI",
                        help="DPI for page rasterization before OCR (default: 300).")
    return parser.parse_args()


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    args = parse_args()

    # ── Load patterns ──────────────────────────────────────────────────
    json_path = Path(args.json)
    if not json_path.is_file():
        print(f"ERROR: JSON file not found: {json_path}")
        sys.exit(1)
    with open(json_path, "r", encoding="utf-8") as f:
        patterns = json.load(f)
    print(f"✓ Loaded {len(patterns)} field pattern(s) from '{json_path}'.")

    # ── OCR availability report ────────────────────────────────────────
    use_ocr = not args.no_ocr
    if use_ocr:
        if not OCR_AVAILABLE:
            print("  [OCR] pytesseract / Pillow not installed → OCR disabled.")
            print("        Run: pip install pytesseract Pillow")
            use_ocr = False
        elif not PDFTOPPM_AVAILABLE:
            print("  [OCR] pdftoppm not found (install poppler-utils) → OCR disabled.")
            use_ocr = False
        else:
            print(f"  [OCR] Enabled  |  lang={args.lang}  |  dpi={args.ocr_dpi}")
    else:
        print("  [OCR] Disabled (--no-ocr flag set).")

    # ── Collect PDFs ───────────────────────────────────────────────────
    pdf_files = collect_pdfs(args.pdfs)
    if not pdf_files:
        print("ERROR: No PDF files found.")
        sys.exit(1)
    print(f"\nFound {len(pdf_files)} PDF file(s) to process.\n")

    # ── Process & write ────────────────────────────────────────────────
    fieldnames = ["pdf_file", "extraction_method"] + list(patterns.keys())
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    total = len(pdf_files)
    matched_counts = {field: 0 for field in patterns}
    method_tally = {"native": 0, "ocr": 0, "mixed": 0, "failed": 0}

    with open(output_path, "w", newline="", encoding=args.encoding) as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()

        for idx, pdf_path in enumerate(pdf_files, start=1):
            print(f"[{idx}/{total}] {pdf_path.name}")

            text, method = extract_text_from_pdf(
                str(pdf_path),
                use_ocr=use_ocr,
                ocr_lang=args.lang,
                ocr_dpi=args.ocr_dpi,
            )
            method_tally[method] = method_tally.get(method, 0) + 1
            print(f"  extraction : {method}")

            row = extract_fields(text, patterns)
            matched = sum(1 for v in row.values() if v)
            print(f"  fields     : {matched}/{len(patterns)} matched")

            for field, val in row.items():
                if val:
                    matched_counts[field] += 1

            row["pdf_file"] = str(pdf_path)
            row["extraction_method"] = method
            writer.writerow(row)

    # ── Summary ────────────────────────────────────────────────────────
    print(f"\n{'─'*52}")
    print(f"✓ Results saved → {output_path}")
    print(f"\nExtraction method breakdown:")
    for m, count in method_tally.items():
        if count:
            print(f"  {m:<10} : {count} PDF(s)")

    print(f"\nField match summary ({total} PDF(s) total):")
    print(f"  {'Field':<30} {'Matched':>7}")
    print(f"  {'─'*40}")
    for field, count in matched_counts.items():
        icon = "✓" if count > 0 else "✗"
        print(f"  {icon} {field:<28} {count:>5}/{total}")


if __name__ == "__main__":
    main()
