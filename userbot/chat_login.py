"""Chat login — បន្ថែមគណនី Telegram ឆ្លងកាត់ chat របស់ Admin Bot (ជំនួស terminal)។

គោលការណ៍សុវត្ថិភាព ៣ ដែលមិនអាចប្ដូរបាន៖

1. **OTP/2FA មិនដែលស្ថិតក្នុង FSM, DB, log ឬអត្ថបទរបស់ Bot** — វាហូរចូល `Future`
   ក្នុង memory តែមួយគត់ ហើយ `safety.register_secret()` រាំងមិនឱ្យចេញក្នុង log ណា
   ទោះ exception បញ្ចេញ request repr។  caller (aiogram handler) ជាអ្នកលុបសាររបស់
   អ្នកប្រើភ្លាម មុន processData ផង។
2. **Session string ចេញពី `client.session.save()` → Fernet → DB តែប៉ុណ្ណោះ**។
   `StringSession.save()` ត្រឡប់ `''` មុន auth ដូច្នេះការ encrypt កើតឿន **ក្រោយ**
   `sign_in` ជានិច្ច (មិនដែលរក្សាទុក «គណនីដែល login មិនទាន់បាន»)។
3. **Account row បង្កើតតែពេល auth ជោគជ័យ** — បើបង្កើតមុន ការបរាជ័យនឹងទុក orphan row
   កាន់កាប់ UNIQUE phone និងអាចលួច `is_primary`។

ការដំណើរការ login ជា `asyncio.Task` ដែលរង់ចាំ Future ជំនួសឱ្យ `input()`/`getpass()`
របស់ CLI (Style B) ដូច្នេះគ្មាន stdout print គ្មាន retry ដែល control មិនបាន។
"""
from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

import phonenumbers
from secrets import randbelow

from sqlalchemy import select, update

from database import crud
from database.models import Account
from database.session import db_session
from userbot import credentials, safety, session_store
from userbot.manager import DEVICE_POOL, current_manager
from userbot.safety import describe_error

log = logging.getLogger("userbot.chat_login")

# លេខទូរស័ព្ទក្នុងស្រុក (ចាប់ផ្តើមដោយ 0) ត្រូវបំពេញកូដប្រទេសតាម region នេះ
DEFAULT_REGION = "KH"


def normalize_phone(raw: str, *, region: str = DEFAULT_REGION) -> str | None:
    """បម្លែងលេខដែលអ្នកប្រើវាយ → E.164 (`+85593251670`)។ បរាជ័យ → `None`។

    ទទួល «093251670», «093 251 670», «+85593251670», «85593251670», «00955...»។
    លេខខ្លីពេក ឬមិនមែនលេខទូរស័ព្ទ → `None` (កុំបញ្ជូនទៅ Telethon ដើម្បីកុំឱ្យ error
    ចេញជាភាសាអង់គ្លេសរញែញនៅចុងបញ្ចប់)។
    """
    text = (raw or "").strip()
    if not text:
        return None
    cleaned = re.sub(r"[^\d+]", "", text)
    if cleaned.startswith("00"):  # ទ្រង់ទ្រាយ international ចាស់ → + ដំបូង
        cleaned = "+" + cleaned[2:]
    if not cleaned:
        return None
    candidates = [cleaned]
    if not cleaned.startswith("+"):
        candidates.append("+" + cleaned)  # លេខដែលដាក់កូដប្រទេសរួច តែគ្មាន +
    for candidate in candidates:
        try:
            parsed = phonenumbers.parse(candidate, None if candidate.startswith("+") else region)
        except phonenumbers.NumberParseException:
            continue
        if phonenumbers.is_valid_number(parsed):
            return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
    return None

CODE_TIMEOUT = 300.0
PASSWORD_TIMEOUT = 180.0
MAX_CODE_ATTEMPTS = 3
MAX_CONCURRENT = 2

# ម៉ាស៊ីន error → សារខ្មែរ។ យើងមិនដែលបង្ហាញ `str(RPCError)` ទេ ព្រោះ repr របស់វា
# បញ្ចូល request ទាំងមូល (មានលេខទូរស័ព្ទ និងអត្ថបទសារ)។
HINTS: dict[str, str] = {
    "PhoneNumberInvalidError": "លេខទូរស័ព្ទខុសទ្រង់ទ្រាយ — សូមវាយ +855XXXXXXXX",
    "PhoneCodeInvalidError": "កូដ OTP មិនត្រឹមត្រូវ",
    "SessionPasswordIncorrect": "ពាក្យសម្ងាត់ 2FA មិនត្រឹមត្រូវ",
    "SessionPasswordNeededError": "គណនីនេះមាន 2FA",
    "PhoneCodeExpiredError": "កូដ OTP ផុតកំណត់",
    "PhoneCodeSaltInvalid": "កូដ OTP ខុស ឬផុតកំណត់",
    "SessionExpiredError": "session ផុតកំណត់ — សាកល្បង /addaccount ឡើងវិញ",
    "SessionRevokedError": "Telegram បានដក session នេះ — សាកល្បង login ឡើងវិញ ក្រោយ ២៤ ម៉ោង",
    "SessionLoggedOut": "គណនីនេះ out log រួច — ត្រូវ login ឡើងវិញ",
    "Unauthorized": "Telegram បដិសេធការ login នេះ",
    "ApiIdInvalidError": "api_id / api_hash ខុស — ពិនិត្យ my.telegram.org → API development tools",
    "AuthKeyUnregisteredError": "គណនីនេះត្រូវបាន Telegram បិទ (banned)",
    "FloodWaitError": "Telegram សុំឱ្យរង់ចាំបន្តិចមុនសាកល្បងឡើងវិញ",
    "SessionStartFailed": "Telegram បដិសេធមិនឱ្យចាប់ផ្តើម session ពី IP នេះ",
    "ConnectionError": "មិនអាចទាក់ទង Telegram បានទេ — ពិនិត្យបណ្តាញ",
    "TimeoutError": "Telegram ឆ្លើយយឺតពេល — សាកល្បងឡើងវិញ",
}


def khmer_error(exc: BaseException) -> str:
    """សារខ្មែរខ្លី ពីឈ្មោះ exception តែប៉ុណ្ណោះ — គ្មាន request repr។"""
    name = type(exc).__name__
    hint = HINTS.get(name)
    if hint is None:
        for known, text in HINTS.items():
            if name.startswith(known):
                hint = text
                break
    if hint is None:
        # កំហុសក្រៅ RPC (TypeError, AttributeError…) = កូដរបស់យើង មិនមែន Telegram ទេ
        # — ប្រាប់ច្បាស់ ដើម្បីកុំឱ្យអ្នកប្រើទៅរក my.telegram.org ដោយខុសកន្លែង
        if not type(exc).__module__.startswith("telethon.errors"):
            hint = "កំហុសក្នុងប្រព័ន្ធរបស់យើង មិនមែនពី Telegram — សូមមើល log"
        else:
            hint = "មានកំហុសពី Telegram"
    if name == "FloodWaitError":
        seconds = getattr(exc, "seconds", None)
        if isinstance(seconds, int):
            hint = f"Telegram សុំឱ្យរង់ចាំ {seconds} វិនាទីមុនសាកល្បងឡើងវិញ"
    return f"{hint} ({describe_error(exc)})"


class LoginAborted(Exception):
    """បញ្ចប់ការ login ដោយសារសារខ្មែរដែលផ្ញើទៅ user បានហើយ។"""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class LoginChannel(Protocol):
    """អ្វីដែល aiogram handler ត្រូវផ្តល់ (Bot ផ្ញើសារ + លុបសារ)។"""

    async def ask_code(self, retry: bool = False) -> None: ...
    async def ask_password(self) -> None: ...
    async def set_stage(self, stage: str) -> None: ...
    async def result(self, ok: bool, text: str) -> None: ...


@dataclass
class PendingLogin:
    key: str
    chat_id: int
    user_id: int
    phone: str
    name: str
    device_index: int
    api_id: int
    api_hash: str
    channel: LoginChannel
    client: Any = None
    code_hash: str = ""
    code_attempts: int = 0
    resent: bool = False
    stage: str = "code"
    code_future: asyncio.Future | None = None
    password_future: asyncio.Future | None = None
    task: asyncio.Task | None = None

    @property
    def account_id(self) -> int | None:
        return getattr(self, "_account_id", None)


def _stable_device_index(existing: Account | None) -> int:
    """Fingerprint ត្រូវដូចគ្នារាល់ពេល reconnect។

    គណនីដែលមាន row រួច ប៉ុន្តែ `device_index` NULL → manager ប្រើ `account_id` ដូច្នេះ
    យើងត្រូវប្រើ `account_id` ដែរ (កុំចេះតែជ្រើសថ្មី មិនដូចគ្នាទេ)។ គណនីថ្មីស្រឡាង
    ជ្រើសចៃដន្យ ហើយរក្សាទុកលេខនោះក្នុង row ទ itself។
    """
    if existing is None:
        return randbelow(len(DEVICE_POOL))
    if existing.device_index is not None:
        return int(existing.device_index)
    return int(existing.id)


def _client_for(device_index: int, api_id: int, api_hash: str) -> Any:
    """Telethon client ដែល fingerprint ដូច manager (device pool តាម index)។

    `api_id`/`api_hash` ជារបស់ម្ចាស់គណនី (មិនមែន .env) — Telegram ចង auth key នឹង App
    ដែលបង្កើតវា ដូច្នេះ session ដែល login ដោយ App ណាមួយ ត្រូវ reconnect ដោយ App នោះដែរ។
    """
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    device, system, version = DEVICE_POOL[device_index % len(DEVICE_POOL)]
    return TelegramClient(
        StringSession(),
        api_id,
        api_hash,
        device_model=device,
        system_version=system,
        app_version=version,
        lang_code="km",
    )


class LoginCoordinator:
    def __init__(self, *, client_factory: Callable[[int, int, str], Any] | None = None) -> None:
        self._pending: dict[str, PendingLogin] = {}
        self._client_factory = client_factory or _client_for

    # ---------- ទម្រង់សាធារណៈ ----------
    def pending_for_user(self, user_id: int) -> PendingLogin | None:
        for entry in self._pending.values():
            if entry.user_id == user_id:
                return entry
        return None

    def has_pending(self, chat_id: int, user_id: int) -> bool:
        return f"{chat_id}:{user_id}" in self._pending

    def _loop(self) -> asyncio.AbstractEventLoop:
        return asyncio.get_running_loop()

    async def begin(
        self,
        *,
        chat_id: int,
        user_id: int,
        phone: str,
        name: str,
        channel: LoginChannel,
    ) -> str | None:
        """ត្រឡប់សារកំហុស (ខ្មែរ) ឬ None = ទទួលបាន OTP flow។

        `api_id`/`api_hash` មិនដែលមកពី chat ទេ — អានពី `.env` ហើយ validate ជា `int`/hex
        ៣២ តួ មុនបង្កើត Telethon client ទើបកំហុសទ្រង់ទ្រាយបែកនៅទីនេះ មិនមែនកណ្តាល login។
        """
        ok, message = session_store.key_status()
        if not ok:
            return f"🔐 {message}"
        creds = credentials.resolve()
        if creds is None:
            return credentials.missing_credentials_message()
        api_id, api_hash = creds
        normalized = normalize_phone(phone)
        if normalized is None:
            return (
                "📵 លេខទូរស័ព្ទខុសទ្រង់ទ្រាយ — វាយបានទាំង «093251670» និង «+85593251670»\n"
                "សូមផ្ញើលេខដែលមាននៅក្នុង Telegram App របស់បង"
            )
        phone = normalized
        if len(self._pending) >= MAX_CONCURRENT:
            return "⏳ មានការ login កំពុងដំណើរ ២ ហើយ — សូមរង់ចាំមួយចប់ជាមុន"
        key = f"{chat_id}:{user_id}"
        if key in self._pending:
            return "⚠️ មានការ login កំពុងដំណើរក្នុង chat នេះរួចហើយ — វាយ /cancel បើចង់បោះបង់"

        safety.register_secret(phone)
        safety.register_secret(api_hash)  # កុំឱ្យ log/exception ណាបញ្ចេញ api_hash
        async with db_session() as session:
            existing = await session.scalar(select(Account).where(Account.phone == phone))
        if existing is not None and existing.owner_admin_id is not None and existing.owner_admin_id != user_id:
            log.info("phone collision: admin=%s ព្យាយាម login លេខដែលជាគណនីរបស់ admin ផ្សេង", user_id)
            return "🚫 លេខនេះជាគណនីរបស់ admin ផ្សេងហើយ — សុំ Owner ប្ដូរម្ចាស់គណនី"

        device_index = _stable_device_index(existing)
        entry = PendingLogin(
            key=key,
            chat_id=chat_id,
            user_id=user_id,
            phone=phone,
            name=(name or "").strip()[:200],
            device_index=device_index,
            api_id=int(api_id),
            api_hash=api_hash,
            channel=channel,
            code_future=self._loop().create_future(),
            password_future=self._loop().create_future(),
        )
        self._pending[key] = entry
        entry.task = asyncio.create_task(self._run(entry), name=f"chat-login:{entry.user_id}")
        return None

    def resolve_code(self, key: str, code: str) -> bool:
        return self._resolve(key, "code_future", code)

    def resolve_password(self, key: str, password: str) -> bool:
        return self._resolve(key, "password_future", password)

    def _resolve(self, key: str, attribute: str, value: str) -> bool:
        entry = self._pending.get(key)
        if entry is None:
            return False
        future = getattr(entry, attribute)
        if future is None or future.done():
            return False
        # ចុះឈ្មោះជា secret មុនអ្វីៗទាំងអស់ ទើប log ណាក៏មិនឃើញតម្លៃនេះ
        safety.register_secret(value)
        future.set_result(value)
        return True

    async def cancel(self, key: str) -> bool:
        entry = self._pending.pop(key, None)
        if entry is None:
            return False
        await self._cleanup(entry)
        return True

    async def cancel_for_user(self, user_id: int) -> int:
        keys = [key for key, entry in self._pending.items() if entry.user_id == user_id]
        for key in keys:
            await self.cancel(key)
        return len(keys)

    async def shutdown(self) -> None:
        for key in list(self._pending):
            await self.cancel(key)

    # ---------- ដំណើរការ ----------
    async def _await_code(self, entry: PendingLogin, *, retry: bool = False) -> str:
        """រង់ចាំកូដ — បង្កើត Future ថ្មីរាល់ព្យាយាម ទើបកូដខុសមិនត្រឡប់មកវិញភ្លាម។"""
        entry.code_future = self._loop().create_future()
        await entry.channel.set_stage("code")
        await entry.channel.ask_code(retry=retry)
        try:
            return await asyncio.wait_for(entry.code_future, CODE_TIMEOUT)
        except asyncio.TimeoutError as exc:
            raise LoginAborted("⏱ រំពឹងច្រើនពេក មិនឃើញកូដ OTP — ការ login ត្រូវបានបញ្ចប់") from exc

    async def _await_password(self, entry: PendingLogin) -> str:
        entry.password_future = self._loop().create_future()
        await entry.channel.set_stage("password")
        await entry.channel.ask_password()
        try:
            return await asyncio.wait_for(entry.password_future, PASSWORD_TIMEOUT)
        except asyncio.TimeoutError as exc:
            raise LoginAborted("⏱ រំពឹងច្រើនពេក មិនឃើញពាក្យសម្ងាត់ 2FA — ការ login ត្រូវបានបញ្ចប់") from exc

    async def _sign_in(self, entry: PendingLogin) -> None:
        """connect → send_code_request → sign_in (OTP, បើមាន 2FA → sign_in password)。"""
        client = entry.client
        retry = False
        while True:
            code = await self._await_code(entry, retry=retry)
            retry = False
            try:
                await client.sign_in(phone=entry.phone, code=code, phone_code_hash=entry.code_hash)
                return
            except Exception as exc:  # noqa: BLE001 — dispatch តាមឈ្មោះ class គ្មាន repr
                name = type(exc).__name__
                if name.startswith("SessionPasswordNeeded"):
                    password = await self._await_password(entry)
                    await client.sign_in(password=password)
                    return
                if name.startswith("PhoneCodeExpired"):
                    if entry.resent:
                        raise LoginAborted("⌛ កូដ OTP ផុតកំណត់ ២ ដង — សូមវាយ /addaccount ម្ដងទៀត") from exc
                    entry.resent = True
                    sent = await client.send_code_request(entry.phone)
                    entry.code_hash = sent.phone_code_hash
                    retry = True
                    continue
                if name.startswith("PhoneCodeInvalid") or name.startswith("PhoneCodeSaltInvalid"):
                    entry.code_attempts += 1
                    if entry.code_attempts >= MAX_CODE_ATTEMPTS:
                        raise LoginAborted("🚫 កូដ OTP ខុស ៣ ដង — ការ login ត្រូវបានបញ្ចប់") from exc
                    retry = True
                    continue
                raise LoginAborted(f"❌ ចុះឈ្មោះបរាជ័យ — {khmer_error(exc)}") from exc

    async def _run(self, entry: PendingLogin) -> None:
        client = None
        try:
            client = self._client_factory(entry.device_index, entry.api_id, entry.api_hash)
            entry.client = client
            await client.connect()
            sent = await client.send_code_request(entry.phone)
            entry.code_hash = sent.phone_code_hash
            await self._sign_in(entry)

            me = await client.get_me()
            if me is None or not await client.is_user_authorized():
                raise LoginAborted("🚫 មិន authorized ក្រោយបញ្ចូលកូដ — សាកល្បង /addaccount ឡើងវិញ")

            token, fp = self._seal(client)
            account_id = await self._persist(entry, token=token, me=me)
            entry._account_id = account_id
            log.info(
                "chat login ជោគជ័យ · គណនី #%s · admin=%s · fp=%s · api_id=%s",
                account_id,
                entry.user_id,
                fp,
                entry.api_id,
            )
            await self._attach(account_id)
            await entry.channel.result(
                True,
                f"✅ ភ្ជាប់រួច — គណនី <code>#{account_id}</code> · fp={fp}\n"
                "🔒 session string រក្សាទុក Fernet ក្នុង DB តែប៉ុណ្ណោះ មិនដែលចូល chat ឬ log ទេ។",
            )
        except LoginAborted as abort:
            await entry.channel.result(False, abort.message)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            # កំហុសដែលមិនមែន RPC (TypeError/AttributeError…) គឺកំហុសកូដ មិនមែន Telegram ទេ
            # — បង្ហាញ file:line ដែលវាផ្ទុះ ជំនួសឱ្យ «មានកំហុសពី Telegram» ដែលរកមិនឃើញ។
            # traceback ពេញលេញឆ្លងកាត់ SecretRedactor រួច (គ្មាន OTP/លេខទូរស័ព្ទក្នុង frame lines)
            where = "?"
            tb = exc.__traceback__
            while tb is not None:
                where = f"{tb.tb_frame.f_code.co_filename.split('/')[-1]}:{tb.tb_lineno}"
                tb = tb.tb_next
            log.warning(
                "chat login កំហុស (admin=%s): %s at %s",
                entry.user_id,
                describe_error(exc),
                where,
                exc_info=True,
            )
            await entry.channel.result(False, f"❌ ចុះឈ្មោះបរាជ័យ — {khmer_error(exc)}")
        finally:
            await self._cleanup(entry)

    @staticmethod
    def _seal(client: Any) -> tuple[str, str]:
        """session → Fernet token + fingerprint 12 hex (មិនដែល return plaintext)។"""
        raw = client.session.save()
        if isinstance(raw, bytes):
            raw = raw.decode()
        if not raw:
            raise LoginAborted("🚫 គ្មាន auth key ក្នុង session — សាកល្បង /addaccount ឡើងវិញ")
        fp = session_store.fingerprint(raw)
        token = session_store.encrypt(raw)
        return token, fp

    async def _persist(self, entry: PendingLogin, *, token: str, me: Any) -> int:
        """បង្កើត/កែ Account row ក្រោយ auth ជោគជ័យតែប៉ុណ្ណោះ (D2: enabled=True)។

        រក្សាទុកតែ session string (Fernet) — `api_id`/`api_hash` នៅក្នុង `.env` ជានិច្ច
        ដូច្នេះគ្មាន secret របស់ App ត្រួតពិនិត្យលើ DB/chat/log ទេ។
        """
        async with db_session() as session:
            existing = await session.scalar(select(Account).where(Account.phone == entry.phone))
            if existing is not None:
                if existing.owner_admin_id is not None and existing.owner_admin_id != entry.user_id:
                    raise LoginAborted("🚫 លេខនេះក្លាយជាគណនីរបស់ admin ផ្សេងមុនរួច — ការ login ត្រូវបោះបង់")
                await session.execute(
                    update(Account)
                    .where(Account.id == existing.id)
                    .values(
                        session_encrypted=token,
                        device_index=entry.device_index,
                        name=entry.name or existing.name,
                    )
                )
                return int(existing.id)
            account = await crud.create_account(
                session,
                phone=entry.phone,
                session_encrypted=token,
                name=entry.name,
                owner_admin_id=entry.user_id,
                enabled=True,
                device_index=entry.device_index,
            )
            await crud.record_account_identity(
                session,
                account.id,
                telegram_user_id=me.id,
                username=me.username or "",
                display_name=" ".join(filter(None, (me.first_name, me.last_name))),
            )
            return int(account.id)

    async def _attach(self, account_id: int) -> None:
        """ភ្ជាប់ភ្លាមបើ manager កំពុងរត់ មិនដូច្នេះ hot-reload ≤ ៦០ វិនាទីធ្វើការ។"""
        manager = current_manager()
        if manager is None:
            return
        try:
            await manager.reconcile()
        except Exception as exc:  # noqa: BLE001
            log.warning("reconcile ក្រោយ chat login មិនបាន: %s", describe_error(exc))
            await manager.notify(f"⚠️ គណនី #{account_id} login រួច ប៉ុន្តែ manager មិនទាន់ភ្ជាប់ ({type(exc).__name__})")

    async def _cleanup(self, entry: PendingLogin) -> None:
        self._pending.pop(entry.key, None)
        for attribute in ("code_future", "password_future"):
            future = getattr(entry, attribute)
            if future is not None and not future.done():
                future.cancel()
        task = entry.task
        if task is not None and task is not asyncio.current_task() and not task.done():
            task.cancel()
        if entry.client is not None:
            from userbot.manager import safe_disconnect

            await safe_disconnect(entry.client)
            entry.client = None


_coordinator: LoginCoordinator | None = None


def get_coordinator() -> LoginCoordinator:
    global _coordinator
    if _coordinator is None:
        _coordinator = LoginCoordinator()
    return _coordinator


def reset_coordinator() -> None:
    """សម្រាប់តេស្តប៉ុណ្ណោះ។"""
    global _coordinator
    _coordinator = None
