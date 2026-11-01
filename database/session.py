"""Async SQLite engine + session factory។"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import settings
from database.models import Base

log = logging.getLogger("db")


def _ensure_sqlite_dir(url: str) -> None:
    if "sqlite" not in url:
        return
    path = urlsplit(url).path
    if path and path not in (":memory:", "/:memory:"):
        Path(path.lstrip("/")).parent.mkdir(parents=True, exist_ok=True)


_ensure_sqlite_dir(settings.database_url)

# `timeout` របស់ sqlite3 = busy timeout (វិនាទី)។ ចាំបាច់ព្រោះ `python -m userbot.add_account`
# ដំណើរការក្នុង process ដាច់ដោយឡែក ប៉ុន្តែសរសេរចូល SQLite file តែមួយនឹង main.py។
_connect_args = {"timeout": 5.0} if "sqlite" in settings.database_url else {}

engine = create_async_engine(settings.database_url, echo=False, connect_args=_connect_args)
SessionFactory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db() -> None:
    """បង្កើតតារាងថ្មី + បន្ថែមជួងលើតារាងចាស់ + បំពេញ settings លំនាំដើម។"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if "sqlite" in settings.database_url and ":memory:" not in settings.database_url:
            # WAL នៅក្នុង header នៃ file ទានិរន្តរភាព ដូច្នេះ set ម្តងគត់គ្រប់ connection
            await conn.exec_driver_sql("PRAGMA journal_mode=WAL")

    from database import crud, migrations

    await migrations.migrate()

    async with db_session() as session:
        await crud.seed_defaults(session)


@asynccontextmanager
async def db_session():
    """Context manager សាមញ្ញ៖ commit បើជោគជ័យ, rollback បើមានកំហុស។"""
    session = SessionFactory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
