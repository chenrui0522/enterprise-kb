from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity import Session


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_session_token() -> str:
    return secrets.token_urlsafe(32)


async def create_session(
    db: AsyncSession,
    *,
    user_id: str,
    ttl_hours: int,
    user_agent: str | None = None,
    ip: str | None = None,
) -> tuple[Session, str]:
    token = generate_session_token()
    now = datetime.now(timezone.utc)
    row = Session(
        user_id=user_id,
        token_hash=hash_session_token(token),
        expires_at=now + timedelta(hours=ttl_hours),
        last_seen_at=now,
        user_agent=user_agent,
        ip=ip,
    )
    db.add(row)
    await db.flush()
    return row, token


async def get_session_by_token(db: AsyncSession, token: str) -> Session | None:
    token_hash = hash_session_token(token)
    result = await db.execute(select(Session).where(Session.token_hash == token_hash))
    row = result.scalar_one_or_none()
    if row is None:
        return None
    now = datetime.now(timezone.utc)
    expires = row.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires <= now:
        await db.execute(delete(Session).where(Session.id == row.id))
        await db.flush()
        return None
    row.last_seen_at = now
    await db.flush()
    return row


async def revoke_session(db: AsyncSession, token: str) -> None:
    await db.execute(delete(Session).where(Session.token_hash == hash_session_token(token)))
    await db.flush()


async def revoke_user_sessions(db: AsyncSession, user_id: str) -> None:
    await db.execute(delete(Session).where(Session.user_id == user_id))
    await db.flush()
