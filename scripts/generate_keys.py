"""បង្កើត `SESSION_FERNET_KEY` សម្រាប់ `.env` — key សម្រាប់ encrypt session របស់ Telegram។

    python scripts/generate_keys.py            # បង្ហាញ key ឱ្យ copy ដោយខ្លួនឯង
    python scripts/generate_keys.py --write    # សរសេរចូល .env ដោយស្វ័យប្រវត្តិ

`--write` មិនសរសេរជំនួស key ដែលមានស្រាប់ទេ (មូលហេតុ៖ key ថ្មីធ្វើឱ្យ session
ដែល encrypt រួច decrypt មិនបាន → គណនីទាំងអស់ត្រូវ login ឡើងវិញ)។
បើចង់ប្តូរពិតៗ ត្រូវប្រើ `--force`។
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from cryptography.fernet import Fernet

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
ENV_EXAMPLE = ROOT / ".env.example"

OTHER_KEYS = (
    ("TG_API_ID", "my.telegram.org → API development tools → App api_id"),
    ("TG_API_HASH", "my.telegram.org → API development tools → App api_hash"),
)


def mask(key: str) -> str:
    return f"{key[:6]}…{key[-4:]} (len={len(key)})" if len(key) > 12 else "***"


def current_key(text: str) -> str:
    # `[^\S\n]*` = ចន្លោះប៉ុណ្ណោះ — `\s` ធម្មតាឆ្លងកាត់ newline ហើយចាប់បន្ទាត់បន្ទាប់ខុស
    match = re.search(r"^SESSION_FERNET_KEY[^\S\n]*=[^\S\n]*(.*)$", text, re.MULTILINE)
    return match.group(1).strip().strip('"').strip("'") if match else ""


def write_key(key: str, *, force: bool) -> int:
    if not ENV_PATH.exists():
        print(f"❌ រកមិនឃើញ {ENV_PATH.relative_to(ROOT)} — copy ពី .env.example សិន", file=sys.stderr)
        return 1
    text = ENV_PATH.read_text(encoding="utf-8")
    existing = current_key(text)
    if existing and not force:
        print(
            "⚠️  .env មាន SESSION_FERNET_KEY ស្រាប់ — មិនសរសេរជំនួសទេ។\n"
            "    key ថ្មី = session ចាស់ decrypt មិនបាន (គណនីត្រូវ login ឡើងវិញ)។\n"
            "    បើប្តូរពិតៗ៖ python scripts/generate_keys.py --write --force",
            file=sys.stderr,
        )
        return 1

    line = f"SESSION_FERNET_KEY={key}"
    if re.search(r"^SESSION_FERNET_KEY[^\S\n]*=", text, re.MULTILINE):
        text = re.sub(
            r"^SESSION_FERNET_KEY[^\S\n]*=.*$", line, text, count=1, flags=re.MULTILINE
        )
    else:
        text = text.rstrip("\n") + f"\n\n# Fernet key សម្រាប់ encrypt session (scripts/generate_keys.py)\n{line}\n"
    ENV_PATH.write_text(text, encoding="utf-8")
    try:
        ENV_PATH.chmod(0o600)  # .env មាន secret — មិនឱ្យអ្នកផ្សេងអាន
    except OSError:
        pass
    print(f"✅ បានសរសេរ SESSION_FERNET_KEY ចូល .env — {mask(key)} (ឯកសារបានកំណត់សិទ្ធិ 600)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="បង្កើត SESSION_FERNET_KEY")
    parser.add_argument("--write", action="store_true", help="សរសេរចូល .env ដោយស្វ័យប្រវត្តិ")
    parser.add_argument("--force", action="store_true", help="សរសេរជំនួស key ចាស់ (បំផ្លាញ session ចាស់)")
    args = parser.parse_args()

    key = Fernet.generate_key().decode()
    if args.write:
        return write_key(key, force=args.force)

    print("🔑 SESSION_FERNET_KEY ថ្មី៖\n")
    print(f"    {key}\n")
    print("ដាក់ចូល .env (ឬរត់ `python scripts/generate_keys.py --write` ដោយស្វ័យប្រវត្តិ)៖\n")
    print(f"    SESSION_FERNET_KEY={key}\n")
    if not ENV_EXAMPLE.exists():
        print(f"(មិនមាន {ENV_EXAMPLE.name})", file=sys.stderr)
    print("បន្ទាប់មក៖ userbot ត្រូវការពីរ key ទៀតពី my.telegram.org ៖")
    for name, hint in OTHER_KEYS:
        print(f"    {name}=   ← {hint}")
    print("\nរួច restart៖ python main.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
