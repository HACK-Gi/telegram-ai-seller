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

from config import settings
from database import crud
from database.session import db_session

log = logging.getLogger("userbot.controls")

HELP = (
    "🎮 បញ្ជាដែលដំណើរការលើគណនីនេះ៖\n"
    "/pause <customer_id> — ផ្អាក AI សម្រាប់អតិថិជនម្នាក់\n"
    "/resume <customer_id> — បន្ត AI\n"
    "/pauseall — ផ្អាក AI គ្រប់គណនី\n"
    "/resumeall — បើក AI ឡើងវិញ\n"
    "/stopbot — ផ្តាច់គណនីទាំងអស់\n"
    "/startbot — ភ្ជាប់ឡើងវិញ\n"
    "/status — ស្ថានភាព queue + គណនី"
)


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
        if user_id != settings.owner_id and user_id not in settings.admin_ids:
            return  # មិនមែន staff — ទុកឱ្យ Seller
        if user_id == settings.owner_id:
            await self._record_owner_identity(event)
        text = (event.text or "").strip()
        if not text.startswith("/"):
            return

        parts = text.split()
        command = parts[0].lower().split("@", 1)[0]  # /pause@somebot → /pause
        args = parts[1:]

        if command == "/pause":
            await self._set_paused(event, args, True)
        elif command == "/resume":
            await self._set_paused(event, args, False)
        elif command in ("/pauseall", "/resumeall"):
            enabled = command == "/resumeall"
            async with db_session() as session:
                await crud.set_setting(session, "ai_enabled", "on" if enabled else "off")
            await event.respond(f"🤖 AI ទាំងអស់ ត្រូវបាន{'បន្ត' if enabled else 'ផ្អាក'}" + ("" if enabled else " — សារអតិថិជន នៅតែត្រូវរក្សាទុក"))
        elif command == "/stopbot":
            await event.respond("🛑 កំពុងផ្តាច់គណនីទាំងអស់…")
            asyncio.create_task(self.manager.global_stop())
        elif command == "/startbot":
            await event.respond("▶️ កំពុងភ្ជាប់គណនីឡើងវិញ…")
            asyncio.create_task(self.manager.global_start())
        elif command == "/status":
            await event.respond(self._status_text())
        elif command in ("/help", "/commands"):
            await event.respond(HELP)

    async def _record_owner_identity(self, event) -> None:
        """ម្ចាស់ផ្ញើសារពី userbot ម្តង → រក្សាទុក @username ពិត (display ក្នុង catalog contact)។"""
        entity = getattr(event, "chat", None)
        username = getattr(entity, "username", None)
        if not username:
            return
        async with db_session() as session:
            if (await crud.get_setting(session, "owner_username")) != username:
                await crud.set_setting(session, "owner_username", username)

    async def _set_paused(self, event, args: list[str], paused: bool) -> None:
        if not args or not args[0].lstrip("-").isdigit():
            await event.respond("✏️ ប្រើ៖ /pause <customer_id> ឧ. /pause 555000111")
            return
        telegram_id = int(args[0])
        async with db_session() as session:
            customer = await crud.get_customer_by_telegram(session, telegram_id)
            if customer is None:
                await event.respond(f"🔍 រកមិនឃើញអតិថិជន {telegram_id} ទេ")
                return
            await crud.set_customer_flag(session, customer.id, ai_paused=paused)
        verb = "ផ្អាក" if paused else "បន្ត"
        note = " — AI នឹងមិនឆ្លើយរហូតដល់ /resume" if paused else ""
        await event.respond(f"⏯ {verb} AI សម្រាប់អតិថិជន {telegram_id}{note}")

    def _status_text(self) -> str:
        info = self.manager.status()
        lines = [f"📊 គណនីភ្ជាប់៖ {len(info['running_accounts'])} · global {'បិទ' if info['global_stopped'] else 'បើក'}"]
        for account_id, depth in sorted(info["queues"].items()):
            lines.append(f" · គណនី #{account_id} — ជួររង់ចាំ {depth}")
        return "\n".join(lines)
