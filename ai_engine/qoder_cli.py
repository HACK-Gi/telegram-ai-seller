"""Backend តាម Qoder CLI (subprocess, គ្មាន API key)។

សុវត្ថិភាព៖ មិនប្រើ shell ទេ (create_subprocess_exec) ដូច្នេះអត្ថបទពីអតិថិជន
មិនអាចបញ្ចូល commandes បន្ថែមបានឡើយ។
"""
from __future__ import annotations

import asyncio
import shlex

from ai_engine.base import AIEngine, AIError, Turn, clamp
from config import BASE_DIR


def build_transcript(system: str, history: list[Turn], user_text: str) -> str:
    """CLI ទទួល prompt ជាអត្ថបទតែមួយ ដូច្នេះតម្រៀប system + ប្រវត្តិ + សារចុងក្រោយ។"""
    lines = [f"[ស្ថានភាព]\n{system.strip()}", "[ការសន្ទនាចុងក្រោយ]"]
    for turn in history:
        who = "អតិថិជន" if turn.role == "user" else "អ្នក"
        lines.append(f"{who}: {turn.content.strip()}")
    lines.append(f"[សារថ្មីពីអតិថិជន]\n{user_text.strip()}")
    lines.append('[តួនាទី] ចម្លើយតបខ្លីៗជាភាសាខ្មែរ តាមស្ទីលខាងលើ។ ចម្លើយតបតែអត្ថបទប៉ុណ្ណោះ។')
    return "\n\n".join(lines)


class QoderCLIEngine(AIEngine):
    name = "qoder_cli"

    def __init__(self, binary: str, args_template: str, timeout: int = 90) -> None:
        self.binary = binary
        self.args_template = args_template
        self.timeout = timeout

    async def generate(self, system: str, history: list[Turn], user_text: str) -> str:
        prompt = build_transcript(system, history, user_text)
        argv = [part.replace("{prompt}", prompt) for part in shlex.split(self.args_template)]
        command = [self.binary, *argv]
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=str(BASE_DIR),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise AIError(f"រកមិនឃើញ CLI '{self.binary}' — កំណត់ QODER_CLI_BIN ក្នុង .env") from exc

        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=self.timeout)
        except asyncio.TimeoutError as exc:
            process.kill()
            raise AIError(f"CLI ឈប់ឆ្លើយលើស {self.timeout}s") from exc

        if process.returncode != 0:
            detail = (stderr or b"").decode("utf-8", "replace").strip()[:300]
            raise AIError(f"CLI បង្ហាញកំហុស (code {process.returncode}): {detail}")

        reply = stdout.decode("utf-8", "replace").strip()
        if not reply:
            raise AIError("CLI ត្រឡប់ទទេ")
        return clamp(reply)
