"""របាយការណ៍ — ប្រើរួមគ្នា រវាង 📊 Analytics និង APScheduler (ជូនដំណឹងប្រចាំថ្ងៃ)។"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from database import crud
from database.models import OrderStatus
from helpers import format_dt, money, utcnow


async def build_report(
    session: AsyncSession,
    period: str = "today",
    *,
    owner_admin_id: int | None = None,
    account_ids: tuple[int, ...] | None = None,
) -> str:
    """សង្ខេបចំណូល/Order/ផលិតផលលក់ដាច់/អតិថិជន សម្រាប់ `period` (today|week|month|year)។

    គ្មានវិសាលភាព = របាយការណ៍ទាំងអស់ (scheduler ជូន owner)។ Panel ត្រូវបញ្ជូន
    `owner_admin_id`/`account_ids` ពី scope ជានិច្ច ទើប staff មិនឃើញលេខរបស់គណនីអ្នកដទៃ។
    """
    start, end = crud.period_bounds(period)
    revenue = await crud.revenue_between(session, start, end, account_ids=account_ids)
    counts = await crud.order_counts_by_status(session, account_ids=account_ids)
    in_period = await crud.order_counts_between(session, start, end, account_ids=account_ids)
    top = await crud.top_products(session, start, end, account_ids=account_ids)
    new_customers, returning = await crud.new_vs_returning(session, start, end, account_ids=account_ids)
    products, product_total = await crud.list_products(session, page=1, per_page=1000, owner_admin_id=owner_admin_id)
    low = await crud.low_stock_products(
        session, int(await crud.get_setting(session, "stock_alert_threshold") or 5), owner_admin_id=owner_admin_id
    )

    labels = {"today": "ថ្ងៃនេះ", "week": "សប្តាហ៍នេះ", "month": "ខែនេះ", "year": "ឆ្នាំនេះ"}
    lines = [
        f"📊 <b>របាយការណ៍ {labels.get(period, period)}</b>",
        f"🕒 {format_dt(utcnow())} ({period} → {format_dt(start, '%d/%m %H:%M')} UTC)",
        "",
        f"💰 ចំណូលបញ្ចាក់រួច: <b>{money(revenue)}</b>",
        f"🛒 Order ក្នុងចន្លោះ: <b>{sum(in_period.values())}</b>  (សរុបទាំងអស់ {sum(counts.values())})",
    ]
    for status in OrderStatus.ALL:
        lines.append(f"   · {OrderStatus.LABELS[status]}: {counts.get(status, 0)}")
    lines.append("")
    lines.append(f"👥 អតិថិជនថ្មី: <b>{new_customers}</b> · ត្រឡប់មកវិញ: <b>{returning}</b>")
    lines.append(f"📦 ផលិតផល: <b>{product_total}</b> (សកម្ម {sum(1 for item in products if item.is_active)})")
    if top:
        lines.append("\n🏆 លក់ដាច់បំផុត:")
        lines.extend(f"   {index}. {name} — {count}× · {money(total)}" for index, (name, count, total) in enumerate(top, 1))
    if low:
        lines.append("\n⚠️ Stock តិច:")
        lines.extend(f"   · {item.name} — សល់ {remaining}" for item, remaining in low)
    return "\n".join(lines)
