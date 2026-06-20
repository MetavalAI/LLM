import fitz
import json
import pandas as pd
import ollama
import argparse
import logging
import os


# Log file setup
logging.basicConfig(
    filename="error.log",
    level=logging.ERROR,
    format="%(asctime)s - %(levelname)s - %(message)s"
)


def extract_page_text(page, page_num):
    """
    Ek single page ka text nikalta hai.
    Agar scanned PDF hai to OCR bhi karega.
    """

    page_text = page.get_text()

    # Agar selectable text nahi mila to OCR
    if not page_text.strip():
        print(f"   -> Page {page_num} scanned lag raha hai, OCR chal raha hai...")

        try:
            import easyocr
            import numpy as np
            from PIL import Image
            import io

            pix = page.get_pixmap(dpi=150)

            reader = easyocr.Reader(["en"], gpu=False)

            img_data = pix.tobytes("png")
            image = Image.open(io.BytesIO(img_data))

            bounds = reader.readtext(
                np.array(image),
                detail=0
            )

            page_text = " ".join(bounds)

        except ImportError:
            error_msg = (
                f"Page {page_num}: OCR ke liye easyocr install nahi hai."
            )

            print(f"   [ERROR] {error_msg}")
            logging.error(error_msg)

            page_text = ""

        except Exception as e:
            error_msg = (
                f"Page {page_num} par OCR fail ho gaya: {e}"
            )

            print(f"   [ERROR] {error_msg}")
            logging.error(error_msg)

            page_text = ""

    return page_text


def extract_fields_from_page(text, page_num):
    """
    Ek single page ke text se JSON data nikalta hai.
    """

    if not text.strip():
        return None

    prompt = f"""
You are an expert engineering document extraction AI.

Your job is to read the text of a SINGLE PAGE from a document and find specific fields.

Extract ONLY these fields and use them exactly as JSON keys:

- Tag_Number
- Service
- Line_No.
- Line_Size
- Line_ID
- Type_of_taps

RULES:

1. Return ONLY a single valid JSON object for this page.
2. Do not include markdown code blocks like ```json ... ```.
3. No explanation, just raw JSON.
4. If a field is missing, set its value to "NA".
5. Extract data ONLY from the text provided below.

DOCUMENT PAGE TEXT:

{text}
"""

    response = ollama.chat(
        model="gemma3:4b",
        messages=[
            {
                "role": "user",
                "content": prompt
            }
        ],
        options={
            "temperature": 0.0
        }
    )

    result = response["message"]["content"]

    result = (
        result
        .replace("```json", "")
        .replace("```", "")
        .strip()
    )

    try:
        data = json.loads(result)

        data["Source_Page"] = f"Page {page_num}"

        return data

    except json.JSONDecodeError as e:

        error_msg = (
            f"Page {page_num} ka LLM output valid JSON nahi hai. "
            f"Error: {e}"
        )

        print(f"   [ERROR] {error_msg}")
        logging.error(error_msg)

        return {
            "Tag_Number": "ERROR",
            "Service": "ERROR",
            "Line_No.": "ERROR",
            "Line_Size": "ERROR",
            "Line_ID": "ERROR",
            "Type_of_taps": "ERROR",
            "Source_Page": f"Page {page_num}"
        }


def save_excel(all_data_list, output_path):
    """
    Excel save karta hai.
    """

    try:
        df = pd.DataFrame(all_data_list)

        cols = [
            "Source_Page",
            "Tag_Number",
            "Service",
            "Line_No.",
            "Line_Size",
            "Line_ID",
            "Type_of_taps"
        ]

        df = df.reindex(columns=cols)

        df.to_excel(output_path, index=False)

    except Exception as e:

        error_msg = (
            f"Excel save karte waqt error aaya: {e}"
        )

        print(f"[ERROR] {error_msg}")
        logging.error(error_msg)


def main():

    try:
        parser = argparse.ArgumentParser()

        parser.add_argument(
            "-p",
            "--pdf_path",
            required=True
        )

        parser.add_argument(
            "-o",
            "--output",
            required=True
        )

        args = parser.parse_args()

        print("\n[1/3] PDF File khol raha hoon...")

        doc = fitz.open(args.pdf_path)

        total_pages = len(doc)

        print(f"Total Pages Mile: {total_pages}")

        all_extracted_rows = []

        # Har page ko individually process karo
        for i in range(total_pages):

            page_num = i + 1

            print(
                f"\n--- Processing Page "
                f"{page_num}/{total_pages} ---"
            )

            page_text = extract_page_text(
                doc[i],
                page_num
            )

            if page_text.strip():

                print(
                    f"   LLM ko bhej raha hoon "
                    f"Page {page_num} ka text..."
                )

                page_data = extract_fields_from_page(
                    page_text,
                    page_num
                )

                if page_data:
                    all_extracted_rows.append(page_data)

                    print(
                        f"   Data extracted: "
                        f"Tag -> {page_data.get('Tag_Number')}"
                    )

            else:

                error_msg = (
                    f"Page {page_num} khali mila."
                )

                print(f"   [Skip] {error_msg}")

                logging.error(error_msg)

        doc.close()

        if not all_extracted_rows:
            print(
                "\n[tagda error] Kisi bhi page se "
                "koi text ya data nahi mila."
            )
            return

        print("\n[2/3] Sabhi pages ka extracted data:")

        print(
            json.dumps(
                all_extracted_rows,
                indent=4
            )
        )

        print("-----------------------------------")

        print(
            f"\n[3/3] Excel me total "
            f"{len(all_extracted_rows)} "
            f"lines/entries save ho rhi hain..."
        )

        save_excel(
            all_extracted_rows,
            args.output
        )

        print(
            f"Mubarak ho! Excel save ho gayi hai "
            f"iss location pe:\n{args.output}\n"
        )

    except Exception as e:

        error_msg = f"Fatal Error: {e}"

        print(f"\n[FATAL ERROR] {error_msg}")

        logging.error(error_msg)


if __name__ == "__main__":
    main()



# # python app.py -p D:\Test\EI00362-DATA-OP.pdf -o D:\Test\output.xlsx
# # D:\Test\EI00362-DATA-OP.pdf
# # D:\Test\output.xlsx