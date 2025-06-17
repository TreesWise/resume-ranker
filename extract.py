import fitz  # PyMuPDF
from docx import Document
import io
from docx import Document
import os
import platform
from fastapi import HTTPException
import asyncio

def extract_text_from_pdf(file_like):
    doc = fitz.open(stream=file_like.read(), filetype="pdf")
    text = ""
    for page in doc:
        text += page.get_text()
    return text

    

def extract_text_from_docx(file_like):
    doc = Document(io.BytesIO(file_like.read()))
    # Extract text from paragraphs
    text = "\n".join([p.text for p in doc.paragraphs if p.text.strip() != ""])
    # Extract text from tables
    for table in doc.tables:
        for row in table.rows:
            row_text = " | ".join([cell.text.strip() for cell in row.cells if cell.text.strip() != ""])
            text += "\n" + row_text
    # Extract text from headers (heading levels 1-9)
    for paragraph in doc.paragraphs:
        if paragraph.style.name.startswith('Heading'):
            text += "\n" + paragraph.text.strip()
    return text
