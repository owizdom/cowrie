"""Shared FastAPI dependencies.

Three separate audiences, deliberately not interchangeable:

    cowriepay   an Individual using the consumer app
    admin       a Cowrie Admin, further narrowed by RBAC role
    regulator   a Regulator with read-only access

A token minted for one audience is rejected by the others, because SRS §2.3
gives each user class a different privilege set and a single "logged in" flag
would collapse that distinction.
"""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_session
from ..enums import AdminRole
from ..models import AdminUser, ApiKey, User
from ..security import decode_token, verify_secret

#: Role hierarchy from SRS §2.3.  Higher index implies every lower privilege.
ROLE_ORDER = [
    AdminRole.SUPPORT,
    AdminRole.REVIEWER,
    AdminRole.OFFICER,
    AdminRole.ENGINEER,
    AdminRole.ADMIN,
]


def _bearer(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    return authorization[7:]


def current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_session),
) -> User:
    """The signed-in CowriePay user."""
    payload = decode_token(_bearer(authorization), audience="cowriepay")
    if payload is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired session")

    user = db.get(User, payload["sub"])
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account not found")
    return user


def current_admin(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_session),
) -> AdminUser:
    """The signed-in admin console operator."""
    payload = decode_token(_bearer(authorization), audience="admin")
    if payload is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired admin session")

    admin = db.get(AdminUser, payload["sub"])
    if admin is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Admin account not found")
    return admin


def require_role(minimum: AdminRole):
    """RBAC gate - SRS §2.3.

    Returns a dependency that admits an admin only at or above `minimum`.
    Used per route rather than per router, because the console mixes read
    (Support) and destructive (Officer) operations on the same resources.
    """

    def _guard(admin: AdminUser = Depends(current_admin)) -> AdminUser:
        if ROLE_ORDER.index(admin.role) < ROLE_ORDER.index(minimum):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"This action needs the {minimum} role or higher; you are {admin.role}.",
            )
        return admin

    return _guard


def current_regulator(
    authorization: str | None = Header(default=None),
) -> dict:
    """A Regulator session.  Read-only by construction: there is no write route
    anywhere that accepts the regulator audience."""
    payload = decode_token(_bearer(authorization), audience="regulator")
    if payload is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired regulator session")
    return payload


def api_key_auth(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    db: Session = Depends(get_session),
) -> ApiKey:
    """FR 4.1 - authenticate an institutional caller by API key.

    Keys are stored hashed, so identifying one means finding the candidate by
    its public prefix and then verifying the hash.  Scanning every key and
    bcrypt-comparing each would be correct but quadratic; the prefix narrows it
    to one row before any expensive comparison.
    """
    if not x_api_key:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Missing X-API-Key header. See the developer portal for key setup.",
        )

    parts = x_api_key.split("_")
    if len(parts) < 3:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Malformed API key")

    prefix = f"{parts[0]}_{parts[1]}_{parts[2][:6]}"
    candidates = db.execute(select(ApiKey).where(ApiKey.prefix == prefix)).scalars().all()

    for candidate in candidates:
        if verify_secret(x_api_key, candidate._keyHash) and not candidate.isActive():
            # Distinguish expiry from a bad key: the fix is a rotation, not a
            # hunt for a typo.
            from ..models import utcnow as _now

            expired = candidate.expiresAt is not None and _now() >= candidate.expiresAt
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED,
                "This API key expired after 90 days. Create a replacement in the portal."
                if expired
                else "This API key has been revoked.",
            )

        if candidate.isActive() and verify_secret(x_api_key, candidate._keyHash):
            from ..models import utcnow

            candidate.lastUsedAt = utcnow()
            candidate.requestCount += 1
            db.commit()
            return candidate

    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or revoked API key")


def require_scope(scope: str):
    """FR 4.1 - keys carry scopes; a read key must not be able to move money."""

    def _guard(key: ApiKey = Depends(api_key_auth)) -> ApiKey:
        if not key.hasScope(scope):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"This API key lacks the '{scope}' scope.",
            )
        return key

    return _guard
