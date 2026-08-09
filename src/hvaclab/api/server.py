"""FastAPI application factory.

Wires the store, historian, adapters, poller, and safety layer into an HTTP server that
speaks Project Haystack REST, plus a small set of non-standard endpoints for the things
Haystack has no vocabulary for (trunk budget assessments, tagging review queue, orphaned
override reports).

Startup ordering matters and is a safety property, not a preference:

1. Load the life safety blocklist. If it fails to load, refuse to start.
2. Construct the `WriteGate` in read-only mode.
3. Open the historian and audit log; verify the audit chain.
4. Load the tag store.
5. Construct adapters — simulator by default, real ones only when explicitly configured.
6. Start the poller LAST, so nothing touches a trunk before the budget is known.

Shutdown ordering is the reverse, and `CovManager.unsubscribe_all` must run even on
SIGTERM — a container killed without unsubscribing leaves COV slots held on terminal
units for the full lifetime.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class ServerConfig:
    """Deployment configuration.

    `enable_writes` defaults to False and is deliberately not exposed via any API — it can
    only be set at deployment, and even then the write path still traverses the blocklist,
    the gate, and the audit log.
    """

    db_path: Path
    fixture_path: Path | None = None
    use_simulator: bool = True
    site_timezone: str = "UTC"
    blocklist_path: Path | None = None
    enable_writes: bool = False
    host: str = "127.0.0.1"
    port: int = 8080
    auth_required: bool = True
    cors_origins: tuple[str, ...] = ()
    log_level: str = "INFO"


def create_app(config: ServerConfig) -> Any:
    """Build the FastAPI application with all routes and lifecycle hooks.

    TODO: Construct the app, wire the Haystack op routes (GET and POST at
        `/api/{op}`), the non-standard diagnostic routes, and the startup/shutdown
        handlers in the order documented in the module docstring.
    What's missing: the startup ordering must be enforced, not merely followed — a failure
        to load the blocklist must abort startup rather than continue with an empty one,
        because an empty blocklist plus `allow_unknown` would silently mean "everything is
        writable". Return type is `Any` only because FastAPI is not imported at module
        scope; narrow it to `FastAPI` in phase 2.
    Acceptance: `create_app` with a simulator config starts, serves `about`, and reports
        `read_only` in its `ops` doc; a missing blocklist file aborts startup.
    Depends on: `api.haystack_rest.ApiContext`, `store.tagstore.TagStore`,
        `store.historian.Historian`, `safety.blocklist.LifeSafetyBlocklist`,
        `safety.write_gate.WriteGate`, `adapters.sim.SimAdapter`.
    """
    raise NotImplementedError("FastAPI app factory not yet implemented")


def build_context(config: ServerConfig) -> Any:
    """Construct the `ApiContext` — store, historian, gate — in the safe order.

    TODO: Load blocklist, open audit log and verify its chain, open historian, load tag
        store, construct the gate, and return the context.
    What's missing: audit chain verification at startup. A broken chain means corruption or
        tampering and must be surfaced immediately, not discovered during an incident
        review months later.
    Acceptance: a context built with a corrupt audit log raises at startup naming the bad
        sequence number.
    Depends on: `safety.audit.AuditLog.verify_chain`, `safety.blocklist.load_from_matrix`.
    """
    raise NotImplementedError("context construction not yet implemented")


async def startup(app: Any, config: ServerConfig) -> None:
    """Startup hook: connect adapters, discover, tag, and start the poller last.

    TODO: Connect adapters, run discovery, apply tagging profiles, register points with
        the poller, assess trunk budgets, then start the poll loop.
    What's missing: budget assessment MUST complete before the poller starts. Starting a
        poll loop before knowing the trunk budget is exactly the failure this whole
        transport layer exists to prevent, and the ordering is the only thing enforcing it.
    Acceptance: with the simulator, startup discovers devices, tags them, and begins
        polling within budget; the trunk assessment appears in the logs before the first
        poll.
    Depends on: `transport.budget.BudgetRegistry.assess_all`,
        `transport.polling.AdaptivePoller`, `semantic.profiles.base.run_profile`.
    """
    raise NotImplementedError("startup sequence not yet implemented")


async def shutdown(app: Any) -> None:
    """Shutdown hook: unsubscribe COV, release claims, flush, close.

    TODO: Stop the poller, call `CovManager.unsubscribe_all`, release any active write
        claims, flush the historian, and close the audit log.
    What's missing: this must run on SIGTERM, not only on a graceful HTTP shutdown, and
        releasing active write claims is the part with physical consequences — a process
        that dies holding an override leaves a valve where it put it, indefinitely.
    Acceptance: SIGTERM releases every COV slot and every active claim; the historian's
        buffered samples are durable.
    Depends on: `transport.cov.CovManager.unsubscribe_all`,
        `safety.write_gate.WriteGate.active_claims`, `store.historian.Historian.close`.
    """
    raise NotImplementedError("shutdown sequence not yet implemented")


def main() -> None:
    """Console entry point: parse arguments, build the app, run uvicorn.

    TODO: Parse CLI arguments into a `ServerConfig`, create the app, and run uvicorn.
    What's missing: the CLI must default to the SIMULATOR. A tool that connects to real
        BACnet gear by default is a tool that will one day be run on the wrong network by
        someone who did not mean to. Real adapters require explicit configuration and an
        explicit flag.
    Acceptance: `hvaclab` with no arguments starts against the bundled fixtures and never
        opens a BACnet socket.
    Depends on: `create_app`, `ServerConfig`.
    """
    raise NotImplementedError("CLI entry point not yet implemented")
