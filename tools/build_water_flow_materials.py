"""Write `water-flow-materials.json`: which material each water flow is made of.

The material is the axis the model was missing.  `sea water`, `cooling water`,
`brine` and unqualified water are all H2O and all CAS 7732-18-5, so the only
thing separating them was a name no field held -- and `pipeline/deduplication.py`
signs on fields, so a difference held in none of them collapses.  See
`plans/water-taxonomy.md`.

**Nothing here is inferred at run time.**  The layering could read a flow's name
and guess, the way `detect_origin_qualifier` does for qualifiers, and that is
exactly what this file exists to avoid: no algorithm reads `Water, salt, sole`
and knows it is brine.  Each row is a curated assignment of one source flow to
one concept in `environmental-materials.json`, and the layering does a lookup.

The rows are generated from the vendor files, so the uuid, name, unit and
context columns are the vendor's and cannot drift from them by transcription.
The `node` and `match` columns are the curated part, and they come from the
rules below -- which is where a reviewer should look, because everything else is
mechanical.

**Every list this project merges is covered, or its water rows fall back to a
registry number twelve substances share.**  EF 3.1 and the five ecoinvent
releases were assigned when the scheme was built; bafu was not, and its 290
water rows arrived at a merge that could only see 7732-18-5.  253 of them were
reported `multiple-flow-object-candidates` and placed nowhere, which is 9.6% of
that list ([#86](https://github.com/brightway-labs/brightway-flows/issues/86)).
A list added to `SOURCE_KEYS` is one line; a list left out is silent.

`match` records how well the source flow and the concept agree:

``exact``
    The source names the material.  `Water, lake` is lake water.
``close``
    The material is read off the context rather than the name.  Every `Water`
    row in an air context is water vapour, because water in the air domain is
    vapour or rain -- true, and our reading rather than the vendor's.
``broad``
    The source is genuinely unspecific and lands on a parent concept.  EF's
    `water` is water, not any particular kind of it.

Usage::

    uv run python tools/build_water_flow_materials.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from brightway_flows.simapro_names import name_without_unit_suffix
from brightway_flows.sources import registered_source_list

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "src" / "brightway_flows" / "data"
OUTPUT_PATH = DATA_DIR / "water-flow-materials.json"

#: Every registered list, read through the source registry rather than by a
#: path spelled here, so that what this classifies is what the merge loads.
#: bafu's adapter takes the geography out of the name at extraction (#65), and
#: a table built from the raw vendor export would be keyed on names -- `Water,
#: RER` -- that no longer exist by the time anything reads it.  The registry
#: also supplies the `source` column: the merge looks a row up under
#: :attr:`SourceList.source_label`, so writing anything else here produces a
#: table that loads and never matches.
SOURCE_KEYS = (
    "EF-3.1",
    "ecoinvent-3.8",
    "ecoinvent-3.9.1",
    "ecoinvent-3.10.1",
    "ecoinvent-3.11",
    "ecoinvent-3.12",
    "bafu-2026-v1",
    "agribalyse-3.2",
)

#: EF 3.1, by flow name.  Where one name spans several contexts the value is a
#: callable taking the context and returning `(node, match)`.
EF_BY_NAME: dict[str, Any] = {
    "Water, salt, sole": ("brine", "exact"),
    "Water Cooling sea": ("cooling_water", "exact"),
    "Water from cooling": ("cooling_water", "exact"),
    "Water to Cooling": ("cooling_water", "exact"),
    "freshwater": ("fresh_water", "exact"),
    "Green water": ("green_water", "exact"),
    "ground water": ("groundwater", "exact"),
    "lake water": ("lake_water", "exact"),
    "Water (rain water)": ("rainwater", "exact"),
    "river water": ("river_water", "exact"),
    "sea water": ("sea_water", "exact"),
    "Water from turbine": ("turbine_water", "exact"),
    "Water to turbine": ("turbine_water", "exact"),
    "water vapour": ("water_vapour", "exact"),
    "Water, in air": ("water_vapour", "exact"),
    "Water (evapotranspiration)": ("water_vapour", "close"),
}

#: ecoinvent, by flow name, with the same shape.
ECOINVENT_BY_NAME: dict[str, Any] = {
    "Water, salt, sole": ("brine", "exact"),
    "Water, cooling, unspecified natural origin": ("cooling_water", "exact"),
    "Water, green": ("green_water", "exact"),
    "Water, well, in ground": ("groundwater", "exact"),
    "Water, lake": ("lake_water", "exact"),
    "Water, river": ("river_water", "exact"),
    "Water, salt, ocean": ("sea_water", "exact"),
    "Water, turbine use, unspecified natural origin": ("turbine_water", "exact"),
    "Water, in air": ("water_vapour", "exact"),
    "Fresh water (obsolete)": ("water", "broad"),
    "Salt water (obsolete)": ("water", "broad"),
}

#: bafu, by flow name, with the same shape.  Six of the eleven are names
#: ecoinvent ships too and are assigned the concept ecoinvent's row is
#: assigned, because two lists spelling a flow the same way and meaning
#: different things is not something a curator should have to discover from a
#: merge report.
#:
#: The other five name materials the taxonomy already carries *for this list*:
#: `environmental-materials.json` cites bafu's `Chemically polluted water`,
#: `Waste water` and `Water, process, surface` as the reason `contaminated
#: water`, `waste water` and `surface water` are in the scheme at all, and
#: those three concepts have had no flow on them since -- the concepts were
#: added and the rows were never assigned to them.  `Water, well` is
#: ecoinvent's `Water, well, in ground` with the compartment left out of the
#: name, and `Water, fossil` is the water ecoinvent reaches by putting the
#: withdrawal in a `fossil well` compartment: fossil water *is* fossil
#: groundwater, and bafu is the first list to say so in the name.
BAFU_BY_NAME: dict[str, Any] = {
    "Chemically polluted water": ("contaminated_water", "exact"),
    "Waste water": ("waste_water", "exact"),
    "Water, cooling, unspecified natural origin": ("cooling_water", "exact"),
    "Water, fossil": ("fossil_groundwater", "exact"),
    "Water, lake": ("lake_water", "exact"),
    "Water, process, surface": ("surface_water", "exact"),
    "Water, river": ("river_water", "exact"),
    "Water, salt, ocean": ("sea_water", "exact"),
    "Water, salt, sole": ("brine", "exact"),
    "Water, turbine use, unspecified natural origin": ("turbine_water", "exact"),
    "Water, well": ("groundwater", "exact"),
}

#: agribalyse, by base name -- the name with the geography taken back out of it
#: (:func:`_agribalyse_base`), because AGRIBALYSE's adapter keeps the vendor's
#: `Water, river, FR` spellings and one base fans out over up to two hundred
#: places.  Fifteen of the eighteen repeat a sibling list's assignment for a
#: sibling's spelling.  The three of its own: `Water, cooling, well` names its
#: use and its origin, and the use wins because that is how every cooling name
#: is assigned (EF's `Water Cooling sea` is cooling water, not sea water);
#: `Water, groundwater consumption` names the material with an accounting word
#: after it; `Water, barrage` and `Water, process, drinking` carry their own
#: reasons in :func:`classify`.
AGRIBALYSE_BY_NAME: dict[str, Any] = {
    "Turbined water": ("turbine_water", "exact"),
    "Waste water": ("waste_water", "exact"),
    "Water, barrage": (
        "surface_water", "close",
        "A barrage names the structure, not the material; what it impounds is "
        "surface water, so the material is read off what the name implies -- "
        "our reading, which is why the match is `close`.",
    ),
    "Water, cooling, salt, ocean": ("cooling_water", "exact"),
    "Water, cooling, unspecified natural origin": ("cooling_water", "exact"),
    "Water, cooling, well": ("cooling_water", "exact"),
    "Water, fossil": ("fossil_groundwater", "exact"),
    "Water, fresh": ("fresh_water", "exact"),
    "Water, groundwater consumption": ("groundwater", "exact"),
    "Water, in air": ("water_vapour", "exact"),
    "Water, lake": ("lake_water", "exact"),
    "Water, process, drinking": (
        "water", "broad",
        "Drinking names a quality, not a source: drinking water may have been "
        "a river, a well or a main, so it lands on the parent concept.",
    ),
    "Water, rain": ("rainwater", "exact"),
    "Water, river": ("river_water", "exact"),
    "Water, salt, ocean": ("sea_water", "exact"),
    "Water, salt, sole": ("brine", "exact"),
    "Water, turbine use, unspecified natural origin": ("turbine_water", "exact"),
    "Water, well": ("groundwater", "exact"),
    "Water (evapotranspiration)": (
        "water_vapour", "close",
        "Evapotranspiration names the process that put the water into the air, "
        "and what arrives there is vapour -- the same reading EF 3.1's "
        "identically named row already carries in this table.  `close` because "
        "the vendor named the process and we name the substance.",
    ),
}

#: The unqualified names each list ships, which the tables above deliberately
#: do not carry: what they are made of is read off the compartment rather than
#: the name, by :func:`classify`.  Listed per list because a name that is
#: unqualified in one vendor's vocabulary need not be in another's.
UNQUALIFIED_BY_SOURCE: dict[str, frozenset[str]] = {
    "EF 3.1": frozenset({"water", "water vapour"}),
    "ecoinvent": frozenset({"water", "water, unspecified natural origin"}),
    "bafu": frozenset({
        "water",
        "water, unspecified",
        "water, embodied in product",
        "water, unspecified natural origin",
        "water, process, unspecified natural origin",
    }),
    "agribalyse": frozenset({
        "water",
        "water, unspecified natural origin",
        "water, process, unspecified natural origin",
    }),
}

AIR_COMPARTMENTS = (
    "Emissions to air", "Resources from air", "air", "in air", "emissions to air",
)

#: Why the air rule exists, repeated onto every row it decides.
AIR_REASON = (
    "Water in the air domain is vapour or rain, and this flow says neither, so "
    "the material is read off the context rather than the name -- our reading, "
    "which is why the match is `close` rather than `exact`. `Green water` is the "
    "one exception: EF files it under Resources from air and it is neither."
)
UNSPECIFIC_REASON = (
    "Genuinely unspecific: the source names water without naming a kind of it, "
    "so it lands on the parent concept rather than a narrower one."
)

#: Comments ruled onto single rows, keyed by (source, uuid), so a curated
#: paragraph written against one row's own evidence survives regeneration.
#: The file drifted from this tool once -- #89's ruling was written into the
#: file by hand and the next regeneration would have erased it -- and this
#: table is what makes the tool the single writer again.
RULED_COMMENTS: dict[tuple[str, str], str] = {
    ("bafu-2026-v1", "1cb76acd-05eb-5243-a882-de030c4836d0"): (
        "Genuinely unspecific, like the five other rows BAFU ships under this "
        "name: the source names water without naming a kind of it, so it lands "
        "on the parent concept rather than a narrower one.\n\nThis used to say "
        "`groundwater`, on the reasoning that \"the name says unspecified "
        "*origin*, and the compartment supplies it\". #89 withdrew that "
        "premise. The compartment is a filing slip: BAFU writes this name into "
        "`resources / land` (64 datasets), `resources / unspecified` (64), "
        "`resources / in ground` (60) and `resources / in water` (7), and in "
        "54 of the 60 ground datasets the land and unspecified rows sit beside "
        "this one -- one withdrawal written four times in one dataset, not "
        "four descriptions of anything. The other five rows are all `water`, "
        "so believing the compartment here published the same withdrawal as "
        "two different substances depending on which compartment the vendor "
        "happened to use. A row whose own name says the origin is unspecified "
        "is water of unstated origin."
    ),
}


def _is_air(context: list[str]) -> bool:
    return any(part in AIR_COMPARTMENTS for part in context)


def _list_of(source: str) -> str:
    """Which vendor *source* names, dropping the version."""
    if source == "EF 3.1":
        return "EF 3.1"
    return source.split("-", 1)[0]


def _table_for(source: str) -> dict[str, Any]:
    return {
        "EF 3.1": EF_BY_NAME,
        "ecoinvent": ECOINVENT_BY_NAME,
        "bafu": BAFU_BY_NAME,
        "agribalyse": AGRIBALYSE_BY_NAME,
    }[_list_of(source)]


#: AGRIBALYSE writes the inventory's place onto the flow name -- `Water, river,
#: FR`, `Water, cooling, unspecified natural origin, IAI Area, South America` --
#: and ships up to two hundred spellings of one base.  This recognises the
#: place so classification happens on the base.  It is a *classification-time*
#: reading private to this tool: nothing at run time parses these names,
#: because the table it writes is keyed on the uuid.  The pipeline's own
#: geography split (`simapro_names.split_geography_suffix`) is deliberately not
#: widened here -- it moves matching behaviour, and this tool must not.
_REGION_WORDS = frozenset({
    "GLO", "RoW", "RER", "RNA", "RLA", "RME", "RAF", "RAS", "SAS", "WEU",
    "ASCC", "HICC", "NORDEL", "UCTE", "TRE", "RFC", "SERC", "WECC", "MRO",
    "NPCC", "UN-EUROPE", "UN-OCEANIA", "UN-SEASIA",
})
_REGION_PREFIXES = (
    "IAI Area", "Europe without", "Europe, without", "Canada without",
    "UCTE without", "RER w/o", "BR-", "MRO,", "NPCC,", "WECC,", "SERC,",
    "RFC,", "TRE,", "HICC,", "ASCC,",
)
_CODE_RE = re.compile(r"^[A-Z]{2}(-[A-Z0-9]{2,3})?$")


def _is_region(remainder: str) -> bool:
    """Whether the comma-tail *remainder* spells a place and nothing else."""
    return bool(
        remainder in _REGION_WORDS
        or remainder.startswith(_REGION_PREFIXES)
        or _CODE_RE.match(remainder)
    )


def _agribalyse_base(name: str) -> str | None:
    """The name with its trailing place removed, or ``None`` for no reading.

    Longest known base first, so `Water, salt, sole` is brine before `Water`
    is consulted -- and whatever follows the base must spell a place, so
    `Water, salt` alone would be refused rather than read as water somewhere
    called Salt.  A refused name fails the build of this table loudly
    (:func:`_rows_for`), never silently: an unclassified water row is a gap in
    the very curation this file is.
    """
    fields = name.split(", ")
    for i in range(len(fields), 0, -1):
        base = ", ".join(fields[:i])
        remainder = ", ".join(fields[i:])
        known = (
            base in AGRIBALYSE_BY_NAME
            or base.casefold() in UNQUALIFIED_BY_SOURCE["agribalyse"]
        )
        if known and (not remainder or _is_region(remainder)):
            return base
    return None


def _unspecified_natural_origin(source: str, context: list[str]) -> tuple[str, str, str]:
    """`(node, match, why)` for a name that says the origin is unspecified.

    The one phrase whose material depends on where the water was taken from:
    from a fossil well it is fossil groundwater, from the ground it is
    groundwater of no stated age, and from anywhere else it is water of no
    stated kind.  The name says unspecified *origin*, and the compartment
    supplies it.

    ecoinvent writes it as `Water, unspecified natural origin` and bafu as that
    and `Water, process, unspecified natural origin`, so it is a rule about the
    phrase rather than about either list's spelling.  The cooling and turbine
    names carry the same phrase and never reach here: they name their material,
    so the tables above answer them first.

    The `in ground` branch is ecoinvent's alone.  #89 withdrew its premise
    for BAFU -- the compartment is a filing slip for this name, not an origin
    statement, when one row's withdrawal is written into four compartments at
    once -- and AGRIBALYSE files the name the same four-compartment way, so
    the filing-slip reading applies to it from the start.  ecoinvent keeps the
    older reading because that is what its five releases' rows say in the
    published table today, and re-deciding a merged list's material moves its
    rows -- a question for its own change, not this tool's mechanics.  A
    fossil well applies to every list, because there the compartment names a
    material the target list cannot otherwise express, not a place in the
    vendor's cabinet.
    """
    if "fossil well" in context:
        return "fossil_groundwater", "exact", (
            "Taken from a fossil well, and fossil groundwater is its own "
            "material rather than a body groundwater sits in: EF 3.1 "
            "classifies every water resource it carries as `Renewable material "
            "resources from water`, so the target list has nowhere to put water "
            "that is not renewable, and mapping it onto `ground water` "
            "published it as an unconfined aquifer -- the one thing ecoinvent "
            "says it is not."
        )
    if _is_air(context):
        return "water_vapour", "close", AIR_REASON
    if _list_of(source) == "ecoinvent" and "in ground" in context:
        return "groundwater", "broad", (
            "Taken from the ground, so groundwater -- the name says unspecified "
            "*origin*, and the compartment supplies it."
        )
    return "water", "broad", UNSPECIFIC_REASON


def classify(source: str, name: str, context: list[str], unit: str) -> tuple[str, str, str]:
    """`(node, match, why)` for one source flow."""
    table = _table_for(source)
    if name in table:
        entry = table[name]
        if len(entry) == 3:
            return entry
        node, match = entry
        if node == "green_water":
            return node, match, (
                "An accounting category rather than a material: green water is "
                "separate for accounting reasons, not physics, so it stays a "
                "qualifier and anchors to AGROVOC."
            )
        if node == "brine":
            return node, match, (
                "Brine, not water. Its CAS 7732-18-5 is the vendor's error -- "
                "brine is a mixture, not the molecule -- and the concept carries "
                "no CAS for that reason."
            )
        return node, match, "The source names the material."

    if "unspecified natural origin" in name.casefold():
        return _unspecified_natural_origin(source, context)

    # Unqualified water: the context decides whether it is vapour.
    if _is_air(context):
        return "water_vapour", "close", AIR_REASON
    return "water", "broad", UNSPECIFIC_REASON


def _rows_for(source: str, path: Path, *, simapro_origin: bool = False) -> list[dict[str, Any]]:
    """Every water flow in one vendor file, classified.

    The name a flow is classified under is the name the *pipeline* sees.  For a
    SimaPro-shaped list that is the name with the unit taken back out of it
    (#67): `Water/m3` is water, and a measure written into a name does not
    change what the water is made of.  ``source_name`` still carries the
    vendor's spelling, because the lookup at run time is on the uuid and this
    column is the vendor's rather than ours.

    Which names are in scope is a whitelist, not a substring test: `Occupation,
    water bodies, artificial` has water in its name and is a land class.
    AGRIBALYSE is the exception in both directions: its water family is too
    wide to whitelist by spelling (one base fans out over hundreds of places),
    so scope is the `Water`/`Waste water` prefix and a water name that fails to
    classify fails this tool rather than falling silently out of the table.
    Its emissions-to-air rows were held back until #353 decided the
    water-vapour question; they classify here now, through the same air rule
    that answers every other list's airborne water.
    """
    agribalyse = _list_of(source) == "agribalyse"
    rows = []
    refused: list[str] = []
    for flow in json.loads(path.read_bytes()):
        name, unit = flow["name"], flow["unit"]
        context = list(flow.get("context") or [])
        classified = name
        if simapro_origin:
            classified = name_without_unit_suffix(name, unit) or name
        if agribalyse:
            if not classified.casefold().startswith(
                ("water", "waste water", "turbined water")
            ):
                # `Turbined water` is the list's one water spelling that does
                # not lead with the word -- the discharge from a turbine,
                # BAFU's `Water from turbine` said the other way round (#352).
                continue
            base = _agribalyse_base(classified)
            if base is None:
                refused.append(name)
                continue
            classified = base
        in_scope = (
            classified in _table_for(source)
            or classified.strip().lower() in UNQUALIFIED_BY_SOURCE[_list_of(source)]
        )
        if not in_scope:
            continue
        node, match, why = classify(source, classified, context, unit)
        why = RULED_COMMENTS.get((source, flow["uuid"]), why)
        rows.append(
            {
                "source": source,
                "source_uuid": flow["uuid"],
                "source_name": name,
                "source_context": context,
                "unit": unit,
                "node": node,
                "match": match,
                "comment": why,
            }
        )
    if refused:
        raise SystemExit(
            f"{len(refused)} {source} water rows have no classification: "
            f"{sorted(set(refused))[:10]}"
        )
    return rows


def source_rows(key: str) -> list[dict[str, Any]]:
    """Every water flow one registered list ships, classified.

    The manifest answers all three questions this needs -- where the fetched
    flows are, what the merge calls the list, and whether SimaPro shaped its
    names -- so adding a list is one entry in `SOURCE_KEYS` and nothing else.
    """
    source = registered_source_list(key)
    return _rows_for(
        source.source_label, source.flows_path, simapro_origin=source.simapro_origin
    )


def main() -> int:
    rows = [row for key in SOURCE_KEYS for row in source_rows(key)]
    rows.sort(key=lambda r: (r["source"], r["source_name"].lower(), r["source_uuid"]))

    known = {
        c["id"]
        for c in json.loads(
            (DATA_DIR / "environmental-materials.json").read_bytes()
        )["concepts"]
    }
    unknown = {r["node"] for r in rows} - known
    if unknown:
        raise SystemExit(f"rows name concepts the taxonomy does not carry: {unknown}")

    payload = {
        "schema_version": 1,
        "description": (
            "Which concept in environmental-materials.json each water flow is "
            "made of. Curated: no algorithm reads `Water, salt, sole` and knows "
            "it is brine, which is why the layering does a lookup here rather "
            "than parsing a name at run time. Generated by "
            "tools/build_water_flow_materials.py -- the uuid, name, unit and "
            "context columns are the vendor's, and `node` and `match` are the "
            "curated part. `match` is `exact` where the source names the "
            "material, `close` where it is read off the context, and `broad` "
            "where the source is genuinely unspecific and lands on a parent. "
            "One row per (source, uuid): a flow has one material, and two rows "
            "arbitrated by file order is the collapse this file exists to stop."
        ),
        "rows": rows,
    }
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2) + "\n")

    by_node: dict[str, int] = {}
    for row in rows:
        by_node[row["node"]] = by_node.get(row["node"], 0) + 1
    print(f"{len(rows)} rows -> {OUTPUT_PATH.name}")
    for node, count in sorted(by_node.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"  {node:<20} {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
