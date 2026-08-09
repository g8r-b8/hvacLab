"""Trane tagging profile: Tracer SC+, Tracer UC400/UC600, Symbio 700/800.

Naming style is terse, uppercase, hyphen-separated abbreviations, usually
`<location><medium>-<quantity>` with an optional suffix:

    DA-T        discharge air temperature          -> discharge air temp sensor
    SA-T        supply air temperature             -> supply air temp sensor
    RA-T        return air temperature             -> return air temp sensor
    OA-T        outdoor air temperature            -> outside air temp sensor
    MA-T        mixed air temperature              -> mixed air temp sensor
    ZN-T        zone (space) temperature           -> zone air temp sensor
    ZN-SP       zone temperature setpoint          -> zone air temp sp
    SA-FLOW     supply airflow                     -> discharge air flow sensor
    SA-FLOW-SP  supply airflow setpoint            -> discharge air flow sp
    DPR-POS     damper position                    -> damper cmd
    VLV-POS     valve position                     -> valve cmd
    SF-S        supply fan status                  -> discharge fan run sensor
    SF-C        supply fan command                 -> discharge fan run cmd
    DA-SP       duct static pressure setpoint      -> discharge air pressure sp
    OCC-REQ     occupancy request                  -> occ point
    SPACE-CO2   space CO2                          -> zone air co2 sensor

Trane-specific traps a naive regex hits:

* **`-SP` is overloaded.** On a VAV, `ZN-SP` is a *setpoint*. On an AHU, `DA-SP` is
  *static pressure* — a sensor, not a setpoint. Disambiguation requires equipment
  context plus the object's units (degF -> setpoint; inH2O -> pressure).
* **`-S` vs `-C`.** Suffix `S` is status (sensor, BI), `C` is command (BO). Getting this
  backwards makes commands look readable and status look writable.
* **Symbio vs UC generations disagree.** Symbio 700 firmware moved to longer names
  (`DischAirTemp`) on some object sets, so this profile must handle both a terse and a
  verbose dialect under the same vendor id.
* **Tracer SC+ "exposed" points** are republished from downstream MS/TP devices with a
  prefix like `VAV_2_14/ZN-T`. That prefix is the equipment identity and is more reliable
  than the device name — parse it.
"""

from __future__ import annotations

from dataclasses import dataclass

from hvaclab.model.equip import EquipType
from hvaclab.semantic.profiles.base import DiscoveredObject, TagCandidate
from hvaclab.semantic.tags import TagSet

TRANE_VENDOR_IDS: tuple[int, ...] = (24,)
"""BACnet vendor identifiers claimed by Trane. Verify against the BACnet vendor registry."""


@dataclass(frozen=True, slots=True)
class TraneToken:
    """One parsed segment of a Trane point name, with its semantic role."""

    text: str
    role: str
    tags: tuple[str, ...] = ()


class TraneProfile:
    """Tagging profile for Trane Tracer SC+ / UC / Symbio controllers."""

    name: str = "trane"
    vendor_ids: tuple[int, ...] = TRANE_VENDOR_IDS

    def __init__(self, overrides: dict[str, TagSet] | None = None) -> None:
        """Build the profile and compile its abbreviation tables.

        TODO: Compile the location table (DA/SA/RA/OA/MA/EA/ZN/SPACE/UN), the quantity
            table (T/TEMP/FLOW/PRESS/SP/POS/CO2/RH/PWR), the suffix table (-S/-C/-SP/-CMD/
            -STPT/-POS/-ALM/-EN), and merge in persisted overrides.
        What's missing: the tables themselves, and a dialect flag so the terse UC style
            and the verbose Symbio style share one profile.
        Acceptance: constructing with no arguments succeeds and does no I/O.
        Depends on: `semantic.tags.TagVocabulary`.
        """
        raise NotImplementedError("Trane abbreviation tables not yet compiled")

    def claims(self, obj: DiscoveredObject) -> float:
        """Confidence that this object follows Trane naming, 0..1.

        TODO: Score BACnet vendor id (strong), device model strings ("Tracer", "Symbio",
            "UC400"), and naming style (uppercase, hyphenated, <=12 chars, known
            abbreviations) into a single score.
        What's missing: the weighting, and the case that matters commercially — a Trane
            controller integrated behind a Carrier i-Vu front end reports i-Vu's vendor id
            on the republished objects but keeps Trane names. Naming style must therefore
            be able to outvote vendor id.
        Acceptance: "DA-T" on vendor 24 scores > 0.9; "dischargeAirTemp" on vendor 24
            scores < 0.4 so the ALC profile can win.
        Depends on: `tokenize_name`.
        """
        raise NotImplementedError("Trane claim scoring not yet implemented")

    def tokenize_name(self, name: str) -> tuple[str, ...]:
        """Split a Trane point name into abbreviation tokens.

        TODO: Strip any `EQUIP/` republish prefix, split on hyphens and underscores,
            uppercase, and split any residual camelCase for the Symbio dialect.
        What's missing: handling of numeric suffixes that are instance disambiguators
            rather than semantics ("ZN-T-2" is the second zone sensor, not a different
            quantity) — those must be preserved as an instance token, not dropped and not
            treated as a tag.
        Acceptance: "VAV_2_14/ZN-T" -> ("ZN","T") with the prefix surfaced separately;
            "DischAirTemp" -> ("DISCH","AIR","TEMP").
        Depends on: nothing.
        """
        raise NotImplementedError("Trane name tokenizer not yet implemented")

    def tag_point(
        self,
        obj: DiscoveredObject,
        equip_hint: EquipType | None = None,
    ) -> TagCandidate | None:
        """Propose Haystack tags for one Trane object.

        TODO: Tokenize, map location and quantity tokens to markers, derive kind from the
            suffix and object type, derive unit from the BACnet units enum, and score.
        What's missing: the `-SP` disambiguation described in the module docstring — it
            needs `equip_hint` plus units plus commandability, and when those disagree the
            candidate's confidence must drop below the auto-apply threshold rather than
            picking a side.
        Acceptance: "DA-T" on an AHU yields {point, discharge, air, temp, sensor} at
            confidence > 0.9; "DA-SP" with inH2O units on an AHU yields pressure sensor,
            not a setpoint; "ZN-SP" with degF on a VAV yields zone air temp sp.
        Depends on: `tokenize_name`, `model.units`, `semantic.tags`.
        """
        raise NotImplementedError("Trane point tagging heuristics not yet implemented")

    def tag_equip(
        self,
        device_name: str,
        objects: tuple[DiscoveredObject, ...],
    ) -> TagCandidate | None:
        """Infer equipment type and identity from a Trane device name and its objects.

        TODO: Parse names like "VAV 2-14", "AHU-1", "UC400 VAV_2_14" for the type token,
            then corroborate against the object population.
        What's missing: the corroboration rules, which beat name parsing on ambiguous
            devices. A device with SA-FLOW, DPR-POS and ZN-T is a VAV whatever it is
            called; one with OA-T, MA-T, RA-T, SF-S and DA-SP is an AHU. Name-only
            inference should cap confidence around 0.7.
        Acceptance: "AHU-1" with airside AHU objects yields EquipType.AHU at > 0.9; a
            device named "CTRL-7" with VAV-shaped objects still yields VAV.
        Depends on: `tag_point`, `model.equip.EquipType`.
        """
        raise NotImplementedError("Trane equipment inference not yet implemented")

    def parse_republish_prefix(self, object_name: str) -> tuple[str | None, str]:
        """Split a Tracer SC+ republished name into (equipment prefix, bare point name).

        TODO: Detect the `EQUIP/POINT` (and `EQUIP.POINT`) forms the SC+ uses when
            exposing downstream MS/TP points on BACnet/IP, returning both halves.
        What's missing: nothing conceptually, but the payoff is large — the prefix is the
            SC+'s own equipment identity, so it gives equipment grouping for free AND
            tells the transport layer that this point is available from the supervisor's
            cache rather than requiring a route down to MS/TP.
        Acceptance: "VAV_2_14/ZN-T" -> ("VAV_2_14", "ZN-T"); "DA-T" -> (None, "DA-T").
        Depends on: `adapters.supervisor`.
        """
        raise NotImplementedError("Tracer SC+ republish prefix parsing not yet implemented")
