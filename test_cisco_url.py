
import asyncio
import httpx
from job_hunter_lib.fetchers import fetch_workday_jobs
from job_hunter_lib.config import WORKDAY_SOURCES

async def main():
    cisco_source = [s for s in WORKDAY_SOURCES if s["company"] == "cisco"][0]
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        jobs, sent_count = await fetch_workday_jobs(client, cisco_source)
        if jobs:
            print(f"Found {len(jobs)} jobs for Cisco.")
            print(f"Generated URL for first job: {jobs[0]['url']}")
        else:
            print("No jobs found for Cisco.")

if __name__ == "__main__":
    asyncio.run(main())
