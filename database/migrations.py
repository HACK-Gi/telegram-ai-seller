"""Additive SQLite migration — `create_all` មិនកែតារាងដែលមានស្រាប់ទេ។

គោលការណ៍៖ បន្ថែមតែប៉ុណ្ណោះ (ADD COLUMN / CREATE INDEX / CREATE TABLE)។ មិនដែល
DROP ឬកែប្រែប្រភេទជួងទេ ព្រោះ `data/app.db` មានទិន្នន័យពិតរបស់ម្ចាស់។
រាល់ជំហានរត់ក្នុង transaction តែមួយ ហើយ idempotent (រត់ម្តងទៀត = គ្មានអ្វីប្តូរ)។
"""
from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.engine import Connection

from database.models import Base

log = logging.getLogger("db.migrate")

SCHEMA_VERSION = 7

# SQLite ហាម NOT NULL ដោយគ្មាន literal default, ហាម UNIQUE/PRIMARY KEY លើជួងថ្មី,
# ហើយជួងដែលមាន REFERENCES ត្រូវតែ default NULL — ដូច្នេះ child FK ទាំងអស់ជា plain nullable។
ADDITIVE_COLUMNS: dict[str, list[tuple[str, str]]] = {
    "telegram_accounts": [
        ("enabled", "BOOLEAN NOT NULL DEFAULT 0"),
        ("telegram_user_id", "BIGINT"),
        ("username", "VARCHAR(100) NOT NULL DEFAULT ''"),
        ("display_name", "VARCHAR(200) NOT NULL DEFAULT ''"),
        ("working_hours", "VARCHAR(16)"),
        ("warmup_started_at", "DATETIME"),
        ("warmup_days", "INTEGER NOT NULL DEFAULT 7"),
        ("pause_until", "DATETIME"),
        ("last_health_check", "DATETIME"),
        ("notes", "TEXT NOT NULL DEFAULT ''"),
        # ជំហានទី ២.២ — RBAC + device fingerprint ថេរ
        ("owner_admin_id", "BIGINT"),
        ("device_index", "INTEGER"),
        # ជំហានទី ២.៣ — App credentials ក្នុងមួយគណនី (Fernet) ជំនួស .env
        ("tg_api_id_encrypted", "TEXT"),
        ("tg_api_hash_encrypted", "TEXT"),
    ],
    "customers": [
        ("account_id", "INTEGER"),
        ("access_hash", "BIGINT"),
    ],
    "orders": [
        ("account_id", "INTEGER"),
        ("code_sent_at", "DATETIME"),
    ],
    "products": [
        ("product_code", "VARCHAR(32)"),
        ("category_id", "INTEGER"),
        ("name_en", "VARCHAR(200) NOT NULL DEFAULT ''"),
        ("currency", "VARCHAR(8) NOT NULL DEFAULT 'USD'"),
        ("is_featured", "BOOLEAN NOT NULL DEFAULT 0"),
        ("owner_admin_id", "BIGINT"),
    ],
    "qrcodes": [
        ("owner_admin_id", "BIGINT"),
        # ជំហានទី ២.២ — QR ជាលុយពិត ភ្ជាប់នឹងគណនីដែលលក់ (NULL = QR ទូទៅ)
        ("account_id", "INTEGER"),
    ],
    "stock_codes": [
        ("content", "TEXT NOT NULL DEFAULT ''"),
        ("status", "VARCHAR(16) NOT NULL DEFAULT 'available'"),
        ("reserved_for_customer_id", "BIGINT"),
        ("reserved_at", "DATETIME"),
    ],
    "categories": [
        ("prefix", "VARCHAR(8) NOT NULL DEFAULT ''"),
    ],
}

NEW_TABLES: tuple[str, ...] = ("account_products", "categories")

INDEXES: tuple[str, ...] = (
    # derived rate-limit counting រាប់តាម (account_id, created_at) — មិនមាន index នេះទេនឹងស្កេនពេញតារាង
    "CREATE INDEX IF NOT EXISTS ix_messages_account_created ON messages (account_id, created_at)",
    "CREATE INDEX IF NOT EXISTS ix_customers_account_id ON customers (account_id)",
    "CREATE INDEX IF NOT EXISTS ix_orders_account_id ON orders (account_id)",
    "CREATE INDEX IF NOT EXISTS ix_orders_code_unsent ON orders (account_id, id) "
    "WHERE code_sent_at IS NULL AND status = 'delivered'",
    "CREATE INDEX IF NOT EXISTS ix_stock_codes_product_status ON stock_codes (product_id, status)",
    # រត់បន្ទាប់ពី backfill — NULL ច្រើនមិនប៉ះ unique ទេ ប៉ុន្តែ code ដែលស្ទួនគ្នាត្រូវរាំង
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_products_product_code ON products (product_code)",
    # RBAC — គ្រប់ read-path រាំងតាមម្ចាស់ ដូច្នេះជួងនេះត្រូវមាន index (ឈ្មោះដូច create_all)
    "CREATE INDEX IF NOT EXISTS ix_telegram_accounts_owner_admin_id ON telegram_accounts (owner_admin_id)",
    "CREATE INDEX IF NOT EXISTS ix_products_owner_admin_id ON products (owner_admin_id)",
    "CREATE INDEX IF NOT EXISTS ix_qrcodes_owner_admin_id ON qrcodes (owner_admin_id)",
    # ជំហានទី ២.២ — userbot ស្វែង QR តាមគណនីលក់ រាល់ការទិញ
    "CREATE INDEX IF NOT EXISTS ix_qrcodes_account_id ON qrcodes (account_id)",
)


def _table_info(conn: Connection, table: str) -> dict[str, str]:
    rows = conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()  # noqa: S608 — ឈ្មោះតារាងពី constants ខាងលើ
    return {row[1]: str(row[2] or "").upper() for row in rows}


def _schema_version(conn: Connection) -> int:
    return int(conn.exec_driver_sql("PRAGMA user_version").fetchone()[0] or 0)


def _seed_categories(conn: Connection) -> int:
    """បញ្ចូលប្រភេទលំនាំដើម ៧ + «ទូទៅ» (fallback) — idempotent តាម code។"""
    from database.crud import DEFAULT_CATEGORIES

    added = 0
    for order, item in enumerate(DEFAULT_CATEGORIES):
        result = conn.exec_driver_sql(
            "INSERT INTO categories (code, prefix, name_kh, name_en, icon, description, display_order, is_active) "
            "VALUES (:code, :prefix, :name_kh, :name_en, :icon, :description, :display_order, 1) "
            "ON CONFLICT(code) DO NOTHING",
            {**item, "display_order": order * 10},
        )
        added += int(result.rowcount or 0)
    return added


def _next_code_number(conn: Connection, prefix: str) -> int:
    """លេខបន្តបាត 001 ក្នុងមួយ prefix — អានពី product_code ដែលមានស្រាប់។"""
    rows = conn.exec_driver_sql(
        "SELECT product_code FROM products WHERE product_code LIKE ?", (f"{prefix}-%",)
    ).fetchall()
    highest = 0
    for (code,) in rows:
        tail = str(code).rsplit("-", 1)[-1]
        if tail.isdigit():
            highest = max(highest, int(tail))
    return highest + 1


def _backfill_products(conn: Connection) -> int:
    """ផលិតផលចាស់ (គ្មាន product_code) → ផ្សំ category_id + បង្កើត code តាម prefix។"""
    rows = conn.exec_driver_sql(
        "SELECT id, category FROM products WHERE product_code IS NULL ORDER BY id"
    ).fetchall()
    if not rows:
        return 0
    cats = conn.exec_driver_sql(
        "SELECT id, code, prefix, name_kh, name_en FROM categories"
    ).fetchall()
    lookup: dict[str, tuple[int, str]] = {}
    for cat_id, code, prefix, name_kh, name_en in cats:
        effective = (str(prefix or "").strip() or str(code).upper().replace("_", ""))[:5]
        for key in (code, name_kh, name_en):
            if key:
                lookup[str(key).strip().lower()] = (int(cat_id), effective)
    fallback = conn.exec_driver_sql("SELECT id, prefix, code FROM categories WHERE code = 'gen'").fetchone()
    if fallback is None:
        return 0
    fallback_id, fallback_prefix = int(fallback[0]), (str(fallback[1] or "GEN").strip() or "GEN")[:5]

    def resolve(legacy: str) -> tuple[int, str]:
        key = str(legacy or "").strip().lower()
        if key in lookup:
            return lookup[key]
        for cat_id, code, prefix, _kh, _en in cats:
            if str(code).startswith(key + "_") or str(code).lower() == key:
                effective = (str(prefix or "").strip() or str(code).upper().replace("_", ""))[:5]
                return int(cat_id), effective
        return fallback_id, fallback_prefix

    counters: dict[str, int] = {}
    updated = 0
    for product_id, legacy_category in rows:
        cat_id, prefix = resolve(legacy_category)
        counters[prefix] = counters.get(prefix) or _next_code_number(conn, prefix)
        product_code = f"{prefix}-{counters[prefix]:03d}"
        counters[prefix] += 1
        conn.exec_driver_sql(
            "UPDATE products SET product_code = ?, category_id = ? WHERE id = ?",
            (product_code, cat_id, product_id),
        )
        updated += 1
    return updated


def _refresh_default_prompts(conn: Connection) -> int:
    """ជំនួសតែ prompt ដែលជាលំនាំដើមចាស់ *ដូចគ្នាពិត* — កំណត់ហេតុរបស់ម្ចាស់មិនត្រូវប៉ះទេ។

    រាល់ពេលកែ `DEFAULT_SYSTEM_PROMPT`/`DEFAULT_FEW_SHOT` ត្រូវដាក់អត្ថបទចាស់ជា
    `LEGACY_..._V<n>` រួចបន្ថែមជួរនៅទីនេះ ទើប DB ដែលបាន seed ពីមុនតាមทัน។
    """
    from database.crud import (
        DEFAULT_FEW_SHOT,
        DEFAULT_SYSTEM_PROMPT,
        LEGACY_DEFAULT_FEW_SHOT,
        LEGACY_DEFAULT_FEW_SHOT_V2,
        LEGACY_DEFAULT_SYSTEM_PROMPT,
        LEGACY_DEFAULT_SYSTEM_PROMPT_V2,
    )

    pairs = (
        ("system_prompt", LEGACY_DEFAULT_SYSTEM_PROMPT, DEFAULT_SYSTEM_PROMPT),
        ("system_prompt", LEGACY_DEFAULT_SYSTEM_PROMPT_V2, DEFAULT_SYSTEM_PROMPT),
        ("few_shot", LEGACY_DEFAULT_FEW_SHOT, DEFAULT_FEW_SHOT),
        ("few_shot", LEGACY_DEFAULT_FEW_SHOT_V2, DEFAULT_FEW_SHOT),
    )
    replaced = 0
    for key, legacy, new in pairs:
        row = conn.exec_driver_sql("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        if row is not None and str(row[0]) == legacy:
            conn.exec_driver_sql("UPDATE settings SET value = ? WHERE key = ?", (new, key))
            replaced += 1
    return replaced


def _resolve_owner_id(conn: Connection) -> int | None:
    """ID របស់ម្ចាស់គត់ដែលទិន្នន័យចាស់ត្រូវទុកឱ្យ — env ជាអាទិភាព ប៉ុន្តែ DB អាចបញ្ជាក់បាន។"""
    from config import settings

    if settings.owner_id:
        return int(settings.owner_id)
    row = conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table' AND name='admins'").fetchone()
    if row is None:
        return None
    row = conn.exec_driver_sql("SELECT telegram_id FROM admins WHERE role = 'owner' LIMIT 1").fetchone()
    return int(row[0]) if row is not None else None


def _backfill_owners(conn: Connection) -> int | None:
    """ទិន្នន័យចាស់ទាំងអស់ = របស់ម្ចាស់ (staff ថ្មីមិនគួរឃើញអ្វីសោះពេលដំបូង)។

    តែ NULL ដែលនៅសល់ (គ្មាន owner_id ក្នុង env/DB) នៅតែសុវត្ថិភាព ព្រោះ owner ឃើញ
    គ្រប់យ៉ាងដោយមិន filter តាមជួងនេះទេ រីឯ staff ឃើញតែជួងដែលត្រង់ ID របស់ខ្លួន។
    """
    owner_id = _resolve_owner_id(conn)
    if owner_id is None:
        return None
    moved = 0
    for table in ("telegram_accounts", "products", "qrcodes"):
        result = conn.exec_driver_sql(
            f"UPDATE {table} SET owner_admin_id = ? WHERE owner_admin_id IS NULL", (owner_id,)  # noqa: S608 — ឈ្មោះតារាងពី constants ខាងលើ
        )
        moved += int(result.rowcount or 0)
    return moved


def _apply(conn: Connection) -> list[str]:
    notes: list[str] = []
    known_tables = {row[0] for row in conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}

    for table, columns in ADDITIVE_COLUMNS.items():
        if table not in known_tables:
            continue  # DB ថ្មីស្អាត — create_all បានបង្កើតជួងទាំងនេះរួចហើយ
        existing = _table_info(conn, table)
        for name, ddl in columns:
            if name in existing:
                if existing[name] and ddl.split()[0] not in existing[name]:
                    log.warning("ជួង %s.%s មានប្រភេទ %s ខុសពី %s — រក្សាទុកដូចចាស់ មិនកែទេ", table, name, existing[name], ddl)
                continue
            conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
            notes.append(f"{table}.{name}")

    # តារាងថ្មី បង្កើតពី model ដើម្បីកុំឱ្យ schema និង code ឃ្លាតពីគ្នា
    for table_name in NEW_TABLES:
        table = Base.metadata.tables[table_name]
        if not conn.dialect.has_table(conn, table.name):
            table.create(conn, checkfirst=True)
            notes.append(f"table {table.name}")

    seeded = _seed_categories(conn)
    if seeded:
        notes.append(f"categories seeded +{seeded}")
    backfilled = _backfill_products(conn)
    if backfilled:
        notes.append(f"product_code backfill +{backfilled}")
    # is_sold ចាស់ → status ថ្មី ឱ្យត្រង់គ្នា (idempotent)
    conn.exec_driver_sql("UPDATE stock_codes SET status = 'sold' WHERE is_sold = 1 AND status <> 'sold'")

    refreshed = _refresh_default_prompts(conn)
    if refreshed:
        notes.append(f"default prompts refreshed ×{refreshed}")

    owners = _backfill_owners(conn)
    if owners is None:
        notes.append("owner backfill skipped (no OWNER_ID)")
    elif owners:
        notes.append(f"owner backfill +{owners}")

    for ddl in INDEXES:
        conn.exec_driver_sql(ddl)

    # គណនីចាស់ដែលមិនទាន់មាន warm-up clock ត្រូវរាប់ពីថ្ងៃបង្កើត
    if "telegram_accounts" in known_tables:
        conn.exec_driver_sql(
            "UPDATE telegram_accounts SET warmup_started_at = created_at WHERE warmup_started_at IS NULL"
        )

    conn.exec_driver_sql(f"PRAGMA user_version = {SCHEMA_VERSION}")
    return notes


async def migrate() -> list[str]:
    """រត់ migration លើ engine ច្បាស់លាស់ ត្រឡប់បញ្ជីអ្វីដែលបានបន្ថែម។"""
    from database.session import engine

    async with engine.begin() as conn:
        return await conn.run_sync(_apply)


async def schema_version() -> int:
    from database.session import engine

    async with engine.connect() as conn:
        return await conn.run_sync(lambda c: c.execute(text("PRAGMA user_version")).scalar_one())
