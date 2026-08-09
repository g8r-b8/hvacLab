"""Phase 1 smoke tests.

Deliberately minimal. The point of the skeleton commit is that every module *imports*
without side effects — no socket binding, no file reads, no network discovery at import
time. Real behavioural tests land in phase 2 alongside each implemented function.

The fixture equivalence test is the exception: the fixtures are data, not logic, so their
invariant can be asserted now, and it is the invariant the whole normalization layer will
be measured against.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"

MODULES = [
    "hvaclab",
    "hvaclab.model",
    "hvaclab.model.units",
    "hvaclab.model.point",
    "hvaclab.model.equip",
    "hvaclab.model.site",
    "hvaclab.model.topology",
    "hvaclab.model.alarm",
    "hvaclab.model.history",
    "hvaclab.semantic",
    "hvaclab.semantic.tags",
    "hvaclab.semantic.filter",
    "hvaclab.semantic.profiles",
    "hvaclab.semantic.profiles.base",
    "hvaclab.semantic.profiles.trane",
    "hvaclab.semantic.profiles.carrier_alc",
    "hvaclab.semantic.export",
    "hvaclab.semantic.export.haystack",
    "hvaclab.semantic.export.brick",
    "hvaclab.adapters",
    "hvaclab.adapters.base",
    "hvaclab.adapters.sim",
    "hvaclab.adapters.bacnet",
    "hvaclab.adapters.supervisor",
    "hvaclab.adapters.modbus",
    "hvaclab.safety",
    "hvaclab.safety.blocklist",
    "hvaclab.safety.write_gate",
    "hvaclab.safety.audit",
    "hvaclab.transport",
    "hvaclab.transport.budget",
    "hvaclab.transport.polling",
    "hvaclab.transport.cov",
    "hvaclab.store",
    "hvaclab.store.tagstore",
    "hvaclab.store.historian",
    "hvaclab.api",
    "hvaclab.api.haystack_rest",
    "hvaclab.api.server",
]


def test_package_imports() -> None:
    """The package imports and exposes a version."""
    import hvaclab

    assert hvaclab.__version__


@pytest.mark.parametrize("module_name", MODULES)
def test_every_module_imports(module_name: str) -> None:
    """Every module imports cleanly. Imports must never do I/O or raise."""
    assert importlib.import_module(module_name) is not None


def test_fixtures_describe_equivalent_equipment() -> None:
    """The Trane and Carrier fixtures describe the same building under different names.

    This is the invariant the entire semantic normalization layer exists to exploit: the
    same equipment ids and the same logical point ids, expressed in two vendor dialects.
    """
    trane = json.loads((FIXTURES / "trane_tracer_sc.json").read_text())
    carrier = json.loads((FIXTURES / "carrier_ivu.json").read_text())

    assert trane["site"]["id"] == carrier["site"]["id"]
    assert {e["id"] for e in trane["equips"]} == {e["id"] for e in carrier["equips"]}
    assert {s["id"] for s in trane["spaces"]} == {s["id"] for s in carrier["spaces"]}
    assert {o["logical_id"] for o in trane["objects"]} == {
        o["logical_id"] for o in carrier["objects"]
    }


def test_fixtures_use_different_vendor_naming() -> None:
    """The fixtures must not accidentally converge on the same point names."""
    trane = json.loads((FIXTURES / "trane_tracer_sc.json").read_text())
    carrier = json.loads((FIXTURES / "carrier_ivu.json").read_text())

    trane_names = {o["object_name"] for o in trane["objects"]}
    carrier_names = {o["object_name"] for o in carrier["objects"]}

    assert not trane_names & carrier_names, "fixtures share point names; normalization is untested"


def test_life_safety_points_present_in_both_fixtures() -> None:
    """Both fixtures carry UUKL-listed points for the blocklist to find."""
    for name in ("trane_tracer_sc.json", "carrier_ivu.json"):
        doc = json.loads((FIXTURES / name).read_text())
        assert doc["life_safety"]["blocked_logical_ids"]
        assert doc["life_safety"]["source_document"]
