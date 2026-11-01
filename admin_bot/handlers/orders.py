"""🛒 Orders — បញ្ជីរង់ចាំ, ផ្ទៀងផ្ទាត់ Slip, បញ្ចេញ Code ពី Stock, ប្រវត្តិ។"""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from admin_bot import keyboards, media, render
from admin_bot.scope import Scope
from database import crud, db_session
from database.models import Order, OrderStatus
from helpers import esc, money, pagination_pages

log = logging.getLogger("admin.orders")
router = Router()
PER_PAGE = 8

NOT_FOUND = "🚫 រកមិនឃើញ Order នេះក្នុងវិសាលភាពរបស់អ្នក"
NO_ACCOUNT = "🔐 អ្នកគ្មានគណនី Userbot ទេ — សូមសុំម្ចាស់បន្ថែមគណនី មុនបង្កើត Order"


class AddOrder(StatesGroup):
    customer = State()
    product = State()


class EditNote(StatesGroup):
    note = State()


def target_id(callback: CallbackQuery) -> int:
    return int(callback.data.rsplit(":", 1)[-1])


async def guard_order(callback: CallbackQuery, order_id: int, scope: Scope) -> Order | None:
    """IDOR guard — អាន Order តាមវិសាលភាព <i>មុន</i> បញ្ចេញ Code/បោះបង់។ ក្រៅវិសាលភាព = បដិសេធ។"""
    async with db_session() as session:
        order = await crud.get_order(session, order_id, account_ids=scope.ids)
    if order is None:
        log.warning("IDOR: user=%s order=%s ក្រៅវិសាលភាព", scope.admin_id, order_id)
        await callback.answer(NOT_FOUND, show_alert=True)
    return order


async def show_list(callback: CallbackQuery, state: FSMContext, scope: Scope, page: int | None = None) -> None:
    data = await state.get_data()
    status = data.get("ord_status", OrderStatus.AWAITING_VERIFY)
    current_page = page if page is not None else int(data.get("ord_page", 1))
    await state.update_data(ord_page=current_page, ord_status=status)

    async with db_session() as session:
        counts = await crud.order_counts_by_status(session, account_ids=scope.ids)
        orders, total = await crud.list_orders(
            session,
            status=None if status == "all" else status,
            page=current_page,
            per_page=PER_PAGE,
            account_ids=scope.ids,
        )
    pages = pagination_pages(total, PER_PAGE)
    current_page = min(current_page, pages)
    header = (
        "🛒 <b>Orders</b>\n"
        f"🔎 Filter: <b>{OrderStatus.LABELS.get(status, '📚 ទាំងអស់')}</b> · រកឃើញ {total}\n"
        "<i>ចុច Tab ដើម្បីប្តូរស្ថានភាព</i>"
    )
    if not orders:
        header += "\n\n<i>អត់មាន Order ក្នុងស្ថានភាពនេះ</i>"
    if callback.message is None:
        await callback.answer()
        return
    await callback.message.edit_text(header, reply_markup=keyboards.orders_menu(counts, orders, current_page, pages, status))
    await callback.answer()


async def show_order(callback: CallbackQuery, order_id: int, scope: Scope, toast: str = "") -> None:
    order = await guard_order(callback, order_id, scope)
    if order is None:
        return
    async with db_session() as session:
        card = render.order_card(order)
        markup = keyboards.order_actions(order)
        product_id = order.product_id
        remaining = await crud.stock_remaining(session, product_id) if product_id else None
    if callback.message is None:
        await callback.answer()
        return
    extra = f"\n📦 Stock សល់: <b>{remaining}</b>" if remaining is not None else ""
    await callback.message.edit_text(card + extra, reply_markup=markup)
    await callback.answer(toast)


# ---------------- បញ្ជី ----------------

@router.callback_query(F.data == "menu:orders")
async def cb_orders_root(callback: CallbackQuery, state: FSMContext, scope: Scope) -> None:
    await state.set_state(None)
    await state.update_data(ord_status=OrderStatus.AWAITING_VERIFY, ord_page=1)
    await show_list(callback, state, scope, page=1)


@router.callback_query(F.data.startswith("ord:list:"))
async def cb_orders_filter(callback: CallbackQuery, state: FSMContext, scope: Scope) -> None:
    value = callback.data.split(":", 2)[2]
    if value in ("prev", "next"):
        page = int((await state.get_data()).get("ord_page", 1)) + (1 if value == "next" else -1)
        await show_list(callback, state, scope, page=max(1, page))
        return
    await state.update_data(ord_status=value, ord_page=1)
    await show_list(callback, state, scope, page=1)


@router.callback_query(F.data.startswith("ord:view:"))
async def cb_order_view(callback: CallbackQuery, scope: Scope) -> None:
    await show_order(callback, target_id(callback), scope)


@router.callback_query(F.data.startswith("ord:slip:"))
async def cb_order_slip(callback: CallbackQuery, scope: Scope) -> None:
    order_id = target_id(callback)
    async with db_session() as session:
        order = await crud.get_order(session, order_id, account_ids=scope.ids)
        if order is None:
            log.warning("IDOR: user=%s order=%s slip", scope.admin_id, order_id)
            await callback.answer(NOT_FOUND, show_alert=True)
            return
        file_id = order.slip_file_id
        name = order.customer_name
    if not file_id:
        await callback.answer("Order នេះមិនមាន Slip ទេ", show_alert=True)
        return
    await media.send_photo_to_admin(callback.bot, callback.from_user.id, file_id, f"🧾 Slip · Order #{order_id} · {name}")
    await callback.answer()


# ---------------- ផ្ទៀងផ្ទាត់ + បញ្ចេញ Code ----------------

@router.callback_query(F.data.startswith("ord:confirm:"))
async def cb_order_confirm(callback: CallbackQuery, scope: Scope) -> None:
    """ផ្ទៀងផ្ទាត់ + បញ្ចេញ Code — ក្នុងវិសាលភាពរបស់ admin នោះ។ AI មិនធ្វើអ្វីទាំងនេះទេ។"""
    order_id = target_id(callback)
    if await guard_order(callback, order_id, scope) is None:
        return
    async with db_session() as session:
        order, code, message = await crud.confirm_and_deliver(session, order_id)
        if order is None:
            await callback.answer(message, show_alert=True)
            return
        card = render.order_card(order)
        markup = keyboards.order_actions(order)
        remaining = await crud.stock_remaining(session, order.product_id) if order.product_id else None

    if code is None:
        if callback.message is not None:
            await callback.message.edit_text(
                f"⚠️ <b>មិនអាចបញ្ចេញ Code បានទេ</b>\n{esc(message)}\n\n"
                f"🧾 Order #{order_id} នៅតែរង់ចាំ។ សូមបន័ែម Stock (📦 ផលិតផល → 🔢 Stock)",
                reply_markup=markup,
            )
        await callback.answer("Stock អស់!", show_alert=True)
        return

    if callback.message is not None:
        await callback.message.edit_text(
            f"✅ <b>Order #{order_id} បានបញ្ចាក់</b>\n\n🔑 Code: <code>{esc(code)}</code>\n"
            f"👤 អតិថិជន: <code>{order.customer_id}</code>\n"
            f"📦 Stock សល់: {remaining}\n\n"
            "<i>ជំហានទី ២៖ Userbot នឹងផ្ញើ Code នេះទៅអតិថិជនស្វ័យប្រវត្តិ។ "
            "ឥឡូវសូម copy បញ្ជូនទៅគេដោយដៃ។</i>",
            reply_markup=markup,
        )
    await callback.answer("បានបញ្ចេញ Code")


@router.callback_query(F.data.startswith("ord:askcancel:"))
async def cb_order_ask_cancel(callback: CallbackQuery, scope: Scope) -> None:
    order_id = target_id(callback)
    if await guard_order(callback, order_id, scope) is None:
        return
    if callback.message is None:
        await callback.answer()
        return
    await callback.message.edit_text(
        f"❌ បោះបង់ Order <code>#{order_id}</code>?\n<i>Code ដែលបានកាត់ នឹងមិនត្រឡប់មកវិញទេ (បើធ្លាប់បញ្ចាក់)។</i>",
        reply_markup=keyboards.confirm_action(f"បោះបង់ #{order_id}", f"ord:cancel:{order_id}"),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("ord:cancel:"))
async def cb_order_cancel(callback: CallbackQuery, scope: Scope) -> None:
    order_id = target_id(callback)
    if await guard_order(callback, order_id, scope) is None:
        return
    async with db_session() as session:
        await crud.cancel_order(session, order_id)
    await show_order(callback, order_id, scope, toast="បានបោះបង់ Order")


@router.callback_query(F.data.startswith("ord:note:"))
async def cb_order_note(callback: CallbackQuery, state: FSMContext, scope: Scope) -> None:
    order_id = target_id(callback)
    if await guard_order(callback, order_id, scope) is None:
        return
    await state.set_state(EditNote.note)
    await state.update_data(note_order=order_id)
    if callback.message is None:
        await callback.answer()
        return
    await callback.message.answer("📝 សរសេរកំណត់ត្រាសម្រាប់ Order នេះ (<code>-</code> ដើម្បីសម្អាត):")
    await callback.answer()


@router.message(EditNote.note, F.text)
async def md_order_note(message: Message, state: FSMContext, scope: Scope) -> None:
    data = await state.get_data()
    order_id = data["note_order"]
    raw = message.text.strip()
    note = "" if raw in ("-", "ទទេ") else raw
    async with db_session() as session:
        if await crud.get_order(session, order_id, account_ids=scope.ids) is None:
            log.warning("IDOR: user=%s order=%s note", scope.admin_id, order_id)
            await state.set_state(None)
            await message.answer(NOT_FOUND)
            return
        await crud.update_order(session, order_id, note=note)
    await state.set_state(None)
    await message.answer(
        f"✅ បានរក្សាទុកកំណត់ត្រា Order #{order_id}", reply_markup=keyboards.main_menu(scope.is_owner)
    )


# ---------------- បង្កើត Order ដោយដៃ ----------------

@router.callback_query(F.data == "ord:add")
async def cb_order_add(callback: CallbackQuery, state: FSMContext, scope: Scope) -> None:
    if not scope.has_accounts:
        log.info("ord:add បដិសេធ — user=%s គ្មានគណនី", scope.admin_id)
        await callback.answer(NO_ACCOUNT, show_alert=True)
        return
    async with db_session() as session:
        account_id = await crud.pick_order_account(
            session, owner_admin_id=scope.owner_id, account_ids=scope.ids
        )
    await state.set_state(AddOrder.customer)
    await state.update_data(order_account_id=account_id)
    if callback.message is None:
        await callback.answer()
        return
    await callback.message.answer(
        "➕ <b>បង្កើត Order ដោយដៃ</b>\n\n👤 ផ្ញើ <b>Telegram ID របស់អតិថិជន</b> (លេខ ឧ. 123456789):"
    )
    await callback.answer()


@router.message(AddOrder.customer, F.text)
async def md_order_customer(message: Message, state: FSMContext, scope: Scope) -> None:
    try:
        telegram_id = int(message.text.strip())
    except ValueError:
        await message.answer("⛔ ត្រូវជាលេខ ID តែប៉ុណ្ណោះ:")
        return
    await state.update_data(order_customer=telegram_id)
    await state.set_state(AddOrder.product)
    async with db_session() as session:
        products, _total = await crud.list_products(
            session, page=1, per_page=15, active_only=True, owner_admin_id=scope.owner_id
        )
    listing = "\n".join(f"<code>#{item.id}</code> {esc(item.name)} · {money(item.final_price)}" for item in products)
    await message.answer(
        f"📦 ផ្ញើ <b>ID ផលិតផល</b> ដែលត្រូវលក់៖\n{listing or '<i>មិនមានផលិតផលសកម្ម</i>'}"
    )


@router.message(AddOrder.product, F.text)
async def md_order_product(message: Message, state: FSMContext, scope: Scope) -> None:
    try:
        product_id = int(message.text.strip().lstrip("#"))
    except ValueError:
        await message.answer("⛔ ផ្ញើ ID ផលិតផលជាលេខ:")
        return
    data = await state.get_data()
    telegram_id = data["order_customer"]
    account_id = data.get("order_account_id")
    if account_id is None and not scope.is_owner:
        # staff ត្រូវតែមានគណនី ទើប order របស់គេ visible/attributable ក្នុងវិសាលភាព
        await state.set_state(None)
        await message.answer(NO_ACCOUNT, reply_markup=keyboards.main_menu(scope.is_owner))
        return
    async with db_session() as session:
        # ផលិតផលក្រៅវិសាលភាព = រកមិនឃើញ (IDOR) — staff លក់បានតែផលិតផលរបស់ខ្លួន
        product = await crud.get_product(session, product_id, owner_admin_id=scope.owner_id)
        if product is None:
            await message.answer("⛔ រកមិនឃើញផលិតផលនេះ")
            await state.set_state(None)
            return
        customer = await crud.get_or_create_customer(session, telegram_id)
        order = await crud.create_order(
            session,
            customer_id=telegram_id,
            product_id=product.id,
            product_name=product.name,
            price=product.final_price,
            customer_name=customer.name or str(telegram_id),
            status=OrderStatus.PENDING_PAYMENT,
            account_id=account_id,
        )
        order_id, card = order.id, render.order_card(order)
    await state.set_state(None)
    await message.answer(
        f"✅ បង្កើត Order <code>#{order_id}</code>\n\n{card}\n\n"
        "⏭ Userbot (ជំហានទី ២) នឹងផ្ញើ QR ទៅអតិថិជន។ ឥឡូវម្ចាស់អាច ផ្ទៀងផ្ទាត់ → បញ្ចេញ Code។",
        reply_markup=keyboards.order_actions(order),
    )


@router.message(Command("orders"))
async def cmd_orders(message: Message, scope: Scope) -> None:
    async with db_session() as session:
        counts = await crud.order_counts_by_status(session, account_ids=scope.ids)
        orders, total = await crud.list_orders(
            session, status=OrderStatus.AWAITING_VERIFY, page=1, per_page=8, account_ids=scope.ids
        )
    if not orders:
        await message.answer(
            "🛒 គ្មាន Order រង់ចាំផ្ទៀងផ្ទាត់ទេ\n"
            + "\n".join(f"· {label}: {counts.get(status, 0)}" for status, label in OrderStatus.LABELS.items()),
            reply_markup=keyboards.main_menu(scope.is_owner),
        )
        return
    body = "🛒 <b>Order រង់ចាំផ្ទៀងផ្ទាត់</b>\n" + "\n".join(
        f"#{item.id} · {esc(item.product_name)} · {money(item.price)} · {esc(item.customer_name or item.customer_id)}"
        for item in orders
    )
    await message.answer(body, reply_markup=keyboards.main_menu(scope.is_owner))
