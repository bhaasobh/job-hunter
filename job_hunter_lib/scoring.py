"""Fetch jobs without ranking or scoring."""

from job_hunter_lib.jobs import fetch_jobs


async def find_and_filter_jobs(_cv_content: str) -> list[dict]:
    """Return fetched jobs after source-level filtering only."""
    jobs = await fetch_jobs()
    print(f"{len(jobs)} jobs fetched after filtring")
    return jobs
