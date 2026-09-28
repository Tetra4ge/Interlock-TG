import sys
import time
from pathlib import Path

try:
    import fitz  # PyMuPDF
    import pdfplumber
except ImportError as e:
    print(f"Required package missing: {e}. Ensure pymupdf and pdfplumber are installed.")
    sys.exit(1)

def run_bakeoff(pdf_path: str):
    path = Path(pdf_path)
    if not path.exists():
        print(f"Test PDF not found at {pdf_path}")
        return

    print(f"=== Parser Bakeoff: {path.name} ===")
    
    # 1. PyMuPDF (fitz)
    print("\n[1] PyMuPDF (fitz) Extraction")
    start = time.perf_counter()
    try:
        doc = fitz.open(path)
        first_page_text = doc[0].get_text() if len(doc) > 0 else ""
        pages = len(doc)
        doc.close()
        t = (time.perf_counter() - start) * 1000
        
        print(f"  Time  : {t:.2f} ms")
        print(f"  Pages : {pages}")
        print(f"  Output: {first_page_text[:120].replace(chr(10), ' ')}...")
    except Exception as e:
        print(f"  Failed: {e}")

    # 2. pdfplumber
    print("\n[2] pdfplumber Extraction")
    start = time.perf_counter()
    try:
        with pdfplumber.open(path) as pdf:
            first_page_text = pdf.pages[0].extract_text() if len(pdf.pages) > 0 else ""
            pages = len(pdf.pages)
        t = (time.perf_counter() - start) * 1000
        
        print(f"  Time  : {t:.2f} ms")
        print(f"  Pages : {pages}")
        print(f"  Output: {first_page_text[:120].replace(chr(10), ' ')}...")
    except Exception as e:
        print(f"  Failed: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m spikes.parser_bakeoff <path_to_pdf>")
        print("Place a sample PDF in data/inbox/ to run this test.")
    else:
        run_bakeoff(sys.argv[1])
