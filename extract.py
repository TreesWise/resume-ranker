import fitz  # PyMuPDF
from docx import Document
import io
import fitz  # PyMuPDF
import subprocess
import tempfile
import shutil
import os
import asyncio

def extract_text_from_pdf(file_like):
    doc = fitz.open(stream=file_like.read(), filetype="pdf")
    text = ""
    for page in doc:
        text += page.get_text()
    return text

# def extract_text_from_docx(file_like):
#     doc = Document(io.BytesIO(file_like.read()))
#     return "\n".join([p.text for p in doc.paragraphs])



# def extract_text_from_pdf(file_like):
#     file_like.seek(0)
#     doc = fitz.open(stream=file_like.read(), filetype="pdf")
#     text = ""
#     for page in doc:
#         text += page.get_text()
#     return text




async def extract_text_from_docx(file_like):
    with tempfile.TemporaryDirectory() as temp_dir:
        docx_path = os.path.join(temp_dir, "temp.docx")
        pdf_path = os.path.join(temp_dir, "temp.pdf")

        with open(docx_path, "wb") as f:
            f.write(file_like.read())

        try:
            process = await asyncio.create_subprocess_exec(
                "libreoffice", "--headless", "--convert-to", "pdf",
                "--outdir", temp_dir, docx_path
            )
            await process.communicate()
        except Exception as e:
            print(f"LibreOffice conversion failed: {e}")
            return ""

        if os.path.exists(pdf_path):
            with open(pdf_path, "rb") as pdf_file:
                return extract_text_from_pdf(pdf_file)
        else:
            print("PDF file not found after conversion.")
            return ""
