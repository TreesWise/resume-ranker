from fastapi import FastAPI, File, UploadFile, Form, Query, Depends, HTTPException, Header
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import create_engine, text
from typing import List
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
import asyncio
import uuid
import re
import os
from dotenv import load_dotenv
import io

from extract import extract_text_from_pdf, extract_text_from_docx
from rank import get_relevance_score, calculate_weighted_score_manual

# Load env
load_dotenv()
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN")

app = FastAPI()

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

executor = ThreadPoolExecutor(max_workers=10)  # ⭐ CHANGED: global thread pool

def get_db_engine():
    return create_engine("sqlite:///Resume_Parser.db", connect_args={"check_same_thread": False})

def extract_email_regex(text):
    match = re.search(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", text)
    return match.group(0) if match else None

def initialize_database():
    engine = get_db_engine()
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS TempResumes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT, email TEXT, resume_content TEXT,
                uploaded_by TEXT, upload_session_id TEXT, created_at DATETIME
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS TempJobDescription (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uploaded_by TEXT, job_title TEXT, jd_text TEXT,
                upload_session_id TEXT, created_at DATETIME
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS CV_Ranking_User_Email (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT, weighted_score REAL, uploaded_by TEXT,
                job_title TEXT, created_at DATETIME
            )
        """))

# ⭐ Parallel extraction helper
def parse_resume(file_name, content_bytes):
    if file_name.endswith(".pdf"):
        return extract_text_from_pdf(io.BytesIO(content_bytes))
    elif file_name.endswith(".docx"):
        return extract_text_from_docx(io.BytesIO(content_bytes))
    return None

import re

@app.post("/upload-folder/")
async def upload_folder(uploaded_by: str = Form(...), files: List[UploadFile] = File(...)):
    session_id = str(uuid.uuid4())
    bad_files = []

    def sanitize_filename(file_name):
        # Remove special characters that may cause issues
        return re.sub(r'[<>:"/\|?*]', '_', file_name)

    async def process_and_store(file):
        try:
            content = await file.read()
            sanitized_filename = sanitize_filename(file.filename)  # sanitize the filename
            loop = asyncio.get_running_loop()
            resume_text = await loop.run_in_executor(executor, parse_resume, sanitized_filename, content)
            
            if not resume_text:
                bad_files.append(sanitized_filename)
                return
            
            email = extract_email_regex(resume_text) or "unknown@example.com"
            engine = get_db_engine()
            with engine.begin() as conn:
                conn.execute(text("""
                    INSERT INTO TempResumes (filename, email, resume_content, uploaded_by, upload_session_id, created_at)
                    VALUES (:filename, :email, :resume_content, :uploaded_by, :session_id, :created_at)
                """), {
                    "filename": sanitized_filename, "email": email, "resume_content": resume_text,
                    "uploaded_by": uploaded_by, "session_id": session_id, "created_at": datetime.now()
                })
        except Exception as e:
            bad_files.append(file.filename)

    tasks = [process_and_store(file) for file in files]
    await asyncio.gather(*tasks)

    return {"status": "success", "uploaded_by": uploaded_by, "bad_files": bad_files}

# ✅ upload-jd unchanged except make it async
@app.post("/upload-jd/")
async def upload_job_description(
    uploaded_by: str = Form(...), job_title: str = Form(...), jd_file: UploadFile = File(...)
):
    content = await jd_file.read()
    loop = asyncio.get_running_loop()
    if jd_file.filename.endswith(".docx"):
        jd_text = await loop.run_in_executor(executor, extract_text_from_docx, io.BytesIO(content))
    elif jd_file.filename.endswith(".pdf"):
        jd_text = await loop.run_in_executor(executor, extract_text_from_pdf, io.BytesIO(content))
    else:
        return JSONResponse(content={"error": "Unsupported file type"}, status_code=400)

    job_title_lower = job_title.strip().lower()
    session_id = str(uuid.uuid4())
    engine = get_db_engine()

    with engine.begin() as conn:
        existing = conn.execute(text("""
            SELECT jd_text FROM TempJobDescription WHERE LOWER(job_title)=:job_title
            ORDER BY created_at DESC LIMIT 1
        """), {"job_title": job_title_lower}).fetchone()
        if existing:
            return {"status": "exists", "job_title": job_title}

        conn.execute(text("""
            INSERT INTO TempJobDescription (uploaded_by, job_title, jd_text, upload_session_id, created_at)
            VALUES (:uploaded_by, :job_title, :jd_text, :session_id, :created_at)
        """), {"uploaded_by": uploaded_by, "job_title": job_title_lower,
               "jd_text": jd_text, "session_id": session_id, "created_at": datetime.now()})

    return {"status": "success", "job_title": job_title}

# ⭐ Parallel ranking
class RankRequest(BaseModel):
    criteria_with_weights: List[dict]
    uploaded_by: str
    job_title: str

@app.post("/rank-resumes-dynamic/")
async def rank_uploaded_resumes_dynamic(request: RankRequest):
    criteria = [c["criterion"] for c in request.criteria_with_weights]
    uploaded_by = request.uploaded_by
    job_title_norm = request.job_title.strip().lower()

    engine = get_db_engine()
    jd_row = None
    with engine.connect() as conn:
        jd_row = conn.execute(text("""
            SELECT jd_text FROM TempJobDescription WHERE LOWER(job_title)=:jt
            ORDER BY created_at DESC LIMIT 1
        """), {"jt": job_title_norm}).fetchone()
    if not jd_row:
        return JSONResponse(content={"error": "No JD found"}, status_code=400)

    jd_text = jd_row[0]

    session_id_row = None
    with engine.connect() as conn:
        session_id_row = conn.execute(text("""
            SELECT upload_session_id FROM TempResumes WHERE uploaded_by=:ub
            ORDER BY created_at DESC LIMIT 1
        """), {"ub": uploaded_by}).fetchone()
    if not session_id_row:
        return JSONResponse(content={"error": "No resumes found"}, status_code=400)

    session_id = session_id_row[0]
    resumes = []
    with engine.connect() as conn:
        resumes = conn.execute(text("""
            SELECT filename, email, resume_content FROM TempResumes
            WHERE uploaded_by=:ub AND upload_session_id=:sid
        """), {"ub": uploaded_by, "sid": session_id}).fetchall()

    async def evaluate_resume(filename, email, resume_text):
        loop = asyncio.get_running_loop()
        eval_result = await loop.run_in_executor(executor, get_relevance_score, resume_text, jd_text, criteria)
        weighted_score, _ = calculate_weighted_score_manual(eval_result, request.criteria_with_weights)
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO CV_Ranking_User_Email (email, weighted_score, uploaded_by, job_title, created_at)
                VALUES (:email, :score, :ub, :jt, :dt)
            """), {"email": email, "score": weighted_score, "ub": uploaded_by, "jt": job_title_norm, "dt": datetime.now()})
        return {
            "filename": filename, "email": email, "weighted_score": weighted_score,
            "section_scores": {c: eval_result[c] for c in criteria},
            "evaluation_summary": eval_result.get("summary_comment", ""), "status": "processed"
        }

    tasks = [evaluate_resume(f, e, t) for f, e, t in resumes]
    results = await asyncio.gather(*tasks)
    results.sort(key=lambda x: x.get("weighted_score", 0), reverse=True)
    return {"ranked_resumes": results}

@app.get("/get-records/")
async def get_records(
    job_title: str = Query(None, description="Job title to fetch ranked resumes")
):
    engine = get_db_engine()

    # elif job_title and not email:
    normalized_job_title = job_title.strip().lower()
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT id, email, created_at, weighted_score, uploaded_by, job_title
            FROM CV_Ranking_User_Email
            WHERE job_title = :job_title
            ORDER BY weighted_score DESC
        """), {"job_title": normalized_job_title}).mappings().all()

    response = []
    for row in result:
        response.append({
            "id": row["id"],
            "email": row["email"],
            "created_at": str(row["created_at"]),
            "weighted_score": row["weighted_score"],
            "uploaded_by": row["uploaded_by"],
            "job_title": row["job_title"]
        })

    return {"job_title": job_title, "ranked_resumes": response}


@app.get("/job-titles/")
async def get_job_titles(query: str = Query(default=None, description="Optional search query")):
    engine = get_db_engine()
    with engine.connect() as conn:
        if query:
            result = conn.execute(text("""
                SELECT DISTINCT job_title 
                FROM TempJobDescription 
                WHERE job_title LIKE :query 
                ORDER BY job_title
            """), {"query": f"%{query.lower()}%"}).fetchall()
        else:
            result = conn.execute(text("""
                SELECT DISTINCT job_title 
                FROM TempJobDescription 
                ORDER BY job_title
            """)).fetchall()

        job_titles = [row[0] for row in result if row[0]]
        return {"job_titles": job_titles}
    
from fastapi import Depends, HTTPException, Header
from dotenv import load_dotenv
load_dotenv()

async def verify_admin_token(x_admin_token: str = Header(...)):
    if x_admin_token != ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Unauthorized")
    

import os
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN")
@app.get("/debug/all-data", dependencies=[Depends(verify_admin_token)])
def get_all_data():
    engine = get_db_engine()
    with engine.connect() as conn:
        resumes = conn.execute(text("SELECT * FROM TempResumes")).mappings().all()
        jd = conn.execute(text("SELECT * FROM TempJobDescription")).mappings().all()
        rankings = conn.execute(text("SELECT * FROM CV_Ranking_User_Email")).mappings().all()
    return {
        "TempResumes": [dict(row) for row in resumes],
        "TempJobDescription": [dict(row) for row in jd],
        "CV_Ranking_User_Email": [dict(row) for row in rankings],
    }



@app.get("/clear-db/")
def clear_database_now():
    try:
        clear_old_data()
        return {"status": "success", "message": "Database cleared successfully."}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/", response_class=HTMLResponse)
def upload_form():
    return """
<!DOCTYPE html>
<html>
<head>
    <title>Resume Ranker</title>
    <style>
        body { font-family: Arial, sans-serif; padding: 20px; }
        input[type="text"], input[type="file"] { margin-bottom: 10px; }
        .criterion-item { margin-bottom: 10px; padding: 10px; border: 1px solid #ccc; }
    </style>
</head>
<body>
    <h2>Upload Resume Folder</h2>
    <form id="resumeUploadForm" action="/upload-folder/" enctype="multipart/form-data" method="post">
        <label>Upload by (Your Name):</label><br>
        <input type="text" name="uploaded_by" id="uploaded_by_input" required><br>
        <label>Select folder containing resumes (.pdf, .docx):</label><br>
        <input type="file" name="files" webkitdirectory directory multiple accept=".pdf,.docx" required><br>
        <input type="submit" value="Upload Resumes">
    </form>
    <div id="resumeUploadResult"></div>

    <hr>

    <h2>Upload Job Description & Role</h2>
    <form id="jdUploadForm" action="/upload-jd/" enctype="multipart/form-data" method="post">
        <label>Uploaded by (Your Name):</label><br>
        <input type="text" name="uploaded_by" id="jd_uploaded_by_input" required><br>
        <label>Select Job Description (.pdf or .docx):</label><br>
        <input type="file" name="jd_file" accept=".pdf,.docx" required><br>
        <label>Job Role:</label><br>
        <input type="text" name="job_title" id="job_title_input" required><br>
        <input type="submit" value="Upload JD + Job Role">
    </form>
    <div id="jdUploadResult"></div>

    <hr>

    <h2>Rank Resumes (Dynamic)</h2>
    <p><strong>Note:</strong> The first criterion you add will have the most weight, second slightly less, and so on.</p>
    <form id="rankForm">
        <input type="hidden" id="rank_uploaded_by">
        <input type="hidden" id="rank_job_title">
        <div id="criteriaList"></div>
        <button type="button" onclick="addCriterion()">Add Criterion</button>
        <button type="button" onclick="submitRank()">Rank Resumes</button>
    </form>
    <h3>Results:</h3>
    <pre id="resultBox"></pre>

    <hr>

    <h2>Search Records by Job Title</h2>
    <form id="getRecordsForm">
        <label>Job Title:</label><br>
        <input type="text" id="recordsInput" required><br>
        <button type="button" onclick="getRecords()">Search</button>
    </form>
    <h3>Search Result:</h3>
    <pre id="recordsResult"></pre>

    <hr>

    <h2>Available Job Titles</h2>
    <button onclick="fetchJobTitles()">Load Job Titles</button>
    <ul id="jobTitlesList"></ul>

<script>
    document.getElementById('resumeUploadForm').addEventListener('submit', async function (e) {
        e.preventDefault();
        const formData = new FormData(this);
        const uploadedBy = document.getElementById("uploaded_by_input").value.trim();
        const res = await fetch(this.action, { method: 'POST', body: formData });
        const result = await res.json();
        document.getElementById('resumeUploadResult').textContent = JSON.stringify(result, null, 2);
        if (uploadedBy) document.getElementById("rank_uploaded_by").value = uploadedBy;
    });

    document.getElementById('jdUploadForm').addEventListener('submit', async function (e) {
        e.preventDefault();
        const formData = new FormData(this);
        const jobTitle = document.getElementById("job_title_input").value.trim();
        const uploadedBy = document.getElementById("jd_uploaded_by_input").value.trim();

        if (!jobTitle || !uploadedBy) {
            document.getElementById('jdUploadResult').textContent = "Please fill all required fields.";
            return;
        }

        const res = await fetch(this.action, { method: 'POST', body: formData });
        const result = await res.json();
        document.getElementById('jdUploadResult').textContent = JSON.stringify(result, null, 2);

        if (jobTitle) document.getElementById("rank_job_title").value = jobTitle;
        if (uploadedBy) document.getElementById("rank_uploaded_by").value = uploadedBy;
    });

    async function getRecords() {
        const input = document.getElementById("recordsInput").value.trim();
        const output = document.getElementById("recordsResult");
        if (!input) {
            output.textContent = "Please enter a job title.";
            return;
        }
        const queryParam = `job_title=${encodeURIComponent(input)}`;
        try {
            const res = await fetch(`/get-records/?${queryParam}`);
            const result = await res.json();
            output.textContent = JSON.stringify(result, null, 2);
        } catch (err) {
            output.textContent = "Error fetching records: " + err.message;
        }
    }

    let criterionIndex = 0;

    function addCriterion(name = "") {
        const container = document.createElement("div");
        container.className = "criterion-item";
        container.id = `criterion-${criterionIndex}`;
        container.innerHTML = `
            <label>Criterion:</label>
            <input type="text" name="criterion" value="${name}" required>
            <button type="button" onclick="removeCriterion('criterion-${criterionIndex}')">Remove</button>
        `;
        document.getElementById("criteriaList").appendChild(container);
        criterionIndex++;
    }

    function removeCriterion(id) {
        const el = document.getElementById(id);
        if (el) el.remove();
    }

    async function submitRank() {
        const uploadedBy = document.getElementById("rank_uploaded_by").value.trim();
        const jobTitle = document.getElementById("rank_job_title").value.trim();
        const resultBox = document.getElementById("resultBox");
        const items = document.querySelectorAll("#criteriaList .criterion-item");

        if (!uploadedBy || !jobTitle || items.length === 0) {
            resultBox.textContent = "Please fill all required fields and add at least one criterion.";
            return;
        }

        const criteria_with_weights = [];
        for (const item of items) {
            const criterion = item.querySelector('input[name="criterion"]').value.trim();
            if (!criterion) {
                resultBox.textContent = "All criteria must be filled.";
                return;
            }
            criteria_with_weights.push({ criterion });
        }

        const payload = {
            uploaded_by: uploadedBy,
            job_title: jobTitle,
            criteria_with_weights: criteria_with_weights
        };

        try {
            const res = await fetch("/rank-resumes-dynamic/", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });
            const result = await res.json();
            resultBox.textContent = JSON.stringify(result, null, 2);
        } catch (err) {
            resultBox.textContent = "Error calling API: " + err.message;
        }
    }

    async function fetchJobTitles() {
        const listElement = document.getElementById("jobTitlesList");
        listElement.innerHTML = "<li>Loading...</li>";
        try {
            const res = await fetch("/job-titles/");
            const data = await res.json();

            if (data.job_titles && data.job_titles.length > 0) {
                listElement.innerHTML = "";
                data.job_titles.forEach(title => {
                    const li = document.createElement("li");
                    li.textContent = title;
                    listElement.appendChild(li);
                });
            } else {
                listElement.innerHTML = "<li>No job titles found.</li>";
            }
        } catch (err) {
            listElement.innerHTML = `<li>Error loading job titles: ${err.message}</li>`;
        }
    }

    window.addEventListener("load", () => {
        addCriterion();
    });
</script>
</body>
</html>
"""



# === Monthly Cleanup Logic Starts Here ===
from apscheduler.schedulers.background import BackgroundScheduler

def clear_old_data():
    engine = get_db_engine()
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM TempResumes"))
        conn.execute(text("DELETE FROM TempJobDescription"))
        conn.execute(text("DELETE FROM CV_Ranking_User_Email"))
    print("[INFO] Database cleared as part of monthly cleanup.")

def schedule_monthly_cleanup():
    scheduler = BackgroundScheduler()
    scheduler.add_job(clear_old_data, 'cron', day='last', hour=23, minute=59)
    scheduler.start()


@app.on_event("startup")
def on_startup():
    schedule_monthly_cleanup()
    initialize_database() 
# === Monthly Cleanup Logic Ends Here ===


