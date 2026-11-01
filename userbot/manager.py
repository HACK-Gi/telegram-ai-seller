"""AccountManager — គណនី Telethon ច្រើនក្នុង process តែមួយ (ជំហានទី ២.១)។

រាល់គណនីមាន equipment ផ្ទាល់ខ្លួន៖ TelegramClient + Outbox (single writer) +
Coalescer + Seller + Controls។ គ្មាន shared state រវាងគណនីទេ — នេះជាបេះដូងនៃច្បាប់
sticky «A ទទួលសារ → A តប»៖ ការផ្ញើចេញទាំងអស់ត្រូវតែឆ្លងកាត់ outbox របស់គណនីដែល
អតិថិជនបានសរសេរមក គ្មាន path RR/fallback ទេ។

Hot-reload៖ reconcile រាល់ ៦០ វិនាទី បើក/បិទគណនីតាម `enabled` + session ក្នុង DB
ដោយមិនត្រូវ restart process។ Panel អាប់ដេត intent → manager ពិនិត្យឃើញខ្លួនឯង។
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from telethon import TelegramClient, events

from config import settings
from database import crud
from database.models import AccountStatus
from database.session import db_session
from userbot import session_store
from userbot.catalog import Catalog
from userbot.outbox import PRIORITY_REPLY, Outbox, OutboxItem, PeerRef, TelethonSender
from userbot.safety import describe_error
from userbot.seller import Seller
from userbot.controls import Controls

log = logging.getLogger("userbot.manager")

RECONCILE_INTERVAL = 60.0

# គណនីច្រើនពី IP តែមួយ ដែល device string หมือนគ្នាក៊ូ = fingerprint ងាយ។
# ជ្រើសស្ថិតស្ថេរតាម account_id (មិនប្តូររៀងរាល់ restart)។
DEVICE_POOL: tuple[tuple[str, str, str], ...] = (
    ("Samsung Galaxy A54", "Android 14", "Telegram Android 11.2"),
    ("iPhone 13", "iOS 17.5", "Telegram iOS 11.2"),
    ("ASUS VivoBook 15", "Windows 11", "Telegram Desktop 5.4"),
    ("Xiaomi Redmi Note 12", "Android 13", "Telegram Android 11.1"),
    ("MacBook Air M2", "macOS 14.5", "Telegram Desktop 5.4"),
    ("OPPO A78", "Android 13", "Telegram Android 11.2"),
)


class ManagerError(RuntimeError):
    pass


def make_client(account_id: int, session: Any, device_index: int | None = None) -> TelegramClient:
    """device_index ត្រូវរក្សាទុកក្នុង DB (`Account.device_index`) ដើម្បីឱ្យ fingerprint
    ពេល login (chat/CLI) ដូចគ្នានឹងពេល manager ភ្ជាប់រាល់ពេល reconnect — បើប្តូរ
    Telegram ឃើញ «device ថ្មី» រាល់ដងដែល reconnect ដែលជា signal នៃ bot farm។"""
    index = device_index if device_index is not None else account_id
    device, system, version = DEVICE_POOL[index % len(DEVICE_POOL)]
    return TelegramClient(
        session,
        settings.tg_api_id,
        settings.tg_api_hash,
        device_model=device,
        system_version=system,
        application_version=version,
        lang_code="km",
        request_timeout=30,
        auto_reconnect=True,
        connection_retries=4,
    )


class AccountManager:
    def __init__(
        self,
        *,
        notify: Callable[[str], Awaitable[None]] | None = None,
        reconcile_interval: float = RECONCILE_INTERVAL,
    ) -> None:
        self._clients: dict[int, TelegramClient] = {}
        self._outboxes: dict[int, Outbox] = {}
        self._sellers: dict[int, Seller] = {}
        self._notify = notify
        self._reconcile_interval = reconcile_interval
        self._tasks: list[asyncio.Task] = []
        self._global_stopped = False
        self._started = False

    # ---------- ទំនាក់ទំនង ----------
    def set_notify(self, notify: Callable[[str], Awaitable[None]]) -> None:
        self._notify = notify

    async def notify(self, text: str) -> None:
        """ជូនដំណឹងម្ចាស់ — កំហុសផ្ទេរមិនសម្លាប់ worker ទេ (log តាម describe_error)។"""
        if self._notify is None:
            log.warning("notify (គ្មាន channel): %s", text)
            return
        try:
            await self._notify(text)
        except Exception as exc:  # noqa: BLE001
            log.warning("notify owner មិនបាន: %s", describe_error(exc))

    # ---------- ចាប់ផ្តើម / បញ្ឈប់ ----------
    async def start(self) -> None:
        self._started = True
        async with db_session() as session:
            flag = await crud.get_setting(session, "userbot_enabled", "on")
        if flag.strip().lower() != "on":
            self._global_stopped = True
            log.info("userbot ត្រូវបានបិទពីមុន (/stopbot) — reconcile នៅដំណើរការស្ងាត់")
        await self.reconcile()
        self._tasks.append(asyncio.create_task(self._reconcile_loop(), name="userbot:reconcile"))
        log.info("AccountManager ដំណើរការ · គណនី active %d", len(self._clients))

    async def shutdown(self) -> None:
        for task in self._tasks:
            task.cancel()
        self._tasks.clear()
        for account_id in list(self._clients):
            try:
                await self.stop_client(account_id)
            except Exception:  # noqa: BLE001
                log.exception("shutdown គណនី %s មិនស្អាត", account_id)

    async def _reconcile_loop(self) -> None:
        while True:
            await asyncio.sleep(self._reconcile_interval)
            try:
                await self.reconcile()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("reconcile កំហុស")

    async def reconcile(self) -> None:
        """ដូរភាពរវាង DB intent និង clients ពិត — hot-reload ដោយគ្មាន restart។"""
        if not settings.tg_api_id or not settings.tg_api_hash:
            return
        async with db_session() as session:
            flag = await crud.get_setting(session, "userbot_enabled", "on")
            self._global_stopped = flag.strip().lower() != "on"
            if self._global_stopped:
                desired: dict[int, Any] = {}
            else:
                accounts = await crud.list_connectable_accounts(session)
                desired = {account.id: account for account in accounts}
        for account_id in [a for a in self._clients if a not in desired]:
            await self.stop_client(account_id)
        for account_id, account in desired.items():
            if account_id not in self._clients:
                await self.start_client(account)

    async def start_client(self, account) -> bool:
        if account.id in self._clients:
            return True
        try:
            session = session_store.load_session(account.session_encrypted)
        except session_store.SessionCryptoError as exc:
            async with db_session() as db:
                await crud.set_account_status(db, account.id, AccountStatus.OFFLINE, str(exc))
            await self.notify(f"🔐 គណនី {account.phone} ភ្ជាប់មិនបាន — {exc}")
            return False

        client = make_client(account.id, session, getattr(account, "device_index", None))
        try:
            await client.connect()
            if not await client.is_user_authorized():
                raise RuntimeError("session មិន authorized — ចុះឈ្មោះឡើងវិញតាម /addaccount ក្នុង Admin Bot")
            me = await client.get_me()
        except Exception as exc:  # noqa: BLE001
            name = type(exc).__name__
            banned = name in ("Unauthorized", "AuthKeyUnregisteredError", "SessionRevokedError")
            status = AccountStatus.BANNED if banned else AccountStatus.OFFLINE
            async with db_session() as db:
                await crud.set_account_status(db, account.id, status, describe_error(exc))
            await safe_disconnect(client)
            await self.notify(
                f"🔴 គណនី {account.phone} ភ្ជាប់មិនបាន ({name}{' — session ត្រូវចុះឈ្មោះឡើងវិញ' if banned else ''})"
            )
            return False

        async with db_session() as db:
            await crud.record_account_identity(
                db,
                account.id,
                telegram_user_id=me.id,
                username=me.username or "",
                display_name=" ".join(filter(None, (me.first_name, me.last_name))),
            )
            await crud.touch_health(db, account.id, status=AccountStatus.ACTIVE)

        sender = TelethonSender(client)
        outbox = Outbox(account.id, sender, notify=self.notify)
        catalog = Catalog(account.id, outbox=outbox, notify=self.notify, is_staff=Seller._is_staff)
        seller = Seller(account.id, client=client, outbox=outbox, notify=self.notify, catalog=catalog)
        self._sellers[account.id] = seller
        Controls(account.id, client=client, manager=self)
        client.add_event_handler(seller.on_incoming, events.NewMessage(incoming=True))
        client.add_event_handler(catalog.on_callback, events.CallbackQuery(pattern="^ub:"))
        await seller.start()
        outbox.start()

        self._clients[account.id] = client
        self._outboxes[account.id] = outbox
        log.info("ភ្ជាប់គណនី %s (#%d) ជា %s", account.phone, account.id, me.username or me.phone or me.id)
        return True

    async def stop_client(self, account_id: int) -> None:
        seller = self._sellers.pop(account_id, None)
        outbox = self._outboxes.pop(account_id, None)
        client = self._clients.pop(account_id, None)
        if seller is not None:
            await seller.stop()
        if outbox is not None:
            await outbox.stop()
        if client is not None:
            await safe_disconnect(client)
        async with db_session() as db:
            await crud.touch_health(db, account_id, status="offline")
        log.info("បិទគណនី #%s", account_id)

    async def restart_client(self, account_id: int) -> bool:
        await self.stop_client(account_id)
        async with db_session() as db:
            account = await crud.get_account(db, account_id)
        if account is None:
            raise ManagerError(f"រកមិនឃើញគណនី #{account_id}")
        return await self.start_client(account)

    # ---------- ការផ្ញើចេញ (sticky path តែមួយ) ----------
    def outbox_for(self, account_id: int) -> Outbox:
        outbox = self._outboxes.get(account_id)
        if outbox is None:
            raise ManagerError(f"គណនី #{account_id} មិន active — ការផ្ញើត្រូវបានបដិសេធ (មិនប្តូរទៅគណនីផ្សេងទេ)")
        return outbox

    async def send_message(
        self,
        account_id: int,
        customer_id: int,
        text: str,
        *,
        access_hash: int | None = None,
        priority: int = PRIORITY_REPLY,
        kind: str = "ai_reply",
        file_path: str | None = None,
        order_id: int | None = None,
    ) -> None:
        """Owner-initiated outbound ក៏ឆ្លងកាត់ outbox របស់គណនី sticky ដូចគ្នា —
        រាប់ចូល budget, គោរព FloodWait, មិនលោតជាន់ AI ឡើយ។"""
        self.outbox_for(account_id).enqueue(
            OutboxItem(
                priority=priority,
                seq=0,
                kind=kind,
                peer=PeerRef(customer_id, access_hash),
                text=text,
                file_path=file_path,
                order_id=order_id,
            )
        )

    # ---------- បញ្ជា global (controls) ----------
    @property
    def global_stopped(self) -> bool:
        return self._global_stopped

    async def global_stop(self) -> None:
        self._global_stopped = True
        async with db_session() as db:
            await crud.set_setting(db, "userbot_enabled", "off")
        for account_id in list(self._clients):
            await self.stop_client(account_id)

    async def global_start(self) -> None:
        self._global_stopped = False
        async with db_session() as db:
            await crud.set_setting(db, "userbot_enabled", "on")
        await self.reconcile()

    def status(self) -> dict[str, Any]:
        return {
            "running_accounts": sorted(self._clients),
            "global_stopped": self._global_stopped,
            "started": self._started,
            "queues": {account_id: outbox.depth for account_id, outbox in self._outboxes.items()},
        }


async def safe_disconnect(client: TelegramClient) -> None:
    try:
        await client.disconnect()
    except Exception:  # noqa: BLE001
        pass


_manager: AccountManager | None = None


def get_manager(**kwargs) -> AccountManager:
    global _manager
    if _manager is None:
        _manager = AccountManager(**kwargs)
    return _manager


def current_manager() -> AccountManager | None:
    """Manager ដែលកំពុងរត់ ឬ None (មិនបង្កើតថ្មី) — chat login ប្រើដើម្បីភ្ជាប់ភ្លាម។"""
    return _manager


def reset_manager() -> None:
    """សម្រាប់តេស្តប៉ុណ្ណោះ។"""
    global _manager
    _manager = None
