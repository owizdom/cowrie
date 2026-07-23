"""Tamper-evident audit log (NFR 5).

NFR 5: "Every action that changes a financial balance is written to a
permanent, tamper-evident log that is also anchored on-chain."

The class diagram gives AuditLogEntry three private hash fields
(-beforeHash, -afterHash, -prevLogHash) and one operation, +verifyChain().
This module is the implementation of exactly that.

How the tamper evidence works
-----------------------------
Each entry stores:

    beforeHash    SHA-256 of the entity's state before the action
    afterHash     SHA-256 of the entity's state after the action
    prevLogHash   the entryHash of the previous entry in the log
    entryHash     SHA-256 over this entry's own fields including prevLogHash

Because entryHash covers prevLogHash, the entries form a chain.  Editing any
historical row changes its entryHash, which no longer matches the prevLogHash
recorded by its successor, and verify_chain() reports the exact sequence number
where the break occurs.  Deleting a row breaks the same link.

What this does and does not give you
------------------------------------
It detects tampering; it does not prevent it.  Someone with write access to the
database could rewrite every subsequent row and produce a consistent chain.
That is why NFR 5 also requires anchoring: `anchor_pending` writes the head
hash of a batch to the chain, and once anchored, rewriting history would also
require rewriting a block, which the database operator cannot do.  Entries
anchored this way carry the anchor transaction hash.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..enums import ActorType
from ..models import AuditLogEntry, utcnow
from ..security import sha256_hex

#: Actions that move money or change a compliance decision.  Only these are
#: required to be logged by NFR 5, but logging more costs nothing.
FINANCIAL_ACTIONS = {
    "transaction.created",
    "transaction.quoted",
    "transaction.authorized",
    "transaction.state_changed",
    "transaction.settled",
    "transaction.refunded",
    "transaction.failed",
    "transaction.cancelled",
    "cusdc.minted",
    "cusdc.burned",
    "reserve.attested",
    "kyc.approved",
    "kyc.rejected",
    "kyc.frozen",
    "user.frozen",
    "regulator.export",
}


def _canonical(payload: Any) -> str:
    """Stable JSON so the same state always hashes to the same value.

    sort_keys matters: without it, two dictionaries with identical content but
    different insertion order would hash differently and the chain would report
    phantom tampering.
    """
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def snapshot(entity: Any, fields: list[str] | None = None) -> dict:
    """Capture the auditable state of an entity.

    Private attributes (leading underscore) are deliberately excluded: the log
    must not become a second copy of the encrypted ID numbers and key hashes
    that the class diagram marks private.
    """
    if entity is None:
        return {}
    if fields is None:
        fields = [
            c.key
            for c in entity.__table__.columns
            if not c.key.startswith("_")
            and c.key not in {"pin_hash", "key_hash", "secret_hash", "password_hash",
                              "id_number_encrypted", "before_hash", "after_hash", "prev_log_hash"}
        ]
    return {f: getattr(entity, f, None) for f in fields}


def _head(db: Session) -> AuditLogEntry | None:
    return db.execute(
        select(AuditLogEntry).order_by(AuditLogEntry.seq.desc()).limit(1)
    ).scalar_one_or_none()


def record(
    db: Session,
    *,
    entity_type: str,
    entity_id: str,
    action: str,
    actor: ActorType,
    actor_id: str = "",
    before: dict | None = None,
    after: dict | None = None,
    detail: dict | None = None,
) -> AuditLogEntry:
    """Append one entry.  There is no update or delete counterpart by design."""
    prev = _head(db)
    prev_hash = prev.entryHash if prev else ""
    next_seq = (prev.seq + 1) if prev else 1

    before_hash = sha256_hex(_canonical(before)) if before is not None else ""
    after_hash = sha256_hex(_canonical(after)) if after is not None else ""

    # `ts` must be set here, not left to the column default.  A column default is
    # applied at INSERT, so it would still be None while the entry hash is being
    # computed - and the hash would then cover "None" while verification later
    # recomputes it over the real timestamp, breaking the chain on every row.
    ts = utcnow()

    entry = AuditLogEntry(
        seq=next_seq,
        entityType=entity_type,
        entityId=entity_id,
        actor=actor,
        actorId=actor_id,
        action=action,
        detail=detail or {},
        ts=ts,
    )
    entry._beforeHash = before_hash
    entry._afterHash = after_hash
    entry._prevLogHash = prev_hash
    entry.entryHash = _entry_hash(
        seq=next_seq,
        entity_type=entity_type,
        entity_id=entity_id,
        actor=str(actor),
        action=action,
        before_hash=before_hash,
        after_hash=after_hash,
        prev_hash=prev_hash,
        ts=ts,
    )

    db.add(entry)
    db.flush()
    return entry


def _entry_hash(
    *,
    seq: int,
    entity_type: str,
    entity_id: str,
    actor: str,
    action: str,
    before_hash: str,
    after_hash: str,
    prev_hash: str,
    ts: Any,
) -> str:
    return sha256_hex(
        _canonical(
            {
                "seq": seq,
                "entityType": entity_type,
                "entityId": entity_id,
                "actor": actor,
                "action": action,
                "beforeHash": before_hash,
                "afterHash": after_hash,
                "prevLogHash": prev_hash,
                "ts": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
            }
        )
    )


def verify_chain(db: Session) -> dict:
    """+verifyChain() : bool, with the detail an auditor actually needs.

    Walks the log in sequence order and checks two things per entry: that its
    recorded prevLogHash matches the previous entry's entryHash, and that its
    own entryHash still matches a recomputation over its fields.  Returns the
    first break rather than only a boolean, because "the log is broken" is not
    an actionable finding but "the log is broken at entry 148" is.
    """
    entries = db.execute(select(AuditLogEntry).order_by(AuditLogEntry.seq.asc())).scalars().all()

    expected_prev = ""
    for entry in entries:
        recomputed = _entry_hash(
            seq=entry.seq,
            entity_type=entry.entityType,
            entity_id=entry.entityId,
            actor=str(entry.actor),
            action=entry.action,
            before_hash=entry._beforeHash,
            after_hash=entry._afterHash,
            prev_hash=entry._prevLogHash,
            ts=entry.ts,
        )
        if recomputed != entry.entryHash:
            return {
                "valid": False,
                "entriesChecked": len(entries),
                "brokenAtSeq": entry.seq,
                "reason": "entry contents do not match its recorded hash (row was edited)",
            }
        if entry._prevLogHash != expected_prev:
            return {
                "valid": False,
                "entriesChecked": len(entries),
                "brokenAtSeq": entry.seq,
                "reason": "chain link mismatch (a preceding row was edited or removed)",
            }
        expected_prev = entry.entryHash

    return {
        "valid": True,
        "entriesChecked": len(entries),
        "brokenAtSeq": None,
        "headHash": expected_prev,
        "reason": "",
    }


async def anchor_pending(db: Session, chain) -> dict:
    """Anchor every un-anchored entry as one batch (NFR 5).

    Anchoring each entry individually would be one chain transaction per audit
    row, which is unaffordable.  Instead the head hash of the batch goes
    on-chain: because each entry commits to all its predecessors, anchoring the
    head anchors the whole prefix.
    """
    pending = (
        db.execute(select(AuditLogEntry).where(AuditLogEntry.anchorTxHash == "").order_by(AuditLogEntry.seq))
        .scalars()
        .all()
    )
    if not pending:
        return {"anchored": 0, "txHash": ""}

    head_hash = pending[-1].entryHash
    tx_hash = await chain.anchor(head_hash)
    for entry in pending:
        entry.anchorTxHash = tx_hash
    db.flush()

    return {"anchored": len(pending), "txHash": tx_hash, "headHash": head_hash}


def stats(db: Session) -> dict:
    total = db.execute(select(func.count()).select_from(AuditLogEntry)).scalar_one()
    anchored = db.execute(
        select(func.count()).select_from(AuditLogEntry).where(AuditLogEntry.anchorTxHash != "")
    ).scalar_one()
    return {"totalEntries": total, "anchoredEntries": anchored, "pendingAnchor": total - anchored}
