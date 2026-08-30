"""Telegram formatting and delivery."""

import html

import httpx

from job_hunter_lib.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from job_hunter_lib.utils import safe_html


def format_job_message(job: dict, index: int = None) -> str:
    """Format a single job for Telegram."""
    score = int(job.get("match_score", 0))
    score_icon = "🔥" if score >= 85 else "✅" if score >= 75 else "⚡"
    
    header = f"<b>{score_icon} {job.get('title', 'N/A')}</b>"
    if index is not None:
        header = f"<b>{score_icon} {index}. {job.get('title', 'N/A')}</b>"

    lines = [
        header,
        f"🏢 {safe_html(job.get('company', 'N/A'))}",
        f"📍 {safe_html(job.get('location', 'N/A'))}",
        f"💰 {safe_html(job.get('salary', 'Not specified'))}",
        f"📊 AI Score: {score}/100",
        f"💡 {safe_html(job.get('match_reason', ''))}",
        f"🕒 {safe_html(job.get('posted', 'Recently'))}",
        f"🔗 {safe_html(job.get('source', 'Unknown'))}",
        f'<a href="{html.escape(str(job.get("url", "#")), quote=True)}">Apply Here</a>'
    ]
    return "\n".join(lines)


def format_telegram_message(jobs: list[dict]) -> str:
    """Old list formatter - now just returns a header or empty msg."""
    if not jobs:
        return "Job Hunt Complete\n\nNo matching jobs found this time."
    return f"<b>Found {len(jobs)} matches! Sending them individually...</b>"


def get_job_keyboard(job_id: str):
    """Create the InlineKeyboard for a job."""
    return {
        "inline_keyboard": [
            [
                {"text": "✅ Applied", "callback_data": f"applied_{job_id}"},
                {"text": "❌ Didn't Apply", "callback_data": f"notapplied_{job_id}"},
            ],
            [
                {"text": "⏰ Remind Me Later", "callback_data": f"remind_{job_id}"}
            ]
        ]
    }


async def send_telegram_message(message: str, reply_markup: dict = None) -> bool:
    """Send a message to Telegram, splitting it into chunks if it's too long."""
    if not message:
        return False

    MAX_LENGTH = 4000  # Telegram limit is 4096, using 4000 to be safe
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    
    # Split the message into chunks
    chunks = []
    if len(message) <= MAX_LENGTH:
        chunks = [message]
    else:
        current_chunk = ""
        for line in message.split("\n"):
            if len(current_chunk) + len(line) + 1 > MAX_LENGTH:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                current_chunk = line + "\n"
            else:
                current_chunk += line + "\n"
        if current_chunk:
            chunks.append(current_chunk.strip())

    success = True
    async with httpx.AsyncClient(timeout=30) as client:
        for i, chunk in enumerate(chunks):
            # Only add keyboard to the last chunk (or if there's only one chunk)
            payload = {
                "chat_id": TELEGRAM_CHAT_ID,
                "text": chunk,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            }
            if reply_markup and i == len(chunks) - 1:
                payload["reply_markup"] = reply_markup

            response = await client.post(url, json=payload)
            if response.status_code != 200:
                print(f"Telegram error: {response.text}")
                success = False
            else:
                print(f"Part of message sent to Telegram ({len(chunk)} characters).")

    return success
