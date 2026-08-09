"""Engineering units: vocabulary, registry, and conversion.

Why this module is load-bearing: on a real site, two physically identical VAV boxes
from the same order can report in different units because a technician changed a
controller-level display preference, or because a Symbio replacement shipped with a
metric default. BACnet `units` (Enumerated, ASHRAE 135 Table, e.g. 64=degF, 62=degC)
is the authoritative hint, but it is frequently wrong or absent on Analog Value
objects that were created by a programmer rather than bound to hardware.

Policy: normalize at INGEST, never at display. The store holds one canonical unit per
quantity kind; the API renders whatever the caller asks for. Haystack `unit` tags are
emitted from the canonical value.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Quantity(StrEnum):
    """Physical quantity kind — the dimension a unit measures."""

    TEMPERATURE = "temperature"
    TEMPERATURE_DIFFERENTIAL = "temperatureDifferential"
    PRESSURE = "pressure"
    PRESSURE_DIFFERENTIAL = "pressureDifferential"
    FLOW_VOLUMETRIC = "flowVolumetric"
    FLOW_MASS = "flowMass"
    POWER = "power"
    ENERGY = "energy"
    HUMIDITY_RELATIVE = "humidityRelative"
    CONCENTRATION = "concentration"
    VELOCITY = "velocity"
    FREQUENCY = "frequency"
    VOLTAGE = "voltage"
    CURRENT = "current"
    TIME = "time"
    PERCENT = "percent"
    DIMENSIONLESS = "dimensionless"


class Unit(StrEnum):
    """Units we can ingest or emit.

    Values are Project Haystack unit symbols so they can be written straight into a
    Haystack `unit` tag or a Zinc number literal without a lookup table.
    """

    # Temperature
    DEG_F = "°F"
    DEG_C = "°C"
    KELVIN = "K"
    DELTA_DEG_F = "Δ°F"
    DELTA_DEG_C = "Δ°C"

    # Pressure
    IN_H2O = "inH₂O"
    PSI = "psi"
    PASCAL = "Pa"
    KILOPASCAL = "kPa"
    IN_HG = "inHg"

    # Flow
    CFM = "cfm"
    CFH = "cfh"
    L_PER_S = "L/s"
    M3_PER_H = "m³/h"
    GPM = "gal/min"
    LB_PER_H = "lb/h"
    KG_PER_H = "kg/h"

    # Power / energy
    WATT = "W"
    KILOWATT = "kW"
    TON_REFRIGERATION = "tonref"
    BTU_PER_H = "BTU/h"
    KILOWATT_HOUR = "kWh"
    BTU = "BTU"
    THERM = "therm"

    # Electrical
    VOLT = "V"
    AMPERE = "A"
    HERTZ = "Hz"

    # Air quality / misc
    PERCENT = "%"
    PERCENT_RH = "%RH"
    PPM = "ppm"
    FPM = "ft/min"
    M_PER_S = "m/s"
    SECOND = "s"
    MINUTE = "min"
    HOUR = "h"
    NONE = ""


@dataclass(frozen=True, slots=True)
class UnitSpec:
    """Static description of one unit.

    Affine conversion to the quantity's canonical unit is `canonical = value * scale + offset`.
    Offset is nonzero only for absolute temperature scales, which is exactly the case
    that a naive ratio-only converter gets catastrophically wrong (a 55 degF discharge
    air temp becoming 99 degC).
    """

    unit: Unit
    quantity: Quantity
    scale: float
    offset: float
    bacnet_enum: int | None
    aliases: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Measurement:
    """A magnitude bound to a unit. Arithmetic on bare floats is a bug waiting to happen."""

    value: float
    unit: Unit


class UnitRegistry:
    """Lookup surface for unit metadata, canonical units, and vendor/BACnet aliases."""

    def __init__(self, specs: tuple[UnitSpec, ...] | None = None) -> None:
        """Build a registry, defaulting to the built-in unit table.

        TODO: Populate the default `UnitSpec` table for every `Unit` member and index it
            by unit, by BACnet enumeration, and by lowercased alias.
        What's missing: the affine constants (degF: scale 5/9, offset -160/9 to degC),
            correct ASHRAE 135 `units` enumerations (62=degC, 64=degF, 63=degK,
            98=percent, 96=ppm, 84=inH2O... verify against bacpypes3's EngineeringUnits
            rather than trusting memory), and the alias set vendors actually emit
            ("DEG F", "Deg-F", "F", "degreesFahrenheit", "IN-WC", "in wg", "CFM").
        Acceptance: `UnitRegistry()` constructs with no arguments; every `Unit` member
            resolves via `spec()`; no two units in one quantity claim the same alias.
        Depends on: nothing — this is the base of the model.
        """
        raise NotImplementedError("unit spec table not yet populated")

    def spec(self, unit: Unit) -> UnitSpec:
        """Return the static spec for a unit.

        TODO: Return the indexed `UnitSpec`, raising `KeyError` for unknown units.
        What's missing: the index itself.
        Acceptance: round-trips for every `Unit` member.
        Depends on: `UnitRegistry.__init__`.
        """
        raise NotImplementedError("unit spec index not yet built")

    def canonical_unit(self, quantity: Quantity) -> Unit:
        """Return the canonical storage unit for a quantity.

        TODO: Map each `Quantity` to the one unit the historian and tag store persist.
        What's missing: the policy decision itself. Proposal: SI-leaning but
            field-friendly — degC for temperature, Pa for pressure, L/s for volumetric
            flow, W for power, %RH for humidity. Emitting degF at the API boundary is a
            rendering concern, not a storage concern.
        Acceptance: every `Quantity` member returns a unit whose spec has that quantity
            and `scale == 1.0, offset == 0.0`.
        Depends on: `spec`.
        """
        raise NotImplementedError("canonical unit policy not yet decided")

    def from_bacnet(self, bacnet_units_enum: int) -> Unit | None:
        """Resolve a BACnet `units` property enumeration to a `Unit`.

        TODO: Look up the ASHRAE 135 enumeration; return None when unmapped.
        What's missing: coverage of the enumerations that actually appear on Trane and
            ALC gear, and a deliberate None (not a guess) for proprietary values above
            255, which vendors do use.
        Acceptance: 64 -> DEG_F, 62 -> DEG_C, 98 -> PERCENT; an unmapped enum returns
            None and does not raise.
        Depends on: `UnitRegistry.__init__`.
        """
        raise NotImplementedError("BACnet units enumeration table not yet built")

    def from_text(self, text: str) -> Unit | None:
        """Resolve a free-text unit string (vendor label, trend header) to a `Unit`.

        TODO: Normalize case/whitespace/punctuation and match against the alias index.
        What's missing: the alias index, plus a decision on ambiguity — "F" could be
            Fahrenheit or Farad; in an HVAC corpus, prefer Fahrenheit but record the
            ambiguity so the tagging profile can down-weight its confidence.
        Acceptance: "DEG F", "deg-f", "°F" all resolve to DEG_F; "" resolves to
            Unit.NONE; garbage returns None.
        Depends on: `UnitRegistry.__init__`.
        """
        raise NotImplementedError("unit alias index not yet built")

    def quantity_of(self, unit: Unit) -> Quantity:
        """Return the quantity a unit measures.

        TODO: Delegate to `spec(unit).quantity`.
        What's missing: the spec table.
        Acceptance: DEG_F -> TEMPERATURE, DELTA_DEG_F -> TEMPERATURE_DIFFERENTIAL.
        Depends on: `spec`.
        """
        raise NotImplementedError("unit spec index not yet built")


class UnitConverter:
    """Converts measurements between units of the same quantity."""

    def __init__(self, registry: UnitRegistry) -> None:
        """Bind a converter to a registry.

        TODO: Store the registry; optionally memoize (scale, offset) pairs per unit pair.
        What's missing: nothing beyond the registry.
        Acceptance: constructing does no work that can raise.
        Depends on: `UnitRegistry`.
        """
        raise NotImplementedError("converter construction not yet implemented")

    def convert(self, measurement: Measurement, to: Unit) -> Measurement:
        """Convert a measurement to a target unit.

        TODO: Compose the two affine transforms via the canonical unit and return a new
            `Measurement`. Raise `IncompatibleUnitsError` on a quantity mismatch.
        What's missing: the composition, and the guard that makes DELTA_DEG_F and DEG_F
            non-interchangeable — a 10 degF rise is 5.6 degC, but 10 degF is -12.2 degC.
            Conflating them is the single most common HVAC unit bug.
        Acceptance: 55 DEG_F -> 12.78 DEG_C (1e-9); 10 DELTA_DEG_F -> 5.556 DELTA_DEG_C;
            DEG_F -> PASCAL raises; convert to the same unit is identity, not a rounding.
        Depends on: `UnitRegistry.spec`, `UnitRegistry.canonical_unit`.
        """
        raise NotImplementedError("affine unit conversion not yet implemented")

    def normalize(self, measurement: Measurement) -> Measurement:
        """Convert a measurement into its quantity's canonical unit.

        TODO: Look up the canonical unit for the measurement's quantity and convert.
        What's missing: nothing beyond `convert` and `canonical_unit`.
        Acceptance: normalizing an already-canonical measurement returns an equal value;
            normalize is idempotent.
        Depends on: `convert`, `UnitRegistry.canonical_unit`.
        """
        raise NotImplementedError("canonical normalization not yet implemented")

    def infer_unit(
        self,
        bacnet_units_enum: int | None,
        text_hint: str | None,
        value_samples: tuple[float, ...],
        expected_quantity: Quantity | None,
    ) -> tuple[Unit | None, float]:
        """Best-effort unit inference with a confidence score, for untrusted AV objects.

        TODO: Rank evidence — BACnet enum (strong), text hint (medium), value range
            plausibility against the expected quantity (weak tiebreaker) — and return
            (unit, confidence in 0..1).
        What's missing: the plausibility bands. A discharge air temp of 55 is far more
            likely degF than degC; a space temp of 22 is far more likely degC than degF.
            These bands must be per-`Quantity` and per-point-role, so this signature may
            need to take a tag hint once profiles exist.
        Acceptance: enum present and self-consistent yields confidence >= 0.9; range-only
            inference never exceeds 0.6; total absence of evidence returns (None, 0.0).
        Depends on: `UnitRegistry.from_bacnet`, `UnitRegistry.from_text`.
        """
        raise NotImplementedError("unit inference heuristics not yet implemented")


class IncompatibleUnitsError(ValueError):
    """Raised when a conversion is attempted between different quantities."""
