"""Load CV data from Telegram, local cache, or file."""

from datetime import datetime
import os
from pathlib import Path
from urllib.parse import quote
import tempfile

import httpx

from job_hunter_lib.config import (
    CV_FILE_PATH,
    CV_STORAGE_DIR,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    TELEGRAM_CV_MIN_LENGTH,
    TELEGRAM_CV_MODE,
)

try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None


def extract_text_from_message(message: dict) -> str:
    return (message.get("text") or message.get("caption") or "").strip()


def normalize_cv_message_text(text: str) -> str:
    if text.lower().startswith("/cv"):
        return text[3:].lstrip(" :\n")
    return text


def is_cv_message(text: str) -> bool:
    if not text:
        return False
    if text.lower().startswith("/cv"):
        return True
    return len(text) >= TELEGRAM_CV_MIN_LENGTH


def ensure_cv_storage_dir() -> Path:
    CV_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    return CV_STORAGE_DIR


def cv_file_path(update_id: int) -> Path:
    ensure_cv_storage_dir()
    return CV_STORAGE_DIR / f"cv_{update_id}.txt"


def save_cv_message(update_id: int, text: str, message_date: int | None = None, suffix: str = ".txt") -> Path:
    path = cv_file_path(update_id)
    if suffix != ".txt":
        path = path.with_suffix(suffix)
    if not path.exists():
        path.write_text(text, encoding="utf-8")
        if message_date:
            timestamp = datetime.fromtimestamp(message_date).isoformat()
            os.utime(path, (message_date, message_date))
            print(f"Saved CV locally: {path} ({timestamp})")
        else:
            print(f"Saved CV locally: {path}")
    return path


def read_latest_saved_cv() -> str | None:
    if not CV_STORAGE_DIR.exists():
        return None

    files = sorted(
        CV_STORAGE_DIR.glob("cv_*.txt"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not files:
        return None

    latest_path = files[0]
    text = latest_path.read_text(encoding="utf-8").strip()
    if not text:
        return None

    print(f"CV loaded from local store: {latest_path.name} ({len(text)} characters)")
    return text


async def download_telegram_file(client: httpx.AsyncClient, file_id: str) -> bytes:
    """Download a Telegram file by file_id."""
    get_file_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getFile"
    file_response = await client.get(get_file_url, params={"file_id": file_id})
    file_response.raise_for_status()
    file_data = file_response.json()
    file_path = file_data.get("result", {}).get("file_path")
    if not file_path:
        raise ValueError("Telegram getFile did not return file_path")

    download_url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{quote(file_path)}"
    content_response = await client.get(download_url)
    content_response.raise_for_status()
    return content_response.content


def extract_text_from_pdf_bytes(raw_bytes: bytes) -> str:
    """Extract text from PDF bytes when pypdf is installed."""
    if PdfReader is None:
        raise RuntimeError("PDF support requires the 'pypdf' package")

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as temp_file:
        temp_file.write(raw_bytes)
        temp_path = Path(temp_file.name)

    try:
        reader = PdfReader(str(temp_path))
        text_parts = []
        for page in reader.pages:
            page_text = page.extract_text() or ""
            if page_text.strip():
                text_parts.append(page_text.strip())
        return "\n".join(text_parts).strip()
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass


async def extract_cv_from_document(client: httpx.AsyncClient, message: dict) -> tuple[str | None, str]:
    """Extract CV text from a Telegram document when possible."""
    document = message.get("document") or {}
    if not document:
        return None, "no-document"

    file_name = str(document.get("file_name", ""))
    mime_type = str(document.get("mime_type", "")).lower()
    file_id = document.get("file_id")
    if not file_id:
        return None, "missing-file-id"

    if not (
        mime_type.startswith("text/")
        or file_name.lower().endswith(".txt")
        or mime_type == "application/pdf"
        or file_name.lower().endswith(".pdf")
    ):
        return None, f"unsupported-document:{file_name or mime_type or 'unknown'}"

    raw_bytes = await download_telegram_file(client, file_id)
    suffix = ".pdf" if mime_type == "application/pdf" or file_name.lower().endswith(".pdf") else ".txt"

    if suffix == ".pdf":
        try:
            text = extract_text_from_pdf_bytes(raw_bytes)
        except RuntimeError as exc:
            return None, f"pdf-parser-missing:{exc}"
        except Exception as exc:
            return None, f"pdf-read-failed:{type(exc).__name__}"
    else:
        try:
            text = raw_bytes.decode("utf-8").strip()
        except UnicodeDecodeError:
            text = raw_bytes.decode("latin-1", errors="ignore").strip()

    if not is_cv_message(text):
        return None, "document-too-short"

    return text, "document-text"


async def sync_cvs_from_telegram() -> str | None:
    if not TELEGRAM_BOT_TOKEN:
        return None

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
    candidates = []
    chat_id = str(TELEGRAM_CHAT_ID)
    skipped_reasons = []
    updates = []

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(url, params={"limit": 100, "timeout": 10})
        response.raise_for_status()
        data = response.json()
        updates = data.get("result", [])

        for update in updates:
            message = update.get("message") or update.get("edited_message") or {}
            if not message:
                continue

            message_chat_id = str((message.get("chat") or {}).get("id", ""))
            if chat_id and message_chat_id != chat_id:
                skipped_reasons.append(f"other-chat:{message_chat_id}")
                continue

            update_id = int(update.get("update_id", 0))
            message_date = message.get("date")

            text = normalize_cv_message_text(extract_text_from_message(message))
            if is_cv_message(text):
                save_cv_message(update_id, text, message_date)
                candidates.append((update_id, text))
                continue

            document_text, reason = await extract_cv_from_document(client, message)
            if document_text:
                save_cv_message(update_id, document_text, message_date)
                candidates.append((update_id, document_text))
                continue

            skipped_reasons.append(reason)

    if not candidates:
        if updates:
            sample_reasons = ", ".join(skipped_reasons[:5]) if skipped_reasons else "no-matching-cv-messages"
            print(f"No usable CV found in Telegram updates. Reasons: {sample_reasons}")
        else:
            print("No Telegram updates found. Send a message to the bot first, then run the script again.")
        return None

    if TELEGRAM_CV_MODE == "longest":
        candidates.sort(key=lambda item: len(item[1]), reverse=True)
    else:
        candidates.sort(key=lambda item: item[0], reverse=True)

    cv_text = candidates[0][1]
    print(f"CV loaded from Telegram ({len(cv_text)} characters)")
    return cv_text


async def read_cv() -> str:
    telegram_cv = await sync_cvs_from_telegram()
    if telegram_cv:
        return telegram_cv

    latest_saved_cv = read_latest_saved_cv()
    if latest_saved_cv:
        return latest_saved_cv

    cv_path = Path(CV_FILE_PATH)
    if cv_path.exists():
        return cv_path.read_text(encoding="utf-8")

    raise FileNotFoundError(
        "No CV found in Telegram and local CV file is missing: "
        f"{CV_FILE_PATH}\nSend your CV to the bot chat or create '{CV_FILE_PATH}'."
    )
