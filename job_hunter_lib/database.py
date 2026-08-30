"""MongoDB integration for job response tracking."""

import pymongo
from datetime import datetime
from job_hunter_lib.config import MONGO_URI

# Connect to MongoDB
client = pymongo.MongoClient(MONGO_URI)
db = client.job_hunter
responses = db.job_responses
jobs_col = db.jobs

def save_job_response(user_id: int, job_id: str, status: str):
    """Save or update a user's response to a job in MongoDB."""
    result = responses.update_one(
        {"user_id": user_id, "job_id": job_id},
        {"$set": {
            "status": status,
            "timestamp": datetime.utcnow()
        }},
        upsert=True
    )
    return result.upserted_id or job_id

def save_job_to_db(job: dict):
    """Save or update full job details and return True when the job has no saved response."""
    job_id = job.get("job_id")
    if not job_id:
        return False

    existing = jobs_col.find_one({"job_id": job_id})
    job_data = dict(job)
    job_data["last_seen"] = datetime.utcnow()

    if not existing:
        jobs_col.insert_one(job_data)
    else:
        jobs_col.update_one(
            {"job_id": job_id},
            {"$set": job_data}
        )

    return responses.count_documents({"job_id": job_id}, limit=1) == 0

def mark_job_as_notified(job_id: str):
    """Mark a job as having been sent to Telegram."""
    jobs_col.update_one({"job_id": job_id}, {"$set": {"notified": True}})

def get_job_from_db(job_id: str):
    """Retrieve full job details from MongoDB."""
    return jobs_col.find_one({"job_id": job_id})

def get_jobs_by_status(status: str):
    """Get all jobs that have a specific response status."""
    # Find active responses with this status
    active_responses = list(responses.find({"status": status}))
    job_ids = [r["job_id"] for r in active_responses]
    return list(jobs_col.find({"job_id": {"$in": job_ids}}))

def get_unresponded_jobs():
    """Get jobs that have been fetched but the user hasn't voted on at all."""
    # Get all job_ids that have any response
    responded_ids = responses.distinct("job_id")
    # Return jobs that are NOT in the responded list
    return list(jobs_col.find({"job_id": {"$nin": responded_ids}}))
