"""MongoDB persistence for jobs displayed by the web app."""

import os
import re
from datetime import datetime, timezone
import pymongo

from job_hunter_lib.config import MONGO_URI
from job_hunter_lib.utils import generate_job_id

client = pymongo.MongoClient(MONGO_URI) if MONGO_URI else None
db = client.job_hunter if client else None

VALID_STATUSES = {"new", "old", "saved", "applied"}

def get_custom_companies() -> list[dict]:
    if db is None: return []
    docs = db.custom_companies.find().sort("name", 1)
    companies = []
    for doc in docs:
        doc.pop("_id", None)
        companies.append(doc)
    return companies

def add_custom_company(name: str, ats_type: str, config: dict) -> dict:
    clean_name = str(name).strip()
    clean_ats = str(ats_type).strip().lower()
    company_id = re.sub(r"[^a-z0-9_]+", "_", clean_name.lower()).strip("_") or f"custom_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    now = datetime.now(timezone.utc).isoformat()
    
    doc = {
        "company_id": company_id,
        "name": clean_name,
        "ats_type": clean_ats,
        "config": config,
        "created_at": now
    }
    db.custom_companies.update_one({"company_id": company_id}, {"$set": doc}, upsert=True)
    return doc

def delete_custom_company(company_id: str) -> bool:
    res = db.custom_companies.delete_one({"company_id": company_id})
    return res.deleted_count > 0

def cleanup_database_hygiene():
    # MongoDB handles this differently, we can skip complex deduplication here or implement later
    pass

def save_search_results(jobs: list[dict], run_seen_ids: set | None = None) -> list[dict]:
    now = datetime.now(timezone.utc).isoformat()
    saved = []
    
    for source_job in jobs:
        job = dict(source_job)
        job_id = str(job.get("job_id") or generate_job_id(job))
        job["job_id"] = job_id
        
        existing = db.jobs.find_one({"job_id": job_id})
        
        if existing:
            ai_analyzed = bool(existing.get("ai_analyzed")) or bool(job.get("ai_analyzed") or job.get("ai_analysis"))
            if existing.get("ai_analyzed"):
                for field in ("match_score", "match_reason", "ai_analysis", "score_source"):
                    if field in existing:
                        job[field] = existing[field]
                        
            already_counted = run_seen_ids is not None and job_id in run_seen_ids
            count = existing.get("appearance_count", 1) if already_counted else existing.get("appearance_count", 1) + 1
            
            status = existing.get("status", "new")
            if status not in {"saved", "applied"}:
                status = "old" if count > 3 else "new"
                
            first_seen = existing.get("first_seen", now)
            
            job.update(status=status, appearance_count=count, first_seen=first_seen, last_seen=now, ai_analyzed=ai_analyzed)
            db.jobs.update_one({"job_id": job_id}, {"$set": job})
        else:
            ai_analyzed = bool(job.get("ai_analyzed") or job.get("ai_analysis"))
            job.update(status="new", appearance_count=1, first_seen=now, last_seen=now, ai_analyzed=ai_analyzed)
            db.jobs.insert_one(job.copy())
            
        if run_seen_ids is not None:
            run_seen_ids.add(job_id)
            
        saved.append(job)
        
    return saved

def get_all_jobs() -> list[dict]:
    docs = db.jobs.find().sort("last_seen", -1)
    jobs = []
    for doc in docs:
        doc.pop("_id", None)
        jobs.append(doc)
    return jobs

def get_unsent_new_jobs(recipient: str) -> list[dict]:
    sent_job_ids = db.telegram_deliveries.distinct("job_id", {"recipient": recipient})
    docs = db.jobs.find({
        "status": "new",
        "job_id": {"$nin": sent_job_ids}
    }).sort("first_seen", -1)
    
    jobs = []
    for doc in docs:
        doc.pop("_id", None)
        jobs.append(doc)
    return jobs

def mark_jobs_sent_to_telegram(job_ids: list[str], recipient: str):
    now = datetime.now(timezone.utc).isoformat()
    ops = [
        pymongo.UpdateOne(
            {"job_id": j_id, "recipient": recipient},
            {"$setOnInsert": {"sent_at": now}},
            upsert=True
        ) for j_id in job_ids
    ]
    if ops:
        db.telegram_deliveries.bulk_write(ops)

def save_job_ai_analysis(job_id: str, analysis: dict, match_reason: str, score_source: str) -> dict | None:
    updates = {
        "match_score": analysis["score"],
        "match_reason": match_reason,
        "ai_analysis": analysis,
        "score_source": score_source,
        "ai_analyzed": True
    }
    db.jobs.update_one({"job_id": job_id}, {"$set": updates})
    
    doc = db.jobs.find_one({"job_id": job_id})
    if doc:
        doc.pop("_id", None)
    return doc

def update_job_status(job_id: str, status: str) -> dict | None:
    if status not in VALID_STATUSES:
        raise ValueError("Status must be new, old, saved, or applied")
        
    db.jobs.update_one({"job_id": job_id}, {"$set": {"status": status}})
    doc = db.jobs.find_one({"job_id": job_id})
    if doc:
        doc.pop("_id", None)
    return doc

def get_ai_job_match(cv_hash: str, job_hash: str, model: str) -> dict | None:
    doc = db.ai_job_matches.find_one({"cv_hash": cv_hash, "job_hash": job_hash, "model": model})
    return doc.get("analysis_json") if doc else None

def save_ai_job_match(cv_hash: str, job_hash: str, model: str, analysis: dict) -> None:
    now = datetime.now(timezone.utc).isoformat()
    db.ai_job_matches.update_one(
        {"cv_hash": cv_hash, "job_hash": job_hash, "model": model},
        {"$set": {"analysis_json": analysis, "created_at": now}},
        upsert=True
    )
