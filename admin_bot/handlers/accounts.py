"""📱 គណនី Telegram (Userbot sessions) — បញ្ជី, ស្ថានភាព, Primary, AI និងការ login ក្នុង chat។

OTP/2FA វាយចូល chat របស់ admin នោះ ហើយសារត្រូវ<b>លុបភ្លាម</b> ពេលអានរួច ទើប code
មិនសល់ក្នុង history របស់ Bot។ Session string មិនដែលចេញពី chat ឡើយ (Fernet encrypt
ក្នុង DB) ហើយ error ត្រូវ redact តាម userbot/safety។
"""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from admin_bot import keyboards, render
from admin_bot.owner_gate import OwnerOnly
from admin_bot.scope import Scope
from database import crud, db_session
from database.models import Account
from helpers import esc
from userbot import chat_login

router = Router()
log = logging.getLogger("admin.accounts")

NOT_FOUND = "🚫 រកមិនឃើញគណនីនេះក្នុងវិសាលភាពរបស់អ្នក"

HOWTO = (
    "📱 <b>បន័ែមគណនី</b> — ចុច ➕ ឬរាយការ <code>/addaccount +855XXXXXXXX</code>\n\n"
    "1. Bot សួរលេខទូរស័ព្ទ → Telegram ផ្ញើ OTP ទៅ<b>គណនីរបស់អ្នក</b> (មិនមែន chat នេះទេ)\n"
    "2. វាយកូដ OTP ចូល → <b>សាររបស់អ្នកត្រូវលុបភ្លាម</b> ពេលអានរួច\n"
    "3. បើគណនីមាន 2FA → វាយពាក្យសម្ងាត់ (សារក៏ត្រូវលុបដែរ)\n"
    "4. Session ត្រូវ encrypt (Fernet) ទុកក្នុង DB ហើយ Userbot ភ្ជាប់ក្នុង ៦០ វិនាទី\n\n"
    "⚠️ កុំវាយ OTP របស់គណនីដែលអ្នក<b>មិន</b>កាន់កាប់ — Panel នេះសាកល្បង login ពិត។\n"
    "ℹ️ បោះបង់ពេលណាក៏បានដោយ <code>/cancel</code>។\n\n"
    "ត្រូវការ <code>TG_API_ID</code> + <code>TG_API_HASH</code> + <code>SESSION_FERNET_KEY</code> ក្នុង <code>.env</code>។"
)


class LoginStates(StatesGroup):
    waiting_phone = State()
    waiting_code = State()
    waiting_password = State()


def target_id(callback: CallbackQuery) -> int:
    return int(callback.data.rsplit(":", 1)[-1])


def login_key(message: Message, scope: Scope) -> str:
    return f"{message.chat.id}:{scope.admin_id}"


class ChatChannel:
    """រូបរាង <code>LoginChannel</code> របស់ coordinator — Bot ផ្ញើសារ, FSM តាម stage។"""

    def __init__(self, bot, chat_id: int, state: FSMContext) -> None:
        self.bot = bot
        self.chat_id = chat_id
        self.state = state

    async def set_stage(self, stage: str) -> None:
        mapping = {"code": LoginStates.waiting_code, "password": LoginStates.waiting_password}
        await self.state.set_state(mapping.get(stage, LoginStates.waiting_phone))

    async def ask_code(self, retry: bool = False) -> None:
        lead = "🔁 កូដមុនខុស ឬផុតកំណត់ — សាកល្បងម្តងទៀត៖\n\n" if retry else ""
        await self.bot.send_message(
            self.chat_id,
            f"{lead}🔑 ផ្ញើ<b>កូដ OTP</b> ដែល Telegram បានផ្ញើទៅគណនីរបស់អ្នក (ឧ. <code>54321</code>)។\n"
            "<i>សាររបស់អ្នកនឹងត្រូវលុបភ្លាម បន្ទាប់ពីអាន។</i>",
        )

    async def ask_password(self) -> None:
        await self.bot.send_message(
            self.chat_id,
            "🛡 គណនីនេះមាន <b>2FA</b> — ផ្ញើពាក្យសម្ងាត់ Cloud របស់អ្នក។\n"
            "<i>សារនេះក៏ត្រូវលុបភ្លាម បន្ទាប់ពីអានដែរ។</i>",
        )

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
            "\n<i>មិនទាន់មានគណនី — ចុច ➕ បន័ែមគណនី ឬ <code>/addaccount</code></i>"
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
    await callback.message.edit_text(HOWTO, reply_markup=keyboards.accounts_menu([], scope))
    await callback.answer()


@router.callback_query(F.data.startswith("acc:view:"))
async def cb_view(callback: CallbackQuery, scope: Scope) -> None:
    await show_account(callback, target_id(callback), scope)


# ---------------- ចុះឈ្មោះគណនី (OTP ក្នុង chat) ----------------

async def _ask_phone(event: Message | CallbackQuery, state: FSMContext) -> None:
    await state.set_state(LoginStates.waiting_phone)
    prompt = "📱 ផ្ញើ<b>លេខទូរស័ព្ទ</b>ដែលជាប់នឹងគណនី Telegram នេះ (ឧ. <code>093251670</code> ឬ <code>+85593251670</code>)៖"
    if isinstance(event, CallbackQuery):
        if event.message is None:
            await event.answer()
            return
        await event.message.answer(prompt)
        await event.answer()
    else:
        await event.answer(prompt)


async def _begin_login(message: Message, state: FSMContext, scope: Scope, phone: str) -> None:
    error = await chat_login.get_coordinator().begin(
        chat_id=message.chat.id,
        user_id=scope.admin_id,
        phone=phone,
        name="",
        channel=ChatChannel(message.bot, message.chat.id, state),
    )
    if error is not None:
        await state.set_state(None)
        await message.answer(error)
        return
    await state.update_data(login_key=login_key(message, scope))


@router.callback_query(F.data == "acc:add")
async def cb_account_add(callback: CallbackQuery, state: FSMContext) -> None:
    await _ask_phone(callback, state)


@router.message(Command("addaccount"))
async def cmd_add_account(message: Message, command: CommandObject, state: FSMContext, scope: Scope) -> None:
    if not command.args:
        await _ask_phone(message, state)
        return
    await _begin_login(message, state, scope, command.args.split()[0])


@router.message(LoginStates.waiting_phone, F.text)
async def md_login_phone(message: Message, state: FSMContext, scope: Scope) -> None:
    await _begin_login(message, state, scope, message.text.strip())


@router.message(LoginStates.waiting_code, F.text)
async def md_login_code(message: Message, state: FSMContext, scope: Scope) -> None:
    key = (await state.get_data()).get("login_key") or login_key(message, scope)
    code = message.text.strip()
    await _delete_secret(message)
    if chat_login.get_coordinator().resolve_code(key, code):
        return
    await _login_lost(message, state, scope, "កូដ")


@router.message(LoginStates.waiting_password, F.text)
async def md_login_password(message: Message, state: FSMContext, scope: Scope) -> None:
    key = (await state.get_data()).get("login_key") or login_key(message, scope)
    password = message.text
    await _delete_secret(message)
    if chat_login.get_coordinator().resolve_password(key, password):
        return
    await _login_lost(message, state, scope, "ពាក្យសម្ងាត់")


async def _login_lost(message: Message, state: FSMContext, scope: Scope, what: str) -> None:
    """គ្មាន pending ទៀត (timeout/cancel រួច) → សម្អាត FSM កុំឱ្យសារធម្មតាត្រូវចាប់ជា code វិញ។"""
    if chat_login.get_coordinator().has_pending(message.chat.id, scope.admin_id):
        return
    await state.set_state(None)
    await message.answer(
        f"⚠️ ការ login ចប់ហើយ (មិនបានទទួល{what}) — សាកល្បង <code>/addaccount</code> ឡើងវិញ",
        reply_markup=keyboards.main_menu(scope.is_owner),
    )


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
