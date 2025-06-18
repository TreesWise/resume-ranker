# from fastapi import FastAPI, File, UploadFile, Form, Body
# from fastapi.responses import HTMLResponse, JSONResponse
# from fastapi.middleware.cors import CORSMiddleware
# from typing import List
# from io import BytesIO
# import chardet
# import re
# from rank import get_relevance_score
# from extract import extract_text_from_pdf, extract_text_from_docx
# from sqlalchemy import create_engine, text
# # Temporary in-memory storage
# temp_resume_store = {}
# temp_jd_content = None
# temp_uploaded_by = None
# temp_job_title = None
# app = FastAPI()

# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=["*"],
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )


# @app.post("/upload-folder/")
# async def upload_folder(uploaded_by: str = Form(...), files: List[UploadFile] = File(...)):
#     global temp_resume_store, temp_uploaded_by
#     temp_resume_store.clear()
#     temp_uploaded_by = uploaded_by

#     for file in files:
#         content = await file.read()
#         temp_resume_store[file.filename] = content

#     return {"status": "success", "message": f"{len(temp_resume_store)} resumes uploaded temporarily.", "uploaded_by": uploaded_by}


# @app.post("/upload-jd/")
# async def upload_job_description(job_title: str = Form(...), jd_file: UploadFile = File(...)):
#     global temp_jd_content, temp_job_title
#     content = await jd_file.read()

#     try:
#         # Check if the uploaded JD file is a PDF or DOCX
#         if jd_file.filename.endswith(".docx"):
#             # Extract text from DOCX file
#             jd_text = extract_text_from_docx(BytesIO(content))
#         elif jd_file.filename.endswith(".pdf"):
#             # Extract text from PDF file
#             jd_text = extract_text_from_pdf(BytesIO(content))
#         else:
#             # Handle case for unsupported file types
#             return JSONResponse(content={"error": "Unsupported file type. Only .docx and .pdf are supported."}, status_code=400)

#         # Store the extracted job description content and job title temporarily
#         temp_jd_content = jd_text
#         temp_job_title = job_title
        
#         return {"status": "success", "message": "Job description uploaded temporarily.", "job_title": job_title}
#     except Exception as e:
#         return JSONResponse(content={"error": f"Failed to decode JD file: {str(e)}"}, status_code=400)

# #MSSQL engine using pyodbc
# def get_db_engine():
#     connection_string = (
#         "mssql+pyodbc://@10.201.1.86,50001/Resume_Parser"
#         "?driver=ODBC+Driver+17+for+SQL+Server"
#         "&trusted_connection=yes"
#     )
#     return create_engine(connection_string)


# def extract_email_regex(text):
#     match = re.search(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", text)
#     return match.group(0) if match else None

# @app.post("/rank-resumes-dynamic/")
# async def rank_uploaded_resumes_dynamic(criteria: List[str] = Body(...)):
#     global temp_jd_content, temp_uploaded_by, temp_job_title

#     if not temp_resume_store:
#         return JSONResponse(content={"error": "No resumes uploaded."}, status_code=400)

#     if not temp_jd_content:
#         return JSONResponse(content={"error": "No job description uploaded."}, status_code=400)

#     if not temp_job_title:
#         return JSONResponse(content={"error": "No job role provided."}, status_code=400)

#     jd_text = temp_jd_content
#     engine = get_db_engine()
#     results = []
#     duplicate_resumes = [] 

#     for filename, content in temp_resume_store.items():
#         if filename.endswith(".pdf"):
#             resume_text = extract_text_from_pdf(BytesIO(content))
#         elif filename.endswith(".docx"):
#             resume_text = extract_text_from_docx(BytesIO(content))
#         else:
#             continue

#         evaluation_result = get_relevance_score(resume_text, jd_text, criteria)

#         # Extract email (first try OpenAI result, fallback to regex)
#         # openai_emails = evaluation_result.get("emails", [])
#         # email = openai_emails[0] if openai_emails else extract_email_regex(resume_text)
#         email = extract_email_regex(resume_text)

#         if not email:
#             print(f"No email found in: {filename}")
#             continue

#         # Check if the email already exists for the same job title
#         with engine.connect() as conn:
#             query = text("SELECT COUNT(*) FROM CV_Ranking_User_Email WHERE email = :email AND job_title = :job_title")
#             result = conn.execute(query, {"email": email, "job_title": temp_job_title}).scalar()

#             if result > 0:
#                 # If the email already exists for the same job title, skip the insertion
#                 print(f"Email {email} already exists for job role {temp_job_title}, skipping.")
#                 duplicate_resumes.append(f"Resume for {email} already exists for job title {temp_job_title}")
#                 continue

#         # Calculate weighted score
#         score_sum = sum(evaluation_result.get(c, {}).get("score", 0) for c in criteria)
#         weighted_score = round(score_sum / len(criteria), 2) if criteria else 0
        

#         # Insert into database if email doesn't exist for this job title
#         with engine.begin() as conn:
#             insert_query = text("""
#                 INSERT INTO CV_Ranking_User_Email (email, weighted_score, uploaded_by, job_title)
#                 VALUES (:email, :weighted_score, :uploaded_by, :job_title)
#             """)
#             conn.execute(insert_query, {
#                 "email": email,
#                 "weighted_score": weighted_score,
#                 "uploaded_by": temp_uploaded_by or "Unknown",
#                 "job_title": temp_job_title
#             })
#             print(f"Inserted email: {email} with job role: {temp_job_title}")

#         individual_scores = [evaluation_result[c]["score"] for c in criteria]
#         weighted_score = round(sum(individual_scores) / len(criteria), 2)

#         results.append({
#             "filename": filename,
#             "email": email,
#             "weighted_score": weighted_score,
#             "section_scores": {c: evaluation_result[c]["score"] for c in criteria},
#             "job_title": temp_job_title,
#             "evaluation": evaluation_result
#         })

#     results.sort(key=lambda x: x["weighted_score"], reverse=True)
#     temp_resume_store.clear()
#     temp_jd_content = None
#     temp_job_title = None

#     return {"ranked_resumes": results}


# from fastapi import Query

# @app.get("/get-ranked-resumes/")
# async def get_ranked_resumes(job_title: str = Query(..., description="Job Title to filter resumes by")):
#     engine = get_db_engine()
#     with engine.connect() as conn:
#         query = text("""
#             SELECT id, email, created_at, weighted_score, uploaded_by, job_title
#             FROM CV_Ranking_User_Email
#             WHERE job_title = :job_title
#             ORDER BY weighted_score DESC
#         """)
#         result = conn.execute(query, {"job_title": job_title}).mappings().all()

#         # Format response nicely
#         response = []
#         for row in result:
#             response.append({
#                 "id": row["id"],
#                 "email": row["email"],
#                 "created_at": str(row["created_at"]),
#                 "weighted_score": row["weighted_score"],
#                 "uploaded_by": row["uploaded_by"],
#                 "job_title": row["job_title"]
#             })

#     return {"job_title": job_title, "ranked_resumes": response}

# @app.get("/get-user-by-email/")
# async def get_user_by_email(email: str = Query(..., description="Email address to fetch user records")):
#     engine = get_db_engine()
#     with engine.connect() as conn:
#         query = text("""
#             SELECT id, email, created_at, weighted_score, uploaded_by, job_title
#             FROM CV_Ranking_User_Email
#             WHERE email = :email
#             ORDER BY created_at DESC
#         """)
#         result = conn.execute(query, {"email": email}).mappings().all()

#         if not result:
#             return {"email": email, "records": [], "message": "No records found for this email."}

#         records = []
#         for row in result:
#             records.append({
#                 "id": row["id"],
#                 "email": row["email"],
#                 "created_at": str(row["created_at"]),
#                 "weighted_score": row["weighted_score"],
#                 "uploaded_by": row["uploaded_by"],
#                 "job_title": row["job_title"]
#             })

#     return {"email": email, "records": records}

# @app.get("/", response_class=HTMLResponse)
# def upload_form():
#     return """<!DOCTYPE html>
# <html>
# <head>
#     <title>Resume Ranker</title>
# </head>
# <body>
#     <h2>Upload Resume Folder</h2>
#     <form id="resumeUploadForm" action="/upload-folder/" enctype="multipart/form-data" method="post">
#         <label>Upload by (Your Name):</label><br>
#         <input type="text" name="uploaded_by" required><br><br>

#         <label>Select folder containing resumes (.pdf, .docx):</label><br>
#         <input type="file" name="files" webkitdirectory directory multiple accept=".pdf,.docx"><br><br>

#         <input type="submit" value="Upload Resumes">
#     </form>

#     <div id="resumeUploadResult"></div>

#     <h2>Upload Job Description & Role</h2>
#     <form id="jdUploadForm" action="/upload-jd/" enctype="multipart/form-data" method="post">
#         <label>Select Job Description (.pdf or .docx):</label><br>
#         <input type="file" name="jd_file" accept=".pdf,.docx" required><br><br>

#         <label>Job Role:</label><br>
#         <input type="text" name="job_title" required><br><br>

#         <input type="submit" value="Upload JD + Job Role">
#     </form>

#     <div id="jdUploadResult"></div>

#     <h2>Rank Resumes (Dynamic)</h2>
#     <form id="rankForm">
#         <label>Criterion 1:</label><br>
#         <input type="text" id="crit1" value=""><br><br>

#         <label>Criterion 2:</label><br>
#         <input type="text" id="crit2" value=""><br><br>

#         <label>Criterion 3:</label><br>
#         <input type="text" id="crit3" value=""><br><br>

#         <button type="button" onclick="submitRank()">Rank Resumes</button>
#     </form>

#     <h3>Results:</h3>
#     <pre id="resultBox"></pre>

#     <h2>Get Ranked Resumes</h2>
#     <form id="getRankedResumesForm">
#         <label>Job Title:</label><br>
#         <input type="text" id="jobTitleForRankedResumes" required><br><br>

#         <button type="button" onclick="getRankedResumes()">Get Ranked Resumes</button>
#     </form>

#     <h3>Ranked Resumes Result:</h3>
#     <pre id="rankedResumesResult"></pre>

#     <!-- New Section to Fetch User Data by Email -->
#     <h2>Get User Data by Email</h2>
#     <form id="getUserByEmailForm">
#         <label>Email:</label><br>
#         <input type="email" id="userEmailInput" required><br><br>
#         <button type="button" onclick="fetchUserData()">Fetch User Data</button>
#     </form>

#     <h3>User Records Result:</h3>
#     <pre id="userRecordsResult"></pre>

#     <script>
#         // Resume Upload
#         document.getElementById('resumeUploadForm').addEventListener('submit', async function (event) {
#             event.preventDefault();

#             const formData = new FormData(this);

#             const res = await fetch(this.action, {
#                 method: 'POST',
#                 body: formData
#             });

#             const result = await res.json();

#             document.getElementById('resumeUploadResult').innerHTML = 
#                 `<h3>Upload Result</h3>
#                 <p><strong>Uploaded by:</strong> ${result.uploaded_by || "Unknown"}</p>
#                 <p>${result.message}</p>`;
#         });

#         // JD Upload
#         document.getElementById('jdUploadForm').addEventListener('submit', async function (event) {
#             event.preventDefault();

#             const formData = new FormData(this);

#             const res = await fetch(this.action, {
#                 method: 'POST',
#                 body: formData
#             });

#             const result = await res.json();

#             document.getElementById('jdUploadResult').innerHTML = 
#                 `<h3>JD Upload Result</h3>
#                 <p><strong>Message:</strong> ${result.message || "Upload failed"}</p>
#                 <p><strong>Job Role:</strong> ${result.job_title || "Unknown"}</p>`;
#         });

#         // Rank Resumes
#         async function submitRank() {
#             const criteria = [];

#             const crit1 = document.getElementById("crit1").value.trim();
#             const crit2 = document.getElementById("crit2").value.trim();
#             const crit3 = document.getElementById("crit3").value.trim();

#             if (crit1) criteria.push(crit1);
#             if (crit2) criteria.push(crit2);
#             if (crit3) criteria.push(crit3);

#             if (criteria.length === 0) {
#                 document.getElementById("resultBox").textContent = "Please enter at least one criterion.";
#                 return;
#             }

#             const res = await fetch("/rank-resumes-dynamic/", {
#                 method: "POST",
#                 headers: {
#                     "Content-Type": "application/json"
#                 },
#                 body: JSON.stringify(criteria)
#             });

#             const result = await res.json();
#             document.getElementById("resultBox").textContent = JSON.stringify(result, null, 2);
#         }

#         // Get Ranked Resumes by Job Title
#         async function getRankedResumes() {
#             const jobTitle = document.getElementById("jobTitleForRankedResumes").value.trim();

#             if (!jobTitle) {
#                 document.getElementById("rankedResumesResult").textContent = "Please enter a job title.";
#                 return;
#             }

#             const res = await fetch(`/get-ranked-resumes/?job_title=${jobTitle}`);
#             const result = await res.json();

#             document.getElementById("rankedResumesResult").textContent = JSON.stringify(result, null, 2);
#         }

#         // Fetch User Data by Email
#         async function fetchUserData() {
#             const email = document.getElementById("userEmailInput").value.trim();

#             if (!email) {
#                 document.getElementById("userRecordsResult").textContent = "Please enter a valid email.";
#                 return;
#             }

#             const res = await fetch(`/get-user-by-email/?email=${email}`);
#             const result = await res.json();

#             if (result.records && result.records.length > 0) {
#                 document.getElementById("userRecordsResult").textContent = JSON.stringify(result, null, 2);
#             } else {
#                 document.getElementById("userRecordsResult").textContent = "No records found for this email.";
#             }
#         }
#     </script>
# </body>
# </html>

# """



# from fastapi import FastAPI, File, UploadFile, Form
# from fastapi.responses import HTMLResponse, JSONResponse
# from fastapi.middleware.cors import CORSMiddleware
# from typing import List
# from io import BytesIO
# import re
# from rank import get_relevance_score
# from extract import extract_text_from_pdf, extract_text_from_docx
# from sqlalchemy import create_engine, text
# from datetime import datetime
# import uuid
# from pydantic import BaseModel

# app = FastAPI()

# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=["*"],
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )

# def get_db_engine():
#     connection_string = (
#         "mssql+pyodbc://@10.201.1.86,50001/Resume_Parser"
#         "?driver=ODBC+Driver+17+for+SQL+Server"
#         "&trusted_connection=yes"
#     )
#     return create_engine(connection_string)

# def extract_email_regex(text):
#     match = re.search(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", text)
#     return match.group(0) if match else None

# @app.post("/upload-folder/")
# async def upload_folder(uploaded_by: str = Form(...), files: List[UploadFile] = File(...)):
#     session_id = str(uuid.uuid4())
#     engine = get_db_engine()
#     with engine.begin() as conn:
#         for file in files:
#             content = await file.read()
#             resume_text = (
#                 extract_text_from_pdf(BytesIO(content)) if file.filename.endswith(".pdf")
#                 else extract_text_from_docx(BytesIO(content)) if file.filename.endswith(".docx")
#                 else None
#             )
#             if not resume_text:
#                 continue
#             email = extract_email_regex(resume_text) or "unknown@example.com"
#             conn.execute(text("""
#                 INSERT INTO TempResumes (filename, email, resume_content, uploaded_by, upload_session_id, created_at)
#                 VALUES (:filename, :email, :resume_content, :uploaded_by, :upload_session_id, GETDATE())
#             """), {
#                 "filename": file.filename,
#                 "email": email,
#                 "resume_content": resume_text,
#                 "uploaded_by": uploaded_by,
#                 "upload_session_id": session_id
#             })

#     return {"status": "success", "message": f"{len(files)} resumes uploaded.", "uploaded_by": uploaded_by}

# @app.post("/upload-jd/")
# async def upload_job_description(
#     uploaded_by: str = Form(...),
#     job_title: str = Form(...),
#     jd_file: UploadFile = File(...)
# ):
#     content = await jd_file.read()
#     engine = get_db_engine()
#     session_id = str(uuid.uuid4())
#     jd_text = (
#         extract_text_from_docx(BytesIO(content)) if jd_file.filename.endswith(".docx")
#         else extract_text_from_pdf(BytesIO(content)) if jd_file.filename.endswith(".pdf")
#         else None
#     )
#     if not jd_text:
#         return JSONResponse(content={"error": "Unsupported file type"}, status_code=400)

#     with engine.begin() as conn:
#         conn.execute(text("""
#             INSERT INTO TempJobDescription (uploaded_by, job_title, jd_text, upload_session_id, created_at)
#             VALUES (:uploaded_by, :job_title, :jd_text, :upload_session_id, GETDATE())
#         """), {
#             "uploaded_by": uploaded_by,
#             "job_title": job_title,
#             "jd_text": jd_text,
#             "upload_session_id": session_id
#         })

#     return {
#         "status": "success",
#         "message": "Job description uploaded.",
#         "uploaded_by": uploaded_by,
#         "job_title": job_title
#     }

# class RankRequest(BaseModel):
#     criteria: List[str]
#     uploaded_by: str
#     job_title: str

# @app.post("/rank-resumes-dynamic/")
# async def rank_uploaded_resumes_dynamic(request: RankRequest):
#     criteria = request.criteria
#     uploaded_by = request.uploaded_by
#     job_title = request.job_title

#     engine = get_db_engine()

#     # Fetch latest JD for this uploaded_by and job_title
#     with engine.connect() as conn:
#         jd_row = conn.execute(text("""
#             SELECT TOP 1 jd_text 
#             FROM TempJobDescription 
#             WHERE uploaded_by = :uploaded_by AND job_title = :job_title 
#             ORDER BY created_at DESC
#         """), {
#             "uploaded_by": uploaded_by,
#             "job_title": job_title
#         }).fetchone()

#     if not jd_row:
#         return JSONResponse(content={"error": "No job description found."}, status_code=400)

#     jd_text = jd_row[0]
#     results = []

#     # Fetch resumes
#     with engine.connect() as conn:
#         resumes = conn.execute(text("""
#             SELECT filename, email, resume_content 
#             FROM TempResumes 
#             WHERE uploaded_by = :uploaded_by
#         """), {"uploaded_by": uploaded_by}).fetchall()

#     if not resumes:
#         return JSONResponse(content={"error": "No resumes found."}, status_code=400)

#     for filename, email, resume_text in resumes:
#         if not resume_text or not email:
#             continue

#         with engine.connect() as conn:
#             exists = conn.execute(text("""
#                 SELECT COUNT(*) FROM CV_Ranking_User_Email 
#                 WHERE email = :email AND job_title = :job_title
#             """), {"email": email, "job_title": job_title}).scalar()
#         if exists > 0:
#             continue

#         evaluation_result = get_relevance_score(resume_text, jd_text, criteria)
#         weighted_score = round(sum(evaluation_result[c]["score"] for c in criteria) / len(criteria), 2)

#         with engine.begin() as conn:
#             conn.execute(text("""
#                 INSERT INTO CV_Ranking_User_Email (email, weighted_score, uploaded_by, job_title)
#                 VALUES (:email, :weighted_score, :uploaded_by, :job_title)
#             """), {
#                 "email": email,
#                 "weighted_score": weighted_score,
#                 "uploaded_by": uploaded_by,
#                 "job_title": job_title
#             })

#         results.append({
#             "filename": filename,
#             "email": email,
#             "weighted_score": weighted_score,
#             "section_scores": {c: evaluation_result[c]["score"] for c in criteria},
#             "job_title": job_title,
#             "evaluation": evaluation_result
#         })

#     results.sort(key=lambda x: x["weighted_score"], reverse=True)
#     return {"ranked_resumes": results}

# @app.get("/", response_class=HTMLResponse)
# def upload_form():
#     return """
#     <!DOCTYPE html>
#     <html>
#     <head><title>Resume Ranker</title></head>
#     <body>
#     <h2>Upload Resume Folder</h2>
#     <form id="resumeUploadForm" action="/upload-folder/" enctype="multipart/form-data" method="post">
#         <label>Upload by (Your Name):</label><br>
#         <input type="text" name="uploaded_by" id="uploaded_by_input" required><br><br>
#         <label>Select folder containing resumes (.pdf, .docx):</label><br>
#         <input type="file" name="files" webkitdirectory directory multiple accept=".pdf,.docx"><br><br>
#         <input type="submit" value="Upload Resumes">
#     </form>
#     <div id="resumeUploadResult"></div>

#     <h2>Upload Job Description & Role</h2>
#     <form id="jdUploadForm" action="/upload-jd/" enctype="multipart/form-data" method="post">
#         <label>Select Job Description (.pdf or .docx):</label><br>
#         <input type="file" name="jd_file" accept=".pdf,.docx" required><br><br>
#         <label>Job Role:</label><br>
#         <input type="text" name="job_title" id="job_title_input" required><br><br>
#         <label>Uploaded by (must match resume uploader):</label><br>
#         <input type="text" name="uploaded_by" id="uploaded_by_jd" required><br><br>
#         <input type="submit" value="Upload JD + Job Role">
#     </form>
#     <div id="jdUploadResult"></div>

#     <h2>Rank Resumes (Dynamic)</h2>
#     <form id="rankForm">
#         <input type="hidden" id="rank_uploaded_by">
#         <input type="hidden" id="rank_job_title">

#         <label>Criterion 1:</label><br>
#         <input type="text" id="crit1"><br><br>
#         <label>Criterion 2:</label><br>
#         <input type="text" id="crit2"><br><br>
#         <label>Criterion 3:</label><br>
#         <input type="text" id="crit3"><br><br>
#         <button type="button" onclick="submitRank()">Rank Resumes</button>
#     </form>
#     <h3>Results:</h3>
#     <pre id="resultBox"></pre>

#     <script>
#         document.getElementById('resumeUploadForm').addEventListener('submit', async function (e) {
#             e.preventDefault();
#             const formData = new FormData(this);
#             const uploadedBy = document.getElementById("uploaded_by_input").value.trim();
#             const res = await fetch(this.action, { method: 'POST', body: formData });
#             const result = await res.json();
#             document.getElementById('resumeUploadResult').textContent = JSON.stringify(result, null, 2);
#             if (uploadedBy) document.getElementById("rank_uploaded_by").value = uploadedBy;
#         });

#         document.getElementById('jdUploadForm').addEventListener('submit', async function (e) {
#             e.preventDefault();
#             const formData = new FormData(this);
#             const uploadedBy = document.getElementById("uploaded_by_jd").value.trim();
#             const jobTitle = document.getElementById("job_title_input").value.trim();
#             const res = await fetch(this.action, { method: 'POST', body: formData });
#             const result = await res.json();
#             document.getElementById('jdUploadResult').textContent = JSON.stringify(result, null, 2);
#             if (uploadedBy) document.getElementById("rank_uploaded_by").value = uploadedBy;
#             if (jobTitle) document.getElementById("rank_job_title").value = jobTitle;
#         });

#         async function submitRank() {
#             const criteria = [];
#             const crit1 = document.getElementById("crit1").value.trim();
#             const crit2 = document.getElementById("crit2").value.trim();
#             const crit3 = document.getElementById("crit3").value.trim();
#             if (crit1) criteria.push(crit1);
#             if (crit2) criteria.push(crit2);
#             if (crit3) criteria.push(crit3);

#             const uploadedBy = document.getElementById("rank_uploaded_by").value.trim();
#             const jobTitle = document.getElementById("rank_job_title").value.trim();

#             if (!uploadedBy || !jobTitle || criteria.length === 0) {
#                 document.getElementById("resultBox").textContent = "All fields are required.";
#                 return;
#             }

#             const payload = {
#                 criteria: criteria,
#                 uploaded_by: uploadedBy,
#                 job_title: jobTitle
#             };

#             try {
#                 const res = await fetch("/rank-resumes-dynamic/", {
#                     method: "POST",
#                     headers: { "Content-Type": "application/json" },
#                     body: JSON.stringify(payload)
#                 });

#                 const result = await res.json();
#                 document.getElementById("resultBox").textContent = JSON.stringify(result, null, 2);
#             } catch (err) {
#                 document.getElementById("resultBox").textContent = "Error calling API: " + err.message;
#             }
#         }

#     </script>
#     </body>
#     </html>
#     """




from fastapi import FastAPI, File, UploadFile, Form, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import List
from io import BytesIO
from pydantic import BaseModel
from sqlalchemy import create_engine, text
from datetime import datetime
import uuid
import re

from extract import extract_text_from_pdf, extract_text_from_docx
from rank import get_relevance_score

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
        for file in files:
            content = await file.read()
            resume_text = (
                extract_text_from_pdf(BytesIO(content)) if file.filename.endswith(".pdf")
                else extract_text_from_docx(BytesIO(content)) if file.filename.endswith(".docx")
                else None
            )
            if not resume_text:
                continue
            email = extract_email_regex(resume_text) or "unknown@example.com"
            conn.execute(text("""
                INSERT INTO TempResumes (filename, email, resume_content, uploaded_by, upload_session_id, created_at)
                VALUES (:filename, :email, :resume_content, :uploaded_by, :upload_session_id, :created_at)
            """), {
                "filename": file.filename,
                "email": email,
                "resume_content": resume_text,
                "uploaded_by": uploaded_by,
                "upload_session_id": session_id,
                "created_at": datetime.now()
            })
    return {"status": "success", "message": f"{len(files)} resumes uploaded.", "uploaded_by": uploaded_by}

@app.post("/upload-jd/")
async def upload_job_description(job_title: str = Form(...), jd_file: UploadFile = File(...)):
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

    uploaded_by = "system"  # Or hardcode a default if needed

    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO TempJobDescription (uploaded_by, job_title, jd_text, upload_session_id, created_at)
            VALUES (:uploaded_by, :job_title, :jd_text, :upload_session_id, :created_at)
        """), {
            "uploaded_by": uploaded_by,
            "job_title": job_title,
            "jd_text": jd_text,
            "upload_session_id": session_id,
            "created_at": datetime.now()
        })
    return {"status": "success", "message": "Job description uploaded.", "uploaded_by": uploaded_by, "job_title": job_title}


class RankRequest(BaseModel):
    criteria: List[str]
    uploaded_by: str
    job_title: str

@app.post("/rank-resumes-dynamic/")
async def rank_uploaded_resumes_dynamic(request: RankRequest):
    criteria = request.criteria
    uploaded_by = request.uploaded_by
    job_title = request.job_title
    engine = get_db_engine()

    with engine.connect() as conn:
        jd_row = conn.execute(text("""
        SELECT jd_text 
        FROM TempJobDescription 
        WHERE job_title = :job_title 
        ORDER BY created_at DESC 
        LIMIT 1
    """), {"job_title": job_title}).fetchone()


    if not jd_row:
        return JSONResponse(content={"error": "No job description found."}, status_code=400)

    jd_text = jd_row[0]
    results = []

    with engine.connect() as conn:
        resumes = conn.execute(text("""
            SELECT filename, email, resume_content 
            FROM TempResumes 
            WHERE uploaded_by = :uploaded_by
        """), {"uploaded_by": uploaded_by}).fetchall()

    if not resumes:
        return JSONResponse(content={"error": "No resumes found."}, status_code=400)

    for filename, email, resume_text in resumes:
        if not resume_text or not email:
            continue

        with engine.connect() as conn:
            exists = conn.execute(text("""
                SELECT COUNT(*) 
                FROM CV_Ranking_User_Email 
                WHERE email = :email AND job_title = :job_title
            """), {"email": email, "job_title": job_title}).scalar()
        if exists > 0:
            continue

        evaluation_result = get_relevance_score(resume_text, jd_text, criteria)
        weighted_score = round(sum(evaluation_result[c]["score"] for c in criteria) / len(criteria), 2)

        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO CV_Ranking_User_Email (email, weighted_score, uploaded_by, job_title)
                VALUES (:email, :weighted_score, :uploaded_by, :job_title)
            """), {
                "email": email,
                "weighted_score": weighted_score,
                "uploaded_by": uploaded_by,
                "job_title": job_title
            })

        results.append({
            "filename": filename,
            "email": email,
            "weighted_score": weighted_score,
            "section_scores": {c: evaluation_result[c]["score"] for c in criteria},
            "job_title": job_title,
            "evaluation": evaluation_result
        })

    results.sort(key=lambda x: x["weighted_score"], reverse=True)
    return {"ranked_resumes": results}

@app.get("/get-ranked-resumes/")
async def get_ranked_resumes(job_title: str = Query(..., description="Job Title to filter resumes by")):
    engine = get_db_engine()
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT id, email, created_at, weighted_score, uploaded_by, job_title
            FROM CV_Ranking_User_Email
            WHERE job_title = :job_title
            ORDER BY weighted_score DESC
        """), {"job_title": job_title}).mappings().all()

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

@app.get("/get-user-by-email/")
async def get_user_by_email(email: str = Query(..., description="Email address to fetch user records")):
    engine = get_db_engine()
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT id, email, created_at, weighted_score, uploaded_by, job_title
            FROM CV_Ranking_User_Email
            WHERE email = :email
            ORDER BY created_at DESC
        """), {"email": email}).mappings().all()

        if not result:
            return {"email": email, "records": [], "message": "No records found for this email."}

        records = []
        for row in result:
            records.append({
                "id": row["id"],
                "email": row["email"],
                "created_at": str(row["created_at"]),
                "weighted_score": row["weighted_score"],
                "uploaded_by": row["uploaded_by"],
                "job_title": row["job_title"]
            })

    return {"email": email, "records": records}

@app.get("/", response_class=HTMLResponse)
def upload_form():
    return """
    <!DOCTYPE html>
    <html>
    <head><title>Resume Ranker</title></head>
    <body>
    <h2>Upload Resume Folder</h2>
    <form id="resumeUploadForm" action="/upload-folder/" enctype="multipart/form-data" method="post">
        <label>Upload by (Your Name):</label><br>
        <input type="text" name="uploaded_by" id="uploaded_by_input" required><br><br>
        <label>Select folder containing resumes (.pdf, .docx):</label><br>
        <input type="file" name="files" webkitdirectory directory multiple accept=".pdf,.docx"><br><br>
        <input type="submit" value="Upload Resumes">
    </form>
    <div id="resumeUploadResult"></div>

    <h2>Upload Job Description & Role</h2>
    <form id="jdUploadForm" action="/upload-jd/" enctype="multipart/form-data" method="post">
        <label>Select Job Description (.pdf or .docx):</label><br>
        <input type="file" name="jd_file" accept=".pdf,.docx" required><br><br>
        <label>Job Role:</label><br>
        <input type="text" name="job_title" id="job_title_input" required><br><br>
        <input type="submit" value="Upload JD + Job Role">
    </form>



    <div id="jdUploadResult"></div>

    <h2>Rank Resumes (Dynamic)</h2>
    <form id="rankForm">
        <input type="hidden" id="rank_uploaded_by">
        <input type="hidden" id="rank_job_title">
        <label>Criterion 1:</label><br>
        <input type="text" id="crit1"><br><br>
        <label>Criterion 2:</label><br>
        <input type="text" id="crit2"><br><br>
        <label>Criterion 3:</label><br>
        <input type="text" id="crit3"><br><br>
        <button type="button" onclick="submitRank()">Rank Resumes</button>
    </form>
    <h3>Results:</h3>
    <pre id="resultBox"></pre>

    <!--New Section: Get Ranked Resumes -->
    <h2>Get Ranked Resumes</h2>
    <form id="getRankedResumesForm">
        <label>Job Title:</label><br>
        <input type="text" id="jobTitleForRankedResumes" required><br><br>
        <button type="button" onclick="getRankedResumes()">Get Ranked Resumes</button>
    </form>
    <h3>Ranked Resumes Result:</h3>
    <pre id="rankedResumesResult"></pre>

    <!--New Section: Get User Data by Email -->
    <h2>Get User Data by Email</h2>
    <form id="getUserByEmailForm">
        <label>Email:</label><br>
        <input type="email" id="userEmailInput" required><br><br>
        <button type="button" onclick="fetchUserData()">Fetch User Data</button>
    </form>
    <h3>User Records Result:</h3>
    <pre id="userRecordsResult"></pre>

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
            const res = await fetch(this.action, { method: 'POST', body: formData });
            const result = await res.json();
            document.getElementById('jdUploadResult').textContent = JSON.stringify(result, null, 2);
            if (jobTitle) document.getElementById("rank_job_title").value = jobTitle;
        });


        async function submitRank() {
            const criteria = [];
            const crit1 = document.getElementById("crit1").value.trim();
            const crit2 = document.getElementById("crit2").value.trim();
            const crit3 = document.getElementById("crit3").value.trim();
            if (crit1) criteria.push(crit1);
            if (crit2) criteria.push(crit2);
            if (crit3) criteria.push(crit3);

            const uploadedBy = document.getElementById("rank_uploaded_by").value.trim();
            const jobTitle = document.getElementById("rank_job_title").value.trim();

            if (!uploadedBy || !jobTitle || criteria.length === 0) {
                document.getElementById("resultBox").textContent = "All fields are required.";
                return;
            }

            const payload = {
                criteria: criteria,
                uploaded_by: uploadedBy,
                job_title: jobTitle
            };

            try {
                const res = await fetch("/rank-resumes-dynamic/", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(payload)
                });

                const result = await res.json();
                document.getElementById("resultBox").textContent = JSON.stringify(result, null, 2);
            } catch (err) {
                document.getElementById("resultBox").textContent = "Error calling API: " + err.message;
            }
        }

        async function getRankedResumes() {
            const jobTitle = document.getElementById("jobTitleForRankedResumes").value.trim();
            if (!jobTitle) {
                document.getElementById("rankedResumesResult").textContent = "Please enter a job title.";
                return;
            }
            const res = await fetch(`/get-ranked-resumes/?job_title=${encodeURIComponent(jobTitle)}`);
            const result = await res.json();
            document.getElementById("rankedResumesResult").textContent = JSON.stringify(result, null, 2);
        }

        async function fetchUserData() {
            const email = document.getElementById("userEmailInput").value.trim();
            if (!email) {
                document.getElementById("userRecordsResult").textContent = "Please enter a valid email.";
                return;
            }
            const res = await fetch(`/get-user-by-email/?email=${encodeURIComponent(email)}`);
            const result = await res.json();
            document.getElementById("userRecordsResult").textContent = JSON.stringify(result, null, 2);
        }
    </script>
    </body>
    </html>
    """
