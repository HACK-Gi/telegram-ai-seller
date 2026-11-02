"""Qoder CLI → OpenAI-compatible proxy.

Bot 走 `AI_BACKEND=openai` (ai_engine/openai_compat.py) 打到这里，这里把
`/v1/chat/completions` 请求转成一次 `qodercli -p` 调用，再把 stdout 包成 OpenAI
的 JSON 返回。

安全：prompt 通过 stdin 传入（不经过 shell，也不进 argv），并禁用所有工具，
因此客户消息无法触发文件读写或命令执行。

Run:  ./scripts/run_qoder_proxy.sh   (or)   python scripts/qoder_proxy.py
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402

logger = logging.getLogger("qoder_proxy")

BASE_DIR = Path(__file__).resolve().parent.parent
BIN = os.getenv("QODER_CLI_BIN", "qodercli").strip() or "qodercli"
# តែងតែតិចជាង AI_TIMEOUT របស់ Bot ដើម្បីកុំឱ្យ Client timeout ដំណាលគ្នា
TIMEOUT = int(os.getenv("QODER_PROXY_TIMEOUT", "80"))
MODEL_LABEL = os.getenv("OPENAI_MODEL", "qoder-cli").strip() or "qoder-cli"
QODER_MODEL = os.getenv("QODER_PROXY_MODEL", "").strip()  # empty -> CLI default
MAX_CONCURRENCY = int(os.getenv("QODER_PROXY_CONCURRENCY", "2"))
HOST = os.getenv("QODER_PROXY_HOST", "127.0.0.1")
PORT = int(os.getenv("QODER_PROXY_PORT", "3000"))

app = FastAPI(title="Qoder CLI proxy", docs_url=None, redoc_url=None)
_gate = asyncio.Semaphore(MAX_CONCURRENCY)


def _text_of(content) -> str:
    """OpenAI content may be a string or a list of parts; flatten to plain text."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            part.get("text", "") if isinstance(part, dict) else str(part) for part in content
        )
    return str(content)


def split_messages(messages: list[dict]) -> tuple[str, list[dict], str]:
    """-> (system, history, last user text). History keeps role/content only."""
    system_parts = [_text_of(m.get("content")) for m in messages if m.get("role") == "system"]
    turns = [m for m in messages if m.get("role") in ("user", "assistant")]
    if turns and turns[-1].get("role") == "user":
        last = _text_of(turns[-1].get("content"))
        turns = turns[:-1]
    else:
        last = ""
    history = [{"role": m["role"], "content": _text_of(m.get("content"))} for m in turns]
    return "\n\n".join(p for p in system_parts if p.strip()), history, last


def build_prompt(system: str, history: list[dict], user_text: str) -> str:
    """Mirror ai_engine/qoder_cli.build_transcript so both paths phrase it alike."""
    lines = [f"[ស្ថានភាព]\n{system.strip()}", "[ការសន្ទនាចុងក្រោយ]"] if system.strip() else [
        "[ការសន្ទនាចុងក្រោយ]"]
    for turn in history:
        who = "អតិថិជន" if turn["role"] == "user" else "អ្នក"
        lines.append(f"{who}: {turn['content'].strip()}")
    lines.append(f"[សារថ្មីពីអតិថិជន]\n{user_text.strip()}")
    lines.append("[តួនាទី] ចម្លើយតបខ្លីៗជាភាសាខ្មែរ តាមស្ទីលខាងលើ។ ចម្លើយតបតែអត្ថបទប៉ុណ្ណោះ។")
    return "\n\n".join(lines)


def openai_error(status: int, message: str, err_type: str = "server_error") -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"message": message, "type": err_type, "code": status}},
    )


async def call_cli(prompt: str) -> str:
    argv = [BIN, "-p", "--no-session-persistence", "--tools", "", "-o", "text"]
    if QODER_MODEL:
        argv[2:2] = ["-m", QODER_MODEL]
    process = await asyncio.create_subprocess_exec(
        *argv,
        cwd=str(BASE_DIR),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(prompt.encode("utf-8")), timeout=TIMEOUT
        )
    except asyncio.TimeoutError as exc:
        process.kill()
        raise RuntimeError(f"qodercli timed out after {TIMEOUT}s") from exc

    if process.returncode != 0:
        detail = (stderr or b"").decode("utf-8", "replace").strip()[:300]
        raise RuntimeError(f"qodercli exited {process.returncode}: {detail}")
    return stdout.decode("utf-8", "replace").strip()


@app.get("/health")
async def health() -> dict:
    return {"ok": bool(shutil.which(BIN)), "binary": BIN, "model": QODER_MODEL or "cli-default"}


@app.get("/v1/models")
async def models() -> dict:
    return {
        "object": "list",
        "data": [{"id": MODEL_LABEL, "object": "model", "owned_by": "qoder-cli"}],
    }


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return openai_error(400, "request body is not valid JSON", "invalid_request_error")

    if body.get("stream"):
        return openai_error(400, "stream is not supported by the Qoder CLI proxy",
                            "invalid_request_error")

    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        return openai_error(400, "'messages' must be a non-empty array", "invalid_request_error")

    system, history, user_text = split_messages(messages)
    if not user_text:
        return openai_error(400, "no user message found", "invalid_request_error")

    if shutil.which(BIN) is None:
        return openai_error(503, f"CLI '{BIN}' not found on PATH")

    started = time.monotonic()
    async with _gate:
        try:
            content = await call_cli(build_prompt(system, history, user_text))
        except RuntimeError as exc:
            logger.error(str(exc))
            return openai_error(502, str(exc))

    elapsed = time.monotonic() - started
    logger.info("reply in %.1fs (%d chars)", elapsed, len(content))
    if not content:
        return openai_error(502, "qodercli returned an empty reply")

    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": body.get("model") or MODEL_LABEL,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": max(1, len(user_text) // 4),
            "completion_tokens": max(1, len(content) // 4),
            "total_tokens": max(2, (len(user_text) + len(content)) // 4),
        },
    }


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception) -> JSONResponse:
    """Any unexpected crash → OpenAI-shaped 500, and never echo the prompt."""
    logger.exception("unhandled error on %s: %s", request.url.path, exc)
    return openai_error(500, f"{type(exc).__name__}: {exc}")


if __name__ == "__main__":
    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if shutil.which(BIN) is None:
        print(f"⚠️  '{BIN}' not on PATH — run ./scripts/install_qoder.sh first", file=sys.stderr)
    print(f"""🚀 Qoder Proxy running on http://{HOST}:{PORT}
   Health: http://{HOST}:{PORT}/health
   Chat:   http://{HOST}:{PORT}/v1/chat/completions""", flush=True)
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")
