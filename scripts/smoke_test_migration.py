"""🧪 Smoke test ជំហាន ១b/២/៥ — migration v4 + stock reservation + oversell លើច្បាប់របស់ DB ពិត។

ប្រើ៖ python scripts/smoke_test_migration.py

ច្បាប់របស់ `data/app.db` ត្រូវចម្លងតាម sqlite backup API (WAL-aware — `cp` ធម្មតា
យកតែ main file ដែលអាចជា version ចាស់)។ រត់ migration ២ ដើម្បីភាព idempotent,
ពិនិត្យ seed ៨ ប្រភេទ, backfill GAME-001, prompt refresh (លំនាំដើមចាស់ → ថ្មី,
កំណត់ហេតុម្ចាស់ → មិនប៉ះ), រួច flow ទាំងស្រុង៖ code ស្វ័យប្រវត្តិ, កក់, oversell
ត្រូវបដិសេធ, deliver ត្រឡប់ content, cancel → release។ គ្មានប៉ះ DB ពិតទេ។
"""
from __future__ import annotations

import asyncio
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SCRATCH = Path("/tmp/smoke_migration.db")
for suffix in ("", "-wal", "-shm"):
    p = Path(str(SCRATCH) + suffix)
    if p.exists():
        p.unlink()

src = sqlite3.connect(str(ROOT / "data" / "app.db"))
dst = sqlite3.connect(str(SCRATCH))
src.backup(dst)
dst.close()
src.close()

os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{SCRATCH}"
os.environ["AI_BACKEND"] = "mock"

import database.crud as crud  # noqa: E402
from database import migrations, session as dbsession  # noqa: E402
from database.models import OrderStatus  # noqa: E402

PASS = 0
FAIL = 0


def check(name: str, cond: bool) -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name}")


async def main() -> int:
    # ១) ដាក់លំនាំដើមចាស់ «យ fictitious fresh» ដើម្បីឱ្យ refresh កំណត់បាន
    async with dbsession.SessionFactory() as s:
        row = await s.get(crud.Setting, "system_prompt")
        if row is None:
            s.add(crud.Setting(key="system_prompt", value=crud.LEGACY_DEFAULT_SYSTEM_PROMPT))
            row = await s.get(crud.Setting, "system_prompt")
        else:
            row.value = crud.LEGACY_DEFAULT_SYSTEM_PROMPT
        fs = await s.get(crud.Setting, "few_shot")
        if fs is None:
            s.add(crud.Setting(key="few_shot", value=crud.LEGACY_DEFAULT_FEW_SHOT))
        else:
            fs.value = crud.LEGACY_DEFAULT_FEW_SHOT
        await s.commit()

    print("\n[1] Migration v4 — idempotent + seed + backfill + prompt refresh")
    notes = await migrations.migrate()
    check("schema version = 4", (await migrations.schema_version()) == 4)
    async with dbsession.SessionFactory() as s:
        seeded_now = await crud.list_all_categories(s)
    check("categories មាន ៨ (seed ឬស្រាប់ពី DB ពិត)", len(seeded_now) == 8)
    check("prompts ត្រូវ refresh", any("default prompts refreshed" in n for n in notes))
    async with dbsession.SessionFactory() as s:
        sp = await crud.get_setting(s, "system_prompt")
        fs = await crud.get_setting(s, "few_shot")
        check("system_prompt → លំនាំដើមថ្មី", sp == crud.DEFAULT_SYSTEM_PROMPT)
        check("few_shot → លំនាំដើមថ្មី", fs == crud.DEFAULT_FEW_SHOT)
        check("prompt ថ្មីមាន «menu» + voice rule", "«menu»" in sp and "Voice" in sp)
    # owner custom មិនត្រូវប៉ះ
    async with dbsession.SessionFactory() as s:
        row = await s.get(crud.Setting, "system_prompt")
        row.value = "MY CUSTOM PROMPT"
        await s.commit()
    notes2 = await migrations.migrate()
    check("migration ទី២ → គ្មាន refresh ថ្មី", not any("prompts" in n for n in notes2))
    async with dbsession.SessionFactory() as s:
        check("កំណត់ហេតុម្ចាស់ ត្រូវរក្សាទុក", (await crud.get_setting(s, "system_prompt")) == "MY CUSTOM PROMPT")
        row = await s.get(crud.Setting, "system_prompt")
        row.value = crud.DEFAULT_SYSTEM_PROMPT
        await s.commit()

    print("\n[2] Categories + backfill លើទិន្នន័យពិត (ច្បាប់)")
    async with dbsession.SessionFactory() as s:
        cats = await crud.list_all_categories(s)
        codes = [c.code for c in cats]
        check("មាន ៨ categories", len(cats) == 8 and "game_acc" in codes and "gen" in codes)
        p1 = await crud.get_product(s, 1)
        if p1 is not None:
            game_cat = await crud.get_category_by_code(s, "game_acc")
            check("backfill product #1 → GAME-*", str(p1.product_code or "").startswith("GAME-"))
            check("backfill category_id → game_acc", p1.category_id == game_cat.id)
            check("stock collection អានបាន (no MissingGreenlet)", p1.remaining >= 0)

    print("\n[3] Product code + stock lines + reservation/oversell")
    async with dbsession.SessionFactory() as s:
        cat = await crud.get_category_by_code(s, "ai_pro")
        p = await crud.create_product(s, name="Test AIPRO", price=10.0, category_id=cat.id)
        await s.commit()
        check("code ស្វ័យប្រវត្តិ AIPRO-*", str(p.product_code or "").startswith("AIPRO-"))
        check("category ត្រូវ mirror ពី name_kh", p.category == cat.name_kh)
        check("stock រឿនដោយគ្មាន MissingGreenlet", p.remaining == 0 and p.available == 0 and p.reserved == 0)
        pid = p.id
        base = p.product_code

    async with dbsession.SessionFactory() as s:
        created = await crud.add_stock_lines(s, pid, ["u1@mail.com|pass1", "", "u2@mail.com|pass2", "u1@mail.com|pass1", "u3@mail.com|pass3"])
        await s.commit()
        check("បង្កើត ៣ codes (រំលងទទេ + content ស្ទួន)", len(created) == 3)
        check("ទម្រង់ {code}-S001..S003", [c.code for c in created] == [f"{base}-S001", f"{base}-S002", f"{base}-S003"])
        check("ទាំងអស់ available", all(c.status == "available" for c in created))
        check("content រក្សាទុក", created[0].content == "u1@mail.com|pass1")

        check("available = 3", await crud.available_stock(s, pid) == 3)
        r1 = await crud.reserve_stock(s, pid, 1, 999001)
        await s.commit()
        check("កក់ ១ ជោគជ័យ", len(r1) == 1 and r1[0].status == "reserved")
        check("available លើស = 2", await crud.available_stock(s, pid) == 2)
        r2 = await crud.reserve_stock(s, pid, 3, 999002)
        await s.commit()
        check("oversell ត្រូវបដិសេធ (សុំ 3 សល់ 2 → [])", r2 == [])
        check("មិនកក់ពាក់កណ្តាល — available នៅ 2", await crud.available_stock(s, pid) == 2)

        released = await crud.release_reserved(s, product_id=pid)
        await s.commit()
        check("release កក់គ្មាន order រួច", released >= 1)
        order = await crud.create_order(s, customer_id=999001, product_id=pid, product_name="Test AIPRO", price=10.0, quantity=1)
        await s.commit()
        r3 = await crud.reserve_stock(s, pid, 1, 999001, order_id=order.id)
        await s.commit()
        check("order បាន Code ដែលកក់ត្រឹមត្រូវ (S001)", len(r3) == 1 and r3[0].code == f"{base}-S001" and r3[0].order_id == order.id)
        order_id = order.id

    async with dbsession.SessionFactory() as s:
        order, code, _msg = await crud.confirm_and_deliver(s, order_id)
        await s.commit()
        check("deliver ត្រឡប់ content (មិនមែន code label)", code == "u1@mail.com|pass1")
        check("status = delivered", order.status == OrderStatus.DELIVERED)

    async with dbsession.SessionFactory() as s:
        await crud.release_reserved(s, product_id=pid)
        await s.commit()
        o2 = await crud.create_order(s, customer_id=999002, product_id=pid, product_name="Test AIPRO", price=10.0)
        await s.commit()
        rr = await crud.reserve_stock(s, pid, 3, 999002, order_id=o2.id)
        await s.commit()
        check("កក់ ៣ ខណៈសល់ ២ → ត្រូវបដិសេធ", rr == [])
        rr = await crud.reserve_stock(s, pid, 1, 999002, order_id=o2.id)
        await s.commit()
        check("កក់ ១ ជោគជ័យ (សល់ ២)", len(rr) == 1)
        before = await crud.available_stock(s, pid)
        await crud.cancel_order(s, o2.id)
        await s.commit()
        check("cancel → release ត្រឡប់ available", await crud.available_stock(s, pid) == before + 1)

    async with dbsession.SessionFactory() as s:
        await crud.delete_product(s, pid)
        await s.commit()
        check("សម្អាត test product រួច", await crud.get_product(s, pid) is None)

    print(f"\n{'✅ រំលង' if FAIL == 0 else '❌ មាន failure'} — {PASS}/{PASS + FAIL} checks")
    await dbsession.engine.dispose()
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
