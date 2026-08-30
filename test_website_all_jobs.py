"""Live end-to-end checks for the website's job search.

Run this test explicitly because it contacts every configured career website:

    python3 -m pytest -v -s test_website_all_jobs.py
"""

import re
from collections import Counter

import pytest

import web_app
from job_hunter_lib.config import SUPPORTED_COMPANIES
from job_hunter_lib.jobs import fetch_jobs as real_fetch_jobs
from job_hunter_lib.utils import generate_job_id


def _company_key(value: object) -> str:
    """Normalize display names and config slugs for coverage comparisons."""
    return re.sub(r"[^a-z0-9]+", "", str(value).casefold())


def _job_key(job: dict) -> str:
    """Use the same duplicate key preference as the website search."""
    key = job.get("job_id") or job.get("url") or (
        job.get("company"),
        job.get("title"),
        job.get("location"),
    )
    return str(key)


@pytest.mark.integration
def test_website_returns_all_jobs_from_all_companies(monkeypatch):
    """Fail with a useful report if sources/jobs disappear from the website."""
    fetched_jobs: list[dict] = []

    async def recording_fetch_jobs(**kwargs):
        jobs = await real_fetch_jobs(**kwargs)
        fetched_jobs.extend(jobs)
        return jobs

    def save_without_database(jobs, *args, **kwargs):
        # Preserve the website response shape without modifying jobs.db.
        saved = []
        for source_job in jobs:
            job = dict(source_job)
            job["job_id"] = str(job.get("job_id") or generate_job_id(job))
            job.setdefault("status", "new")
            job.setdefault("appearance_count", 1)
            job.setdefault("ai_analyzed", False)
            saved.append(job)
        return saved

    monkeypatch.setattr(web_app, "fetch_jobs", recording_fetch_jobs)
    monkeypatch.setattr(web_app, "get_all_jobs", lambda: [])
    monkeypatch.setattr(web_app, "save_search_results", save_without_database)

    with web_app.app.test_client() as client:
        response = client.post(
            "/api/search",
            json={
                "companies": [],
                "locations": [],
                "job_types": [],
                "excluded_keywords": [],
                "use_ai_analysis": False,
            },
        )

    assert response.status_code == 200, response.get_data(as_text=True)
    payload = response.get_json()
    displayed_jobs = payload["jobs"]

    expected_unique_jobs = {_job_key(job): job for job in fetched_jobs}
    displayed_job_keys = {_job_key(job) for job in displayed_jobs}
    missing_job_keys = sorted(set(expected_unique_jobs) - displayed_job_keys)

    displayed_company_keys = {
        _company_key(job.get("company")) for job in displayed_jobs
    }
    company_quantities = Counter(
        str(job.get("company") or "Unknown").strip() for job in displayed_jobs
    )
    print("\n\nJOB QUANTITY BY COMPANY")
    print("=" * 50)
    for company in SUPPORTED_COMPANIES:
        quantity = sum(
            count
            for displayed_company, count in company_quantities.items()
            if _company_key(displayed_company) == _company_key(company)
        )
        print(f"{company:<35} {quantity:>5}")
    print("=" * 50)
    print(f"TOTAL UNIQUE JOBS{'':<18} {len(displayed_jobs):>5}")

    missing_companies = sorted(
        company
        for company in SUPPORTED_COMPANIES
        if _company_key(company) not in displayed_company_keys
    )

    invalid_jobs = [
        {
            "company": job.get("company"),
            "title": job.get("title"),
            "url": job.get("url"),
        }
        for job in displayed_jobs
        if not str(job.get("company") or "").strip()
        or not str(job.get("title") or "").strip()
        or not str(job.get("url") or "").startswith(("http://", "https://"))
    ]

    problems = []
    if missing_companies:
        problems.append(
            f"{len(missing_companies)} configured companies returned no displayed jobs:\n"
            + "\n".join(f"  - {company}" for company in missing_companies)
        )
    if missing_job_keys:
        preview = [expected_unique_jobs[key] for key in missing_job_keys[:20]]
        problems.append(
            f"{len(missing_job_keys)} fetched jobs were absent from the API response. "
            f"First 20: {preview!r}"
        )
    if invalid_jobs:
        problems.append(
            f"{len(invalid_jobs)} displayed jobs have no title, company, or valid URL. "
            f"First 20: {invalid_jobs[:20]!r}"
        )

    assert payload["count"] == len(displayed_jobs)
    assert len(displayed_jobs) == len(expected_unique_jobs)
    assert not problems, "\n\n".join(problems)
