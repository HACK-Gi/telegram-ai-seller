"""Debounce 3 វិនាទី ក្នុងមួយ (គណនី, អតិថិជន) — បង្រួលសារបន្តបន្ទាប់ជា 1 វគ្គ។

អតិថិជនម្នាក់ច្រើនសរសេរ 3 សារតាមក្រោយគ្នា («សួស្តី», «មាន HTML 5GB ទេ», «តម្លៃប៉ុន្មាន»)។
ការតប 3 ដងដាច់ដោយឡែកមើលទៅដូចជា robot ហើយចំណាយ budget 3 ដង។ Worker មួយក្នុង
មួយ conversation រក្សាលំដាប់សារ និងធ្វើតែ 1 AI call ប៉ុណ្ណោះ។
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

log = logging.getLogger("userbot.coalescer")


@dataclass(frozen=True, eq=True)
class ConvKey:
    account_id: int
    peer_id: int


class Coalescer:
    def __init__(
        self,
        flush: Callable[[ConvKey, tuple], Awaitable[None]],
        *,
        window: float = 3.0,
        idle_exit: float = 120.0,
    ) -> None:
        self._flush = flush
        self.window = window
        self.idle_exit = idle_exit
        self._queues: dict[ConvKey, asyncio.Queue] = {}
        self._workers: dict[ConvKey, asyncio.Task] = {}
        self._locks: dict[ConvKey, asyncio.Lock] = {}

    def _queue(self, key: ConvKey) -> asyncio.Queue:
        queue = self._queues.get(key)
        if queue is None:
            queue = asyncio.Queue()
            self._queues[key] = queue
            self._locks[key] = asyncio.Lock()
        return queue

    async def submit(self, key: ConvKey, item) -> None:
        queue = self._queue(key)
        await queue.put(item)
        worker = self._workers.get(key)
        if worker is None or worker.done():
            self._workers[key] = asyncio.create_task(self._run(key), name=f"coalesce:{key.account_id}:{key.peer_id}")

    async def _run(self, key: ConvKey) -> None:
        queue = self._queues[key]
        try:
            while True:
                try:
                    first = await asyncio.wait_for(queue.get(), timeout=self.idle_exit)
                except asyncio.TimeoutError:
                    return  # conversation ស្ងាត់ → បិទ worker កុំឱ្យលេច task
                batch = [first]
                while True:
                    try:
                        batch.append(await asyncio.wait_for(queue.get(), timeout=self.window))
                    except asyncio.TimeoutError:
                        break
                async with self._locks[key]:
                    try:
                        await self._flush(key, tuple(batch))
                    except Exception:  # noqa: BLE001 — កំហុសតែមួយមិនត្រូវសម្លាប់ worker
                        log.exception("កំហុសក្នុង conversation %s", key)
        except asyncio.CancelledError:
            raise
        finally:
            self._workers.pop(key, None)

    async def pending(self, key: ConvKey) -> int:
        queue = self._queues.get(key)
        return queue.qsize() if queue else 0

    async def drain(self) -> None:
        """ពេល shutdown — បញ្ចេញ batch ដែលកំពុងរង់ចាំ កុំឱ្យបាត់សារអតិថិជន។"""
        for key, worker in list(self._workers.items()):
            worker.cancel()
            try:
                await worker
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            queue = self._queues.get(key)
            if not queue:
                continue
            batch = []
            while not queue.empty():
                batch.append(queue.get_nowait())
            if batch:
                try:
                    await self._flush(key, tuple(batch))
                except Exception:  # noqa: BLE001
                    log.exception("drain បរាជ័យសម្រាប់ %s", key)
        self._queues.clear()
        self._locks.clear()
        self._workers.clear()
