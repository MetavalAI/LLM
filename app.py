# machine 2
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import fitz, json, os, ollama, easyocr, numpy as np, io
from PIL import Image

app = FastAPI(title="MetaVal LLM Extraction Engine")
reader = easyocr.Reader(['en'], gpu=False)

# 1. Define the exact JSON structure Node.js will send
class DocumentRequest(BaseModel):
    file_path: str

@app.post("/extract")
async def extract_data(request: DocumentRequest):
    file_path = request.file_path
    print(f"\n⚙️ [Machine 2] Request received to parse: {file_path}")
    
    # 2. Safety Check: Ensure the file dropped by OneDrive actually exists
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found on disk")
        
    # We define the specific fields Node.js PostgreSQL database expects
    allowed_fields = ["doc_no", "rev", "item_description", "fluid_state"]
    results = []
    
    # 3. Dynamic System Prompt
    system_prompt = f"""
    Tu ek expert engineering data sheet parser hai. PDF se technical specs nikal.
    1. Document Number ya Tag Number dhoond.
    2. Ye specific fields extract kar: {', '.join(allowed_fields)}.
    3. Agar field nahi milti to 'NA' likh.
    4. Strict JSON format mein output de.
    Structure: {{"data": [{{"doc_no": "...", "rev": "...", "item_description": "...", "fluid_state": "..."}}]}}
    """
    
    try:
        print("🧠 [Machine 2] Booting LLM inference...")
        doc = fitz.open(file_path)
        
        # 4. Process each page (Text first, OCR as fallback)
        for idx, page in enumerate(doc):
            text = page.get_text().strip()
            
            # If no selectable text, trigger EasyOCR
            if not text:
                pix = page.get_pixmap(dpi=150)
                img = Image.open(io.BytesIO(pix.tobytes("png")))
                text = " ".join(reader.readtext(np.array(img), detail=0))
            
            # 5. Send to Ollama (Gemma 3)
            response = ollama.chat(model='gemma3:4b', messages=[
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': f"Extract data:\n{text}"}
            ], options={'temperature': 0.0})
            
            # Clean and parse JSON response
            content = response['message']['content'].replace('```json', '').replace('```', '')
            data = json.loads(content)
            print(f"📊 [DATA EXTRACTED PAGE {idx+1}]: {json.dumps(data, indent=2)}")
            
            # 6. Normalize data for Node.js
            for item in data.get("data", []):
                clean_row = {
                    "doc_no": str(item.get("doc_no", "UNKNOWN")).strip().upper(),
                    "rev": str(item.get("rev", "0")).strip(),
                    "item_description": str(item.get("item_description", "NA")).strip(),
                    "fluid_state": str(item.get("fluid_state", "NA")).strip()
                }
                results.append(clean_row)

        doc.close()
        
        # Grab the first extracted item to send back to Node.js
        final_data = results[0] if results else {"doc_no": "UNKNOWN", "rev": "0", "item_description": "NA", "fluid_state": "NA"}
        
        print(f"✅ [Machine 2] Extraction successful! Sending back to Node.js...")
        
        # Node expects response.data.data
        return {"status": "success", "data": final_data}
        
    except Exception as e:
        print(f"❌ [Machine 2] Extraction Error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))



# uvicorn app:app --host 0.0.0.0 --port 8000 --reload
# uvicorn app:app --port 8000