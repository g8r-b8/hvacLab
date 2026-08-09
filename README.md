# hvacLab

A vendor-neutral frontend/backend for **commercial HVAC building automation systems (BAS)**,
targeting Trane (Tracer SC+, Symbio) and Carrier (i-Vu / Automated Logic WebCTRL).

Both vendors speak BACnet natively, so there is nothing to reverse-engineer. The hard problems
are semantics, bandwidth, write safety, and life-safety liability.

> **Day-one scope is READ-ONLY.** The write path is scaffolded but structurally gated:
> a write cannot reach an adapter without traversing `hvaclab.safety`.

---

## Architecture (layered stack)

```
                    ┌──────────────────────────────────────────────┐
                    │  api/                                        │
                    │  FastAPI app  ·  Project Haystack REST ops   │
                    │  about read hisRead watchSub/Poll pointWrite │
                    └───────────────┬──────────────────────────────┘
                                    │
        ┌───────────────────────────┴───────────────────────────┐
        │                                                       │
┌───────▼─────────────────────┐                    ┌────────────▼───────────────┐
│  store/                     │                    │  semantic/                 │
│  tagstore  (entities+tags)  │◄───tags/topology───┤  tags · filter · profiles  │
│  historian (DuckDB trends)  │                    │  export: haystack, brick   │
└───────┬─────────────────────┘                    └────────────┬───────────────┘
        │                                                       │
        │                     ┌─────────────────────────────────┘
        │                     │  model/  (the canonical internal model)
        │                     │  units point equip site topology alarm history
        │                     │  ── retains 223P-shaped topology, not just tags ──
        │                     └─────────────────────────────────┐
        │                                                       │
┌───────▼───────────────────────────────────────────────────────▼───────────────┐
│  transport/   budget (MS/TP math) · polling (adaptive) · cov (slot budgeting)  │
└───────────────────────────────┬───────────────────────────────────────────────┘
                                │
┌───────────────────────────────▼───────────────────────────────────────────────┐
│  safety/   blocklist (UUKL deny-by-default) → write_gate (priority 1-16) →     │
│            audit (immutable log).  ALL writes funnel here. No bypass.          │
└───────────────────────────────┬───────────────────────────────────────────────┘
                                │
┌───────────────────────────────▼───────────────────────────────────────────────┐
│  adapters/                                                                    │
│   sim (day-one target)  supervisor (PREFERRED read path)  bacnet  modbus      │
└───────────────────────────────┬───────────────────────────────────────────────┘
                                │
        BACnet/IP ─── Tracer SC+ / i-Vu supervisor cache ─── BACnet MS/TP RS-485
                                                              (VAVs, FCUs, ...)
```

---

## The four hard problems

### 1. Semantic normalization

Trane exposes a discharge air temperature as `AI:12 "DA-T"`. Automated Logic exposes the same
physical sensor as `AV:301 "dischargeAirTemp"`. Project Haystack tags are the normalization
target: `point discharge air temp sensor equipRef->@ahu-1`.

Per-vendor **tagging profiles** (`semantic/profiles/`) map discovered BACnet objects to tag sets
using naming heuristics, object-type priors, unit priors, and equipment context. Realistic
heuristic coverage is **70–85%**; the tail is not a bug, it is a workflow — unmatched and
low-confidence candidates land in a `ReviewQueue` for a human, and accepted corrections feed
back as profile overrides.

Units differ per controller on identical equipment (one VAV in `degF`, its twin in `degC`), so
`model/units.py` normalizes at ingest, not at display.

### 2. MS/TP bandwidth

BACnet terminal units hang off RS-485 trunks at 9600–76800 baud. Token-passing gives roughly
**20–40 point reads/sec on a healthy 38.4k trunk**. Naive per-point polling saturates the trunk
and starves the native BAS control loops — the fastest way to get thrown off a customer site.

Mitigations, in priority order:

1. **Read the supervisor's cache over BACnet/IP** (`adapters/supervisor.py`) instead of routing
   down to MS/TP at all. This is the preferred path and usually costs the trunk nothing.
2. **ReadPropertyMultiple batching**, bounded by the device's max APDU length accepted
   (commonly 480 or 128 bytes on MS/TP) and max segments.
3. **COV subscriptions** — but devices support only ~4–8 concurrent subscriptions, and
   lifetimes must be renewed before expiry (`transport/cov.py`).
4. **TrendLog + ReadRange** for bulk history instead of replaying polls.
5. **Adaptive poll rates by point volatility** (`transport/polling.py`): a space temp does not
   need the cadence of a damper command.

Also watch `max_master`: the default of 127 against an actual highest MAC of, say, 12 burns
real trunk time on Poll For Master frames. `transport/budget.py` models this explicitly.

### 3. Write safety

The BACnet priority array has 16 slots and **no global registry of who claimed what**. A write
that is never released (write `null` at the same priority) leaves the point overridden forever.
Physical consequences: short-cycled compressors, frozen coils, ASHRAE 62.1 ventilation
non-compliance.

`safety/write_gate.py` tracks every claim, requires an explicit release, and detects orphaned
overrides. `safety/audit.py` records every attempt — allowed or denied — immutably.

### 4. UL 864 / UUKL life safety

Smoke control equipment is listed **as-configured** under UL 864 category UUKL. Writing to a
participating point compromises the listing, with AHJ, insurance, and criminal liability
exposure. This cannot be a UI toggle — `safety/blocklist.py` is a structural, deny-by-default
deny-list at the adapter boundary, seeded from the project's smoke control sequence matrix. A
point of unknown UUKL status is treated as blocked, not as allowed.

---

## Future-proofing: tags today, Brick and 223P later

Haystack tags are the day-one output, but the internal model deliberately keeps more than tags:
`model/topology.py` retains **Substances** (air, water, electricity), **ConnectionPoints** with
direction (inlet/outlet), **Connections**, **Junctions**, and served **DomainSpaces** — the
shape ASHRAE 223P needs. Brick Schema and 223P can therefore be emitted from the same store
later without a model rewrite. `semantic/export/brick.py` exists in phase 1 purely to prove
the model is translatable.

---

## Phase plan

| Phase | Contents |
| --- | --- |
| **1 — Skeleton (this commit)** | Every file, every typed signature, substantive docstrings, `NotImplementedError` bodies. Fixtures are real data. |
| **2 — Sim loop** | `model/*` value objects, `SimAdapter` replay from fixtures, `tagstore`, Haystack `filter`, Zinc/Hayson export. No hardware. |
| **3 — Read on iron** | `bacnet.py` (Who-Is/I-Am, RPM), `supervisor.py` cached reads, `budget.py` + `polling.py`, `cov.py`, `historian.py` backfill via ReadRange. |
| **4 — Semantics at scale** | Trane + ALC profiles, confidence scoring, `ReviewQueue` UI, override persistence. |
| **5 — Gated writes** | `blocklist.py` from a real smoke control matrix, `write_gate.py` claim/release, `audit.py`, `pointWrite` REST op. Commissioning-only, never automatic. |
| **6 — Ontology export** | Brick + 223P emission, round-trip validation against the internal topology. |

---

## Development

```bash
uv sync
uv run pytest
uv run ruff check .
uv run mypy
```

Pickup points for phase 2:

```bash
grep -rn "NotImplementedError\|TODO:" src/
```
