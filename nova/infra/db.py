"""Async SQLAlchemy engine and sessions."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from sqlalchemy import JSON, MetaData
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from nova.config import get_settings

JSONType = JSON().with_variant(JSONB(), "postgresql")

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)
    type_annotation_map = {dict: JSONType, list: JSONType}


def utcnow() -> datetime:
    return datetime.now(UTC)


def aware(value: datetime | None) -> datetime | None:
    """SQLite returns naive datetimes; NOVA stores UTC everywhere."""
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def new_id() -> uuid.UUID:
    return uuid.uuid4()


_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def configure(url: str | None = None, *, null_pool: bool = False) -> None:
    """(Re)configure the engine — workers use ``null_pool`` (one event loop per task)."""
    global _engine, _sessionmaker
    url = url or get_settings().database_url
    kwargs: dict = {"pool_pre_ping": True}
    if null_pool or url.startswith("sqlite"):
        kwargs = {"poolclass": NullPool}
    _engine = create_async_engine(url, **kwargs)
    _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)


def engine() -> AsyncEngine:
    if _engine is None:
        configure()
    assert _engine is not None
    return _engine


def sessionmaker() -> async_sessionmaker[AsyncSession]:
    if _sessionmaker is None:
        configure()
    assert _sessionmaker is not None
    return _sessionmaker


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    async with sessionmaker()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_session() -> AsyncIterator[AsyncSession]:
    async with sessionmaker()() as session:
        yield session
