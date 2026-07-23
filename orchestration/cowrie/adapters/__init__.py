"""Adapters for the five external actors in the use case diagram.

    Mono              NGN on-ramp        adapters/mono.py
    Safaricom Daraja  M-Pesa off-ramp    adapters/daraja.py
    Smile ID          KYC                adapters/smileid.py
    Banking Partner   cUSDC USD reserve  adapters/banking_partner.py
    Base Network      settlement         adapters/chain.py

Every one of them is a simulation.  SRS 2.5 constraint 2 states the position
this build takes: no banking partner is integrated and the contracts are not
deployed to Base, so the behaviour is modelled with seeded demo data.  None of
these modules opens a network connection to a third party, and none of them
holds a credential for one.

Each adapter keeps the request and response shapes of the real API it stands in
for, so that replacing a simulation with a live client is a change confined to
one file.  Where a shape is simplified, the module says which fields were
dropped.
"""

from .banking_partner import BankingPartnerAdapter
from .chain import ChainAdapter, get_chain
from .daraja import DarajaAdapter
from .mono import MonoAdapter
from .smileid import SmileIdAdapter

__all__ = [
    "BankingPartnerAdapter",
    "ChainAdapter",
    "DarajaAdapter",
    "MonoAdapter",
    "SmileIdAdapter",
    "get_chain",
]
