"""🧪 តេស្ត Data Isolation ១០០% រវាង Tenant (Multi-Tenant SaaS) — គ្មានបណ្តាញ គ្មាន BOT_TOKEN។

ច្បាប់ដែលតេស្តនេះការពារ (ជំហានទី ៣)៖

| សកម្មភាព                             | លទ្ធផលដែលត្រូវកើត                 |
|--------------------------------------|------------------------------------|
| A បន័ែមផលិតផល/គណនី/QR/Order         | B, C, Owner មើលមិនឃើញ              |
| B ចុច id ទិន្នន័យរបស់ A               | ❌ បដិសេធ (IDOR guard បដិសេធដោយផ្ទាល់) |
| C មើល Order របស់ A                    | រាប់ 0                              |
| Owner មើលទិន្នន័យលម្អិតរបស់ B         | ❌ មិនឃើញ (ឃើញតែចំនួនសរុប)          |
| កូដភ្លេចបញ្ជូន scope (`account_ids=()`) | ❌ ទទេ (default ជាបិទ)              |

រត់លើ DB សាកល្បងដាច់ដោយឡែក (`data/test_tenant_isolation.db`) មិនប៉ះ `data/app.db`។
ប្រើ៖ python scripts/test_tenant_isolation.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DB = ROOT / "data" / "test_tenant_isolation.db"
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

from admin_bot.handlers import accounts as account_handlers  # noqa: E402
from admin_bot.handlers import products as product_handlers  # noqa: E402
from admin_bot.scope import Scope  # noqa: E402
from config import settings  # noqa: E402
from database import crud, db_session, init_db  # noqa: E402
from database.models import OrderStatus  # noqa: E402
from helpers import utcnow  # noqa: E402

A, B, C = 910000001, 910000002, 910000003
OWNERS = (A, B, C)
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


class RejectingCallback:
    """គ្រាន់តែ catch `.answer()` របស់ IDOR guard — មិន send អ្វីទាំងអស់។"""

    def __init__(self) -> None:
        self.answers: list[str] = []

    async def answer(self, message: str = "", cache_time: int = 0, show_alert: bool = False) -> None:
        self.answers.append(message)


def scope_of(shop: int, ids: tuple[int, ...]) -> Scope:
    return Scope(admin_id=shop, is_owner=shop == settings.owner_id, account_ids=ids)


async def main() -> int:
    await init_db()

    # ---------- ១) សាងសហាង ៣ ដែល Data ត្រូវតែដាច់ពីគ្នា ----------
    built: dict[int, dict[str, int]] = {}
    async with db_session() as session:
        for shop in OWNERS:
            await crud.auto_register_user(session, shop, f"Shop {shop}")
        for shop in OWNERS:
            categories = await crud.list_all_categories(session, shop)
            category = next((row for row in categories if row.code == "game_acc"), categories[0])
            account = await crud.create_account(
                session, f"+8551{shop % 1000000:06d}", f"SESSION-{shop}", f"UB {shop}",
                owner_admin_id=shop, enabled=True,
            )
            product = await crud.create_product(
                session, name=f"PRODUCT-OF-{shop}", price=float(shop % 97),
                category=category.name_kh, category_id=category.id, owner_admin_id=shop,
            )
            await crud.add_stock_lines(session, product.id, [f"code-{shop}-1|pw", f"code-{shop}-2|pw"])
            qr = await crud.create_qrcode(
                session, name=f"QR-OF-{shop}", provider="ABA", account_info=f"{shop} ABA",
                is_default=True, owner_admin_id=shop, account_id=account.id,
            )
            customer_tg = 950_000_000 + shop
            await crud.get_or_create_customer(session, customer_tg, f"Client {shop}")
            await crud.set_customer_account(session, customer_tg, account.id)
            order = await crud.create_order(
                session, customer_id=customer_tg, product_id=product.id,
                product_name=f"PRODUCT-OF-{shop}", price=float(10 + shop % 7), account_id=account.id,
            )
            reserved = await crud.reserve_stock(session, product.id, 1, customer_tg, order_id=order.id)
            delivered, code_out, _msg = (
                await crud.confirm_and_deliver(session, order.id) if reserved else (None, None, "")
            )
            built[shop] = {
                "account": account.id, "product": product.id, "qr": qr.id,
                "order": order.id, "customer_tg": customer_tg, "category": category.id,
                "price": float(10 + shop % 7),
            }
            check(f"Order របស់ {shop} → delivered + ប្រគល់ Code 1 មុខ",
                  delivered is not None and delivered.status == OrderStatus.DELIVERED and bool(code_out))

    scopes: dict[int, Scope] = {}
    async with db_session() as session:
        for shop in OWNERS:
            scopes[shop] = scope_of(shop, await crud.owned_account_ids(session, shop))
    check("owned_account_ids របស់នីមួយៗ = គណនីរបស់ខ្លួនតែមួយ",
          all(scopes[shop].ids == (built[shop]["account"],) for shop in OWNERS))

    # ---------- ២) គណនី ----------
    async with db_session() as session:
        for shop in OWNERS:
            others = [row.id for row in await crud.list_accounts(session, owner_admin_id=shop)]
            check(f"បញ្ជីគណនីរបស់ {shop} មានតែគណនីរបស់ខ្លួន", others == [built[shop]["account"]])
        stolen = await crud.get_account(session, built[A]["account"], owner_admin_id=B)
        check("get_account(គណនី A) ក្នុងវិសាលភាព B → None", stolen is None)
        cb = RejectingCallback()
        guarded = await account_handlers.guard_account(cb, built[A]["account"], scopes[B])
        check("guard_account(គណនី A) ដោយ B → បដិសេធ + alert", guarded is None and cb.answers)
        own = await account_handlers.guard_account(cb, built[B]["account"], scopes[B])
        check("guard_account(គណនីខ្លួន) ដោយ B → អនុញ្ញាត", own is not None)

    # ---------- ៣) ផលិតផល + Stock ----------
    async with db_session() as session:
        for shop in OWNERS:
            rows, total = await crud.list_products(session, page=1, per_page=50, owner_admin_id=shop)
            names = {row.name for row in rows}
            check(f"ផលិតផលរបស់ {shop} = តែរបស់ខ្លួន (total={total})",
                  names == {f"PRODUCT-OF-{shop}"} and total == 1)
            check(f"count_products_by_owner({shop}) = 1", await crud.count_products_by_owner(session, shop) == 1)
        cross = await crud.get_product(session, built[A]["product"], owner_admin_id=C)
        check("get_product(ផលិតផល A) ក្នុងវិសាលភាព C → None", cross is None)
        cb = RejectingCallback()
        blocked = await product_handlers.guard_product(cb, built[A]["product"], scopes[C])
        check("guard_product(ផលិតផល A) ដោយ C → បដិសេធមុន delete/update", blocked is None and cb.answers)
        code = await crud.get_product(session, built[A]["product"], owner_admin_id=A)
        by_code = await crud.get_product_by_code(session, code.product_code, owner_admin_id=C)
        check("code ដូចគ្នា (GAME-001) រាល់ហាង → ត្រឡប់ផលិតផលរបស់ C តែប៉ុណ្ណោះ មិនមែនរបស់ A",
              by_code is not None and by_code.id == built[C]["product"] and by_code.name == "PRODUCT-OF-910000003")
        low = await crud.low_stock_products(session, 5, owner_admin_id=B)
        check("low_stock_products(របស់ B) មិនរាប់ផលិតផល A/C",
              {row[0].id for row in low} == {built[B]["product"]})

    # ---------- ៤) QR — លុយត្រូវចូលហាងដែលលក់ (D3) ----------
    async with db_session() as session:
        for shop in OWNERS:
            rows = await crud.list_qrcodes(session, owner_admin_id=shop, account_ids=scopes[shop].ids)
            check(f"បញ្ជី QR របស់ {shop} មានតែ QR របស់ខ្លួន", {row.id for row in rows} == {built[shop]["qr"]})
        alien = await crud.get_qrcode(session, built[A]["qr"], owner_admin_id=B)
        check("get_qrcode(QR A) ក្នុងវិសាលភាព B → None", alien is None)
        await crud.delete_qrcode(session, built[A]["qr"], owner_admin_id=B)
        check("delete_qrcode(QR A) ដោយ B → លុបមិនបាន",
              await crud.get_qrcode(session, built[A]["qr"], owner_admin_id=A) is not None)
        await crud.set_default_qrcode(session, built[A]["qr"], owner_admin_id=B)
        kept = await crud.get_qrcode(session, built[A]["qr"], owner_admin_id=A)
        check("set_default_qrcode(QR A) ដោយ B → ប្ដូរមិនបាន", kept is not None and kept.is_default)
        picked = await crud.best_qrcode(session, built[A]["product"], owner_admin_id=A, account_id=built[A]["account"])
        wrong = await crud.best_qrcode(session, built[A]["product"], owner_admin_id=B, account_id=built[A]["account"])
        check("best_qrcode របស់ A → QR A", picked is not None and picked.id == built[A]["qr"])
        check("B មិនដែលឃើញ QR របស់ A ឡើយ (វិសាលភាពម្ចាស់)", wrong is None)

    # ---------- ៥) អតិថិជន + Order + Analytics (derive តាម account_ids) ----------
    async with db_session() as session:
        for shop in OWNERS:
            ids = scopes[shop].ids
            rows, total = await crud.list_customers(session, page=1, per_page=50, account_ids=ids)
            check(f"អតិថិជនរបស់ {shop} = តែអតិថិជនដែលចូលគណនីរបស់ខ្លួន",
                  total == 1 and {row.telegram_id for row in rows} == {built[shop]["customer_tg"]})
            hidden = await crud.get_customer_by_telegram(session, built[A]["customer_tg"], account_ids=ids)
            if shop != A:
                check(f"{shop} មើលអតិថិជន A → None", hidden is None)
            orders, order_total = await crud.list_orders(session, page=1, per_page=50, account_ids=ids)
            check(f"Order របស់ {shop} = តែ Order របស់ខ្លួន",
                  order_total == 1 and {row.id for row in orders} == {built[shop]["order"]})
            check(f"count_orders_by_owner(scope {shop}) = 1", await crud.count_orders_by_owner(session, ids) == 1)
            seen = await crud.get_order(session, built[A]["order"], account_ids=ids)
            check(f"get_order(Order A) ក្នុងវិសាលភាព {shop} → {'ឃើញ' if shop == A else 'បដិសេធ'}",
                  (seen is not None) == (shop == A))
    async with db_session() as session:
        since = utcnow() - timedelta(days=1)
        until = utcnow() + timedelta(days=1)
        for shop in OWNERS:
            ids = scopes[shop].ids
            revenue = await crud.revenue_between(session, since, until, account_ids=ids)
            counts = await crud.order_counts_between(session, since, until, account_ids=ids)
            fresh, again = await crud.new_vs_returning(session, since, until, account_ids=ids)
            tops = await crud.top_products(session, since, until, account_ids=ids)
            statuses = await crud.order_counts_by_status(session, account_ids=ids)
            names = {row[0] for row in tops}
            check(f"Analytics របស់ {shop}: ចំណូល = តែលក់របស់ខ្លួន ({revenue})",
                  abs(revenue - built[shop]["price"]) < 1e-6)
            check(f"Analytics របស់ {shop}: top_products/Order count មិនរាប់ហាងផ្សេង",
                  len(tops) == 1 and counts.get(OrderStatus.DELIVERED, 0) == 1
                  and statuses.get(OrderStatus.DELIVERED, 0) == 1
                  and all(("PRODUCT-OF-" in str(item)) for item in names))
            check(f"Analytics របស់ {shop}: អតិថិជនថ្មី ១ (តែរបស់ខ្លួន)", fresh + again == 1)
        empty = await crud.order_counts_by_status(session, account_ids=())
        check("កូដភ្លេច scope (account_ids=()) → ទទេ មិនមែនគ្រប់ហាង",
              sum(empty.values()) == 0 and await crud.revenue_between(session, since, until, account_ids=()) == 0.0)

    # ---------- ៦) Owner ឃើញតែចំនួនសរុប មិនមែនទិន្នន័យលម្អិត ----------
    owner_scope = scope_of(settings.owner_id, ())
    async with db_session() as session:
        rows, total = await crud.list_products(session, page=1, per_page=50, owner_admin_id=owner_scope.owner_id)
        check("Owner (គ្មានផលិតផលផ្ទាល់ខ្លួន) → មិនឃើញផលិតផល A/B/C", total == 0 and rows == [])
        tenants, orders = await crud.platform_totals(session)
        check("platform_totals ត្រឡប់ចំនួនសរុបតែ ២ តម្លៃ", tenants >= 3 and orders >= 3)
        check("count_tenants មិនត្រឡប់ឈ្មោះ/ID លក់", isinstance(await crud.count_tenants(session), int))
        admin_rows = await crud.list_admins(session)
        check("list_admins ជា path សម្រាប់ System តែប៉ុណ្ណោះ (row = ម្ចាស់ហាង)", len(admin_rows) >= 3)

    # ---------- ៧) ផ្ទេរម្ចាស់គណនី → scope ប្ដូរ ប៉ុន្តែ QR មិនឆ្លងម្ចាស់ (D3) ----------
    async with db_session() as session:
        moved = await crud.transfer_account_owner(session, built[A]["account"], B)
        check("transfer_account_owner(A→B) ជោគជ័យ", moved)
    async with db_session() as session:
        ids_a = await crud.owned_account_ids(session, A)
        ids_b = await crud.owned_account_ids(session, B)
        check("គណនីដែលផ្ទេរហើយ → ចេញពី scope របស់ A", built[A]["account"] not in ids_a)
        check("គណនីដែលផ្ទេរហើយ → ចូលក្នុង scope របស់ B", built[A]["account"] in ids_b)
        check("B មើលឃើញគណនី ២ (របស់ខ្លួន + ដែលទទួលផ្ទេរ)", len(ids_b) == 2)
        orphan = await crud.best_qrcode(session, built[B]["product"], owner_admin_id=B, account_id=built[A]["account"])
        check("B លក់តាមគណនីដែលទទួលផ្ទេរ → មិនបាន QR ធនាគាររបស់ A (fail-closed)", orphan is None)
        untouched = await crud.get_qrcode(session, built[A]["qr"], owner_admin_id=A)
        check("QR ចាស់នៅជារបស់ A ដដែល (លុយមិន្លេចតាមគណនី)", untouched is not None and untouched.is_default)

    print(f"\n{'✅ រំលង' if FAIL == 0 else '❌ មាន failure'} — {PASS}/{PASS + FAIL} checks")
    from database.session import engine

    await engine.dispose()
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
