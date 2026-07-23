"""Base Network settlement (two modes, both local).

The bridge call, the 12-confirmation wait and the cUSDC mint/burn all happen
through this module.  It has two implementations behind one interface:

    SimulatedChain   default.  Models Base in-process: a block counter
                     advancing at settings.base_block_seconds, deterministic
                     transaction hashes, and honest confirmation counting.
                     Nothing leaves the machine.

    AnvilChain       optional.  Deploys cusdc/ - the real Solidity contracts -
                     to a local Anvil node and issues real transactions against
                     them.  Real hashes, real receipts, real block numbers,
                     real reverts.  Still entirely local: Base mainnet is never
                     contacted and no funded key exists.

SRS 2.5 constraint 2 permits the simulation.  AnvilChain exists because the
contracts were written anyway and running them proves the settlement logic
rather than asserting it.  Which mode produced a record is stored on the record
(OnchainRecord.chainMode) so the UI never claims more than it did.

Neither mode touches Base mainnet or Base Sepolia.  There is no RPC URL for a
public network anywhere in this codebase.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Protocol

from ..config import REPO_ROOT, settings


@dataclass(slots=True)
class BridgeSubmission:
    tx_hash: str
    block_number: int
    contract_address: str
    cngn_amount: Decimal
    cusdc_amount: Decimal
    gas_used_usd: Decimal
    mode: str


@dataclass(slots=True)
class ConfirmationStatus:
    confirmations: int
    head_block: int
    rolled_back: bool
    final: bool


class ChainAdapter(Protocol):
    mode: str

    async def submit_bridge(
        self, *, transfer_id: str, cngn_amount: Decimal, cusdc_amount: Decimal
    ) -> BridgeSubmission: ...

    async def confirmation_status(self, submission: BridgeSubmission) -> ConfirmationStatus: ...

    async def mint_cusdc(self, *, amount: Decimal, attestation_ref: str) -> str: ...

    async def burn_cusdc(self, *, amount: Decimal) -> str: ...

    async def total_supply(self) -> Decimal: ...

    async def anchor(self, digest: str) -> str: ...

    async def health(self) -> dict: ...


# ---------------------------------------------------------------------------
# Simulated Base
# ---------------------------------------------------------------------------


class SimulatedChain:
    """An in-process model of Base L2.

    Block height is derived from wall-clock time rather than incremented by a
    background task, so confirmations advance correctly even when the process
    is busy, and the arithmetic is checkable: at 2s blocks, 12 confirmations is
    24 seconds, which is the number FR 3.3 quotes.
    """

    mode = "simulated"

    def __init__(self) -> None:
        self._genesis = time.time()
        self._genesis_block = 21_400_000  # a plausible Base height, for realism
        self._supply = Decimal("12400128.000000")
        self._rolled_back: set[str] = set()
        self._nonce = 0

    # -- internals ----------------------------------------------------------
    def _head(self) -> int:
        elapsed = time.time() - self._genesis
        return self._genesis_block + int(elapsed / max(settings.base_block_seconds, 0.05))

    def _hash(self, label: str) -> str:
        self._nonce += 1
        raw = f"{label}:{self._nonce}:{self._genesis}".encode()
        return "0x" + hashlib.sha256(raw).hexdigest()

    def force_rollback(self, tx_hash: str) -> None:
        """Demo hook for DemoScenario.CHAIN_ROLLBACK (Bridging -> Refunding).

        A real reorg on an L2 is rare; the requirement still has to handle it,
        and FR 3.3 says so explicitly, so the path has to be reachable.
        """
        self._rolled_back.add(tx_hash)

    # -- interface ----------------------------------------------------------
    async def submit_bridge(
        self, *, transfer_id: str, cngn_amount: Decimal, cusdc_amount: Decimal
    ) -> BridgeSubmission:
        """FR 3.1 - one transaction that takes cNGN through cUSDC and emits a
        confirmation event."""
        await asyncio.sleep(settings.scaled(0.4))
        return BridgeSubmission(
            tx_hash=self._hash(f"bridge:{transfer_id}"),
            block_number=self._head(),
            contract_address=settings.bridge_address,
            cngn_amount=cngn_amount,
            cusdc_amount=cusdc_amount,
            gas_used_usd=Decimal(str(settings.network_gas_usd)),
            mode=self.mode,
        )

    async def confirmation_status(self, submission: BridgeSubmission) -> ConfirmationStatus:
        head = self._head()
        rolled = submission.tx_hash in self._rolled_back
        confirmations = 0 if rolled else max(0, head - submission.block_number)
        return ConfirmationStatus(
            confirmations=confirmations,
            head_block=head,
            rolled_back=rolled,
            final=(not rolled) and confirmations >= settings.required_confirmations,
        )

    async def mint_cusdc(self, *, amount: Decimal, attestation_ref: str) -> str:
        await asyncio.sleep(settings.scaled(0.3))
        self._supply += amount
        return self._hash(f"mint:{attestation_ref}")

    async def burn_cusdc(self, *, amount: Decimal) -> str:
        await asyncio.sleep(settings.scaled(0.3))
        self._supply -= amount
        return self._hash(f"burn:{amount}")

    async def total_supply(self) -> Decimal:
        return self._supply

    async def anchor(self, digest: str) -> str:
        """NFR 5 - write an audit-log batch hash on-chain."""
        await asyncio.sleep(settings.scaled(0.2))
        return self._hash(f"anchor:{digest}")

    async def health(self) -> dict:
        return {
            "mode": self.mode,
            "network": "Base (simulated in-process)",
            "chainId": settings.chain_id,
            "headBlock": self._head(),
            "blockSeconds": settings.base_block_seconds,
            "requiredConfirmations": settings.required_confirmations,
            "contractsDeployed": False,
            "note": "No external RPC. Base mainnet and Base Sepolia are not contacted.",
        }


# ---------------------------------------------------------------------------
# Local Anvil running the real contracts
# ---------------------------------------------------------------------------

DEPLOYMENT_FILE = REPO_ROOT / "cusdc" / "deployments" / "local.json"


class AnvilChain:
    """Real Solidity contracts on a local Anvil node.

    Requires `anvil` running and `cusdc/script/Deploy.s.sol` to have been run
    (`make chain` does both).  Reads the deployed addresses from
    cusdc/deployments/local.json.

    Every transaction here is genuine: signed with Anvil's first well-known
    development key, mined by the local node, and returning a receipt that can
    be inspected with `cast`.  The key is the publicly published Anvil test key,
    which is exactly why it is safe to have in a repository - it controls
    nothing outside a local node.
    """

    mode = "anvil"

    #: Anvil's first default account.  Published in Foundry's own documentation.
    #: Deliberately hard-coded: it must never be swapped for a real key, and a
    #: literal here is easier to audit than an environment variable that could
    #: be pointed at one.
    DEV_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"

    def __init__(self) -> None:
        from web3 import Web3

        self._w3 = Web3(Web3.HTTPProvider(settings.anvil_rpc_url, request_kwargs={"timeout": 5}))
        deployment = json.loads(Path(DEPLOYMENT_FILE).read_text())
        self._addresses = deployment["addresses"]
        self._abis = deployment["abis"]
        self._account = self._w3.eth.accounts[0]
        self._bridge = self._w3.eth.contract(
            address=self._w3.to_checksum_address(self._addresses["CowrieBridge"]),
            abi=self._abis["CowrieBridge"],
        )
        self._cusdc = self._w3.eth.contract(
            address=self._w3.to_checksum_address(self._addresses["CUSDC"]),
            abi=self._abis["CUSDC"],
        )
        self._rolled_back: set[str] = set()

    @staticmethod
    def available() -> bool:
        """True when a local node is reachable and a deployment exists."""
        if not DEPLOYMENT_FILE.exists():
            return False
        try:
            from web3 import Web3

            w3 = Web3(Web3.HTTPProvider(settings.anvil_rpc_url, request_kwargs={"timeout": 2}))
            return bool(w3.is_connected())
        except Exception:
            return False

    # cUSDC and cNGN both use 6 decimals, matching USDC on Base.
    _UNIT = Decimal(10**6)

    def _to_units(self, amount: Decimal) -> int:
        return int((amount * self._UNIT).to_integral_value())

    def _from_units(self, units: int) -> Decimal:
        return Decimal(units) / self._UNIT

    def force_rollback(self, tx_hash: str) -> None:
        # A real reorg cannot be forced on Anvil through the standard API, so
        # the rollback scenario is marked at this layer.  The chain state is
        # genuine; only the reorg verdict is injected.
        self._rolled_back.add(tx_hash)

    async def submit_bridge(
        self, *, transfer_id: str, cngn_amount: Decimal, cusdc_amount: Decimal
    ) -> BridgeSubmission:
        def _send() -> BridgeSubmission:
            ref = self._w3.keccak(text=transfer_id)
            tx = self._bridge.functions.executeBridge(
                ref,
                self._to_units(cngn_amount),
                self._to_units(cusdc_amount),
            ).transact({"from": self._account})
            receipt = self._w3.eth.wait_for_transaction_receipt(tx, timeout=20)
            return BridgeSubmission(
                tx_hash=receipt["transactionHash"].hex()
                if not isinstance(receipt["transactionHash"], str)
                else receipt["transactionHash"],
                block_number=receipt["blockNumber"],
                contract_address=self._addresses["CowrieBridge"],
                cngn_amount=cngn_amount,
                cusdc_amount=cusdc_amount,
                gas_used_usd=Decimal(str(settings.network_gas_usd)),
                mode=self.mode,
            )

        return await asyncio.to_thread(_send)

    async def confirmation_status(self, submission: BridgeSubmission) -> ConfirmationStatus:
        def _check() -> ConfirmationStatus:
            head = self._w3.eth.block_number
            rolled = submission.tx_hash in self._rolled_back
            confirmations = 0 if rolled else max(0, head - submission.block_number)
            return ConfirmationStatus(
                confirmations=confirmations,
                head_block=head,
                rolled_back=rolled,
                final=(not rolled) and confirmations >= settings.required_confirmations,
            )

        return await asyncio.to_thread(_check)

    async def mint_cusdc(self, *, amount: Decimal, attestation_ref: str) -> str:
        def _send() -> str:
            tx = self._cusdc.functions.mintWithAttestation(
                self._account,
                self._to_units(amount),
                self._w3.keccak(text=attestation_ref),
            ).transact({"from": self._account})
            receipt = self._w3.eth.wait_for_transaction_receipt(tx, timeout=20)
            h = receipt["transactionHash"]
            return h if isinstance(h, str) else h.hex()

        return await asyncio.to_thread(_send)

    async def burn_cusdc(self, *, amount: Decimal) -> str:
        def _send() -> str:
            tx = self._cusdc.functions.burn(self._to_units(amount)).transact({"from": self._account})
            receipt = self._w3.eth.wait_for_transaction_receipt(tx, timeout=20)
            h = receipt["transactionHash"]
            return h if isinstance(h, str) else h.hex()

        return await asyncio.to_thread(_send)

    async def total_supply(self) -> Decimal:
        def _read() -> Decimal:
            return self._from_units(self._cusdc.functions.totalSupply().call())

        return await asyncio.to_thread(_read)

    async def anchor(self, digest: str) -> str:
        def _send() -> str:
            tx = self._bridge.functions.anchorAuditBatch(
                self._w3.keccak(text=digest)
            ).transact({"from": self._account})
            receipt = self._w3.eth.wait_for_transaction_receipt(tx, timeout=20)
            h = receipt["transactionHash"]
            return h if isinstance(h, str) else h.hex()

        return await asyncio.to_thread(_send)

    async def health(self) -> dict:
        def _read() -> dict:
            return {
                "mode": self.mode,
                "network": "Anvil (local fork-free node) running cusdc/ contracts",
                "chainId": self._w3.eth.chain_id,
                "headBlock": self._w3.eth.block_number,
                "blockSeconds": settings.base_block_seconds,
                "requiredConfirmations": settings.required_confirmations,
                "contractsDeployed": True,
                "addresses": self._addresses,
                "note": "Local node only. Base mainnet and Base Sepolia are not contacted.",
            }

        return await asyncio.to_thread(_read)


# ---------------------------------------------------------------------------
# selection
# ---------------------------------------------------------------------------

_chain: ChainAdapter | None = None


def get_chain() -> ChainAdapter:
    """Return the configured chain adapter, falling back safely.

    Asking for anvil when no node is running degrades to the simulator with a
    log line rather than failing to boot, because a demo that will not start is
    worse than a demo that is honest about its mode.
    """
    global _chain
    if _chain is not None:
        return _chain

    if settings.chain_mode == "anvil":
        if AnvilChain.available():
            try:
                _chain = AnvilChain()
                print("[chain] anvil mode: local node + deployed cusdc/ contracts")
                return _chain
            except Exception as exc:  # pragma: no cover - environment dependent
                print(f"[chain] anvil unavailable ({exc}); falling back to simulated")
        else:
            print("[chain] anvil requested but no local node/deployment found; using simulated")

    _chain = SimulatedChain()
    return _chain


def reset_chain() -> None:
    """Test hook."""
    global _chain
    _chain = None
