import fitz                     # PyMuPDF: PDF files se text aur images extract karne ke liye
import json                     # LLM ke JSON response ko parse karne ke liye
import pandas as pd             # Data ko structure karke Excel me convert karne ke liye
import ollama                   # Local LLM (Gemma 3) ko call karne ke liye
import argparse                 # Command-line arguments (-p pdf_path) handle karne ke liye
import logging                  # Errors ko 'error.log' file me record karne ke liye
import os                       # File paths aur folders create/manage karne ke liye
import psycopg2                 # PostgreSQL database se connect karne ke liye
from datetime import datetime   # Timestamp (date/time) lagane ke liye

# Yahan aapke local PostgreSQL connection ki details hain.
DB_CONFIG = {
    "host":     "localhost",
    "port":     5432,
    "database": "pdf_extraction_db",
    "user":     "postgres",
    "password": "admin"
}

# Data isi sequence me final excel sheet me populate hoga.
EXCEL_COLUMNS = [
    "TagNo", "Item Name", "Quantity", "Project", "Plate MATERIAL",
    "Flange MATERIAL", "Flange Type", "Piece Type", "Weld Type", "Holder Type",
    "Line_Size", "Size in NPS OR DN", "Flange Schedule", "Pipe Wall Thk", "Rating",
    "RJ HOLDER MATERIAL", "Drain/Vent", "Smooth Finish", "Serration", "Stellite",
    "Fluid/Service_Name", "Service Discription", "Service Type", "Calculation Standard",
    "Flow Element Type", "Flow Rate Unit", "Flow Rate Minimum", "Flow Rate Maximum",
    "Flow Rate Normal", "Flow Rate at FullScale", "Tapping", "Multi Hole", "Pipe Material",
    "Pressure Unit", "Temp Unit", "Viscosity Unit", "Density Unit", "Density_Calc_Method",
    "MolecularWeight_Customer", "Compressibility_atFlow_Customer", "Compressibility_atBase_Customer",
    "Gas Name", "Base Pressure", "Upstream Pressure", "Base_Temperature", "Operating_Temperature",
    "Vapour_Pressure", "Density_at_Base_Customer", "Density_at_Flow_Customer", "Viscosity_Customer",
    "IsentropicExponent_Customer", "DP Unit", "DP at Full Scale", "Design Pressure Discription",
    "Design Pressure", "Design Temp Discription", "Design Temp", "Flange Standard",
    "Plate Thk Customer", "Spare Plate Required", "Stud/Nut", "Gasket", "JackBolt",
    "Packing_Cost_Manual", "Accessories", "Accessories_Amt", "IBR", "IBR_Amt_Manual",
    "Nace", "Nace_Type", "Nace_Percent", "Calibration", "CalibrationAmt_Manual",
    "Freight_Required", "Freight_Amt_Manual", "Special_Requirement", "Special_Requirement_Amt",
    "OFA Tap Orientation", "FNA Tap Orientation", "Venturi Tap Orientation", "Plug_Material",
    "Pressure_Tap_Angle", "JackBold_Position", "ItemCode_Heading", "ItemCode", "TestSchedule",
    "FNA Pipe Machining Required", "FNA Pipe Machined Cost", "FNA Total Assy. Length",
    "FNA Upstream Length", "FNA Pipe Length Show to Customer", "FNA Pipe Length Customer",
    "Chamfer", "ØD1", "Adapter Rating", "Flow Nozzle Holding Ring Material", "Flow Nozzle Material",
    "Nipple Material", "Nipple Size", "Nipple Schedule", "Nipple Quantity", "Venturi Throat Material",
    "Cyllinder Material", "Cone Material", "Piezometer RIng Material", "End Flange Standard",
    "End Flange Type", "End Flange Material", "End Flange Rating", "No of End Flange",
    "Adapter Material", "No. of Tapping 1", "Tap Size 1", "No. of Tapping 2", "Tap Size 2",
    "Companion Flange Required", "Tapping Flange", "Tapping Flange Size", "PilotTube Type",
    "Duct Inside Width", "Duct Outside Width", "Duct Inside Height", "Duct Outside Height",
    "PitotTube Probe Material", "Pitot Tube Type", "Pitot End Support", "Clamping Condition",
    "Pitot Tube End Connection Material", "Pitot Tube Sleeve Material",
]

# Logging System Config: Script ke runtime faults isi file me datetime stamp ke sath log honge.
logging.basicConfig(
    filename="error.log",
    level=logging.ERROR,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# Yeh function har page se textual content read karta hai. Agar page ek flat image/scanned copy hai,
# toh fallback mechanism ke taur par EasyOCR trigger karke computer vision se characters read karta hai.
def extract_page_text(page, page_num):
    page_text = page.get_text() # Native layer se text nikalne ki koshish

    # Agar string empty milti hai toh OCR mode chalu hoga
    if not page_text.strip():
        print(f"   -> Page {page_num} scanned lag raha hai, OCR chal raha hai...")
        try:
            import easyocr
            import numpy as np
            from PIL import Image
            import io

            # Page surface ko 150 DPI image matrix me convert kiya gaya
            pix = page.get_pixmap(dpi=150)
            reader = easyocr.Reader(["en"], gpu=False) # CPU optimization par load kiya
            img_data = pix.tobytes("png")
            image    = Image.open(io.BytesIO(img_data))
            bounds    = reader.readtext(np.array(image), detail=0)
            page_text = " ".join(bounds) # Fragmented array ko flat single string me wrap kiya

        except ImportError:
            msg = f"Page {page_num}: easyocr install nahi hai — OCR skip."
            print(f"   [ERROR] {msg}")
            logging.error(msg)
            page_text = ""

        except Exception as e:
            msg = f"Page {page_num} OCR fail: {e}"
            print(f"   [ERROR] {msg}")
            logging.error(msg)
            page_text = ""

    return page_text


# Is function me strict prompt architecture ke zariye raw text local Gemma model ko 
# forward kiya jata hai taaki woh strict unstructured-to-structured JSON conversion kare.
def extract_fields_from_page(text, page_num):
    if not text.strip():
        return None

#     prompt = f"""
# You are an expert at extracting data from Instrumentation Data Sheets (IDS) for Orifice Plates and Flanges.

# The document is a structured table. Each row has a ROW NUMBER, a FIELD NAME, and a VALUE.

# Extract the following fields and return a single flat JSON object.
# Use the EXACT key names listed below. No extra keys. No arrays. No markdown.

# === FIELD EXTRACTION RULES ===

# "TagNo"
#   - Row 1 in the GENERAL section
#   - Looks like: 073-FE-1301, 073-FE-1302, etc.
#   - NEVER use Document No. (like B903-073-YF-DS-3100) — that is a different field
#   - NEVER use Ref. No. or Job No.
#   - Example correct value: "073-FE-1301"

# "Fluid/Service_Name"
#   - Row 2, labeled "Service"
#   - Example: "EFFLUENT WASTE WATER"

# "Line_Size"
#   - Row 4, labeled "Line Size"
#   - Extract ONLY the pipe size in NPS format like 8", 12", 14", 18"
#   - Do NOT include Line ID or OD values (like 202.7 or 219.1)
#   - Example correct value: "8\""

# "Tapping"
#   - Row 6, labeled "Type of taps"
#   - Extract ONLY the tap type value like: "Flange", "D-D/2", "Corner", "Pipe"
#   - Do NOT include tap size or any other description
#   - Example correct value: "Flange"

# "Flow Rate Maximum"
#   - Row 9, labeled "Maximum Flow" with unit m3/h
#   - Extract ONLY the numeric value
#   - Example: 125

# "Flow Rate Normal"
#   - Row 10, labeled "Normal Flow" with unit m3/h
#   - Extract ONLY the numeric value
#   - Example: 100

# "Flow Rate Minimum"
#   - Row 11, labeled "Minimum Flow" with unit m3/h
#   - Extract ONLY the numeric value
#   - Example: 50

# "Upstream Pressure"
#   - Row 12, labeled "Operating Inlet Pressure"
#   - Extract the numeric value only
#   - Example: 3.1

# "Pressure Unit"
#   - Unit associated with Operating Inlet Pressure
#   - Example: "kg/cm2g"

# "Operating_Temperature"
#   - Row 13, labeled "Operating Temperature"
#   - Extract value as-is: "ambient" or numeric like 25
#   - Do NOT put "Degree of Super Heat" here — that is a different row

# "Temp Unit"
#   - Unit for Operating Temperature
#   - Example: "deg C" or "C"

# "Design Temp"
#   - Row 14, labeled "Design Temperature"
#   - Extract numeric value only
#   - Example: 65

# "Pipe Material"
#   - Row 29, labeled "Plate Material"
#   - Example: "SS 316"

# "Flange MATERIAL"
#   - Row 45, labeled "Flange Material"
#   - Example: "ASTM A 105"

# "Flange Type"
#   - Row 42, labeled "Type of Flange"
#   - Example: "Weld Neck"
#   - Common values: Weld Neck, Slip On, Socket Weld, RTJ

# "Rating"
#   - Row 46, labeled "Size & Rating" — extract ONLY the rating part (not the size)
#   - Example: "300#", "150#", "600#"
#   - Do NOT put "ISO 5167" or any standard here

# "No. of Tapping 1"
#   - Row 44, labeled "No. of Taps per flange"
#   - Convert text to number: "Two" = 2, "One" = 1, "Four" = 4
#   - Example: 2

# "Tap Size 1"
#   - Row 43, labeled "Tap Size" with unit mm
#   - Extract numeric value only
#   - Example: 0.5

# "Flange Standard"
#   - Row 47 area, labeled "Facing & Finish" is different — look for Flange Standard separately
#   - Common values: "ANSI B16.5", "ASME B16.5"

# "Stud/Nut"
#   - Row 50, labeled "Stud Bolt Material"
#   - Example: "A193 GR.B7"

# "Gasket"
#   - Row 49, labeled "Gasket Material"
#   - Example: "SP.WND SS316+GRAFIL+I RING"

# "IBR"
#   - Row 52, labeled "Statutory"
#   - Example: "NA", "Yes", "No"

# "Calculation Standard"
#   - Row 28, labeled "Basis of Sizing"
#   - Example: "ISO 5167"

# "Flow Element Type"
#   - Row 27, labeled "Type"
#   - Example: "Conc. Square Edged"

# === RULES ===
# 1. Return ONLY a valid JSON object — no array, no markdown, no explanation
# 2. Missing value => "NA"
# 3. Numbers stay as numbers (not strings) for numeric fields
# 4. Read row numbers carefully — do not confuse similar-looking rows

# DOCUMENT TEXT:
# {text}
# """
    prompt = f"""
You are a document data extraction engine.

Extract fields from the following Instrument Data Sheet text.

Return ONLY a valid JSON object.
No explanation. No markdown. No extra keys.

---

RULES:
- If value is missing → use "NA"
- Numbers must be numeric (not strings)
- Extract EXACT values only (no guessing)
- Do not include units unless specified
- If multiple values exist, choose the most relevant one

---

FIELDS TO EXTRACT:

TagNo:
- Format like 073-FE-1301
- NEVER use document/job/ref numbers

Fluid/Service_Name:
- Service name of system

Line_Size:
- Pipe size like 8", 12"
- Ignore OD or numeric diameters

Tapping:
- Only one of: Flange, D-D/2, Corner, Pipe

Flow Rate Minimum:
Flow Rate Maximum:
Flow Rate Normal:
- Numeric only

Upstream Pressure:
Pressure Unit:

Operating_Temperature:
- numeric or "ambient"
- ignore "superheat" type text

Temp Unit:

Design Temp:
- numeric only

Pipe Material:
Flange MATERIAL:
Flange Type:
Rating:

No. of Tapping 1:
- convert words to number (two → 2)

Tap Size 1:

Flange Standard:

Stud/Nut:
Gasket:
IBR:
Calculation Standard:
Flow Element Type:

---

INPUT TEXT:
{text}
"""

    # Ollama execution engine call
    response = ollama.chat(

        # model="qwen3-vl:4b"   # ✅ Vision
        model="gemma3:4b",       # ✅ Vision
        # model="qwen2.5:4b"    # ❌ Text-only
        # model="qwen2.5:3b"    # ❌ Text-only
        
        messages=[{"role": "user", "content": prompt}],
        options={"temperature": 0.0} # Deterministic values ke liye strict temperature set kiya
    )

    # Markdown elements stripping
    result = (
        response["message"]["content"]
        .replace("```json", "")
        .replace("```", "")
        .strip()
    )

    try:
        data = json.loads(result)
        print(f"   Response Type: {type(data).__name__}")

        # List wrapper array bypass rule
        if isinstance(data, list):
            if not data:
                msg = f"Page {page_num}: Empty list aayi LLM se."
                print(f"   [ERROR] {msg}")
                logging.error(msg)
                return None
            data = data[0]

        if isinstance(data, dict):
            data = post_process(data, page_num) # Clean values schema normalization
            data["Source_Page"] = f"Page {page_num}"
            return data

        msg = f"Page {page_num}: Unexpected type {type(data).__name__}"
        print(f"   [ERROR] {msg}")
        logging.error(msg)
        return None

    except json.JSONDecodeError as e:
        msg = f"Page {page_num} JSON parse fail: {e}"
        print(f"   [ERROR] {msg}")
        logging.error(msg)
        return {
            "TagNo":       "ERROR",
            "Line_Size":   "ERROR",
            "Source_Page": f"Page {page_num}"
        }


# LLM hallucinations aur standardisation formats (jaise metrics normalization, strings clean karna)
# ko manage karne ke liye specialized regex aur dictionary mapping algorithms.
def post_process(data, page_num):
    import re

    # Suspicious TagNo Validation Rule
    tag = str(data.get("TagNo", ""))
    if tag.startswith("B9") or tag.startswith("8903") or len(tag) > 20:
        print(f"   [WARN] Page {page_num}: TagNo suspicious = '{tag}' — manually verify")
        logging.warning(f"Page {page_num}: TagNo suspicious: {tag}")

    # Regex based NPS Size validation rule (Sirf 8" ya 12" format retain karne ke liye)
    line_size = str(data.get("Line_Size", ""))
    nps_match = re.search(r'(\d+(?:\.\d+)?)\s*["\']', line_size)
    if nps_match:
        data["Line_Size"] = nps_match.group(0).strip()

    # Standard leak validation rule inside Rating Column
    rating = str(data.get("Rating", ""))
    if "ISO" in rating or "ANSI" in rating or "ASME" in rating:
        print(f"   [WARN] Page {page_num}: Rating field me standard aa gaya: '{rating}'")
        data["Rating"] = "NA"

    # String word conversion logic for Numeric Values
    taps_raw = str(data.get("No. of Tapping 1", "")).lower().strip()
    word_to_num = {"one": 1, "two": 2, "three": 3, "four": 4, "six": 6, "eight": 8}
    if taps_raw in word_to_num:
        data["No. of Tapping 1"] = word_to_num[taps_raw]

    # Standard keyword extraction for Tapping Column
    tapping = str(data.get("Tapping", ""))
    for keyword in ["Flange", "D-D/2", "Corner", "Pipe", "Vena Contracta"]:
        if keyword.lower() in tapping.lower():
            data["Tapping"] = keyword
            break

    # Typo validation checks inside Flange structure data
    ft = str(data.get("Flange Type", ""))
    ft_clean = ft.replace("WNeld", "Weld").replace("Neld", "Weld")
    data["Flange Type"] = ft_clean

    # Float/Integer absolute filtering rule from mixed numeric string types
    for flow_field in ["Flow Rate Minimum", "Flow Rate Maximum", "Flow Rate Normal",
                       "Upstream Pressure", "Design Temp", "Tap Size 1"]:
        val = data.get(flow_field, "NA")
        if val and val != "NA":
            try:
                num_match = re.search(r'[\d.]+', str(val))
                if num_match:
                    data[flow_field] = float(num_match.group())
            except:
                pass

    # Operating Temperature filtering rule for cross-row mismatch blocks
    ot = str(data.get("Operating_Temperature", ""))
    if "degree" in ot.lower() or "super heat" in ot.lower():
        data["Operating_Temperature"] = "NA"
        print(f"   [WARN] Page {page_num}: Operating_Temperature had wrong value, set to NA")

    return data

# Ingest data payload to PostgreSQL engine with an automatic UPSERT feature.
# Agar combination duplicate hai toh target row updates algorithm chalu ho jata hai.
def save_to_postgres(all_data_list, pdf_name, timestamp):
    try:
        conn   = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()

        success_count = 0
        for row in all_data_list:
            tag_no = row.get("TagNo", "NA")
            if not tag_no or tag_no in ("NA", "ERROR"):
                continue

            cursor.execute("""
                INSERT INTO ofa_upload (
                    "TagNo", "PDF_Name", "PDF_RunTimestamp",
                    "Line_Size", "Fluid/Service_Name", "Tapping",
                    "Flow Rate Minimum", "Flow Rate Maximum", "Flow Rate Normal",
                    "Upstream Pressure", "Pressure Unit",
                    "Operating_Temperature", "Temp Unit", "Design Temp",
                    "Pipe Material", "Flange MATERIAL", "Flange Type",
                    "Rating", "No. of Tapping 1", "Tap Size 1",
                    "Flange Standard", "Stud/Nut", "Gasket",
                    "IBR", "Calculation Standard", "Flow Element Type"
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s
                )
                ON CONFLICT ("TagNo", "PDF_Name") DO UPDATE SET
                    "PDF_RunTimestamp"    = EXCLUDED."PDF_RunTimestamp",
                    "Line_Size"           = EXCLUDED."Line_Size",
                    "Fluid/Service_Name"  = EXCLUDED."Fluid/Service_Name",
                    "Tapping"             = EXCLUDED."Tapping",
                    "Flow Rate Minimum"   = EXCLUDED."Flow Rate Minimum",
                    "Flow Rate Maximum"   = EXCLUDED."Flow Rate Maximum",
                    "Flow Rate Normal"    = EXCLUDED."Flow Rate Normal",
                    "Upstream Pressure"   = EXCLUDED."Upstream Pressure",
                    "Pressure Unit"       = EXCLUDED."Pressure Unit",
                    "Operating_Temperature" = EXCLUDED."Operating_Temperature",
                    "Temp Unit"           = EXCLUDED."Temp Unit",
                    "Design Temp"         = EXCLUDED."Design Temp",
                    "Pipe Material"       = EXCLUDED."Pipe Material",
                    "Flange MATERIAL"     = EXCLUDED."Flange MATERIAL",
                    "Flange Type"         = EXCLUDED."Flange Type",
                    "Rating"              = EXCLUDED."Rating",
                    "No. of Tapping 1"    = EXCLUDED."No. of Tapping 1",
                    "Tap Size 1"          = EXCLUDED."Tap Size 1",
                    "Flange Standard"     = EXCLUDED."Flange Standard",
                    "Stud/Nut"            = EXCLUDED."Stud/Nut",
                    "Gasket"              = EXCLUDED."Gasket",
                    "IBR"                 = EXCLUDED."IBR",
                    "Calculation Standard" = EXCLUDED."Calculation Standard",
                    "Flow Element Type"   = EXCLUDED."Flow Element Type"
            """, (
                tag_no,
                pdf_name,
                timestamp,
                row.get("Line_Size", "NA"),
                row.get("Fluid/Service_Name", "NA"),
                row.get("Tapping", "NA"),
                row.get("Flow Rate Minimum", 0) or 0,
                row.get("Flow Rate Maximum", 0) or 0,
                row.get("Flow Rate Normal", 0) or 0,
                row.get("Upstream Pressure", 0) or 0,
                row.get("Pressure Unit", "NA"),
                row.get("Operating_Temperature", "NA"),
                row.get("Temp Unit", "NA"),
                row.get("Design Temp", 0) or 0,
                row.get("Pipe Material", "NA"),
                row.get("Flange MATERIAL", "NA"),
                row.get("Flange Type", "NA"),
                row.get("Rating", "NA"),
                row.get("No. of Tapping 1", 0) or 0,
                row.get("Tap Size 1", "NA"),
                row.get("Flange Standard", "NA"),
                row.get("Stud/Nut", "NA"),
                row.get("Gasket", "NA"),
                row.get("IBR", "NA"),
                row.get("Calculation Standard", "NA"),
                row.get("Flow Element Type", "NA"),
            ))
            success_count += 1

        conn.commit()
        print(f"   ✅ PostgreSQL me {success_count} rows save ho gayi!")
        cursor.close()
        conn.close()

    except Exception as e:
        print(f"   ❌ DB Error: {e}")
        logging.error(f"PostgreSQL save failed [{pdf_name}]: {e}")

# Array payload structural format reindexing engine through Pandas logic setup
def save_excel(all_data_list, output_path):
    df = pd.DataFrame(all_data_list)
    df = df.reindex(columns=EXCEL_COLUMNS) # Structural indexing constraint execution
    df.to_excel(output_path, index=False)
    print(f"   ✅ Excel save ho gayi: {output_path}")

# Ingestion system core orchestration center block. Handles argument routing configurations.
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-p", "--pdf_path", required=True, help="PDF file ka path")
    args = parser.parse_args()

    pdf_path  = args.pdf_path
    pdf_name  = os.path.splitext(os.path.basename(pdf_path))[0]
    pdf_dir   = os.path.dirname(pdf_path)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Creating targets configurations sub-directories
    output_folder = os.path.join(pdf_dir, "output")
    os.makedirs(output_folder, exist_ok=True)
    output_path = os.path.join(output_folder, f"{pdf_name}_{timestamp}.xlsx")

    print(f"\n{'='*55}")
    print(f"   PDF: {pdf_name}")
    print(f"   Run: {timestamp}")
    print(f"{'='*55}")

    print("\n[1/3] PDF khol raha hoon...")
    doc         = fitz.open(pdf_path)
    total_pages = len(doc)
    print(f"      Total Pages: {total_pages}")

    all_extracted_rows = []

    print("\n[2/3] Pages process ho rahi hain...")
    for i in range(total_pages):
        page_num  = i + 1
        print(f"\n   --- Page {page_num}/{total_pages} ---")

        page_text = extract_page_text(doc[i], page_num)

        if page_text.strip():
            print(f"      LLM ko bhej raha hoon...")
            page_data = extract_fields_from_page(page_text, page_num)
            if page_data:
                all_extracted_rows.append(page_data)
        else:
            msg = f"Page {page_num} khali mili — skip."
            print(f"      [Skip] {msg}")
            logging.error(msg)

    doc.close()

    if not all_extracted_rows:
        print("\n[ERROR] Kisi bhi page se data nahi mila. Exit.")
        return

    total = len(all_extracted_rows)
    print(f"\n[3/3] {total} rows mili — save ho rhi hain...")

    save_to_postgres(all_extracted_rows, pdf_name, timestamp)
    save_excel(all_extracted_rows, output_path)

    print(f"\n{'='*55}")
    print(f"   Mubarak ho! Kaam ho gaya.")
    print(f"   Excel: {output_path}")
    print(f"   DB:    ofa_upload table ({pdf_name})")
    print(f"{'='*55}\n")


if __name__ == "__main__":
    main()

# python test.py -p D:\Test\EI00362-DATA-OP-1.pdf

# psql -U postgres -d pdf_extraction_db
# SELECT COUNT(*) FROM ofa_upload;
# SELECT * FROM ofa_upload;