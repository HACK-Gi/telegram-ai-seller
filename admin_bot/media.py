"""ការដាក់រូបភាពឱ្យស្ថិតក្នុង media/ សម្រាប់ Bot និង Userbot ទាំងសងខាង។

Bot API `file_id` អាចប្រើបានតែដោយ bot ដដែលប៉ុណ្ណោះ ដូច្នេះពេលអ្នកប្រើ upload
យើងរក្សាទុកទាំង file_id (សម្រាប់ Panel) និងឯកសារនៅលើ disk (សម្រាប់ Telethon)។
"""
from __future__ import annotations

import logging
from pathlib import Path

from aiogram import Bot
from aiogram.types import Message

from helpers import esc
from userbot.safety import describe_error

log = logging.getLogger("admin.media")


async def save_message_photo(message: Message, directory: Path, stem: str, index: int = 0) -> tuple[str, str]:
    """ទាញយករូបភាពចុងក្រោយពីសារ → media/ ត្រឡប់ (file_id, path)។"""
    photo = message.photo[-1]
    destination = directory / f"{stem}_{index}.jpg"
    await message.bot.download(photo.file_id, destination=destination)
    return photo.file_id, str(destination)


async def save_message_document(message: Message, directory: Path, stem: str) -> tuple[str, str]:
    """សម្រាប់ Slip ដែលអតិថិជនផ្ញើជាឯកសារ (មិនមែន photo)។"""
    document = message.document
    assert document is not None
    suffix = Path(document.file_name or "slip").suffix or ".bin"
    destination = directory / f"{stem}{suffix}"
    await message.bot.download(document.file_id, destination=destination)
    return document.file_id, str(destination)


async def send_photo_to_admin(bot: Bot, chat_id: int, file_id: str, caption: str) -> None:
    try:
        await bot.send_photo(chat_id=chat_id, photo=file_id, caption=caption)
    except Exception as exc:  # TelegramAPIError / រូបបាត់
        log.warning("មិនអាចផ្ញើរូប %s បាន: %s", file_id[:16], describe_error(exc))
        await bot.send_message(chat_id=chat_id, text=f"⚠️ រូបភាពមិនអាចបើកបានទេ ({esc(caption)})")
