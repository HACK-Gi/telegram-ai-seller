"""តេស្ត Qoder Proxy (scripts/qoder_proxy.py) តាម HTTP ពិតប្រាកដ។

រត់ Proxy មុន (background):
    ./scripts/run_qoder_proxy.sh --bg
រួច:
    .venv/bin/python scripts/test_qoder_proxy.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import aiohttp
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

BASE = os.getenv("OPENAI_BASE_URL", "http://127.0.0.1:3000/v1").rstrip("/")
ORIGIN = BASE[: -len("/v1")] if BASE.endswith("/v1") else BASE
TIMEOUT = int(os.getenv("AI_TIMEOUT", "90"))

results: dict[str, bool] = {}


def report(name: str, ok: bool, detail: str = "") -> None:
    results[name] = ok
    print(f"{'✅' if ok else '❌'} {name}" + (f"\n   {detail}" if detail else ""))


async def main() -> int:
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=TIMEOUT)) as http:
        # ១. Health
        try:
            async with http.get(f"{ORIGIN}/health") as resp:
                body = await resp.text()
                report("GET /health", resp.status == 200, f"HTTP {resp.status} {body[:200]}")
        except Exception as exc:
            report("GET /health", False, f"{type(exc).__name__}: {exc}")
            print("\n⛔ Proxy មិនឆ្លើយ — រត់: ./scripts/run_qoder_proxy.sh --bg")
            return 1

        # ២. Models
        try:
            async with http.get(f"{BASE}/models", headers={"Authorization": "Bearer x"}) as resp:
                data = await resp.json(content_type=None)
                report("GET /v1/models", resp.status == 200 and "data" in data, json.dumps(data)[:200])
        except Exception as exc:
            report("GET /v1/models", False, f"{type(exc).__name__}: {exc}")

        # ៣. Chat — ទម្រង់ OpenAI ពេញលេញ
        payload = {
            "model": os.getenv("OPENAI_MODEL", "qoder-cli"),
            "messages": [
                {"role": "system", "content": "អ្នកជាអ្នកលក់រួសរាយ ឆ្លើយខ្លីជាភាសាខ្មែរ។ អាវតម្លៃ $25។"},
                {"role": "user", "content": "សួស្តី អាវតម្លៃប៉ុន្មាន?"},
            ],
            "temperature": 0.7,
            "stream": False,
        }
        try:
            async with http.post(
                f"{BASE}/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {os.getenv('OPENAI_API_KEY', '')}"},
            ) as resp:
                data = await resp.json(content_type=None)
                content = data["choices"][0]["message"]["content"]
                ok = resp.status == 200 and bool(content.strip())
                report("POST /v1/chat/completions", ok, f"HTTP {resp.status} reply={content[:180]!r}")
        except (KeyError, IndexError, TypeError) as exc:
            report("POST /v1/chat/completions", False, f"bad shape: {exc}")
        except Exception as exc:
            report("POST /v1/chat/completions", False, f"{type(exc).__name__}: {exc}")

        # ៤. ករណីខុស → 400 មិនមែន crash
        try:
            async with http.post(f"{BASE}/chat/completions", json={"model": "x", "messages": []}) as resp:
                report("reject empty messages", resp.status == 400, f"HTTP {resp.status}")
        except Exception as exc:
            report("reject empty messages", False, f"{type(exc).__name__}: {exc}")

        # ៥. stream=true → 400 (Proxy មិនគ្របដណ្តប់ទេ)
        try:
            stream_payload = dict(payload, stream=True)
            async with http.post(f"{BASE}/chat/completions", json=stream_payload) as resp:
                report("reject stream=true", resp.status == 400, f"HTTP {resp.status}")
        except Exception as exc:
            report("reject stream=true", False, f"{type(exc).__name__}: {exc}")

    print("\n" + "=" * 52)
    failed = [name for name, ok in results.items() if not ok]
    print(f"📊 {len(results) - len(failed)}/{len(results)} ឆ្លង")
    if failed:
        print("❌ បរាជ័យ: " + ", ".join(failed))
    print("=" * 52)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
