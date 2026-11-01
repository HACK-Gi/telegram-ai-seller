"""សិទ្ធិ Owner តែម្នាក់ឯង — សម្រាប់ផ្នែកដែលប៉ះទិន្នន័យ global ទាំងមូល។

គោលការណ៍៖ **default ជាបិទ**។ យើងមិនសរសេរ `if not scope.is_owner: return` ក្នុង
គ្រប់ handler ទេ (ងាយភ្លេច ហើយការស្ងាត់ធ្វើឱ្យ staff គិតថា Panel ខូច) គិតជា
`OwnerGate` (outer middleware លើ router ទាំងមូល — settings/prompt) ឬ `OwnerOnly`
(filter ក្នុងកម្រិត handler — សម្រាប់ router ដែល read បើកឱ្យ staff តែ write បិទ
ដូច categories) ទាំងពីរបដិសេធដោយបង្ហាញហេតុផលច្បាស់លាស់។
"""
from __future__ import annotations

import logging

from aiogram import BaseMiddleware
from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, Message

from admin_bot.scope import Scope

log = logging.getLogger("admin.owner_gate")

REFUSAL = "🔒 ផ្នែកនេះមានតែ <b>ម្ចាស់ (Owner)</b> ប៉ុណ្ណោះ។\nប្រសិនបើត្រូវការប្ដូរ សូមទាក់ទងម្ចាស់។"


async def refuse(event: CallbackQuery | Message) -> None:
    """ប្រាប់ staff មូលហេតុជំនួសការស្ងាត់ (callback មិនត្រូវការ HTML)។"""
    if isinstance(event, CallbackQuery):
        await event.answer(REFUSAL.replace("<b>", "").replace("</b>", ""), show_alert=True)
    else:
        await event.answer(REFUSAL)


class OwnerGate(BaseMiddleware):
    """ដាក់លើ router (settings/prompt/admins/backup) — staff ទទួលបានការបដិសេធ។"""

    async def __call__(self, handler, event: CallbackQuery | Message, data: dict):
        scope: Scope | None = data.get("scope")
        if scope is not None and scope.is_owner:
            return await handler(event, data)

        log.info("បដិសេធ right-owner ពី user %s → %s", data.get("user_id"), type(event).__name__)
        await refuse(event)
        return None


class OwnerOnly(BaseFilter):
    """ដាក់លើ handler write នីមួយៗ — read នៅសល់សម្រាប់ staff។

    ត្រូវការ `scope` ដែល StaffGate ចាក់ឱ្យរាល់ update ដូច្នេះ filter មិន DB hit ទេ។
    """

    async def __call__(self, event: CallbackQuery | Message, scope: Scope) -> bool:
        if scope.is_owner:
            return True
        log.info("បដិសេធ right-write ពី user %s", scope.admin_id)
        await refuse(event)
        return False
