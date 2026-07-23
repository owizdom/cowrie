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
    accessCode: str
    regulator: str = "SEC_NIGERIA"


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

    challenge_id, code = otp_service.issue(
        purpose="REGISTRATION",
        identifier=body.phone,
        payload=body.model_dump(),
    )

    return {
        "challengeId": challenge_id,
        "sentTo": body.phone,
        "message": "Enter the 6-digit code to finish creating your account.",
        # No SMS provider is configured, so the code is returned rather than
        # sent.  See services/otp.py.
        "demoCode": code,
        "demoNote": "Returned only because this build has no SMS provider wired.",
    }


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
        ngnBalance=Decimal("750000.00"),  # seeded demo balance
        bankName="Guaranty Trust Bank",
        bankAccountMasked="******4417",
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


@router.post("/regulator/login")
def regulator_login(body: RegulatorLogin) -> dict:
    """Regulator portal sign-in.

    A shared access code rather than per-person accounts, which matches how the
    portal is described in SRS §2.3: quarterly or on-demand read-only access for
    a named regulator, not a staffed console.  The code is configuration, and
    the session it mints is read-only because no write route accepts the
    regulator audience.
    """
    valid = {"SEC_NIGERIA": "sec-ng-demo", "CMA_KENYA": "cma-ke-demo", "CBN": "cbn-demo"}
    if valid.get(body.regulator) != body.accessCode:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid access code for that regulator.")

    token = create_token(body.regulator, audience="regulator", extra={"regulator": body.regulator})
    return {
        "token": token,
        "regulator": body.regulator,
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
