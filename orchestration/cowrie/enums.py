"""Enumerations.

These are transcribed 1:1 from the `Enumerations` package of the Cowrie class
diagram (docs/uml/cowrie_class.puml).

One deliberate addition is documented here rather than hidden:

    TransactionState.CANCELLED

The class diagram's `TransactionState` enum lists ten values and does not
include CANCELLED, but the state machine diagram (docs/uml/cowrie_state.puml)
defines the transition `Quoted --> Cancelled : quote expires (> 60s)`.  The two
diagrams disagree.  The state machine is the authority on the transaction
lifecycle, so CANCELLED is included and the class diagram is treated as having
an omission.  See README section "Diagram reconciliation".
"""

from enum import StrEnum


class KycLevel(StrEnum):
    """Verification tier.  Transaction limits scale with this (FR 1.2)."""

    NONE = "NONE"
    TIER1 = "TIER1"
    TIER2 = "TIER2"
    TIER3 = "TIER3"


class KycStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    FROZEN = "FROZEN"


class KycIdType(StrEnum):
    """African government ID types accepted by Smile ID (SRS 3.3)."""

    NIN = "NIN"
    BVN = "BVN"
    KENYAN_ID = "KENYAN_ID"
    NIDA = "NIDA"
    GHANA_CARD = "GHANA_CARD"


class TransactionState(StrEnum):
    CREATED = "CREATED"
    QUOTED = "QUOTED"
    AUTHORIZED = "AUTHORIZED"
    ONRAMP_PENDING = "ONRAMP_PENDING"
    BRIDGING = "BRIDGING"
    OFFRAMP_PENDING = "OFFRAMP_PENDING"
    SETTLED = "SETTLED"
    REFUNDING = "REFUNDING"
    REFUNDED = "REFUNDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"  # from the state machine diagram; see module docstring


class IntentStatus(StrEnum):
    CREATED = "CREATED"
    PROCESSING = "PROCESSING"
    SETTLED = "SETTLED"
    FAILED = "FAILED"


class WebhookStatus(StrEnum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    REVOKED = "REVOKED"


class ActorType(StrEnum):
    USER = "USER"
    ADMIN = "ADMIN"
    SYSTEM = "SYSTEM"
    REGULATOR = "REGULATOR"


# --------------------------------------------------------------------------
# Supporting enums.  Not on the class diagram, but required by requirements
# that the diagram references (admin RBAC in SRS 2.3, dispute handling in
# FR 5.2, and the demo scenario switch that exercises the state machine).
# --------------------------------------------------------------------------


class AdminRole(StrEnum):
    """RBAC roles from SRS 2.3, "Cowrie Admins" privilege column."""

    SUPPORT = "SUPPORT"  # read only
    REVIEWER = "REVIEWER"  # + KYC decisions
    OFFICER = "OFFICER"  # + regulator export, freeze
    ENGINEER = "ENGINEER"  # + deploy / chain operations
    ADMIN = "ADMIN"  # + role grants


class DisputeStatus(StrEnum):
    OPEN = "OPEN"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"
    REJECTED = "REJECTED"


class RiskLevel(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class DemoScenario(StrEnum):
    """Forces a transfer down a specific branch of the state machine diagram.

    Demo-only.  Every value maps to one labelled arrow in
    docs/uml/cowrie_state.puml so the prototype can demonstrate the whole
    lifecycle, not only the happy path.
    """

    HAPPY = "HAPPY"  # ... -> SETTLED
    SANCTIONS_HOLD = "SANCTIONS_HOLD"  # Authorized -> Failed
    MONO_ERROR = "MONO_ERROR"  # Authorized -> Failed
    ONRAMP_TIMEOUT = "ONRAMP_TIMEOUT"  # OnRampPending -> Refunding
    CHAIN_ROLLBACK = "CHAIN_ROLLBACK"  # Bridging -> Refunding
    PAYOUT_FAILED = "PAYOUT_FAILED"  # OffRampPending -> Refunding


#: Legal transitions, transcribed from docs/uml/cowrie_state.puml.
#: The transfer service refuses any move that is not in this table, which makes
#: the diagram executable rather than decorative.
ALLOWED_TRANSITIONS: dict[TransactionState, set[TransactionState]] = {
    TransactionState.CREATED: {TransactionState.QUOTED},
    TransactionState.QUOTED: {TransactionState.AUTHORIZED, TransactionState.CANCELLED},
    TransactionState.AUTHORIZED: {TransactionState.ONRAMP_PENDING, TransactionState.FAILED},
    TransactionState.ONRAMP_PENDING: {TransactionState.BRIDGING, TransactionState.REFUNDING},
    TransactionState.BRIDGING: {TransactionState.OFFRAMP_PENDING, TransactionState.REFUNDING},
    TransactionState.OFFRAMP_PENDING: {TransactionState.SETTLED, TransactionState.REFUNDING},
    TransactionState.REFUNDING: {TransactionState.REFUNDED},
    # terminal states
    TransactionState.SETTLED: set(),
    TransactionState.REFUNDED: set(),
    TransactionState.FAILED: set(),
    TransactionState.CANCELLED: set(),
}

#: States from which no further movement is possible.
TERMINAL_STATES = {
    TransactionState.SETTLED,
    TransactionState.REFUNDED,
    TransactionState.FAILED,
    TransactionState.CANCELLED,
}

#: States where the sender's money is in flight and NFR 3 applies.
IN_FLIGHT_STATES = {
    TransactionState.ONRAMP_PENDING,
    TransactionState.BRIDGING,
    TransactionState.OFFRAMP_PENDING,
}
