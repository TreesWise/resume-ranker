# import fitz  # PyMuPDF
# from docx import Document
# import io

# def extract_text_from_pdf(file_like):
#     doc = fitz.open(stream=file_like.read(), filetype="pdf")
#     text = ""
#     for page in doc:
#         text += page.get_text()
#     return text

# def extract_text_from_docx(file_like):
#     doc = Document(io.BytesIO(file_like.read()))
#     return "\n".join([p.text for p in doc.paragraphs])



import fitz  # PyMuPDF
from docx import Document
import io
import subprocess
import tempfile
import os


def extract_text_from_pdf(file_like):
    """Extract text from PDF using PyMuPDF."""
    doc = fitz.open(stream=file_like.read(), filetype="pdf")
    text = ""
    for page in doc:
        text += page.get_text()
    return text


def convert_docx_to_pdf(docx_bytes):
    """
    Convert DOCX bytes to PDF bytes using LibreOffice in headless mode.
    Requires LibreOffice to be installed on the system.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        docx_path = os.path.join(tmpdir, "input.docx")
        pdf_path = os.path.join(tmpdir, "input.pdf")

        # Save the DOCX bytes to a temp file
        with open(docx_path, "wb") as f:
            f.write(docx_bytes)

        # Run LibreOffice to convert DOCX to PDF
        try:
            subprocess.run(
                ["libreoffice", "--headless", "--convert-to", "pdf", docx_path, "--outdir", tmpdir],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"LibreOffice failed to convert DOCX to PDF: {e}")

        # Read the resulting PDF
        if not os.path.exists(pdf_path):
            raise FileNotFoundError("PDF file was not created by LibreOffice.")

        with open(pdf_path, "rb") as f:
            return f.read()


def extract_text_from_docx(file_like):
    """
    Extract text from a DOCX file by converting it to PDF using LibreOffice,
    then extracting the text from the resulting PDF using PyMuPDF.
    """
    docx_bytes = file_like.read()
    pdf_bytes = convert_docx_to_pdf(docx_bytes)
    return extract_text_from_pdf(io.BytesIO(pdf_bytes))
