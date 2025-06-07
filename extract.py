import fitz  # PyMuPDF
from docx import Document
import io

def extract_text_from_pdf(file_like):
    doc = fitz.open(stream=file_like.read(), filetype="pdf")
    text = ""
    for page in doc:
        text += page.get_text()
    return text

def extract_text_from_docx(file_like):
    doc = Document(io.BytesIO(file_like.read()))
    return "\n".join([p.text for p in doc.paragraphs])
