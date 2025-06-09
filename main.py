from fastapi import FastAPI, File, UploadFile, Form, Body
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import List
from io import BytesIO
import chardet
import re
from rank import get_relevance_score
from extract import extract_text_from_pdf, extract_text_from_docx
from sqlalchemy import create_engine, text
# Temporary in-memory storage
temp_resume_store = {}
temp_jd_content = None

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/upload-folder/")
async def upload_folder(files: List[UploadFile] = File(...)):
    global temp_resume_store
    temp_resume_store.clear()

    for file in files:
        content = await file.read()
        temp_resume_store[file.filename] = content

    return {"status": "success", "message": f"{len(temp_resume_store)} resumes uploaded temporarily."}


@app.post("/upload-jd/")
async def upload_job_description(jd_file: UploadFile = File(...)):
    global temp_jd_content
    content = await jd_file.read()

    try:
        detected = chardet.detect(content)
        encoding = detected["encoding"] or "utf-8"
        jd_text = content.decode(encoding, errors="ignore")
    except Exception as e:
        return JSONResponse(content={"error": f"Failed to decode JD file: {str(e)}"}, status_code=400)

    temp_jd_content = jd_text
    return {"status": "success", "message": "Job description uploaded temporarily."}


#MSSQL engine using pyodbc
def get_db_engine():
    connection_string = (
        "mssql+pyodbc://@10.201.1.86,50001/Resume_Parser"
        "?driver=ODBC+Driver+17+for+SQL+Server"
        "&trusted_connection=yes"
    )
    return create_engine(connection_string)


def extract_email_regex(text):
    match = re.search(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", text)
    return match.group(0) if match else None

@app.post("/rank-resumes-dynamic/")
async def rank_uploaded_resumes_dynamic(criteria: List[str] = Body(...)):
    global temp_jd_content
    if not temp_resume_store:
        return JSONResponse(content={"error": "No resumes uploaded."}, status_code=400)

    if not temp_jd_content:
        return JSONResponse(content={"error": "No job description uploaded."}, status_code=400)

    jd_text = temp_jd_content
    engine = get_db_engine()
    results = []

    for filename, content in temp_resume_store.items():
        if filename.endswith(".pdf"):
            resume_text = extract_text_from_pdf(BytesIO(content))
        elif filename.endswith(".docx"):
            resume_text = extract_text_from_docx(BytesIO(content))
        else:
            continue

        evaluation_result = get_relevance_score(resume_text, jd_text, criteria)

        # Try to get email from OpenAI
        openai_emails = evaluation_result.get("emails", [])
        email = openai_emails[0] if openai_emails else extract_email_regex(resume_text)
        print(email)

        if not email:
            print(f"No email found in: {filename}")
            continue

        # Check DB for duplicate
        with engine.connect() as conn:
            query = text("SELECT COUNT(*) FROM CV_Ranking_User_Email WHERE email = :email")
            result = conn.execute(query, {"email": email}).scalar()

        if result > 0:
            print(f"Email already exists in DB, skipping: {email}")
            continue

        # Save new email to DB
        with engine.begin() as conn:
            insert_query = text("INSERT INTO CV_Ranking_User_Email (email) VALUES (:email)")
            conn.execute(insert_query, {"email": email})
            print(f"Inserted email: {email}")

        individual_scores = [evaluation_result[c]["score"] for c in criteria]
        weighted_score = round(sum(individual_scores) / len(individual_scores), 2)

        results.append({
            "filename": filename,
            "email": email,
            "emails": openai_emails,
            "weighted_score": weighted_score,
            "section_scores": {c: evaluation_result[c]["score"] for c in criteria},
            "evaluation": evaluation_result
        })

    results.sort(key=lambda x: x["weighted_score"], reverse=True)
    temp_resume_store.clear()
    temp_jd_content = None

    return {"ranked_resumes": results}

@app.get("/", response_class=HTMLResponse)
def upload_form():
    return """
    <html>
        <head>
            <title>Resume Ranker</title>
        </head>
        <body>
            <h2>Upload Resume Folder</h2>
            <form action="/upload-folder/" enctype="multipart/form-data" method="post">
                <label>Select folder containing resumes (.pdf, .docx):</label><br>
                <input type="file" name="files" webkitdirectory directory multiple accept=".pdf,.docx"><br><br>
                <input type="submit" value="Upload Resumes">
            </form>

            <h2>Upload Job Description</h2>
            <form action="/upload-jd/" enctype="multipart/form-data" method="post">
                <label>Select Job Description (.pdf or .docx):</label><br>
                <input type="file" name="jd_file" accept=".pdf,.docx"><br><br>
                <input type="submit" value="Upload JD">
            </form>

            <h2>Rank Resumes (Dynamic)</h2>
            <form id="rankForm">
                <label>Criterion 1:</label><br>
                <input type="text" id="crit1" value=""><br><br>

                <label>Criterion 2:</label><br>
                <input type="text" id="crit2" value=""><br><br>

                <label>Criterion 3:</label><br>
                <input type="text" id="crit3" value=""><br><br>

                <button type="button" onclick="submitRank()">Rank Resumes</button>
            </form>

            <h3>Results:</h3>
            <pre id="resultBox"></pre>

            <script>
                async function submitRank() {
                    const criteria = [
                        document.getElementById("crit1").value.trim(),
                        document.getElementById("crit2").value.trim(),
                        document.getElementById("crit3").value.trim()
                    ].filter(Boolean);

                    const res = await fetch('/rank-resumes-dynamic/', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(criteria)
                    });

                    const result = await res.json();
                    document.getElementById('resultBox').textContent = JSON.stringify(result, null, 2);
                }
            </script>
        </body>
    </html>
    """
