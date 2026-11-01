"""💾 Backup / Restore — SQLite file, រក្សាទុកក្នុង backups/ និងផ្ញើទៅម្ចាស់ជាឯកសារ។"""
from __future__ import annotations

import logging
import shutil
import sqlite3
from pathlib import Path
from urllib.parse import urlsplit

from aiogram import Bot
from aiogram.types import FSInputFile

from config import BACKUP_DIR
from config import settings
from database.session import engine
from helpers import utcnow

log = logging.getLogger("services.backup")
KEEP = 14  # រក្សា backup ចុងក្រោយ ១៤ ឯកសារ

EXPECTED_TABLES = {"products", "orders", "customers", "stock_codes", "settings", "telegram_accounts"}


def database_path() -> Path:
    path = urlsplit(settings.database_url).path
    return Path(path.lstrip("/")).resolve()


def _remove_wal_sidecars(path: Path) -> None:
    """ក្រោយ replace DB ឯកសារ `-wal` ចាស់ត្រូវតែលុបចោល បើមិនដូច្នោះទេ frame ចាស់ជាន់ទិន្នន័យថ្មី។"""
    for suffix in ("-wal", "-shm"):
        try:
            sidecar = path.with_name(path.name + suffix)
            if sidecar.exists():
                sidecar.unlink()
        except OSError as exc:
            log.warning("លុប %s មិនបាន: %s", path.name + suffix, exc)


def _copy_database(source: Path, destination: Path) -> None:
    """SQLite online backup — រាប់បញ្ចូលទាំង WAL frames ដែល process ផ្សេង (smoke scripts) សរសេរនៅ។"""
    destination.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source, timeout=5.0) as origin, sqlite3.connect(destination) as target:
        origin.backup(target)


async def create_backup(label: str = "auto") -> Path:
    """ចម្លង DB បច្ចុប្បន្នទៅ backups/app_<label>_<timestamp>.db រួចសម្អាតកំណាត់ចាស់។"""
    source = database_path()
    if not source.exists():
        raise FileNotFoundError(f"រកមិនឃើញ database នៅ {source}")
    stamp = utcnow().strftime("%Y%m%d_%H%M%S")
    destination = BACKUP_DIR / f"app_{label}_{stamp}.db"
    # បិទ pool ជាមុន ដើម្បីកុំឱ្យចម្លងឯកសារកំពុងសរសេរ (WAL/journal កំពុងបើក)
    await engine.dispose()
    _copy_database(source, destination)
    prune_backups()
    log.info("បានបង្កើត backup: %s", destination.name)
    return destination


def prune_backups() -> None:
    files = sorted(BACKUP_DIR.glob("app_*.db"), key=lambda item: item.stat().st_mtime, reverse=True)
    for stale in files[KEEP:]:
        try:
            stale.unlink()
            log.info("លុប backup ចាស់: %s", stale.name)
        except OSError as exc:
            log.warning("លុប %s មិនបាន: %s", stale.name, exc)


def validate_sqlite(path: Path) -> str | None:
    """ត្រួតពិនិត្យឯកសារដែលអ្នកប្រើ upload ចូល — ត្រឡប់ None បើយឺត, ឬមូលហេតុបដិសេធ។"""
    if not path.exists():
        return "រកមិនឃើញឯកសារ"
    if path.stat().st_size < 4096:
        return "ឯកសារតូចពេក (មិនមែន SQLite)"
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        return f"មិនអាចបើកបាន: {exc}"
    try:
        header = connection.execute("PRAGMA integrity_check").fetchone()
        if not header or header[0] != "ok":
            return "ឯកសារខូច (integrity_check បរាជ័យ)"
        names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        missing = EXPECTED_TABLES - names
        if missing:
            return "តារាងខ្វះ: " + ", ".join(sorted(missing))
    except sqlite3.Error as exc:
        return f"ឯកសារមិនមែន SQLite ត្រឹមត្រូវ: {exc}"
    finally:
        connection.close()
    return None


async def send_backup(bot: Bot, chat_id: int, path: Path) -> None:
    await bot.send_document(
        chat_id=chat_id,
        document=FSInputFile(path),
        caption=f"💾 Backup {path.name} · {path.stat().st_size // 1024} KB",
    )


async def stage_restore(payload: bytes | Path) -> Path:
    """ដាក់ឯកសារrestore ក្នុង backups/pending_restore.db (មិនជាន់ DB ទេ)។"""
    destination = BACKUP_DIR / "pending_restore.db"
    if isinstance(payload, Path):
        shutil.copy2(payload, destination)
    else:
        destination.write_bytes(payload)
    return destination


async def apply_restore(pending: Path) -> Path:
    """ជំនួស DB ដោយឯកសារrestore (សន្ចី current ទៅ backups/app_pre_restore_*.db ជាមុនសិន)។"""
    reason = validate_sqlite(pending)
    if reason:
        raise ValueError(reason)
    current = database_path()
    safety = await create_backup("pre_restore") if current.exists() else None
    await engine.dispose()
    _copy_database(pending, current)
    _remove_wal_sidecars(current)
    log.warning("បាន restore DB ពី %s (សន្ចី at %s)", pending.name, safety.name if safety else "—")
    return safety or current


async def list_backups() -> list[Path]:
    return sorted(BACKUP_DIR.glob("app_*.db"), key=lambda item: item.stat().st_mtime, reverse=True)
