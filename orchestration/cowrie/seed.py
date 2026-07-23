"""First-boot provisioning.

Two things are written when the database is empty, and nothing else:

    console operators   Cowrie's own compliance staff. SRS 2.3 lists five roles
                        with different privileges, and the Admin privilege is
                        the one that grants roles - so operators are provisioned
                        rather than self-registered.

    sanctions lists     FR 1.3 screens every user against OFAC, UN and EU at
                        signup, on every transfer and daily. Without the lists
                        there is nothing to screen against, so they are
                        reference data the system needs to function.

There is no sample dataset. No users, no transfers, no KYC submissions, no
disputes, no partner keys, no reserve history. Everything else in the system
arrives through the product.

The sanctions entries below are fictional. Shipping a copy of the real OFAC SDN,
UN Consolidated or EU lists would be stale within a week and would misrepresent
what has been integrated; what is real is the matching logic and the
enforcement path behind it.
"""

from __future__ import annotations

from sqlalchemy import func, select

from .db import session_scope
from .enums import AdminRole
from .models import AdminUser, SanctionsEntry
from .security import hash_secret

#: Initial console password. Every operator must change it on first sign-in in
#: any real deployment; it is here so the console is reachable at all.
INITIAL_CONSOLE_PASSWORD = "cowrie-demo"

#: Cowrie's compliance team, one per role in SRS 2.3.
OPERATORS = [
    ("Amara Obi", "amara@cowrie.demo", AdminRole.ADMIN),
    ("Kwame Mensah", "kwame@cowrie.demo", AdminRole.OFFICER),
    ("Zainab Musa", "zainab@cowrie.demo", AdminRole.REVIEWER),
    ("David Kimani", "david@cowrie.demo", AdminRole.ENGINEER),
    ("Blessing Eze", "blessing@cowrie.demo", AdminRole.SUPPORT),
]

#: Fictional entries, so the screening path in FR 1.3 can be exercised in both
#: directions. See the module docstring.
SANCTIONS = [
    ("OFAC", "Ibrahim Al-Rashid Kone", "ML", "Fictional entry"),
    ("OFAC", "Viktor Semenov Petrov", "RU", "Fictional entry"),
    ("UN", "Hassan Abdi Warsame", "SO", "Fictional entry"),
    ("UN", "Mohammed Tahir Bakr", "SD", "Fictional entry"),
    ("EU", "Dmitri Sokolov Ivanov", "BY", "Fictional entry"),
    ("EU", "Andrei Kuznetsov Mikhail", "RU", "Fictional entry"),
]


def _already_provisioned() -> bool:
    with session_scope() as db:
        return db.execute(select(func.count()).select_from(AdminUser)).scalar_one() > 0


def seed_if_empty() -> None:
    """Provision once, on an empty database."""
    if _already_provisioned():
        return
    provision()


def provision() -> None:
    with session_scope() as db:
        for list_name, full_name, country, reason in SANCTIONS:
            db.add(
                SanctionsEntry(
                    listName=list_name, fullName=full_name, country=country, reason=reason
                )
            )

        for full_name, email, role in OPERATORS:
            operator = AdminUser(email=email, fullName=full_name, role=role)
            operator._passwordHash = hash_secret(INITIAL_CONSOLE_PASSWORD)
            db.add(operator)

        db.commit()

    print(f"[provision] {len(OPERATORS)} console operators, {len(SANCTIONS)} sanctions entries")
    print(f"[provision] console: {OPERATORS[0][1]} / {INITIAL_CONSOLE_PASSWORD}")


if __name__ == "__main__":
    from .db import init_db

    init_db()
    provision()
