"""Fetch, AI-score, and Telegram-send the best new jobs on a fixed interval."""

import asyncio
from datetime import datetime

from job_hunter_lib.config import (
    SCHEDULE_BOOTSTRAP_SILENT,
    SCHEDULE_INTERVAL_HOURS,
    SCHEDULE_MAX_TELEGRAM_JOBS,
    SCHEDULE_MIN_AI_SCORE,
)
from job_hunter_lib.cv_store import read_cv
from job_hunter_lib.jobs import fetch_jobs
from job_hunter_lib.local_database import get_all_jobs, mark_jobs_sent_to_telegram, save_search_results
from job_hunter_lib.ollama_matcher import analysis_summary, analyze_job_with_ollama
from job_hunter_lib.telegram_client import format_job_message, send_telegram_message
from job_hunter_lib.utils import generate_job_id


async def run_scheduled_hunt() -> dict:
    print(f"[{datetime.now().isoformat(timespec='seconds')}] Scheduled AI hunt started")
    cv_text = await read_cv()
    existing = {str(job.get("job_id")): job for job in get_all_jobs()}
    fetched = await fetch_jobs(notify=False, excluded_keywords=[])
    unique = {}
    for source_job in fetched:
        job = dict(source_job)
        job_id = str(job.get("job_id") or generate_job_id(job))
        job["job_id"] = job_id
        unique[job_id] = job

    if not existing and SCHEDULE_BOOTSTRAP_SILENT:
        save_search_results(list(unique.values()))
        print(f"Baseline created with {len(unique)} jobs; no Telegram messages sent.")
        return {"fetched": len(unique), "analyzed": 0, "sent": 0, "baseline": True}

    candidates = []
    for job_id, job in unique.items():
        previous = existing.get(job_id)
        if previous is None or (previous.get("status") == "new" and not previous.get("ai_analyzed")):
            candidates.append(job)

    analyzed = []
    for index, job in enumerate(candidates, 1):
        print(f"AI scoring {index}/{len(candidates)}: {job.get('title')}")
        try:
            analysis, _cached = await asyncio.to_thread(analyze_job_with_ollama, cv_text, job)
        except Exception as exc:
            print(f"AI analysis failed for {job.get('title')}: {exc}")
            continue
        job.update(
            match_score=analysis["score"],
            match_reason=analysis_summary(analysis),
            ai_analysis=analysis,
            score_source="Ollama scheduled analysis",
            ai_analyzed=True,
        )
        analyzed.append(job)

    saved = save_search_results(list(unique.values()))
    saved_by_id = {job["job_id"]: job for job in saved}
    matches = [saved_by_id[job["job_id"]] for job in analyzed if job["match_score"] >= SCHEDULE_MIN_AI_SCORE]
    matches.sort(key=lambda job: int(job.get("match_score", 0)), reverse=True)
    selected = matches[:SCHEDULE_MAX_TELEGRAM_JOBS]
    if selected:
        await send_telegram_message(
            f"<b>🎯 {len(selected)} best new job matches</b>\n"
            f"Minimum AI score: {SCHEDULE_MIN_AI_SCORE}/100"
        )
        sent_ids = []
        for index, job in enumerate(selected, 1):
            if await send_telegram_message(format_job_message(job, index=index)):
                sent_ids.append(job["job_id"])
        mark_jobs_sent_to_telegram(sent_ids, "scheduled")
    print(f"Scheduled hunt complete: {len(candidates)} candidates, {len(analyzed)} analyzed, {len(selected)} sent")
    return {"fetched": len(unique), "analyzed": len(analyzed), "sent": len(selected), "baseline": False}


async def main():
    while True:
        started = asyncio.get_running_loop().time()
        try:
            await run_scheduled_hunt()
        except Exception as exc:
            print(f"Scheduled hunt failed: {exc}")
        elapsed = asyncio.get_running_loop().time() - started
        await asyncio.sleep(max(0, SCHEDULE_INTERVAL_HOURS * 3600 - elapsed))


if __name__ == "__main__":
    asyncio.run(main())
