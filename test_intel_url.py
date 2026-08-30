
import asyncio
import httpx
from job_hunter_lib.fetchers import fetch_workday_jobs
from job_hunter_lib.config import WORKDAY_SOURCES

async def main():
    intel_source = [s for s in WORKDAY_SOURCES if s["company"] == "intel"][0]
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        # We only want to see if the URL is generated correctly
        # We might not even need a real response if we mock it, 
        # but let's try a real fetch for a few jobs.
        jobs, sent_count = await fetch_workday_jobs(client, intel_source)
        if jobs:
            print(f"Generated URL for first job: {jobs[0]['url']}")
        else:
            print("No jobs found for Intel.")

if __name__ == "__main__":
    asyncio.run(main())
