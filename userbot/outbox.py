"""Outbox — ជួរផ្ញើមួយក្នុងមួយគណនី ជា single writer ដូច្នេះ budget មិនប្រួតគ្នា។

គ្រប់ការផ្ញើចេញ (AI តប, ការជូនដំណឹងក្រៅម៉ោង, Code ដែលម្ចាស់ approve, ping របស់ panel)
ឆ្លងកាត់ queue តែមួយ៖ រង់ចាំ human delay, បង្ហាញ typing, គោរព FloodWait និងរាប់ចូល
កម្រិត 50/h · 200/ថ្ងៃ ដូចគ្នា។ អ្វីដែលម្ចាស់ trigger ដោយខ្លួនឯង មិនដែលលោតជាន់ AI ទេ។

**Inbound only** — គ្មាន path ណាអនុញ្ញាតឱ្យផ្ញើទៅអ្នកប្រើដែលមិនដែលសរសេរមកទេ។
"""
from __future__ import annotations

import abc
import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any

from database import crud
from database.models import AccountStatus
from database.session import db_session
from helpers import utcnow
from userbot import limits, text_delay
from userbot.safety import describe_error, mask_phone

log = logging.getLogger("userbot.outbox")

PRIORITY_DELIVERY = 0
PRIORITY_REPLY = 1
PRIORITY_NOTICE = 2


@dataclass(frozen=True)
class PeerRef:
    """អតិថិជនដែល *បាន* សរសេរមកគណនីនេះ (គ្មាន peer ថ្មីត្រូវបានបង្កើតក្នុង outbox ទេ)។"""

    peer_id: int
    access_hash: int | None = None


@dataclass(order=True)
class OutboxItem:
    priority: int
    seq: int
    kind: str = field(compare=False, default=limits.KIND_AI_REPLY)
    peer: PeerRef = field(compare=False, default=None)
    text: str = field(compare=False, default="")
    file_path: str | None = field(compare=False, default=None)
    order_id: int | None = field(compare=False, default=None)
    account_id: int = field(compare=False, default=0)
    buttons: Any = field(compare=False, default=None)  # Telethon reply_keyboard_markup ឬ None
    no_log: bool = field(compare=False, default=False)  # catalog/menu សារ មិនចូល AI context ទេ


class Sender(abc.ABC):
    """ចំណុចប្រសព្វផ្ញើ — Telethon ពិត ឬ MockSender សម្រាប់តេស្ត។"""

    @abc.abstractmethod
    async def send_text(self, peer: PeerRef, text: str, buttons: Any = None) -> Any:
        """ត្រឡប់ object ដែលមាន `.id` (msg id) ឬ None។"""

    @abc.abstractmethod
    async def send_photo(self, peer: PeerRef, path: str, caption: str) -> Any:
        ...

    @abc.abstractmethod
    def typing(self, peer: PeerRef, seconds: float):
        """async context manager បង្ហាញ 'កំពុងវាយអក្សរ'។"""


class TelethonSender(Sender):
    """ឯកសារនេះប៉ុណ្ណោះក្នុង userbot ដែលប៉ះ Telethon API នៃការផ្ញើចេញ។"""

    def __init__(self, client: Any) -> None:
        self.client = client

    async def _resolve(self, peer: PeerRef):
        try:
            return await self.client.get_input_entity(peer.peer_id)
        except (ValueError, TypeError):
            # StringSession មិនរក្សា entity cache ក្រោយ restart ទេ → ប្រើ access_hash ដែលរក្សាទុក
            if peer.access_hash:
                from telethon.tl import types

                return await self.client.get_input_entity(types.PeerUser(peer.peer_id, access_hash=peer.access_hash))
            raise

    async def send_text(self, peer: PeerRef, text: str, buttons: Any = None) -> Any:
        # parse_mode=None → អត្ថបទរាវដូចមនុស្សវាយ ហើយ Markdown ខ្មែរមិនបំផ្លាញសារទេ
        kwargs = {"parse_mode": None}
        if buttons is not None:
            kwargs["buttons"] = buttons
        return await self.client.send_message(await self._resolve(peer), text, **kwargs)

    async def send_photo(self, peer: PeerRef, path: str, caption: str) -> Any:
        return await self.client.send_file(await self._resolve(peer), path, caption=caption, parse_mode=None, force_document=False)

    @asynccontextmanager
    async def typing(self, peer: PeerRef, seconds: float):
        try:
            entity = await self._resolve(peer)
        except Exception as exc:  # noqa: BLE001 — typing មិនត្រូវបំផ្លាញការផ្ញើទេ
            log.warning("typing មិនបាន: %s", describe_error(exc))
            yield None
            return
        async with self.client.action(entity, "typing", delay=min(4.0, max(1.0, seconds))):
            yield None


def flood_seconds(exc: BaseException) -> int | None:
    """FloodWaitError/SlowModeWaitError មាន `.seconds`។ ដាក់ដោយឈ្មោះ ជំនួសឱ្យ import
    telethon.errors ក្នុង worker ដើម្បីឱ្យតេស្តបង្កើត exception ក្លែងក្លាយបាន។"""
    if type(exc).__name__ in ("FloodWaitError", "SlowModeWaitError"):
        seconds = getattr(exc, "seconds", None)
        if isinstance(seconds, int) and seconds > 0:
            return seconds
    return None


class Outbox:
    def __init__(
        self,
        account_id: int,
        sender: Sender,
        *,
        notify=None,
        sleep=asyncio.sleep,
        delay_fn=text_delay.human_delay,
    ) -> None:
        self.account_id = account_id
        self.sender = sender
        self._notify = notify
        self._sleep = sleep
        self._delay = delay_fn
        self._items: list[OutboxItem] = []
        self._seq = 0
        self._wakeup = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._stopping = False

    @property
    def depth(self) -> int:
        return len(self._items)

    def enqueue(self, item: OutboxItem) -> None:
        self._seq += 1
        item.account_id = self.account_id
        if item.seq == 0:
            item.seq = self._seq
        self._items.append(item)
        self._items.sort(key=lambda entry: (entry.priority, entry.seq))
        self._wakeup.set()

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._stopping = False
            self._task = asyncio.create_task(self._run(), name=f"outbox:{self.account_id}")

    async def stop(self) -> None:
        self._stopping = True
        self._wakeup.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _emit(self, text: str) -> None:
        if self._notify is None:
            log.info(text)
            return
        try:
            await self._notify(text)
        except Exception:  # noqa: BLE001
            log.exception("ជូនដំណឹង owner មិនបាន")

    async def _run(self) -> None:
        while not self._stopping:
            if not self._items:
                self._wakeup.clear()
                try:
                    await self._wakeup.wait()
                except asyncio.CancelledError:
                    raise
                continue
            item = self._items[0]
            try:
                await self._deliver(item)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("outbox worker កំហុសសម្រាប់ %s", item.kind)
                if self._items and self._items[0] is item:
                    self._items.pop(0)  # កុំឃុំ item ដែលបរាជ័យជារៀងរហូត (fallback path)

    async def _deliver(self, item: OutboxItem) -> None:
        async with db_session() as session:
            account = await crud.get_account(session, self.account_id)
        if account is None:
            self._items.remove(item)
            return

        budget = await self._budget(account)
        if not budget.allows(item.kind):
            # item នៅខាងមុខដដែល ហើយយើងរង់ចាំដល់ slot ទំនេរ — មិនបោះបង់សារអតិថិជនទេ
            await self._notice_once(budget, account)
            until = budget.blocked_until or (utcnow() + timedelta(minutes=5))
            await self._sleep(max(0.1, (until - utcnow()).total_seconds()))
            return

        await self._delay(budget.delay, sleep=self._sleep)
        if item.file_path and not Path(item.file_path).exists():
            log.warning("ឯកសារមិនមាន %s — ប្តូរទៅផ្ញើអត្ថបទ", item.file_path)
            item = OutboxItem(
                priority=item.priority, seq=item.seq, kind=item.kind, peer=item.peer,
                text=item.text, order_id=item.order_id, buttons=item.buttons, no_log=True,
            )
        try:
            async with self.sender.typing(item.peer, text_delay.typing_seconds(item.text)):
                if item.file_path:
                    await self.sender.send_photo(item.peer, item.file_path, item.text)
                else:
                    await self.sender.send_text(item.peer, item.text, item.buttons)
        except Exception as exc:  # noqa: BLE001
            wait = flood_seconds(exc)
            if wait is None:
                raise
            until = utcnow() + timedelta(seconds=wait)
            log.warning("FloodWait គណនី %s → %ss", self.account_id, wait)
            async with db_session() as session:
                await crud.set_account_pause(session, self.account_id, until)
                await crud.set_account_status(session, self.account_id, AccountStatus.PAUSED, f"FloodWait {wait}s")
            if wait > 3600:
                await self._emit(f"🚦 គណនី #{account.id} {mask_phone(account.phone)} ជាប់ FloodWait {wait} វិនាទី — ឈប់ផ្ញើរហូតដល់ {until}")
            return

        self._items.remove(item)
        async with db_session() as session:
            # Message សរសេរ *បន្ទាប់ពី* ផ្ញើជោគជ័យ ដើម្បី derived counting ដូចការផ្ញើពិត
            if not item.no_log:  # សារ menu/catalog មិនចូល AI context ទេ (budget នៅរាប់ដដែល)
                await crud.add_message(session, item.peer.peer_id, "assistant", item.text, account_id=self.account_id)
            if item.order_id:
                await crud.mark_code_sent(session, item.order_id)
            if budget.reason in ("hour", "day"):
                await crud.set_account_pause(session, self.account_id, None)

    async def _budget(self, account):
        async with db_session() as session:
            fresh = await crud.get_account(session, account.id)
            return await limits.current_budget(session, fresh or account)

    async def _notice_once(self, budget, account) -> None:
        bucket = utcnow().strftime("%Y-%m-%dT%H") if budget.reason == "hour" else utcnow().strftime("%Y-%m-%d")
        async with db_session() as session:
            if not await crud.notice_once(session, f"budget:{self.account_id}:{budget.reason}", bucket=bucket):
                return
            await crud.set_account_status(session, self.account_id, AccountStatus.PAUSED, f"limit {budget.reason}")
        await self._emit(
            f"🪫 គណនី #{account.id} {mask_phone(account.phone)} ដល់កម្រិត ({budget.reason}) · {budget.describe()}\n"
            f"សារក្នុងជួរ {self.depth} នឹងផ្ញើបន្តនៅ {budget.blocked_until}"
        )
