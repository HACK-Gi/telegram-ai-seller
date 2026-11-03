"""Inline keyboards ទាំងអស់សម្រាប់ Admin Panel។

callback_data ជា string សាមញ្ញ `section:action[:args]` ដូច្នេះ handler ចម្លើយបានច្បាស់
និងមិនអាស្រ័យលើ aiogram callback factory។
"""
from __future__ import annotations

from collections.abc import Sequence

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from database.models import Account, AccountStatus, Category, Customer, Order, OrderStatus, Product, QRCode
from helpers import esc, money


def build(rows: Sequence[Sequence[tuple[str, str] | None]]) -> InlineKeyboardMarkup:
    """(label, value) → button។ value ចាប់ផ្តើមដោយ `http://`/`https://` គឺ **URL button**
    (Telegram បើក browser) មិនមែន callback_data ទេ — ព្រោះ callback_data កំណត់ ៦៤ bytes
    ហើយ handler ទាំងអស់សន្មត់ string `section:action[:args]` ដែល URL មិនមែនជារូបភាពនោះ។
    """
    clean = [
        [
            (
                InlineKeyboardButton(text=text, url=data)
                if data.startswith(("http://", "https://"))
                else InlineKeyboardButton(text=text, callback_data=data)
            )
            for text, data in row
            if data
        ]
        for row in rows
    ]
    return InlineKeyboardMarkup(inline_keyboard=[row for row in clean if row])


def web_app_row() -> list[tuple[str, str]] | None:
    """ប៊ូតុងតំណទៅ Session Web App — `None` ពេល URL មិនចាប់ផ្តើមដោយ http (មិនទាន់ deploy
    ឬម្ចាស់បិតដោយ `SESSION_WEB_URL=off`) ទើបមេនុមិនបង្ហាញប៊ូតុងដែលចុចមិនបាន។
    """
    from config import settings  # import ក្នុង function ទើប test patch settings បាន

    url = (settings.session_web_url or "").strip()
    return [("🌐 បង្កើត Session String", url)] if url.startswith("http") else None


def pager(prefix: str, page: int, pages: int) -> list[tuple[str, str]]:
    """Page ត្រូវរក្សាទុកក្នុង FSM state ជំនួសឱ្យការដាក់ក្នុង callback_data។"""
    row: list[tuple[str, str]] = []
    if page > 1:
        row.append(("⬅️", f"{prefix}:prev"))
    row.append((f"📄 {page}/{pages}", "noop:page"))
    if page < pages:
        row.append(("➡️", f"{prefix}:next"))
    return row


BACK_MAIN = ("🏠 ត្រឡប់មេនុសំខាន់", "menu:main")
BUTTON_ROWS = 40  # Telegram កំណត់ ១០០ button ក្នុង keyboard មួយ — ទុកទីតាំងសម្រាប់ជួរផ្សេង


def main_menu(is_owner: bool) -> InlineKeyboardMarkup:
    """មេនុរបស់ <b>ម្ចាស់ហាងម្នាក់ៗ</b> — រាល់ប៊ូតុង drive ទិន្នន័យក្នុង scope របស់គេតែប៉ុណ្ណោះ។

    «គណនី + បន័ែមគណនី» នៅជួរលើកដំបូង ព្រោះវាជាចំណុចចាប់ផ្តើមលក់។ ផ្នែក global
    (System Prompt/ការកំណត់) លាក់សម្រាប់តែ Owner ដើម្បីឱ្យត្រូវ OwnerOnly filter។
    ជំហានទី ៤ — «🔐 Admins» ត្រូវលុបចេញទាំងស្រុង ព្រោះគ្មានតួនាទីដែលត្រូវបន្ថែមដោយដៃទៀតទេ។
    """
    rows = [
        [("📱 គណនី Telegram", "menu:accounts"), ("➕ បន័ែមគណនី", "acc:addsession")],
    ]
    web = web_app_row()
    if web:  # មិនទាន់ deploy Web App → គ្មានជួរនេះ ទើបមេនុមិនមានប៊ូតុងចុចមិនបាន
        rows.append(web)
    rows += [
        [("📦 ផលិតផល", "menu:products"), ("🏷 ប្រភេទអីវ៉ាន់", "menu:categories")],
        [("💳 QR Code", "menu:qr"), ("🛒 Orders", "menu:orders")],
        [("👥 អតិថិជន", "menu:customers"), ("📊 Analytics", "menu:analytics")],
    ]
    if is_owner:
        rows.append([("🧠 System Prompt", "menu:prompt")])
        rows.append([("⚙️ ការកំណត់", "menu:settings")])
    return build(rows)


def products_menu(products: Sequence[Product], page: int, pages: int) -> InlineKeyboardMarkup:
    rows = [
        [
            (
                f"{'🟢' if item.is_active else '⚪'} #{item.id} {esc(item.name)} · {money(item.final_price)}"
                + (f" [{esc(item.product_code)}]" if item.product_code else "")
                + f" · 📦{item.remaining}",
                f"prod:view:{item.id}",
            )
        ]
        for item in products
    ]
    rows.append(
        [
            ("➕ បន័ែមថ្មី", "prod:add"),
            ("🔍 ស្វែងរក", "prod:search"),
            ("🏷 ចម្រោះ", "prod:categories"),
            ("🗂 គ្រប់គ្រងប្រភេទ", "menu:categories"),
        ]
    )
    if pages > 1:
        rows.append(pager("prod:list", page, pages))
    rows.append([BACK_MAIN])
    return build(rows)


def product_actions(product: Product, remaining: int) -> InlineKeyboardMarkup:
    return build(
        [
            [("✏️ កែព័ត៌មាន", f"prod:edit:{product.id}"), (f"🔢 Stock ({remaining})", f"prod:stock:{product.id}")],
            [("🖼 រូបភាព", f"prod:images:{product.id}"), ("💳 ភ្ជាប់ QR", f"prod:qrpick:{product.id}")],
            [("⏯ បើក/បិទ", f"prod:toggle:{product.id}"), ("🗑 លុប", f"prod:askdel:{product.id}")],
            [("⬅️ បញ្ជីផលិតផល", "menu:products"), BACK_MAIN],
        ]
    )


def product_fields(product: Product) -> InlineKeyboardMarkup:
    return build(
        [
            [("📛 ឈ្មោះ", f"prod:f:name:{product.id}"), ("📝 ការពិពណ៌នា", f"prod:f:desc:{product.id}")],
            [("💰 តម្លៃ", f"prod:f:price:{product.id}"), ("🏷 ប្រភេទ", f"prod:f:cat:{product.id}")],
            [("💸 Discount %", f"prod:f:disc:{product.id}")],
            [("⬅️ ត្រឡប់", f"prod:view:{product.id}"), BACK_MAIN],
        ]
    )


def categories_filter_menu(categories: Sequence[Category]) -> InlineKeyboardMarkup:
    rows = [[(f"{item.icon} {esc(item.name_kh)}", f"prod:filter:{item.id}")] for item in categories]
    rows.append([("⏭ បង្ហាញទាំងអស់", "prod:filter:"), ("⬅️ បញ្ជីផលិតផល", "menu:products"), BACK_MAIN])
    return build(rows)


def category_manager(
    categories: Sequence[Category], counts: dict[int, int], *, can_manage: bool = True
) -> InlineKeyboardMarkup:
    rows = [
        [
            (
                f"{item.icon} {esc(item.name_kh)} · <{esc(item.code)}> · [{esc(item.product_prefix)}] · {counts.get(item.id, 0)} 📦",
                f"cat:view:{item.id}",
            )
        ]
        for item in categories
    ]
    if can_manage:
        rows.append([("➕ បន័ែមប្រភេទ", "cat:add")])
    rows.append([("🏷 ចម្រោះផលិតផល", "prod:categories"), ("⬅️ ផលិតផល", "menu:products"), BACK_MAIN])
    return build(rows)


def category_actions(
    category: Category, count: int, *, can_manage: bool = True
) -> InlineKeyboardMarkup:
    rows = [[(f"📦 មើលផលិតផល ({count})", f"prod:filter:{category.id}")]]
    if can_manage:
        rows[0].insert(0, ("✏️ កែព័ត៌មាន", f"cat:edit:{category.id}"))
        rows.append(
            [
                ("⏯ បិទ/បើក", f"cat:toggle:{category.id}"),
                ("🗑 លុប", f"cat:askdel:{category.id}"),
            ]
        )
    rows.append([("⬅️ បញ្ជីប្រភេទ", "menu:categories"), BACK_MAIN])
    return build(rows)


def category_fields(category: Category) -> InlineKeyboardMarkup:
    return build(
        [
            [("📛 ឈ្មោះខ្មែរ", f"cat:f:name_kh:{category.id}"), ("🇬🇧 ឈ្មោះអង់គ្លេស", f"cat:f:name_en:{category.id}")],
            [("🎨 Icon", f"cat:f:icon:{category.id}"), ("🔤 Prefix", f"cat:f:prefix:{category.id}")],
            [("📝 ការពិពណ៌នា", f"cat:f:description:{category.id}")],
            [("⬅️ ត្រឡប់", f"cat:view:{category.id}"), BACK_MAIN],
        ]
    )


def stock_mode_menu(product: Product) -> InlineKeyboardMarkup:
    return build(
        [
            [("🤖 ស្វ័យប្រវត្តិ (content lines → codes)", f"stock:auto:{product.id}")],
            [("✍️ គ្រាប់ Code ដោយខ្លួន", f"stock:manual:{product.id}")],
            [("⬅️ ត្រឡប់", f"prod:view:{product.id}"), BACK_MAIN],
        ]
    )


def confirm_action(label: str, confirm_data: str) -> InlineKeyboardMarkup:
    return build(
        [
            [(f"⚠️ បាទ/ចាស — {label}", confirm_data), ("❌ បោះបង់", "noop:cancel")],
            [BACK_MAIN],
        ]
    )


def qr_menu(qrs: Sequence[QRCode], account_names: dict[int, str] | None = None) -> InlineKeyboardMarkup:
    rows = []
    for item in qrs:
        tag = ""
        if item.account_id is not None:
            label = esc((account_names or {}).get(item.account_id) or f"#{item.account_id}")
            tag = f" 🤖{label}"
        rows.append(
            [(("⭐ " if item.is_default else "▫️ ") + f"{esc(item.name)} [{esc(item.provider)}]{tag}", f"qr:view:{item.id}")]
        )
    rows.append([("➕ បន័ែម QR (Upload រូបភាព)", "qr:add")])
    rows.append([BACK_MAIN])
    return build(rows)


def qr_actions(qr: QRCode) -> InlineKeyboardMarkup:
    rows = [[("⭐ ធ្វើជា Default", f"qr:default:{qr.id}"), ("🖼 ប្ដូររូបភាព QR", f"qr:image:{qr.id}")]]
    rows.append([("📦 ភ្ជាប់ផលិតផល", f"qr:link:{qr.id}"), ("🗑 លុប", f"qr:askdel:{qr.id}")])
    rows.append([("⬅️ បញ្ជី QR", "menu:qr"), BACK_MAIN])
    return build(rows)


def product_picker(action_prefix: str, products: Sequence[Product]) -> InlineKeyboardMarkup:
    rows = [[(f"#{item.id} {esc(item.name)}", f"{action_prefix}:{item.id}")] for item in products]
    rows.append([("⏭ ប្រើ QR Default", f"{action_prefix}:0"), ("⬅️ ត្រឡប់", "menu:products"), BACK_MAIN])
    return build(rows)


def account_picker(action_prefix: str, accounts: Sequence[Account], *, back_data: str = "menu:qr") -> InlineKeyboardMarkup:
    """ជ្រើសរើសគណនីដែល QR នេះជាការបង់ប្រាក់ពិតប្រាកដ — `{prefix}:0` = QR ទូទៅ។"""
    rows = [[(f"🤖 #{item.id} {esc(item.name)}", f"{action_prefix}:{item.id}")] for item in accounts]
    rows.append([("🌐 គ្មាន (QR ទូទៅ សម្រាប់គ្រប់គណនី)", f"{action_prefix}:0")])
    rows.append([("⬅️ ត្រឡប់", back_data), BACK_MAIN])
    return build(rows)


def prompt_menu() -> InlineKeyboardMarkup:
    return build(
        [
            [("👁 មើល Prompt ពេញ", "prompt:show"), ("✏️ កែ Prompt", "prompt:edit")],
            [("🎯 Few-shot examples", "prompt:fs"), ("🧪 សាកល្បង AI ពិត", "prompt:test")],
            [BACK_MAIN],
        ]
    )


def fs_menu(has_examples: bool) -> InlineKeyboardMarkup:
    rows = [[("👁 មើល", "prompt:fs:show"), ("✏️ សរសេរថ្មី", "prompt:fs:edit")]]
    rows.append([("📋 បញ្ចូលឧទាហរណ៍ Default", "prompt:fs:default")])
    if has_examples:
        rows.append([("🗑 សម្អាតទាំងអស់", "prompt:fs:askclear")])
    rows.append([("⬅️ ត្រឡប់ Prompt", "menu:prompt"), BACK_MAIN])
    return build(rows)


def ai_test_menu(cases: Sequence[str]) -> InlineKeyboardMarkup:
    rows = [[(f"[{index}] {case}", f"ptest:{index}")] for index, case in enumerate(cases, 1)]
    rows.append([("✍️ សួរដោយខ្លួនឯង", "ptest:custom")])
    rows.append([("⬅️ ត្រឡប់ Prompt", "menu:prompt"), BACK_MAIN])
    return build(rows)


def orders_menu(counts: dict[str, int], orders: Sequence[Order], page: int, pages: int, status: str) -> InlineKeyboardMarkup:
    rows = [
        [
            (f"⏳ {counts.get(OrderStatus.PENDING_PAYMENT, 0)}", "ord:list:" + OrderStatus.PENDING_PAYMENT),
            (f"🔎 {counts.get(OrderStatus.AWAITING_VERIFY, 0)}", "ord:list:" + OrderStatus.AWAITING_VERIFY),
            (f"✅ {counts.get(OrderStatus.DELIVERED, 0)}", "ord:list:" + OrderStatus.DELIVERED),
            (f"❌ {counts.get(OrderStatus.CANCELLED, 0)}", "ord:list:" + OrderStatus.CANCELLED),
        ],
        [("📚 ទាំងអស់", "ord:list:all"), ("➕ បង្កើត Order ដោយដៃ", "ord:add")],
    ]
    rows += [
        [(f"🧾 #{item.id} {esc(item.product_name or '')} · {money(item.price)} · {OrderStatus.LABELS.get(item.status, item.status)}", f"ord:view:{item.id}")]
        for item in orders
    ]
    if pages > 1:
        rows.append(pager("ord:list", page, pages))
    rows.append([BACK_MAIN])
    return build(rows)


def order_actions(order: Order) -> InlineKeyboardMarkup:
    rows: list[list[tuple[str, str]]] = []
    if order.status in (OrderStatus.PENDING_PAYMENT, OrderStatus.AWAITING_VERIFY):
        rows.append([("✅ ផ្ទៀងផ្ទាត់ + បញ្ចេញ Code", f"ord:confirm:{order.id}"), ("❌ បោះបង់ Order", f"ord:askcancel:{order.id}")])
    if order.slip_file_id:
        rows.append([("🖼 មើល Slip", f"ord:slip:{order.id}")])
    rows.append([("📝 កំណត់ត្រា", f"ord:note:{order.id}")])
    rows.append([("⬅️ បញ្ជី Order", "menu:orders"), BACK_MAIN])
    return build(rows)


def customers_menu(customers: Sequence[Customer], page: int, pages: int) -> InlineKeyboardMarkup:
    rows = [
        [
            (
                f"{'⏸' if item.ai_paused else ('🚫' if item.is_blocked else '🟢')} {esc(item.name or item.telegram_id)} · {money(item.total_spent)}",
                f"cus:view:{item.id}",
            )
        ]
        for item in customers
    ]
    rows.append([("🔍 ស្វែងរក", "cus:search"), ("🏷 តាម Tag", "cus:tags")])
    if pages > 1:
        rows.append(pager("cus:list", page, pages))
    rows.append([BACK_MAIN])
    return build(rows)


def tags_menu() -> InlineKeyboardMarkup:
    presets = ["VIP", "ថ្មី", "ស្មោះត្រង់", "Spam"]
    rows = [[("🏷 " + tag, "cus:filter:" + tag) for tag in presets]]
    rows.append([("⏭ គ្មាន Filter", "cus:filter:"), ("⬅️ បញ្ជីអតិថិជន", "menu:customers"), BACK_MAIN])
    return build(rows)


def customer_actions(customer: Customer) -> InlineKeyboardMarkup:
    rows = [
        [
            ("⏸ Pause AI" if not customer.ai_paused else "▶️ Resume AI", f"cus:pause:{customer.id}" if not customer.ai_paused else f"cus:resume:{customer.id}"),
            ("🚫 Block" if not customer.is_blocked else "✅ Unblock", f"cus:block:{customer.id}" if not customer.is_blocked else f"cus:unblock:{customer.id}"),
        ],
        [("🏷 កែ Tags", f"cus:tagsel:{customer.id}"), ("📝 កំណត់ត្រា", f"cus:note:{customer.id}")],
        [("🧾 មើល Orders", f"cus:orders:{customer.id}"), ("🧠 សម្អាត Context AI", f"cus:askclear:{customer.id}")],
        [("⬅️ បញ្ជីអតិថិជន", "menu:customers"), BACK_MAIN],
    ]
    return build(rows)


def accounts_menu(accounts: Sequence[Account], scope: "Scope | None" = None) -> InlineKeyboardMarkup:
    """បញ្ជីគណនីជា «កាតលេខ» មួយជួរឈរមួយគណនី — គ្មានកំណត់ចំនួន រហូតដល់ ៩៩៦ button/callback។

    លេខទូរស័ព្ទត្រូវបិទកណ្តាល (ប្រើ `display_label()`) ទោះក្នុង button តូចៗ។
    """
    icons = {"active": "🟢", "offline": "⚪", "paused": "🟡", "banned": "🔴"}
    shown = accounts[:BUTTON_ROWS]
    rows = [
        [
            (
                f"{index}. {icons.get(item.status, '⚪')} #{item.id} {esc(item.display_label())}"
                + (" ⭐" if item.is_primary else "")
                + ("" if item.enabled else " 🔒"),
                f"acc:view:{item.id}",
            )
        ]
        for index, item in enumerate(shown, 1)
    ]
    if len(accounts) > len(shown):
        rows.append([(f"… មានទៀត {len(accounts) - len(shown)} គណនី · មើលបញ្ជីខាងលើ", "noop:more")])
    rows.append([("➕ បន័ែមគណនី (Session String)", "acc:addsession")])
    web = web_app_row()
    if web:  # តំណទៅ Web App ជិតប៊ូតុងបន័ែមគណនី ព្រោះគឺជាកន្លែងបង្កើត Session String
        rows.append(web)
    rows.append([("ℹ️ របៀបបន័ែមគណនី", "acc:howto")])
    rows.append([BACK_MAIN])
    return build(rows)


def account_actions(account: Account, scope: "Scope | None" = None) -> InlineKeyboardMarkup:
    is_owner = bool(scope is not None and scope.is_owner)
    rows = [
        [
            ("🤖 AI on/off", f"acc:ai:{account.id}"),
            ("🟢 បើក Userbot" if not account.enabled else "🔒 បិទ Userbot", f"acc:enable:{account.id}"),
            ("🗑 លុបគណនី", f"acc:askdel:{account.id}"),
        ]
    ]
    if is_owner:
        if not account.is_primary:
            rows.insert(0, [("⭐ ធ្វើជា Primary", f"acc:primary:{account.id}")])
        rows.append([("🔀 ប្ដូរម្ចាស់គណនី", f"acc:askowner:{account.id}")])
    rows.append([("⬅️ បញ្ជីគណនី", "menu:accounts"), BACK_MAIN])
    return build(rows)


def analytics_menu() -> InlineKeyboardMarkup:
    return build(
        [
            [("ថ្ងៃនេះ", "ana:today"), ("សប្តាហ៍", "ana:week"), ("ខែ", "ana:month"), ("ឆ្នាំ", "ana:year")],
            [("📤 ផ្ញើរបាយការណ៍ប្រចាំថ្ងៃឥឡូវ", "ana:send")],
            [BACK_MAIN],
        ]
    )


def settings_menu(is_owner: bool) -> InlineKeyboardMarkup:
    rows = [
        [("🕒 Working hours", "set:hours"), ("💬 សារក្រៅម៉ោង", "set:offreply")],
        [("🤖 Toggle AI ទាំងអស់", "set:ai"), ("📱 Toggle Userbot", "set:userbot")],
        [("📉 Stock alert threshold", "set:threshold"), ("🌐 ភាសា", "set:lang")],
    ]
    if is_owner:
        rows.append([("💾 Backup ឥឡូវ", "set:backup"), ("📥 Restore ពីឯកសារ", "set:restore")])
    rows.append([BACK_MAIN])
    return build(rows)
