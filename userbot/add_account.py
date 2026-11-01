"""ចុះឈ្មោះគណនី Telegram ថ្មី — ដំណើរការក្នុង terminal ដាច់ដោយឡែកពី main.py។

    python -m userbot.add_account +85512345678 --name "ហាង ១" [--force]

ហេតុអ្វីជា terminal ជំនួសឱ្យ chat របស់ Bot៖ OTP/2FA ក្នុង chat នៅក្នុង log, DB backup
 និងទិន្នន័យដែល Telegram រក្សាទុក។ នៅទីនេះ OTP ខ្លីជាងនេះ — វានៅក្នុង memory របស់
process តែមួយនេះ ហើយ `safety.register_secret` រាំងមិនឱ្យចូល log ណាទោះកំហុសបញ្ចេញ repr។

Session ចេញពី `client.session.save()` → Fernet encrypt → ចូល DB តែប៉ុណ្ណោះ។
main.py ដែលកំពុងរត់ នឹងឃើញគណនីថ្មីក្នុង reconcile ≤ ៦០ វិនាទី (hot-reload)។
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import re
import sys

from sqlalchemy import select, update
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from telethon.sessions import StringSession

from config import settings
from database import crud
from database.models import Account
from database.session import db_session
from userbot import safety, session_store
from userbot.manager import DEVICE_POOL
from userbot.safety import describe_error

PHONE_RE = re.compile(r"^\+?\d{8,15}$")


async def login(phone: str, name: str, force: bool) -> int:
    ok, message = session_store.key_status()
    if not ok:
        print(f"❌ {message}", file=sys.stderr)
        return 1
    if not settings.tg_api_id or not settings.tg_api_hash:
        print("❌ កំណត់ TG_API_ID + TG_API_HASH ក្នុង .env ជាមុន (my.telegram.org)", file=sys.stderr)
        return 1
    if not PHONE_RE.match(phone):
        print(f"❌ លេខទូរស័ព្ទខុសទ្រង់ទ្រាយ: {phone} (រំពឹង +855XXXXXXXX)", file=sys.stderr)
        return 1

    safety.register_secret(phone)

    async with db_session() as session:
        existing = await session.scalar(select(Account).where(Account.phone == phone))
    if existing is not None and not force:
        print(f"❌ គណនី {phone} មានរួច (#{existing.id}) — ប្រើ --force ដើម្បី login ឡើងវិញ", file=sys.stderr)
        return 1

    device_index = existing.id if existing is not None else 1
    device, system, version = DEVICE_POOL[device_index % len(DEVICE_POOL)]
    client = TelegramClient(
        StringSession(),
        settings.tg_api_id,
        settings.tg_api_hash,
        device_model=device,
        system_version=system,
        application_version=version,
        lang_code="km",
    )

    print(f"🔑 ចាប់ផ្តើមចុះឈ្មោះ {phone} … (OTP នឹងមកដល់ app Telegram របស់បង)")
    try:
        await client.connect()
        sent = await client.send_code_request(phone)
        code = input("   កូដ OTP: ").strip()
        safety.register_secret(code)
        try:
            await client.sign_in(phone=phone, code=code, phone_code_hash=sent.phone_code_hash)
        except SessionPasswordNeededError:
            password = getpass.getpass("   ពាក្យសម្ងាត់ 2FA: ")
            safety.register_secret(password)
            await client.sign_in(password=password)
    except Exception as exc:  # noqa: BLE001 — describe_error គ្មាន request repr (OTP/លេខទូរស័ព្ទ)
        print(f"❌ ចុះឈ្មោះបរាជ័យ: {describe_error(exc)}", file=sys.stderr)
        await client.disconnect()
        return 1

    me = await client.get_me()
    if me is None or not await client.is_user_authorized():
        print("❌ មិន authorized ក្រោយ sign_in — សាកល្បងឡើងវិញ", file=sys.stderr)
        await client.disconnect()
        return 1

    try:
        raw = client.session.save()
        if isinstance(raw, bytes):
            raw = raw.decode()
        if not raw:
            raise RuntimeError("គ្មាន auth key ក្នុង session — សាកល្បងចុះឈ្មោះឡើងវិញ")
        fp = session_store.fingerprint(raw)
        token = session_store.encrypt(raw)
    finally:
        await client.disconnect()

    async with db_session() as session:
        if existing is not None:
            await session.execute(
                update(Account)
                .where(Account.id == existing.id)
                .values(session_encrypted=token, enabled=True, name=name or existing.name)
            )
            account_id = existing.id
        else:
            account = await crud.create_account(session, phone=phone, session_encrypted=token, name=name)
            await crud.record_account_identity(
                session,
                account.id,
                telegram_user_id=me.id,
                username=me.username or "",
                display_name=" ".join(filter(None, (me.first_name, me.last_name))),
            )
            account_id = account.id

    print(f"✅ រួចរាល់ — គណនី #{account_id} · session fp={fp}")
    print("   main.py នឹងភ្ជាប់ដោយស្វ័យប្រវត្តិក្នុង ≤ ៦០ វិនាទី (hot-reload)។")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="ចុះឈ្មោះគណនី Telegram សម្រាប់ userbot")
    parser.add_argument("phone", help="លេខទូរស័ព្ទ E.164 ឧ. +85512345678")
    parser.add_argument("--name", default="", help="ស្លាកឈ្មោះ (មិនបង្ហាញទៅអតិថិជនទេ)")
    parser.add_argument("--force", action="store_true", help="login ឡើងវិញសម្រាប់លេខដែលមានស្រាប់")
    args = parser.parse_args()
    return asyncio.run(login(args.phone.strip(), args.name.strip(), args.force))


if __name__ == "__main__":
    sys.exit(main())
