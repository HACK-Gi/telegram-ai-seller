"""តេស្ត AI Engines ទាំងអស់ (backend នីមួយៗ + Fallback Chain)។

    .venv/bin/python scripts/test_ai_engines.py

ប្រសិនបើតេស្ត `openai` បរាជ័យ ដោយសារ Proxy មិនបានរត់៖
    ./scripts/run_qoder_proxy.sh --bg
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from config import settings  # noqa: E402

PASS, FAIL, SKIP = "pass", "fail", "skip"
results: dict[str, str] = {}

SYSTEM = "អ្នកជាអ្នកលក់ដ៏រួសរាយ ឆ្លើយខ្លីជាភាសាខ្មែរ។ អាវតម្លៃ $25។"
USER_TEXT = "សួស្តី តើមានអីវ៉ាន់អ្វី?"


async def probe(name: str, factory) -> None:
    print(f"\n🧪 តេស្ត {name}...")
    engine = None
    try:
        engine = factory()
        reply = await engine.generate(system=SYSTEM, history=[], user_text=USER_TEXT)
    except Exception as exc:
        results[name] = FAIL
        print(f"❌ {name} បរាជ័យ: {type(exc).__name__}: {exc}")
        return
    finally:
        if engine is not None:
            try:
                await engine.close()
            except Exception:
                pass
    results[name] = PASS
    print(f"✅ {name} ដំណើរការ!\n   Reply: {reply[:120]}...")


def skip(name: str, why: str) -> None:
    results[name] = SKIP
    print(f"⏭️  {name}: {why}")


async def main():
    # ១. Groq
    if os.getenv("GROQ_API_KEY"):
        from ai_engine.groq import GroqEngine

        await probe("Groq", GroqEngine)
    else:
        skip("Groq", "គ្មាន GROQ_API_KEY")

    # ២. Qoder CLI (direct subprocess)
    from ai_engine.qoder_cli import QoderCLIEngine

    await probe(
        "Qoder CLI",
        lambda: QoderCLIEngine(
            binary=settings.qoder_cli_bin,
            args_template=settings.qoder_cli_args,
            timeout=settings.qoder_cli_timeout,
        ),
    )

    # ៣. OpenAI-compatible (Qoder Proxy)
    from ai_engine.openai_compat import OpenAICompatEngine

    await probe(
        "OpenAI/Proxy",
        lambda: OpenAICompatEngine(
            base_url=settings.openai_base_url,
            model=settings.openai_model,
            api_key=settings.openai_api_key,
            timeout=settings.ai_timeout,
        ),
    )

    # ៤. Mock
    from ai_engine.mock import MockEngine

    await probe("Mock", MockEngine)

    # ៥. Fallback Chain (AI_BACKEND ពិតប្រាកដក្នុង .env)
    print(f"\n🧪 តេស្ត Fallback Chain (AI_BACKEND={settings.ai_backend})...")
    from ai_engine import close_engine, get_engine

    chain = get_engine()
    try:
        reply = await chain.generate(system=SYSTEM, history=[], user_text=USER_TEXT)
        served = getattr(chain, "last_backend", chain.name)
        fell_back = getattr(chain, "fell_back", False)
        results["Fallback Chain"] = FAIL if served == "mock" else PASS
        mark = "✅" if results["Fallback Chain"] == PASS else "⚠️"
        print(f"{mark} Fallback Chain ឆ្លើយតាម backend '{served}'"
              f"{' (fell back!)' if fell_back else ''}\n   Reply: {reply[:120]}...")
        if served == "mock":
            print("   ⚠️  ចម្លើយមកពី mock — គ្រប់ backend ពិតបរាជ័យ! ពិនិត្យ Proxy/Groq។")
    except Exception as exc:
        results["Fallback Chain"] = FAIL
        print(f"❌ Fallback Chain បរាជ័យ: {exc}")
    finally:
        await close_engine()

    print("\n" + "=" * 52)
    print("📊 សេចក្តីសន្និដ្ឋាន:")
    for name, status in results.items():
        print(f"  {'✅' if status == PASS else '⚠️' if status == SKIP else '❌'} {name} [{status}]")
    print("=" * 52)
    return 1 if FAIL in results.values() else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
