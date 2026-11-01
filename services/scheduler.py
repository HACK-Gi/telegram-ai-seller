"""⏰ កិច្ចស្វ័យប្រវត្តិ — របាយការណ៍ប្រចាំថ្ងៃ/សប្តាហ៍, Backup រាល់ ២៤ ម៉ោង និងជូនដំណឹង Stock តិច។

គ្រប់ job ត្រូវហ្វ័រព័ទ្ធដោយ try/except៖ កិច្ចមួយបរាជ័យ មិនត្រូវបញ្ឈប់ scheduler ទាំងមូលទេ។
"""
from __future__ import annotations

import logging

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from config import settings
from database import crud, db_session
from helpers import esc, local_tz, utcnow
from services import backup as backup_service
from services.reports import build_report

log = logging.getLogger("services.scheduler")

REPORT_HOUR = 21  # របាយការណ៍ប្រចាំថ្ងៃ ម៉ោង ២១:០០ តាមម៉ោងក្នុងស្រុក
WEEKLY_DAY = "mon"
WEEKLY_HOUR = 9
BACKUP_INTERVAL_HOURS = 24
STOCK_SCAN_MINUTES = 30
MISFIRE_GRACE = 3600  # បើម៉ាស៊ីនបិទខ្លី គួររត់ជូន once នៅពេលបើកមកវិញ


async def _send_owner(bot: Bot, text: str) -> None:
    """ផ្ញើទៅម្ចាស់ — កំហុសបណ្តាញ មិនត្រូវផ្តាច់ job ទេ។"""
    try:
        await bot.send_message(chat_id=settings.owner_id, text=text)
    except Exception as exc:  # noqa: BLE001
        log.warning("មិនអាចផ្ញើសារជូន owner បានទេ: %s", exc)


async def daily_report(bot: Bot) -> None:
    """របាយការណ៍ចុងថ្ងៃ (ចំណូល + Order + អតិថិជន) រាល់ ២១:០០។"""
    try:
        async with db_session() as session:
            text = await build_report(session, "today")
        await _send_owner(bot, text)
        log.info("បានផ្ញើរបាយការណ៍ប្រចាំថ្ងៃ")
    except Exception:  # noqa: BLE001
        log.exception("កិច្ច daily_report បរាជ័យ")


async def weekly_report(bot: Bot) -> None:
    """សេចក្តីសង្ខេបសប្តាហ៍ ថ្ងៃចន្ទ ព្រឹក។"""
    try:
        async with db_session() as session:
            text = await build_report(session, "week")
        await _send_owner(bot, f"📅 <b>សប្តាហ៍មុន</b>\n{text}")
        log.info("បានផ្ញើរបាយការណ៍ប្រចាំសប្តាហ៍")
    except Exception:  # noqa: BLE001
        log.exception("កិច្ច weekly_report បរាជ័យ")


async def auto_backup() -> None:
    """ចម្លងឯកសារ DB រាល់ ២៤ ម៉ោង ទុកកំណាត់ចុងក្រោយ ១៤។"""
    try:
        path = await backup_service.create_backup("auto")
        log.info("backup ស្វ័យប្រវត្តិរួចរាល់: %s", path.name)
    except Exception:  # noqa: BLE001
        log.exception("កិច្ច auto_backup បរាជ័យ")


async def low_stock_watch(bot: Bot) -> None:
    """ជូនដំណឹង Stock តិច តែម្តងក្នុងមួយថ្ងៃ ក្នុងមួយផលិតផល (មិន spam)។"""
    try:
        async with db_session() as session:
            threshold = int(await crud.get_setting(session, "stock_alert_threshold") or 5)
            alerted = await crud.get_json_setting(session, "low_stock_alerted", {})
            low = await crud.low_stock_products(session, threshold)

            today = utcnow().strftime("%Y-%m-%d")
            lines: list[str] = []
            for product, remaining in low:
                key = str(product.id)
                if alerted.get(key) == today:
                    continue
                alerted[key] = today
                lines.append(f"· <b>{esc(product.name)}</b> — សល់ <code>{remaining}</code>")

            # ផលិតផលដែលបញ្ចូល stock គ្រប់គ្រាន់វិញ ត្រូវលុបចេញពីបញ្ជីជូនដំណឹង
            still_low = {str(item.id) for item, _ in low}
            alerted = {key: value for key, value in alerted.items() if key in still_low}
            await crud.set_json_setting(session, "low_stock_alerted", alerted)

        if lines:
            await _send_owner(
                bot,
                f"⚠️ <b>Stock តិចជាង {threshold}</b>\n" + "\n".join(lines) + "\n\nសូមបញ្ចូល Code បន្ថែម 📦",
            )
    except Exception:  # noqa: BLE001
        log.exception("កិច្ច low_stock_watch បរាជ័យ")


def build_scheduler(bot: Bot) -> AsyncIOScheduler:
    """រៀបចំកិច្ចស្វ័យប្រវត្តិទាំងអស់ (របាយការណ៍ ២ + backup + stock watch) — មិនទាន់ start។"""
    timezone = local_tz()
    scheduler = AsyncIOScheduler(timezone=timezone)
    scheduler.add_job(
        daily_report,
        CronTrigger(hour=REPORT_HOUR, minute=0, timezone=timezone),
        args=[bot],
        id="daily_report",
        coalesce=True,
        max_instances=1,
        misfire_grace_time=MISFIRE_GRACE,
    )
    scheduler.add_job(
        weekly_report,
        CronTrigger(day_of_week=WEEKLY_DAY, hour=WEEKLY_HOUR, minute=0, timezone=timezone),
        args=[bot],
        id="weekly_report",
        coalesce=True,
        max_instances=1,
        misfire_grace_time=MISFIRE_GRACE,
    )
    scheduler.add_job(
        auto_backup,
        IntervalTrigger(hours=BACKUP_INTERVAL_HOURS),
        id="auto_backup",
        coalesce=True,
        max_instances=1,
        misfire_grace_time=MISFIRE_GRACE,
    )
    scheduler.add_job(
        low_stock_watch,
        IntervalTrigger(minutes=STOCK_SCAN_MINUTES),
        args=[bot],
        id="low_stock_watch",
        coalesce=True,
        max_instances=1,
        misfire_grace_time=STOCK_SCAN_MINUTES * 60,
    )
    return scheduler


def describe_jobs(scheduler: AsyncIOScheduler) -> list[str]:
    """បង្ហាញម៉ោងដែលកិច្ចនឹងដំណើរការបន្ទាប់ (ត្រូវប្រើពេល boot, ម៉ោងក្នុងស្រុក)។"""
    timezone = local_tz()
    return [
        f"· {job.id} → {job.next_run_time.astimezone(timezone).strftime('%d/%m/%Y %H:%M')}"
        for job in scheduler.get_jobs()
        if job.next_run_time
    ]
