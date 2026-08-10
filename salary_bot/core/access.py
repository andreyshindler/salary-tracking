"""Who may use the bot.

Access lives in the database rather than in ``ALLOWED_USER_IDS`` because it has
to change at runtime: an admin approving someone from a Telegram button cannot
edit the ``.env`` file, and even if it could, environment variables are fixed
when the container is created and would not take effect until a recreate.

``ALLOWED_USER_IDS`` keeps one job — **bootstrapping**. Anyone listed there is
an admin, approved automatically on first contact. That solves the chicken and
egg problem of needing an admin before anyone can be approved.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import User

PENDING = "pending"
APPROVED = "approved"
DENIED = "denied"


def apply_bootstrap(s: Session, user: User, bootstrap_ids: frozenset[int]) -> None:
    """Promote an env-listed user to approved admin.

    Runs on every contact, not just creation, so adding an ID to
    ``ALLOWED_USER_IDS`` and restarting still works as an escape hatch if the
    admin ever loses access.
    """
    if user.tg_user_id not in bootstrap_ids:
        return
    if user.status != APPROVED:
        user.status = APPROVED
    if not user.is_admin:
        user.is_admin = True


def is_approved(user: User) -> bool:
    return user.status == APPROVED


def admin_ids(s: Session, bootstrap_ids: frozenset[int] = frozenset()) -> list[int]:
    """Telegram IDs to send access requests to.

    Falls back to the bootstrap list when no admin row exists yet — otherwise
    the very first request would have nowhere to go.
    """
    rows = list(
        s.execute(select(User.tg_user_id).where(User.is_admin.is_(True))).scalars()
    )
    if rows:
        return rows
    return sorted(bootstrap_ids)


def is_admin(s: Session, tg_user_id: int) -> bool:
    user = s.execute(
        select(User).where(User.tg_user_id == tg_user_id)
    ).scalar_one_or_none()
    return bool(user and user.is_admin and user.status == APPROVED)


def users_by_status(s: Session, status: str) -> list[User]:
    return list(
        s.execute(
            select(User).where(User.status == status).order_by(User.created_at)
        ).scalars()
    )


def approved_users(s: Session) -> list[User]:
    return users_by_status(s, APPROVED)


def get_by_tg_id(s: Session, tg_user_id: int) -> User | None:
    return s.execute(
        select(User).where(User.tg_user_id == tg_user_id)
    ).scalar_one_or_none()


def set_status(s: Session, tg_user_id: int, status: str) -> User | None:
    user = get_by_tg_id(s, tg_user_id)
    if user is None:
        return None
    user.status = status
    if status != APPROVED:
        # A revoked or denied account must not keep admin rights.
        user.is_admin = False
    s.flush()
    return user


def display_name(user: User) -> str:
    """Something human for the approval screen; falls back to the numeric ID."""
    parts = []
    if user.tg_first_name:
        parts.append(user.tg_first_name)
    if user.tg_username:
        parts.append(f"@{user.tg_username}")
    return " ".join(parts) if parts else str(user.tg_user_id)
