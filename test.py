# test_extract.py
# Basic PDF -> Structured Extraction Test
# Input PDF path and output JSON path are taken from terminal arguments

import pdfplumber
import pandas as pd
import json
import re
import sys
from pathlib import Path


def clean_text(text):
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def extract_text_from_pdf(pdf_path):
    full_text = []

    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            text = page.extract_text()
            if text:
                full_text.append(f"\n--- PAGE {page_num} ---\n")
                full_text.append(text)

    return clean_text("\n".join(full_text))


def simple_field_extraction(text):
    """
    Basic regex-based extraction test
    Modify/add fields as needed
    """

    data = {
        "invoice_number": None,
        "date": None,
        "total_amount": None,
        "vendor_name": None,
    }

    invoice_match = re.search(r"Invoice\s*No[:\-]?\s*(\S+)", text, re.I)
    date_match = re.search(r"Date[:\-]?\s*([0-9\/\-\.]+)", text, re.I)
    amount_match = re.search(r"Total\s*Amount[:\-]?\s*([\d,]+\.\d{2})", text, re.I)

    if invoice_match:
        data["invoice_number"] = invoice_match.group(1)

    if date_match:
        data["date"] = date_match.group(1)

    if amount_match:
        data["total_amount"] = amount_match.group(1)

    # Example vendor extraction
    lines = text.split("\n")
    if lines:
        data["vendor_name"] = lines[0][:100]

    return data


def save_output(data, output_path):
    output_path = Path(output_path)

    if output_path.suffix.lower() == ".json":
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)

    elif output_path.suffix.lower() == ".xlsx":
        df = pd.DataFrame([data])
        df.to_excel(output_path, index=False)

    else:
        raise ValueError("Output file must be .json or .xlsx")


def main():
    if len(sys.argv) != 3:
        print("\nUsage:")
        print("python test_extract.py <pdf_path> <output_path>")
        print("\nExample:")
        print("python test_extract.py sample.pdf output.json\n")
        sys.exit(1)

    pdf_path = sys.argv[1]
    output_path = sys.argv[2]

    print(f"\nReading PDF: {pdf_path}")

    text = extract_text_from_pdf(pdf_path)

    print("\nExtracting fields...")

    extracted_data = simple_field_extraction(text)

    print("\nExtracted Data:")
    print(json.dumps(extracted_data, indent=4))

    save_output(extracted_data, output_path)

    print(f"\nOutput saved to: {output_path}")


if __name__ == "__main__":
    main()