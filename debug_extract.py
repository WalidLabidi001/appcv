import pdfplumber
import os

def extract_text(filepath):
    try:
        text_parts = []
        with pdfplumber.open(filepath) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text(x_tolerance=2, y_tolerance=2)
                if not page_text:
                    page_text = page.extract_text(layout=True)
                if page_text:
                    text_parts.append(page_text)
        return '\n'.join(text_parts).strip()
    except Exception as e:
        return f"Error: {e}"

uploads_dir = r"c:\Users\kaddo\Downloads\appcv\uploads"
for filename in os.listdir(uploads_dir):
    if filename.endswith(".pdf"):
        print(f"--- {filename} ---")
        text = extract_text(os.path.join(uploads_dir, filename))
        print(text[:1000]) # First 1000 chars
        print("\n\n")
