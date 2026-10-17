"""What the account migration tool decided about an account's password sign-in (ADR 001 §8, NOV-113).

An account the tool never touched has no row: nothing changes for it. The only reader is the password sign-in.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nova.infra.models import AccountMigration


async def password_blocked(session: AsyncSession, user_id: uuid.UUID) -> bool:
    """Is the password sign-in closed for this account (SSO required / password disabled), break-glass accounts excepted?"""
    row = await session.scalar(select(AccountMigration).where(AccountMigration.user_id == user_id))
    return bool(row and not row.break_glass and (row.password_login_disabled or row.sso_required))
