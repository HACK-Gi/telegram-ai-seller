"""📱 គណនី Telegram (Userbot sessions) — បញ្ជី, ស្ថានភាព, Primary, និងការគ្រប់គ្រង AI។

ការចុះឈ្មោះ OTP (`/addaccount`) ត្រូវបានដំឡើងក្នុង <b>ជំហានទី ២</b> ព្រោះវាទាមទារ
Telethon + API_ID/API_HASH + Fernet key។ Handler នេះគ្រប់គ្រង Record ដែលមានស្រាប់។
"""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from admin_bot import keyboards, render
from database import crud, db_session

router = Router()

HOWTO = (
    "📱 <b>ការបន័ែមគណនី Telegram</b>\n\n"
    "ចំណុចនេះមកដល់ក្នុង <b>ជំហានទី ២</b> (Userbot/Telethon) ដែលត្រូវការ៖\n"
    "1. <code>TG_API_ID</code> + <code>TG_API_HASH</code> ពី my.telegram.org\n"
    "2. <code>SESSION_FERNET_KEY</code> សម្រាប់ បិទបាំង (encrypt) session string\n\n"
    "⚠️ <b>ណែនាំអំពីសុវត្ថិភាព</b>៖ ខ្ញុំនឹងសង់ OTP flow ក្នុង <b>terminal របស់អ្នក</b> "
    "(<code>python -m userbot.add_account +855XXXXXXXX</code>) ជំនួសឱ្យការវាយ OTP/2FA "
    "ចូលក្នុង chat របស់ Bot — ព្រោះសារក្នុង chat អាចស្ថិតក្នុង log, backup DB "
    "និង ទិន្នន័យដែល Telegram រក្សាទុក។\n\n"
    "អ្វីដែល Panel នេះធ្វើបានឥឡូវ៖ មើលស្ថានភាព, កំណត់ Primary, បិទ/បើក AI រាល់គណនី, លុប Record។"
)


def target_id(callback: CallbackQuery) -> int:
    return int(callback.data.rsplit(":", 1)[-1])


async def show_list(event: CallbackQuery | Message) -> None:
    async with db_session() as session:
        accounts = await crud.list_accounts(session)
    header = "📱 <b>គណនី Telegram</b>\n"
    if not accounts:
        header += "\n<i>មិនទាន់មានគណនី — មើល ℹ️ របៀបបន័ែមគណនី</i>"
    else:
        header += f"\nសរុប {len(accounts)} · ⭐ = Primary (គណនីដែល AI ប្រើឆ្លើយតប)"
    if isinstance(event, CallbackQuery):
        if event.message is None:
            await event.answer()
            return
        await event.message.edit_text(header, reply_markup=keyboards.accounts_menu(accounts))
        await event.answer()
    else:
        await event.answer(header, reply_markup=keyboards.accounts_menu(accounts))


async def show_account(callback: CallbackQuery, account_id: int, toast: str = "") -> None:
    async with db_session() as session:
        account = await crud.get_account(session, account_id)
        if account is None:
            await callback.answer("រកមិនឃើញគណនី", show_alert=True)
            return
        card = render.account_card(account)
        markup = keyboards.account_actions(account)
    if callback.message is None:
        await callback.answer(toast)
        return
    await callback.message.edit_text(card, reply_markup=markup)
    await callback.answer(toast)


@router.callback_query(F.data == "menu:accounts")
async def cb_accounts_root(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(None)
    await show_list(callback)


@router.callback_query(F.data == "acc:howto")
async def cb_howto(callback: CallbackQuery) -> None:
    if callback.message is None:
        await callback.answer()
        return
    await callback.message.edit_text(HOWTO, reply_markup=keyboards.accounts_menu([]))
    await callback.answer()


@router.callback_query(F.data.startswith("acc:view:"))
async def cb_view(callback: CallbackQuery) -> None:
    await show_account(callback, target_id(callback))


@router.callback_query(F.data.startswith("acc:primary:"))
async def cb_primary(callback: CallbackQuery) -> None:
    account_id = target_id(callback)
    async with db_session() as session:
        await crud.set_primary_account(session, account_id)
    await show_account(callback, account_id, toast="⭐ កំណត់ជា Primary រួច")


@router.callback_query(F.data.startswith("acc:ai:"))
async def cb_ai(callback: CallbackQuery) -> None:
    account_id = target_id(callback)
    async with db_session() as session:
        account = await crud.get_account(session, account_id)
        if account is None:
            await callback.answer("រកមិនឃើញ", show_alert=True)
            return
        account.ai_enabled = not account.ai_enabled
        enabled = account.ai_enabled
    await show_account(callback, account_id, toast=f"🤖 AI {'បើក' if enabled else 'បិទ'} សម្រាប់គណនីនេះ")


@router.callback_query(F.data.startswith("acc:askdel:"))
async def cb_ask_delete(callback: CallbackQuery) -> None:
    account_id = target_id(callback)
    async with db_session() as session:
        account = await crud.get_account(session, account_id)
    if account is None or callback.message is None:
        await callback.answer("រកមិនឃើញ" if account is None else "", show_alert=account is None)
        return
    await callback.message.edit_text(
        f"🗑 លុបគណនី <b>{account.phone}</b> <code>#{account.id}</code>?\n\n"
        "<i>ជំហានទី ២៖ Session string ត្រូវលុបចេញពី DB និង session file ក្នុង media/session។ "
        "អ្នកនៅតែអាច login ឡើងវិញដោយខ្លួនឯង។</i>",
        reply_markup=keyboards.confirm_action(f"លុប #{account_id}", f"acc:del:{account_id}"),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("acc:del:"))
async def cb_delete(callback: CallbackQuery) -> None:
    """លុប Record ហើយប្រគល់ star Primary ទៅគណនីដែលនៅសល់។"""
    account_id = target_id(callback)
    async with db_session() as session:
        account = await crud.get_account(session, account_id)
        phone = account.phone if account else ""
        was_primary = bool(account and account.is_primary)
        await crud.delete_account(session, account_id)
        if was_primary:
            remaining = await crud.list_accounts(session)
            if remaining:
                await crud.set_primary_account(session, remaining[0].id)
        accounts = await crud.list_accounts(session)
    if callback.message is None:
        await callback.answer()
        return
    await callback.message.edit_text(
        f"🗑 បានលុបគណនី <code>{phone}</code>", reply_markup=keyboards.accounts_menu(accounts)
    )
    await callback.answer()


@router.message(Command("accounts"))
async def cmd_accounts(message: Message, state: FSMContext) -> None:
    await state.set_state(None)
    await show_list(message)
