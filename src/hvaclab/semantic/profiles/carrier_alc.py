"""Carrier / Automated Logic tagging profile: i-Vu, WebCTRL, LGR/SE/ZN controllers.

ALC's Eikon-programmed controllers expose long descriptive camelCase names, because the
name is usually the microblock label from the graphical control program:

    dischargeAirTemp        -> discharge air temp sensor
    supplyAirTemp           -> supply air temp sensor
    returnAirTemp           -> return air temp sensor
    outdoorAirTemp          -> outside air temp sensor
    mixedAirTemp            -> mixed air temp sensor
    zoneTemp                -> zone air temp sensor
    coolingSetpoint         -> zone air temp cooling sp
    heatingSetpoint         -> zone air temp heating sp
    supplyAirFlow           -> discharge air flow sensor
    airflowSetpoint         -> discharge air flow sp
    damperPosition          -> damper cmd
    coolingValveCommand     -> chilled water valve cmd
    supplyFanStatus         -> discharge fan run sensor
    supplyFanCommand        -> discharge fan run cmd
    ductStaticPressure      -> discharge air pressure sensor
    zoneCO2                 -> zone air co2 sensor
    occupancyStatus         -> occupied sensor

ALC-specific traps:

* **Everything is an AV.** ALC programs frequently expose calculated and even physical
  values as Analog Value objects rather than Analog Input/Output, so `object_type` is a
  much weaker signal than on Trane, and commandability does not imply "safe to write".
* **Units are often absent or `no-units`** on AVs, because the microblock carried the
  unit implicitly. Unit inference from name + value range does more work here than on any
  other vendor.
* **Names are not unique across a controller.** Two microblocks can both be
  `zoneTemp` for different zones on a multi-zone LGR; only the object instance
  distinguishes them, so equipment attribution must come from the i-Vu tree path, not
  the name.
* **i-Vu tree paths** (`#trane_hq/bldg1/floor2/vav_2_14/zoneTemp`) are the richest
  structural signal any vendor gives us — they hand over the whole site hierarchy. Parse
  them when the adapter can retrieve them.
* **WebCTRL "display name" vs "reference name"** differ; the reference name is stable and
  programmatic, the display name is what the operator sees and gets edited. Prefer the
  reference name for identity, the display name for `dis`.
"""

from __future__ import annotations

from dataclasses import dataclass

from hvaclab.model.equip import EquipType
from hvaclab.semantic.profiles.base import DiscoveredObject, TagCandidate
from hvaclab.semantic.tags import TagSet

ALC_VENDOR_IDS: tuple[int, ...] = (24, 27)
"""Vendor ids seen on Carrier/ALC gear. Verify against the BACnet vendor registry; the
Carrier and Automated Logic registrations differ and i-Vu republishes under its own."""


@dataclass(frozen=True, slots=True)
class IvuTreePath:
    """A parsed i-Vu / WebCTRL tree path — free site hierarchy when available."""

    system: str | None
    building: str | None
    floor: str | None
    equip: str | None
    point: str
    raw: str


class CarrierAlcProfile:
    """Tagging profile for Carrier i-Vu and Automated Logic WebCTRL controllers."""

    name: str = "carrier_alc"
    vendor_ids: tuple[int, ...] = ALC_VENDOR_IDS

    def __init__(self, overrides: dict[str, TagSet] | None = None) -> None:
        """Build the profile and compile its camelCase word tables.

        TODO: Compile word tables for location (discharge/supply/return/outdoor/outside/
            mixed/exhaust/zone/space), quantity (temp/flow/pressure/humidity/co2/power),
            role (setpoint/command/status/position/enable/alarm), and equipment
            (ahu/vav/fcu/chiller/boiler/pump), then merge persisted overrides.
        What's missing: the tables, plus an ALC-specific synonym map — ALC integrators use
            "outdoor" where Haystack uses "outside", and "discharge"/"supply" are used
            interchangeably for the same duct on different jobs.
        Acceptance: constructing with no arguments succeeds and does no I/O.
        Depends on: `semantic.tags.TagVocabulary`.
        """
        raise NotImplementedError("ALC word tables not yet compiled")

    def claims(self, obj: DiscoveredObject) -> float:
        """Confidence that this object follows ALC naming, 0..1.

        TODO: Score device model strings ("i-Vu", "WebCTRL", "LGR", "SE6104", "ZN341"),
            camelCase shape, name length, and known ALC vocabulary words.
        What's missing: the weighting. Because ALC and Trane can share a vendor id in
            integrated jobs, naming shape must dominate — a name with a lowercase first
            letter, an internal uppercase, and no hyphens is near-conclusive ALC.
        Acceptance: "dischargeAirTemp" scores > 0.9; "DA-T" scores < 0.3.
        Depends on: `tokenize_name`.
        """
        raise NotImplementedError("ALC claim scoring not yet implemented")

    def tokenize_name(self, name: str) -> tuple[str, ...]:
        """Split a camelCase ALC name into lowercase word tokens.

        TODO: Split on case transitions, digits, underscores and spaces; lowercase the
            result.
        What's missing: acronym handling. Naive case-transition splitting turns "zoneCO2"
            into ("zone","c","o","2") and "supplyAirVFDSpeed" into nonsense; the splitter
            must treat runs of uppercase as single tokens, with the last uppercase letter
            starting a new word when followed by lowercase.
        Acceptance: "zoneCO2" -> ("zone","co2"); "supplyAirVFDSpeed" ->
            ("supply","air","vfd","speed"); "dischargeAirTemp" ->
            ("discharge","air","temp").
        Depends on: nothing.
        """
        raise NotImplementedError("ALC camelCase tokenizer not yet implemented")

    def tag_point(
        self,
        obj: DiscoveredObject,
        equip_hint: EquipType | None = None,
    ) -> TagCandidate | None:
        """Propose Haystack tags for one ALC object.

        TODO: Tokenize, map words to markers via the word tables, derive kind from role
            words plus commandability, infer unit, and score.
        What's missing: unit inference weighting. Because ALC AVs so often report
            `no-units`, this profile must lean on `UnitConverter.infer_unit` with the
            expected quantity from the name — and must NOT let a missing unit veto an
            otherwise strong name match. Also: `object_type` contributes almost nothing
            here, so do not weight it as heavily as in the Trane profile.
        Acceptance: "dischargeAirTemp" yields {point, discharge, air, temp, sensor} at
            > 0.9 even with units absent; "coolingValveCommand" yields
            {point, chilled, water, valve, cmd}.
        Depends on: `tokenize_name`, `model.units.UnitConverter.infer_unit`.
        """
        raise NotImplementedError("ALC point tagging heuristics not yet implemented")

    def tag_equip(
        self,
        device_name: str,
        objects: tuple[DiscoveredObject, ...],
    ) -> TagCandidate | None:
        """Infer equipment type and identity from an ALC device name and its objects.

        TODO: Parse the device name and, when available, the i-Vu tree path's equipment
            segment; corroborate against the object population as in the Trane profile.
        What's missing: multi-equipment controllers. A single LGR can host several VAVs'
            logic, so this may need to return several equipment candidates rather than
            one — flag that as a signature change for phase 4 rather than forcing one
            equipment per device.
        Acceptance: a device whose objects are all zone/airflow/damper yields VAV; a
            device with mixed/return/outdoor air and fan status yields AHU.
        Depends on: `parse_tree_path`, `tag_point`.
        """
        raise NotImplementedError("ALC equipment inference not yet implemented")

    def parse_tree_path(self, path: str) -> IvuTreePath | None:
        """Parse an i-Vu / WebCTRL tree path into its hierarchy segments.

        TODO: Split a path like "#hq/bldg1/floor2/vav_2_14/zoneTemp" into system,
            building, floor, equipment, and point.
        What's missing: tolerance for variable depth. Real i-Vu trees are not uniformly
            five levels; some jobs have no floor level, some have an extra area level. Map
            by recognizing segment patterns from the right (the last segment is always the
            point) rather than by fixed position.
        Acceptance: a five-segment path fills every field; a three-segment path fills
            point and equip and leaves the rest None; a non-path string returns None.
        Depends on: `model.site`.
        """
        raise NotImplementedError("i-Vu tree path parsing not yet implemented")
