"""បង្កើត Bot + Dispatcher សម្រាប់ Admin Panel។"""
from __future__ import annotations

import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import ErrorEvent

from admin_bot.access import StaffGate
from admin_bot.handlers import all_routers
from admin_bot.mock import MockSession
from config import settings

log = logging.getLogger("admin.bot")
MOCK_TOKEN = "123456:MOCKBOTMOCKBOTMOCKBOT"


def is_mock() -> bool:
    return settings.use_mock_bot or settings.bot_token in ("", "MOCK")


def create_bot() -> Bot:
    """Bot ពិត ឬ Mock (នៅពេលគ្មាន Token ដើម្បីសាកល្បង Panel)។"""
    defaults = DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True)
    if is_mock():
        log.warning("⚠️ Bot កំពុងដំណើរការក្នុង MOCK mode — គ្មានសារពិតចេញទៅ Telegram ទេ")
        return Bot(token=MOCK_TOKEN, session=MockSession(), default=defaults)
    return Bot(token=settings.bot_token, default=defaults)


def build_dispatcher() -> Dispatcher:
    dispatcher = Dispatcher()
    dispatcher.errors.register(on_error)

    # Outer middleware ចម្រោះ អ្នកប្រើអនាមិក មុន handler ណាមួយដំណើរការ
    dispatcher.message.outer_middleware(StaffGate())
    dispatcher.callback_query.outer_middleware(StaffGate())

    for router in all_routers:
        dispatcher.include_router(router)
    return dispatcher


async def on_error(event: ErrorEvent) -> bool:
    """កុំឱ្យ កំហុសតែមួយ បិទ Panel ទាំងមូល — បង្ហាញសារសាមញ្យ ជូន owner។

    Log តែ *ឈ្មោះ* class (+ លេខ code/seconds បើមាន) ប៉ុណ្ណោះ មិនដែលបង្ហាញ
    `str(exception)` ទេ ព្រោះ repr របស់ Telethon/aiogram បញ្ចូលទាំង អត្ថបទសារ
    និងលេខទូរស័ព្ទ/OTP ដែលកំពុង flow login ក្នុង chat នេះ។
    """
    from userbot.safety import describe_error

    exc = event.exception
    # «message is not modified» = ចុចប៊ូតុងដដែល ២ ដង មិនមែនកំហុសទេ (កុំបង្កជារាយការណ៍)
    if isinstance(exc, TelegramBadRequest) and "not modified" in str(exc):
        log.debug("edit មិនប្តូរអ្វី — រំលង")
        return True

    log.error("កំហុសក្នុង update: %s", describe_error(event.exception))
    cause = getattr(event.exception, "__cause__", None)
    if cause is not None:
        log.error("  ប្រភព: %s", describe_error(cause))
    # Traceback មានតែពេល owner បើក LOG_LEVEL=debug — វាឆ្លង SecretRedactor ដូចគ្នា
    log.debug("កំហុសក្នុង update (traceback)", exc_info=event.exception)
    if event.update.message is not None and not is_mock():
        try:
            await event.update.message.answer("⛔ មានកំហុសបន្តិច — សូមព្យាយាមម្ដងទៀត ឬវាយ /menu")
        except Exception:  # noqa: BLE001
            return True
    return True
