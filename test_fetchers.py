"""Fast unit tests for every function in job_hunter_lib.fetchers."""

import asyncio
import sys
import types

import httpx
import pytest

from job_hunter_lib import fetchers


def run(awaitable):
    return asyncio.run(awaitable)


def client_returning(*, json_data=None, text="", status=200, headers=None):
    """Build an AsyncClient whose every request returns the supplied fixture."""
    def handler(request):
        return httpx.Response(
            status,
            json=json_data if json_data is not None else None,
            text=None if json_data is not None else text,
            headers=headers,
            request=request,
        )

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def assert_one_job(result, company):
    jobs, sent = result
    assert sent == 0
    assert len(jobs) == 1
    assert jobs[0]["company"] == company
    assert jobs[0]["job_id"]
    assert jobs[0]["url"].startswith("http")
    return jobs[0]


def test_format_source_error():
    request = httpx.Request("GET", "https://careers.example/jobs")
    response = httpx.Response(503, request=request)
    status_error = httpx.HTTPStatusError("failed", request=request, response=response)
    assert fetchers.format_source_error(status_error) == "503 from careers.example"
    assert fetchers.format_source_error(ValueError("bad data")) == "ValueError: bad data"


def test_matches_preferences():
    token = fetchers.ACTIVE_EXCLUDED_KEYWORDS.set(("senior", "manager"))
    try:
        assert fetchers.matches_preferences({"title": "Software Engineer"})
        assert not fetchers.matches_preferences({"title": "Senior Software Engineer"})
    finally:
        fetchers.ACTIVE_EXCLUDED_KEYWORDS.reset(token)


def test_send_jobs_without_status(monkeypatch):
    sent_messages = []
    fake_database = types.ModuleType("job_hunter_lib.database")
    fake_database.save_job_to_db = lambda job: job["title"] != "Known"
    monkeypatch.setitem(sys.modules, "job_hunter_lib.database", fake_database)
    monkeypatch.setattr(fetchers, "format_job_message", lambda job: job["title"])
    monkeypatch.setattr(fetchers, "get_job_keyboard", lambda job_id: {"id": job_id})

    async def fake_send(message, reply_markup=None):
        sent_messages.append((message, reply_markup))
        return True

    monkeypatch.setattr(fetchers, "send_telegram_message", fake_send)
    jobs = [{"title": "Known", "job_id": "1"}, {"title": "New", "job_id": "2"}]
    assert run(fetchers.send_jobs_without_status(jobs)) == 1
    assert sent_messages == [("New", {"id": "2"})]
    assert run(fetchers.send_jobs_without_status([])) == 0


def test_fetch_greenhouse_jobs():
    data = {"jobs": [{
        "title": "Backend Engineer", "location": {"name": "Tel Aviv, Israel"},
        "content": "Build APIs", "absolute_url": "https://example/jobs/1",
        "updated_at": "2026-01-01",
    }]}
    async def scenario():
        async with client_returning(json_data=data) as client:
            return await fetchers.fetch_greenhouse_jobs(client, "board", False, "company")
    assert_one_job(run(scenario()), "company")


def test_fetch_qualcomm_jobs():
    data = {"data": {"positions": [{
        "name": "Chip Engineer", "locations": ["Haifa, Israel"],
        "description": "Design chips", "positionUrl": "/job/1",
        "postedDate": "2026-01-01", "jobCategory": ["Engineering"],
    }]}}
    source = {"company": "qualcomm", "base_url": "https://example/api?lang=en"}
    async def scenario():
        async with client_returning(json_data=data) as client:
            return await fetchers.fetch_qualcomm_jobs(client, source, False)
    assert_one_job(run(scenario()), "qualcomm")


def test_fetch_nvidia_jobs():
    data = {"jobPostings": [{
        "title": "GPU Engineer", "locationsText": "Yokneam, Israel",
        "externalPath": "/job/gpu-engineer", "postedDate": "Today",
    }]}
    source = {"company": "nvidia", "base_url": "https://nvidia.wd5.myworkdayjobs.com/wday/cxs/nvidia/NVIDIAExternalCareerSite/jobs"}
    async def scenario():
        async with client_returning(json_data=data) as client:
            return await fetchers.fetch_nvidia_jobs(client, source, False)
    assert_one_job(run(scenario()), "nvidia")


def test_fetch_workday_jobs():
    data = {"jobPostings": [{
        "title": "Cloud Engineer", "locationsText": "Petah Tikva, Israel",
        "externalPath": "/job/cloud-1", "postedOn": "Today",
        "bulletFields": ["Cloud"],
    }]}
    source = {
        "company": "example", "base_url": "https://example.wd1.myworkdayjobs.com/wday/cxs/example/Site/jobs",
        "payload": {"limit": 20, "offset": 0, "searchText": ""},
    }
    async def scenario():
        async with client_returning(json_data=data) as client:
            return await fetchers.fetch_workday_jobs(client, source, False)
    assert_one_job(run(scenario()), "example")


def test_fetch_career_page_jobs():
    page = '<div>Tel Aviv, Israel <a href="/jobs/backend-engineer">Backend Engineer</a></div>'
    source = {
        "company": "official_company", "url": "https://careers.example/careers/",
        "path_markers": ["/jobs/"], "assume_israel": True,
    }
    async def scenario():
        async with client_returning(text=page) as client:
            return await fetchers.fetch_career_page_jobs(client, source, False)
    assert_one_job(run(scenario()), "official_company")


def test_fetch_sqlink_jobs():
    page = """
    <div id="searchResultsList"><div class="article" id="id-154682">
      <a href="/career/devops/devops-engineer/"><h3>DevOps Engineer</h3></a>
      <section class="description"><strong>תיאור המשרה:</strong><p>Build cloud platforms.</p></section>
      <section class="requirements"><strong>דרישות המשרה:</strong><p>Python and Kubernetes.</p></section>
    </div></div>
    """
    source = {"company": "sqlink", "url": "https://www.sqlink.com/career/", "kind": "sqlink"}
    async def scenario():
        async with client_returning(text=page) as client:
            return await fetchers.fetch_career_page_jobs(client, source, False)
    job = assert_one_job(run(scenario()), "sqlink")
    assert job["job_id"] == "sqlink-154682"
    assert job["url"] == "https://www.sqlink.com/career/devops/devops-engineer/"
    assert "Python" in job["requirements"]


def test_fetch_tesnet_jobs():
    page = """
    <div class="job-list"><div class="item">
      <h3 class="title">QA Automation Engineer</h3>
      <div class="locations">איזור: מרכז</div>
      <div class="description"><p>Python and test automation.</p></div>
      <a href="https://www.facebook.com/sharer/sharer.php?u=https%3A%2F%2Ftesnet-group.com%2Fjob%2Fqa-automation%2F"></a>
      <a class="popup-job" data-job-code=" JB-1234" href="#popup-contact">Apply</a>
    </div></div>
    """
    source = {"company": "tesnet", "url": "https://tesnet-group.com/job/", "kind": "tesnet"}
    async def scenario():
        async with client_returning(text=page) as client:
            return await fetchers.fetch_career_page_jobs(client, source, False)
    job = assert_one_job(run(scenario()), "tesnet")
    assert job["job_id"] == "tesnet-JB-1234"
    assert job["location"] == "מרכז"
    assert job["url"] == "https://tesnet-group.com/job/qa-automation/"


def test_fetch_career_page_recruitee_jobs():
    data = {"offers": [
        {
            "id": 101, "title": "Payments Engineer", "country_code": "IL",
            "location": "Tel Aviv, Israel", "description": "<p>Build payments</p>",
            "requirements": "<ul><li>Python</li></ul>",
            "employment_type_code": "fulltime_permanent",
            "careers_url": "https://careers.example/o/payments-engineer",
            "created_at": "2026-08-20 10:00:00 UTC",
        },
        {
            "id": 102, "title": "Overseas Engineer", "country_code": "SG",
            "location": "Singapore", "careers_url": "https://careers.example/o/overseas",
        },
    ]}
    source = {
        "company": "zota", "url": "https://careers.example/",
        "api_url": "https://careers.example/api/offers/", "kind": "recruitee",
    }
    async def scenario():
        async with client_returning(json_data=data) as client:
            return await fetchers.fetch_career_page_jobs(client, source, False)
    job = assert_one_job(run(scenario()), "zota")
    assert job["requirements"] == "Python"
    assert job["job_type"] == "Full-time"


def test_fetch_comeet_jobs():
    data = [{
        "name": "Security Engineer", "location": {"name": "Tel Aviv", "country": "Israel"},
        "details": [{"value": "Protect systems"}], "department": "Security",
        "url_active_page": "https://example/jobs/security",
    }]
    source = {"company": "comeet_company", "uid": "uid", "token": "token"}
    async def scenario():
        async with client_returning(json_data=data) as client:
            return await fetchers.fetch_comeet_jobs(client, source, False)
    assert_one_job(run(scenario()), "comeet_company")


def test_fetch_smartrecruiters_jobs():
    data = {"content": [{
        "id": "1", "name": "Platform Engineer",
        "location": {"country": "il", "fullLocation": "Tel Aviv, Israel"},
        "company": {"identifier": "Example"},
        "typeOfEmployment": {"label": "Full-time"}, "department": {"label": "R&D"},
    }]}
    source = {"company": "smart_company", "url": "https://api.example/jobs"}
    async def scenario():
        async with client_returning(json_data=data) as client:
            return await fetchers.fetch_smartrecruiters_jobs(client, source, False)
    assert_one_job(run(scenario()), "smart_company")


def test_fetch_ashby_jobs():
    data = {"jobs": [{
        "title": "DevOps Engineer", "location": "Tel Aviv, Israel",
        "descriptionPlain": "Operate systems", "employmentType": "FullTime",
        "department": "Engineering", "jobUrl": "https://example/jobs/devops",
    }]}
    source = {"company": "ashby_company", "board": "board"}
    async def scenario():
        async with client_returning(json_data=data) as client:
            return await fetchers.fetch_ashby_jobs(client, source, False)
    assert_one_job(run(scenario()), "ashby_company")


def test_fetch_elbit_jobs():
    data = [{
        "status": 1, "jobId": 42, "jobTitle": "Systems Engineer",
        "area": "Haifa", "description": "Build systems", "jobCode": "SYS42",
    }]
    source = {
        "company": "elbit", "url": "https://api.example/jobs",
        "job_url": "https://example/job", "careers_url": "https://example/careers",
    }
    async def scenario():
        async with client_returning(json_data=data) as client:
            return await fetchers.fetch_elbit_jobs(client, source, False)
    job = assert_one_job(run(scenario()), "elbit")
    assert job["job_id"] == "elbit-42"


def test_fetch_iscar_jobs():
    page = '<h3><a href="https://www.iscar.com/marcom/job/JB-123">Software Engineer - JB-123</a></h3>'
    source = {
        "company": "iscar", "url": "https://www.iscar.com/career/",
        "text_proxy": "https://proxy.example/", "max_pages": 1,
    }
    async def scenario():
        async with client_returning(text=page) as client:
            return await fetchers.fetch_iscar_jobs(client, source, False)
    job = assert_one_job(run(scenario()), "iscar")
    assert job["job_id"] == "iscar-123"


def test_fetch_bank_jobs():
    page = '<article><h3>QA Engineer</h3><p>Testing bank software</p></article>'
    source = {"company": "mizrahi", "url": "https://bank.example/jobs", "kind": "mizrahi"}
    async def scenario():
        async with client_returning(text=page) as client:
            return await fetchers.fetch_bank_jobs(client, source, False)
    assert_one_job(run(scenario()), "mizrahi")


def test_fetch_government_jobs():
    page = '''<article><a href="/he/pages/software-job">מהנדס תוכנה</a>
    <div>דרושים סטטוס פעיל מיקום: ירושלים תאריך פרסום: 01.01.2026</div></article>'''
    source = {
        "company": "israel_civil_service", "url": "https://gov.example/jobs",
        "search_url": "https://search.example/rss",
    }
    async def scenario():
        async with client_returning(text=page) as client:
            return await fetchers.fetch_government_jobs(client, source, False)
    assert_one_job(run(scenario()), "israel_civil_service")


def test_fetch_big_tech_jobs():
    data = {"hits": 1, "jobs": [{
        "id": "123", "title": "Software Engineer", "location": "Tel Aviv, Israel",
        "description_short": "Build services", "job_path": "/en/jobs/123",
    }]}
    source = {"company": "amazon", "kind": "amazon", "url": "https://amazon.example/api/jobs"}
    async def scenario():
        async with client_returning(json_data=data) as client:
            return await fetchers.fetch_big_tech_jobs(client, source, False)
    job = assert_one_job(run(scenario()), "amazon")
    assert job["job_id"] == "amazon-123"


def test_make_official_job():
    job = fetchers._make_official_job(
        "company", "Engineer", "Remote, Israel", "Build things",
        "https://example/jobs/1", "Official careers",
    )
    assert job["company"] == "company"
    assert job["remote"] is True
    assert job["job_id"].startswith("company-")


def test_all_fetcher_functions_have_tests():
    """Guard against adding a fetcher function without adding its unit test."""
    expected = {
        "format_source_error", "matches_preferences", "send_jobs_without_status",
        "fetch_greenhouse_jobs", "fetch_qualcomm_jobs", "fetch_nvidia_jobs",
        "fetch_workday_jobs", "fetch_career_page_jobs", "fetch_comeet_jobs",
        "fetch_smartrecruiters_jobs", "fetch_ashby_jobs", "fetch_elbit_jobs",
        "fetch_iscar_jobs", "fetch_bank_jobs", "fetch_government_jobs",
        "fetch_big_tech_jobs", "_make_official_job",
    }
    actual = {
        name for name, value in vars(fetchers).items()
        if callable(value)
        and getattr(value, "__module__", None) == fetchers.__name__
    }
    assert actual == expected


def test_fetch_jobs_source_calls_registration():
    from job_hunter_lib.jobs import fetch_jobs
    import asyncio

    # Run with non-existent company filter to verify all source_calls build without NameError
    jobs = asyncio.run(fetch_jobs(companies=["non_existent_company"], notify=False))
    assert jobs == []


