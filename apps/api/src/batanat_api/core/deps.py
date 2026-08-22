"""Shared FastAPI dependencies.

**Authentication is deliberately a placeholder.** The PRD has no auth phase, and
whether this is single-user or multi-tenant is an open question in TODO.md. The
assumption being carried is single-user: `get_current_user` resolves the seeded
demo user.

Everything downstream already takes a `user_id`, so replacing this function with
a real session lookup is the whole change — no call site moves. That is the
point of putting it here now rather than threading a global user through the
code.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from batanat_api.db.models import User
from batanat_api.db.session import get_session

SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_current_user(session: SessionDep) -> User:
    """The signed-in user. Currently: the first (and only) seeded user."""
    user = (await session.execute(select(User).order_by(User.created_at))).scalars().first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No user exists yet. Run `make seed`.",
        )
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
