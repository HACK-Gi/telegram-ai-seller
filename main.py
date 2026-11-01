"""ចំណុចចូល — ដំណើរការដោយ `python main.py`។

ជំហានទី ១៖ Admin Bot (Aiogram) + កិច្ចស្វ័យប្រវត្តិ។
ជំហានទី ២៖ userbot (Telethon multi-account) រត់ក្នុង process តែមួយ —
          ភ្ជាប់លុះត្រាតែមាន TG_API_ID/TG_API_HASH ក្នុង .env។
"""
from __future__ import annotations

import asyncio
import logging
import sys
from logging.handlers import RotatingFileHandler

from config import LOG_DIR, settings

log = logging.getLogger("main")


def setup_logging() -> None:
    """សរសេរ logs/app.log (៥MB × ៥ កំណាត់) + console។

    គ្មាន session string ឬ OTP ត្រូវចូល log ឡើយ — `SecretRedactor` ជា filter តែមួយគត់
    ដែលធានាបាន ទោះកំហុសបញ្ចេញ repr នៃ request (មានអត្ថបទសារ/លេខទូរស័ព្ទ) ក៏ដោយ។
    """
    from userbot.safety import SecretRedactor

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s | %(levelname)-7s | %(name)s | %(message)s")

    file_handler = RotatingFileHandler(LOG_DIR / "app.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8")
    file_handler.setFormatter(formatter)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    root.handlers.clear()
    redactor = SecretRedactor()
    file_handler.addFilter(redactor)
    console_handler.addFilter(redactor)
    root.addHandler(file_handler)
    root.addHandler(console_handler)

    for noisy in ("aiogram.event", "aiogram.dispatcher", "apscheduler.executors.default", "aiosqlite"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


async def run() -> None:
    setup_logging()
    from admin_bot.bot import build_dispatcher, create_bot, is_mock  # ព្យាយាម import ក្រោយ logging រួច
    from database.session import init_db
    from services.scheduler import build_scheduler, describe_jobs

    log.info("ចាប់ផ្តើម Telegram AI Auto-Seller · AI backend = %s · timezone = %s", settings.ai_backend, settings.timezone)
    await init_db()
    log.info("ទិន្នន័យដំបូងរួចរាល់ (តារាង + settings លំនាំដើម)")

    bot = create_bot()
    dispatcher = build_dispatcher()
    scheduler = build_scheduler(bot)
    scheduler.start()
    for line in describe_jobs(scheduler):
        log.info("កិច្ចស្វ័យប្រវត្តិ %s", line)

    if is_mock():
        message = (
            "MOCK mode — គ្មាន BOT_TOKEN ពិត ដូច្នេះមិនអាច poll Telegram បានទេ។\n"
            "សាកល្បង panel ដោយ៖ python scripts/smoke_test.py\n"
            "ដំណើរការពិត៖ ដាក់ BOT_TOKEN ក្នុង .env រួច បើក `python main.py`"
        )
        log.warning(message)
        print(message)
        scheduler.shutdown(wait=False)
        await bot.session.close()
        return

    # Userbot ត្រូវចាប់ផ្តើមជានិច្ច៖ api_id/api_hash ជារបស់គណនីនីមួយៗ (my.telegram.org) ដូច្នេះ
    # .env ទទេមិនមែនជាឧបសគ្គទៀតទេ — manager ភ្ជាប់តែគណនីដែលមាន creds ប៉ុណ្ណោះ។
    from userbot.manager import get_manager

    async def notify_owner(text: str) -> None:
        await bot.send_message(settings.owner_id, text)

    manager = get_manager(notify=notify_owner)
    await manager.start()
    if not (settings.tg_api_id and settings.tg_api_hash):
        log.info("គ្មាន TG_API_ID/TG_API_HASH ក្នុង .env — ប្រើ credentials របស់គណនីនីមួយៗជំនួស")

    try:
        await dispatcher.start_polling(bot, allowed_updates=dispatcher.resolve_used_update_types())
    finally:
        from userbot.chat_login import get_coordinator

        await get_coordinator().shutdown()
        if manager is not None:
            await manager.shutdown()
        scheduler.shutdown(wait=False)
        await bot.session.close()
        log.info("បិទ Admin Bot + Userbot រួចរាល់")


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\nបានបិទដោយសន្តិវិឌី (Ctrl+C)")
    except Exception as exc:  # noqa: BLE001
        log.exception("ចាប់ផ្តើមមិនបាន: %s", exc)
        sys.exit(1)
