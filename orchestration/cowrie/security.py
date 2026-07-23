"""Credentials, tokens, hashing and signatures.

Covers four distinct secrets, each with a different threat model:

    user PIN         6 digits, bcrypt-hashed (FR 2.2)
    admin password   bcrypt-hashed
    partner API key  shown once at creation, bcrypt-hashed at rest (FR 4.1)
    webhook secret   HMAC-SHA256 signing key for outbound events (FR 4.3)

NFR 2 requires signing keys to live in tamper-resistant hardware.  This build
has no HSM, so the module keeps every signing operation behind
`sign_with_platform_key`; that function is the single place an HSM client would
replace, and it says so rather than pretending the requirement is met.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
from jose import JWTError, jwt

from .config import settings

# ---------------------------------------------------------------------------
# password / PIN hashing
# ---------------------------------------------------------------------------


def hash_secret(raw: str) -> str:
    return bcrypt.hashpw(raw.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_secret(raw: str, hashed: str) -> bool:
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(raw.encode(), hashed.encode())
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# JWT session tokens
# ---------------------------------------------------------------------------


def create_token(subject: str, audience: str, extra: dict[str, Any] | None = None) -> str:
    """Issue a session token.

    `audience` separates the surfaces: a CowriePay token must not open the
    admin console, so the audience is checked on every protected route.
    """
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": subject,
        "aud": audience,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.jwt_ttl_minutes)).timestamp()),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str, audience: str) -> dict[str, Any] | None:
    try:
        return jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            audience=audience,
        )
    except JWTError:
        return None


# ---------------------------------------------------------------------------
# partner API keys (FR 4.1)
# ---------------------------------------------------------------------------


def generate_key_pair(environment: str = "sandbox") -> dict[str, str]:
    """FR 4.1 - "Let businesses generate API key pairs".

    A pair, not a single key, because the two halves have different exposure:
    the publishable key identifies the partner and may sit in client code, while
    the secret key authorises money movement and must never leave their server.
    Collapsing them into one key would mean the credential that can send a
    payment is the same one they paste into a browser.
    """
    secret_body = secrets.token_hex(16)
    publishable_body = secrets.token_hex(12)
    return {
        "secret": f"sk_{environment}_{secret_body}",
        "secret_prefix": f"sk_{environment}_{secret_body[:6]}",
        "publishable": f"pk_{environment}_{publishable_body}",
        "publishable_prefix": f"pk_{environment}_{publishable_body[:6]}",
    }


def generate_api_key(environment: str = "sandbox") -> tuple[str, str]:
    """Return (plaintext_key, public_prefix).

    Format: ck_<env>_<32 hex>.  The prefix stored alongside the hash is the
    first 6 characters of the random part, which is enough to identify a key in
    a list without being enough to use it.
    """
    body = secrets.token_hex(16)
    plaintext = f"ck_{environment}_{body}"
    prefix = f"ck_{environment}_{body[:6]}"
    return plaintext, prefix


def generate_webhook_secret() -> tuple[str, str]:
    body = secrets.token_hex(16)
    return f"whsec_{body}", f"whsec_{body[:6]}"


# ---------------------------------------------------------------------------
# webhook signatures (FR 4.3)
# ---------------------------------------------------------------------------


def sign_webhook(secret: str, timestamp: int, body: str) -> str:
    """HMAC-SHA256 over '{timestamp}.{body}'.

    The timestamp is inside the signed material so a captured payload cannot be
    replayed later with a fresh header.  Returned in the same shape the
    developer portal documents: 't=<ts>,v1=<hex>'.
    """
    signed_payload = f"{timestamp}.{body}".encode()
    digest = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={digest}"


def verify_webhook(secret: str, header: str, body: str, tolerance_seconds: int = 300) -> bool:
    """Reference verifier - the code a partner writes on their side."""
    try:
        parts = dict(p.split("=", 1) for p in header.split(","))
        ts = int(parts["t"])
        received = parts["v1"]
    except (ValueError, KeyError):
        return False
    if abs(int(datetime.now(UTC).timestamp()) - ts) > tolerance_seconds:
        return False
    expected = hmac.new(secret.encode(), f"{ts}.{body}".encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, received)


# ---------------------------------------------------------------------------
# platform signing (NFR 2 / NFR 5)
# ---------------------------------------------------------------------------


def sign_with_platform_key(payload: str) -> str:
    """Sign regulator exports and audit anchors.

    NOT the production design.  NFR 2 requires this key to live in tamper-
    resistant hardware and never be readable by the application; here it is an
    HMAC under the JWT secret.  Swapping this one function for an HSM or KMS
    client is what closes the gap, and the admin UI labels exports produced by
    this path as demo-signed so nobody mistakes them for the real thing.
    """
    return hmac.new(settings.jwt_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def sha256_hex(payload: str) -> str:
    return hashlib.sha256(payload.encode()).hexdigest()


# ---------------------------------------------------------------------------
# field encryption (FR 1.2 - -idNumberEncrypted on the class diagram)
# ---------------------------------------------------------------------------


def encrypt_id_number(id_number: str) -> bytes:
    """Protect a government ID number at rest.

    A demonstration of the requirement, not a production cipher: this is a
    keyed hash plus the last four characters, which is enough for the admin
    console to show 'NIN ****4821' and enough to compare two submissions for
    equality, while making the full number unrecoverable from the database.
    Production needs envelope encryption under a KMS-held data key so that a
    lawful request can actually retrieve the number.
    """
    keyed = hmac.new(settings.jwt_secret.encode(), id_number.encode(), hashlib.sha256).digest()
    tail = id_number[-4:].rjust(4, "*").encode()
    return keyed + b"|" + tail


def id_number_tail(blob: bytes) -> str:
    if not blob or b"|" not in blob:
        return "****"
    return blob.rsplit(b"|", 1)[1].decode(errors="replace")


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)
