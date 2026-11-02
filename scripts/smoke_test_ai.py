"""🧪 Smoke test — ជួសជុល AI ពិត (echo guard, BackendChain, fallback, few-shot)។

ប្រើ៖ python scripts/smoke_test_ai.py

គ្មានបណ្តាញទេ — backend ទាំងអស់ជា FakeEngine ក្នុង process។ ត្រួតពិនិត្យ៖
strip_echo/accept_reply, retry, fallback លំដាប់, AIAllFailed, badge ត្រឹមត្រូវ,
DEFAULT_FEW_SHOT ≥ ៦ ឧទាហរណ៍ និងរចនាសម្ព័ន្ធ get_engine chain។
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ["USE_MOCK_BOT"] = "1"
os.environ["BOT_TOKEN"] = ""
os.environ["AI_BACKEND"] = "qoder_cli"
os.environ["QODER_CLI_BIN"] = "qoder"
# កុំឱ្យរចនាសម្ព័ន្ធ chain អាស្រ័យ GROQ_API_KEY ក្នុង .env (តេស្តនេះត្រូវ offline សុទ្ធ)
os.environ["GROQ_API_KEY"] = ""
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./data/smoke_ai.db"
os.environ["OWNER_ID"] = "700000001"
os.environ["TG_API_ID"] = ""
os.environ["TG_API_HASH"] = ""

from ai_engine import base  # noqa: E402
from ai_engine.base import AIEngine, AIError  # noqa: E402
from ai_engine.chain import AIAllFailed, BackendChain, SAFE_REPLY  # noqa: E402
from config import settings  # noqa: E402

PASS = 0
FAIL = 0


def check(name: str, ok: bool) -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
    else:
        FAIL += 1
        print(f"  ❌ {name}")


class FakeEngine(AIEngine):
    def __init__(self, name: str, replies: list) -> None:
        self.name = name
        self._replies = list(replies)
        self.calls = 0

    async def generate(self, system, history, user_text) -> str:
        self.calls += 1
        item = self._replies.pop(0) if self._replies else "ចម្លើយត្រឹមត្រូវពី " + self.name
        if isinstance(item, Exception):
            raise item
        return item


Q = "code 100 prime?"


async def main() -> None:
    # ---------- ១. strip_echo / accept_reply ----------
    check("echo សុទ្ធ ត្រូវកាត់", base.strip_echo(Q, Q) == "")
    mock_fallback = f"[mock] ខ្ញុំទទួលបាន: {Q}"
    check("mock fallback ត្រូវកាត់", base.strip_echo(mock_fallback, Q) == "")
    mixed = f"{Q}\n{mock_fallback}\nខ្ញុំមាន Prime Code 100 តម្លៃ $5 បង"
    check("ខ្សែល្អត្រូវសល់", base.strip_echo(mixed, Q) == "ខ្ញុំមាន Prime Code 100 តម្លៃ $5 បង")
    with_marker = f"អតិថិជន: {Q} ត្រឡប់?"
    check("លាយបញ្ចូលគ្នា មិនមែន echo សុទ្ → នៅ", base.strip_echo(with_marker, Q) == with_marker)
    check("ទទេ → បដិសេធ", base.accept_reply("", Q) == "")
    check("ខ្លីពេក (<5) → បដិសេធ", base.accept_reply("អូ", Q) == "")
    good = "ខ្ញុំមិនទាន់យល់ច្បាស់ទេបង 😊"
    check("ចម្លើយល្អ → ទទួល", base.accept_reply(good, Q) == good)
    thai = "សូមស្វាគមន៍មកកាន់ร้านរបស់ខ្ញុំ បងចង់បានអ្វី? ចង់បាន អំពាវនាវ"
    cleaned = base.accept_reply(thai, Q)
    check("កាត់អក្សរថៃចេញ", "ร้าน" not in cleaned and "ថៃ" not in cleaned and len(cleaned) >= 5)
    check("ខ្មែរនៅសល់", "សូមស្វាគមន៍" in cleaned)

    # ---------- ២. BackendChain ----------
    first = FakeEngine("qoder_cli", ["ចម្លើយល្អពី qoder_cli បង"])
    second = FakeEngine("openai", ["ចម្លើយល្អពី openai"])
    chain = BackendChain([first, second])
    check("chain name បង្ហាញ fallback", chain.name == "qoder_cli → fallback: openai")
    reply = await chain.generate("sys", [], Q)
    check("primary ជោគជ័យ → ប្រើ primary", reply.startswith("ចម្លើយល្អពី qoder_cli"))
    check("badge: last_backend=qoder_cli", chain.last_backend == "qoder_cli" and not chain.fell_back)

    echo_then_good = FakeEngine("qoder_cli", [Q, mock_fallback, "ឥឡូវឆ្លើយត្រូវហើយបង"])
    fb = FakeEngine("openai", ["openai ជួយហើយបង"])
    chain2 = BackendChain([echo_then_good, fb])
    reply = await chain2.generate("sys", [], Q)
    check("retry ២ ដង រាលដាល echo", echo_then_good.calls == 2)
    check("echo អស់ → fallback engine 2", reply == "openai ជួយហើយបង")
    check("badge: fell_back=True", chain2.fell_back and chain2.last_backend == "openai")
    check("attempts កត់ត្រា", len(chain2.attempts) == 2 and "echo" in chain2.attempts[-1])

    err = FakeEngine("qoder_cli", [AIError("CLI បង្ហាញកំហុស (code 1)")])
    fb2 = FakeEngine("openai", ["openai នៅរក្សាបាន"])
    chain3 = BackendChain([err, fb2])
    reply = await chain3.generate("sys", [], Q)
    check("AIError → ទៅ fallback ភ្លាម (មិន retry)", err.calls == 1 and reply == "openai នៅរក្សាបាន")

    dead1 = FakeEngine("qoder_cli", [AIError("timeout")])
    dead2 = FakeEngine("openai", [AIError("connection refused")])
    chain4 = BackendChain([dead1, dead2])
    try:
        await chain4.generate("sys", [], Q)
        check("ទាំងអស់បរាជ័យ → AIAllFailed", False)
    except AIAllFailed as exc:
        check("ទាំងអស់បរាជ័យ → AIAllFailed", len(exc.attempts) == 2)
        check("AIAllFailed ជា AIError", isinstance(exc, AIError))

    # ---------- ៣. SAFE_REPLY + config ----------
    check("SAFE_REPLY ត្រឹមត្រូវ", SAFE_REPLY == "សូមរង់ចាំបន្តិច ខ្ញុំកំពុងពិនិត្យ។")
    check("settings ai_backend=qoder_cli", settings.ai_backend == "qoder_cli")
    check("args template no-session", "--no-session-persistence" in settings.qoder_cli_args)

    # ---------- ៤. get_engine chain រចនាសម្ព័ន្ ----------
    import ai_engine

    ai_engine._engine = None
    engine = ai_engine.get_engine()
    check("get_engine → BackendChain", isinstance(engine, BackendChain))
    check("chain មាន ៣ backend", len(engine._engines) == 3 and engine._engines[0].name == "qoder_cli")
    check("fallback លំដាប់ openai → mock", [e.name for e in engine._engines[1:]] == ["openai", "mock"])
    ai_engine._engine = None

    os.environ["AI_BACKEND"] = "mock"
    from ai_engine import _fallback_engines

    check("mock → គ្មាន chain (តេស្តសុទ្ធ)", _fallback_engines(FakeEngine("mock", [])) == [])
    check("openai primary → សល់តែ mock (មិនខ្វែង)",
          [e.name for e in _fallback_engines(FakeEngine("openai", []))] == ["mock"])
    del os.environ["AI_BACKEND"]

    # ---------- ៥. few-shot defaults ----------
    from admin_bot.handlers.prompt import TEST_CASES, fs_examples
    from database import crud

    check("DEFAULT_FEW_SHOT ≥ 6 ឧទាហរណ៍", fs_examples(crud.DEFAULT_FEW_SHOT) >= 6)
    check("DEFAULTS ត្រង់ few_shot", crud.DEFAULTS["few_shot"] == crud.DEFAULT_FEW_SHOT)
    check("persona មានច្បាប់សំខាន់៖", "កុំចម្លងសារអតិថិជន" in crud.DEFAULT_SYSTEM_PROMPT)
    check("persona ហាមស្លាក [ASSISTANT]", "[ASSISTANT]" in crud.DEFAULT_SYSTEM_PROMPT)

    # Userbot លក់ដោយសន្ទនាសុទ្ធ — persona/few-shot មិនត្រូវបង្រៀនឱ្យនិយាយរឿងប៊ូតុង
    button_words = ("ចុច", "ប៊ូតុង", "ប៊ូតុន", "click", "មេនុ", "menu", "ទិញឥឡូវ")
    few_shot = crud.DEFAULT_FEW_SHOT.lower()
    check(f"few-shot គ្មានពាក្យប៊ូតុង {[w for w in button_words if w in few_shot]}",
          not any(word in few_shot for word in button_words))
    # អនុញ្ញាតឱ្យមានពាក្យទាំងនេះតែក្នុងខ្សែហាម (ក្រោយ «ច្បាប់សំខាន់បំផុត») ប៉ុណ្ណោះ
    before_rules = crud.DEFAULT_SYSTEM_PROMPT.split("ច្បាប់សំខាន់បំផុត")[0].lower()
    check(f"persona (ផ្នែកណែនាំ) គ្មានពាក្យប៊ូតុង {[w for w in button_words if w in before_rules]}",
          not any(word in before_rules for word in button_words))
    check("persona មានខ្សែហាមពាក្យប៊ូតុងជាច្បាប់ទី១",
          "កុំប្រើពាក្យ" in crud.DEFAULT_SYSTEM_PROMPT and "ប៊ូតុង" in crud.DEFAULT_SYSTEM_PROMPT)
    check("TEST_CASES 5 + custom", len(TEST_CASES) == 5 and TEST_CASES[2] == Q)

    # ខ្សែ «ច្បាប់សំខាន់» ដែល compose បន្ថែមខាងចុង មិនត្រូវបង្រៀនឱ្យនិយាយរឿងប៊ូតុងទេ
    from ai_engine.prompting import compose_system_prompt

    closing = compose_system_prompt("A", "B", "C").split("ច្បាប់សំខាន់៖", 1)[-1]
    leaked = [word for word in button_words if word in closing.lower()]
    check(f"compose tail គ្មានពាក្យប៊ូតុង {leaked}", not leaked)
    check("compose tail និយាយថា ប្រព័ន្ធ ជាអ្នកផ្ញើ QR", "កុំអះអាងថាអ្នកបានផ្ញើរូបភាព" in closing)

    print(f"\n✅ smoke_test_ai: {PASS}/{PASS + FAIL}")
    if FAIL:
        sys.exit(1)


asyncio.run(main())
