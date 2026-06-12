from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


async def get_user_by_id(session: AsyncSession, user_id: int) -> User | None:
    result = await session.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def get_user_by_username(session: AsyncSession, username: str) -> User | None:
    result = await session.execute(select(User).where(User.username == username))
    return result.scalar_one_or_none()


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    result = await session.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def get_user_by_username_or_email(
    session: AsyncSession,
    *,
    username: str,
    email: str | None,
) -> User | None:
    conditions = [User.username == username]
    if email:
        conditions.append(User.email == email)

    result = await session.execute(select(User).where(or_(*conditions)))
    return result.scalar_one_or_none()


async def create_user(
    session: AsyncSession,
    *,
    username: str,
    email: str | None,
    hashed_password: str,
) -> User:
    user = User(username=username, email=email, hashed_password=hashed_password)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user
