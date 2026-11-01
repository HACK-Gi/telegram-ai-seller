"""📊 Analytics — ចំណូល, Order, ផលិតផលលក់ដាច់, អតិថិជនថ្មី vs ត្រឡប់មកវិញ។"""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from admin_bot import keyboards, render
from admin_bot.scope import Scope
from database import crud, db_session
from helpers import money
from services.reports import build_report

router = Router()
PERIODS = ("today", "week", "month", "year")


async def show_report(event: Message | CallbackQuery, period: str, scope: Scope) -> None:
    async with db_session() as session:
        text = await build_report(session, period, owner_admin_id=scope.owner_id, account_ids=scope.ids)
    if isinstance(event, CallbackQuery):
        if event.message is None:
            await event.answer()
            return
        await event.message.edit_text(text, reply_markup=keyboards.analytics_menu())
        await event.answer()
    else:
        await event.answer(text, reply_markup=keyboards.analytics_menu())


@router.callback_query(F.data == "menu:analytics")
async def cb_analytics_root(callback: CallbackQuery, state: FSMContext, scope: Scope) -> None:
    await state.set_state(None)
    await show_report(callback, "today", scope)


@router.callback_query(F.data == "ana:send")
async def cb_analytics_send(callback: CallbackQuery, scope: Scope) -> None:
    """ផ្ញើរបាយការណ៍ថ្មីជាសារឯករាជ៙ ដើម្បី copy ឬ forward បាន។"""
    if callback.message is None:
        await callback.answer()
        return
    async with db_session() as session:
        text = await build_report(session, "today", owner_admin_id=scope.owner_id, account_ids=scope.ids)
    await callback.message.answer(text)
    await callback.answer("បានផ្ញើរបាយការណ៍")


@router.callback_query(F.data.startswith("ana:"))
async def cb_analytics_period(callback: CallbackQuery, scope: Scope) -> None:
    period = callback.data.split(":", 1)[1]
    if period not in PERIODS:
        await callback.answer()
        return
    await show_report(callback, period, scope)


@router.message(Command("stats"))
async def cmd_stats(message: Message, scope: Scope) -> None:
    async with db_session() as session:
        start, end = crud.period_bounds("today")
        revenue = await crud.revenue_between(session, start, end, account_ids=scope.ids)
        counts = await crud.order_counts_by_status(session, account_ids=scope.ids)
        threshold = int(await crud.get_setting(session, "stock_alert_threshold") or 5)
        low = await crud.low_stock_products(session, threshold, owner_admin_id=scope.owner_id)
        accounts = await crud.list_accounts(session, owner_admin_id=scope.owner_id)
    body = (
        f"📊 <b>សង្ខេបថ្ងៃនេះ</b>\n"
        f"💰 ចំណូលបញ្ជាក់: <b>{money(revenue)}</b>\n"
        f"🛒 រង់ចាំផ្ទៀងផ្ទាត់: <b>{counts['awaiting_verify']}</b> · រង់ចាំបង់: <b>{counts['pending_payment']}</b>\n"
        f"✅ បានប្រគល់: <b>{counts['delivered']}</b> · ❌ បោះបង់: <b>{counts['cancelled']}</b>\n"
        f"📱 គណនី Userbot: <b>{len(accounts)}</b>\n"
        + (
            "⚠️ Stock តិច: " + ", ".join(f"{item.name} ({remaining})" for item, remaining in low)
            if low
            else "✅ Stock គ្រប់គ្រាន់គ្រប់ផលិតផល"
        )
    )
    await message.answer(body, reply_markup=keyboards.main_menu(scope.is_owner))
