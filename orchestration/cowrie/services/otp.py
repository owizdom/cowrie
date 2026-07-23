"""One-time codes - FR 1.1 and the second factor in FR 2.2.

FR 1.1: "Sign up with a phone number and email, verified by a one-time code
**before the account is created**."

That ordering is a requirement, not a detail.  The code is issued and verified
against a pending-registration record; the User row is only written once the
code checks out, so an unverified phone number never becomes an account.

FR 2.2: "Require a 6-digit PIN to confirm (**plus a second factor for large
transfers**)."

The same mechanism serves as the step-up factor.  Above a threshold, confirming
a transfer needs a fresh code as well as the PIN.

Delivery
--------
There is no SMS provider in this build, so codes are not sent anywhere - they
are returned by the API and displayed in the UI, clearly labelled as a demo
affordance.  Pretending to send an SMS that never arrives would make the app
untestable.  The seam is `_deliver`, which is the single function an SMS or
email provider would replace.

Codes are stored hashed with an expiry and an attempt counter, because a
one-time code that can be brute-forced is not a factor.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from ..config import settings
from ..security import hash_secret, verify_secret

#: Codes are six digits, matching the PIN length users already know.
CODE_LENGTH = 6
TTL = timedelta(minutes=10)
MAX_ATTEMPTS = 5

#: FR 2.2 - transfers at or above this USD value need the second factor as well
#: as the PIN.  Set at the TIER1 limit so the step-up is demonstrable with the
#: seeded accounts rather than theoretical.
STEP_UP_THRESHOLD_USD = 200.0


@dataclass(slots=True)
class Challenge:
    purpose: str
    """REGISTRATION | STEP_UP"""
    identifier: str
    """Phone number for registration, transaction id for a step-up."""
    code_hash: str
    expires_at: datetime
    attempts: int = 0
    payload: dict = field(default_factory=dict)
    """For REGISTRATION, the account details held until the code is verified."""

    def expired(self) -> bool:
        return datetime.now(UTC) >= self.expires_at


class OtpService:
    """In-memory challenge store.

    In-memory is correct for a single-container demo and wrong for a multi-
    container deployment; SRS §3.3 lists Redis as the session cache and this is
    exactly the kind of state that belongs there.  The interface below is what a
    Redis-backed implementation would satisfy.
    """

    def __init__(self) -> None:
        self._challenges: dict[str, Challenge] = {}

    # -- issuing ------------------------------------------------------------
    def issue(
        self,
        *,
        purpose: str,
        identifier: str,
        payload: dict | None = None,
        email: str = "",
    ) -> tuple[str, str, bool]:
        """Create a challenge.  Returns (challenge_id, code, delivered).

        `delivered` says whether the code actually reached the user. When it is
        False the caller must show the code, or sign-up becomes impossible.
        """
        code = "".join(secrets.choice("0123456789") for _ in range(CODE_LENGTH))
        challenge_id = f"otp_{secrets.token_hex(8)}"

        self._challenges[challenge_id] = Challenge(
            purpose=purpose,
            identifier=identifier,
            code_hash=hash_secret(code),
            expires_at=datetime.now(UTC) + TTL,
            payload=payload or {},
        )
        self._prune()
        delivered = self._deliver(
            identifier=identifier, code=code, purpose=purpose, email=email
        )
        return challenge_id, code, delivered

    def _deliver(self, *, identifier: str, code: str, purpose: str, email: str = "") -> bool:
        """Send the code, and report whether it actually went anywhere.

        FR 1.1 requires a one-time code but does not say by which channel - it
        says "a phone number and email, verified by a one-time code". Email is
        therefore compliant, and it is the channel that can be delivered for
        free; SMS needs a paid provider account.

        Returns True when the code was genuinely sent, so the caller knows
        whether it still has to show it on screen. Reporting success when
        nothing was sent would strand the user on a code they never receive.
        """
        if not email:
            print(f"[otp] {purpose} code for {identifier}: {code} (shown on screen)")
            return False

        # HTTP first. Most platform hosts block outbound SMTP ports to stop
        # spam, so on a deployment port 587 fails with "Network is unreachable"
        # while an HTTPS API on 443 goes straight through.
        if settings.resend_api_key:
            if self._send_via_resend(email=email, code=code):
                return True

        if not settings.smtp_host:
            print(f"[otp] {purpose} code for {identifier}: {code} (shown on screen)")
            return False

        import smtplib
        from email.message import EmailMessage

        message = EmailMessage()
        message["Subject"] = f"{code} is your Cowrie code"
        message["From"] = settings.smtp_from or settings.smtp_user
        message["To"] = email
        message.set_content(
            f"Your Cowrie verification code is {code}.\n\n"
            "It expires in 10 minutes and can only be used once.\n"
            "If you did not request it, you can ignore this message."
        )

        try:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as server:
                server.starttls()
                if settings.smtp_user:
                    server.login(settings.smtp_user, settings.smtp_password)
                server.send_message(message)
            print(f"[otp] {purpose} code emailed to {email}")
            return True
        except Exception as exc:  # noqa: BLE001
            # A mail server that is down must not block sign-up. Fall back to
            # showing the code rather than failing the registration.
            print(f"[otp] email delivery failed ({exc}); showing the code instead")
            return False

    def _send_via_resend(self, *, email: str, code: str) -> bool:
        """Send over HTTPS rather than SMTP.

        Returns False on any failure so the caller falls back rather than
        leaving the user waiting for a code that is not coming.
        """
        import httpx

        try:
            response = httpx.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {settings.resend_api_key}"},
                json={
                    "from": settings.resend_from,
                    "to": [email],
                    "subject": f"{code} is your Cowrie code",
                    "text": (
                        f"Your Cowrie verification code is {code}.\n\n"
                        "It expires in 10 minutes and can only be used once.\n"
                        "If you did not request it, you can ignore this message."
                    ),
                },
                timeout=10,
            )
            if response.status_code < 300:
                print(f"[otp] code emailed to {email}")
                return True
            print(f"[otp] resend rejected the request ({response.status_code}): {response.text[:200]}")
        except Exception as exc:  # noqa: BLE001
            print(f"[otp] resend unreachable ({exc})")
        return False

    # -- verifying ----------------------------------------------------------
    def verify(self, *, challenge_id: str, code: str) -> Challenge:
        """Consume a challenge, or raise.

        Single-use: a verified challenge is removed, so a captured code cannot
        be replayed.
        """
        challenge = self._challenges.get(challenge_id)
        if challenge is None:
            raise ValueError("This code has expired or was already used. Request a new one.")

        if challenge.expired():
            del self._challenges[challenge_id]
            raise ValueError("This code has expired. Request a new one.")

        if challenge.attempts >= MAX_ATTEMPTS:
            del self._challenges[challenge_id]
            raise ValueError("Too many incorrect attempts. Request a new code.")

        if not verify_secret(code, challenge.code_hash):
            challenge.attempts += 1
            remaining = MAX_ATTEMPTS - challenge.attempts
            raise ValueError(f"Incorrect code. {remaining} attempt{'s' if remaining != 1 else ''} left.")

        del self._challenges[challenge_id]
        return challenge

    def peek(self, challenge_id: str) -> Challenge | None:
        return self._challenges.get(challenge_id)

    def _prune(self) -> None:
        for key in [k for k, v in self._challenges.items() if v.expired()]:
            del self._challenges[key]


def requires_step_up(source_amount_ngn: float | int) -> bool:
    """FR 2.2 - is this large enough to need a second factor?"""
    usd = float(source_amount_ngn) / settings.mid_market_ngn_per_usd
    return usd >= STEP_UP_THRESHOLD_USD


service = OtpService()
