"""
Session String Generator — User រត់នៅម៉ាស៊ីនខ្លួនឯង

ប្រើ: python scripts/get_session.py +85512345678

លទ្ធផល: Session String វែង (ចម្លង → ផ្ញើទៅ Bot)
"""
import asyncio
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from telethon import TelegramClient
from telethon.sessions import StringSession

# config.py អាន .env ខ្លួនឯង — credentials ត្រូវជា int + hex ៣២ មុនបញ្ជូនទៅ Telethon
from userbot.credentials import env_credentials, missing_credentials_message


async def generate_session(phone: str):
    creds = env_credentials()
    if creds is None:
        print(missing_credentials_message())
        return
    api_id, api_hash = creds

    print(f"📱 Phone: {phone}")
    print(f"🔑 API ID: {api_id}")
    print()

    client = TelegramClient(StringSession(), api_id, api_hash)
    await client.connect()

    # ផ្ញើ OTP
    print("⏳ កំពុងផ្ញើ OTP...")
    try:
        sent = await client.send_code_request(phone)
        print(f"✅ OTP បានផ្ញើ! Type: {sent.type.__class__.__name__}")
    except Exception as e:
        print(f"❌ បរាជ័យ: {type(e).__name__}: {e}")
        return

    # ទទួល OTP ពី Terminal
    print()
    code = input("🔢 OTP (5-6 digits): ").strip()

    try:
        await client.sign_in(phone=phone, code=code)
    except Exception as e:
        if "password" in str(e).lower() or type(e).__name__ == "SessionPasswordNeededError":
            print("\n🔒 គណនីនេះមាន 2FA")
            password = getpass.getpass("🔒 2FA Password: ")
            await client.sign_in(password=password)
        else:
            print(f"❌ OTP បរាជ័យ: {type(e).__name__}: {e}")
            return

    # យក Session String
    me = await client.get_me()
    session_string = client.session.save()

    print()
    print("=" * 60)
    print("✅ ចូលបានជោគជ័យ!")
    print("=" * 60)
    print(f"👤 Name: {me.first_name}")
    print(f"🆔 ID: {me.id}")
    print(f"📞 Phone: {me.phone}")
    print(f"📱 Device: Kjfjfu107 (Android 11.2, Samsung Galaxy A54)")
    print()
    print("=" * 60)
    print("🔐 SESSION STRING:")
    print("=" * 60)
    print()
    print(session_string)
    print()
    print("=" * 60)
    print("⚠️ សំខាន់:")
    print("  1. ចម្លង Session String ខាងលើ (ទាំងអស់)")
    print("  2. ផ្ញើទៅ Bot តាម /addsession")
    print("  3. Bot នឹងលុបសារ + Encrypt + Save ដោយស្វ័យប្រវត្តិ")
    print("=" * 60)

    await client.disconnect()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("ប្រើ: python scripts/get_session.py +85512345678")
        sys.exit(1)

    asyncio.run(generate_session(sys.argv[1]))
