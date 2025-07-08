

from fastapi import FastAPI, File, UploadFile, Form, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import List
from io import BytesIO
from pydantic import BaseModel
from sqlalchemy import create_engine, text
from datetime import datetime, timedelta
import uuid
import re

from extract import extract_text_from_pdf, extract_text_from_docx
from rank import get_relevance_score, calculate_weighted_score_manual

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def initialize_database():
    engine = get_db_engine()
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS TempResumes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT,
                email TEXT,
                resume_content TEXT,
                uploaded_by TEXT,
                upload_session_id TEXT,
                created_at DATETIME
            )
        """))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS TempJobDescription (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uploaded_by TEXT,
                job_title TEXT,
                jd_text TEXT,
                upload_session_id TEXT,
                created_at DATETIME
            )
        """))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS CV_Ranking_User_Email (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT,
                weighted_score REAL,
                uploaded_by TEXT,
                job_title TEXT,
                created_at DATETIME
            )
        """))

# @app.on_event("startup")
# def on_startup():
#     initialize_database()  # Create tables if not exist
#     schedule_monthly_cleanup()  # Your existing monthly cleanup




def get_db_engine():
    return create_engine("sqlite:///Resume_Parser.db", connect_args={"check_same_thread": False})

def extract_email_regex(text):
    match = re.search(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", text)
    return match.group(0) if match else None




@app.post("/upload-folder/")
async def upload_folder(uploaded_by: str = Form(...), files: List[UploadFile] = File(...)):
    session_id = str(uuid.uuid4())
    engine = get_db_engine()

    with engine.begin() as conn:
        bad_files = []

        for file in files:
            content = await file.read()
            file_name = file.filename
            try:
                if file_name.endswith(".pdf"):
                    resume_text = extract_text_from_pdf(BytesIO(content))
                elif file_name.endswith(".docx"):
                    resume_text = extract_text_from_docx(BytesIO(content))
                else:
                    print(f"[SKIPPED] Unsupported file format: {file_name}")
                    bad_files.append(file_name)
                    continue


                if not resume_text:
                    print(f"[ERROR] Could not extract text from file: {file_name}")
                    bad_files.append(file_name)
                    continue

                if not resume_text:
                    continue

                email = extract_email_regex(resume_text) or "unknown@example.com"

                # Always insert regardless of existing content
                conn.execute(text("""
                    INSERT INTO TempResumes (
                        filename,
                        email,
                        resume_content,
                        uploaded_by,
                        upload_session_id,
                        created_at
                    ) VALUES (
                        :filename,
                        :email,
                        :resume_content,
                        :uploaded_by,
                        :upload_session_id,
                        :created_at
                    )
                """), {
                    "filename": file.filename,
                    "email": email,
                    "resume_content": resume_text,
                    "uploaded_by": uploaded_by,
                    "upload_session_id": session_id,
                    "created_at": datetime.now()
                })
            except Exception as e:
                print(f"[ERROR] Failed to extract from {file_name}: {e}")
                bad_files.append(file_name)

    return {
        "status": "success",
        "message": f"{len(files)} resumes uploaded.",
        "uploaded_by": uploaded_by
    }


@app.post("/upload-jd/")
async def upload_job_description(
    uploaded_by: str = Form(...),
    job_title: str = Form(...),
    jd_file: UploadFile = File(...)
):
    content = await jd_file.read()
    engine = get_db_engine()
    session_id = str(uuid.uuid4())

    jd_text = (
        extract_text_from_docx(BytesIO(content)) if jd_file.filename.endswith(".docx")
        else extract_text_from_pdf(BytesIO(content)) if jd_file.filename.endswith(".pdf")
        else None
    )
    if not jd_text:
        return JSONResponse(content={"error": "Unsupported file type"}, status_code=400)

    job_title_lower = job_title.strip().lower()

    with engine.begin() as conn:
        existing_jd = conn.execute(text("""
            SELECT jd_text 
            FROM TempJobDescription
            WHERE LOWER(job_title) = :job_title
            ORDER BY created_at DESC
            LIMIT 1
        """), {
            "job_title": job_title_lower
        }).fetchone()

        if existing_jd:
            return {
                "status": "exists",
                "message": f"A job description for '{job_title}' already exists and will be used.",
                "uploaded_by": uploaded_by,
                "job_title": job_title
            }

        conn.execute(text("""
            INSERT INTO TempJobDescription (uploaded_by, job_title, jd_text, upload_session_id, created_at)
            VALUES (:uploaded_by, :job_title, :jd_text, :upload_session_id, :created_at)
        """), {
            "uploaded_by": uploaded_by,
            "job_title": job_title_lower,
            "jd_text": jd_text,
            "upload_session_id": session_id,
            "created_at": datetime.now()
        })

    return {
        "status": "success",
        "message": "Job description uploaded.",
        "uploaded_by": uploaded_by,
        "job_title": job_title
    }

class RankRequest(BaseModel):
    criteria_with_weights: List[dict]  # still expecting [{criterion: "X"}]
    uploaded_by: str
    job_title: str


@app.post("/rank-resumes-dynamic/")
async def rank_uploaded_resumes_dynamic(request: RankRequest):
    # criteria = request.criteria
    criteria_with_weights = request.criteria_with_weights
    criteria = [item["criterion"] for item in criteria_with_weights]
    uploaded_by = request.uploaded_by
    job_title_raw = request.job_title
    normalized_job_title = job_title_raw.strip().lower()  # ✅ Normalizing here

    engine = get_db_engine()

    # ✅ Use normalized job title for fetching JD
    with engine.connect() as conn:
        jd_row = conn.execute(text("""
            SELECT jd_text 
            FROM TempJobDescription 
            WHERE LOWER(job_title) = :job_title 
            ORDER BY created_at DESC 
            LIMIT 1
        """), {"job_title": normalized_job_title}).fetchone()

    if not jd_row:
        return JSONResponse(content={"error": "No job description found."}, status_code=400)

    jd_text = jd_row[0]
    results = []

    # ✅ Use latest session for this uploader
    with engine.connect() as conn:
        session_row = conn.execute(text("""
            SELECT upload_session_id 
            FROM TempResumes 
            WHERE uploaded_by = :uploaded_by
            ORDER BY created_at DESC 
            LIMIT 1
        """), {"uploaded_by": uploaded_by}).fetchone()

        if not session_row:
            return JSONResponse(content={"error": "No recent resumes found."}, status_code=400)

        latest_session_id = session_row[0]

        resumes = conn.execute(text("""
            SELECT filename, email, resume_content 
            FROM TempResumes 
            WHERE uploaded_by = :uploaded_by AND upload_session_id = :session_id
        """), {"uploaded_by": uploaded_by, "session_id": latest_session_id}).fetchall()

    if not resumes:
        return JSONResponse(content={"error": "No resumes found."}, status_code=400)

    for filename, email, resume_text in resumes:
        if not resume_text or not email:
            continue

        with engine.connect() as conn:
            recent_row = conn.execute(text("""
                SELECT created_at 
                FROM CV_Ranking_User_Email 
                WHERE email = :email AND LOWER(job_title) = :job_title
                ORDER BY created_at DESC
                LIMIT 1
            """), {"email": email, "job_title": normalized_job_title}).fetchone()

            if recent_row and recent_row[0]:
                last_uploaded = recent_row[0]
                if isinstance(last_uploaded, str):
                    last_uploaded = datetime.fromisoformat(last_uploaded)

                if isinstance(last_uploaded, datetime) and datetime.now() - last_uploaded <= timedelta(days=30):
                    results.append({
                        "filename": filename,
                        "email": email,
                        "status": "skipped",
                        "message": f"Resume for '{email}' and job title '{job_title_raw}' was already uploaded within the last month (on {last_uploaded.strftime('%Y-%m-%d')})."
                    })
                    continue
            else:
                # You could skip if no date is present as well to be safe
                evaluation_result = get_relevance_score(resume_text, jd_text, criteria)
                weighted_score, weight_map = calculate_weighted_score_manual(evaluation_result, criteria_with_weights)

                with engine.begin() as conn:
                    conn.execute(text("""
                        INSERT INTO CV_Ranking_User_Email (email, weighted_score, uploaded_by, job_title, created_at)
                        VALUES (:email, :weighted_score, :uploaded_by, :job_title, :created_at)
                    """), {
                        "email": email,
                        "weighted_score": weighted_score,
                        "uploaded_by": uploaded_by,
                        "job_title": normalized_job_title,
                        "created_at": datetime.now()
                    })

                # results.append({
                #     "filename": filename,
                #     "email": email,
                #     "weighted_score": weighted_score,
                #     "section_scores": {c: evaluation_result[c]["score"] for c in criteria},
                #     "job_title": job_title_raw,  # ✅ Display original input in response
                #     "evaluation": evaluation_result,
                #     "status": "processed"
                # })
                results.append({
                    "filename": filename,
                    "email": email,
                    "weighted_score": weighted_score,
                    "section_scores": {
                        c: {
                            "score": evaluation_result[c]["score"],
                            "comment": evaluation_result[c]["comment"]
                        }
                        for c in criteria
                    },
                    "job_title": job_title_raw,
                    "evaluation_summary": evaluation_result.get("summary_comment", ""),
                    "status": "processed"
                })

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






