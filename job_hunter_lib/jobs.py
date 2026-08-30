"""Main job orchestration and processing logic."""

import asyncio
import html
import re
import httpx

from job_hunter_lib.config import (
    GREENHOUSE_BOARDS,
    GREENHOUSE_COMPANY_ALIASES,
    nvidia_source,
    qualcomm_source,
    ISRAEL_LOCATION_KEYWORDS,
    COMEET_SOURCES,
    ASHBY_SOURCES,
    ELBIT_SOURCE,
    ISCAR_SOURCE,
    BANK_SOURCES,
    GOVERNMENT_JOBS_SOURCE,
    BIG_TECH_SOURCES,
    SMARTRECRUITERS_SOURCES,
    JUNIOR_KEYWORDS,
    SKILL_KEYWORDS,
    WORKDAY_SOURCES,
    CAREER_PAGE_SOURCES,
)
from job_hunter_lib.fetchers import (
    fetch_greenhouse_jobs,
    fetch_qualcomm_jobs,
    fetch_nvidia_jobs,
    fetch_workday_jobs,
    fetch_comeet_jobs,
    fetch_smartrecruiters_jobs,
    fetch_ashby_jobs,
    fetch_elbit_jobs,
    fetch_iscar_jobs,
    fetch_bank_jobs,
    fetch_government_jobs,
    fetch_big_tech_jobs,
    fetch_career_page_jobs,
    format_source_error,
    ACTIVE_EXCLUDED_KEYWORDS,
    TITLE_EXCLUDED_KEYWORDS,
)
from job_hunter_lib.local_database import get_custom_companies

CV_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "your", "you",
    "have", "has", "had", "using", "used", "use", "into", "over", "under",
    "build", "built", "work", "worked", "working", "experience", "professional",
    "summary", "education", "languages", "skills", "technical", "student",
    "engineering", "software", "systems", "developer", "development",
    "strong", "knowledge", "opportunities", "reliable", "scalable",
}

def extract_cv_keywords(cv_content: str) -> list[str]:
    cv_lower = str(cv_content).lower()

    # Keep known technical terms with high priority when they appear in the CV.
    matched_known = [keyword for keyword in SKILL_KEYWORDS if keyword in cv_lower]

    # Extract candidate terms from the CV text itself.
    normalized = cv_lower.replace("/", " ").replace("-", " ")
    raw_tokens = re.findall(r"[a-zA-Z][a-zA-Z0-9+#.]{1,24}", normalized)

    token_counts: dict[str, int] = {}
    for token in raw_tokens:
        cleaned = token.strip(".").lower()
        if cleaned in CV_STOPWORDS or len(cleaned) < 2:
            continue
        token_counts[cleaned] = token_counts.get(cleaned, 0) + 1

    # Preserve important multi-word platform terms when present in the CV.
    phrase_candidates = [
        "rest api", "api gateway", "cloud watch", "usb type c",
        "embedded systems", "machine learning", "operating systems",
        "computer vision", "data structures", "network engineering",
        "cloud computing", "fault isolation",
    ]
    matched_phrases = [phrase for phrase in phrase_candidates if phrase in cv_lower]

    ranked_tokens = sorted(
        token_counts.items(),
        key=lambda item: (-item[1], -len(item[0]), item[0]),
    )
    extracted_tokens = [token for token, _count in ranked_tokens[:20]]

    combined = []
    for keyword in matched_known + matched_phrases + extracted_tokens:
        if keyword not in combined:
            combined.append(keyword)

    return combined[:15] or ["python", "linux", "automation"]

SECTION_HEADINGS = (
    "requirements", "qualifications", "what you bring", "what we're looking for",
    "required skills", "skills and experience", "דרישות", "כישורים",
)
SECTION_END_HEADINGS = (
    "responsibilities", "about the role", "about us", "what you'll do", "benefits",
    "why join", "equal opportunity", "apply", "תחומי אחריות", "אודות",
)


def _clean_job_text(value: str) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", str(value or "")))
    return re.sub(r"\s+", " ", text).strip()


def _section_after_heading(text: str, headings: tuple[str, ...], end_headings: tuple[str, ...]) -> str:
    heading_pattern = "|".join(re.escape(heading) for heading in headings)
    match = re.search(rf"\b(?:{heading_pattern})\b\s*:?-?", text, re.I)
    if not match:
        return ""
    remainder = text[match.end():]
    end_pattern = "|".join(re.escape(heading) for heading in end_headings)
    end_match = re.search(rf"\b(?:{end_pattern})\b\s*:?-?", remainder, re.I)
    return remainder[:end_match.start() if end_match else 3000].strip(" :-")


def extract_job_sections(job: dict) -> dict:
    """Add normalized requirements and responsibilities to a fetched job."""
    description = _clean_job_text(job.get("description", ""))
    requirements = _section_after_heading(description, SECTION_HEADINGS, SECTION_END_HEADINGS)
    responsibilities = _section_after_heading(
        description,
        ("responsibilities", "what you'll do", "what you will do", "תחומי אחריות"),
        SECTION_HEADINGS + ("benefits", "why join", "equal opportunity", "דרישות"),
    )
    if not requirements:
        sentences = re.split(r"(?<=[.!?])\s+|[•▪●]\s*", description)
        requirement_signals = (
            "required", "must", "experience", "proficient", "knowledge of", "familiar",
            "degree", "years", "ניסיון", "חובה", "דרישות", "תואר",
        )
        requirements = " ".join(
            sentence.strip() for sentence in sentences
            if any(signal in sentence.lower() for signal in requirement_signals)
        )
    enriched = dict(job)
    enriched["description"] = description[:5000]
    enriched["requirements"] = _clean_job_text(job.get("requirements"))[:3000] or requirements[:3000]
    enriched["responsibilities"] = _clean_job_text(job.get("responsibilities"))[:3000] or responsibilities[:3000]
    return enriched


def _contains_keyword(text: str, keyword: str) -> bool:
    return re.search(rf"(?<![a-z0-9+#]){re.escape(keyword.lower())}(?![a-z0-9+#])", text.lower()) is not None


def keyword_score(job: dict, cv_keywords: list[str], cv_experience_years: int = 0) -> tuple[int, str]:
    """Score title, explicit requirements, general description, and experience fit."""
    title = str(job.get("title", ""))
    requirements = str(job.get("requirements", ""))
    description = " ".join((str(job.get("description", "")), str(job.get("tags", ""))))
    title_matches = [keyword for keyword in cv_keywords if _contains_keyword(title, keyword)]
    requirement_matches = [keyword for keyword in cv_keywords if _contains_keyword(requirements, keyword)]
    description_matches = [
        keyword for keyword in cv_keywords
        if _contains_keyword(description, keyword)
        and keyword not in title_matches and keyword not in requirement_matches
    ]

    score = 1.0
    score += min(2.5, len(title_matches) * 1.25)
    score += min(4.0, len(requirement_matches) * 1.1)
    score += min(2.0, len(description_matches) * 0.5)

    required_years = [
        int(value) for value in re.findall(r"\b(\d{1,2})\+?\s*(?:years?|שנות)\b", requirements, re.I)
    ]
    minimum_years = max(required_years, default=0)
    experience_note = ""
    if minimum_years and cv_experience_years:
        if cv_experience_years >= minimum_years:
            score += 0.5
            experience_note = f"experience meets {minimum_years}+ years"
        else:
            score -= min(2.0, (minimum_years - cv_experience_years) * 0.5)
            experience_note = f"requires {minimum_years}+ years"

    score = max(1, min(10, round(score)))
    reasons = []
    if title_matches:
        reasons.append(f"title: {', '.join(title_matches[:3])}")
    if requirement_matches:
        reasons.append(f"requirements: {', '.join(requirement_matches[:4])}")
    if description_matches:
        reasons.append(f"description: {', '.join(description_matches[:3])}")
    if experience_note:
        reasons.append(experience_note)
    return score, "; ".join(reasons) or "No strong CV match found in the published job details."

async def fetch_jobs(
    return_stats: bool = False,
    notify: bool = True,
    progress_callback=None,
    companies: list[str] | None = None,
    excluded_keywords: list[str] | None = None,
    on_jobs_found=None,
):
    ACTIVE_EXCLUDED_KEYWORDS.set(tuple(
        str(keyword).strip().lower()
        for keyword in (TITLE_EXCLUDED_KEYWORDS if excluded_keywords is None else excluded_keywords)
        if str(keyword).strip()
    ))
    selected_companies = {str(company).strip().lower() for company in (companies or []) if str(company).strip()}
    completed_sources = 0

    def report(source_name: str):
        nonlocal completed_sources
        completed_sources += 1
        if progress_callback:
            progress_callback(completed_sources, total_sources, source_name)

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        results = []
        sent_count = 0

        source_calls = []
        for board in GREENHOUSE_BOARDS:
            company_name = GREENHOUSE_COMPANY_ALIASES.get(board, board)
            source_calls.append((
                company_name,
                lambda board=board, company_name=company_name: fetch_greenhouse_jobs(
                    client, board, notify=notify, company_name=company_name
                ),
            ))

        source_calls.extend([
            ("qualcomm", lambda: fetch_qualcomm_jobs(client, qualcomm_source, notify=notify)),
            ("nvidia", lambda: fetch_nvidia_jobs(client, nvidia_source, notify=notify)),
            ("elbit_systems", lambda: fetch_elbit_jobs(client, ELBIT_SOURCE, notify=notify)),
            ("iscar", lambda: fetch_iscar_jobs(client, ISCAR_SOURCE, notify=notify)),
        ])

        for source in BANK_SOURCES:
            source_calls.append((
                source["company"],
                lambda source=source: fetch_bank_jobs(client, source, notify=notify),
            ))

        source_calls.append((
            "israel_civil_service",
            lambda: fetch_government_jobs(client, GOVERNMENT_JOBS_SOURCE, notify=notify),
        ))

        fetcher_groups = [
            (BIG_TECH_SOURCES, fetch_big_tech_jobs),
            (WORKDAY_SOURCES, fetch_workday_jobs),
            (SMARTRECRUITERS_SOURCES, fetch_smartrecruiters_jobs),
            (COMEET_SOURCES, fetch_comeet_jobs),
            (ASHBY_SOURCES, fetch_ashby_jobs),
            (CAREER_PAGE_SOURCES, fetch_career_page_jobs),
        ]
        for sources, fetcher in fetcher_groups:
            for source in sources:
                source_calls.append((
                    source["company"],
                    lambda source=source, fetcher=fetcher: fetcher(client, source, notify=notify),
                ))

        try:
            custom_companies = get_custom_companies()
        except Exception:
            custom_companies = []

        for custom in custom_companies:
            ats = str(custom.get("ats_type", "")).strip().lower()
            name = str(custom.get("name", "")).strip()
            cfg = custom.get("config", {})
            if not name:
                continue
            if ats == "greenhouse":
                token = str(cfg.get("board_token") or name).strip()
                source_calls.append((
                    name,
                    lambda token=token, name=name: fetch_greenhouse_jobs(client, token, notify=notify, company_name=name),
                ))
            elif ats == "workday":
                wd_source = {
                    "company": name,
                    "base_url": cfg.get("base_url", ""),
                    "payload": cfg.get("payload") or {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": cfg.get("search_text", "Israel")},
                }
                source_calls.append((
                    name,
                    lambda source=wd_source: fetch_workday_jobs(client, source, notify=notify),
                ))
            elif ats == "comeet":
                cm_source = {
                    "company": name,
                    "uid": cfg.get("uid", ""),
                    "token": cfg.get("token", ""),
                    "assume_israel": cfg.get("assume_israel", True),
                }
                source_calls.append((
                    name,
                    lambda source=cm_source: fetch_comeet_jobs(client, source, notify=notify),
                ))
            elif ats == "smartrecruiters":
                sr_source = {
                    "company": name,
                    "id": cfg.get("id", name),
                    "assume_israel": cfg.get("assume_israel", True),
                }
                source_calls.append((
                    name,
                    lambda source=sr_source: fetch_smartrecruiters_jobs(client, source, notify=notify),
                ))
            elif ats == "ashby":
                ab_source = {
                    "company": name,
                    "board_name": cfg.get("board_name", name),
                    "assume_israel": cfg.get("assume_israel", True),
                }
                source_calls.append((
                    name,
                    lambda source=ab_source: fetch_ashby_jobs(client, source, notify=notify),
                ))
            elif ats in {"career_page", "website", "html"}:
                markers = cfg.get("path_markers")
                if isinstance(markers, str):
                    markers = [m.strip() for m in markers.split(",") if m.strip()]
                cp_source = {
                    "company": name,
                    "url": cfg.get("url", ""),
                    "path_markers": markers or ["/job/", "/jobs/", "/position/", "/careers/"],
                    "assume_israel": cfg.get("assume_israel", True),
                }
                source_calls.append((
                    name,
                    lambda source=cp_source: fetch_career_page_jobs(client, source, notify=notify),
                ))

        if selected_companies:
            source_calls = [
                source_call for source_call in source_calls
                if source_call[0].lower() in selected_companies
            ]

        total_sources = len(source_calls)
        slow_companies = {source["company"] for source in CAREER_PAGE_SOURCES} | {"iscar"}
        fast_semaphore = asyncio.Semaphore(6)
        slow_semaphore = asyncio.Semaphore(2)

        async def run_source(source_name: str, fetch_source):
            is_slow = source_name in slow_companies
            semaphore = slow_semaphore if is_slow else fast_semaphore
            timeout = 150 if source_name == "gav_systems" else (45 if is_slow else 35)
            async with semaphore:
                for attempt in range(2):
                    try:
                        jobs_list, source_sent_count = await asyncio.wait_for(fetch_source(), timeout=timeout)
                        return source_name, jobs_list, source_sent_count
                    except Exception as exc:
                        status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
                        retryable = isinstance(exc, (httpx.TimeoutException, httpx.TransportError, TimeoutError)) or status in {429, 502, 503, 504}
                        if attempt == 0 and retryable:
                            await asyncio.sleep(0.5)
                            continue
                        return source_name, [], 0, exc

        source_calls.sort(key=lambda item: item[0] in slow_companies)
        tasks = [asyncio.create_task(run_source(name, fetcher)) for name, fetcher in source_calls]
        for task in asyncio.as_completed(tasks):
            outcome = await task
            source_name, jobs_list, source_sent_count, *error = outcome
            if error:
                print(f"Error fetching jobs for {source_name}: {error[0]}")
            results.append(jobs_list)
            sent_count += source_sent_count
            if on_jobs_found and jobs_list:
                try:
                    enriched_batch = [extract_job_sections(job) for job in jobs_list]
                    on_jobs_found(source_name, enriched_batch)
                except Exception as exc:
                    print(f"Error in on_jobs_found for {source_name}: {exc}")
            report(source_name)

    jobs = []
    for result in results:
        if isinstance(result, Exception):
            print(f"Source fetch failed: {format_source_error(result)}")
            continue
        jobs.extend(extract_job_sections(job) for job in result)
    if return_stats:
        return jobs, sent_count
    return jobs


async def auto_detect_company_ats(
    client: httpx.AsyncClient,
    raw_url: str = "",
    name: str = "",
    config: dict | None = None,
) -> tuple[str, dict, str]:
    """
    Intelligently detect the recruitment platform (ATS) from a URL, HTML, or company name.
    Returns (ats_type, resolved_config, description_message).
    """
    url = str(raw_url or (config or {}).get("url") or (config or {}).get("base_url") or "").strip()
    clean_name = str(name).strip()
    name_slug = re.sub(r"[^a-zA-Z0-9]+", "", clean_name).lower()
    cfg = dict(config or {})

    # 1. Direct URL regex checks
    if "greenhouse.io" in url.lower():
        match = re.search(r"greenhouse\.io/(?:v1/boards/|embed/job_board\?for=)?([^/?#]+)", url, re.I)
        token = match.group(1) if match else (name_slug or "company")
        return "greenhouse", {"board_token": token}, f"Detected Greenhouse board '{token}'"

    if "myworkdayjobs.com" in url.lower() or "myworkdaysite.com" in url.lower():
        if "/wday/cxs/" in url and url.endswith("/jobs"):
            base_url = url
        else:
            m = re.search(r"https?://([^/]+)/([^/]+)/([^/?#]+)", url)
            if m:
                base_url = f"https://{m.group(1)}/wday/cxs/{m.group(2)}/{m.group(3)}/jobs"
            else:
                base_url = url
        return "workday", {"base_url": base_url, "search_text": cfg.get("search_text", "Israel")}, "Detected Workday CXS portal"

    if "smartrecruiters.com" in url.lower():
        match = re.search(r"smartrecruiters\.com/(?:v1/companies/)?([^/?#]+)", url, re.I)
        token = match.group(1) if match else (name_slug or clean_name)
        return "smartrecruiters", {"id": token, "assume_israel": True}, f"Detected SmartRecruiters ID '{token}'"

    if "ashbyhq.com" in url.lower():
        match = re.search(r"ashbyhq\.com/(?:posting-api/job-board/)?([^/?#]+)", url, re.I)
        token = match.group(1) if match else (name_slug or clean_name)
        return "ashby", {"board_name": token, "assume_israel": True}, f"Detected Ashby board '{token}'"

    if "comeet.com" in url.lower() or "comeet.co" in url.lower():
        match = re.search(r"comeet\.(?:com|co)/jobs/[^/]+/([^/?#]+)", url, re.I)
        uid = match.group(1) if match else (cfg.get("uid") or "")
        return "comeet", {"uid": uid, "token": cfg.get("token", ""), "assume_israel": True}, "Detected Comeet company"

    # 2. If URL is given, perform HTTP GET to check for redirects, embedded iframes, or JS widgets
    if url.startswith("http"):
        try:
            resp = await client.get(url, follow_redirects=True, timeout=12)
            final_url = str(resp.url)
            body = resp.text

            # Check final redirected URL
            if "greenhouse.io" in final_url.lower():
                match = re.search(r"greenhouse\.io/(?:v1/boards/|embed/job_board\?for=)?([^/?#]+)", final_url, re.I)
                token = match.group(1) if match else (name_slug or "company")
                return "greenhouse", {"board_token": token}, f"Detected Greenhouse via redirect to '{token}'"

            if "myworkdayjobs.com" in final_url.lower():
                m = re.search(r"https?://([^/]+)/([^/]+)/([^/?#]+)", final_url)
                base_url = f"https://{m.group(1)}/wday/cxs/{m.group(2)}/{m.group(3)}/jobs" if m else final_url
                return "workday", {"base_url": base_url, "search_text": cfg.get("search_text", "Israel")}, "Detected Workday via redirect"

            if "smartrecruiters.com" in final_url.lower():
                match = re.search(r"smartrecruiters\.com/([^/?#]+)", final_url, re.I)
                token = match.group(1) if match else (name_slug or clean_name)
                return "smartrecruiters", {"id": token, "assume_israel": True}, "Detected SmartRecruiters via redirect"

            if "ashbyhq.com" in final_url.lower():
                match = re.search(r"ashbyhq\.com/([^/?#]+)", final_url, re.I)
                token = match.group(1) if match else (name_slug or clean_name)
                return "ashby", {"board_name": token, "assume_israel": True}, "Detected Ashby via redirect"

            # Check HTML page source for embedded widgets
            gh_match = re.search(r"boards\.greenhouse\.io/(?:embed/job_board\?for=|v1/boards/|)([a-zA-Z0-9_\-]+)", body, re.I)
            if gh_match:
                return "greenhouse", {"board_token": gh_match.group(1)}, f"Found Greenhouse embedded board '{gh_match.group(1)}'"

            sr_match = re.search(r"jobs\.smartrecruiters\.com/([a-zA-Z0-9_\-]+)", body, re.I)
            if sr_match:
                return "smartrecruiters", {"id": sr_match.group(1), "assume_israel": True}, f"Found SmartRecruiters widget '{sr_match.group(1)}'"

            ashby_match = re.search(r"jobs\.ashbyhq\.com/([a-zA-Z0-9_\-]+)", body, re.I)
            if ashby_match:
                return "ashby", {"board_name": ashby_match.group(1), "assume_israel": True}, f"Found Ashby widget '{ashby_match.group(1)}'"

            wd_match = re.search(r"https?://([a-zA-Z0-9_\.\-]+\.myworkdayjobs\.com/[^\"'\s<>]+)", body, re.I)
            if wd_match:
                raw_wd = wd_match.group(1)
                m = re.search(r"https?://([^/]+)/([^/]+)/([^/?#]+)", raw_wd)
                base_url = f"https://{m.group(1)}/wday/cxs/{m.group(2)}/{m.group(3)}/jobs" if m else raw_wd
                return "workday", {"base_url": base_url, "search_text": cfg.get("search_text", "Israel")}, "Found Workday link embedded in careers page"

            # Check Comeet widgets in HTML
            cm_match = re.search(r"data-company-uid=[\"']([^\"']+)[\"']", body, re.I)
            if cm_match:
                return "comeet", {"uid": cm_match.group(1), "token": "", "assume_israel": True}, f"Found Comeet widget UID '{cm_match.group(1)}'"

            # Fallback to career page scraper with this URL
            markers = cfg.get("path_markers")
            if isinstance(markers, str):
                markers = [m.strip() for m in markers.split(",") if m.strip()]
            return "career_page", {"url": final_url, "path_markers": markers or ["/job/", "/jobs/", "/position/", "/careers/"], "assume_israel": True}, f"Direct Career Page scraper ({final_url})"

        except Exception:
            pass

    # 3. If only name was provided, probe Greenhouse / Ashby APIs
    if name_slug:
        try:
            gh_probe = await client.get(f"https://boards-api.greenhouse.io/v1/boards/{name_slug}/jobs", timeout=6)
            if gh_probe.status_code == 200:
                return "greenhouse", {"board_token": name_slug}, f"Auto-detected active Greenhouse board '{name_slug}'"
        except Exception:
            pass

        try:
            ashby_probe = await client.get(f"https://api.ashbyhq.com/posting-api/job-board/{name_slug}", timeout=6)
            if ashby_probe.status_code == 200:
                return "ashby", {"board_name": name_slug, "assume_israel": True}, f"Auto-detected active Ashby board '{name_slug}'"
        except Exception:
            pass

    # Default fallback
    target_url = url if url.startswith("http") else (f"https://www.{name_slug}.com/careers" if name_slug else "")
    return "career_page", {"url": target_url, "path_markers": ["/job/", "/jobs/", "/position/", "/careers/"], "assume_israel": True}, "Configured as Standard Career Page"


async def test_company_fetcher(ats_type: str, name: str, config: dict) -> tuple[list[dict], str, str, str, dict]:
    """
    Test fetching jobs for a company configuration and return:
    (jobs_list, error_message, detected_ats, detected_message, resolved_config).
    """
    ats = str(ats_type).strip().lower()
    clean_name = str(name).strip() or "TestCompany"
    cfg = dict(config or {})
    detected_msg = ""

    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            if ats in {"auto", "unknown", "detect", ""}:
                raw_url = cfg.get("url") or cfg.get("base_url") or ""
                ats, cfg, detected_msg = await auto_detect_company_ats(client, raw_url=raw_url, name=clean_name, config=cfg)

            if ats == "greenhouse":
                token = str(cfg.get("board_token") or clean_name).strip()
                jobs, _ = await fetch_greenhouse_jobs(client, token, notify=False, company_name=clean_name)
            elif ats == "workday":
                wd_source = {
                    "company": clean_name,
                    "base_url": cfg.get("base_url", ""),
                    "payload": cfg.get("payload") or {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": cfg.get("search_text", "Israel")},
                }
                jobs, _ = await fetch_workday_jobs(client, wd_source, notify=False)
            elif ats == "comeet":
                cm_source = {
                    "company": clean_name,
                    "uid": cfg.get("uid", ""),
                    "token": cfg.get("token", ""),
                    "assume_israel": cfg.get("assume_israel", True),
                }
                jobs, _ = await fetch_comeet_jobs(client, cm_source, notify=False)
            elif ats == "smartrecruiters":
                sr_source = {
                    "company": clean_name,
                    "id": cfg.get("id", clean_name),
                    "assume_israel": cfg.get("assume_israel", True),
                }
                jobs, _ = await fetch_smartrecruiters_jobs(client, sr_source, notify=False)
            elif ats == "ashby":
                ab_source = {
                    "company": clean_name,
                    "board_name": cfg.get("board_name", clean_name),
                    "assume_israel": cfg.get("assume_israel", True),
                }
                jobs, _ = await fetch_ashby_jobs(client, ab_source, notify=False)
            elif ats in {"career_page", "website", "html"}:
                markers = cfg.get("path_markers")
                if isinstance(markers, str):
                    markers = [m.strip() for m in markers.split(",") if m.strip()]
                cp_source = {
                    "company": clean_name,
                    "url": cfg.get("url", ""),
                    "path_markers": markers or ["/job/", "/jobs/", "/position/", "/careers/"],
                    "assume_israel": cfg.get("assume_israel", True),
                }
                jobs, _ = await fetch_career_page_jobs(client, cp_source, notify=False)
            else:
                return [], f"Unsupported ATS type: {ats_type}", ats, detected_msg, cfg

            enriched = [extract_job_sections(j) for j in jobs]
            return enriched, "", ats, detected_msg or f"Platform: {ats.capitalize()}", cfg
    except Exception as exc:
        return [], str(exc), ats, detected_msg, cfg


