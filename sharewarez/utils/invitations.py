"""Invitation token and lifecycle helpers.

Raw invitation credentials exist only long enough to build the URL delivered to
the inviter or recipient. The database stores a deterministic digest so a
database disclosure cannot be used to claim pending invitations.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone

from sqlalchemy import and_

from sharewarez.models import InviteToken


DEFAULT_INVITE_LIFETIME_DAYS = 7
MAX_INVITE_LIFETIME_DAYS = 30


def generate_invitation_credential() -> tuple[str, str]:
    raw_token = secrets.token_urlsafe(32)
    return raw_token, digest_invitation_credential(raw_token)


def digest_invitation_credential(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
    """Treat legacy timestamp-without-time-zone values as UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def invitation_is_expired(invitation: InviteToken, *, now: datetime | None = None) -> bool:
    return as_utc(invitation.expires_at) <= (now or utc_now())


def invitation_status(invitation: InviteToken, *, now: datetime | None = None) -> str:
    if invitation.used:
        return "accepted"
    if invitation.revoked_at is not None:
        return "revoked"
    if invitation_is_expired(invitation, now=now):
        return "expired"
    return "pending"


def active_invitation_clause(*, now: datetime | None = None):
    current_time = now or utc_now()
    return and_(
        InviteToken.used.is_(False),
        InviteToken.revoked_at.is_(None),
        InviteToken.expires_at > current_time,
    )
