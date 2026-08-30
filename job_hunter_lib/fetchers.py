"""Fetching functions for various job boards."""

import asyncio
import httpx
import html
import json
import re
from contextvars import ContextVar
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup

from job_hunter_lib.config import ISRAEL_LOCATION_KEYWORDS
from job_hunter_lib.telegram_client import send_telegram_message, get_job_keyboard, format_job_message
from job_hunter_lib.utils import trim_text, generate_job_id

TITLE_EXCLUDED_KEYWORDS = [
    "senior",
    "manager",
    "staff",
    "student",
    "lead",
    "principal",
    "head",
    "director",
    "vp",
    "vice",
    "chief",
    "architect"
]
ACTIVE_EXCLUDED_KEYWORDS = ContextVar(
    "active_excluded_keywords",
    default=tuple(TITLE_EXCLUDED_KEYWORDS),
)

def format_source_error(exc: Exception) -> str:
    """Return a compact error description for failed source fetches."""
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        host = urlparse(str(exc.request.url)).netloc
        return f"{status} from {host}"
    if isinstance(exc, httpx.HTTPError):
        return f"{type(exc).__name__}: {exc}"
    return f"{type(exc).__name__}: {exc}"

def matches_preferences(job: dict) -> bool:
    title = str(job.get("title") or "").strip().lower()
    url = str(job.get("url") or "").strip().lower()
    if not title or title == "none" or title == "untitled role" or title.startswith("image "):
        return False
    if url and (url == "#" or any(url.endswith(ext) for ext in (".svg", ".png", ".jpg", ".jpeg", ".gif", ".webp"))):
        return False
    if any(keyword in title for keyword in ACTIVE_EXCLUDED_KEYWORDS.get()):
        return False
    return True


async def send_jobs_without_status(jobs: list[dict]) -> int:
    """Send only jobs that do not yet have a saved response status."""
    if not jobs:
        return 0

    # Import lazily so read-only users such as the web interface do not need a
    # working MongoDB connection merely to import the job fetchers.
    from job_hunter_lib.database import save_job_to_db

    print(f"Checking {len(jobs)} jobs for missing response status...")
    sent_count = 0
    for job in jobs:
        should_send = save_job_to_db(job)
        if not should_send:
            continue

        message = format_job_message(job)
        keyboard = get_job_keyboard(job["job_id"])
        if await send_telegram_message(message, reply_markup=keyboard):
            sent_count += 1
    return sent_count

async def fetch_greenhouse_jobs(
    client: httpx.AsyncClient,
    board_token: str,
    notify: bool = True,
    company_name: str | None = None,
) -> tuple[list[dict], int]:
    company = company_name or board_token
    print(f"Fetching Greenhouse jobs for {board_token}...")
    response = await client.get(
        f"https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs",
        params={"content": "true"},
    )
    response.raise_for_status()
    data = response.json()
    
    jobs = []
    for item in data.get("jobs", []):
        location = (item.get("location") or {}).get("name", "Not specified")
        offices = item.get("offices") or []
        office_locations = ", ".join(
            office.get("location", "")
            for office in offices
            if isinstance(office, dict) and office.get("location")
        )
        location_text = office_locations or location
        
        is_israel_job = any(keyword in location_text.lower() for keyword in ISRAEL_LOCATION_KEYWORDS)
        if not is_israel_job:
            continue

        jobs.append(
            {
                "title": item.get("title", "N/A"),
                "company": company,
                "location": location_text or "Not specified",
                "salary": "Not specified",
                "description": trim_text(html.unescape(item.get("content", ""))),
                "job_type": "Full-time",
                "tags": "",
                "url": item.get("absolute_url", ""),
                "posted": item.get("updated_at", "Recently"),
                "remote": "remote" in location_text.lower(),
                "source": f"Greenhouse:{company}",
            }
        )
        # Add job_id for tracking
        jobs[-1]["job_id"] = generate_job_id(jobs[-1])
    print(f'jobs from Greenhouse before filtering:{board_token}: {len(jobs)}')
    filtered_jobs = [job for job in jobs if matches_preferences(job)]
    print(f'jobs from Greenhouse after filtering:{board_token}: {len(filtered_jobs)}')
    sent_count = await send_jobs_without_status(filtered_jobs) if notify else 0
    return filtered_jobs, sent_count

async def fetch_qualcomm_jobs(client: httpx.AsyncClient, source: dict, notify: bool = True) -> tuple[list[dict], int]:
    print(f"Fetching Qualcomm jobs for {source['company']}...")
    company = source["company"]
    base_url = source["base_url"]
    jobs = []
    start = 0
    page_size = 10

    while True:
        parsed_url = urlparse(base_url)
        query_params = dict(parse_qsl(parsed_url.query, keep_blank_values=True))
        query_params["start"] = str(start)
        page_url = urlunparse(parsed_url._replace(query=urlencode(query_params)))

        try:
            response = await client.get(page_url, timeout=30)
            response.raise_for_status()
        except Exception as exc:
            print(f"Source fetch failed: {exc} from {company}")
            return jobs, 0

        data = response.json()
        positions = data.get("data", {}).get("positions", [])
        if not positions:
            break

        for job in positions:
            jobs.append(
                {
                    "title": job.get("name"),
                    "company": company,
                    "location": ", ".join(job.get("locations", [])),
                    "salary": "Not specified",
                    "description": trim_text(job.get("description", "")),
                    "job_type": "Full-time",
                    "tags": ", ".join(job.get("jobCategory", []) if isinstance(job.get("jobCategory"), list) else []),
                    "url": f"https://careers.qualcomm.com{job.get('positionUrl')}",
                    "posted": job.get("postedDate", "Recently"),
                    "remote": "remote" in ", ".join(job.get("locations", [])).lower(),
                    "source": f"Qualcomm:{company}",
                }
            )
            # Add job_id for tracking
            jobs[-1]["job_id"] = generate_job_id(jobs[-1])

        if len(positions) < page_size:
            break
        start += len(positions)
    filtered_jobs = [job for job in jobs if matches_preferences(job)]
    print(f'jobs from Qualcomm after filtering:{company}: {len(filtered_jobs)}')
    sent_count = await send_jobs_without_status(filtered_jobs) if notify else 0
    return filtered_jobs, sent_count

async def fetch_nvidia_jobs(client: httpx.AsyncClient, source: dict, notify: bool = True) -> tuple[list[dict], int]:
    print(f"Fetching Nvidia jobs for {source['company']}...")
    company = source["company"]
    url = source["base_url"]
    parsed_url = urlparse(url)
    base_host = f"{parsed_url.scheme}://{parsed_url.netloc}"
    path_parts = [part for part in parsed_url.path.split("/") if part]
    site_name = path_parts[3] if len(path_parts) > 3 else "NVIDIAExternalCareerSite"

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0"
    }

    limit = 20
    offset = 0
    jobs = []

    while True:
        payload = {
            "limit": limit,
            "offset": offset,
            "searchText": "",
            "appliedFacets": {
                "locationHierarchy1": ["2fcb99c455831013ea52bbe14cf9326c"]  # Israel
            }
        }

        try:
            r = await client.post(url, json=payload, headers=headers, timeout=30)
            r.raise_for_status()
        except Exception as e:
            print(f"Source fetch failed: {e} from {company}")
            break

        data = r.json()
        postings = data.get("jobPostings", [])

        if not postings:
            break

        for job in postings:
            location = job.get("locationsText", "")
            external_path = str(job.get("externalPath", "")).strip()
            job_slug = external_path.rsplit("/", 1)[-1] if external_path else ""
            jobs.append({
                "title": job.get("title"),
                "company": company,
                "location": location,
                "salary": "Not specified",
                "description": trim_text(job.get("description", "")),
                "job_type": "Full-time",
                "tags": "",
                "url": f"{base_host}/en-US/{site_name}/job/{job_slug}" if job_slug else base_host,
                "posted": job.get("postedDate", "Recently"),
                "remote": "remote" in location.lower(),
                "source": f"Nvidia:{company}",
            })
            # Add job_id for tracking
            jobs[-1]["job_id"] = generate_job_id(jobs[-1])
        if len(postings) < limit:
            break
        offset += limit
    filtered_jobs = [job for job in jobs if matches_preferences(job)]
    print(f'jobs from Nvidia after filtering:{company}: {len(filtered_jobs)}')
    sent_count = await send_jobs_without_status(filtered_jobs) if notify else 0
    return filtered_jobs, sent_count

async def fetch_workday_jobs(client: httpx.AsyncClient, source: dict, notify: bool = True) -> tuple[list[dict], int]:
    company = source["company"]
    print(f"Fetching Workday jobs for {company}...")
    url = source["base_url"]
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0",
    }

    base_payload = source.get(
        "payload",
        {
            "appliedFacets": {},
            "limit": 20,
            "offset": 0,
            "searchText": "",
        },
    )
    limit = int(base_payload.get("limit", 20))
    offset = int(base_payload.get("offset", 0))
    jobs = []
    seen_paths = set()
    max_pages = int(source.get("max_pages", 10))
    page_count = 0

    while True:
        page_count += 1
        if page_count > max_pages:
            print(f"Stopping {company} after {max_pages} pages.")
            break

        payload = dict(base_payload)
        payload["offset"] = offset

        try:
            response = await client.post(url, json=payload, headers=headers, timeout=30)
            response.raise_for_status()
        except Exception as exc:
            print(f"Source fetch failed: {exc} from {company}")
            return jobs, 0

        data = response.json()
        postings = data.get("jobPostings", [])
        if not postings:
            break

        new_paths = []
        for job in postings:
            external_path = job.get("externalPath")
            if external_path and external_path not in seen_paths:
                new_paths.append(external_path)

        if not new_paths and seen_paths:
            break

        for job in postings:
            external_path = job.get("externalPath")
            if external_path and external_path in seen_paths:
                continue
            if external_path:
                seen_paths.add(external_path)

            base_host = url.split('/wday')[0]
            external_path = job.get('externalPath', '')
            
            if company in {"hpe", "marvell", "applied_materials", "kla", "cadence"}:
                parts = url.split('/')
                site_name = parts[6] if len(parts) > 6 else "Jobsathpe"
                job_url = f"{base_host}/{site_name}{external_path}"
            elif company in ["intel", "cisco", "dell"]:
                # Construct modern URL: /en-US/SITE/[job|details]/SLUG?locations=...
                # SITE is usually the 7th element in the wday/cxs/... URL
                parts = url.split('/')
                site_name = parts[6] if len(parts) > 6 else "External"
                job_slug = external_path.rsplit('/', 1)[-1]
                
                path_segment = "details" if company == "intel" else "job"
                job_url = f"{base_host}/en-US/{site_name}/{path_segment}/{job_slug}"
                
                # Append locations if present in search payload
                locations = source.get("payload", {}).get("appliedFacets", {}).get("locations", [])
                if locations:
                    job_url += "?" + urlencode([("locations", l) for l in locations], doseq=True)
            else:
                job_url = f"{base_host}{external_path}"

            jobs.append(
                {
                    "title": job.get("title"),
                    "company": company,
                    "location": job.get("locationsText", "Not specified"),
                    "salary": "Not specified",
                    "description": trim_text(job.get("description", "")),
                    "job_type": "Full-time",
                    "tags": ", ".join(job.get("bulletFields") or []),
                    "url": job_url,
                    "posted": job.get("postedOn", "Recently"),
                    "remote": "remote" in str(job.get("locationsText", "")).lower(),
                    "source": f"Workday:{company}",
                }
            )
            # Add job_id for tracking
            jobs[-1]["job_id"] = generate_job_id(jobs[-1])

        if len(postings) < limit:
            break
        offset += len(postings)
    print(f"Fetched {len(jobs)} jobs from {company} before filtering.")
    filtered_jobs = [job for job in jobs if matches_preferences(job)]
    print(f'jobs from Workday after filtering:{company}: {len(filtered_jobs)}')
    sent_count = await send_jobs_without_status(filtered_jobs) if notify else 0
    return filtered_jobs, sent_count


async def fetch_career_page_jobs(client: httpx.AsyncClient, source: dict, notify: bool = True) -> tuple[list[dict], int]:
    """Extract Israel job-detail links from a company's official careers page."""
    company = source["company"]
    page_url = source["url"]
    proxy_url = source.get("proxy_url")
    print(f"Fetching official careers page for {company}...")

    if source.get("kind") == "tesnet":
        try:
            response = await client.get(
                page_url,
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=30,
            )
            response.raise_for_status()
        except Exception as exc:
            print(f"Source fetch failed: {exc} from {company}")
            return [], 0

        jobs = []
        soup = BeautifulSoup(response.text, "html.parser")
        for card in soup.select(".job-list .item"):
            title_node = card.select_one("h3.title")
            apply_link = card.select_one("a.popup-job[data-job-code]")
            if title_node is None or apply_link is None:
                continue

            share_link = card.select_one('a[href*="facebook.com/sharer"]')
            share_params = dict(parse_qsl(urlparse(str(share_link.get("href", ""))).query)) if share_link else {}
            job_url = share_params.get("u") or page_url
            job_code = str(apply_link.get("data-job-code") or "").strip()
            location_node = card.select_one(".locations")
            description_node = card.select_one(".description")
            title = title_node.get_text(" ", strip=True)
            location = location_node.get_text(" ", strip=True).removeprefix("איזור:").strip() if location_node else "Israel"
            description = description_node.get_text(" ", strip=True) if description_node else ""

            job = {
                "title": title,
                "company": company,
                "location": location or "Israel",
                "salary": "Not specified",
                "description": trim_text(description),
                "requirements": trim_text(description, 3000),
                "responsibilities": "",
                "job_type": "Full-time",
                "tags": "",
                "url": job_url,
                "posted": "Recently",
                "remote": "remote" in description.lower() or "היברידי" in description,
                "source": "Tesnet Careers",
                "job_id": f"tesnet-{job_code}" if job_code else generate_job_id({"url": job_url}),
            }
            jobs.append(job)

        filtered_jobs = [job for job in jobs if matches_preferences(job)]
        print(f"jobs from Tesnet after filtering:{company}: {len(filtered_jobs)}")
        sent_count = await send_jobs_without_status(filtered_jobs) if notify else 0
        return filtered_jobs, sent_count

    if source.get("kind") == "sqlink":
        try:
            response = await client.get(
                page_url,
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=30,
            )
            response.raise_for_status()
        except Exception as exc:
            print(f"Source fetch failed: {exc} from {company}")
            return [], 0

        jobs = []
        soup = BeautifulSoup(response.text, "html.parser")
        for article in soup.select("#searchResultsList .article[id]"):
            link = article.select_one("a[href]")
            title_node = link.select_one("h3") if link else None
            if link is None or title_node is None:
                continue

            title = title_node.get_text(" ", strip=True)
            href = urljoin(page_url, str(link.get("href", "")))
            job_number = article.get("id", "").removeprefix("id-").strip()
            description_node = article.select_one("section.description:not(.number)")
            requirements_node = article.select_one("section.requirements")
            description = description_node.get_text(" ", strip=True) if description_node else ""
            requirements = requirements_node.get_text(" ", strip=True) if requirements_node else ""
            context = f"{title} {description} {requirements}"

            job = {
                "title": title,
                "company": company,
                "location": "Israel",
                "salary": "Not specified",
                "description": trim_text(description),
                "requirements": trim_text(requirements, 3000),
                "responsibilities": "",
                "job_type": "Full-time",
                "tags": "",
                "url": href,
                "posted": "Recently",
                "remote": "remote" in context.lower() or "היברידי" in context,
                "source": "SQLink Careers",
                "job_id": f"sqlink-{job_number}" if job_number else generate_job_id({"url": href}),
            }
            jobs.append(job)

        filtered_jobs = [job for job in jobs if matches_preferences(job)]
        print(f"jobs from SQLink after filtering:{company}: {len(filtered_jobs)}")
        sent_count = await send_jobs_without_status(filtered_jobs) if notify else 0
        return filtered_jobs, sent_count

    if source.get("kind") == "recruitee":
        try:
            response = await client.get(
                source["api_url"],
                headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"},
                timeout=30,
            )
            response.raise_for_status()
            items = response.json().get("offers", [])
        except Exception as exc:
            print(f"Source fetch failed: {exc} from {company}")
            return [], 0

        jobs = []
        for item in items:
            if not isinstance(item, dict) or str(item.get("country_code") or "").upper() != "IL":
                continue
            description = BeautifulSoup(
                html.unescape(str(item.get("description") or "")), "html.parser"
            ).get_text(" ", strip=True)
            requirements = BeautifulSoup(
                html.unescape(str(item.get("requirements") or "")), "html.parser"
            ).get_text(" ", strip=True)
            location = str(item.get("location") or item.get("city") or "Israel").strip()
            employment_code = str(item.get("employment_type_code") or "").lower()
            if "parttime" in employment_code:
                job_type = "Part-time"
            elif "contract" in employment_code or "temporary" in employment_code:
                job_type = "Contract"
            else:
                job_type = "Full-time"
            offer_id = str(item.get("id") or item.get("slug") or "").strip()
            job = {
                "title": str(item.get("title") or "N/A").strip(),
                "company": company,
                "location": location,
                "salary": "Not specified",
                "description": trim_text(f"{description} {requirements}".strip()),
                "requirements": trim_text(requirements, 3000),
                "responsibilities": trim_text(description, 3000),
                "job_type": job_type,
                "tags": str(item.get("department") or ""),
                "url": str(item.get("careers_url") or page_url),
                "posted": str(item.get("created_at") or item.get("updated_at") or "Recently")[:10],
                "remote": "remote" in location.lower(),
                "source": f"Recruitee:{company}",
                "job_id": f"recruitee-{company}-{offer_id}" if offer_id else generate_job_id(item),
            }
            jobs.append(job)

        filtered_jobs = [job for job in jobs if matches_preferences(job)]
        print(f"jobs from Recruitee after filtering:{company}: {len(filtered_jobs)}")
        sent_count = await send_jobs_without_status(filtered_jobs) if notify else 0
        return filtered_jobs, sent_count

    if source.get("kind") == "strauss":
        try:
            response = await client.get(
                page_url,
                params={"user_page": 1, "freeText": ""},
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=40,
            )
            response.raise_for_status()
        except Exception as exc:
            print(f"Source fetch failed: {exc} from {company}")
            return [], 0

        jobs = []
        soup = BeautifulSoup(response.text, "html.parser")
        for card in soup.select(".jobs_list_order_wrap[data-id]"):
            job_number = str(card.get("data-id") or "").strip()
            title_node = card.select_one(".jobs_list_order_title")
            if not job_number or title_node is None:
                continue
            title = title_node.get_text(" ", strip=True)
            location_node = card.select_one(".details_item.location .det_item")
            location = location_node.get_text(" ", strip=True) if location_node else "Israel"
            if "israel" not in location.lower():
                location = f"{location}, Israel"
            category_node = card.select_one(".details_item.business_unit .det_item")
            date_nodes = card.select(".details_item.date_published .det_item")
            posted = date_nodes[-1].get_text(" ", strip=True) if date_nodes else "Recently"
            detail = card.select_one(".jobs_list_order_desc")
            description = detail.get_text(" ", strip=True) if detail else card.get_text(" ", strip=True)
            responsibilities = ""
            requirements = ""
            if detail:
                for heading in detail.select("h3"):
                    heading_text = heading.get_text(" ", strip=True)
                    values = []
                    sibling = heading.find_next_sibling()
                    while sibling is not None and sibling.name != "h3":
                        value = sibling.get_text(" ", strip=True)
                        if value:
                            values.append(value)
                        sibling = sibling.find_next_sibling()
                    section = " ".join(values)
                    if "מה כולל התפקיד" in heading_text:
                        responsibilities = section
                    elif "מה חשוב להביא" in heading_text:
                        requirements = section

            job = {
                "title": title,
                "company": company,
                "location": location,
                "salary": "Not specified",
                "description": trim_text(description),
                "requirements": trim_text(requirements, 3000),
                "responsibilities": trim_text(responsibilities, 3000),
                "job_type": "Full-time",
                "tags": category_node.get_text(" ", strip=True) if category_node else "",
                "url": f"{page_url}?jobid={job_number}",
                "posted": posted,
                "remote": "remote" in description.lower() or "היברידי" in description,
                "source": "Strauss Group Careers",
                "job_id": f"strauss-{job_number}",
            }
            jobs.append(job)

        filtered_jobs = [job for job in jobs if matches_preferences(job)]
        print(f"jobs from official careers after filtering:{company}: {len(filtered_jobs)}")
        sent_count = await send_jobs_without_status(filtered_jobs) if notify else 0
        return filtered_jobs, sent_count

    if source.get("kind") == "successfactors":
        try:
            response = await client.get(
                page_url,
                params=source.get("search_params", {"locationsearch": "Israel"}),
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=30,
            )
            response.raise_for_status()
        except Exception as exc:
            print(f"Source fetch failed: {exc} from {company}")
            return [], 0

        jobs = []
        seen_urls = set()
        soup = BeautifulSoup(response.text, "html.parser")
        for row in soup.select("tr.data-row"):
            link = row.select_one("a.jobTitle-link[href]")
            if link is None:
                continue
            href = urljoin(page_url, str(link.get("href", "")))
            if href in seen_urls:
                continue
            seen_urls.add(href)
            title = link.get_text(" ", strip=True)
            location_node = row.select_one(".jobLocation")
            location = location_node.get_text(" ", strip=True) if location_node else "Israel"
            department_node = row.select_one(".jobDepartment")
            facility_node = row.select_one(".jobFacility")
            job_number_match = re.search(r"/(\d+)/?$", urlparse(href).path)
            job_number = job_number_match.group(1) if job_number_match else generate_job_id({"url": href})
            description = title
            try:
                detail_response = await client.get(href, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
                detail_response.raise_for_status()
                detail_soup = BeautifulSoup(detail_response.text, "html.parser")
                detail_node = detail_soup.select_one(".jobdescription")
                if detail_node:
                    description = detail_node.get_text(" ", strip=True)
            except Exception as exc:
                print(f"Job detail fetch failed: {exc} from {company}")

            job = {
                "title": title,
                "company": company,
                "location": location,
                "salary": "Not specified",
                "description": trim_text(description),
                "job_type": "Full-time",
                "tags": ", ".join(filter(None, [
                    department_node.get_text(" ", strip=True) if department_node else "",
                    facility_node.get_text(" ", strip=True) if facility_node else "",
                ])),
                "url": href,
                "posted": "Recently",
                "remote": "remote" in location.lower() or "remote" in description.lower(),
                "source": "Teradyne Careers",
                "job_id": f"teradyne-{job_number}",
            }
            jobs.append(job)

        filtered_jobs = [job for job in jobs if matches_preferences(job)]
        print(f"jobs from official careers after filtering:{company}: {len(filtered_jobs)}")
        sent_count = await send_jobs_without_status(filtered_jobs) if notify else 0
        return filtered_jobs, sent_count

    if source.get("kind") == "gav_wp":
        items = []
        try:
            for page in range(1, 10):
                response = await client.get(
                    source["api_url"],
                    params={"per_page": 100, "page": page, "status": "publish"},
                    headers={"User-Agent": "Mozilla/5.0"},
                    timeout=30,
                )
                if response.status_code == 400 and page > 1:
                    break
                response.raise_for_status()
                page_items = response.json()
                items.extend(page_items)
                total_pages = int(response.headers.get("x-wp-totalpages") or 1)
                if page >= total_pages:
                    break
        except Exception as exc:
            print(f"Source fetch failed: {exc} from {company}")
            return [], 0

        detail_semaphore = asyncio.Semaphore(8)

        async def build_job(item: dict) -> dict:
            title = html.unescape(str((item.get("title") or {}).get("rendered") or "N/A"))
            href = str(item.get("link") or page_url)
            location = "Israel"
            description = title
            requirements = ""
            wp_id = str(item.get("id") or "").strip()
            job_number = wp_id or generate_job_id({"url": href})
            posted = str(item.get("date") or "Recently")[:10]
            async with detail_semaphore:
                try:
                    detail_response = await client.get(href, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
                    detail_response.raise_for_status()
                    detail_soup = BeautifulSoup(detail_response.text, "html.parser")
                    labels = detail_soup.find(string=lambda value: value and "מיקום המשרה:" in value)
                    container = labels.parent.parent.parent.parent if labels else None
                    detail_text = container.get_text(" ", strip=True) if container else ""
                    match = re.search(
                        r"מיקום המשרה:\s*(.*?)\s*תיאור המשרה:\s*(.*?)\s*דרישות המשרה:\s*(.*?)\s*מס['׳]? משרה:\s*(\d+)\s*תאריך פרסום:\s*([^\s]+)",
                        detail_text,
                        re.S,
                    )
                    if match:
                        location, role_description, requirements, _internal_num, posted = match.groups()
                        description = f"{role_description} {requirements}".strip()
                except Exception as exc:
                    print(f"Job detail fetch failed: {exc} from {company}")
            return {
                "title": title,
                "company": company,
                "location": f"{location}, Israel" if "israel" not in location.lower() else location,
                "salary": "Not specified",
                "description": trim_text(description),
                "requirements": trim_text(requirements, 3000),
                "responsibilities": "",
                "job_type": "Full-time",
                "tags": "",
                "url": href,
                "posted": posted,
                "remote": "remote" in description.lower() or "מהבית" in description,
                "source": "GAV Systems Careers",
                "job_id": f"gav-{job_number}",
            }

        jobs = await asyncio.gather(*(build_job(item) for item in items))
        filtered_jobs = [job for job in jobs if matches_preferences(job)]
        print(f"jobs from official careers after filtering:{company}: {len(filtered_jobs)}")
        sent_count = await send_jobs_without_status(filtered_jobs) if notify else 0
        return filtered_jobs, sent_count

    if source.get("kind") == "proceed":
        try:
            response = await client.post(
                source["api_url"],
                json={"token": source["api_token"]},
                headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"},
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()
            items = data if isinstance(data, list) else data.get("orders", [])
        except Exception as exc:
            print(f"Source fetch failed: {exc} from {company}")
            return [], 0

        jobs = []
        for item in items:
            order_id = str(item.get("order_id") or "").strip()
            title = str(item.get("description") or "").strip()
            if not order_id or not title:
                continue

            location_parts = []
            for value in (item.get("Order_place"), item.get("work_area")):
                value = str(value or "").strip()
                if value and value not in location_parts:
                    location_parts.append(value)
            location = ", ".join(location_parts) or "Israel"
            description = item.get("notes_text") or item.get("notes") or title
            tags = ", ".join(
                str(value).strip()
                for value in (item.get("category_name"), item.get("profession_name"))
                if value and str(value).strip()
            )
            job = {
                "title": title,
                "company": company,
                "location": location,
                "salary": "Not specified",
                "description": trim_text(html.unescape(str(description))),
                "job_type": item.get("order_def_job_scope1_desc") or "Full-time",
                "tags": tags,
                "url": f"{page_url.rstrip('/')}/page?order_id={order_id}",
                "posted": item.get("orderDate") or item.get("update_date") or "Recently",
                "remote": "remote" in location.lower() or "hybrid" in location.lower(),
                "source": "Proceed Careers",
                "job_id": f"proceed-{order_id}",
            }
            jobs.append(job)

        filtered_jobs = [job for job in jobs if matches_preferences(job)]
        print(f"jobs from official careers after filtering:{company}: {len(filtered_jobs)}")
        sent_count = await send_jobs_without_status(filtered_jobs) if notify else 0
        return filtered_jobs, sent_count

    if source.get("kind") == "ness":
        try:
            response = await client.get(
                source["api_url"],
                params={
                    "profId": "",
                    "areasId": "",
                    "freeText": "",
                    "isHot": "false",
                    "rows": 1000,
                    "page": 1,
                    "isToggle": "false",
                },
                headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"},
                timeout=30,
            )
            response.raise_for_status()
            items = response.json().get("allOrderDetailsList", [])
        except Exception as exc:
            print(f"Source fetch failed: {exc} from {company}")
            return [], 0

        jobs = []
        for item in items:
            job_number = str(item.get("index") or "").strip()
            if not job_number:
                continue
            location = str(item.get("posLocation") or "Israel").strip()
            job = {
                "title": str(item.get("title") or "N/A").strip(),
                "company": company,
                "location": location,
                "salary": "Not specified",
                "description": trim_text(html.unescape(str(item.get("posDescription") or ""))),
                "job_type": "Full-time",
                "tags": ", ".join(
                    value for value in (item.get("profName"), item.get("subProfName")) if value
                ),
                "url": f"https://www.ness-tech.co.il/careers/job/{job_number}",
                "posted": item.get("lastUpdated") or "Recently",
                "remote": "remote" in location.lower() or "hybrid" in location.lower(),
                "source": "Ness Technologies Careers",
                "job_id": f"ness-{job_number}",
            }
            jobs.append(job)

        filtered_jobs = [job for job in jobs if matches_preferences(job)]
        print(f"jobs from official careers after filtering:{company}: {len(filtered_jobs)}")
        sent_count = await send_jobs_without_status(filtered_jobs) if notify else 0
        return filtered_jobs, sent_count

    if source.get("kind") == "qualitest":
        jobs = []
        seen_urls = set()
        page_size = 25
        for start_row in range(0, 250, page_size):
            try:
                response = await client.get(
                    page_url,
                    params={
                        "q": "",
                        "locationsearch": "Israel",
                        "startrow": start_row,
                    },
                    headers={"User-Agent": "Mozilla/5.0"},
                    timeout=30,
                )
                response.raise_for_status()
            except Exception as exc:
                print(f"Source fetch failed: {exc} from {company}")
                return jobs, 0

            soup = BeautifulSoup(response.text, "html.parser")
            rows = soup.select("tr.data-row")
            if not rows:
                break

            new_jobs = 0
            for row in rows:
                link = row.select_one("a.jobTitle-link[href]")
                if link is None:
                    continue
                href = urljoin(page_url, str(link.get("href", "")))
                if href in seen_urls:
                    continue
                seen_urls.add(href)
                new_jobs += 1

                title = link.get_text(" ", strip=True)
                location_node = row.select_one(".jobDepartment") or row.select_one(".jobLocation")
                location = location_node.get_text(" ", strip=True) if location_node else "Israel"
                date_node = row.select_one(".jobDate")
                facility_node = row.select_one(".jobFacility")
                job_number = (
                    facility_node.get_text(" ", strip=True).lstrip("#")
                    if facility_node else ""
                )
                job = {
                    "title": title,
                    "company": company,
                    "location": f"{location}, Israel" if "israel" not in location.lower() else location,
                    "salary": "Not specified",
                    "description": title,
                    "job_type": "Full-time",
                    "tags": "Quality Engineering",
                    "url": href,
                    "posted": date_node.get_text(" ", strip=True) if date_node else "Recently",
                    "remote": "remote" in location.lower(),
                    "source": "Qualitest Careers",
                    "job_id": f"qualitest-{job_number}" if job_number else generate_job_id({"url": href}),
                }
                jobs.append(job)

            if len(rows) < page_size or not new_jobs:
                break

        filtered_jobs = [job for job in jobs if matches_preferences(job)]
        print(f"jobs from official careers after filtering:{company}: {len(filtered_jobs)}")
        sent_count = await send_jobs_without_status(filtered_jobs) if notify else 0
        return filtered_jobs, sent_count

    if source.get("kind") == "philips":
        jobs = []
        seen_ids = set()
        page_size = 10
        total_hits = page_size
        for offset in range(0, 500, page_size):
            if offset >= total_hits and offset > 0:
                break
            try:
                response = await client.get(
                    page_url,
                    params={"from": offset, "s": 1},
                    headers={"User-Agent": "Mozilla/5.0"},
                    timeout=30,
                )
                response.raise_for_status()
                match = re.search(
                    r"phApp\.ddo\s*=\s*(\{.*?\});\s*phApp\.",
                    response.text,
                    re.S,
                )
                if match is None:
                    raise ValueError("Philips careers data was not found in the page")
                result = json.loads(match.group(1)).get("eagerLoadRefineSearch", {})
                total_hits = int(result.get("totalHits") or 0)
                items = result.get("data", {}).get("jobs", [])
            except Exception as exc:
                print(f"Source fetch failed: {exc} from {company}")
                return jobs, 0

            if not items:
                break
            for item in items:
                job_number = str(item.get("jobId") or "").strip()
                if not job_number or job_number in seen_ids:
                    continue
                seen_ids.add(job_number)
                location = str(
                    item.get("cityStateCountry") or item.get("location") or "Israel"
                ).strip()
                apply_url = str(item.get("applyUrl") or "").strip()
                detail_url = re.sub(r"/apply(?:\?.*)?$", "", apply_url)
                job = {
                    "title": str(item.get("title") or "N/A").strip(),
                    "company": company,
                    "location": location,
                    "salary": "Not specified",
                    "description": trim_text(str(item.get("descriptionTeaser") or "")),
                    "job_type": item.get("type") or "Full-time",
                    "tags": item.get("category") or "",
                    "url": detail_url or page_url,
                    "posted": str(item.get("postedDate") or "Recently")[:10],
                    "remote": "remote" in location.lower() or "home based" in location.lower(),
                    "source": "Philips Careers",
                    "job_id": f"philips-{job_number}",
                }
                jobs.append(job)

        filtered_jobs = [job for job in jobs if matches_preferences(job)]
        print(f"jobs from official careers after filtering:{company}: {len(filtered_jobs)}")
        sent_count = await send_jobs_without_status(filtered_jobs) if notify else 0
        return filtered_jobs, sent_count

    if source.get("kind") == "siemens":
        try:
            response = await client.get(
                page_url,
                params={
                    "42385": "Israel",
                    "folderOffset": 0,
                    "folderRecordsPerPage": 100,
                },
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=30,
            )
            response.raise_for_status()
        except Exception as exc:
            print(f"Source fetch failed: {exc} from {company}")
            return [], 0

        jobs = []
        seen_urls = set()
        soup = BeautifulSoup(response.text, "html.parser")
        for card in soup.select("article.article--result"):
            country_node = card.select_one(".list-item-jobCountry")
            country = country_node.get_text(" ", strip=True) if country_node else ""
            if country.lower() != "israel":
                continue
            link = card.select_one('a.link[href*="/JobDetail/"]')
            if link is None:
                continue
            href = urljoin(page_url, str(link.get("href", "")))
            if href in seen_urls:
                continue
            seen_urls.add(href)

            location_node = card.select_one(".list-item-location")
            location = location_node.get_text(" ", strip=True) if location_node else "Israel"
            id_node = card.select_one(".list-item-jobId")
            id_text = id_node.get_text(" ", strip=True) if id_node else ""
            id_match = re.search(r"(\d+)", id_text)
            job_number = id_match.group(1) if id_match else href.rstrip("/").rsplit("/", 1)[-1]
            family_node = card.select_one(".list-item-family")
            title = link.get_text(" ", strip=True)
            job = {
                "title": title,
                "company": company,
                "location": location,
                "salary": "Not specified",
                "description": card.get_text(" ", strip=True),
                "job_type": "Full-time",
                "tags": family_node.get_text(" ", strip=True) if family_node else "",
                "url": href,
                "posted": "Recently",
                "remote": "remote" in location.lower(),
                "source": "Siemens Careers Marketplace",
                "job_id": f"siemens-{job_number}",
            }
            jobs.append(job)

        filtered_jobs = [job for job in jobs if matches_preferences(job)]
        print(f"jobs from official careers after filtering:{company}: {len(filtered_jobs)}")
        sent_count = await send_jobs_without_status(filtered_jobs) if notify else 0
        return filtered_jobs, sent_count

    try:
        response = await client.get(proxy_url or page_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
        response.raise_for_status()
    except Exception as exc:
        print(f"Source fetch failed: {exc} from {company}")
        return [], 0

    page_host = urlparse(page_url).netloc.removeprefix("www.")
    markers = tuple(source.get("path_markers") or ["/job/", "/jobs/", "/position/", "/positions/", "/pos/", "/opening/", "/openings/", "/career/", "/careers/", "/vacancy/", "/vacancies/"])
    jobs = []
    seen_urls = set()
    candidates = []
    if proxy_url:
        for match in re.finditer(r"\[([^\]]+)\]\((https?://[^)]+)\)", response.text):
            context = response.text[max(0, match.start() - 250):match.end() + 250]
            candidates.append((match.group(1).strip(), match.group(2), context, ""))
    else:
        soup = BeautifulSoup(response.text, "html.parser")
        for link in soup.select("a[href]"):
            heading = link.select_one("h1, h2, h3, h4, h5, h6, [class*='title'], [fs-list-field='title']")
            title_text = heading.get_text(" ", strip=True) if heading else link.get_text(" ", strip=True)
            loc_node = link.select_one("[fs-list-field='location'], [class*='location']")
            loc_text = loc_node.get_text(" ", strip=True) if loc_node else ""
            card = link.find_parent(["article", "li", "div", "tr"])
            context = card.get_text(" ", strip=True) if card else title_text
            candidates.append((
                title_text,
                urljoin(page_url, str(link.get("href", ""))),
                context,
                loc_text,
            ))

    for title, href, context, explicit_location in candidates:
        parsed = urlparse(href)
        if parsed.netloc.removeprefix("www.") != page_host:
            continue
        if any(parsed.path.lower().endswith(ext) for ext in (".svg", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".css", ".js", ".ico")):
            continue
        if not any(marker in parsed.path.lower() for marker in markers):
            continue

        if not title or len(title) < 3 or title.lower() in {"apply", "apply now", "read more", "view job", "learn more"} or title.lower().startswith("image "):
            continue
        
        full_text = f"{title} {explicit_location} {context}"
        location_match = re.search(
            r"\b(Israel|Tel Aviv|Haifa|Jerusalem|Herzliya|Petah Tikva|Ramat Gan|"
            r"Ra['’]?anana|Rehovot|Migdal Haemek|Hod Hasharon|Caesarea|Yokneam)\b",
            full_text,
            re.I,
        )
        if not location_match and not source.get("assume_israel"):
            continue

        if href in seen_urls:
            continue
        seen_urls.add(href)
        
        if location_match:
            resolved_location = explicit_location if (explicit_location and "israel" in explicit_location.lower()) else f"{location_match.group(1)}"
        else:
            resolved_location = explicit_location or "Israel"

        job = {
            "title": title,
            "company": company,
            "location": resolved_location,
            "salary": "Not specified",
            "description": trim_text(context),
            "job_type": "Full-time",
            "tags": "",
            "url": href,
            "posted": "Recently",
            "remote": "remote" in context.lower(),
            "source": f"Official Careers:{company}",
        }
        job["job_id"] = generate_job_id(job)
        jobs.append(job)

    filtered_jobs = [job for job in jobs if matches_preferences(job)]
    print(f"jobs from official careers after filtering:{company}: {len(filtered_jobs)}")
    sent_count = await send_jobs_without_status(filtered_jobs) if notify else 0
    return filtered_jobs, sent_count

async def fetch_comeet_jobs(client: httpx.AsyncClient, source: dict, notify: bool = True) -> tuple[list[dict], int]:
    company = source["company"]
    uid = source["uid"]
    token = source["token"]
    print(f"Fetching Comeet jobs for {company}...")
    
    url = f"https://www.comeet.co/careers-api/2.0/company/{uid}/positions"
    params = {
        "token": token,
        "details": "true"
    }
    
    try:
        response = await client.get(url, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
    except Exception as exc:
        print(f"Source fetch failed: {exc} from {company}")
        return [], 0

    jobs = []
    for item in data:
        if not isinstance(item, dict):
            continue
        # Location logic
        loc_data = item.get("location") or {}
        location_parts = []
        for value in (loc_data.get("name"), loc_data.get("city"), loc_data.get("country")):
            value = str(value or "").strip()
            if value and value not in location_parts:
                location_parts.append(value)
        location_text = ", ".join(location_parts) or "Israel"
        country = str(loc_data.get("country") or "")
        
        # Filter for Israel
        is_israel = (
            source.get("assume_israel")
            or country.upper() in {"IL", "ISRAEL"}
            or any(k in location_text.lower() for k in ISRAEL_LOCATION_KEYWORDS)
        )
        if not is_israel:
            continue
            
        # Extract description
        details = item.get("details") or []
        description_parts = [str(d.get("value", "")) for d in details if isinstance(d, dict) and d.get("value") is not None]
        full_description = " ".join(description_parts)

        job_entry = {
            "title": item.get("name", "N/A"),
            "company": company,
            "location": location_text,
            "salary": "Not specified",
            "description": trim_text(html.unescape(full_description)),
            "job_type": "Full-time",
            "tags": item.get("department", ""),
            "url": item.get("url_active_page", ""),
            "posted": "Recently",
            "remote": loc_data.get("is_remote", False),
            "source": f"Comeet:{company}",
        }
        # Add job_id for tracking
        job_entry["job_id"] = generate_job_id(job_entry)
        jobs.append(job_entry)

    print(f'jobs from Comeet before filtering:{company}: {len(jobs)}')
    filtered_jobs = [job for job in jobs if matches_preferences(job)]
    print(f'jobs from Comeet after filtering:{company}: {len(filtered_jobs)}')
    sent_count = await send_jobs_without_status(filtered_jobs) if notify else 0
    return filtered_jobs, sent_count

async def fetch_smartrecruiters_jobs(client: httpx.AsyncClient, source: dict, notify: bool = True) -> tuple[list[dict], int]:
    company = source["company"]
    url = source["url"]
    print(f"Fetching SmartRecruiters jobs for {company}...")
    
    try:
        response = await client.get(url, timeout=30)
        response.raise_for_status()
        data = response.json()
    except Exception as exc:
        print(f"Source fetch failed: {exc} from {company}")
        return [], 0

    jobs = []
    content = data.get("content", [])
    for item in content:
        if not isinstance(item, dict):
            continue
        location = item.get("location") or {}
        country = location.get("country", "")
        full_location = location.get("fullLocation", "")
        
        # Filter for Israel
        is_israel = (country.lower() == "il") or any(k in full_location.lower() for k in ISRAEL_LOCATION_KEYWORDS)
        if not is_israel:
            continue
            
        jobs.append({
            "title": item.get("name", "N/A"),
            "company": company,
            "location": full_location,
            "salary": "Not specified",
            "description": "SmartRecruiters Job Posting", # Content usually requires another API call per job
            "job_type": item.get("typeOfEmployment", {}).get("label", "Full-time"),
            "tags": item.get("department", {}).get("label", ""),
            "url": f"https://jobs.smartrecruiters.com/{item.get('company', {}).get('identifier')}/{item.get('id')}",
            "posted": item.get("releasedDate", "Recently"),
            "remote": location.get("remote", False),
            "source": f"SmartRecruiters:{company}",
        })
        # Add job_id for tracking
        jobs[-1]["job_id"] = generate_job_id(jobs[-1])
    
    print(f'jobs from SmartRecruiters before filtering:{company}: {len(jobs)}')
    filtered_jobs = [job for job in jobs if matches_preferences(job)]
    print(f'jobs from SmartRecruiters after filtering:{company}: {len(filtered_jobs)}')
    sent_count = await send_jobs_without_status(filtered_jobs) if notify else 0
    return filtered_jobs, sent_count


async def fetch_ashby_jobs(client: httpx.AsyncClient, source: dict, notify: bool = True) -> tuple[list[dict], int]:
    """Fetch Israel jobs from an Ashby public job board."""
    company = source["company"]
    board = source["board"]
    print(f"Fetching Ashby jobs for {company}...")
    response = await client.get(
        f"https://api.ashbyhq.com/posting-api/job-board/{board}",
        timeout=30,
    )
    response.raise_for_status()

    jobs = []
    for item in response.json().get("jobs", []):
        location = str(item.get("location") or "Not specified")
        if not any(keyword in location.lower() for keyword in ISRAEL_LOCATION_KEYWORDS):
            continue

        job = {
            "title": item.get("title", "N/A"),
            "company": company,
            "location": location,
            "salary": "Not specified",
            "description": trim_text(html.unescape(item.get("descriptionPlain") or "")),
            "job_type": item.get("employmentType") or "Full-time",
            "tags": item.get("department") or item.get("team") or "",
            "url": item.get("jobUrl") or item.get("applyUrl") or "",
            "posted": item.get("publishedAt") or "Recently",
            "remote": bool(item.get("isRemote")) or "remote" in location.lower(),
            "source": f"Ashby:{company}",
        }
        job["job_id"] = generate_job_id(job)
        jobs.append(job)

    print(f"jobs from Ashby before filtering:{company}: {len(jobs)}")
    filtered_jobs = [job for job in jobs if matches_preferences(job)]
    print(f"jobs from Ashby after filtering:{company}: {len(filtered_jobs)}")
    sent_count = await send_jobs_without_status(filtered_jobs) if notify else 0
    return filtered_jobs, sent_count


async def fetch_elbit_jobs(client: httpx.AsyncClient, source: dict, notify: bool = True) -> tuple[list[dict], int]:
    """Fetch jobs from Elbit Systems' public careers JSON feed."""
    company = source["company"]
    print(f"Fetching Elbit Systems jobs for {company}...")
    response = await client.get(source["url"], timeout=30)
    response.raise_for_status()

    jobs = []
    for item in response.json():
        if not isinstance(item, dict) or item.get("status") != 1:
            continue

        area = str(item.get("area") or "Israel")
        description = trim_text(html.unescape(str(item.get("description") or "")))
        job_id = item.get("jobId")
        job = {
            "title": item.get("jobTitle") or "N/A",
            "company": company,
            "location": f"{area}, Israel" if area.lower() != "israel" else "Israel",
            "salary": "Not specified",
            "description": description,
            "job_type": item.get("employmentType") or "Not specified",
            "tags": f"Job code: {item.get('jobCode', item.get('jobId', ''))}",
            "url": f"{source['job_url']}?jid={job_id}" if job_id else source["careers_url"],
            "posted": item.get("openDate") or item.get("updateDate") or "Recently",
            "remote": "remote" in area.lower(),
            "source": "Elbit Systems Careers",
        }
        job["job_id"] = f"elbit-{job_id}" if job_id else generate_job_id(job)
        jobs.append(job)

    print(f"jobs from Elbit before filtering:{company}: {len(jobs)}")
    filtered_jobs = [job for job in jobs if matches_preferences(job)]
    print(f"jobs from Elbit after filtering:{company}: {len(filtered_jobs)}")
    sent_count = await send_jobs_without_status(filtered_jobs) if notify else 0
    return filtered_jobs, sent_count


async def fetch_iscar_jobs(client: httpx.AsyncClient, source: dict, notify: bool = True) -> tuple[list[dict], int]:
    """Fetch all paginated jobs from ISCAR's official careers site."""
    company = source["company"]
    base_url = source["url"]
    max_pages = int(source.get("max_pages", 20))
    print("Fetching ISCAR jobs...")
    jobs_by_url = {}

    for page_number in range(1, max_pages + 1):
        page_url = base_url if page_number == 1 else f"{base_url}{page_number}/"
        response = await client.get(
            page_url,
            timeout=30,
            headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "he-IL,he;q=0.9"},
        )
        using_markdown = response.status_code == 403
        if using_markdown:
            proxy_base = source["text_proxy"]
            proxy_url = proxy_base if page_number == 1 else f"{proxy_base}{page_number}/"
            response = await client.get(proxy_url, timeout=30)
        if response.status_code == 404:
            break
        response.raise_for_status()
        page_jobs = 0
        new_jobs = 0
        listings = []
        if using_markdown:
            listings = re.findall(r"^### \[([^\]]+)\]\((https?://www\.iscar\.com/marcom/[^)]+)\)", response.text, re.MULTILINE)
        else:
            soup = BeautifulSoup(response.text, "html.parser")
            listings = [
                (link.get_text(" ", strip=True), str(link.get("href") or ""))
                for heading in soup.select("h3")
                if (link := heading.find("a", href=True))
            ]

        for title, url in listings:
            if not title or not url or "career-job-list" in url:
                continue
            if url.startswith("/"):
                url = "https://www.iscar.com" + url
            job_code_match = re.search(r"\bJB[-\s]?(\d+)\b", title, re.I)
            job_code = job_code_match.group(1) if job_code_match else ""
            clean_title = re.sub(r"\s*[–-]?\s*JB[-\s]?\d+\s*$", "", title, flags=re.I).strip()
            job = {
                "title": clean_title or title,
                "company": company,
                "location": "Israel",
                "salary": "Not specified",
                "description": title,
                "job_type": "Not specified",
                "tags": f"Job code: JB-{job_code}" if job_code else "",
                "url": url,
                "posted": "Recently",
                "remote": False,
                "source": "ISCAR Careers",
                "job_id": f"iscar-{job_code}" if job_code else "iscar-" + generate_job_id({"title": clean_title, "url": url}),
            }
            if url not in jobs_by_url:
                new_jobs += 1
            jobs_by_url[url] = job
            page_jobs += 1

        if page_jobs == 0 or new_jobs == 0:
            break

    filtered_jobs = [job for job in jobs_by_url.values() if matches_preferences(job)]
    print(f"jobs from ISCAR after filtering:{company}: {len(filtered_jobs)}")
    sent_count = await send_jobs_without_status(filtered_jobs) if notify else 0
    return filtered_jobs, sent_count


async def fetch_bank_jobs(client: httpx.AsyncClient, source: dict, notify: bool = True) -> tuple[list[dict], int]:
    """Fetch jobs from Bank Leumi's official careers page."""
    company = source["company"]
    print(f"Fetching bank jobs for {company}...")
    response = await client.get(source["url"], timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    jobs = []

    if source.get("kind") == "mizrahi":
        for heading in soup.select("h3"):
            title = heading.get_text(" ", strip=True)
            if not title:
                continue
            block = heading.find_parent(["article", "li", "section", "div"])
            body = block.get_text(" ", strip=True) if block else title
            job = {
                "title": title,
                "company": company,
                "location": "Israel",
                "salary": "Not specified",
                "description": trim_text(body),
                "job_type": "Not specified",
                "tags": "Banking",
                "url": source["url"],
                "posted": "Recently",
                "remote": "עבודה מהבית" in body,
                "source": "Mizrahi-Tefahot Careers",
            }
            job["job_id"] = "mizrahi-" + generate_job_id(job)
            jobs.append(job)
        filtered_jobs = [job for job in jobs if matches_preferences(job)]
        print(f"jobs from bank after filtering:{company}: {len(filtered_jobs)}")
        sent_count = await send_jobs_without_status(filtered_jobs) if notify else 0
        return filtered_jobs, sent_count

    for checkbox in soup.select('input[name="job_checkbox"][value]'):
        job_id = str(checkbox.get("value"))
        container = checkbox.find_parent(class_="jobs-table") or checkbox.parent
        # Each checkbox is followed by its own expanded job block.
        block = checkbox.find_next(class_="full-job")
        title_node = block.select_one("h3.job-title") if block else None
        if not title_node:
            continue
        title = title_node.get_text(" ", strip=True)
        body = block.get_text(" ", strip=True)
        location_match = re.search(
            r"(?:מיקום המשרה|מיקום)\s*[:：]?\s*(.{2,50}?)(?=\s+(?:כישורים|דרישות|היקף|תיאור|$))",
            body,
        )
        location = location_match.group(1).strip() if location_match else "Israel"
        job = {
            "title": title,
            "company": company,
            "location": location,
            "salary": "Not specified",
            "description": trim_text(body),
            "job_type": "Not specified",
            "tags": f"Bank job ID: {job_id}",
            "url": f"https://www.leumi.co.il/he/node/{job_id}",
            "posted": "Recently",
            "remote": "עבודה מהבית" in body,
            "source": "Bank Leumi Careers",
            "job_id": f"leumi-{job_id}",
        }
        jobs.append(job)

    # The page is already an Israel-only careers board.
    filtered_jobs = [job for job in jobs if matches_preferences(job)]
    print(f"jobs from bank after filtering:{company}: {len(filtered_jobs)}")
    sent_count = await send_jobs_without_status(filtered_jobs) if notify else 0
    return filtered_jobs, sent_count


async def fetch_government_jobs(client: httpx.AsyncClient, source: dict, notify: bool = True) -> tuple[list[dict], int]:
    """Fetch active job publications from Israel's Civil Service Commission."""
    company = source["company"]
    jobs = []
    print("Fetching Israel Civil Service jobs...")
    response = await client.get(
        source["url"],
        timeout=30,
        headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "he-IL,he;q=0.9"},
    )
    # gov.il currently blocks non-browser HTTP clients with 403. Fall back to
    # an RSS index query whose results still link directly to official pages.
    if response.status_code == 403:
        response = await client.get(
            source["search_url"],
            params={
                "format": "rss",
                "q": 'site:gov.il/he/pages (דרוש OR דרושה OR "מכרז פומבי") "סטטוס פעיל"',
                "count": "50",
            },
            timeout=30,
        )
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        for item in soup.select("item"):
            title_node, link_node = item.find("title"), item.find("link")
            title = title_node.get_text(" ", strip=True) if title_node else ""
            url = link_node.get_text(strip=True) if link_node else ""
            if not title or "gov.il/he/pages/" not in url:
                continue
            description_node = item.find("description")
            body = BeautifulSoup(description_node.get_text() if description_node else "", "html.parser").get_text(" ", strip=True)
            job = {
                "title": title,
                "company": company,
                "location": "Israel",
                "salary": "Not specified",
                "description": trim_text(body),
                "job_type": "Not specified",
                "tags": "Government / Civil Service",
                "url": url,
                "posted": "Recently",
                "remote": False,
                "source": "gov.il - Civil Service Commission",
            }
            job["job_id"] = "gov-" + generate_job_id(job)
            jobs.append(job)
        filtered_jobs = [job for job in jobs if matches_preferences(job)]
        print(f"jobs from government after filtering:{company}: {len(filtered_jobs)}")
        sent_count = await send_jobs_without_status(filtered_jobs) if notify else 0
        return filtered_jobs, sent_count

    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    seen_urls = set()

    for link in soup.select('a[href*="/he/pages/"]'):
        title = link.get_text(" ", strip=True)
        href = str(link.get("href") or "")
        if not title or href in seen_urls:
            continue
        card = link.find_parent(["article", "li"]) or link.find_parent("div")
        body = card.get_text(" ", strip=True) if card else title
        if "דרושים" not in body or "פעיל" not in body:
            continue
        seen_urls.add(href)
        url = href if href.startswith("http") else f"https://www.gov.il{href}"
        location_match = re.search(r"מיקום\s*[:：]?\s*([^:]{2,40}?)(?:תאריך|$)", body)
        employment_match = re.search(r"סוג העסקה\s*[:：]?\s*([^:]{2,50}?)(?:מיקום|תאריך|$)", body)
        date_match = re.search(r"תאריך פרסום\s*[:：]?\s*(\d{2}\.\d{2}\.\d{4})", body)
        job = {
            "title": title,
            "company": company,
            "location": (location_match.group(1).strip() if location_match else "Israel"),
            "salary": "Not specified",
            "description": trim_text(body),
            "job_type": (employment_match.group(1).strip() if employment_match else "Not specified"),
            "tags": "Government / Civil Service",
            "url": url,
            "posted": date_match.group(1) if date_match else "Recently",
            "remote": False,
            "source": "gov.il - Civil Service Commission",
        }
        job["job_id"] = "gov-" + generate_job_id(job)
        jobs.append(job)

    filtered_jobs = [job for job in jobs if matches_preferences(job)]
    print(f"jobs from government after filtering:{company}: {len(filtered_jobs)}")
    sent_count = await send_jobs_without_status(filtered_jobs) if notify else 0
    return filtered_jobs, sent_count


async def fetch_big_tech_jobs(client: httpx.AsyncClient, source: dict, notify: bool = True) -> tuple[list[dict], int]:
    """Fetch Israel jobs from official Amazon, Apple, Google, or Microsoft pages."""
    company, kind = source["company"], source["kind"]
    print(f"Fetching official careers jobs for {company}...")
    headers = {"User-Agent": "Mozilla/5.0", "Accept-Language": "en-US,en;q=0.9"}
    jobs = []

    if kind == "amazon":
        offset = 0
        while True:
            response = await client.get(
                source["url"],
                params={"country": "ISR", "result_limit": 100, "offset": offset},
                headers=headers,
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()
            page = data.get("jobs", [])
            for item in page:
                job_id = str(item.get("id") or item.get("job_id") or "")
                job = {
                    "title": item.get("title") or "N/A",
                    "company": company,
                    "location": item.get("location") or "Israel",
                    "salary": "Not specified",
                    "description": trim_text(html.unescape(item.get("description_short") or item.get("description") or "")),
                    "job_type": "Not specified",
                    "tags": item.get("business_category") or item.get("job_category") or "",
                    "url": item.get("url_next_step") or item.get("job_path") or f"https://www.amazon.jobs/en/jobs/{job_id}",
                    "posted": item.get("posted_date") or "Recently",
                    "remote": "remote" in str(item.get("location", "")).lower(),
                    "source": "Amazon Jobs",
                    "job_id": f"amazon-{job_id}" if job_id else "amazon-" + generate_job_id(item),
                }
                if str(job["url"]).startswith("/"):
                    job["url"] = "https://www.amazon.jobs" + job["url"]
                jobs.append(job)
            offset += len(page)
            if not page or offset >= int(data.get("hits", 0)):
                break
    else:
        response = await client.get(source["url"], headers=headers, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        if kind == "apple":
            links = soup.select('a[href*="/details/"]')
            for link in links:
                title = link.get_text(" ", strip=True)
                if not title or title.lower().startswith("see full"):
                    continue
                href = str(link.get("href"))
                card = link.find_parent(["article", "li"]) or link.find_parent("div")
                body = card.get_text(" ", strip=True) if card else title
                location_match = re.search(r"\b(Herzliya|Haifa|Tel Aviv|Israel)\b", body, re.I)
                jobs.append(_make_official_job(company, title, location_match.group(1).strip() if location_match else "Israel", body, "https://jobs.apple.com" + href, "Apple Jobs"))
        elif kind == "google":
            for link in soup.select('a[href^="jobs/results/"][aria-label]'):
                href = str(link.get("href"))
                title = re.sub(r"^Learn more about\s+", "", str(link.get("aria-label")), flags=re.I)
                card = link.find_parent(["article", "li"]) or link.find_parent("div")
                body = card.get_text(" ", strip=True) if card else title
                locations = list(dict.fromkeys(node.get_text(" ", strip=True).lstrip("; ") for node in card.select("span.r0wTof") if node.get_text(strip=True))) if card else []
                jobs.append(_make_official_job(company, title, "; ".join(locations) or "Israel", body, "https://www.google.com/about/careers/applications/" + href, "Google Careers"))
        elif kind == "microsoft":
            for link in soup.select('a[href*="apply.careers.microsoft.com/careers/job/"]'):
                card = link.find_parent("div", class_="careers-joblistResponsive-columnList")
                heading = card.select_one(".careers-joblistResponsive-title") if card else None
                if heading is None and card:
                    heading = card.find(["h2", "h3", "h4"])
                title = heading.get_text(" ", strip=True) if heading else str(link.get("aria-label") or "Microsoft job")
                body = card.get_text(" ", strip=True) if card else title
                jobs.append(_make_official_job(company, title, "Israel", body, str(link.get("href")), "Microsoft Careers"))

    # Deduplicate links that appear more than once in responsive page markup.
    unique = {str(job.get("url")): job for job in jobs if job.get("url")}
    filtered_jobs = [job for job in unique.values() if matches_preferences(job)]
    print(f"jobs from official careers after filtering:{company}: {len(filtered_jobs)}")
    sent_count = await send_jobs_without_status(filtered_jobs) if notify else 0
    return filtered_jobs, sent_count


def _make_official_job(company: str, title: str, location: str, description: str, url: str, source: str) -> dict:
    job = {
        "title": title,
        "company": company,
        "location": location,
        "salary": "Not specified",
        "description": trim_text(description),
        "job_type": "Not specified",
        "tags": "",
        "url": url,
        "posted": "Recently",
        "remote": "remote" in location.lower(),
        "source": source,
    }
    job["job_id"] = f"{company}-" + generate_job_id(job)
    return job
