# llm code for extracting the text

import fitz
import json
import pandas as pd
import ollama
import argparse
import logging
import io


SYNONYM_JSON = r"D:\Test\output.json" # change this as per the json location.

# LOGGING
logging.basicConfig(filename="error.log", level=logging.ERROR, format="%(asctime)s - %(levelname)s - %(message)s")

# SYNONYM FUNCTIONS
def load_synonym_mapping(json_path):

    with open(json_path, "r", encoding="utf-8") as f:data = json.load(f)

    mapping = {}

    for item in data:

        canonical = item["canonical"]

        for synonym in item["synonyms"]:
            mapping[synonym.strip().lower()] = canonical

    return mapping


def normalize_fields(extracted_data, synonym_map):

    normalized = {}

    for key, value in extracted_data.items():

        canonical_key = synonym_map.get(
            key.strip().lower(),
            key
        )

        normalized[canonical_key] = value

    return normalized

# VALIDATION layer
EXPECTED_FIELDS = [
    "Tag_Number",
    "Service",
    "Line_No.",
    "Line_Size",
    "Line_ID",
    "Type_of_taps"
]


def validate_output(data):

    for field in EXPECTED_FIELDS:

        if field not in data:
            data[field] = "NA"

    return data

# OCR
OCR_READER = None

def get_ocr_reader():

    global OCR_READER

    if OCR_READER is None:

        import easyocr

        OCR_READER = easyocr.Reader(['en'], gpu=False)

    return OCR_READER

# PDF TEXT EXTRACTION
def extract_page_text(page, page_num):

    page_text = page.get_text()

    if page_text.strip():
        return page_text

    print(f"Page {page_num} scanned detected. OCR running...")

    try:

        pix = page.get_pixmap(dpi=200)

        import numpy as np
        from PIL import Image

        img_data = pix.tobytes("png")

        image = Image.open(io.BytesIO(img_data))

        reader = get_ocr_reader()

        text_list = reader.readtext(np.array(image), detail=0)

        page_text = " ".join(text_list)

        return page_text

    except Exception as e:

        logging.error(f"OCR Error Page {page_num}: {e}")

        return ""

# LLM EXTRACTION
def extract_fields_from_document(text):

    prompt = f"""
You are an engineering datasheet extraction system.

Extract ONLY these fields:

Tag_Number
Service
Line_No.
Line_Size
Line_ID
Type_of_taps

RULES:

1. Return ONLY valid JSON.
2. No markdown.
3. No explanation.
4. Do not guess.
5. If value is not explicitly found use "NA".
6. Ignore revision history.
7. Ignore page headers and footers.
8. Extract values belonging to the main instrument.

Return format:

{{
  "Tag_Number":"",
  "Service":"",
  "Line_No.":"",
  "Line_Size":"",
  "Line_ID":"",
  "Type_of_taps":""
}}

DOCUMENT:

{text}
"""
    response = ollama.chat(
        model="gemma3:4b",
        messages=[{"role": "user", "content": prompt}], options={"temperature": 0.0})

    result = response["message"]["content"]

    result = result.replace("```json", "").replace("```", "").strip()

    try:

        return json.loads(result)

    except Exception as e:

        logging.error(
            f"Invalid JSON from LLM: {e}"
        )

        return {
            "Tag_Number": "ERROR",
            "Service": "ERROR",
            "Line_No.": "ERROR",
            "Line_Size": "ERROR",
            "Line_ID": "ERROR",
            "Type_of_taps": "ERROR"
        }

# SAVE EXCEL
def save_excel(data, output_path):

    df = pd.DataFrame([data])

    cols = [
        "Tag_Number",
        "Service",
        "Line_No.",
        "Line_Size",
        "Line_ID",
        "Type_of_taps"
    ]

    df = df.reindex(columns=cols)

    df.to_excel(
        output_path,
        index=False
    )

# MAIN
def main():

    parser = argparse.ArgumentParser()
    parser.add_argument("-p", "--pdf_path", required=True)
    parser.add_argument("-o", "--output", required=True)
    args = parser.parse_args()
    print("Loading synonym file...")
    synonym_map = load_synonym_mapping(SYNONYM_JSON)
    print("Opening PDF...")
    doc = fitz.open(args.pdf_path)
    total_pages = len(doc)
    print(f"Pages Found: {total_pages}")
    full_text = ""

    for i in range(total_pages):

        page_num = i + 1

        print(
            f"Reading Page {page_num}/{total_pages}"
        )

        page_text = extract_page_text(
            doc[i],
            page_num
        )

        full_text += (
            f"\n\n--- PAGE {page_num} ---\n\n"
        )

        full_text += page_text

    if not full_text.strip():

        print(
            "No text found in PDF."
        )

        return

    print("\nSending complete PDF to LLM...")

    extracted_data = extract_fields_from_document(full_text)

    extracted_data = normalize_fields(extracted_data, synonym_map)

    extracted_data = validate_output(extracted_data)

    print("\nExtracted Data:")

    print(json.dumps(extracted_data, indent=4))

    save_excel(extracted_data, args.output)

    print(f"\nExcel saved at: {args.output}")


if __name__ == "__main__":
    main()


# python test.py -p "D:\Test\EI00362-DATA-OP.pdf" -o "D:\Test\output.xlsx"
# "D:\Test\EI00362-DATA-OP.pdf"
# "D:\Test\output.xlsx"
# python -m py_compile test.py