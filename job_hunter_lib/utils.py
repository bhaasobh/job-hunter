"""Small shared helpers."""

import html
import re


def trim_text(text: str, limit: int = 5000) -> str:
    compact = re.sub(r"\s+", " ", text or "").strip()
    return compact[:limit]


def safe_html(value, default: str = "") -> str:
    if value is None:
        value = default
    return html.escape(str(value))


def generate_job_id(job: dict) -> str:
    import hashlib
    company = str(job.get("company") or "").strip().lower()
    title = str(job.get("title") or "").strip().lower()
    url = str(job.get("url") or "").strip()
    location = str(job.get("location") or "").strip().lower()

    # Prioritize unique job URL if available (ignoring generic landing pages)
    if url and url != "#" and not url.endswith("/jobs") and not url.endswith("/careers"):
        clean_url = url.split("?")[0].rstrip("/")
        signature = f"{company}_{clean_url}" if company else clean_url
    elif company and title:
        signature = f"{company}_{title}_{location}"
    elif url:
        signature = url.split("?")[0].rstrip("/")
    else:
        signature = f"{company}_{title}_{location}"

    return hashlib.md5(signature.encode("utf-8")).hexdigest()[:12]

