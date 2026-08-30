"""Telegram bot listener with scheduled job fetching."""

from datetime import datetime
import asyncio

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from job_hunter_lib.config import TELEGRAM_BOT_TOKEN
from job_hunter_lib.database import (
    get_job_from_db,
    get_jobs_by_status,
    get_unresponded_jobs,
    save_job_response,
)
from job_hunter_lib.jobs import fetch_jobs
from job_hunter_lib.telegram_client import format_job_message, get_job_keyboard, send_telegram_message

version = "1.0.3" #abra jobs

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Parse callback data and save to MongoDB."""
    query = update.callback_query
    await query.answer()

    data = query.data
    action, job_id = data.split("_", 1)
    user_id = query.from_user.id

    status_map = {"applied": "applied", "notapplied": "not_applied", "remind": "remind"}
    status = status_map.get(action, "unknown")

    save_job_response(user_id, job_id, status)

    if status == "remind":
        job = get_job_from_db(job_id)
        job_title = job.get("title", job_id) if job else job_id
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=f"I'll remind you later about: {job_title}",
        )
        return

    await query.edit_message_reply_markup(reply_markup=None)
    await context.bot.send_message(chat_id=query.message.chat_id, text="Response saved.")


async def send_remind_jobs(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    """Send jobs marked for reminder to the current Telegram chat."""
    remind_jobs = get_jobs_by_status("remind")
    if not remind_jobs:
        await context.bot.send_message(chat_id=chat_id, text="No reminder jobs right now.")
        return

    await context.bot.send_message(
        chat_id=chat_id,
        text=f"You have {len(remind_jobs)} reminder jobs.",
    )
    for job in remind_jobs:
        await context.bot.send_message(
            chat_id=chat_id,
            text="<b>REMINDER</b>\n" + format_job_message(job),
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=get_job_keyboard(job["job_id"]),
        )


async def remind_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /remind command."""
    message = update.effective_message
    if message is None:
        return
    await send_remind_jobs(message.chat_id, context)


async def remind_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle plain-text remind messages."""
    message = update.effective_message
    if message is None or not message.text:
        return
    if message.text.strip().lower() != "remind":
        return
    await send_remind_jobs(message.chat_id, context)


async def scheduled_fetch_task(context: ContextTypes.DEFAULT_TYPE):
    """Fetch new jobs and send pending-response nudges."""
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Starting Scheduled Update...")
    await send_telegram_message("Starting Scheduled Update... " + datetime.now().strftime('%H:%M:%S'))

    try:
        jobs, sent_count = await fetch_jobs(return_stats=True)
        print(
            f"[{datetime.now().strftime('%H:%M:%S')}] "
            f"Job fetch completed. Fetched {len(jobs)} jobs, sent {sent_count} to Telegram."
        )
        # await send_telegram_message(f"<b>Update:</b> Job fetch completed at {datetime.now().strftime('%H:%M:%S')}")
    except Exception as exc:
        print(f"Error during job fetch: {exc}")

    unresponded = get_unresponded_jobs()
    current_time = datetime.utcnow()
    old_unresponded = [
        job
        for job in unresponded
        if (current_time - job.get("last_seen", current_time)).total_seconds() > 3600
    ]

    if old_unresponded:
        await send_telegram_message(
            f"<b>PENDING: {len(old_unresponded)} jobs waiting for a response!</b>"
        )
        for job in old_unresponded[:5]:
            await send_telegram_message(
                "<b>PENDING</b>\n" + format_job_message(job),
                reply_markup=get_job_keyboard(job["job_id"]),
            )
    await send_telegram_message("Scheduled Update completed at " + datetime.now().strftime('%H:%M:%S'))


def main():
    """Start the bot application."""
    print("version: ", version)
    asyncio.run(send_telegram_message("Bot started version: " + version))
    print("Starting Merged Job Hunter (Polling + Scheduler)...")
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CallbackQueryHandler(handle_callback))
    application.add_handler(CommandHandler("remind", remind_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, remind_text_message))

    job_queue = application.job_queue
    job_queue.run_repeating(scheduled_fetch_task, interval=14400, first=10)

    application.run_polling()


if __name__ == "__main__":
    main()
