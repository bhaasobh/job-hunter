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
