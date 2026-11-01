"""Mock Telegram session — ឱ្យ Panel ដំណើរការបានដោយគ្មាន Bot token ឬបណ្តាញ។

ប្រើសម្រាប់ smoke test និង ការពិនិត្យ startup។ គ្មាន message ពិតចេញក្រៅទេ។
"""
from __future__ import annotations

import itertools
import time
from collections.abc import AsyncGenerator
from typing import Any

from aiogram.client.session.base import BaseSession
from aiogram.methods import TelegramMethod
from aiogram.types import Message


class MockSession(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.counter = itertools.count(1)
        self.sent: list[str] = []
        self.texts: list[str] = []

    async def close(self) -> None:
        return None

    async def stream_content(
        self,
        url: str,
        headers: dict[str, Any] | None = None,
        timeout: int = 30,
        chunk_size: int = 65536,
        raise_for_status: bool = True,
    ) -> AsyncGenerator[bytes, None]:  # pragma: no cover - មិនប្រើក្នុង mock
        if False:
            yield b""

    def _chat_id(self, method: TelegramMethod) -> int:
        raw = getattr(method, "chat_id", None)
        try:
            return int(raw)
        except (TypeError, ValueError):
            return 1

    def _message_payload(self, method: TelegramMethod) -> dict:
        chat_id = self._chat_id(method)
        payload: dict = {
            "message_id": next(self.counter),
            "date": int(time.time()),
            "chat": {"id": chat_id, "type": "private", "first_name": "Owner"},
            "from": {"id": 1, "is_bot": True, "first_name": "MockBot", "username": "mock_bot"},
        }
        text = getattr(method, "text", None)
        caption = getattr(method, "caption", None)
        if text:
            payload["text"] = text
        if caption:
            payload["caption"] = caption
        api = method.__api_method__
        if api in ("sendPhoto", "sendMediaGroup"):
            payload["photo"] = [
                {"file_id": "MOCK_FILE_ID", "file_unique_id": "MOCKUID", "width": 512, "height": 512, "file_size": 1024}
            ]
        if api == "sendDocument":
            payload["document"] = {"file_id": "MOCK_DOC", "file_unique_id": "MOCKUIDD", "file_size": 1024}
        return payload

    async def make_request(self, bot, method, timeout: int | None = None) -> Any:
        api = method.__api_method__
        self.sent.append(api)
        body = getattr(method, "text", None) or getattr(method, "caption", None)
        if body:
            self.texts.append(body)

        returning = method.__returning__
        if returning is bool:
            result: Any = True
        elif returning is Message:
            result = self._message_payload(method)
        elif returning is int:
            result = next(self.counter)
        else:
            # វិធីដែលមិនស្គាល់ — បង្វិល "true" ជំនួស ដើម្បីកុំឱ្យ smoke test ដួល
            self.sent.append(f"unhandled:{api}")
            result = True

        # ប្រើ deserialization ពិតរបស់ aiogram ឱ្យបានដូចករណី live តាមរួបរួម
        response = self.check_response(
            bot=bot,
            method=method,
            status_code=200,
            content=self.json_dumps({"ok": True, "result": result}),
        )
        return response.result
