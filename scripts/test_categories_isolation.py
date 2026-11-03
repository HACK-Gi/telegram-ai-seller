"""🧪 តេស្ត Data Isolation លើ <b>ប្រភេទអីវ៉ាន់</b> (Categories per-tenant) — គ្មានបណ្តាញ។

តារាងដែលត្រូវការពារជានិច្ច (ជំហានទី ៥)៖

| សកម្មភាព                             | លទ្ធផលដែលត្រូវកើត            |
|--------------------------------------|--------------------------------|
| A បន័ែមប្រភេទ                        | B, C, Owner មើលមិនឃើញ         |
| B ចុច ID ប្រភេទរបស់ A (cat:view/edit)| ❌ បដិសេធ (IDOR)               |
| code ដូចគ្នា ក្នុង ២ ហាង             | ✅ អនុញ្ញាត (unique ក្នុងម្ចាស់) |
| code ដូចគ្នា ក្នុងហាងតែមួយ           | ❌ បដិសេធ                       |
| លុបរបស់ A                            | របស់ B ដែល code ដូចគ្នានៅដដែល |

រត់លើ DB សាកល្បងដាច់ដោយឡែក មិនប៉ះ `data/app.db` ឡើយ។
ប្រើ៖ python scripts/test_categories_isolation.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DB = ROOT / "data" / "test_categories_isolation.db"
for suffix in ("", "-wal", "-shm"):
    path = Path(str(DB) + suffix)
    if path.exists():
        path.unlink()

os.environ["USE_MOCK_BOT"] = "1"
os.environ["BOT_TOKEN"] = ""
os.environ["AI_BACKEND"] = "mock"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{DB}"
os.environ["TG_API_ID"] = "12345"
os.environ["TG_API_HASH"] = "0123456789abcdef0123456789abcdef"
from cryptography.fernet import Fernet  # noqa: E402

os.environ["SESSION_FERNET_KEY"] = Fernet.generate_key().decode()

from database import crud, db_session, init_db  # noqa: E402

SHOP_A = 900000001
SHOP_B = 900000002
SHOP_C = 900000003

PASS = 0
FAIL = 0


def check(label: str, condition: bool) -> None:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  ✅ {label}")
    else:
        FAIL += 1
        print(f"  ❌ {label}")


async def main() -> int:
    await init_db()

    # ១) រាល់ Tenant ដែលចុច /start = auto-register + ប្រភេទលំនាំដើម ៨ របស់ខ្លួនឯង
    async with db_session() as session:
        for shop in (SHOP_A, SHOP_B, SHOP_C):
            await crud.auto_register_user(session, shop, f"Shop {shop}")
    async with db_session() as session:
        own = {shop: await crud.list_all_categories(session, shop) for shop in (SHOP_A, SHOP_B, SHOP_C)}
    check("A/B/C ម្នាក់ៗមានប្រភេទលំនាំដើម ៨ ជារបស់ខ្លួនឯង", all(len(rows) == 8 for rows in own.values()))
    ids = {shop: {row.id for row in rows} for shop, rows in own.items()}
    check("row id របស់ A មិនជាន់ B ឬ C (មិនមែនបញ្ជីរួមទេ)",
          not (ids[SHOP_A] & ids[SHOP_B]) and not (ids[SHOP_A] & ids[SHOP_C]) and not (ids[SHOP_B] & ids[SHOP_C]))
    check("A មើលមិនឃើញប្រភេទរបស់ B (ទោះ code ដូចគ្នា)",
          len(own[SHOP_A]) == 8 and all(row.owner_admin_id == SHOP_A for row in own[SHOP_A]))

    # ២) code ដូចគ្នា អនុញ្ញាតខ้ามហាង ប៉ុន្តែហាមក្នុងហាងតែមួយ
    async with db_session() as session:
        cat_a, err_a = await crud.create_category(
            session, owner_admin_id=SHOP_A, code="slot", prefix="SLOT", name_kh="ស្លត A", icon="🎰"
        )
        cat_b, err_b = await crud.create_category(
            session, owner_admin_id=SHOP_B, code="slot", prefix="SLOT", name_kh="ស្លត B", icon="🎰"
        )
        dup_a, err_dup = await crud.create_category(session, owner_admin_id=SHOP_A, code="slot", name_kh="ស្លត A ២")
        await session.flush()
    check("A និង B បង្កើត code «slot» ដូចគ្នាបាន (unique ក្នុងម្ចាស់)", cat_a is not None and cat_b is not None)
    check("code ដូចគ្នាក្នុងហាង A → បដិសេធ", cat_a is not None and dup_a is None and "មានស្រាប់" in err_dup)
    if cat_a is None or cat_b is None:
        print("  ⛔ បញ្ឈប់ — មិនអាចបង្កើតប្រភេទបាន ទើប checks ខាងក្រោមគ្មានន័យ")
        return 1
    check("ឈ្មោះ A មិនប្តូរពេល B បង្កើត code ដូចគ្នា", cat_a.name_kh == "ស្លត A" and cat_b.name_kh == "ស្លត B")

    a_id = cat_a.id
    b_id = cat_b.id

    # ៣) IDOR — B ចុច id របស់ A គ្រប់ path ត្រូវតែបដិសេធ
    async with db_session() as session:
        stolen = await crud.get_category(session, a_id, owner_admin_id=SHOP_B)
        check("get_category(id របស់ A) ក្នុងវិសាលភាព B → None", stolen is None)
        by_code = await crud.get_category_by_code(session, "slot", owner_admin_id=SHOP_C)
        check("get_category_by_code(«slot») ក្នុងហាង C → None (មិន guess របស់អ្នកដទៃ)", by_code is None)
        by_name = await crud.get_category_by_name(session, "ស្លត A", owner_admin_id=SHOP_B)
        check("get_category_by_name(ឈ្មោះ A) ក្នុងវិសាលភាព B → None", by_name is None)
        before = await crud.get_category(session, a_id, owner_admin_id=SHOP_A)
        await crud.update_category(session, a_id, owner_admin_id=SHOP_B, name_kh="HIJACKED")
        after = await crud.get_category(session, a_id, owner_admin_id=SHOP_A)
        check("update_category(id របស់ A) ដោយ B → មិនប៉ះអ្វីសោះ",
              before is not None and after is not None and after.name_kh == before.name_kh)
        outcome = await crud.delete_category(session, a_id, owner_admin_id=SHOP_B)
        check("delete_category(id របស់ A) ដោយ B → 'missing' + row នៅដដែល",
              outcome == "missing" and await crud.get_category(session, a_id, owner_admin_id=SHOP_A) is not None)
        flipped = await crud.get_category(session, a_id, owner_admin_id=SHOP_A)
        await crud.update_category(session, a_id, owner_admin_id=SHOP_A, name_kh="ស្លត A", is_active=False)
        off = await crud.get_category(session, a_id, owner_admin_id=SHOP_A)
        check("A កែរបស់ខ្លួនឯងបាន (បិទ is_active)", flipped is not None and off is not None and not off.is_active)
        await crud.update_category(session, a_id, owner_admin_id=SHOP_A, is_active=True)

    # ៤) product_code រាប់តែក្នុងហាង — A និង B អាចមាន SLOT-001 ព្រមគ្នា
    async with db_session() as session:
        cat_a = await crud.get_category(session, a_id, owner_admin_id=SHOP_A)
        cat_b = await crud.get_category(session, b_id, owner_admin_id=SHOP_B)
        code_a = await crud.next_product_code(session, cat_a, SHOP_A)
        code_b = await crud.next_product_code(session, cat_b, SHOP_B)
        prod_a = await crud.create_product(
            session, name="A Slot Item", price=1.0, category_id=cat_a.id, owner_admin_id=SHOP_A
        )
        await session.flush()
    check("SLOT-001 របស់ A និង B មិនជាន់គ្នា", code_a == "SLOT-001" and code_b == "SLOT-001")
    check("ផលិតផល A ទទួល code របស់ហាង A", prod_a.product_code == "SLOT-001" and prod_a.owner_admin_id == SHOP_A)
    async with db_session() as session:
        counts_a = await crud.category_product_counts(session, owner_admin_id=SHOP_A)
        counts_b = await crud.category_product_counts(session, owner_admin_id=SHOP_B)
        check("category_product_counts A រាប់តែផលិតផល A", counts_a.get(a_id) == 1 and counts_b.get(b_id) is None)
        check("B មិនឃើញ count របស់ A", a_id not in counts_b)
        hidden = await crud.get_product(session, prod_a.id, owner_admin_id=SHOP_B)
        check("get_product(ផលិតផល A) ក្នុងវិសាលភាព B → None", hidden is None)

    # ៥) លុបរបស់ A → របស់ B ដែល code ដូចគ្នាត្រូវតែនៅរស់
    async with db_session() as session:
        blocked = await crud.delete_category(session, a_id, owner_admin_id=SHOP_A)
        check("លុបប្រភេទ A ខណៈមានផលិតផល → blocked", blocked == "blocked")
        await crud.delete_product(session, prod_a.id)
        gone = await crud.delete_category(session, a_id, owner_admin_id=SHOP_A)
        check("លុបប្រភេទ A ក្រោយសម្អាតផលិតផល → deleted", gone == "deleted")
        check("ប្រភេទ A បាត់ពីបញ្ជី A", await crud.get_category(session, a_id, owner_admin_id=SHOP_A) is None)
        survivor = await crud.get_category(session, b_id, owner_admin_id=SHOP_B)
        check("ប្រភេទ B (code «slot» ដូចគ្នា) នៅរស់ មិនត្រូវលុបខ້ម", survivor is not None and survivor.code == "slot")
        check("A មិនអាចអាន B ទោះបន្ទាប់ពីលុបរបស់ខ្លួន",
              await crud.get_category(session, b_id, owner_admin_id=SHOP_A) is None)

    # ៦) Owner ដើម មិនមែន super-admin លើប្រភេទរបស់ Tenant ទេ
    from config import settings

    async with db_session() as session:
        under_owner = await crud.list_all_categories(session, settings.owner_id)
        check("Owner ឃើញតែប្រភេទរបស់ខ្លួន (8 មិនមែន 8×N ហាង)", len(under_owner) == 8)
        check("ប្រភេទរបស់ A/B/C គ្មានក្នុងបញ្ជី Owner",
              not (ids[SHOP_A] | ids[SHOP_B] | ids[SHOP_C] | {b_id}) & {row.id for row in under_owner})
        tenant_count, total_orders = await crud.platform_totals(session)
        check("platform_totals រាប់តែចំនួនសរុប (គ្មានទិន្នន័យលម្អិត)",
              tenant_count >= 3 and isinstance(total_orders, int))

    print(f"\n{'✅ រំលង' if FAIL == 0 else '❌ មាន failure'} — {PASS}/{PASS + FAIL} checks")
    from database.session import engine

    await engine.dispose()
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
