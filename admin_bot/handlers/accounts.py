"""📱 គណនី Telegram (Userbot sessions) — បញ្ជី, ស្ថានភាព, Primary, AI និងការ login ក្នុង chat។

OTP/2FA វាយចូល chat របស់ admin នោះ ហើយសារត្រូវ<b>លុបភ្លាម</b> ពេលអានរួច ទើប code
មិនសល់ក្នុង history របស់ Bot។ Session string មិនដែលចេញពី chat ឡើយ (Fernet encrypt
ក្នុង DB) ហើយ error ត្រូវ redact តាម userbot/safety។
"""
from __future__ import annotations

import logging
from secrets import randbelow

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from admin_bot import keyboards, render
from admin_bot.owner_gate import OwnerOnly
from admin_bot.scope import Scope
from config import settings
from database import crud, db_session
from database.models import Account
from helpers import esc
from sqlalchemy import select, update
from userbot import credentials
from userbot.manager import DEVICE_POOL

router = Router()
log = logging.getLogger("admin.accounts")

NOT_FOUND = "🚫 រកមិនឃើញគណនីនេះក្នុងវិសាលភាពរបស់អ្នក"


HOWTO = (
    "📱 <b>បន័ែមគណនី</b> — វាយ <code>/addsession</code>\n\n"
    "១. ដាក់ <code>TG_API_ID</code> + <code>TG_API_HASH</code> (App របស់បងពី\n"
    "   <b>my.telegram.org/apps → API development tools</b>) និង <code>SESSION_FERNET_KEY</code>"
    " ក្នុង <code>.env</code> រួច restart bot\n"
    "២. បង្កើត Session String ដោយប្រើ API ID និង API Hash របស់អ្នក\n"
    "៣. ផ្ញើ Session String ទៅ Bot តាម <code>/addsession</code>\n"
    "៤. Bot នឹង Encrypt + Save ក្នុង DB ហើយ Userbot ភ្ជាប់ក្នុង ៦០ វិនាទី\n\n"
    "🔒 Session String នឹងត្រូវលុបភ្លាម បន្ទាប់ពីអាន ហើយ Encrypt ជានិច្ច។\n"
    "🔑 <b>api_hash មិនដែលវាយតាម chat ទេ</b> — វាជា secret របស់ App មួយ ហើយ chat របស់ Bot\n"
    "   មិនមែនកន្លែងសុវត្ថិភាពទេ (មាន log + backup)។\n"
    "⚠️ កុំប្រើ Session String របស់គណនីដែលអ្នក<b>មិន</b>កាន់កាប់។\n"
    "ℹ️ បោះបង់ពេលណាក៏បានដោយ <code>/cancel</code>។"
)


def _session_web_hint(format_type: str = "html") -> str:
    """តំណទៅគេហទំព័រ Make Session (session_web/) — ទទេ ពេល URL មិនចាប់ផ្តើមដោយ http
    (មិនទាន់ deploy ឬម្ចាស់បិតតំណដោយដាក់ `SESSION_WEB_URL=off`)។

    ហៅពេល handler ជំនួសពេល import ព្រោះ URL ពិតប្រាកដដឹងតែក្រោយ `vercel --prod`
    ហើយ test អាច patch `accounts.settings` ដើម្បីសាកល្បងផ្លូវ «មិនទាន់ deploy»។
    """
    url = (settings.session_web_url or "").strip()
    if not url.startswith("http"):
        return ""
    if format_type == "html":
        return (
            "\n\n🌐 <b>ដើម្បីងាយស្រួល</b> — បង្កើត Session String តាម Web App:\n"
            f'<a href="{esc(url)}">{esc(url)}</a>\n'
            "បន្ទាប់មក ចម្លង Session String មកផ្ញើទីនេះ។"
        )
    return (
        "\n\n🌐 **ដើម្បីងាយស្រួល** — បង្កើត Session String តាម Web App:\n"
        f"{url}\n"
        "បន្ទាប់មក ចម្លង Session String មកផ្ញើទីនេះ។"
    )


class LoginStates(StatesGroup):
    # OTP states disabled - only session string used
    # waiting_phone = State()
    # waiting_code = State()
    # waiting_password = State()
    waiting_session = State()


def target_id(callback: CallbackQuery) -> int:
    return int(callback.data.rsplit(":", 1)[-1])


# login_key function disabled - OTP login removed
# def login_key(message: Message, scope: Scope) -> str:
#     return f"{message.chat.id}:{scope.admin_id}"


class ChatChannel:
    """រូបរាង <code>LoginChannel</code> របស់ coordinator — Bot ផ្ញើសារ, FSM តាម stage។"""

    def __init__(self, bot, chat_id: int, state: FSMContext) -> None:
        self.bot = bot
        self.chat_id = chat_id
        self.state = state

    async def set_stage(self, stage: str) -> None:
        # OTP states disabled - session string only
        pass

    async def ask_code(self, retry: bool = False) -> None:
        # OTP disabled
        pass

    async def ask_password(self) -> None:
        # OTP disabled
        pass

    async def result(self, ok: bool, text: str) -> None:
        await self.state.set_state(None)
        await self.bot.send_message(self.chat_id, text)


async def _delete_secret(message: Message) -> None:
    """លុបសារ OTP/2FA — បើលុបមិនបាន (សារចាស់ពេល/permission) កុំឱ្យដួល login flow។"""
    try:
        await message.delete()
    except Exception as exc:  # noqa: BLE001
        log.info("លុបសារសម្ងាត់មិនបាន: %s", type(exc).__name__)


async def guard_account(callback: CallbackQuery, account_id: int, scope: Scope) -> Account | None:
    """IDOR guard — គណនីរបស់ admin ផ្សេង មិនអាច មើល/AI/enable/លុប បានទេ។"""
    async with db_session() as session:
        account = await crud.get_account(session, account_id, owner_admin_id=scope.owner_id)
    if account is None:
        log.warning("IDOR: user=%s account=%s ក្រៅវិសាលភាព", scope.admin_id, account_id)
        await callback.answer(NOT_FOUND, show_alert=True)
    return account


async def show_list(event: CallbackQuery | Message, scope: Scope) -> None:
    async with db_session() as session:
        accounts = await crud.list_accounts(session, owner_admin_id=scope.owner_id)
    header = "📱 <b>គណនី Telegram</b>\n"
    if not accounts:
        header += (
            "\n<i>មិនទាន់មានគណនី — ចុច ➕ បន័ែមគណនី ឬ <code>/addsession</code></i>"
            if scope.is_owner
            else "\n<i>មិនទាន់មានគណនីក្នុងវិសាលភាពរបស់អ្នក — login គណនីរបស់អ្នក ឬសុំ Owner ប្ដូរម្ចាស់គណនី</i>"
        )
    else:
        header += f"\nសរុប {len(accounts)} · ⭐ = Primary (គណនីដែល AI ប្រើឆ្លើយតប)"
    markup = keyboards.accounts_menu(accounts, scope)
    if isinstance(event, CallbackQuery):
        if event.message is None:
            await event.answer()
            return
        await event.message.edit_text(header, reply_markup=markup)
        await event.answer()
    else:
        await event.answer(header, reply_markup=markup)


async def show_account(callback: CallbackQuery, account_id: int, scope: Scope, toast: str = "") -> None:
    account = await guard_account(callback, account_id, scope)
    if account is None:
        return
    if callback.message is None:
        await callback.answer(toast)
        return
    await callback.message.edit_text(
        render.account_card(account), reply_markup=keyboards.account_actions(account, scope)
    )
    await callback.answer(toast)


@router.callback_query(F.data == "menu:accounts")
async def cb_accounts_root(callback: CallbackQuery, state: FSMContext, scope: Scope) -> None:
    await state.set_state(None)
    await show_list(callback, scope)


@router.callback_query(F.data == "acc:howto")
async def cb_howto(callback: CallbackQuery, scope: Scope) -> None:
    if callback.message is None:
        await callback.answer()
        return
    await callback.message.edit_text(
        HOWTO + _session_web_hint("html"),
        reply_markup=keyboards.accounts_menu([], scope),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("acc:view:"))
async def cb_view(callback: CallbackQuery, scope: Scope) -> None:
    await show_account(callback, target_id(callback), scope)


# ---------------- ចុះឈ្មោះគណនី (Session String only - OTP disabled) ----------------

# OTP login functions disabled - session string only
# async def _ask_phone(event: Message | CallbackQuery, state: FSMContext) -> None:
#     await state.set_state(LoginStates.waiting_phone)
#     prompt = "📱 ផ្ញើ<b>លេខទូរស័ព្ទ</b>ដែលជាប់នឹងគណនី Telegram នេះ (ឧ. <code>093251670</code> ឬ <code>+85593251670</code>)៖"
#     if isinstance(event, CallbackQuery):
#         if event.message is None:
#             await event.answer()
#             return
#         await event.message.answer(prompt)
#         await event.answer()
#     else:
#         await event.answer(prompt)


# async def _begin_login(message: Message, state: FSMContext, scope: Scope, phone: str) -> None:
#     """ចាប់ផ្តើម login ដោយ api_id/api_hash ពី `.env` តែប៉ុណ្ណោះ (មិនមែនពី chat)។"""
#     error = await chat_login.get_coordinator().begin(
#         chat_id=message.chat.id,
#         user_id=scope.admin_id,
#         phone=phone,
#         name="",
#         channel=ChatChannel(message.bot, message.chat.id, state),
#     )
#     if error is not None:
#         await state.set_state(None)
#         await message.answer(error)
#         return
#     await state.update_data(login_key=login_key(message, scope))


@router.callback_query(F.data == "acc:add")
async def cb_account_add(callback: CallbackQuery, state: FSMContext) -> None:
    # OTP login disabled - use session string instead
    await callback.answer("🔐 សូមប្រើ /addsession ជំនួស OTP login", show_alert=True)


@router.callback_query(F.data == "acc:addsession")
async def cb_account_add_session(callback: CallbackQuery, state: FSMContext, scope: Scope) -> None:
    """Button handler for adding account via session string"""
    if callback.message is None:
        await callback.answer()
        return
    await cmd_add_session(callback.message, state, scope)
    await callback.answer()


@router.message(Command("addaccount"))
async def cmd_add_account(message: Message, command: CommandObject, state: FSMContext, scope: Scope) -> None:
    # OTP login disabled - redirect to session string
    await message.answer(
        "🔐 <b>OTP login ត្រូវបានបិទ</b>\n\n"
        "សូមប្រើ Session String ជំនួស:\n"
        "១. បង្កើត Session String ដោយប្រើ API ID និង API Hash របស់អ្នក\n"
        "២. ផ្ញើទៅ Bot: <code>/addsession</code>",
        reply_markup=keyboards.main_menu(scope.is_owner),
    )


@router.message(Command("addsession"))
async def cmd_add_session(message: Message, state: FSMContext, scope: Scope) -> None:
    """បន្ថែមគណនីតាម Session String — គេចពី OTP Block ពី Telegram។"""
    await state.set_state(LoginStates.waiting_session)
    await message.answer(
        "🔐 **បន្ថែមគណនីតាម Session String**\n\n"
        "ដើម្បីទទួលបាន Session String របស់ Telegram (ជាកូដអក្សរមួយជួរវែងសម្រាប់ប្រើប្រាស់ជាមួយបណ្ណាល័យកូដដូចជា Telethon, GramJS, ឬ Pyrogram) អ្នកត្រូវធ្វើតាម ២ ជំហានធំៗខាងក្រោមនេះ៖\n\n"
        "**ជំហានទី ១៖ យក API ID និង API Hash**\n"
        "មុននឹងអាចបង្កើត Session String បាន អ្នកត្រូវចុះឈ្មោះយកលេខសម្គាល់គណនីអ្នកអភិវឌ្ឍន៍ (Developer) ពី Telegram ជាមុនសិន៖\n"
        "1. ចូលទៅកាន់គេហទំព័រផ្លូវការ [Telegram Development Tools](https://my.telegram.org/apps) រួចវាយបញ្ចូលលេខទូរស័ព្ទគណនី Telegram របស់អ្នក។\n"
        "2. វាយបញ្ចូលកូដផ្ទៀងផ្ទាត់ដែល Telegram ផ្ញើទៅក្នុងកម្មវិធីរបស់អ្នក។\n"
        "3. ជ្រើសរើសយក **API development tools**។\n"
        "4. បង្កើតកម្មវិធីថ្មីមួយ (ត្រង់ App title និង Short name អ្នកអាចបំពេញឈ្មោះអ្វីក៏បានតាមចិត្ត)។\n"
        "5. ចម្លង (Copy) ទុក **API ID** និង **API Hash** របស់អ្នក (សូមរក្សាវាជាការសម្ងាត់បំផុត)។\n\n"
        "**ជំហានទី ២៖ បង្កើត Session String**\n"
        "យក API ID និង API Hash ដែលអ្នកទើបបានមកបំពេញក្នុងឧបករណ៍បង្កើត Session String ដើម្បីទទួលបានកូដវែងនោះ។"
        + _session_web_hint("markdown")
        + "\n\n"
        "📤 **បន្ទាប់មក សូមផ្ញើ Session String នោះមកទីនេះភ្លាម។**\n\n"
        "⚠️ **សារនេះនឹងត្រូវលុបភ្លាម បន្ទាប់ពីអាន**\n"
        "🔒 **Session String នឹងត្រូវ Encrypt + Save ក្នុង DB ដោយស្វ័យប្រវត្តិ**\n\n"
        "ឬផ្ញើ /cancel ដើម្បីបោះបង់",
        parse_mode="Markdown",
        disable_web_page_preview=True
    )


# OTP handlers disabled - session string only
# async def _accept_phone(message: Message, state: FSMContext, scope: Scope, raw: str) -> None:
#     """លេខត្រឹមត្រូវ → លុបសារ → ផ្ញើ OTP (api_id/api_hash ពី .env)។ ខុស → នៅ waiting_phone។"""
#     normalized = chat_login.normalize_phone(raw)
#     if normalized is None:
#         await state.set_state(LoginStates.waiting_phone)
#         await message.answer(
#             "📵 លេខទូរស័ព្ទខុសទ្រង់ទ្រាយ — វាយបានទាំង <code>093251670</code> និង <code>+85593251670</code>\n"
#             "សូមផ្ញើលេខដែលមាននៅក្នុង Telegram App របស់បង។"
#         )
#         return
#     await _delete_secret(message)
#     await state.update_data(login_phone=normalized)
#     await message.answer("📨 កំពុងផ្ញើ OTP ទៅ Telegram…")
#     await _begin_login(message, state, scope, normalized)


# @router.message(LoginStates.waiting_phone, F.text)
# async def md_login_phone(message: Message, state: FSMContext, scope: Scope) -> None:
#     await _accept_phone(message, state, scope, message.text.strip())


# @router.message(LoginStates.waiting_code, F.text)
# async def md_login_code(message: Message, state: FSMContext, scope: Scope) -> None:
#     key = (await state.get_data()).get("login_key") or login_key(message, scope)
#     code = message.text.strip()
#     await _delete_secret(message)
#     if chat_login.get_coordinator().resolve_code(key, code):
#         return
#     await _login_lost(message, state, scope, "កូដ")


# @router.message(LoginStates.waiting_password, F.text)
# async def md_login_password(message: Message, state: FSMContext, scope: Scope) -> None:
#     key = (await state.get_data()).get("login_key") or login_key(message, scope)
#     password = message.text
#     await _delete_secret(message)
#     if chat_login.get_coordinator().resolve_password(key, password):
#         return
#     await _login_lost(message, state, scope, "ពាក្យសម្ងាត់")


@router.message(LoginStates.waiting_session, F.text)
async def md_login_session(message: Message, state: FSMContext, scope: Scope) -> None:
    """ទទួល Session String → លុបសារ → Validate → Encrypt → Save DB → Connect។"""
    session_string = message.text.strip()
    await _delete_secret(message)

    # Validate session string format (basic check)
    if len(session_string) < 50 or not session_string.startswith(("1", "2", "3", "4", "5", "6", "7", "8", "9")):
        await state.set_state(None)
        await message.answer(
            "❌ Session String ខុសទ្រង់ទ្រាយ — សូមសាកល្បងឡើងវិញដោយ <code>/addsession</code>",
            reply_markup=keyboards.main_menu(scope.is_owner),
        )
        return

    # ពិនិត្យថា session valid ដោយព្យាយាម connect
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    # credentials អានពី `.env` តាម userbot.credentials (config គ្មាន TG_API_ID module-level ទេ)
    creds = credentials.env_credentials()
    if creds is None:
        await state.set_state(None)
        await message.answer(
            credentials.missing_credentials_message(),
            reply_markup=keyboards.main_menu(scope.is_owner),
        )
        return
    api_id, api_hash = creds

    try:
        client = TelegramClient(StringSession(session_string), api_id, api_hash)
        await client.connect()
        me = await client.get_me()

        if me is None or not await client.is_user_authorized():
            await client.disconnect()
            await state.set_state(None)
            await message.answer(
                "❌ Session String មិនត្រឹមត្រូវ ឬផុតកំណត់ — សូមបង្កើតថ្មីដោយ <code>python scripts/get_session.py</code>",
                reply_markup=keyboards.main_menu(scope.is_owner),
            )
            return

        # Encrypt session string
        from userbot import session_store, safety

        safety.register_secret(session_string)
        token = session_store.encrypt(session_string)
        fp = session_store.fingerprint(session_string)

        # Save to DB
        async with db_session() as session:
            # Check if phone already exists
            existing = await session.scalar(
                select(Account).where(Account.phone == me.phone)
            )
            if existing is not None:
                if existing.owner_admin_id is not None and existing.owner_admin_id != scope.admin_id:
                    await client.disconnect()
                    await state.set_state(None)
                    await message.answer(
                        "🚫 លេខនេះជាគណនីរបស់ admin ផ្សេងហើយ — សុំ Owner ប្ដូរម្ចាស់គណនី",
                        reply_markup=keyboards.main_menu(scope.is_owner),
                    )
                    return

                # Update existing
                device_index = randbelow(len(DEVICE_POOL))
                await session.execute(
                    update(Account)
                    .where(Account.id == existing.id)
                    .values(
                        session_encrypted=token,
                        device_index=device_index,
                        name=f"{me.first_name or ''} {me.last_name or ''}".strip(),
                    )
                )
                account_id = existing.id
            else:
                # Create new
                device_index = randbelow(len(DEVICE_POOL))
                account = await crud.create_account(
                    session,
                    phone=me.phone,
                    session_encrypted=token,
                    name=f"{me.first_name or ''} {me.last_name or ''}".strip(),
                    owner_admin_id=scope.admin_id,
                    enabled=True,
                    device_index=device_index,
                )
                await crud.record_account_identity(
                    session,
                    account.id,
                    telegram_user_id=me.id,
                    username=me.username or "",
                    display_name=" ".join(filter(None, (me.first_name, me.last_name))),
                )
                account_id = account.id

        await client.disconnect()
        await state.set_state(None)

        # Trigger hot-reload
        from userbot.manager import current_manager

        manager = current_manager()
        if manager is not None:
            try:
                await manager.reconcile()
            except Exception as exc:
                log.warning("reconcile ក្រោយ addsession មិនបាន: %s", exc)

        await message.answer(
            f"✅ ភ្ជាប់រួច — គណនី <code>#{account_id}</code> · fp={fp}\n"
            f"👤 {me.first_name or ''} {me.last_name or ''}\n"
            f"📞 {me.phone}\n"
            "🔒 session string រក្សាទុក Fernet ក្នុង DB តែប៉ុណ្ណោះ មិនដែលចូល chat ឬ log ទេ។",
            reply_markup=keyboards.main_menu(scope.is_owner),
        )

    except Exception as exc:
        log.error("addsession error: %s", exc, exc_info=True)
        await state.set_state(None)
        await message.answer(
            f"❌ បរាជ័យ: {type(exc).__name__} — សូមសាកល្បងឡើងវិញ",
            reply_markup=keyboards.main_menu(scope.is_owner),
        )


# _login_lost function disabled - OTP login removed
# async def _login_lost(message: Message, state: FSMContext, scope: Scope, what: str) -> None:
#     """គ្មាន pending ទៀត (timeout/cancel រួច) → សម្អាត FSM កុំឱ្យសារធម្មតាត្រូវចាប់ជា code វិញ។"""
#     if chat_login.get_coordinator().has_pending(message.chat.id, scope.admin_id):
#         return
#     await state.set_state(None)
#     await message.answer(
#         f"⚠️ ការ login ចប់ហើយ (មិនបានទទួល{what}) — សាកល្បង <code>/addaccount</code> ឡើងវិញ",
#         reply_markup=keyboards.main_menu(scope.is_owner),
#     )


# ---------------- សកម្មភាព ----------------

@router.callback_query(F.data.startswith("acc:primary:"), OwnerOnly())
async def cb_primary(callback: CallbackQuery, scope: Scope) -> None:
    """Primary ជា global routing knob (គណនីដែល AI ឆ្លើយឱ្យអតិថិជនទាំងអស់) → Owner តែប៉ុណ្ណោះ។"""
    account_id = target_id(callback)
    if await guard_account(callback, account_id, scope) is None:
        return
    async with db_session() as session:
        await crud.set_primary_account(session, account_id)
    await show_account(callback, account_id, scope, toast="⭐ កំណត់ជា Primary រួច")


@router.callback_query(F.data.startswith("acc:ai:"))
async def cb_ai(callback: CallbackQuery, scope: Scope) -> None:
    account_id = target_id(callback)
    if await guard_account(callback, account_id, scope) is None:
        return
    async with db_session() as session:
        account = await crud.get_account(session, account_id, owner_admin_id=scope.owner_id)
        if account is None:
            await callback.answer(NOT_FOUND, show_alert=True)
            return
        account.ai_enabled = not account.ai_enabled
        enabled = account.ai_enabled
    await show_account(callback, account_id, scope, toast=f"🤖 AI {'បើក' if enabled else 'បិទ'} សម្រាប់គណនីនេះ")


@router.callback_query(F.data.startswith("acc:enable:"))
async def cb_enable(callback: CallbackQuery, scope: Scope) -> None:
    """intent របស់ម្ចាស់គណនី — manager ភ្ជាប់/ផ្ដាច់នៅពេល reconcile បន្ទាប់។"""
    account_id = target_id(callback)
    account = await guard_account(callback, account_id, scope)
    if account is None:
        return
    wanted = not account.enabled
    async with db_session() as session:
        await crud.set_account_enabled(session, account_id, wanted)
    await show_account(callback, account_id, scope, toast="🟢 បើក Userbot" if wanted else "🔒 បិទ Userbot")


@router.callback_query(F.data.startswith("acc:askowner:"), OwnerOnly())
async def cb_ask_owner(callback: CallbackQuery, scope: Scope) -> None:
    account_id = target_id(callback)
    account = await guard_account(callback, account_id, scope)
    if account is None or callback.message is None:
        return
    async with db_session() as session:
        admins = await crud.list_admins(session)
    await callback.message.edit_text(
        f"🔀 ប្ដូរម្ចាស់គណនី <code>#{account_id}</code> ({esc(account.phone)}) →\n"
        "<i>ទិន្នន័យដែល derive ពីគណនីនេះ (ផលិតផល/QR ដែលភ្ជាប់) នឹងតាមម្ចាស់ថ្មីទៅដោយ។</i>",
        reply_markup=keyboards.owner_picker(account, admins),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("acc:owner:"), OwnerOnly())
async def cb_transfer_owner(callback: CallbackQuery, scope: Scope) -> None:
    parts = callback.data.split(":")
    account_id, new_owner = int(parts[2]), int(parts[3])
    if await guard_account(callback, account_id, scope) is None:
        return
    async with db_session() as session:
        moved = await crud.transfer_account_owner(session, account_id, new_owner)
    if not moved:
        await callback.answer("🚫 ប្ដូរម្ចាស់មិនបាន (រកមិនឃើញ admin ឬគណនី)", show_alert=True)
        return
    await callback.answer("🔀 បានប្ដូរម្ចាស់គណនី")
    await show_list(callback, scope)


@router.callback_query(F.data.startswith("acc:askdel:"))
async def cb_ask_delete(callback: CallbackQuery, scope: Scope) -> None:
    account_id = target_id(callback)
    account = await guard_account(callback, account_id, scope)
    if account is None or callback.message is None:
        return
    await callback.message.edit_text(
        f"🗑 លុបគណនី <b>{esc(account.phone)}</b> <code>#{account.id}</code>?\n\n"
        "<i>Session string ត្រូវលុបចេញពី DB និង session file ក្នុង media/session។ "
        "ប្រវត្តិ Order/Customer ចាស់ នៅរក្សាទុកជា snapshot។</i>",
        reply_markup=keyboards.confirm_action(f"លុប #{account_id}", f"acc:del:{account_id}"),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("acc:del:"))
async def cb_delete(callback: CallbackQuery, scope: Scope) -> None:
    """លុប Record ហើយប្រគល់ star Primary ទៅគណនីដែលនៅសល់ក្នុងវិសាលភាព។"""
    account_id = target_id(callback)
    if await guard_account(callback, account_id, scope) is None:
        return
    async with db_session() as session:
        account = await crud.get_account(session, account_id, owner_admin_id=scope.owner_id)
        phone = account.phone if account else ""
        was_primary = bool(account and account.is_primary)
        await crud.delete_account(session, account_id)
        accounts = await crud.list_accounts(session, owner_admin_id=scope.owner_id)
        if was_primary and accounts:
            await crud.set_primary_account(session, accounts[0].id)
    if callback.message is None:
        await callback.answer()
        return
    await callback.message.edit_text(
        f"🗑 បានលុបគណនី <code>{esc(phone)}</code>",
        reply_markup=keyboards.accounts_menu(accounts, scope),
    )
    await callback.answer()


@router.message(Command("accounts"))
async def cmd_accounts(message: Message, state: FSMContext, scope: Scope) -> None:
    await state.set_state(None)
    await show_list(message, scope)
