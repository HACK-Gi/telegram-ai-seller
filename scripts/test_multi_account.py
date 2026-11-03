"""🧪 តេស្ត «គណនីច្រើនគ្មានកំណត់» (Unlimited Multi-Account) — គ្មានបណ្តាញ គ្មាន BOT_TOKEN។

បញ្ហាដើមដែលត្រូវការពារជានិច្ច: `telegram_accounts.phone` ជា NOT NULL + UNIQUE ខណៈ
`get_me().phone` អាចជា `None` (អ្នកប្រើបិទ «Who can see my phone number»)។ បើកូដយក
`me.phone` ទៅរក្សាទុក ឬប្រើជាគន្លឹះរកគណនី គណនីទី២ នឹងបែកជា `IntegrityError` ហើយ
bot មើលទៅដូចជា «ប្រើបានតែគណនីតែមួយ»។ តេស្តនេះបិទ path នោះ។

ប្រើ៖ python scripts/test_multi_account.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DB = ROOT / "data" / "test_multi_account.db"
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

import telethon  # noqa: E402
import telethon.sessions  # noqa: E402

from admin_bot.handlers import accounts as accounts_handlers  # noqa: E402
from admin_bot.scope import Scope  # noqa: E402
from database import crud, db_session, init_db  # noqa: E402
from database.models import Account  # noqa: E402
from sqlalchemy import select  # noqa: E402

OWNER = Scope(admin_id=1001, is_owner=True, account_ids=())
STAFF_A = Scope(admin_id=2002, is_owner=False, account_ids=())
STAFF_B = Scope(admin_id=3003, is_owner=False, account_ids=())

SESSION_1 = "1" + "A" * 300
SESSION_2 = "1" + "B" * 300
SESSION_3 = "1" + "C" * 300
SESSION_1B = "1" + "D" * 300

_checks: list[tuple[str, bool]] = []


def check(label: str, condition: bool) -> None:
    _checks.append((label, bool(condition)))
    print(("  ✅ " if condition else "  ❌ ") + label)


# ---------------- Fakes: Telethon client + FSM/Message ----------------
class FakeStringSession:
    def __init__(self, value: str = "") -> None:
        self.value = value


class Me:
    def __init__(self, user_id: int, phone: str | None, first: str, last: str) -> None:
        self.id = user_id
        self.phone = phone
        self.username = None
        self.first_name = first
        self.last_name = last


class FakeClient:
    """ក្លែង `TelegramClient` តាម path របស់ md_login_session (connect/get_me/authorized)។"""

    current: Me = Me(1, "+85593000001", "One", "")
    built: list["FakeClient"] = []

    def __init__(self, session, api_id, api_hash) -> None:
        self.session = session
        self.disconnected = False
        FakeClient.built.append(self)

    @classmethod
    def set_me(cls, me: Me) -> None:
        cls.current = me
        cls.built.clear()

    async def connect(self) -> bool:
        return True

    async def get_me(self):
        return FakeClient.current

    async def is_user_authorized(self) -> bool:
        return True

    async def disconnect(self) -> None:
        self.disconnected = True


class FakeMessage:
    def __init__(self, text: str) -> None:
        self.text = text
        self.chat = SimpleNamespace(id=777, type="private")
        self.answers: list[str] = []
        self.deleted = False

    async def answer(self, text: str, **_kwargs) -> None:
        self.answers.append(text)

    async def delete(self) -> None:
        self.deleted = True


class FakeState:
    def __init__(self) -> None:
        self.state = None
        self.data: dict = {}

    async def set_state(self, state) -> None:
        self.state = state

    async def update_data(self, data: dict) -> None:
        self.data.update(data)

    async def get_data(self) -> dict:
        return self.data

    async def clear(self) -> None:
        self.state = None
        self.data = {}


telethon.TelegramClient = FakeClient
telethon.sessions.StringSession = FakeStringSession


async def add_session(scope: Scope, me: Me, session_string: str) -> FakeMessage:
    FakeClient.set_me(me)
    message = FakeMessage(session_string)
    state = FakeState()
    await state.set_state(accounts_handlers.LoginStates.waiting_session)
    await accounts_handlers.md_login_session(message, state, scope)
    return message


async def rows() -> list[Account]:
    async with db_session() as session:
        return await crud.list_accounts(session)


async def main() -> int:
    await init_db()

    print("— ១) បន័ែម ៣ គណនី (គណនីទី៣ គ្មានលេខទូរស័ព្ទពី Telegram) —")
    await add_session(STAFF_A, Me(9001, "+85593000001", "Sok", "Chan"), SESSION_1)
    await add_session(STAFF_A, Me(9002, "+85593000002", "Srey", "Neang"), SESSION_2)
    await add_session(STAFF_A, Me(9003, None, "No", "Phone"), SESSION_3)
    all_rows = await rows()
    check("បន័ែម ៣ គណនី → មាន ៣ row ក្នុង DB", len(all_rows) == 3)
    check("រាល់ row មាន owner_admin_id = staff ដែលបន័ែម", {r.owner_admin_id for r in all_rows} == {STAFF_A.admin_id})
    check("គណនីទី៣ ដែលគ្មានលេខ → មិន fail (phone placeholder)",
          any(r.telegram_user_id == 9003 and r.phone.startswith("tg:") for r in all_rows))
    check("placeholder មានលេខ Telegram ក្នុង (តែមួយគត់)",
          any(r.phone == "tg:9003" for r in all_rows))
    check("គ្មាន row ណា phone ទទេ/None (NOT NULL)", all((r.phone or "") != "" for r in all_rows))
    check("គ្មាន row ណាសល់ session string /plain OTP",
          all(SESSION_1 not in (r.session_encrypted or "") for r in all_rows))
    check("គណនីទាំងអស់ enabled=True (intent ភ្ជាប់ភ្លាម)", all(r.enabled for r in all_rows))
    check("primary មានតែមួយគត់", sum(1 for r in all_rows if r.is_primary) == 1)

    print("— ២) Upsert: session ថ្មីលើគណនីដើម → រក្សា row ចាស់ —")
    await add_session(STAFF_A, Me(9001, "+85593000001", "Sok", "Chan"), SESSION_1B)
    after = await rows()
    check("upsert → នៅ ៣ row (មិនបង្កើតស្ទួន)", len(after) == 3)
    first = next(r for r in after if r.telegram_user_id == 9001)
    check("upsert → session ថ្មីជំនួសចាស់", first.session_encrypted != all_rows[0].session_encrypted)
    check("upsert → មិនបាត់ telegram_user_id", first.telegram_user_id == 9001)

    print("— ៣) IDOR: គណនីរបស់ staff ផ្សេង → បដិសេធ មិនប៉ះ row —")
    before_token = first.session_encrypted
    reply = await add_session(STAFF_B, Me(9001, "+85593000001", "Sok", "Chan"), SESSION_2)
    check("IDOR → សារបដិសេធបង្ហាញ", "admin ផ្សេងហើយ" in " ".join(reply.answers))
    again = await rows()
    check("IDOR → មិនបង្កើត row ថ្មី", len(again) == 3)
    check("IDOR → session ដើមមិនត្រូវ replace",
          next(r for r in again if r.telegram_user_id == 9001).session_encrypted == before_token)

    print("— ៤) វិសាលភាព Tenant: ម្ចាស់ហាងនីមួយៗ ឃើញតែគណនីរបស់ខ្លួន (សូម្បីតែ Owner ដើម) —")
    async with db_session() as session:
        owner_seen = await crud.list_accounts(session, owner_admin_id=OWNER.admin_id)
        staff_seen = await crud.list_accounts(session, owner_admin_id=STAFF_A.admin_id)
        other_seen = await crud.list_accounts(session, owner_admin_id=STAFF_B.admin_id)
        unfiltered = await crud.list_accounts(session)
    check("Owner = tenant ធម្មតា → មិនឃើញគណនី staff", len(owner_seen) == 0)
    check("Staff ម្ចាស់គណនី → ឃើញ ៣", len(staff_seen) == 3)
    check("Staff ផ្សេង → មិនឃើញសោះ", len(other_seen) == 0)
    check("query គ្មាន filter = ៣ (មានតែ path internal ប៉ុណ្ណោះ)", len(unfiltered) == 3)

    print("— ៥) គណនី ១០ គណនី (គ្មានកំណត់ពិតប្រាកដ) —")
    for index in range(10):
        await add_session(OWNER, Me(9100 + index, None, f"Shop{index}", ""), f"1{chr(65 + index % 26)}" + "Z" * 300)
    many = await rows()
    check("បន្ថែម ១០ គណនីគ្មានលេខ → សរុប ១៣ row", len(many) == 13)
    check("គ្មាន constraint ណាហាមគណនីទី២+", len(many) > 3)
    check("phone placeholder មិនបុកគ្នា", len({r.phone for r in many}) == len(many))

    print("— ៦) AccountManager ភ្ជាប់គ្រប់គណនី enabled —")
    from userbot import manager as manager_module
    from userbot import session_store

    connected: list[int] = []
    identities: dict[int, Me] = {}

    class ManagerClient(FakeClient):
        me: Me

        async def add_event_handler(self, *args, **kwargs) -> None:
            return None

        async def get_peer_id(self, peer) -> int:
            return 1

        async def get_me(self):
            return self.me

    def fake_make_client(account_id, session, device_index=None, *, api_id, api_hash):
        connected.append(account_id)
        client = ManagerClient(FakeStringSession("x"), api_id, api_hash)
        client.me = identities[account_id]
        return client

    class FakeSender:
        def __init__(self, client) -> None:
            self.client = client

    manager_module.make_client = fake_make_client
    manager_module.TelethonSender = FakeSender
    catalog_calls: list[int] = []
    seller_calls: list[int] = []

    class FakeCatalog:
        def __init__(self, account_id, **kwargs) -> None:
            catalog_calls.append(account_id)

        async def on_callback(self, event) -> None:
            return None

    class FakeSeller:
        def __init__(self, account_id, **kwargs) -> None:
            seller_calls.append(account_id)
            self.account_id = account_id

        async def start(self) -> None:
            return None

        async def stop(self) -> None:
            return None

        def _is_staff(self, user_id: int) -> bool:
            return False

        async def on_incoming(self, event) -> None:
            return None

    class FakeControls:
        def __init__(self, account_id, **kwargs) -> None:
            return None

    manager_module.Catalog = FakeCatalog
    manager_module.Seller = FakeSeller
    manager_module.Controls = FakeControls
    # session string ក្លែង មិនត្រូវ StringSession ពិតយកទេ (byte ខ្លី) — ជំនួស class តែមួយ
    # Fernet decrypt នៅដំណើរការពិត — path រក្សាទុក/អាន session នៅត្រូវបានតេស្ត។
    session_store.StringSession = FakeStringSession

    manager = manager_module.AccountManager(notify=lambda text: asyncio.sleep(0))
    async with db_session() as session:
        accounts = await crud.list_accounts(session, owner_admin_id=None)
    ids = [account.id for account in accounts]
    identities = {
        account.id: Me(
            account.telegram_user_id or 0,
            account.phone,
            account.display_name or f"Shop{account.id}",
            "",
        )
        for account in accounts
    }
    await manager.reconcile()
    check("manager ភ្ជាប់គ្រប់គណនីដែល connectable (១៣)", len(connected) == len(ids) == 13)
    check("គ្រប់គណនីមាន Seller ផ្ទាល់ខ្លួន", sorted(seller_calls) == sorted(connected))
    check("Outbox/catalog ក្នុងមួយគណនី", sorted(catalog_calls) == sorted(connected))

    connected.clear()
    async with db_session() as session:
        await crud.set_account_enabled(session, ids[0], False)
        await session.commit()
    await manager.reconcile()
    check("បិទ ១ គណនី → មិន reconnect ថ្មី", connected == [])
    async with db_session() as session:
        await crud.set_account_enabled(session, ids[0], True)
        await session.commit()
    await manager.reconcile()
    check("បើកឡើងវិញ → reconcile ភ្ជាប់តែគណនីនោះ", connected == [ids[0]])
    await manager.shutdown()
    manager_module.reset_manager()

    print("— ៧) message ជោគជ័យ មិនបង្ហាញលេខទូរស័ព្ទពេញលេញ —")
    reply = await add_session(STAFF_A, Me(9001, "+85593000001", "Sok", "Chan"), SESSION_1)
    body = " ".join(reply.answers)
    check("ភ្ជាប់រួច → បង្ហាញ 🔐 Session: ✅ Configured", "Session:" in body and "Configured" in body)
    check("ភ្ជាប់រួច → លេខត្រូវបិទកណ្តាល", "+855****0001" in body and "+85593000001" not in body)

    failed = [label for label, ok in _checks if not ok]
    print(f"\n{'✅ ជោគជ័យ' if not failed else '❌ បរាជ័យ'} — {len(_checks) - len(failed)}/{len(_checks)} checks")
    for label in failed:
        print(f"  ✗ {label}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
