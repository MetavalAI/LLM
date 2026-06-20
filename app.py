import os
import json
import io

import fitz
import ollama
import easyocr
import numpy as np

from PIL import Image
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from fastapi.middleware.cors import CORSMiddleware
from json_repair import repair_json


app = FastAPI(title="MetaVal Dynamic LLM Extraction Engine")

# CORS Setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Load OCR model once globally
reader = easyocr.Reader(["en"], gpu=False)


class DocumentRequest(BaseModel):
    file_path: str
    mapping_data: dict = Field(default_factory=dict)


@app.post("/extract")
async def extract_data(request: DocumentRequest):
    file_path = request.file_path
    mapping_data = request.mapping_data

    print(f"\n⚙️ [Machine 2] Request received to parse: {file_path}")

    print("=" * 60)
    print("Received Path:", file_path)
    print("Exists:", os.path.exists(file_path))
    print("=" * 60)

    if not mapping_data:
        print(
            "⚠️ [Warning] No mapping_data received from Node.js! "
            "Output might be generic."
        )
    else:
        print(
            f"📋 [Machine 2] Dynamic Mapping Loaded for "
            f"{len(mapping_data.keys())} fields."
        )

    if not os.path.exists(file_path):
        raise HTTPException(
            status_code=404,
            detail=f"File not found on network: {file_path}",
        )

    # =====================================================
    # Dynamic Prompt Builder
    # =====================================================
    schema_instructions = {}

    for target_key, config in mapping_data.items():
        aliases = config.get("aliases", [])
        dropdowns = config.get("dropdowns", [])

        instruction = "Extract this value."

        if aliases:
            instruction += (
                f" In the document, it might be called: "
                f"{', '.join(aliases)}."
            )

        if dropdowns:
            instruction += (
                " IMPORTANT: Your output MUST strictly match exactly "
                f"one of these allowed options: {dropdowns}. "
                "If it doesn't match, return null."
            )

        schema_instructions[target_key] = instruction

    schema_json_str = json.dumps(schema_instructions, indent=2)

    expected_format = json.dumps(
        {
            "data": [
                {
                    key: "..."
                    for key in mapping_data.keys()
                }
            ]
        },
        indent=2,
    )

    system_prompt = f"""
You are an expert industrial document parser.

Extract technical specifications from the provided OCR text.

You MUST extract ONLY the following fields based on their aliases
and strict dropdown constraints:

{schema_json_str}

RULES:
1. If a field has a dropdown list, you MUST pick an exact match from that list.
2. Do not invent values.
3. If a field is missing, return null.
4. Output MUST be valid JSON only.
5. Do not include markdown, explanations, notes, or extra text.

Output Structure MUST look exactly like this:

{expected_format}
"""

    results = []

    try:
        print("🧠 [Machine 2] Booting LLM inference...")

        doc = fitz.open(file_path)

        try:
            for idx, page in enumerate(doc):
                print(f"📄 Processing page {idx + 1}")

                # Extract selectable text
                text = page.get_text().strip()

                # OCR fallback
                if not text:
                    print(
                        f"🔍 No selectable text found on page {idx + 1}. "
                        "Running OCR..."
                    )

                    pix = page.get_pixmap(dpi=150)

                    img = Image.open(
                        io.BytesIO(
                            pix.tobytes("png")
                        )
                    )

                    text = " ".join(
                        reader.readtext(
                            np.array(img),
                            detail=0
                        )
                    )

                if not text.strip():
                    print(
                        f"⚠️ Page {idx + 1} contains no readable text."
                    )
                    continue

                # =====================================================
                # Send page text to Ollama
                # =====================================================
                response = ollama.chat(
                    model="gemma3:4b",
                    messages=[
                        {
                            "role": "system",
                            "content": system_prompt,
                        },
                        {
                            "role": "user",
                            "content": f"Document Text:\n{text}",
                        },
                    ],
                    options={
                        "temperature": 0.0
                    },
                )

                content = (
                    response.get("message", {})
                    .get("content", "")
                    .strip()
                )

                # Remove markdown wrappers
                if content.startswith("```json"):
                    content = content[7:]

                if content.startswith("```"):
                    content = content[3:]

                if content.endswith("```"):
                    content = content[:-3]

                try:
                    # Repair malformed JSON
                    fixed_json = repair_json(content.strip())

                    data = json.loads(fixed_json)

                    page_rows = data.get("data", [])

                    if isinstance(page_rows, dict):
                        page_rows = [page_rows]

                    print(
                        f"📊 [DATA EXTRACTED PAGE {idx + 1}]"
                    )
                    print(
                        json.dumps(
                            page_rows,
                            indent=2,
                            ensure_ascii=False,
                        )
                    )

                    for row in page_rows:
                        clean_row = {}

                        for target_key in mapping_data.keys():
                            clean_row[target_key] = row.get(
                                target_key,
                                None,
                            )

                        results.append(clean_row)

                except Exception as json_error:
                    print(
                        f"❌ JSON Repair Failed on page "
                        f"{idx + 1}: {json_error}"
                    )
                    print("Raw Output:")
                    print(content)

        finally:
            doc.close()

        print(
            f"✅ [Machine 2] Extraction successful! "
            f"Total rows extracted: {len(results)}"
        )

        return {
            "status": "success",
            "data": results,
        }

    except Exception as e:
        print(f"❌ [Machine 2] Extraction Error: {str(e)}")

        raise HTTPException(
            status_code=500,
            detail=str(e),
        )


if __name__ == "__main__":
    import uvicorn

    print("🚀 Starting Dynamic MetaVal Python Engine...")

    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )


# uvicorn app:app --host 0.0.0.0 --port 8000
# uvicorn app:app --host 0.0.0.0 --port 8000 --reload
# uvicorn app:app --port 8000