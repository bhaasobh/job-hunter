"""Entry point for the AI job hunter."""

import asyncio

from job_hunter_lib.cv_store import read_cv
from job_hunter_lib.scoring import find_and_filter_jobs
from job_hunter_lib.telegram_client import format_telegram_message, send_telegram_message


async def run_job_hunt():
    """Main job hunting flow."""
    print("Starting AI Job Hunter...")

    print("Reading your CV...")
    cv_content = 0
    # cv_content = await read_cv()
    # print(f"CV loaded ({len(cv_content)} characters)")

    print("Fetching jobs from free feeds...")
    jobs = await find_and_filter_jobs(cv_content)
    print(f"Found {len(jobs)} jobs.")

    # print("Sending results to Telegram...")
    # message = format_telegram_message(jobs)
    # await send_telegram_message(message)

    # print("\nJob hunt complete.")
    # for index, job in enumerate(jobs, 1):
    #     print(f"{index}. {job.get('title')} @ {job.get('company')} - Score: {job.get('match_score')}/10")


if __name__ == "__main__":
    asyncio.run(run_job_hunt())
