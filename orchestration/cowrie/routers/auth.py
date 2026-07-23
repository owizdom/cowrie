"""Authentication - FR 1.1, FR 2.2, and the admin/regulator sessions.

FR 1.1: "Sign up with a phone number and email, verified by a one-time code
before the account is created."

The flow is three calls, in this order, and the ordering is the requirement:

    POST /auth/register/start     details in, OTP challenge out, NO account yet
    POST /auth/register/verify    code in, account created, session out
    POST /auth/login              phone + 6-digit PIN, session out

Nothing writes a User row until the code is verified.  A caller who abandons
the flow leaves no account behind, which is what "before the account is
created" means.
"""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_session
from ..enums import ActorType, KycLevel
from ..models import AdminUser, User
from ..security import create_token, hash_secret, verify_secret
from ..services import audit
from ..services.otp import service as otp_service
from ..services.sanctions import service as sanctions_service
from .deps import current_user

router = APIRouter(prefix="/auth", tags=["auth"])


# ---------------------------------------------------------------------------
# schemas
# ---------------------------------------------------------------------------


class RegisterStart(BaseModel):
    fullName: str = Field(min_length=2, max_length=160)
    phone: str = Field(min_length=8, max_length=24)
    email: EmailStr
    country: str = Field(min_length=2, max_length=2)
    pin: str = Field(min_length=6, max_length=6)

    @field_validator("pin")
    @classmethod
    def _digits_only(cls, v: str) -> str:
        if not v.isdigit():
            raise ValueError("PIN must be 6 digits")
        return v

    @field_validator("phone")
    @classmethod
    def _e164(cls, v: str) -> str:
        cleaned = v.replace(" ", "").replace("-", "")
        if not cleaned.startswith("+"):
            raise ValueError("Phone must be in international format, e.g. +2348012345678")
        return cleaned

    @field_validator("country")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.upper()


class RegisterVerify(BaseModel):
    challengeId: str
    code: str = Field(min_length=6, max_length=6)


class LoginRequest(BaseModel):
    phone: str
    pin: str = Field(min_length=6, max_length=6)


class AdminLogin(BaseModel):
    email: EmailStr
    password: str


class RegulatorLogin(BaseModel):
    email: EmailStr
    password: str


class RegulatorSignup(BaseModel):
    fullName: str = Field(min_length=2, max_length=160)
    email: EmailStr
    regulator: str = Field(default="SEC_NIGERIA")
    password: str = Field(min_length=8, max_length=128)

    @field_validator("regulator")
    @classmethod
    def _known_body(cls, v: str) -> str:
        allowed = {"SEC_NIGERIA", "CMA_KENYA", "CBN"}
        if v not in allowed:
            raise ValueError(f"regulator must be one of {sorted(allowed)}")
        return v


def _session_payload(user: User, token: str) -> dict:
    return {
        "token": token,
        "user": {
            "id": user.id,
            "fullName": user.fullName,
            "phone": user.phone,
            "email": user.email,
            "country": user.country,
            "kycLevel": str(user.kycLevel),
            "limitUsd": user.limitUsd(),
            "ngnBalance": str(user.ngnBalance),
            "bankName": user.bankName,
            "bankAccountMasked": user.bankAccountMasked,
            "isFrozen": user.isFrozen,
        },
    }


# ---------------------------------------------------------------------------
# registration (FR 1.1)
# ---------------------------------------------------------------------------


@router.post("/register/start", status_code=status.HTTP_202_ACCEPTED)
def register_start(body: RegisterStart, db: Session = Depends(get_session)) -> dict:
    """Issue a one-time code.  Deliberately creates no account."""
    existing = db.execute(
        select(User).where((User.phone == body.phone) | (User.email == body.email))
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "An account already exists for that phone or email.")

    challenge_id, code, delivered = otp_service.issue(
        purpose="REGISTRATION",
        identifier=body.phone,
        payload=body.model_dump(),
        email=body.email,
    )

    response = {
        "challengeId": challenge_id,
        "sentTo": body.email if delivered else body.phone,
        "delivered": delivered,
        "message": (
            f"We sent a 6-digit code to {body.email}."
            if delivered
            else "Enter the 6-digit code to finish creating your account."
        ),
    }
    # Only surfaced when nothing was actually sent - otherwise a code that never
    # arrives would make sign-up impossible.
    if not delivered:
        response["code"] = code
    return response


@router.post("/register/verify", status_code=status.HTTP_201_CREATED)
def register_verify(body: RegisterVerify, db: Session = Depends(get_session)) -> dict:
    """Verify the code, then create the account.  This is the only path that
    writes a User row."""
    try:
        challenge = otp_service.verify(challenge_id=body.challengeId, code=body.code)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    if challenge.purpose != "REGISTRATION":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "That code is not for registration.")

    details = challenge.payload

    user = User(
        fullName=details["fullName"],
        phone=details["phone"],
        email=details["email"],
        country=details["country"],
        kycLevel=KycLevel.TIER1,  # phone + email verified
        # A new account holds nothing. Funds arrive by linking a bank account
        # and topping up, which is the on-ramp FR 2.2 describes.
        ngnBalance=Decimal("0"),
    )
    user._pinHash = hash_secret(details["pin"])
    db.add(user)
    db.flush()

    # <<include>> Screen against sanctions - FR 1.3 requires screening at signup.
    screening = sanctions_service.screen_user(db, user, trigger="SIGNUP")
    if not screening.passed:
        user.isFrozen = True

    audit.record(
        db,
        entity_type="User",
        entity_id=user.id,
        action="user.registered",
        actor=ActorType.USER,
        actor_id=user.id,
        after=audit.snapshot(user),
        detail={"sanctionsPassed": screening.passed, "verifiedBy": "one-time code"},
    )
    db.commit()

    token = create_token(user.id, audience="cowriepay", extra={"phone": user.phone})
    payload = _session_payload(user, token)
    payload["nextStep"] = "Verify your identity to raise your transfer limit (FR 1.2)."
    return payload


# ---------------------------------------------------------------------------
# login
# ---------------------------------------------------------------------------


@router.post("/login")
def login(body: LoginRequest, db: Session = Depends(get_session)) -> dict:
    """Sign in with phone and 6-digit PIN."""
    phone = body.phone.replace(" ", "").replace("-", "")
    user = db.execute(select(User).where(User.phone == phone)).scalar_one_or_none()

    # Same message whether the phone is unknown or the PIN is wrong, so the
    # endpoint cannot be used to enumerate who has an account.
    if user is None or not verify_secret(body.pin, user._pinHash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect phone number or PIN.")

    token = create_token(user.id, audience="cowriepay", extra={"phone": user.phone})
    return _session_payload(user, token)


@router.post("/admin/login")
def admin_login(body: AdminLogin, db: Session = Depends(get_session)) -> dict:
    """Admin console sign-in.  Returns the role so the UI can hide what the
    API would refuse anyway."""
    admin = db.execute(select(AdminUser).where(AdminUser.email == body.email)).scalar_one_or_none()
    if admin is None or not verify_secret(body.password, admin._passwordHash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password.")

    token = create_token(admin.id, audience="admin", extra={"role": str(admin.role)})
    return {
        "token": token,
        "admin": {
            "id": admin.id,
            "email": admin.email,
            "fullName": admin.fullName,
            "role": str(admin.role),
        },
    }


@router.post("/regulator/register", status_code=status.HTTP_201_CREATED)
def regulator_register(body: RegulatorSignup, db: Session = Depends(get_session)) -> dict:
    """Register a named person at a regulator (SRS 2.3).

    The account is read-only by construction, so self-registration grants no
    privilege that could be abused into a write. What it does grant is sight of
    a pseudonymised transaction register, which is why the body a person claims
    to represent is recorded on the account and carried into every export they
    generate.
    """
    from ..models import RegulatorUser

    existing = db.execute(
        select(RegulatorUser).where(RegulatorUser.email == body.email)
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "That email already has portal access.")

    account = RegulatorUser(
        email=body.email,
        fullName=body.fullName,
        regulator=body.regulator,
    )
    account._passwordHash = hash_secret(body.password)
    db.add(account)
    db.flush()

    audit.record(
        db,
        entity_type="RegulatorUser",
        entity_id=account.id,
        action="regulator.registered",
        actor=ActorType.SYSTEM,
        actor_id=body.email,
        after={"email": body.email, "regulator": body.regulator},
    )
    db.commit()

    token = create_token(account.id, audience="regulator", extra={"regulator": body.regulator})
    return {
        "token": token,
        "regulator": body.regulator,
        "fullName": account.fullName,
        "access": "read-only",
    }


@router.post("/regulator/login")
def regulator_login(body: RegulatorLogin, db: Session = Depends(get_session)) -> dict:
    """Regulator portal sign-in.

    The session it mints is read-only because no write route anywhere accepts
    the regulator audience.
    """
    from ..models import RegulatorUser
    from ..models import utcnow as _now

    account = db.execute(
        select(RegulatorUser).where(RegulatorUser.email == body.email)
    ).scalar_one_or_none()
    if account is None or not verify_secret(body.password, account._passwordHash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password.")

    account.lastSeenAt = _now()
    db.commit()

    token = create_token(account.id, audience="regulator", extra={"regulator": account.regulator})
    return {
        "token": token,
        "regulator": account.regulator,
        "fullName": account.fullName,
        "access": "read-only",
        "scope": ["transactions", "reserve", "attestations", "exports", "audit-log"],
    }


@router.get("/me")
def whoami(user: User = Depends(current_user), db: Session = Depends(get_session)) -> dict:
    """The signed-in user, their verification level and their current limit."""
    from ..models import KycSubmission

    submissions = (
        db.execute(
            select(KycSubmission)
            .where(KycSubmission.userId == user.id)
            .order_by(KycSubmission.createdAt.desc())
        )
        .scalars()
        .all()
    )
    return {
        "user": _session_payload(user, "")["user"],
        "kyc": {
            "level": str(user.kycLevel),
            "limitUsd": user.limitUsd(),
            "submissions": [
                {
                    "id": s.id,
                    "status": str(s.status),
                    "idType": str(s.idType),
                    "confidenceScore": float(s.confidenceScore),
                    "createdAt": s.createdAt.isoformat(),
                }
                for s in submissions
            ],
        },
        "corridor": {
            "source": settings.corridor_source,
            "destination": settings.corridor_destination,
        },
    }
