"""រចនាអត្ថបទ Display សម្រាប់ Panel (HTML) និងការបែងចែកសារវែង។"""
from __future__ import annotations

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardMarkup, Message

from database.models import Account, Customer, Order, Product, QRCode
from helpers import esc, format_dt, money, shorten
from database.models import OrderStatus

LIMIT = 3500  # Telegram អនុញ្ញាត ៤០៩៦ — ទុកទីតាំងសម្រាប់ markup និង emoji


async def send_long(target: Message, text: str) -> None:
    """ផ្ញើអត្ថបទវែង (System Prompt, កំណត់ត្រា) ដោយបំបែកជាបន្តបន្ទាប់។"""
    chunks = [text[index : index + LIMIT] for index in range(0, len(text), LIMIT)] or ["(ទទេ)"]
    for chunk in chunks:
        try:
            await target.answer(chunk)
        except TelegramBadRequest as exc:
            await target.answer(f"⚠️ មិនអាចផ្ញើបានទេ: {type(exc).__name__}")


async def safe_edit(message: Message, text: str, reply_markup: InlineKeyboardMarkup | None = None) -> None:
    """Edit សារ Panel ដោយមិនដួល — Telegram ឱ្យ `message is not modified` ពេលអត្ថបទ + markup
    ដូចគ្នាទាំងស្រុង (ចុចប៊ូតុងដដែលពីរដង ឬ toggle ត្រឡប់មកតម្លៃចាស់)។"""
    try:
        await message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest as exc:
        if "not modified" in str(exc):
            return
        raise


def product_card(product: Product, remaining: int | None = None) -> str:
    left = product.remaining if remaining is None else remaining
    lines = [
        f"📦 <b>{esc(product.name)}</b>  <code>#{product.id}</code>"
        + (f"  🏷 <code>{esc(product.product_code)}</code>" if product.product_code else ""),
        f"💰 {money(product.price)}" + (f" → <b>{money(product.final_price)}</b> (-{product.discount_percent}%)" if product.discount_percent else ""),
        f"🏷 {esc(product.category)} · {'🟢 បើក' if product.is_active else '⚪ បិទ'}",
        f"📊 Stock: <b>{left}</b>"
        + (f" · 🟢សល់ {product.available} · 🟡កក់ {product.reserved}" if product.stock else "")
        + ("  ⚠️ តិច/អស់" if left <= 0 else ""),
        f"🖼 រូបភាព: {len(product.image_paths or [])}",
    ]
    if product.description:
        lines.append(f"📝 {esc(shorten(product.description, 300))}")
    return "\n".join(lines)


def order_card(order: Order) -> str:
    status = OrderStatus.LABELS.get(order.status, order.status)
    lines = [
        f"🧾 <b>Order #{order.id}</b> — {status}",
        f"👤 {esc(order.customer_name or '—')} <code>{order.customer_id}</code>",
        f"📦 {esc(order.product_name or '—')} × {order.quantity}",
        f"💰 {money(order.price * order.quantity)}",
        f"🕒 {format_dt(order.created_at)}",
    ]
    if order.slip_file_id:
        lines.append("🖼 បានទទួល Slip")
    if order.delivered_code:
        lines.append(f"🔑 Code: <code>{esc(order.delivered_code)}</code>")
    if order.delivered_at:
        lines.append(f"✅ ប្រគល់ពេល {format_dt(order.delivered_at)}")
    if order.note:
        lines.append(f"📝 {esc(shorten(order.note, 200))}")
    return "\n".join(lines)


def customer_card(customer: Customer) -> str:
    flags = []
    if customer.ai_paused:
        flags.append("⏸ AI Paused")
    if customer.is_blocked:
        flags.append("🚫 Blocked")
    lines = [
        f"👤 <b>{esc(customer.name or '—')}</b>",
        f"<code>{customer.telegram_id}</code> @" + esc(customer.username or "—"),
        f"🏷 Tags: {esc(', '.join(customer.tags or []) or '—')}",
        f"🛒 Orders: {customer.total_orders} · ចំណាយសរុប: {money(customer.total_spent)}",
        f"🕒 ចុងក្រោយ: {format_dt(customer.last_seen)}",
        f"📅 ចាប់ផ្តើម: {format_dt(customer.first_seen)}",
    ]
    if flags:
        lines.append(" · ".join(flags))
    if customer.notes:
        lines.append(f"📝 {esc(shorten(customer.notes, 300))}")
    return "\n".join(lines)


def account_row(account: Account, index: int) -> str:
    """បន្ទាត់គណនីមួយក្នុងបញ្ជី /accounts — លេខរៀង + ស្ថានភាព + លេខបិទកណ្តាល (គ្មានកំណត់ចំនួន)។"""
    from database.models import AccountStatus
    from userbot import safety

    star = " ⭐" if account.is_primary else ""
    return (
        f"{index}. <b>{esc(account.display_label())}</b> <code>#{account.id}</code>{star}\n"
        f"   {AccountStatus.LABELS.get(account.status, account.status)}"
        f" · {'🤖 on' if account.ai_enabled else '🤖 off'}"
        f" · {'🟢 បើក' if account.enabled else '⚪ បិទ'}"
        f" · 🔐 {'✅' if account.session_encrypted else '❌'}"
        f" · 📞 {esc(safety.mask_phone(account.phone))}"
    )


def account_card(account: Account) -> str:
    from database.models import AccountStatus
    from userbot import credentials, safety

    # បង្ហាញស្ថានភាពប៉ុណ្ណោះ — api_id/api_hash/session string មិនដែលចេញជាអត្ថបទទេ
    key_line = (
        "🔑 <b>App:</b> ✅ កំណត់ក្នុង <code>.env</code> រួច"
        if credentials.is_configured()
        else "🔑 <b>App:</b> ❌ <code>.env</code> ខ្វះ TG_API_ID/TG_API_HASH"
    )
    session_line = "🔐 <b>Session:</b> ✅ Configured" if account.session_encrypted else "🔐 <b>Session:</b> ❌ នៅមិនទាន់មាន"
    owner_line = "" if account.owner_admin_id is None else f"👑 <b>ម្ចាស់:</b> <code>{account.owner_admin_id}</code>"
    lines = [
        f"{'⭐' if account.is_primary else '▫️'} <b>គណនី #{account.id}</b> · {esc(account.display_label())}",
        f"<b>{AccountStatus.LABELS.get(account.status, account.status)}</b>"
        f" · {'🟢 AI ឆ្លើយ' if account.ai_enabled else '⚪ AI ឈប់'}"
        f" · {'🟢 បើក' if account.enabled else '⚪ បិទ'}",
        f"📞 {esc(safety.mask_phone(account.phone))} · 🆔 <code>{account.telegram_user_id or '—'}</code>",
        session_line,
        key_line,
        f"🕒 បង្កើត {format_dt(account.created_at)}" + (f" · ⏰ {esc(account.working_hours)}" if account.working_hours else ""),
    ]
    if owner_line:
        lines.append(owner_line)
    if account.last_error:
        lines.append(f"⚠️ {esc(shorten(account.last_error, 160))}")
    return "\n".join(lines)


def qrcode_card(qr: QRCode, account_names: dict[int, str] | None = None) -> str:
    lines = [
        f"💳 <b>{esc(qr.name)}</b>  <code>#{qr.id}</code>  [{esc(qr.provider)}]",
        f"{'⭐ Default' if qr.is_default else '⚪ មិនមែន default'}",
    ]
    if qr.account_id is not None:
        label = esc((account_names or {}).get(qr.account_id) or f"#{qr.account_id}")
        lines.append(f"🤖 គណនីដែលលក់ → ប្រាក់ចូលគណនីនេះតែមួយ៖ {label} (<code>#{qr.account_id}</code>)")
    else:
        lines.append("🌐 QR ទូទៅ — ប្រើបានគ្រប់គណនី ប៉ុន្តែ QR ដែលភ្ជាប់គណនីនីមួយៗ មានអាទិភាពជាង")
    if qr.account_info:
        lines.append(f"🔖 {esc(shorten(qr.account_info, 200))}")
    if qr.image_file_id:
        lines.append("🖼 មានរូប QR")
    if qr.product_id:
        lines.append(f"📦 ភ្ជាប់នឹងផលិតផល #{qr.product_id}")
    return "\n".join(lines)
