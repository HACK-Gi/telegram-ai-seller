"""OwnerGate — router ទាំងអស់ដែលទាក់ទង *រ-global settings* ត្រូវតែ owner តែប៉ុណ្ណោះ។

មិនប្រើ `if not scope.is_owner: return` ក្នុងគ្រប់ handler ទេ (ងាយភ្លេច) គិតជា outer
middleware លើ router មួយ ទាំងមូល ហើយបដិសេធដោយ**បង្ហាញហេតុផលច្បាស់លាស់** ជំនួស
ការស្ងាត់ ដើម្បី staff ដឹងថាត្រូវសុំ owner មិនមែន Panel ខូចទេ។
"""
from __future__ import annotations

import logging

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message

from admin_bot.scope import Scope

log = logging.getLogger("admin.owner_gate")

REFUSAL = "🔒 ផ្នែកនេះមានតែ <b>ម្ចាស់ (Owner)</b> ប៉ុណ្ណោះ។\nប្រសិនបើត្រូវការប្ដូរ សូមទាក់ទងម្ចាស់។"


class OwnerGate(BaseMiddleware):
    """ដាក់លើ router (settings/prompt/admins/backup) — staff ទទួលបានការបដិសេធ។"""

    async def __call__(self, handler, event: CallbackQuery | Message, data: dict):
        scope: Scope | None = data.get("scope")
        if scope is not None and scope.is_owner:
            return await handler(event, data)

        user_id = data.get("user_id")
        log.info("បដិសេធ right-owner ពី user %s → %s", user_id, type(event).__name__)
        if isinstance(event, CallbackQuery):
            await event.answer(REFUSAL.replace("<b>", "").replace("</b>", ""), show_alert=True)
        elif isinstance(event, Message):
            await event.answer(REFUSAL)
        return None
