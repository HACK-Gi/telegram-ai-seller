"""ការពារ Panel + Auto-register — គ្រប់អ្នកប្រើ Telegram ជា «ម្ចាស់ហាង» (Tenant) ផ្ទាល់ខ្លួន។

បើមិនទាន់មាន row ក្នុងតារាង `admins` → បង្កើតឱ្យភ្លាមនៅពេលគេចុច `/start` ហើយគេ
បាន Scope ដែលគត់ទិន្នន័យរបស់ខ្លួនឯង។ មិនមាន «Add Admin» មុនទៀតទេ។

ការពារការរំលោភ (auto-register បិទទ្វារឱ្យគ្រប់គ្នា)៖
* គ្មាន Bot ចូល (bot មិនក្លាយជា tenant) និងគ្មាន chat ក្រុម (private តែប៉ុណ្ណោះ)។
* ចំនួន tenant ថ្មីក្នុងមួយម៉ោង (`MAX_NEW_TENANTS_PER_HOUR`) — លើសពីនេះ drop ស្ងាត់ៗ
  ជំនួសឱ្យបង្កើត row រាប់ម៉ឺនក្នុង DB ក្នុងពេលខ្លី។
* `is_active=False` (Owner លុប Admin) → ត្រឡប់ជាអ្នកប្រើអនាមិកវិញ ហើយមិន auto-register ឡើងវិញ។
"""
from __future__ import annotations

import logging
import time
from collections import deque

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message

from config import settings
from admin_bot.scope import Scope
from database import crud, db_session

log = logging.getLogger("admin.access")

Event = Message | CallbackQuery

# tenant ថ្មីច្រើនពេកក្នុងមួយ ១ ម៉ោង = ទំនងជា spam → បិទទ្វាររហូតដល់វិនាទីចាស់បាត់
MAX_NEW_TENANTS_PER_HOUR = 60
_WINDOW: deque[float] = deque()


def _registration_allowed() -> bool:
    now = time.monotonic()
    while _WINDOW and now - _WINDOW[0] > 3600:
        _WINDOW.popleft()
    if len(_WINDOW) >= MAX_NEW_TENANTS_PER_HOUR:
        return False
    _WINDOW.append(now)
    return True


# បញ្ជាដែល «ថ្លៃ» ក្នុងមួយ user — addsession ភ្ជាប់គណនីពិត ហើយត្រូវ Telegram rate-limit
MAX_SESSION_ADDS_PER_HOUR = 10
_USER_ACTIONS: dict[int, deque[float]] = {}


def action_allowed(user_id: int, *, limit: int = MAX_SESSION_ADDS_PER_HOUR, window: float = 3600.0) -> bool:
    """Sliding window ក្នុង memory — ការពារ spam មិនឱ្យសន្សំ pending login ច្រើនពេក។"""
    stamps = _USER_ACTIONS.setdefault(int(user_id), deque(maxlen=limit))
    now = time.monotonic()
    while stamps and now - stamps[0] > window:
        stamps.popleft()
    if len(stamps) >= limit:
        return False
    stamps.append(now)
    return True


def reset_rate_limits() -> None:
    _WINDOW.clear()
    _USER_ACTIONS.clear()


def user_id_of(event: Event) -> int | None:
    user = getattr(event, "from_user", None)
    return user.id if user is not None else None


async def tenant_scope(user_id: int, *, is_owner: bool) -> Scope:
    """វិសាលភាពពិតរបស់ tenant ម្នាក់ — គណនី + ទិន្នន័យដែល derive ពីគណនីរបស់គេតែប៉ុណ្ណោះ។"""
    async with db_session() as session:
        account_ids = await crud.owned_account_ids(session, user_id)
    return Scope(admin_id=user_id, is_owner=is_owner, account_ids=account_ids)


class StaffGate(BaseMiddleware):
    """Outer middleware លើ update ទាំងអស់ មុន handler — ចាក់ `data["scope"]` ជានិច្ច។

    រាល់ update ទទួលបាន `data["scope"]` ដោយ aiogram ចាក់ទៅ parameter ឈ្មោះ `scope`
    ក្នុង handler ទើបគ្មាន handler ណាត្រូវ query ខ្លួនឯងទេ។
    """

    async def __call__(self, handler, event: Event, data: dict):
        user = getattr(event, "from_user", None)
        if user is None or user.is_bot:
            return None
        user_id = user.id
        chat = getattr(event, "chat", None) or getattr(getattr(event, "message", None), "chat", None)
        if chat is None or chat.type != "private":
            return None

        data["user_id"] = user_id
        is_owner = user_id == settings.owner_id
        data["is_owner"] = is_owner

        async with db_session() as session:
            admin = await crud.get_admin(session, user_id)
            if admin is not None and not admin.is_active:
                log.info("បដិសេធ user %s — Admin ត្រូវបានបិទ (is_active=False)", user_id)
                return None
            if admin is None:
                # Owner/Admin ក្នុង .env ចូលបានទោះ DB ទំនេរ កុំឱ្យ rate-limit ដាក់គេ
                if not (is_owner or user_id in settings.admin_ids) and not _registration_allowed():
                    log.warning("បដិសេធ auto-register %s — ដល់កម្រិត %d tenant/ម៉ោង",
                                user_id, MAX_NEW_TENANTS_PER_HOUR)
                    return None
                admin = await crud.auto_register_user(
                    session, user_id, first_name=user.first_name or "", username=user.username or ""
                )

        data["scope"] = await tenant_scope(user_id, is_owner=is_owner)
        return await handler(event, data)
