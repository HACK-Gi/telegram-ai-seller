"""👥 អតិថិជន (CRM) — Tags, Notes, Block, និងការគ្រប់គ្រង AI រូបបុគ្គល។

Owner និង Staff អាច `/pause <telegram_id>` ដើម្បីឆ្លើយអតិថិជននោះដោយដៃ (Userbot គោរព
តាម flag នេះក្នុង ជំហានទី ២) ហើយ `/resume <telegram_id>` ដើម្បីប្រគល់ឱ្យ AI វិញ —
Staff បានតែក្នុងវិសាលភាពគណនីរបស់ខ្លួន រីឯ `/pauseall` `/resumeall` ជាប់លាប់ទាំងអស់ = តែ Owner។
"""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from admin_bot import keyboards, render
from admin_bot.scope import Scope
from database import crud, db_session
from database.models import Customer, OrderStatus
from helpers import esc, pagination_pages

router = Router()
log = logging.getLogger("admin.customers")
PER_PAGE = 8

NOT_FOUND = "🚫 រកមិនឃើញអតិថិជននេះទេ"
OWNER_ONLY = "🔐 គត់ Owner ប៉ុណ្ណោះដែលអាចប្តូរ AI របស់អតិថិជនទាំងអស់"


class SetTags(StatesGroup):
    tags = State()


class SetNote(StatesGroup):
    note = State()


class SearchCustomers(StatesGroup):
    term = State()


def target_id(callback: CallbackQuery) -> int:
    return int(callback.data.rsplit(":", 1)[-1])


async def guard_customer(callback: CallbackQuery, customer_pk: int, scope: Scope) -> Customer | None:
    """IDOR guard — អានអតិថិជនតាមវិសាលភាព <i>មុន</i> កែទិន្នន័យ។ បើមិនក្នុងវិសាលភាព = បដិសេធ។"""
    async with db_session() as session:
        customer = await crud.get_customer(session, customer_pk, account_ids=scope.ids)
    if customer is None:
        log.warning("IDOR: user=%s cust=%s", scope.admin_id, customer_pk)
        await callback.answer(NOT_FOUND, show_alert=True)
    return customer


async def show_list(event: Message | CallbackQuery, state: FSMContext, scope: Scope, page: int | None = None) -> None:
    data = await state.get_data()
    current_page = page if page is not None else int(data.get("cus_page", 1))
    search = data.get("cus_search", "")
    tag = data.get("cus_tag", "")
    await state.update_data(cus_page=current_page)

    async with db_session() as session:
        customers, total = await crud.list_customers(
            session, search=search, tag=tag, page=current_page, per_page=PER_PAGE,
            account_ids=scope.ids,
        )
    pages = pagination_pages(total, PER_PAGE)
    current_page = min(current_page, pages)
    header = f"👥 <b>អតិថិជន</b> — រកឃើញ {total}" + (f"\n🏷 <code>{esc(tag)}</code>" if tag else "") + (
        f"\n🔍 <code>{esc(search)}</code>" if search else ""
    )
    if not customers:
        header += "\n\n<i>មិនមានអតិថិជនទេ</i>"
        if not scope.ids:
            header += "\n⚠️ <i>មិនទាន់មានគណនីរបស់អ្នក — ចុច ➕ បន័ែមគណនី ឬវាយ <code>/addsession</code>។ Userbot នឹងបង្កើតអតិថិជនពេលមានសារចូល</i>"
        else:
            header += "\n<i>អតិថិជននឹងចូលបញ្ជីនេះពេលមានសារមកគណនីរបស់អ្នក</i>"

    markup = keyboards.customers_menu(customers, current_page, pages)
    if isinstance(event, CallbackQuery):
        if event.message is None:
            await event.answer()
            return
        await event.message.edit_text(header, reply_markup=markup)
        await event.answer()
    else:
        await event.answer(header, reply_markup=markup)


async def show_customer(callback: CallbackQuery, customer_pk: int, scope: Scope) -> None:
    customer = await guard_customer(callback, customer_pk, scope)
    if customer is None:
        return
    card = render.customer_card(customer)
    markup = keyboards.customer_actions(customer)
    if callback.message is None:
        await callback.answer()
        return
    await callback.message.edit_text(card, reply_markup=markup)
    await callback.answer()


# ---------------- បញ្ជី / រុករក ----------------

@router.callback_query(F.data == "menu:customers")
async def cb_customers_root(callback: CallbackQuery, state: FSMContext, scope: Scope) -> None:
    await state.set_state(None)
    await state.update_data(cus_page=1, cus_search="", cus_tag="")
    await show_list(callback, state, scope, page=1)


@router.callback_query(F.data == "cus:list:prev")
async def cb_prev(callback: CallbackQuery, state: FSMContext, scope: Scope) -> None:
    await show_list(
        callback, state, scope, page=max(1, int((await state.get_data()).get("cus_page", 1)) - 1)
    )


@router.callback_query(F.data == "cus:list:next")
async def cb_next(callback: CallbackQuery, state: FSMContext, scope: Scope) -> None:
    await show_list(callback, state, scope, page=int((await state.get_data()).get("cus_page", 1)) + 1)


@router.callback_query(F.data.startswith("cus:view:"))
async def cb_view(callback: CallbackQuery, scope: Scope) -> None:
    await show_customer(callback, target_id(callback), scope)


@router.callback_query(F.data == "cus:search")
async def cb_search(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SearchCustomers.term)
    if callback.message is None:
        await callback.answer()
        return
    await callback.message.answer("🔍 សរសេរឈ្មោះ ឬ username (ឬ /cancel):")
    await callback.answer()


@router.message(SearchCustomers.term, F.text)
async def md_search(message: Message, state: FSMContext, scope: Scope) -> None:
    await state.update_data(cus_search=message.text.strip(), cus_page=1)
    await state.set_state(None)
    await show_list(message, state, scope, page=1)


@router.callback_query(F.data == "cus:tags")
async def cb_tags_menu(callback: CallbackQuery) -> None:
    if callback.message is None:
        await callback.answer()
        return
    await callback.message.edit_text("🏷 ជ្រើសរើស Tag ដើម្បីចម្រោះ:", reply_markup=keyboards.tags_menu())
    await callback.answer()


@router.callback_query(F.data.startswith("cus:filter:"))
async def cb_filter(callback: CallbackQuery, state: FSMContext, scope: Scope) -> None:
    tag = callback.data.split("cus:filter:", 1)[1]
    await state.update_data(cus_tag=tag, cus_page=1)
    await show_list(callback, state, scope, page=1)


# ---------------- សកម្មភាព ----------------

async def _toggle(callback: CallbackQuery, customer_pk: int, scope: Scope, toast: str = "", **values) -> None:
    if await guard_customer(callback, customer_pk, scope) is None:
        return
    async with db_session() as session:
        await crud.set_customer_flag(session, customer_pk, **values)
        customer = await crud.get_customer(session, customer_pk, account_ids=scope.ids)
        if customer is None:
            await callback.answer(NOT_FOUND, show_alert=True)
            return
        card = render.customer_card(customer)
        markup = keyboards.customer_actions(customer)
    if callback.message is not None:
        await callback.message.edit_text(card, reply_markup=markup)
    await callback.answer(toast)


@router.callback_query(F.data.startswith("cus:pause:"))
async def cb_pause(callback: CallbackQuery, scope: Scope) -> None:
    await _toggle(callback, target_id(callback), scope, toast="⏸ AI ឈប់ឆ្លើយអតិថិជននេះ", ai_paused=True)


@router.callback_query(F.data.startswith("cus:resume:"))
async def cb_resume(callback: CallbackQuery, scope: Scope) -> None:
    await _toggle(callback, target_id(callback), scope, toast="▶️ AI ត្រឡប់មកឆ្លើយវិញ", ai_paused=False)


@router.callback_query(F.data.startswith("cus:block:"))
async def cb_block(callback: CallbackQuery, scope: Scope) -> None:
    await _toggle(callback, target_id(callback), scope, toast="🚫 បាន Block", is_blocked=True, ai_paused=True)


@router.callback_query(F.data.startswith("cus:unblock:"))
async def cb_unblock(callback: CallbackQuery, scope: Scope) -> None:
    await _toggle(callback, target_id(callback), scope, toast="✅ បាន Unblock", is_blocked=False)


@router.callback_query(F.data.startswith("cus:tagsel:"))
async def cb_tags_edit(callback: CallbackQuery, state: FSMContext, scope: Scope) -> None:
    customer = await guard_customer(callback, target_id(callback), scope)
    if customer is None:
        return
    await state.set_state(SetTags.tags)
    await state.update_data(tag_customer=customer.id)
    if callback.message is None:
        await callback.answer()
        return
    await callback.message.answer(
        "🏷 សរសេរ Tags ដោយឆ្លាស់ comma (ជំនួសរបស់ចាស់)៖\n<code>VIP, ស្មោះត្រង់</code>"
    )
    await callback.answer()


@router.message(SetTags.tags, F.text)
async def md_tags(message: Message, state: FSMContext, scope: Scope) -> None:
    data = await state.get_data()
    customer_pk = data["tag_customer"]
    tags = [item.strip() for item in message.text.split(",") if item.strip()]
    async with db_session() as session:
        customer = await crud.get_customer(session, customer_pk, account_ids=scope.ids)
        if customer is None:
            log.warning("IDOR: user=%s cust=%s", scope.admin_id, customer_pk)
            await message.answer(NOT_FOUND)
            await state.set_state(None)
            return
        customer.tags = tags
        card = render.customer_card(customer)
        markup = keyboards.customer_actions(customer)
    await state.set_state(None)
    await message.answer(f"✅ Tags ថ្មី: {', '.join(tags) or '—'}", reply_markup=markup)


@router.callback_query(F.data.startswith("cus:note:"))
async def cb_note(callback: CallbackQuery, state: FSMContext, scope: Scope) -> None:
    customer = await guard_customer(callback, target_id(callback), scope)
    if customer is None:
        return
    await state.set_state(SetNote.note)
    await state.update_data(note_customer=customer.id)
    if callback.message is None:
        await callback.answer()
        return
    await callback.message.answer("📝 សរសេរកំណត់ត្រា (<code>-</code> ដើម្បីសម្អាត):")
    await callback.answer()


@router.message(SetNote.note, F.text)
async def md_note(message: Message, state: FSMContext, scope: Scope) -> None:
    data = await state.get_data()
    customer_pk = data["note_customer"]
    raw = message.text.strip()
    async with db_session() as session:
        customer = await crud.get_customer(session, customer_pk, account_ids=scope.ids)
        if customer is None:
            log.warning("IDOR: user=%s cust=%s", scope.admin_id, customer_pk)
            await message.answer(NOT_FOUND)
            await state.set_state(None)
            return
        customer.notes = "" if raw in ("-", "ទទេ") else raw
        card = render.customer_card(customer)
        markup = keyboards.customer_actions(customer)
    await state.set_state(None)
    await message.answer("✅ បានរក្សាទុក", reply_markup=markup)


@router.callback_query(F.data.startswith("cus:orders:"))
async def cb_customer_orders(callback: CallbackQuery, scope: Scope) -> None:
    customer_pk = target_id(callback)
    customer = await guard_customer(callback, customer_pk, scope)
    if customer is None:
        return
    async with db_session() as session:
        orders, total = await crud.list_orders(
            session, customer_id=customer.telegram_id, page=1, per_page=12, account_ids=scope.ids
        )
        telegram_id = customer.telegram_id
    body = f"🧾 Order របស់ <code>{telegram_id}</code> — សរុប {total}\n" + "\n".join(
        f"#{item.id} · {esc(item.product_name)} · {OrderStatus.LABELS.get(item.status, item.status)}" for item in orders
    )
    if callback.message is None:
        await callback.answer()
        return
    await callback.message.edit_text(body, reply_markup=keyboards.customer_actions(customer))
    await callback.answer()


@router.callback_query(F.data.startswith("cus:askclear:"))
async def cb_ask_clear(callback: CallbackQuery, scope: Scope) -> None:
    customer = await guard_customer(callback, target_id(callback), scope)
    if customer is None:
        return
    if callback.message is None:
        await callback.answer()
        return
    await callback.message.edit_text(
        "🧠 សម្អាតប្រវត្តិសារ (Context Memory) របស់អតិថិជននេះ?\n"
        "<i>AI នឹងចាប់ផ្តើមសន្ទនាថ្មី ស្អាត ដោយអានតែ Prompt ប៉ុណ្ណោះ។</i>",
        reply_markup=keyboards.confirm_action(f"សម្អាត Context #{customer.id}", f"cus:clear:{customer.id}"),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("cus:clear:"))
async def cb_clear(callback: CallbackQuery, scope: Scope) -> None:
    customer = await guard_customer(callback, target_id(callback), scope)
    if customer is None:
        return
    async with db_session() as session:
        removed = await crud.clear_history(session, customer.telegram_id)
    card = render.customer_card(customer)
    markup = keyboards.customer_actions(customer)
    if callback.message is not None:
        await callback.message.edit_text(card + f"\n\n🧹 បានសម្អាត {removed} សារ", reply_markup=markup)
    await callback.answer()


# ---------------- Commands របស់ម្ចាស់ ----------------

@router.message(Command("pause"))
async def cmd_pause(message: Message, command: CommandObject, scope: Scope) -> None:
    await _command_flag(message, command, scope, ai_paused=True, ok="⏸ AI paused")


@router.message(Command("resume"))
async def cmd_resume(message: Message, command: CommandObject, scope: Scope) -> None:
    await _command_flag(message, command, scope, ai_paused=False, ok="▶️ AI resumed")


async def _command_flag(message: Message, command: CommandObject, scope: Scope, *, ai_paused: bool, ok: str) -> None:
    """`/pause <telegram_id>` — រក Customer តាម Telegram ID ដោយផ្ទាល់ ក្នុងវិសាលភាពរបស់អ្នក។"""
    if not command.args:
        await message.answer("ℹ️ ប្រើ: <code>/pause 123456789</code> ឬ <code>/resume 123456789</code>")
        return
    try:
        telegram_id = int(command.args.split()[0])
    except ValueError:
        await message.answer("⛔ Telegram ID ត្រូវជាលេខ")
        return
    async with db_session() as session:
        customer = await crud.get_customer_by_telegram(session, telegram_id, account_ids=scope.ids)
        if customer is None:
            log.warning("IDOR: user=%s cust=%s", scope.admin_id, telegram_id)
            await message.answer(
                f"⛔ រកមិនឃើញអតិថិជន <code>{telegram_id}</code>\n"
                "<i>គេមិនធ្លាប់ផ្ញើសារមក ឬមិនមែនអតិថិជនរបស់គណនីអ្នក (Userbot បង្កើត Record ពេលមានសារចូល)។</i>"
            )
            return
        await crud.set_customer_flag(session, customer.id, ai_paused=ai_paused)
        card = render.customer_card(customer)
        markup = keyboards.customer_actions(customer)
    await message.answer(f"{ok} — <code>{telegram_id}</code>\n\n{card}", reply_markup=markup)


async def _tenant_pause_all(message: Message, scope: Scope, *, paused: bool) -> None:
    """ម្ចាស់ហាងបិទ/បើក AI តែក្នុងគណនីរបស់ខ្លួន — មិនប៉ះ `ai_enabled` global ទេ។"""
    if not scope.has_accounts:
        await message.answer(
            "⛔ អ្នកមិនទាន់មានគណនីរបស់ខ្លួនទេ — ចុច ➕ បន័ែមគណនី ឬវាយ <code>/addsession</code>"
        )
        return
    async with db_session() as session:
        changed = await crud.pause_all_customers(session, paused=paused, account_ids=scope.ids)
    verb = "ផ្អាក" if paused else "បន្ត"
    await message.answer(
        f"⏯ <b>{verb} AI</b> អតិថិជន {changed} រូប ក្នុង {len(scope.ids)} គណនីរបស់អ្នក\n"
        "<i>ហាងផ្សេង មិនត្រូវបានប៉ះទេ</i>"
    )


@router.message(Command("pauseall"))
async def cmd_pause_all(message: Message, scope: Scope) -> None:
    if not scope.is_owner:
        await _tenant_pause_all(message, scope, paused=True)
        return
    async with db_session() as session:
        await crud.set_setting(session, "ai_enabled", "off")
    await message.answer(
        "⏸ <b>AI ឈប់ឆ្លើយទាំងអស់</b>\nម្ចាស់ឆ្លើយដោយដៃ។ បន្តដោយ <code>/resumeall</code> ឬ ⚙️ → 🤖 Toggle AI"
    )


@router.message(Command("resumeall"))
async def cmd_resume_all(message: Message, scope: Scope) -> None:
    if not scope.is_owner:
        await _tenant_pause_all(message, scope, paused=False)
        return
    async with db_session() as session:
        await crud.set_setting(session, "ai_enabled", "on")
        cleared = await crud.pause_all_customers(session, paused=False)
    await message.answer(
        f"▶️ <b>AI ដំណើរការវិញទាំងអស់</b>\nបានលើក per-customer pause {cleared} រូប"
    )
