"""Controls — បញ្ជាពីម្ចាស់ផ្ទាល់ (Telegram chat ទៅគណនី userbot)។

Handler នេះរត់ *មុន* logic អតិថិជន៖ សារពី staff (OWNER_ID/ADMIN_IDS) មិនដែលត្រូវបាន
ចាត់ទុកជា inbound អតិថិជនទេ (seller រំលង staff ដូចគ្នា — ការពារពីរជាន់)។
ចម្លើយតបឆ្លងផ្ទាល់ `event.respond` មិនឆ្លង Outbox ទេ — បណ្តាញ control មិនគួរ
 consume budget ការលក់ ឬចូល history AI ឡើយ។
"""
from __future__ import annotations

import asyncio
import logging

from telethon import events

from admin_bot.scope import Scope
from config import settings
from database import crud
from database.session import db_session

log = logging.getLogger("userbot.controls")

HELP = (
    "🎮 បញ្ជាដែលដំណើរការលើគណនីនេះ៖\n"
    "/pause <customer_id> — ផ្អាក AI សម្រាប់អតិថិជនម្នាក់\n"
    "/resume <customer_id> — បន្ត AI\n"
    "/pauseall — ផ្អាក AI គណនីរបស់អ្នកប៉ុណ្ណោះ\n"
    "/resumeall — បើក AI ឡើងវិញ (ដែនកំណត់ដូច /pauseall)\n"
    "/stopbot — ផ្តាច់គណនីទាំងអស់ (Owner តែប៉ុណ្ណោះ)\n"
    "/startbot — ភ្ជាប់ឡើងវិញ (Owner តែប៉ុណ្ណោះ)\n"
    "/status — ស្ថានភាព queue + គណនីក្នុងវិសាលភាពអ្នក"
)
OWNER_ONLY = "⛔ បញ្ជានេះសម្រាប់តែ Owner គត់"


async def may_control(user_id: int) -> bool:
    """Owner, admin ក្នុង .env ឬ ម្ចាស់ហាងដែលចុះឈ្មោះរួច (= auto-register) ប៉ុណ្ណោះ។"""
    if user_id == settings.owner_id or user_id in settings.admin_ids:
        return True
    async with db_session() as session:
        admin = await crud.get_admin(session, user_id)
    return admin is not None and admin.is_active


async def scope_for(user_id: int) -> Scope:
    """វិសាលភាពដូច `admin_bot/access.py` — គ្រប់ម្ចាស់ហាង តាមគណនីរបស់ខ្លួនឯងតែប៉ុណ្ណោះ។"""
    from admin_bot.access import tenant_scope

    return await tenant_scope(user_id, is_owner=user_id == settings.owner_id)


class Controls:
    def __init__(self, account_id: int, *, client, manager) -> None:
        self.account_id = account_id
        self.client = client
        self.manager = manager
        client.add_event_handler(self.on_command, events.NewMessage(incoming=True))

    async def on_command(self, event) -> None:
        if not event.is_private or event.sender_id is None:
            return
        user_id = event.sender_id
        text = (event.text or "").strip()
        if not text.startswith("/"):
            return  # សារធម្មតាពីអតិថិជន — ទុកឱ្យ Seller ឆ្លើយ (មិន query DB)
        if not await may_control(user_id):
            return
        if user_id == settings.owner_id:
            await self._record_owner_identity(event)

        parts = text.split()
        command = parts[0].lower().split("@", 1)[0]  # /pause@somebot → /pause
        args = parts[1:]
        scope = await scope_for(user_id)

        if command == "/pause":
            await self._set_paused(event, args, True, scope)
        elif command == "/resume":
            await self._set_paused(event, args, False, scope)
        elif command in ("/pauseall", "/resumeall"):
            enabled = command == "/resumeall"
            await self._set_paused_all(event, enabled, scope)
        elif command == "/stopbot":
            if not scope.is_owner:
                await event.respond(f"{OWNER_ONLY}\nបញ្ជានេះផ្តាច់គណនីរបស់អ្នកផ្សេងទៀតដោយស្វ័យប្រវត្តិ។")
                return
            await event.respond("🛑 កំពុងផ្តាច់គណនីទាំងអស់…")
            asyncio.create_task(self.manager.global_stop())
        elif command == "/startbot":
            if not scope.is_owner:
                await event.respond(f"{OWNER_ONLY}\nសុំ Owner បើកគណនីឡើងវិញ ឬប្រើ /resumeall សម្រាប់គណនីរបស់អ្នក។")
                return
            await event.respond("▶️ កំពុងភ្ជាប់គណនីឡើងវិញ…")
            asyncio.create_task(self.manager.global_start())
        elif command == "/status":
            await event.respond(self._status_text(scope))
        elif command in ("/help", "/commands"):
            await event.respond(HELP)

    async def _set_paused_all(self, event, enabled: bool, scope: Scope) -> None:
        """Owner បិទ AI ជាន់ global រីឯ Staff ប៉ះតែអតិថិជនក្នុងវិសាលភាពរបស់ខ្លួន។

        Staff មិនត្រូវការ `ai_enabled` global ទេ — វានឹងបិទ AI របស់គណនីអ្នកផ្សេង។
        """
        verb = "បន្ត" if enabled else "ផ្អាក"
        if scope.is_owner:
            async with db_session() as session:
                await crud.set_setting(session, "ai_enabled", "on" if enabled else "off")
                # /pauseall មិនប៉ះ flag រាល់អតិថិជនទេ ទើប per-customer pause ចាស់មិនបាត់
                cleared = await crud.pause_all_customers(session, paused=False) if enabled else 0
            note = "" if enabled else " — សារអតិថិជន នៅតែត្រូវរក្សាទុក"
            extra = f"\nលើក per-customer pause {cleared} រូប" if enabled else ""
            await event.respond(f"🤖 AI ទាំងអស់ ត្រូវបាន{verb}{note}{extra}")
            return
        if not scope.has_accounts:
            await event.respond(
                "⛔ អ្នកមិនទាន់មានគណនីរបស់ខ្លួនទេ — បើក Panel ចុច ➕ បន័ែមគណនី ឬវាយ <code>/addsession</code>"
            )
            return
        async with db_session() as session:
            changed = await crud.pause_all_customers(session, paused=not enabled, account_ids=scope.ids)
        await event.respond(
            f"⏯ {verb} AI អតិថិជន {changed} រូប ក្នុងគណនីរបស់អ្នក "
            f"({len(scope.ids)} គណនី)\nគណនីអ្នកផ្សេង មិនត្រូវបានប៉ះទេ"
        )

    async def _record_owner_identity(self, event) -> None:
        """ម្ចាស់ផ្ញើសារពី userbot ម្តង → រក្សាទុក @username ពិត (display ក្នុង catalog contact)។"""
        entity = getattr(event, "chat", None)
        username = getattr(entity, "username", None)
        if not username:
            return
        async with db_session() as session:
            if (await crud.get_setting(session, "owner_username")) != username:
                await crud.set_setting(session, "owner_username", username)

    async def _set_paused(self, event, args: list[str], paused: bool, scope: Scope) -> None:
        if not args or not args[0].lstrip("-").isdigit():
            await event.respond("✏️ ប្រើ៖ /pause <customer_id> ឧ. /pause 555000111")
            return
        telegram_id = int(args[0])
        async with db_session() as session:
            customer = await crud.get_customer_by_telegram(session, telegram_id, account_ids=scope.ids)
            if customer is None:
                if await crud.get_customer_by_telegram(session, telegram_id) is None:
                    await event.respond(f"🔍 រកមិនឃើញអតិថិជន {telegram_id} ទេ")
                else:
                    # IDOR — row មាន ប៉ុន្តែក្រៅវិសាលភាពរបស់អ្នក
                    log.warning("IDOR: user=%s ព្យាយាម /pause អតិថិជន %s ក្រៅវិសាលភាព", scope.admin_id, telegram_id)
                    await event.respond(f"🔒 អតិថិជន {telegram_id} មិនមែនរបស់គណនីអ្នកទេ")
                return
            await crud.set_customer_flag(session, customer.id, ai_paused=paused)
        verb = "ផ្អាក" if paused else "បន្ត"
        note = " — AI នឹងមិនឆ្លើយរហូតដល់ /resume" if paused else ""
        await event.respond(f"⏯ {verb} AI សម្រាប់អតិថិជន {telegram_id}{note}")

    def _status_text(self, scope: Scope) -> str:
        info = self.manager.status()
        allowed = set(scope.ids)  # គ្រប់ម្ចាស់ហាង រួមទាំង Owner ឃើញតែគណនីរបស់ខ្លួន
        queues = {account_id: depth for account_id, depth in info["queues"].items() if account_id in allowed}
        lines = [
            f"📊 {scope.label()} · គណនីរបស់អ្នកកំពុងរត់៖ {len(queues)} · "
            f"{'AI global បិទ' if info['global_stopped'] else 'AI global បើក'}"
        ]
        for account_id, depth in sorted(queues.items()):
            lines.append(f" · គណនី #{account_id} — ជួររង់ចាំ {depth}")
        return "\n".join(lines)
