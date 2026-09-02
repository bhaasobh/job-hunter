"""Local web interface for searching and filtering job results."""

import asyncio
import html
import io
import json
import os
import re
import threading
import uuid
import smtplib
from email.message import EmailMessage
from datetime import datetime, timedelta, timezone

from flask import Flask, jsonify, render_template, request
import httpx
from pypdf import PdfReader
from docx import Document

from job_hunter_lib.config import OLLAMA_MODEL, OLLAMA_URL, SUPPORTED_COMPANIES, TELEGRAM_BOT_TOKEN
from job_hunter_lib.jobs import auto_detect_company_ats, extract_cv_keywords, fetch_jobs, test_company_fetcher
from job_hunter_lib.local_database import (
    add_custom_company,
    delete_custom_company,
    get_all_jobs,
    get_custom_companies,
    get_unsent_new_jobs,
    mark_jobs_sent_to_telegram,
    save_job_ai_analysis,
    save_search_results,
    update_job_status,
)
from job_hunter_lib.ollama_matcher import analysis_summary, analyze_job_with_ollama
from job_hunter_lib.utils import generate_job_id


app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024
search_tasks = {}
search_tasks_lock = threading.Lock()
cv_profiles = {}
cv_profiles_lock = threading.Lock()
service_lock = threading.Lock()
service_stop_event = threading.Event()
service_thread = None
service_state = {
    "running": False,
    "phase": "stopped",
    "recipient": "",
    "last_run": None,
    "next_run": None,
    "last_result": None,
    "error": "",
}
SERVICE_INTERVAL_SECONDS = 3600


@app.get("/")
def index():
    return render_template("index.html", supported_companies=SUPPORTED_COMPANIES)


def _uploaded_cv_text(upload) -> str:
    filename = str(upload.filename or "").lower()
    raw = upload.read()
    if filename.endswith(".pdf"):
        return "\n".join((page.extract_text() or "") for page in PdfReader(io.BytesIO(raw)).pages).strip()
    if filename.endswith(".docx"):
        document = Document(io.BytesIO(raw))
        return "\n".join(paragraph.text for paragraph in document.paragraphs).strip()
    if filename.endswith(".txt"):
        return raw.decode("utf-8", errors="replace").strip()
    raise ValueError("Upload a PDF, DOCX, or TXT file.")


@app.post("/api/cv/analyze")
def analyze_cv():
    upload = request.files.get("cv")
    if upload is None or not upload.filename:
        return jsonify({"error": "Choose a CV file first."}), 400
    try:
        cv_text = _uploaded_cv_text(upload)
    except Exception as exc:
        return jsonify({"error": f"Could not read this CV: {exc}"}), 400
    if len(cv_text) < 100:
        return jsonify({"error": "The CV contains too little readable text."}), 400

    keywords = extract_cv_keywords(cv_text)
    known_locations = []
    try:
        known_locations = json.loads(request.form.get("known_locations", "[]"))
    except json.JSONDecodeError:
        pass
    cv_lower = cv_text.lower()
    matched_locations = []
    for location in known_locations:
        location = str(location).strip()
        specific_parts = [
            part.strip().lower()
            for part in re.split(r"[,;|]", location)
            if len(part.strip()) > 3 and part.strip().lower() not in {"israel", "remote"}
        ]
        if specific_parts and any(part in cv_lower for part in specific_parts):
            matched_locations.append(location)
    years = [int(value) for value in re.findall(r"\b(\d{1,2})\+?\s+years?\b", cv_lower)]
    max_years = max(years, default=0)
    junior_profile = max_years < 4 or any(term in cv_lower for term in ("student", "graduate", "junior"))
    excluded_keywords = ["unpaid", "internship"]
    if junior_profile:
        excluded_keywords += [
            "senior", "manager", "staff", "lead", "principal", "head",
            "director", "vp", "vice", "chief", "architect",
        ]

    cv_id = uuid.uuid4().hex
    with cv_profiles_lock:
        cv_profiles[cv_id] = cv_text
    return jsonify({
        "cv_id": cv_id,
        "filename": upload.filename,
        "keywords": keywords,
        "locations": matched_locations,
        "job_types": ["Full-time", "Contract"],
        "excluded_keywords": excluded_keywords,
        "experience_years": max_years,
        "profile": "Early career" if junior_profile else "Experienced",
    })


@app.post("/api/search")
def search_jobs():
    return _perform_search(criteria=request.get_json(silent=True) or {})


def _perform_search(progress_callback=None, criteria=None):
    criteria = criteria or {}
    use_ai_analysis = criteria.get("use_ai_analysis", True) is not False
    companies = [str(value).strip().lower() for value in criteria.get("companies", []) if str(value).strip()]
    locations = [str(value).strip().lower() for value in criteria.get("locations", []) if str(value).strip()]
    job_types = [str(value).strip().lower() for value in criteria.get("job_types", []) if str(value).strip()]
    excluded_keywords = [
        str(value).strip().lower()
        for value in criteria.get("excluded_keywords", [])
        if str(value).strip()
    ]
    cv_id = str(criteria.get("cv_id") or "").strip()
    with cv_profiles_lock:
        cv_text = cv_profiles.get(cv_id, "")
    existing_jobs = {str(job.get("job_id")): job for job in get_all_jobs()}
    run_seen_ids = set()
    unique_jobs = {}

    def on_batch_found(source_name, raw_batch):
        batch_valid = []
        for job in raw_batch:
            company = str(job.get("company", "")).lower()
            location = str(job.get("location", "")).lower()
            job_type = str(job.get("job_type", "")).lower()
            job_text = " ".join(str(job.get(field, "")) for field in ("title", "description", "tags")).lower()
            if companies and not any(term in company for term in companies):
                continue
            if locations and not any(term in location for term in locations):
                continue
            if job_types and not any(term in job_type for term in job_types):
                continue
            if excluded_keywords and any(term in job_text for term in excluded_keywords):
                continue
            job_id = str(job.get("job_id") or generate_job_id(job))
            job["job_id"] = job_id
            unique_jobs[job_id] = job
            batch_valid.append(job)

        if batch_valid:
            save_search_results(batch_valid, run_seen_ids=run_seen_ids)

    try:
        jobs = asyncio.run(fetch_jobs(
            notify=False,
            progress_callback=progress_callback,
            companies=companies,
            excluded_keywords=excluded_keywords,
            on_jobs_found=on_batch_found,
        ))
    except Exception as exc:
        app.logger.exception("Job search failed")
        return jsonify({"error": f"Search failed: {exc}"}), 500

    # Remove duplicates returned by overlapping feeds and apply search criteria
    # before saving the results to the local database.
    available_locations = sorted({
        str(job.get("location", "")).strip()
        for job in jobs
        if str(job.get("location", "")).strip()
        and str(job.get("location", "")).strip().lower() not in {"not specified", "n/a"}
    }, key=str.casefold)
    available_job_types = sorted({
        str(job.get("job_type", "")).strip()
        for job in jobs
        if str(job.get("job_type", "")).strip()
        and str(job.get("job_type", "")).strip().lower() not in {"not specified", "n/a"}
    }, key=str.casefold)
    for job in jobs:
        company = str(job.get("company", "")).lower()
        location = str(job.get("location", "")).lower()
        job_type = str(job.get("job_type", "")).lower()
        job_text = " ".join(str(job.get(field, "")) for field in ("title", "description", "tags")).lower()
        if companies and not any(term in company for term in companies):
            continue
        if locations and not any(term in location for term in locations):
            continue
        if job_types and not any(term in job_type for term in job_types):
            continue
        if excluded_keywords and any(term in job_text for term in excluded_keywords):
            continue
        job_id = str(job.get("job_id") or generate_job_id(job))
        job["job_id"] = job_id
        unique_jobs[job_id] = job

    new_jobs = []
    for job in unique_jobs.values():
        job_id = str(job.get("job_id") or generate_job_id(job))
        job["job_id"] = job_id
        existing = existing_jobs.get(job_id)
        if existing is None or (existing.get("status") == "new" and not existing.get("ai_analyzed")):
            new_jobs.append(job)

    ai_scored_count = 0
    ai_cached_count = 0
    ai_errors = []
    if cv_text and use_ai_analysis:
        for index, job in enumerate(new_jobs, start=1):
            if progress_callback:
                progress_callback(
                    index - 1,
                    max(1, len(new_jobs)),
                    f"AI scoring new job {index} of {len(new_jobs)}: {job.get('title', 'job')}",
                )
            try:
                analysis, cached = analyze_job_with_ollama(cv_text, job)
                job["match_score"] = analysis["score"]
                job["match_reason"] = analysis_summary(analysis)
                job["ai_analysis"] = analysis
                job["score_source"] = f"Ollama:{OLLAMA_MODEL}"
                job["ai_analyzed"] = True
                ai_scored_count += 1
                ai_cached_count += int(cached)
            except Exception as exc:
                app.logger.exception("Automatic AI analysis failed for %s", job.get("title"))
                ai_errors.append(str(exc))
            if progress_callback:
                progress_callback(
                    index,
                    max(1, len(new_jobs)),
                    f"AI scored {index} of {len(new_jobs)} new jobs",
                )

    results = save_search_results(list(unique_jobs.values()), run_seen_ids=run_seen_ids)
    results.sort(key=lambda job: (
        str(job.get("company", "")).lower(),
        str(job.get("title", "")).lower(),
    ))
    return jsonify({
        "jobs": results,
        "count": len(results),
        "available_locations": available_locations,
        "available_job_types": available_job_types,
        "ai_model": OLLAMA_MODEL,
        "new_job_count": len(new_jobs),
        "ai_scored_count": ai_scored_count,
        "ai_cached_count": ai_cached_count,
        "ai_error_count": len(ai_errors),
        "ai_error": ai_errors[0] if ai_errors else "",
        "ai_skipped_no_cv": bool(new_jobs and use_ai_analysis and not cv_text),
        "ai_disabled": bool(new_jobs and not use_ai_analysis),
    })


@app.post("/api/jobs/<job_id>/analyze")
def analyze_job(job_id):
    data = request.get_json(silent=True) or {}
    cv_id = str(data.get("cv_id") or "").strip()
    with cv_profiles_lock:
        cv_text = cv_profiles.get(cv_id, "")
    if not cv_text:
        return jsonify({"error": "Upload your CV again before running AI analysis."}), 400

    job = next((item for item in get_all_jobs() if str(item.get("job_id")) == job_id), None)
    if job is None:
        return jsonify({"error": "Job not found. Run a new search and try again."}), 404
    if job.get("ai_analyzed") and job.get("ai_analysis"):
        return jsonify({
            "analysis": job["ai_analysis"],
            "cached": True,
            "match_score": job.get("match_score"),
            "match_reason": job.get("match_reason", ""),
            "score_source": job.get("score_source", f"Ollama:{OLLAMA_MODEL}"),
            "model": OLLAMA_MODEL,
        })
    try:
        analysis, cached = analyze_job_with_ollama(cv_text, job)
    except Exception as exc:
        app.logger.exception("Ollama job analysis failed")
        return jsonify({"error": f"AI analysis failed: {exc}"}), 502
    match_reason = analysis_summary(analysis)
    score_source = f"Ollama:{OLLAMA_MODEL}"
    save_job_ai_analysis(job_id, analysis, match_reason, score_source)
    return jsonify({
        "analysis": analysis,
        "cached": cached,
        "match_score": analysis["score"],
        "match_reason": match_reason,
        "score_source": score_source,
        "model": OLLAMA_MODEL,
    })


@app.get("/api/ai/status")
def ai_status():
    tags_url = OLLAMA_URL.split("/api/", 1)[0].rstrip("/") + "/api/tags"
    try:
        response = httpx.get(tags_url, timeout=5)
        response.raise_for_status()
        models = [str(item.get("name") or "") for item in response.json().get("models", [])]
    except Exception as exc:
        return jsonify({"ready": False, "model": OLLAMA_MODEL, "error": str(exc)}), 503
    ready = OLLAMA_MODEL in models or OLLAMA_MODEL.removesuffix(":latest") in models
    return jsonify({
        "ready": ready,
        "model": OLLAMA_MODEL,
        "message": "Ollama is ready." if ready else f"Model {OLLAMA_MODEL} is not installed.",
    }), 200 if ready else 503


def _run_search_task(task_id, criteria):
    def update(completed, total, source):
        with search_tasks_lock:
            search_tasks[task_id].update(
                progress=round(completed / total * 100),
                completed_sources=completed,
                total_sources=total,
                current_source=source,
            )

    with app.app_context():
        response = _perform_search(update, criteria)
        if isinstance(response, tuple):
            flask_response, status_code = response
        else:
            flask_response, status_code = response, response.status_code
        data = flask_response.get_json()
        with search_tasks_lock:
            if status_code >= 400:
                search_tasks[task_id].update(state="error", error=data.get("error", "Search failed"))
            else:
                search_tasks[task_id].update(state="complete", progress=100, result=data)


@app.post("/api/search/start")
def start_search():
    criteria = request.get_json(silent=True) or {}
    task_id = uuid.uuid4().hex
    with search_tasks_lock:
        search_tasks[task_id] = {
            "state": "running", "progress": 0, "completed_sources": 0,
            "total_sources": 0, "current_source": "Starting search…",
        }
    threading.Thread(target=_run_search_task, args=(task_id, criteria), daemon=True).start()
    return jsonify({"task_id": task_id}), 202


@app.get("/api/search/status/<task_id>")
def search_status(task_id):
    with search_tasks_lock:
        task = search_tasks.get(task_id)
        if task is None:
            return jsonify({"error": "Search task not found"}), 404
        return jsonify(dict(task))


@app.get("/api/jobs")
def saved_jobs():
    jobs = get_all_jobs()
    return jsonify({"jobs": jobs, "count": len(jobs)})


def _new_jobs_html(jobs: list[dict]) -> str:
    rows = []
    for job in jobs:
        title = html.escape(str(job.get("title") or "Untitled job"))
        company = html.escape(str(job.get("company") or "Unknown company"))
        location = html.escape(str(job.get("location") or "Not specified"))
        posted = html.escape(str(job.get("posted") or "Not specified"))
        url = html.escape(str(job.get("url") or "#"), quote=True)
        rows.append(
            f"<tr><td>{title}</td><td>{company}</td><td>{location}</td>"
            f"<td>{posted}</td><td><a href=\"{url}\">View job</a></td></tr>"
        )
    return """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>New Job Hunter Results</title><style>
body{font-family:Arial,sans-serif;color:#17211b;margin:28px}h1{color:#1d6b4f}
table{width:100%;border-collapse:collapse}th,td{padding:10px;border:1px solid #dce4dd;text-align:left}
th{background:#f3f5ef}tr:nth-child(even){background:#fafcf8}a{color:#1d6b4f;font-weight:bold}
</style></head><body>""" + f"<h1>{len(jobs)} new jobs</h1><table><thead><tr>" \
        "<th>Role</th><th>Company</th><th>Location</th><th>Posted</th><th>Link</th>" \
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></body></html>"


def _deliver_jobs_to_telegram(jobs: list[dict], recipient: str) -> int:
    if not jobs:
        return 0
    report = _new_jobs_html(jobs).encode("utf-8")
    response = httpx.post(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument",
        data={"chat_id": recipient, "caption": f"Job Hunter: {len(jobs)} new jobs"},
        files={"document": ("new-jobs.html", report, "text/html")},
        timeout=30,
    )
    telegram_result = response.json()
    if not response.is_success or not telegram_result.get("ok"):
        raise RuntimeError(telegram_result.get("description") or f"Telegram returned HTTP {response.status_code}")
    mark_jobs_sent_to_telegram([str(job["job_id"]) for job in jobs], recipient)
    return len(jobs)


@app.post("/api/telegram/send-new")
def send_new_jobs_to_telegram():
    data = request.get_json(silent=True) or {}
    recipient = str(data.get("recipient") or "").strip()
    if not re.fullmatch(r"(?:-?\d+|@[A-Za-z0-9_]{5,})", recipient):
        return jsonify({"error": "Enter a numeric Telegram chat ID or an @channel username."}), 400
    if not TELEGRAM_BOT_TOKEN:
        return jsonify({"error": "TELEGRAM_BOT_TOKEN is not configured in .env."}), 500

    jobs = get_unsent_new_jobs(recipient)
    if not jobs:
        return jsonify({"count": 0, "message": "No unsent new jobs for this recipient."})

    try:
        sent_count = _deliver_jobs_to_telegram(jobs, recipient)
    except Exception as exc:
        app.logger.warning("Telegram HTML delivery failed: %s", exc)
        return jsonify({"error": f"Telegram delivery failed: {exc}"}), 502

    return jsonify({"count": sent_count, "message": f"Sent {sent_count} new jobs as an HTML file."})


@app.post("/api/email/jobs")
def email_jobs():
    data = request.get_json(silent=True) or {}
    recipient = str(data.get("recipient_email") or "").strip()
    jobs = data.get("jobs", [])
    
    if not recipient:
        return jsonify({"error": "Recipient email is required"}), 400
    if not jobs:
        return jsonify({"error": "No jobs to send"}), 400
        
    gmail_user = os.getenv("GMAIL_USER")
    gmail_password = os.getenv("GMAIL_APP_PASSWORD")
    
    if not gmail_user or not gmail_password:
        return jsonify({"error": "Gmail credentials (GMAIL_USER, GMAIL_APP_PASSWORD) not configured in .env."}), 500
        
    try:
        msg = EmailMessage()
        msg["Subject"] = f"Job Hunter: {len(jobs)} Filtered Jobs"
        msg["From"] = gmail_user
        msg["To"] = recipient
        
        # Build HTML content
        html_content = _new_jobs_html(jobs)
        msg.set_content(f"Found {len(jobs)} jobs. Please view the HTML attachment or enable HTML emails.")
        msg.add_alternative(html_content, subtype='html')
        
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(gmail_user, gmail_password)
            server.send_message(msg)
            
        return jsonify({"message": f"Successfully sent {len(jobs)} jobs to {recipient}"})
    except Exception as exc:
        app.logger.exception("Failed to send email")
        return jsonify({"error": f"Failed to send email: {exc}"}), 502


def _service_snapshot() -> dict:
    with service_lock:
        return dict(service_state)


def _run_hourly_service(recipient: str, criteria: dict) -> None:
    global service_thread
    try:
        while not service_stop_event.is_set():
            with service_lock:
                service_state.update(phase="searching", error="")
            with app.app_context():
                response = _perform_search(criteria=criteria)
                if isinstance(response, tuple):
                    flask_response, status_code = response
                else:
                    flask_response, status_code = response, response.status_code
                result = flask_response.get_json()
            if status_code >= 400:
                raise RuntimeError(result.get("error", "Search failed"))
            if service_stop_event.is_set():
                break

            with service_lock:
                service_state["phase"] = "sending"
            new_jobs = [
                job for job in get_unsent_new_jobs(recipient)
                if int(job.get("appearance_count", 0)) == 1
            ]
            sent_count = _deliver_jobs_to_telegram(new_jobs, recipient)
            now = datetime.now(timezone.utc)
            with service_lock:
                service_state.update(
                    phase="waiting",
                    last_run=now.isoformat(),
                    next_run=(now + timedelta(seconds=SERVICE_INTERVAL_SECONDS)).isoformat(),
                    last_result={"found": result.get("count", 0), "sent": sent_count},
                    error="",
                )
            if service_stop_event.wait(SERVICE_INTERVAL_SECONDS):
                break
    except Exception as exc:
        app.logger.exception("Hourly job service failed")
        with service_lock:
            service_state.update(phase="error", error=str(exc), next_run=None)
    finally:
        with service_lock:
            service_state.update(running=False, phase="stopped" if service_stop_event.is_set() else service_state["phase"], next_run=None)
            service_thread = None


@app.post("/api/service/start")
def start_hourly_service():
    global service_thread
    data = request.get_json(silent=True) or {}
    recipient = str(data.get("recipient") or "").strip()
    if not re.fullmatch(r"(?:-?\d+|@[A-Za-z0-9_]{5,})", recipient):
        return jsonify({"error": "Enter a numeric Telegram chat ID or an @channel username."}), 400
    if not TELEGRAM_BOT_TOKEN:
        return jsonify({"error": "TELEGRAM_BOT_TOKEN is not configured in .env."}), 500
    criteria = data.get("criteria") if isinstance(data.get("criteria"), dict) else {}
    with service_lock:
        if service_state["running"]:
            return jsonify(dict(service_state))
        service_stop_event.clear()
        service_state.update(
            running=True, phase="starting", recipient=recipient, last_run=None,
            next_run=None, last_result=None, error="",
        )
        service_thread = threading.Thread(
            target=_run_hourly_service, args=(recipient, criteria), daemon=True,
            name="hourly-job-service",
        )
        service_thread.start()
        return jsonify(dict(service_state)), 202


@app.post("/api/service/stop")
def stop_hourly_service():
    service_stop_event.set()
    with service_lock:
        if service_state["running"]:
            service_state.update(phase="stopping", next_run=None)
        return jsonify(dict(service_state))


@app.get("/api/service/status")
def hourly_service_status():
    return jsonify(_service_snapshot())


@app.patch("/api/jobs/<job_id>/status")
def set_job_status(job_id):
    data = request.get_json(silent=True) or {}
    try:
        job = update_job_status(job_id, str(data.get("status", "")).lower())
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    if job is None:
        return jsonify({"error": "Job not found"}), 404
    return jsonify({"job": job})


@app.get("/api/companies")
def get_companies():
    custom = get_custom_companies()
    custom_names = {c["name"].lower() for c in custom}
    builtin = [
        {"name": c, "is_custom": False, "ats_type": "builtin", "company_id": c}
        for c in SUPPORTED_COMPANIES
        if c.lower() not in custom_names
    ]
    all_companies = [
        {"name": c["name"], "is_custom": True, "ats_type": c["ats_type"], "company_id": c["company_id"], "config": c.get("config", {})}
        for c in custom
    ] + builtin
    all_companies.sort(key=lambda x: x["name"].lower())
    return jsonify({"companies": all_companies, "count": len(all_companies)})


@app.get("/api/companies/custom")
def list_custom_companies():
    return jsonify({"custom_companies": get_custom_companies()})


@app.post("/api/companies/custom")
def create_custom_company():
    data = request.get_json(silent=True) or {}
    name = str(data.get("name") or "").strip()
    ats_type = str(data.get("ats_type") or "").strip().lower()
    config = data.get("config") if isinstance(data.get("config"), dict) else {}
    if not name:
        return jsonify({"error": "Company name is required."}), 400
    
    if ats_type in {"auto", "unknown", "detect", ""}:
        raw_url = config.get("url") or config.get("base_url") or ""
        try:
            async def _detect():
                async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                    return await auto_detect_company_ats(client, raw_url=raw_url, name=name, config=config)
            ats_type, config, msg = asyncio.run(_detect())
        except Exception:
            ats_type = "career_page"

    if ats_type not in {"greenhouse", "workday", "comeet", "smartrecruiters", "ashby", "career_page"}:
        return jsonify({"error": "Invalid ATS type. Choose Auto-Detect, Greenhouse, Workday, Comeet, SmartRecruiters, Ashby, or Career Website."}), 400
    
    saved = add_custom_company(name=name, ats_type=ats_type, config=config)
    return jsonify({"company": saved, "message": f"Successfully added {name} ({ats_type.capitalize()})!"}), 201


@app.delete("/api/companies/custom/<company_id>")
def remove_custom_company(company_id):
    deleted = delete_custom_company(company_id)
    if not deleted:
        return jsonify({"error": "Custom company not found."}), 404
    return jsonify({"message": "Custom company deleted successfully."})


@app.post("/api/companies/test")
def test_company():
    data = request.get_json(silent=True) or {}
    name = str(data.get("name") or "").strip() or "TestCompany"
    ats_type = str(data.get("ats_type") or "").strip().lower()
    config = data.get("config") if isinstance(data.get("config"), dict) else {}
    
    try:
        jobs, error, detected_ats, detected_msg, resolved_config = asyncio.run(
            test_company_fetcher(ats_type=ats_type, name=name, config=config)
        )
    except Exception as exc:
        return jsonify({"success": False, "jobs_count": 0, "error": str(exc)}), 200

    if error:
        return jsonify({
            "success": False,
            "jobs_count": 0,
            "error": error,
            "detected_ats": detected_ats,
            "detected_message": detected_msg,
            "resolved_config": resolved_config,
        }), 200
    
    return jsonify({
        "success": True,
        "jobs_count": len(jobs),
        "jobs_preview": jobs[:5],
        "detected_ats": detected_ats,
        "detected_message": detected_msg,
        "resolved_config": resolved_config,
        "message": f"Found {len(jobs)} active jobs for {name} ({detected_ats.capitalize()})!",
    })



if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=int(os.getenv("PORT", "5050")),
        debug=os.getenv("FLASK_DEBUG", "false").lower() == "true",
    )
