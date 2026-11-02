"""ការពារ Panel — គត់ Owner និង Admin ដែលបានរក្សាទុកក្នុង DB ប៉ុណ្ណោះ។

អ្នកប្រើអនាមិកទទួលបាន ការលុបចោលស្ងាត់ៗ (Bot token អាចរីករាលដាលបាន ដូច្នេះ
Panel មិនគួរបង្ហាញអ្វីឡើយសម្រាប់គេ)។
"""
from __future__ import annotations

import logging

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message

from config import settings
from admin_bot.scope import Scope, owner_scope
from database import crud, db_session

log = logging.getLogger("admin.access")

Event = Message | CallbackQuery


def user_id_of(event: Event) -> int | None:
    user = getattr(event, "from_user", None)
    return user.id if user is not None else None


class StaffGate(BaseMiddleware):
    """Outer middleware ចម្រោះ update ទាំងអស់ មុនចូល handler។

    រាល់ update ដែលឆ្លង gate នេះ ទទួលបាន `data["scope"]` ដោយ aiogram ចាក់ទៅ
    parameter ឈ្មោះ `scope` ក្នុង handler — គ្មាន handler ណាត្រូវ query ខ្លួនឯងទេ។
    """

    async def __call__(self, handler, event: Event, data: dict):
        user_id = user_id_of(event)
        if user_id is None:
            return None
        chat = getattr(event, "chat", None) or getattr(getattr(event, "message", None), "chat", None)
        if chat is None or chat.type != "private":
            return None

        data["user_id"] = user_id
        if user_id == settings.owner_id:
            data["is_owner"] = True
            data["scope"] = owner_scope()
            return await handler(event, data)

        data["is_owner"] = False
        staff = user_id in settings.admin_ids
        if not staff:
            async with db_session() as session:
                staff = await crud.is_staff(session, user_id)
        if staff:
            async with db_session() as session:
                account_ids = await crud.owned_account_ids(session, user_id)
            data["scope"] = Scope(admin_id=user_id, is_owner=False, account_ids=account_ids)
            return await handler(event, data)

        log.info(
            "បដិសេធ update ពី user %s (មិនមែន staff) — បើគេជា Staff ជំនួយ: Panel → 🔐 Admins → ➕ បញ្ចូល ID %s",
            user_id, user_id,
        )
        return None
