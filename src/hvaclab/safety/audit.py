"""Immutable audit log of every write attempt — allowed, refused, succeeded, or failed.

Purpose, in descending order of how often it will actually matter:

1. **Operations.** "Who overrode this valve, when, and why?" is the question that
   consumes the most time in a BAS troubleshooting session, and BACnet cannot answer it.
2. **Liability.** If a UUKL-listed point is ever touched, or alleged to have been touched,
   this log is the evidence. It must be as convincing to a third party as we can make it.
3. **Debugging.** A refused write is as informative as a successful one; logging only the
   allow path hides every misconfiguration.

Design requirements:

* **Append-only.** No update, no delete. There is deliberately no `delete` or `redact`
  method on `AuditLog`.
* **Hash-chained.** Each record includes the hash of its predecessor, so removing or
  altering a record breaks the chain verifiably. This is not cryptographic overkill — it
  is what turns "our log says" into something an insurer will accept.
* **Records refusals.** Every `GateDecision`, not just ALLOWED.
* **Records the reason string.** A human-written justification, captured at request time.
* **Survives the process.** Backed by the same DuckDB file as the historian, flushed
  synchronously on the write path — an audit record that is still in a buffer when the
  process dies did not happen.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from hvaclab.adapters.base import WriteResult, WriteTicket
from hvaclab.model.point import PointRef
from hvaclab.safety.write_gate import GateDecision


class AuditEventKind(StrEnum):
    """What happened. Every one of these is recorded, including the refusals."""

    WRITE_REQUESTED = "writeRequested"
    WRITE_ALLOWED = "writeAllowed"
    WRITE_REFUSED = "writeRefused"
    WRITE_SUCCEEDED = "writeSucceeded"
    WRITE_FAILED = "writeFailed"
    RELEASE_REQUESTED = "releaseRequested"
    RELEASE_SUCCEEDED = "releaseSucceeded"
    RELEASE_FAILED = "releaseFailed"
    CLAIM_EXPIRED = "claimExpired"
    ORPHAN_DETECTED = "orphanDetected"
    BLOCKLIST_LOADED = "blocklistLoaded"
    BLOCKLIST_HIT = "blocklistHit"
    READ_ONLY_ASSERTED = "readOnlyAsserted"
    GATE_ARMED = "gateArmed"


@dataclass(frozen=True, slots=True)
class AuditRecord:
    """One immutable log entry.

    `prev_hash` and `record_hash` form the chain. `actor` is a human or service identity,
    never "system" — if code initiated a write, the record names which code and on whose
    behalf.
    """

    seq: int
    at: datetime
    kind: AuditEventKind
    actor: str
    ref: PointRef | None = None
    equip_id: str | None = None
    value: float | bool | int | str | None = None
    prior_value: float | bool | int | str | None = None
    priority: int | None = None
    reason: str = ""
    decision: GateDecision | None = None
    explanation: str = ""
    ticket_id: str = ""
    claim_id: str = ""
    adapter: str = ""
    source_ip: str = ""
    prev_hash: str = ""
    record_hash: str = ""

    def compute_hash(self) -> str:
        """Compute this record's chain hash.

        TODO: SHA-256 over a canonical serialization of every field except `record_hash`,
            including `prev_hash`.
        What's missing: the canonical serialization must be stable across Python versions
            and field ordering — use an explicit ordered field list, never `repr()`,
            `dict` ordering, or `pickle`, or the chain will fail to verify after an
            innocuous refactor and destroy the log's evidentiary value.
        Acceptance: recomputing over an unchanged record reproduces `record_hash`;
            changing any field changes the hash.
        Depends on: nothing.
        """
        raise NotImplementedError("audit record hashing not yet implemented")


class AuditLog:
    """Append-only, hash-chained log. No update. No delete. By design."""

    def __init__(self, db_path: Path, actor_default: str = "unknown") -> None:
        """Open (or create) the audit store.

        TODO: Open the DuckDB file, create the audit table if absent, and load the last
            record's hash and sequence number to continue the chain.
        What's missing: the schema must forbid mutation at the storage layer where it can
            — no UPDATE or DELETE grants for the application role — because an append-only
            guarantee enforced only in Python is a guarantee against accidents, not against
            anything else.
        Acceptance: reopening an existing log continues the chain; a log whose chain does
            not verify raises at open.
        Depends on: `store.historian` DuckDB connection handling.
        """
        raise NotImplementedError("audit log storage not yet implemented")

    def record(
        self,
        kind: AuditEventKind,
        actor: str,
        ref: PointRef | None = None,
        value: float | bool | int | str | None = None,
        priority: int | None = None,
        reason: str = "",
        decision: GateDecision | None = None,
        explanation: str = "",
        **extra: str,
    ) -> AuditRecord:
        """Append one record, chained to its predecessor, flushed synchronously.

        TODO: Build the record with the next sequence number and `prev_hash`, compute its
            hash, persist it, and return it.
        What's missing: synchronous durability. This must not return until the record is
            on disk — an audit record buffered in memory when the process is killed is
            exactly the record someone will later ask about. Accept the latency; writes
            are rare and each one moves physical equipment.
        Acceptance: killing the process immediately after `record` returns still leaves the
            record present on reopen; sequence numbers are gapless.
        Depends on: `AuditRecord.compute_hash`, `AuditLog.__init__`.
        """
        raise NotImplementedError("audit append not yet implemented")

    def record_ticket(
        self,
        ticket: WriteTicket,
        decision: GateDecision,
        explanation: str,
    ) -> AuditRecord:
        """Record a gate decision about a ticket, allowed or refused.

        TODO: Map the ticket and decision into a record of the appropriate kind.
        What's missing: nothing beyond `record` — but note that this is called on the
            REFUSAL path too, and that a refusal record must capture the same detail as an
            allow, because a pattern of refusals is how a misconfigured integration or a
            probing client becomes visible.
        Acceptance: a refused ticket produces a WRITE_REFUSED record carrying the decision
            and explanation.
        Depends on: `record`.
        """
        raise NotImplementedError("ticket audit recording not yet implemented")

    def record_result(self, ticket: WriteTicket, result: WriteResult, actor: str) -> AuditRecord:
        """Record the outcome of an executed write or release.

        TODO: Emit WRITE_SUCCEEDED/FAILED or RELEASE_SUCCEEDED/FAILED with the read-back
            state.
        What's missing: capture `priority_in_effect_after` and `value_after` from the
            result. A write that "succeeded" but did not change the effective priority
            means something at a higher priority already owns the point — operationally
            that is a failure, and only the read-back reveals it.
        Acceptance: a successful write whose effective priority did not change is recorded
            with a distinguishing explanation.
        Depends on: `record`, `safety.write_gate.PriorityArraySnapshot`.
        """
        raise NotImplementedError("result audit recording not yet implemented")

    def verify_chain(self, start_seq: int = 0) -> tuple[bool, int | None]:
        """Verify the hash chain, returning (ok, first bad sequence number).

        TODO: Walk records from `start_seq`, recompute each hash, and confirm each
            `prev_hash` matches its predecessor's `record_hash`.
        What's missing: this should run at startup and on a schedule, and a broken chain
            must be an alert, not a log line. A chain break means either corruption or
            tampering, and both need a human immediately.
        Acceptance: an intact log verifies; altering one row's value reports that row's
            sequence number.
        Depends on: `AuditRecord.compute_hash`.
        """
        raise NotImplementedError("chain verification not yet implemented")

    def query(
        self,
        ref: PointRef | None = None,
        actor: str | None = None,
        kinds: tuple[AuditEventKind, ...] = (),
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 1000,
    ) -> tuple[AuditRecord, ...]:
        """Query the log. Read-only; there is no mutating counterpart, deliberately.

        TODO: Build a filtered SELECT over the audit table, ordered by sequence descending.
        What's missing: nothing structural. Note the API surface asymmetry is intentional:
            this class has `record`, `query`, and `verify_chain`, and no `delete`,
            `update`, `purge`, or `redact`. Retention, if ever required, must be a
            documented out-of-band archival process, not a method here.
        Acceptance: filtering by ref returns only that point's records; limit is honoured.
        Depends on: `AuditLog.__init__`.
        """
        raise NotImplementedError("audit query not yet implemented")

    def export(self, path: Path, start: datetime | None = None, end: datetime | None = None) -> int:
        """Export records to a signed file for an auditor, returning the record count.

        TODO: Write records plus the chain hashes to a self-verifying file.
        What's missing: the export must include enough chain context for an external party
            to verify independently — the record before the range and the record after it —
            or the export proves only that the exported rows are internally consistent.
        Acceptance: an exported range verifies standalone; tampering with the export is
            detectable.
        Depends on: `verify_chain`, `query`.
        """
        raise NotImplementedError("audit export not yet implemented")
