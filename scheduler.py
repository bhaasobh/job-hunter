import asyncio
import time
from datetime import datetime, timedelta

from job_hunter_lib.jobs import fetch_jobs
from job_hunter_lib.database import get_jobs_by_status, get_unresponded_jobs, mark_job_as_notified
from job_hunter_lib.telegram_client import send_telegram_message, format_job_message, get_job_keyboard

async def send_updates():
    """Run the job fetcher and send reminders/unresponded updates."""
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Starting Scheduled Update...")

    # 1. Fetch and notify NEW jobs (built into fetchers logic via mark_job_as_notified)
    print("Step 1: Fetching new jobs...")
    try:
        await fetch_jobs()
    except Exception as e:
        print(f"Error during job fetch: {e}")

    # 2. Send Reminders
    print("Step 2: Sending reminders...")
    remind_jobs = get_jobs_by_status("remind")
    if remind_jobs:
        await send_telegram_message(f"<b>⏰ REMINDERS: You have {len(remind_jobs)} jobs to review!</b>")
        for job in remind_jobs:
            message = "<b>REMINDER</b>\n" + format_job_message(job)
            keyboard = get_job_keyboard(job["job_id"])
            await send_telegram_message(message, reply_markup=keyboard)
    else:
        print("No reminders found.")

    # 3. Send Unresponded Jobs
    print("Step 3: Sending unresponded jobs...")
    unresponded = get_unresponded_jobs()
    # Filter out those we just sent as "new" in this exact run? 
    # Actually, the fetchers mark them as 'notified' but not responded.
    # To avoid double-sending jobs that were JUST fetched, we might want to filter them.
    # But for simplicity, let's just send them if they are more than, say, 3 hours old.
    
    current_time = datetime.utcnow()
    old_unresponded = [
        job for job in unresponded 
        if (current_time - job.get("last_seen", current_time)).total_seconds() > 3600
    ]

    if old_unresponded:
        await send_telegram_message(f"<b>⏳ PENDING: {len(old_unresponded)} jobs waiting for a response!</b>")
        for job in old_unresponded[:10]: # Limit to 10 to avoid spamming too much in one go
            message = "<b>PENDING RESPONSE</b>\n" + format_job_message(job)
            keyboard = get_job_keyboard(job["job_id"])
            await send_telegram_message(message, reply_markup=keyboard)
        if len(old_unresponded) > 10:
             await send_telegram_message(f"<i>...and {len(old_unresponded)-10} more pending. Check your dashboard/DB.</i>")
    else:
        print("No old unresponded jobs found.")

    print(f"[{datetime.now().strftime('%H:%M:%S')}] Update Complete. Next run in 4 hours.")

async def main():
    """Main loop for the 4-hour scheduler."""
    INTERVAL = 4 * 3600 # 4 hours in seconds
    
    while True:
        start_time = time.time()
        await send_updates()
        
        # Calculate time to sleep until next interval
        elapsed = time.time() - start_time
        sleep_time = max(0, INTERVAL - elapsed)
        
        await asyncio.sleep(sleep_time)

if __name__ == "__main__":
    asyncio.run(main())
