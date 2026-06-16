# machine 2
import os
import json
import io
import fitz
import ollama
import easyocr
import numpy as np
from PIL import Image
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="MetaVal Dynamic LLM Extraction Engine")

# CORS setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Load OCR only once globally
reader = easyocr.Reader(['en'], gpu=False)

# 1. 100% Dynamic Schema: Node.js se file_path aur mapping_data dono aayenge
class DocumentRequest(BaseModel):
    file_path: str
    mapping_data: dict = {}  # Ye Node.js ka buildDynamicMappingPayload() bhejega

@app.post("/extract")
async def extract_data(request: DocumentRequest):
    # Fix the slash issue for Windows UNC Network Paths
    file_path = request.file_path
    mapping_data = request.mapping_data
    
    print(f"\n⚙️ [Machine 2] Request received to parse: {file_path}")

    # DEBUG
    print("=" * 60)
    print("Received Path:", file_path)
    print("Exists:", os.path.exists(file_path))
    print("=" * 60)
    
    if not mapping_data:
        print("⚠️ [Warning] No mapping_data received from Node.js! Output might be generic.")
    else:
        print(f"📋 [Machine 2] Dynamic Mapping Loaded for {len(mapping_data.keys())} fields.")

    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"File not found on network: {file_path}")

    # ==========================================
    # 🧠 DYNAMIC PROMPT BUILDER
    # ==========================================
    # Node.js ke bheje gaye keywords aur dropdowns se hum LLM ke liye rules banayenge
    schema_instructions = {}
    for target_key, config in mapping_data.items():
        aliases = config.get("aliases", [])
        dropdowns = config.get("dropdowns", [])
        
        instruction = "Extract this value."
        if aliases:
            instruction += f" In the document, it might be called: {', '.join(aliases)}."
        if dropdowns:
            instruction += f" IMPORTANT: Your output MUST strictly match exactly one of these allowed options: {dropdowns}. If it doesn't match, return null."
            
        schema_instructions[target_key] = instruction

    # Convert the required schema into strings for the LLM
    schema_json_str = json.dumps(schema_instructions, indent=2)
    expected_format = json.dumps({"data": [{k: "..." for k in mapping_data.keys()}]}, indent=2)

    system_prompt = f"""
    You are an expert industrial document parser. Extract technical specifications from the provided OCR text.
    
    You MUST extract ONLY the following fields based on their aliases and strict dropdown constraints:
    {schema_json_str}
    
    RULES:
    1. If a field has a dropdown list, you MUST pick an exact match from that list. Do not invent words.
    2. If a field is missing from the text, return null for that field.
    3. Output MUST be valid JSON format only without any conversational text or markdown.
    
    Output Structure MUST look exactly like this:
    {expected_format}
    """

    results = []
    
    try:
        print("🧠 [Machine 2] Booting LLM inference...")
        doc = fitz.open(file_path)
        
        # 3. Process each page
        for idx, page in enumerate(doc):
            text = page.get_text().strip()
            
            # Trigger OCR if text is not selectable
            if not text:
                pix = page.get_pixmap(dpi=150)
                img = Image.open(io.BytesIO(pix.tobytes("png")))
                text = " ".join(reader.readtext(np.array(img), detail=0))
            
            if not text.strip():
                continue
            
            # Send to Ollama (Gemma 3)
            response = ollama.chat(model='gemma3:4b', messages=[
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': f"Document Text:\n{text}"}
            ], options={'temperature': 0.0}) # Temperature 0 = Strict Accuracy
            
            # Clean JSON response
            content = response['message']['content'].strip()
            if content.startswith("```json"):
                content = content[7:]
            if content.endswith("```"):
                content = content[:-3]
            
            try:
                data = json.loads(content.strip())
                page_rows = data.get("data", [])
                
                if isinstance(page_rows, dict):
                    page_rows = [page_rows]
                
                print(f"📊 [DATA EXTRACTED PAGE {idx+1}]: {json.dumps(page_rows, indent=2)}")
                
                # 4. Filter only the requested dynamic keys
                for row in page_rows:
                    clean_row = {}
                    for target_key in mapping_data.keys():
                        clean_row[target_key] = row.get(target_key, None)
                    results.append(clean_row)
                    
            except json.JSONDecodeError:
                print(f"⚠️ [Machine 2] JSON Parsing failed on page {idx+1}. Raw output: {content}")

        doc.close()
        
        print(f"✅ [Machine 2] Extraction successful! Total rows extracted: {len(results)}")
        
        # Return exact structure expected by Node.js
        return {"status": "success", "data": results}
        
    except Exception as e:
        print(f"❌ [Machine 2] Extraction Error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    print("🚀 Starting Dynamic MetaVal Python Engine...")
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)



# uvicorn app:app --host 0.0.0.0 --port 8000 --reload
# uvicorn app:app --port 8000