"""Shared FastAPI dependencies.

`get_current_user` resolves the session cookie to a user, or refuses with 401.
Every operational endpoint depends on it, so authentication is wired in one
place.

There is deliberately no fallback to "the first seeded user" — silent
authentication is the kind of convenience that survives into production.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from batanat_api.db.models import User
from batanat_api.db.session import get_session

SessionDep = Annotated[AsyncSession, Depends(get_session)]

UNAUTHENTICATED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not signed in.",
    headers={"WWW-Authenticate": "Cookie"},
)


async def get_current_user(request: Request, session: SessionDep) -> User:
    """The signed-in user, from the session cookie. Raises 401 otherwise."""
    from batanat_api.auth import sessions

    user_id = await sessions.resolve(request.cookies.get(sessions.COOKIE_NAME))
    if user_id is None:
        raise UNAUTHENTICATED

    user = (
        await session.execute(select(User).where(User.id == user_id, User.is_active.is_(True)))
    ).scalar_one_or_none()
    if user is None:
        raise UNAUTHENTICATED

    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
