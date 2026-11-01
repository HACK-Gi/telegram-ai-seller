"""CRUD — គ្រប់ការងារទិន្នន័យ async ទាំងអស់។

គ្រប់ function ទទួល `session: AsyncSession` ពី `db_session()` របស់ caller
ដូច្នេះការងារមួយអាចជាប់គ្នាក្នុង transaction តែមួយ (ឧ. deliver order + កាត់ stock)។
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from sqlalchemy import case, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database.models import (
    Account,
    AccountProduct,
    AccountStatus,
    Admin,
    Category,
    Customer,
    Message,
    Order,
    OrderStatus,
    Product,
    QRCode,
    Setting,
    StockCode,
    StockCodeStatus,
)
from helpers import utcnow

# តួនាទីដែលរាប់ជា «សារដែលបានផ្ញើចេញ» សម្រាប់កម្រិត 50/h · 200/ថ្ងៃ។
# រួមទាំង `owner` ដោយចេតនា៖ សារដែលម្ចាស់វាយដោយខ្លួនឯងក៏ចេញពីគណនីតែមួយដែរ។
SEND_ROLES = ("assistant", "owner")


# ============================================================
# RBAC helpers — None = គ្មានវិសាលភាព (owner ឃើញទាំងអស់), () = គ្មានសិទ្ធិអ្វីសោះ
# ============================================================


def no_access(account_ids: tuple[int, ...] | list[int] | None) -> bool:
    return account_ids is not None and len(account_ids) == 0


def _owner_where(model, owner_admin_id: int | None):
    if owner_admin_id is None:
        return None
    return model.owner_admin_id == owner_admin_id


async def owned_account_ids(session: AsyncSession, owner_admin_id: int) -> tuple[int, ...]:
    """ID គណនីរបស់ admin ម្នាក់ — StaffGate ហៅម្តងគត់ក្នុងមួយ update។"""
    rows = (
        await session.scalars(select(Account.id).where(Account.owner_admin_id == owner_admin_id).order_by(Account.id))
    ).all()
    return tuple(int(row) for row in rows)


async def count_accounts_by_owner(session: AsyncSession, owner_admin_id: int) -> int:
    return int(
        (await session.scalar(select(func.count(Account.id)).where(Account.owner_admin_id == owner_admin_id))) or 0
    )


# ============================================================
# Settings
# ============================================================

LEGACY_DEFAULT_SYSTEM_PROMPT = """អ្នកគឺជាអ្នកលក់ដ៏ជំនាញ និងមានបទពិសោធន៍ខ្ពស់នៅលើ Telegram។ អ្នកកំពុងលក់ផលិតផលឌីជីថល។

ចរិតរបស់អ្នក៖
- រួសរាយរាក់ទាក់ និងគួរសម
- និយាយខ្លីៗ ច្បាស់លាស់
- ប្រើភាសាខ្មែរធម្មជាតិ លាយពាក្យអង់គ្លេសតែពេលចាំបាច់
- ប្រើ Emoji សមស្រប មិនច្រើនពេក
- កុំសរសេរជាផ្លូវការពេក

ភារកិច្ចរបស់អ្នក៖
1. ស្វាគមន៍អតិថិជនយ៉ាងកក់ក្តៅ
2. ឆ្លើយសំណួរអំពីផលិតផលដោយផ្អែកលើ Catalog
3. ប្រសិនបើអតិថិជនចង់ទិញ → ប្រាប់ឱ្យទូទាត់តាម QR និងផ្ញើ Slip
4. ប្រសិនបើមិនដឹង → "ខ្ញុំនឹងឱ្យអ្នកគ្រប់គ្រងទាក់ទងទៅអ្នកវិញ"
5. កុំប្រឌិតព័ត៌មានដែលមិនមាន
6. កុំផ្ញើកូដ/ឯកសារដោយខ្លួនឯង — ម្ចាស់ជាអ្នកផ្ញើ

ច្បាប់សំខាន់៖
1. កុំចម្លងសារអតិថិជនមកវិញ
2. កុំឆ្លើយស្រាប់ៗ — ត្រូវយល់សំណួរសិន
3. ប្រសិនបើមិនយល់ → សួរត្រឡប់ដោយសុភាព
4. កុំផ្ញើ Code ដោយខ្លួនឯង — ត្រូវរង់ចាំម្ចាស់
5. ផ្ញើតែអត្ថបទចម្លើយប៉ុណ្ណោះ — កុំសរសេរស្លាកដូចជា [ASSISTANT] ឬ "អ្នក:" នាំមុខ
6. សរសេរតែអក្សរខ្មែរ (លាយអង់គ្លេសបាន) — ហាមបន្សាំអក្សរថៃ ឬចិន"""

DEFAULT_SYSTEM_PROMPT = """អ្នកគឺជាអ្នកលក់ដ៏ជំនាញ និងមានបទពិសោធន៍ខ្ពស់នៅលើ Telegram។ អ្នកកំពុងលក់ផលិតផលឌីជីថល។

ចរិតរបស់អ្នក៖
- រួសរាយរាក់ទាក់ និងគួរសម
- និយាយខ្លីៗ ច្បាស់លាស់
- ប្រើភាសាខ្មែរធម្មជាតិ លាយពាក្យអង់គ្លេសតែពេលចាំបាច់
- ប្រើ Emoji សមស្រប មិនច្រើនពេក
- កុំសរសេរជាផ្លូវការពេក

ភារកិច្ចរបស់អ្នក៖
1. ស្វាគមន៍អតិថិជនយ៉ាងកក់ក្តៅ
2. ឆ្លើយសំណួរអំពីផលិតផលដោយផ្អែកលើ Catalog
3. ប្រសិនបើអតិថិជនចង់ទិញ → ប្រាប់ឱ្យទូទាត់តាម QR និងផ្ញើ Slip
4. ប្រសិនបើមិនដឹង → "ខ្ញុំនឹងឱ្យអ្នកគ្រប់គ្រងទាក់ទងទៅអ្នកវិញ"
5. កុំប្រឌិតព័ត៌មានដែលមិនមាន
6. កុំផ្ញើកូដ/ឯកសារដោយខ្លួនឯង — ម្ចាស់ជាអ្នកផ្ញើ
7. បើអតិថិជនចង់រើសមើល → ណែនាំឱ្យវាយ «menu» ដើម្បីជ្រើសប្រភេទអីវ៉ាន់តាមប៊ូតុង
8. ការទិញធ្វើតាមជំហាន៖ ចុច «🛒 ទិញឥឡូវ» → បង់ប្រាក់តាម QR → ផ្ញើរូបភាព slip → រង់ចាំ Code ពីម្ចាស់

ច្បាប់សំខាន់៖
1. កុំចម្លងសារអតិថិជនមកវិញ
2. កុំឆ្លើយស្រាប់ៗ — ត្រូវយល់សំណួរសិន
3. ប្រសិនបើមិនយល់ → សួរត្រឡប់ដោយសុភាព
4. កុំផ្ញើ Code ដោយខ្លួនឯង — ត្រូវរង់ចាំម្ចាស់
5. ផ្ញើតែអត្ថបទចម្លើយប៉ុណ្ណោះ — កុំសរសេរស្លាកដូចជា [ASSISTANT] ឬ "អ្នក:" នាំមុខ
6. សរសេរតែអក្សរខ្មែរ (លាយអង់គ្លេសបាន) — ហាមបន្សាំអក្សរថៃ ឬចិន
7. មិនអាចស្តាប់ Voice ឬ Video note ទេ — សុំអតិថិជនវាយជាអក្សរ ឬផ្ញើរូបភាព
8. រាល់ផលិតផលមានលេខកូដ (ឧ. GAME-001) — គ្រាន់តែយកឈ្មោះ/តម្លៃទេ កុំបង្ហាញកូដ Stock"""

LEGACY_DEFAULT_FEW_SHOT = """អតិថិជន: សួស្តីបង
អ្នក: សួស្តីបង! 🙏 ខ្ញុំនៅទីនេះដើម្បីជួយ។ បងចង់រកអីវ៉ាន់អ្វី?

អតិថិជន: តម្លៃប៉ុន្មាន?
អ្នក: អីវ៉ាន់នេះតម្លៃ $5.00 បង។ បងចង់បានប៉ុន្មាន?

អតិថិជន: code 100 prime?
អ្នក: ខ្ញុំមិនទាន់យល់ច្បាស់ទេបង 😊 តើបងចង់សួរអំពី Prime Code 100 មែនទេ? ខ្ញុំអាចជួយពន្យល់បាន។

អតិថិជន: បងមានអីវ៉ាន់អ្វីខ្លះ?
អ្នក: ខ្ញុំមានអីវ៉ាន់ច្រើនបង៖
• Prime Code 100 — $5.00
• Prime Code 200 — $10.00
• Free Fire UC — $3.00
បងចង់បានអ្វី?

អតិថិជន: qr បង
អ្នក: បាទបង! នេះជា QR សម្រាប់ទូទាត់។ បន្ទាប់ពីទូទាត់រួច សូមផ្ញើ Slip មកខ្ញុំវិញ។

អតិថិជន: ខ្ញុំបាញ់លុយរួចហើយ
អ្នក: អរគុណបង! ខ្ញុំបានបញ្ជូនទៅក្រុមការងារហើយ។ សូមរង់ចាំបន្តិច ខណៈពេលយើងផ្ទៀងផ្ទាត់។"""

DEFAULT_FEW_SHOT = LEGACY_DEFAULT_FEW_SHOT + """

អតិថិជន: code 1000 មានទេបង?
អ្នក: អាស្រ័យលើហ្គេម និង server បង — វាយ «menu» ដើម្បីជ្រើសប្រភេទ ឬប្រាប់ឈ្មោះផលិតផលមកខ្ញុំ ខ្ញុំមើល stock ឱ្យភ្លាម។

អតិថិជន: បងមានអីវ៉ាន់អ្វីខ្លះ? ខ្ញុំមិនដឹងជ្រើស
អ្នក: ងាយបង! វាយ «menu» ម្តង ខ្ញុំនឹងបង្ហាញប្រភេទអីវ៉ាន់ទាំងអស់ជាប៊ូតុង ចុចមើលបានតែម្តង 🙏

អតិថិជន: ខ្ញុំបានផ្ញើ voice មួយ បងស្តាប់ឱ្យផង
អ្នក: សូមអភ័យទោសបង ខ្ញុំស្តាប់ voice មិនបានទេ 🙏 សូមវាយជាអក្សរ ឬផ្ញើរូបភាព (slip ក៏បាន) ជំនួស។

អតិថិជន: ផ្ញើ code មកលេងមុនបានទេ?
អ្នក: មិនបានទេបង — Code ចេញលុះត្រាតែម្ចាស់បានផ្ទៀងផ្ទាត់ slip រួច។ បងចុច «🛒 ទិញឥឡូវ» → បង់ QR → ផ្ញើរូប slip → រង់ចាំ Code តែម្តង 🙏"""

DEFAULTS: dict[str, str] = {
    "system_prompt": DEFAULT_SYSTEM_PROMPT,
    "few_shot": DEFAULT_FEW_SHOT,
    "working_hours": settings.working_hours,
    "off_hours_reply": "ខ្ញុំកំពុងសម្រាកបន្តិច បងអាចទុកសារចោលបាន ខ្ញុំនឹងឆ្លើយតបវិញឱ្យបានឆាប់ 🙏",
    "ai_enabled": "on",
    "userbot_enabled": "on",
    "language": settings.language,
    "stock_alert_threshold": str(settings.stock_alert_threshold),
    "low_stock_alerted": "{}",
    "userbot_notices": "{}",
}

# ប្រភេទអីវ៉ាន់លំនាំដើម — «gen» គឺ fallback សម្រាប់ផលិតផលចាស់/មិនស្គាល់
DEFAULT_CATEGORIES: list[dict] = [
    {"code": "game_acc", "prefix": "GAME", "name_kh": "គណនីហ្គេម", "name_en": "Game Accounts",
     "icon": "🎮", "description": "Free Fire, PUBG, MLBB"},
    {"code": "ai_pro", "prefix": "AIPRO", "name_kh": "គណនី AI Pro", "name_en": "AI Pro Accounts",
     "icon": "🤖", "description": "ChatGPT Plus, Gemini Pro, Claude Pro"},
    {"code": "cloth", "prefix": "CLOTH", "name_kh": "ខោអាវ", "name_en": "Clothing",
     "icon": "👕", "description": "ខោអាវ, អាវ, ស្បែកជើង"},
    {"code": "computer", "prefix": "PC", "name_kh": "កុំព្យូទ័រ", "name_en": "Computers",
     "icon": "💻", "description": "Laptop, PC, Phone, Accessories"},
    {"code": "gift", "prefix": "GIFT", "name_kh": "Gift Cards", "name_en": "Gift Cards",
     "icon": "🎁", "description": "Google Play, iTunes, Steam"},
    {"code": "software", "prefix": "SOFT", "name_kh": "Software", "name_en": "Software",
     "icon": "📱", "description": "Windows, Office, Antivirus"},
    {"code": "service", "prefix": "SVC", "name_kh": "សេវាកម្ម", "name_en": "Services",
     "icon": "🔧", "description": "Design, Coding, Setup"},
    {"code": "gen", "prefix": "GEN", "name_kh": "ទូទៅ", "name_en": "General",
     "icon": "📦", "description": "ផលិតផលមិនបញ្ចូលប្រភេទ"},
]


async def get_setting(session: AsyncSession, key: str, default: str = "") -> str:
    row = await session.get(Setting, key)
    if row is not None:
        return row.value
    return DEFAULTS.get(key, default)


async def set_setting(session: AsyncSession, key: str, value: str) -> None:
    row = await session.get(Setting, key)
    if row is None:
        session.add(Setting(key=key, value=value))
    else:
        row.value = value


async def get_json_setting(session: AsyncSession, key: str, default: dict) -> dict:
    raw = await get_setting(session, key, "")
    try:
        loaded = json.loads(raw) if raw else default
    except json.JSONDecodeError:
        return default
    return loaded if isinstance(loaded, dict) else default


async def set_json_setting(session: AsyncSession, key: str, value: dict) -> None:
    await set_setting(session, key, json.dumps(value, ensure_ascii=False))


async def notice_once(session: AsyncSession, key: str, *, bucket: str) -> bool:
    """ពិត = នេះជាលើកទីមួយរបស់ `key` ក្នុង `bucket` (ម៉ោង ឬថ្ងៃ) — dedupe ជូនដំណឹង panel។

    រក្សាទុកក្នុង setting `userbot_notices` ដូច្នេះវារស់កាត់ restart។ កាត់ 200 entry ចាស់បំផុត
    ដើម្បីកុំឱ្យ JSON ធំគ្មានដែនកំណត់។ pop មុនសរសេរ ដើម្បីឱ្យ entry ថ្មីជាប់នៅចុងក្រោយ។"""
    notices = await get_json_setting(session, "userbot_notices", {})
    if notices.get(key) == bucket:
        return False
    notices.pop(key, None)
    notices[key] = bucket
    if len(notices) > 200:
        notices = dict(list(notices.items())[-200:])
    await set_json_setting(session, "userbot_notices", notices)
    return True


async def seed_defaults(session: AsyncSession) -> None:
    """បង្កើតស្ថាយទាំងអស់ដែលខ្វះ ដោយប្រើតម្លៃលំនាំដើម (មិនលើកលែងតម្លៃដែលមានស្រាប់)។"""
    for key, value in DEFAULTS.items():
        if await session.get(Setting, key) is None:
            session.add(Setting(key=key, value=value))


async def all_settings(session: AsyncSession) -> dict[str, str]:
    rows = (await session.scalars(select(Setting))).all()
    known = {row.key: row.value for row in rows}
    for key, value in DEFAULTS.items():
        known.setdefault(key, value)
    return known


# ============================================================
# Categories (ប្រភេទអីវ៉ាន់)
# ============================================================

async def list_all_categories(session: AsyncSession, active_only: bool = False) -> list[Category]:
    stmt = select(Category)
    if active_only:
        stmt = stmt.where(Category.is_active.is_(True))
    stmt = stmt.order_by(Category.display_order, Category.id)
    return list((await session.scalars(stmt)).all())


async def get_category(session: AsyncSession, category_id: int) -> Category | None:
    return await session.get(Category, category_id)


async def get_category_by_code(session: AsyncSession, code: str) -> Category | None:
    return await session.scalar(select(Category).where(Category.code == code.strip().lower()))


async def get_category_by_name(session: AsyncSession, name: str) -> Category | None:
    key = (name or "").strip().lower()
    if not key:
        return None
    for column in (Category.name_kh, Category.name_en, Category.code):
        category = await session.scalar(select(Category).where(func.lower(column) == key).limit(1))
        if category is not None:
            return category
    for category in await list_all_categories(session):  # ទន់: «game» → game_acc
        if category.code.startswith(key + "_") or category.code == key:
            return category
    for category in await list_all_categories(session):  # កូនស្នាម: «ហ្គេម» ⊂ «គណនីហ្គេម»
        if key in f"{category.name_kh or ''}".lower() or key in f"{category.name_en or ''}".lower():
            return category
    return None


async def create_category(session: AsyncSession, **fields) -> tuple[Category | None, str]:
    """ត្រឡប់ (category, "") ឬ (None, មូលហេតុបរាជ័យ)។"""
    code = str(fields.get("code", "")).strip().lower()
    fields["code"] = code
    if not code or not str(fields.get("name_kh", "")).strip():
        return None, "ត្រូវការ code និង name_kh"
    if await get_category_by_code(session, code) is not None:
        return None, f"code '{code}' មានស្រាប់ហើយ"
    order = int(fields.pop("display_order", 0) or 0)
    if order == 0:
        top = await session.scalar(select(func.max(Category.display_order)))
        order = int(top or 0) + 10
    category = Category(display_order=order, **fields)
    session.add(category)
    await session.flush()
    return category, ""


async def update_category(session: AsyncSession, category_id: int, **values) -> None:
    if "code" in values:
        values["code"] = str(values["code"]).strip().lower()
        dup = await get_category_by_code(session, values["code"])
        if dup is not None and dup.id != category_id:
            return
    await session.execute(update(Category).where(Category.id == category_id).values(**values))
    await session.flush()


async def delete_category(session: AsyncSession, category_id: int) -> str:
    """'deleted' | 'blocked' (មានផលិតផលកាន់កាប់) | 'missing' — ផលិតផលចាស់ត្រូវផ្លាស់ទៅ gen មុនសម្រេច។"""
    category = await session.get(Category, category_id)
    if category is None:
        return "missing"
    used = int(
        await session.scalar(
            select(func.count(Product.id)).where(Product.category_id == category_id)
        )
        or 0
    )
    if used:
        return "blocked"
    await session.delete(category)
    await session.flush()
    return "deleted"


async def category_product_counts(
    session: AsyncSession, *, owner_admin_id: int | None = None
) -> dict[int, int]:
    """រាប់ផលិតផលក្នុងប្រភេទនីមួយៗ — `owner_admin_id` = រាប់តែផលិតផលរបស់ admin នោះ។"""
    stmt = select(Product.category_id, func.count(Product.id)).where(Product.category_id.is_not(None))
    if owner_admin_id is not None:
        stmt = stmt.where(Product.owner_admin_id == owner_admin_id)
    rows = await session.execute(stmt.group_by(Product.category_id))
    return {int(cid): int(count) for cid, count in rows.all() if cid is not None}


async def next_product_code(session: AsyncSession, category: Category) -> str:
    """GAME-001 ទម្រង់ — prefix ពី category.prefix, លេខបន្តតាម prefix ដែលមានស្រាប់។"""
    prefix = category.product_prefix
    rows = (await session.scalars(select(Product.product_code).where(Product.product_code.like(f"{prefix}-%")))).all()
    highest = 0
    for code in rows:
        tail = str(code or "").rsplit("-", 1)[-1]
        if tail.isdigit():
            highest = max(highest, int(tail))
    return f"{prefix}-{highest + 1:03d}"


async def _ensure_product_code(session: AsyncSession, product: Product) -> None:
    """បើផលិតផលគ្មាន category_id → ផ្សំតាមឈ្មោះ string ឬ gen fallback រួចបង្កើត product_code។"""
    if product.category_id is None:
        category = await get_category_by_name(session, product.category)
        if category is None:
            category = await get_category_by_code(session, "gen")
        if category is not None:
            product.category_id = category.id
    if product.category_id is not None:
        category = await session.get(Category, product.category_id)
        if category is not None:
            if product.category != category.name_kh:
                product.category = category.name_kh  # mirror ឈ្មោះ កុំឱ្យ path ចាស់ដែល filter តាម string បាត់
            if product.product_code is None:
                product.product_code = await next_product_code(session, category)


# ============================================================
# Products + Stock
# ============================================================

async def list_products(
    session: AsyncSession,
    search: str = "",
    category: str = "",
    page: int = 1,
    per_page: int = 8,
    active_only: bool = False,
    category_id: int | None = None,
    *,
    owner_admin_id: int | None = None,
) -> tuple[list[Product], int]:
    stmt = select(Product)
    count_stmt = select(func.count(Product.id))
    clause = _owner_where(Product, owner_admin_id)
    if clause is not None:
        stmt = stmt.where(clause)
        count_stmt = count_stmt.where(clause)
    if search:
        clause = (
            Product.name.ilike(f"%{search}%")
            | Product.description.ilike(f"%{search}%")
            | Product.product_code.ilike(f"%{search}%")
        )
        stmt = stmt.where(clause)
        count_stmt = count_stmt.where(clause)
    if category:
        stmt = stmt.where(Product.category == category)
        count_stmt = count_stmt.where(Product.category == category)
    if category_id is not None:
        stmt = stmt.where(Product.category_id == category_id)
        count_stmt = count_stmt.where(Product.category_id == category_id)
    if active_only:
        stmt = stmt.where(Product.is_active.is_(True))
    total = int((await session.scalar(count_stmt)) or 0)
    stmt = stmt.order_by(Product.id.desc()).offset((page - 1) * per_page).limit(per_page)
    rows = list((await session.scalars(stmt)).all())
    return rows, total


async def get_product(session: AsyncSession, product_id: int, *, owner_admin_id: int | None = None) -> Product | None:
    product = await session.get(Product, product_id)
    if product is None or (owner_admin_id is not None and product.owner_admin_id != owner_admin_id):
        return None
    return product


async def get_product_by_code(
    session: AsyncSession, product_code: str, *, owner_admin_id: int | None = None
) -> Product | None:
    stmt = select(Product).where(Product.product_code == product_code.strip().upper()).limit(1)
    clause = _owner_where(Product, owner_admin_id)
    if clause is not None:
        stmt = stmt.where(clause)
    return await session.scalar(stmt)


async def create_product(session: AsyncSession, **fields) -> Product:
    product = Product(**fields)
    session.add(product)
    await session.flush()
    await _ensure_product_code(session, product)
    await session.flush()
    # refresh ដើម្បីឱ្យ stock collection រឿន (selectin) — មិននាំឱ្យ lazy-load ក្នុង async
    await session.refresh(product)
    return product


async def delete_product(session: AsyncSession, product_id: int) -> None:
    await session.execute(delete(StockCode).where(StockCode.product_id == product_id))
    await session.execute(delete(Product).where(Product.id == product_id))


async def add_stock(session: AsyncSession, product_id: int, codes: list[str]) -> int:
    existing = set(
        (await session.scalars(select(StockCode.code).where(StockCode.product_id == product_id))).all()
    )
    added = 0
    for code in codes:
        code = code.strip()
        if code and code not in existing:
            existing.add(code)
            session.add(StockCode(product_id=product_id, code=code))
            added += 1
    await session.flush()
    return added


async def add_stock_lines(session: AsyncSession, product_id: int, lines: list[str]) -> list[StockCode]:
    """បន្ថែម Stock ពីបន្ទាត់ខ្លឹមសារ (ឧ. `user1@mail.com|pass123`) — code ស្វ័យប្រវត្តិ GAME-001-S001...។
    បន្ទាត់ទទេ/ស្ទួនត្រូវរំលង។"""
    product = await session.get(Product, product_id)
    if product is None:
        return []
    await _ensure_product_code(session, product)
    base = product.product_code or f"P{product.id}"
    used = set(
        (await session.scalars(select(StockCode.code).where(StockCode.product_id == product_id))).all()
    )
    contents = {
        str(row or "").strip()
        for row in (await session.scalars(select(StockCode.content).where(StockCode.product_id == product_id))).all()
    }
    seq = 0
    created: list[StockCode] = []
    for line in lines:
        content = line.strip()
        if not content or content in contents:
            continue
        contents.add(content)
        while True:
            seq += 1
            code = f"{base}-S{seq:03d}"
            if code not in used:
                break
        used.add(code)
        item = StockCode(
            product_id=product_id,
            code=code,
            content=content,
            status=StockCodeStatus.AVAILABLE,
        )
        session.add(item)
        created.append(item)
    await session.flush()
    await session.refresh(product)  # stock រឿនសម្រាប់ property ដែល caller នឹងអាន
    return created


async def available_stock(session: AsyncSession, product_id: int) -> int:
    value = await session.scalar(
        select(func.count(StockCode.id)).where(
            StockCode.product_id == product_id, StockCode.status == StockCodeStatus.AVAILABLE
        )
    )
    return int(value or 0)


async def reserve_stock(
    session: AsyncSession, product_id: int, quantity: int, customer_id: int, order_id: int | None = None
) -> list[StockCode]:
    """កក់ Code តាមលំដាប់ — បើមិនគ្រប់ quantity → ត្រឡប់ [] ដាច់ខាត (មិនកក់ពាក់កណ្តាល)។"""
    rows = list(
        (
            await session.scalars(
                select(StockCode)
                .where(StockCode.product_id == product_id, StockCode.status == StockCodeStatus.AVAILABLE)
                .order_by(StockCode.id)
                .limit(quantity)
            )
        ).all()
    )
    if len(rows) < quantity:
        return []
    now = utcnow()
    for item in rows:
        item.status = StockCodeStatus.RESERVED
        item.reserved_for_customer_id = customer_id
        item.reserved_at = now
        if order_id is not None:
            item.order_id = order_id
    await session.flush()
    return rows


async def release_reserved(session: AsyncSession, *, order_id: int | None = None, product_id: int | None = None) -> int:
    stmt = update(StockCode).where(StockCode.status == StockCodeStatus.RESERVED)
    if order_id is not None:
        stmt = stmt.where(StockCode.order_id == order_id)
    if product_id is not None:
        stmt = stmt.where(StockCode.product_id == product_id)
    result = await session.execute(
        stmt.values(
            status=StockCodeStatus.AVAILABLE,
            reserved_for_customer_id=None,
            reserved_at=None,
            order_id=None,
        )
    )
    return int(result.rowcount or 0)


async def stock_remaining(session: AsyncSession, product_id: int) -> int:
    value = await session.scalar(
        select(func.count(StockCode.id)).where(StockCode.product_id == product_id, StockCode.is_sold.is_(False))
    )
    return int(value or 0)


async def list_stock(
    session: AsyncSession, product_id: int, only_available: bool = False, limit: int = 20
) -> list[StockCode]:
    stmt = select(StockCode).where(StockCode.product_id == product_id)
    if only_available:
        stmt = stmt.where(StockCode.is_sold.is_(False))
    stmt = stmt.order_by(StockCode.id).limit(limit)
    return list((await session.scalars(stmt)).all())


async def clear_unsold_stock(session: AsyncSession, product_id: int) -> int:
    """លុប Code ដែលមិនទាន់លក់ទាំងអស់ ត្រឡប់ចំនួនដែលបានលុប។"""
    result = await session.execute(
        delete(StockCode).where(StockCode.product_id == product_id, StockCode.is_sold.is_(False))
    )
    return int(result.rowcount or 0)


async def sold_stock_count(session: AsyncSession, product_id: int) -> int:
    value = await session.scalar(
        select(func.count(StockCode.id)).where(StockCode.product_id == product_id, StockCode.is_sold.is_(True))
    )
    return int(value or 0)


async def list_categories(session: AsyncSession) -> list[str]:
    rows = await session.scalars(select(Product.category).distinct().order_by(Product.category))
    return [row for row in rows if row]


async def low_stock_products(
    session: AsyncSession, threshold: int, *, owner_admin_id: int | None = None
) -> list[tuple[Product, int]]:
    """ផលិតផលដែលសល់តិចជាង threshold (រាប់ទាំងដែលអស់ស្រុង 0)។"""
    counts = dict(
        (
            await session.execute(
                select(StockCode.product_id, func.count(StockCode.id))
                .where(StockCode.is_sold.is_(False))
                .group_by(StockCode.product_id)
            )
        ).all()
    )
    stmt = select(Product).where(Product.is_active.is_(True))
    clause = _owner_where(Product, owner_admin_id)
    if clause is not None:
        stmt = stmt.where(clause)
    products = list((await session.scalars(stmt)).all())
    result: list[tuple[Product, int]] = []
    for product in products:
        remaining = int(counts.get(product.id, 0))
        if remaining < threshold:
            result.append((product, remaining))
    return result


# ============================================================
# QR Codes
# ============================================================

async def list_qrcodes(session: AsyncSession, *, owner_admin_id: int | None = None) -> list[QRCode]:
    stmt = select(QRCode).order_by(QRCode.is_default.desc(), QRCode.id)
    clause = _owner_where(QRCode, owner_admin_id)
    if clause is not None:
        stmt = stmt.where(clause)
    return list((await session.scalars(stmt)).all())


async def get_qrcode(session: AsyncSession, qr_id: int, *, owner_admin_id: int | None = None) -> QRCode | None:
    qr = await session.get(QRCode, qr_id)
    if qr is None or (owner_admin_id is not None and qr.owner_admin_id != owner_admin_id):
        return None
    return qr


async def create_qrcode(session: AsyncSession, **fields) -> QRCode:
    qr = QRCode(**fields)
    session.add(qr)
    await session.flush()
    if qr.is_default:
        await clear_default_qrcodes(session, keep_id=qr.id, owner_admin_id=qr.owner_admin_id)
    return qr


async def clear_default_qrcodes(
    session: AsyncSession, keep_id: int | None = None, *, owner_admin_id: int | None = None
) -> None:
    """default មួយក្នុងមួយម្ចាស់ — ការលុបរបស់ staff មិនប៉ះ default របស់ owner ឡើយ។"""
    stmt = update(QRCode).where(QRCode.is_default.is_(True)).values(is_default=False)
    clause = _owner_where(QRCode, owner_admin_id)
    if clause is not None:
        stmt = stmt.where(clause)
    if keep_id is not None:
        stmt = stmt.where(QRCode.id != keep_id)
    await session.execute(stmt)


async def set_default_qrcode(session: AsyncSession, qr_id: int, *, owner_admin_id: int | None = None) -> None:
    qr = await get_qrcode(session, qr_id, owner_admin_id=owner_admin_id)
    if qr is None:
        return
    await clear_default_qrcodes(session, keep_id=qr_id, owner_admin_id=qr.owner_admin_id)
    qr.is_default = True


async def delete_qrcode(session: AsyncSession, qr_id: int, *, owner_admin_id: int | None = None) -> None:
    """លុប QR ក្នុងវិសាលភាពតែប៉ុណ្ណោះ — ID របស់អ្នកដទៃ នៅសល់ដដែល។"""
    stmt = delete(QRCode).where(QRCode.id == qr_id)
    clause = _owner_where(QRCode, owner_admin_id)
    if clause is not None:
        stmt = stmt.where(clause)
    await session.execute(stmt)


async def best_qrcode(
    session: AsyncSession, product_id: int | None = None, *, owner_admin_id: int | None = None
) -> QRCode | None:
    """QR ដែលត្រូវប្រើ៖ ភ្ជាប់នឹងផលិតផល → default → ថ្មីបំផុត **ក្នុងវិសាលភាពម្ចាស់តែប៉ុណ្ណោះ**។

    គ្មាន fallback ឆ្លងម្ចាស់ឡើយ (D3) — បើ QR មិនមែនរបស់ម្ចាស់គណនីនោះ ប្រាក់នឹងចូល
    គណនីអ្នកដទៃ ដែលជាកំហុសលើលុយពិត មិនមែនត្រឹមទិន្នន័យលេចទេ។
    """
    def scoped(stmt):
        clause = _owner_where(QRCode, owner_admin_id)
        return stmt.where(clause) if clause is not None else stmt

    if product_id:
        qr = await session.scalar(scoped(select(QRCode).where(QRCode.product_id == product_id).order_by(QRCode.id.desc())).limit(1))
        if qr is not None:
            return qr
    qr = await session.scalar(scoped(select(QRCode).where(QRCode.is_default.is_(True))).limit(1))
    if qr is not None:
        return qr
    return await session.scalar(scoped(select(QRCode).order_by(QRCode.id.desc())).limit(1))


# ============================================================
# Customers (CRM)
# ============================================================

async def get_or_create_customer(
    session: AsyncSession,
    telegram_id: int,
    name: str = "",
    username: str = "",
) -> Customer:
    customer = await session.scalar(select(Customer).where(Customer.telegram_id == telegram_id))
    if customer is None:
        customer = Customer(telegram_id=telegram_id, name=name, username=username)
        session.add(customer)
        await session.flush()
    else:
        if name:
            customer.name = name
        if username:
            customer.username = username
        customer.last_seen = utcnow()
    return customer


async def list_customers(
    session: AsyncSession,
    search: str = "",
    tag: str = "",
    page: int = 1,
    per_page: int = 8,
    *,
    account_ids: tuple[int, ...] | None = None,
) -> tuple[list[Customer], int]:
    """Tag ស្ថិតក្នុង JSON column ដូច្នេះញ្ចូលការចម្រោះក្នុង Python (ទិន្នន័យតូច)។

    អតិថិជន derive ពីគណនីដែលគេសរសេរមក (sticky) ដូច្នេះវិសាលភាព = `account_ids`។
    """
    if no_access(account_ids):
        return [], 0
    stmt = select(Customer)
    if account_ids is not None:
        stmt = stmt.where(Customer.account_id.in_(account_ids))
    if search:
        clause = Customer.name.ilike(f"%{search}%") | Customer.username.ilike(f"%{search}%")
        stmt = stmt.where(clause)
    rows = list((await session.scalars(stmt.order_by(Customer.last_seen.desc()))).all())
    if tag:
        rows = [row for row in rows if tag in (row.tags or [])]
    total = len(rows)
    start = (page - 1) * per_page
    return rows[start : start + per_page], total


async def get_customer(
    session: AsyncSession, customer_pk: int, *, account_ids: tuple[int, ...] | None = None
) -> Customer | None:
    customer = await session.get(Customer, customer_pk)
    if customer is None:
        return None
    if account_ids is not None and customer.account_id not in account_ids:
        return None
    return customer


async def get_customer_by_telegram(
    session: AsyncSession, telegram_id: int, *, account_ids: tuple[int, ...] | None = None
) -> Customer | None:
    stmt = select(Customer).where(Customer.telegram_id == telegram_id)
    if account_ids is not None:
        if no_access(account_ids):
            return None
        stmt = stmt.where(Customer.account_id.in_(account_ids))
    return await session.scalar(stmt)


async def set_customer_flag(
    session: AsyncSession, customer_pk: int, *, ai_paused: bool | None = None, is_blocked: bool | None = None
) -> None:
    values: dict = {}
    if ai_paused is not None:
        values["ai_paused"] = ai_paused
    if is_blocked is not None:
        values["is_blocked"] = is_blocked
    if values:
        await session.execute(update(Customer).where(Customer.id == customer_pk).values(**values))


async def pause_all_customers(
    session: AsyncSession, paused: bool, *, account_ids: tuple[int, ...] | None = None
) -> int:
    """`account_ids=None` = គ្រប់អតិថិជន (Owner) — staff ត្រូវតែបញ្ជូនវិសាលភាពរបស់ខ្លួន។"""
    stmt = update(Customer).values(ai_paused=paused)
    if account_ids is not None:
        if no_access(account_ids):
            return 0
        stmt = stmt.where(Customer.account_id.in_(account_ids))
    result = await session.execute(stmt)
    return int(result.rowcount or 0)


async def add_customer_tag(session: AsyncSession, customer_pk: int, tag: str) -> None:
    customer = await session.get(Customer, customer_pk)
    if customer is None:
        return
    tags = list(customer.tags or [])
    if tag not in tags:
        tags.append(tag)
        customer.tags = tags


async def remove_customer_tag(session: AsyncSession, customer_pk: int, tag: str) -> None:
    customer = await session.get(Customer, customer_pk)
    if customer is None:
        return
    customer.tags = [t for t in (customer.tags or []) if t != tag]


async def all_customer_telegram_ids(session: AsyncSession, skip_blocked: bool = True) -> list[int]:
    """⚠️ មិនប្រើក្នុង userbot ទេ (ទុកសម្រាប់ test/របាយការណ៍) — ការផ្ញើទៅអតិថិជនគ្មានសារចូល
    គឺ unsolicited outreach ដែលនាំឱ្យគណនីត្រូវ Ban។ ច្បាប់ Inbound only។"""
    stmt = select(Customer.telegram_id)
    if skip_blocked:
        stmt = stmt.where(Customer.is_blocked.is_(False))
    return list((await session.scalars(stmt.order_by(Customer.telegram_id))).all())


async def set_customer_account(
    session: AsyncSession, telegram_id: int, account_id: int, access_hash: int | None = None
) -> str:
    """Sticky binding៖ «A ទទួលសារ → A តប»។ កំណត់តែម្តងគត់ មិនប្តូរស្ងាត់ៗទេ។
    ត្រឡប់ `bound` | `already` | `conflict` (អតិថិជននេះជាអតិថិជនរបស់គណនីផ្សេង)។"""
    customer = await session.scalar(select(Customer).where(Customer.telegram_id == telegram_id))
    if customer is None:
        return "missing"
    if access_hash is not None and customer.access_hash != access_hash:
        customer.access_hash = access_hash
    if customer.account_id is None:
        customer.account_id = account_id
        return "bound"
    if customer.account_id == account_id:
        return "already"
    return "conflict"


# ============================================================
# Messages (AI context memory)
# ============================================================

async def add_message(
    session: AsyncSession,
    customer_id: int,
    role: str,
    content: str,
    account_id: int | None = None,
) -> Message:
    message = Message(customer_id=customer_id, role=role, content=content, account_id=account_id)
    session.add(message)
    await session.flush()
    return message


async def get_history(
    session: AsyncSession, customer_id: int, limit: int = 20, account_id: int | None = None
) -> list[tuple[str, str]]:
    """ប្រវត្តិចុងក្រោយ តាមលំដាប់ចាស់→ថ្មី (សម្រាប់ AI context)។
    `account_id` = ចាំបាច់សម្រាប់ userbot ព្រោះទំនាក់ទំនងមួយរក្សាទុកតែក្នុងគណនីដែលទទួលសារនោះទេ។"""
    query = select(Message).where(Message.customer_id == customer_id)
    if account_id is not None:
        query = query.where(Message.account_id == account_id)
    rows = list(
        (
            await session.scalars(
                query.order_by(Message.created_at.desc(), Message.id.desc()).limit(limit)
            )
        ).all()
    )
    return [(row.role, row.content) for row in reversed(rows)]


async def clear_history(session: AsyncSession, customer_id: int, account_id: int | None = None) -> int:
    query = delete(Message).where(Message.customer_id == customer_id)
    if account_id is not None:
        query = query.where(Message.account_id == account_id)
    result = await session.execute(query)
    return int(result.rowcount or 0)


# ============================================================
# Orders
# ============================================================

async def create_order(
    session: AsyncSession,
    *,
    customer_id: int,
    product_id: int | None,
    product_name: str,
    price: float,
    quantity: int = 1,
    customer_name: str = "",
    status: str = OrderStatus.PENDING_PAYMENT,
    account_id: int | None = None,
) -> Order:
    order = Order(
        customer_id=customer_id,
        customer_name=customer_name,
        product_id=product_id,
        product_name=product_name,
        price=price,
        quantity=quantity,
        status=status,
        account_id=account_id,
    )
    session.add(order)
    await session.flush()
    return order


async def pick_order_account(
    session: AsyncSession, *, owner_admin_id: int | None = None, account_ids: tuple[int, ...] | None = None
) -> int | None:
    """គណនីសម្រាប់ Order ដែល admin បង្កើតដោយដៃ — primary របស់ admin នោះ បើគ្មាន → ID តូចបំផុត។

    ត្រឡប់ None ពេល admin គ្មានគណនី (handler ត្រូវបដិសេធ មិនមែនទុក order គ្មាន attribution ទេ)។
    """
    if no_access(account_ids):
        return None
    stmt = select(Account).order_by(Account.is_primary.desc(), Account.id)
    clause = _owner_where(Account, owner_admin_id)
    if clause is not None:
        stmt = stmt.where(clause)
    if account_ids is not None:
        stmt = stmt.where(Account.id.in_(account_ids))
    account = await session.scalar(stmt.limit(1))
    return int(account.id) if account is not None else None


async def get_order(session: AsyncSession, order_id: int, *, account_ids: tuple[int, ...] | None = None) -> Order | None:
    order = await session.get(Order, order_id)
    if order is None:
        return None
    if account_ids is not None and order.account_id not in account_ids:
        return None
    return order


async def list_orders(
    session: AsyncSession,
    status: str | None = None,
    customer_id: int | None = None,
    page: int = 1,
    per_page: int = 8,
    *,
    account_ids: tuple[int, ...] | None = None,
) -> tuple[list[Order], int]:
    if no_access(account_ids):
        return [], 0
    stmt = select(Order)
    count_stmt = select(func.count(Order.id))
    if account_ids is not None:
        stmt = stmt.where(Order.account_id.in_(account_ids))
        count_stmt = count_stmt.where(Order.account_id.in_(account_ids))
    if status:
        stmt = stmt.where(Order.status == status)
        count_stmt = count_stmt.where(Order.status == status)
    if customer_id:
        stmt = stmt.where(Order.customer_id == customer_id)
        count_stmt = count_stmt.where(Order.customer_id == customer_id)
    total = int((await session.scalar(count_stmt)) or 0)
    stmt = stmt.order_by(Order.id.desc()).offset((page - 1) * per_page).limit(per_page)
    rows = list((await session.scalars(stmt)).all())
    return rows, total


async def order_counts_by_status(session: AsyncSession, *, account_ids: tuple[int, ...] | None = None) -> dict[str, int]:
    zero = {status: 0 for status in OrderStatus.ALL}
    if no_access(account_ids):
        return zero
    query = select(Order.status, func.count(Order.id))
    if account_ids is not None:
        query = query.where(Order.account_id.in_(account_ids))
    rows = await session.execute(query.group_by(Order.status))
    counts = {status: int(count) for status, count in rows.all()}
    for status in OrderStatus.ALL:
        counts.setdefault(status, 0)
    return counts


async def update_order(session: AsyncSession, order_id: int, **values) -> None:
    await session.execute(update(Order).where(Order.id == order_id).values(**values))


async def _take_stock_code(session: AsyncSession, product_id: int, order_id: int) -> StockCode | None:
    """កាត់ Code មួយពី Stock — អាស៊ីស: Code ដែលកក់សម្រាប់ Order នេះរួច (button flow),
    បើគ្មាន → បន្ទាត់ដំបូងដែលមិនទាន់លក់។ SQLite មិនគាំទ្រ FOR UPDATE ប៉ុន្តែ event loop តែមួយសរសេរ។"""
    code = await session.scalar(
        select(StockCode)
        .where(
            StockCode.product_id == product_id,
            StockCode.order_id == order_id,
            StockCode.status == StockCodeStatus.RESERVED,
        )
        .order_by(StockCode.id)
        .limit(1)
    )
    if code is None:
        code = await session.scalar(
            select(StockCode)
            .where(StockCode.product_id == product_id, StockCode.is_sold.is_(False))
            .order_by(StockCode.id)
            .limit(1)
        )
    if code is None:
        return None
    code.is_sold = True
    code.status = StockCodeStatus.SOLD
    code.order_id = order_id
    code.sold_at = utcnow()
    code.reserved_for_customer_id = None
    code.reserved_at = None
    return code


async def confirm_and_deliver(session: AsyncSession, order_id: int) -> tuple[Order | None, str | None, str]:
    """ផ្ទៀងផ្ទាត់ប្រាក់ + កាត់ Code + កំណត់ Order ថាបានប្រគល់។
    ត្រឡប់ (order, code, message) — message ប្រាប់ម្ចាស់ថាអ្វីបានកើតឡើង។"""
    order = await session.get(Order, order_id)
    if order is None:
        return None, None, "រកមិនឃើញ Order"
    if order.status == OrderStatus.DELIVERED:
        return order, order.delivered_code, "Order នេះបានប្រគល់រួចរាល់ហើយ"
    if order.product_id is None:
        return order, None, "Order នេះមិនបានភ្ជាប់ផលិតផលទេ"

    code = await _take_stock_code(session, order.product_id, order.id)
    if code is None:
        return order, None, "Stock អស់ — មិនមាន Code សល់សម្រាប់បញ្ជាទិញនេះទេ"

    order.delivered_code = code.content or code.code
    order.status = OrderStatus.DELIVERED
    order.delivered_at = utcnow()

    customer = await session.scalar(select(Customer).where(Customer.telegram_id == order.customer_id))
    if customer is not None:
        if order.account_id is None:
            order.account_id = customer.account_id  # snapshot គណនីដែលចែករំលែកទំនាក់ទំនងនេះ
        customer.total_orders += 1
        customer.total_spent = round(customer.total_spent + order.price * order.quantity, 2)
        customer.last_seen = utcnow()

    # code_sent_at នៅ NULL: ម្ចាស់បាន confirm ប៉ុន្តែ userbot អាចមិនទាន់ផ្ញើទៅអតិថិជន
    return order, order.delivered_code, "បានប្រគល់រួចរាល់"


async def cancel_order(session: AsyncSession, order_id: int) -> None:
    await update_order(session, order_id, status=OrderStatus.CANCELLED)
    await release_reserved(session, order_id=order_id)  # បោះបង់ → ដោះ Code ដែលកក់ត្រឡប់ Stock


# ============================================================
# Accounts (Userbot — ជំហានទី ២)
# ============================================================

async def create_account(
    session: AsyncSession,
    phone: str,
    session_encrypted: str,
    name: str = "",
    *,
    owner_admin_id: int | None = None,
    enabled: bool = False,
    device_index: int | None = None,
) -> Account:
    account = Account(
        phone=phone,
        name=name,
        session_encrypted=session_encrypted,
        status=AccountStatus.OFFLINE,
        owner_admin_id=owner_admin_id,
        enabled=enabled,
        device_index=device_index,
        warmup_started_at=utcnow(),  # គណនីថ្មីត្រូវ warm-up 7 ថ្ងៃដោយស្វ័យប្រវត្តិ
    )
    session.add(account)
    await session.flush()
    if not account.is_primary:
        primaries = int(
            (await session.scalar(select(func.count(Account.id)).where(Account.is_primary.is_(True)))) or 0
        )
        if primaries == 0:
            account.is_primary = True
    return account


async def list_accounts(session: AsyncSession, *, owner_admin_id: int | None = None) -> list[Account]:
    stmt = select(Account).order_by(Account.is_primary.desc(), Account.id)
    clause = _owner_where(Account, owner_admin_id)
    if clause is not None:
        stmt = stmt.where(clause)
    return list((await session.scalars(stmt)).all())


async def get_account(session: AsyncSession, account_id: int, *, owner_admin_id: int | None = None) -> Account | None:
    account = await session.get(Account, account_id)
    if account is None or (owner_admin_id is not None and account.owner_admin_id != owner_admin_id):
        return None
    return account


async def transfer_account_owner(session: AsyncSession, account_id: int, new_owner_admin_id: int) -> bool:
    """ប្ដូរម្ចាស់គណនី + ទិន្នន័យដែល derive តាមវា (QR/ផលិតផលដែលភ្ជាប់គណនីនេះ) ក្នុង transaction តែមួយ។

    ផលិតផល/QR ដែល *គ្មាន* row ភ្ជាប់នឹងគណនីណាទេ មិនត្រូវប៉ះទេ — ការភ្ជាប់ (account_products)
    ជាអ្វីដែលកំណត់ថាអ្នកណាលក់វា មិនមែនជួង owner តែមួយទេ។
    """
    account = await session.get(Account, account_id)
    if account is None:
        return False
    account.owner_admin_id = new_owner_admin_id
    linked_product_ids = list(
        (await session.scalars(select(AccountProduct.product_id).where(AccountProduct.account_id == account_id))).all()
    )
    if linked_product_ids:
        await session.execute(
            update(Product)
            .where(Product.id.in_(linked_product_ids), Product.owner_admin_id.is_(None))
            .values(owner_admin_id=new_owner_admin_id)
        )
    return True


async def set_primary_account(session: AsyncSession, account_id: int) -> None:
    await session.execute(update(Account).values(is_primary=False))
    account = await session.get(Account, account_id)
    if account is not None:
        account.is_primary = True


async def set_account_status(session: AsyncSession, account_id: int, status: str, error: str = "") -> None:
    await session.execute(
        update(Account).where(Account.id == account_id).values(status=status, last_error=error[:500])
    )


async def delete_account(session: AsyncSession, account_id: int) -> None:
    """PRAGMA foreign_keys មិនបានបើកទេ ដូច្នេះ `ondelete` ជាអត្ថបទសង្ខេបតែប៉ុណ្ណោះ។
    យើង null `Message.account_id` ដោយខ្លួនឯង (ប្រវត្តិសារត្រូវនៅអានបាន) ប៉ុន្តែរក្សា
    `Customer.account_id` និង `Order.account_id` ទុកជា historical snapshot: attribution
    ចាស់ៗត្រូវរាយការណ៍ដូចដែលវាកើត ទោះគណនីត្រូវលុប។"""
    await session.execute(update(Message).where(Message.account_id == account_id).values(account_id=None))
    await session.execute(delete(AccountProduct).where(AccountProduct.account_id == account_id))
    await session.execute(delete(Account).where(Account.id == account_id))


async def set_account_flag(
    session: AsyncSession, account_id: int, *, is_primary: bool | None = None, ai_enabled: bool | None = None
) -> None:
    account = await session.get(Account, account_id)
    if account is None:
        return
    if is_primary is not None and is_primary != account.is_primary:
        await set_primary_account(session, account_id)
        account = await session.get(Account, account_id)
    if ai_enabled is not None and account is not None:
        account.ai_enabled = ai_enabled


async def set_account_enabled(session: AsyncSession, account_id: int, enabled: bool) -> None:
    """intent របស់ម្ចាស់៖ គណនីនេះគួរភ្ជាប់ឬអត់ (manager សរសេរតែ `status` ប៉ុណ្ណោះ)។"""
    await session.execute(update(Account).where(Account.id == account_id).values(enabled=enabled))


async def set_account_window(session: AsyncSession, account_id: int, spec: str | None) -> None:
    await session.execute(update(Account).where(Account.id == account_id).values(working_hours=spec))


async def set_account_warmup(session: AsyncSession, account_id: int, days: int) -> None:
    values: dict = {"warmup_days": days}
    if days <= 0:
        values["warmup_started_at"] = None  # លើស warm-up ចោល
    await session.execute(update(Account).where(Account.id == account_id).values(**values))


async def set_account_pause(session: AsyncSession, account_id: int, until: datetime | None) -> None:
    """FloodWait / ដល់កម្រិត / ម្ចាស់ pause ដោយដៃ — ត្រូវរស់ពី restart ដូច្នេះទុកក្នុង DB។"""
    await session.execute(update(Account).where(Account.id == account_id).values(pause_until=until))


async def touch_health(session: AsyncSession, account_id: int, *, status: str, error: str = "") -> None:
    await session.execute(
        update(Account)
        .where(Account.id == account_id)
        .values(last_health_check=utcnow(), status=status, last_error=error[:500])
    )


async def record_account_identity(
    session: AsyncSession,
    account_id: int,
    *,
    telegram_user_id: int | None = None,
    username: str = "",
    display_name: str = "",
) -> None:
    values = {
        column: value
        for column, value in (
            ("telegram_user_id", telegram_user_id),
            ("username", username),
            ("display_name", display_name),
        )
        if value not in (None, "")
    }
    if values:
        await session.execute(update(Account).where(Account.id == account_id).values(**values))


async def wipe_account_session(session: AsyncSession, account_id: int) -> None:
    await session.execute(
        update(Account)
        .where(Account.id == account_id)
        .values(session_encrypted="", enabled=False, status=AccountStatus.OFFLINE)
    )


async def list_connectable_accounts(session: AsyncSession) -> list[Account]:
    """គណនីដែល userbot គួរភ្ជាប់ (enabled + session សរសេររួច)។"""
    return list(
        (
            await session.scalars(
                select(Account)
                .where(Account.enabled.is_(True), Account.session_encrypted != "")
                .order_by(Account.is_primary.desc(), Account.id)
            )
        ).all()
    )


# ---------- វិសាលភាពផលិតផលក្នុងមួយគណនី ----------

async def account_scope_ids(session: AsyncSession, account_id: int) -> list[int]:
    return list((await session.scalars(select(AccountProduct.product_id).where(AccountProduct.account_id == account_id))).all())


async def set_account_scope(session: AsyncSession, account_id: int, product_ids: list[int]) -> None:
    """`[]` = លក់គ្រប់ផលិតផល active (គ្មាន row) ជៀសវាង state ទី ៣។"""
    await session.execute(delete(AccountProduct).where(AccountProduct.account_id == account_id))
    for product_id in sorted(set(product_ids)):
        if product_id:
            session.add(AccountProduct(account_id=account_id, product_id=product_id))
    await session.flush()


async def products_for_account(session: AsyncSession, account_id: int) -> list[Product]:
    """គ្មាន row → ផលិតផល active ទាំងអស់។ ប្រើ Prompt AI តែ `remaining` ប៉ុណ្ណោះ (មិន code)។"""
    query = select(Product).where(Product.is_active.is_(True))
    ids = await account_scope_ids(session, account_id)
    if ids:
        query = query.where(Product.id.in_(ids))
    return list((await session.scalars(query.order_by(Product.id))).all())


async def scope_counts(session: AsyncSession) -> dict[int, int]:
    """ចំនួនផលិតផលដែលភ្ជាប់នឹងគណនីនីមួយៗ (0 = ទាំងអស់) សម្រាប់ Panel badge។"""
    rows = await session.execute(
        select(AccountProduct.account_id, func.count(AccountProduct.id)).group_by(AccountProduct.account_id)
    )
    return {int(account_id): int(count) for account_id, count in rows.all()}


async def unsold_codes_for_products(session: AsyncSession, product_ids: list[int]) -> list[str]:
    """Code ពិតដែលនៅសល់ — ប្រើដោយ safety gate ដើម្បីរាំង AI មិនឱ្យប្រកាស code ក្នុង chat។"""
    if not product_ids:
        return []
    return list(
        (
            await session.scalars(
                select(StockCode.code).where(StockCode.product_id.in_(product_ids), StockCode.is_sold.is_(False))
            )
        ).all()
    )


# ---------- កម្រិតការផ្ញើ (derive ជំនួស counter ដែលត្រូវ reset) ----------

async def sent_counts_for_account(
    session: AsyncSession, account_id: int, hour_start: datetime, day_start: datetime
) -> tuple[int, int]:
    """រាប់សារដែល *បានផ្ញើចេញ* ពីគណនីនេះ — ប្រើ index `ix_messages_account_created`។"""
    rows = (
        await session.execute(
            select(
                case((Message.created_at >= hour_start, 1), else_=0),
                case((Message.created_at >= day_start, 1), else_=0),
            ).where(Message.account_id == account_id, Message.role.in_(SEND_ROLES), Message.created_at >= day_start)
        )
    ).all()
    return sum(row[0] for row in rows), sum(row[1] for row in rows)


async def oldest_sent_in_window(session: AsyncSession, account_id: int, since: datetime) -> datetime | None:
    """សារចាស់បំផុតក្នុងវិនដូវ sliding → បន្ថែម 1 ម៉ោង គឺពេលដែល slot ដំបូងប្រាកដជាទំនេរ។"""
    return await session.scalar(
        select(func.min(Message.created_at)).where(
            Message.account_id == account_id, Message.role.in_(SEND_ROLES), Message.created_at >= since
        )
    )


# ---------- Code រង់ចាំផ្ញើ (backlog derive ជំនួសតារាង queue) ----------

async def orders_awaiting_code(session: AsyncSession, account_id: int | None = None) -> list[Order]:
    """Order ដែលបាន confirm + មាន code ប៉ុន្តែ userbot មិនទាន់ផ្ញើ (រួមទាំងក្រោយ restart)។"""
    query = select(Order).where(
        Order.status == OrderStatus.DELIVERED,
        Order.delivered_code.is_not(None),
        Order.code_sent_at.is_(None),
    )
    if account_id is not None:
        query = query.where(Order.account_id == account_id)
    return list((await session.scalars(query.order_by(Order.id))).all())


async def mark_code_sent(session: AsyncSession, order_id: int) -> None:
    await session.execute(update(Order).where(Order.id == order_id).values(code_sent_at=utcnow()))


# ============================================================
# Admins
# ============================================================

async def list_admins(session: AsyncSession) -> list[Admin]:
    return list((await session.scalars(select(Admin).order_by(Admin.id))).all())


async def add_admin(session: AsyncSession, telegram_id: int, name: str = "", role: str = "admin") -> bool:
    exists = await session.scalar(select(Admin).where(Admin.telegram_id == telegram_id))
    if exists is not None:
        return False
    session.add(Admin(telegram_id=telegram_id, name=name, role=role))
    return True


async def remove_admin(session: AsyncSession, telegram_id: int) -> None:
    await session.execute(delete(Admin).where(Admin.telegram_id == telegram_id, Admin.role != "owner"))


async def is_staff(session: AsyncSession, user_id: int) -> bool:
    if user_id == settings.owner_id:
        return True
    if user_id in settings.admin_ids:
        return True
    row = await session.scalar(select(Admin).where(Admin.telegram_id == user_id))
    return row is not None


# ============================================================
# Analytics
# ============================================================

async def revenue_between(
    session: AsyncSession,
    start: datetime,
    end: datetime,
    account_id: int | None = None,
    *,
    account_ids: tuple[int, ...] | None = None,
) -> float:
    if no_access(account_ids):
        return 0.0
    query = select(func.coalesce(func.sum(Order.price * Order.quantity), 0.0)).where(
        Order.status == OrderStatus.DELIVERED, Order.delivered_at >= start, Order.delivered_at < end
    )
    if account_id is not None:
        query = query.where(Order.account_id == account_id)
    if account_ids is not None:
        query = query.where(Order.account_id.in_(account_ids))
    value = await session.scalar(query)
    return float(value or 0.0)


async def order_counts_between(
    session: AsyncSession,
    start: datetime,
    end: datetime,
    account_id: int | None = None,
    *,
    account_ids: tuple[int, ...] | None = None,
) -> dict[str, int]:
    if no_access(account_ids):
        return {}
    query = (
        select(Order.status, func.count(Order.id))
        .where(Order.created_at >= start, Order.created_at < end)
        .group_by(Order.status)
    )
    if account_id is not None:
        query = query.where(Order.account_id == account_id)
    if account_ids is not None:
        query = query.where(Order.account_id.in_(account_ids))
    rows = await session.execute(query)
    return {status: int(count) for status, count in rows.all()}


async def top_products(
    session: AsyncSession,
    start: datetime,
    end: datetime,
    limit: int = 5,
    account_id: int | None = None,
    *,
    account_ids: tuple[int, ...] | None = None,
) -> list[tuple]:
    if no_access(account_ids):
        return []
    query = (
        select(Order.product_name, func.count(Order.id), func.sum(Order.price * Order.quantity))
        .where(Order.status == OrderStatus.DELIVERED, Order.delivered_at >= start, Order.delivered_at < end)
        .group_by(Order.product_name)
        .order_by(func.sum(Order.price * Order.quantity).desc())
        .limit(limit)
    )
    if account_id is not None:
        query = query.where(Order.account_id == account_id)
    if account_ids is not None:
        query = query.where(Order.account_id.in_(account_ids))
    rows = await session.execute(query)
    return [(name or "—", int(count), float(total or 0.0)) for name, count, total in rows.all()]


async def new_vs_returning(
    session: AsyncSession, start: datetime, end: datetime, *, account_ids: tuple[int, ...] | None = None
) -> tuple[int, int]:
    if no_access(account_ids):
        return 0, 0
    customer_scope = (
        select(func.count(Customer.id)).where(Customer.first_seen >= start, Customer.first_seen < end)
    )
    if account_ids is not None:
        customer_scope = customer_scope.where(Customer.account_id.in_(account_ids))
    new_customers = int((await session.scalar(customer_scope)) or 0)
    returning_query = (
        select(func.count(func.distinct(Order.customer_id)))
        .join(Customer, Customer.telegram_id == Order.customer_id)
        .where(
            Order.delivered_at >= start,
            Order.delivered_at < end,
            Order.status == OrderStatus.DELIVERED,
            Customer.first_seen < start,
        )
    )
    if account_ids is not None:
        returning_query = returning_query.where(Order.account_id.in_(account_ids))
    returning = int((await session.scalar(returning_query)) or 0)
    return new_customers, returning


def period_bounds(name: str, now: datetime | None = None) -> tuple[datetime, datetime]:
    """ចន្លោះពេល (UTC) សម្រាប់ today/week/month/year, គិតតាមម៉ោងក្នុងស្រុក។"""
    from helpers import as_local

    local = as_local(now or utcnow())
    assert local is not None
    if name == "today":
        start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    elif name == "week":
        start = (local - timedelta(days=local.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    elif name == "month":
        start = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    elif name == "year":
        start = local.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        raise ValueError(f"period មិនស្គាល់: {name}")
    end = start + timedelta(days=1) if name == "today" else local + timedelta(microseconds=1)
    from zoneinfo import ZoneInfo

    return (
        start.astimezone(ZoneInfo("UTC")).replace(tzinfo=None),
        end.astimezone(ZoneInfo("UTC")).replace(tzinfo=None),
    )
