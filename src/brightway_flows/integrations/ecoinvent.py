import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import randonneur_data as rd
import structlog
import xmltodict
from ecoinvent_interface import EcoinventRelease, ReleaseType, Settings

from brightway_flows.domain.property_statements import (
    PropertyStatement,
    StatementOrigin,
    parse_value_per_unit,
    vendor_statement,
)
from brightway_flows.domain.quantities import quantity, quantity_for_label
from brightway_flows.domain.units import unit_row_for
from brightway_flows.filesystem import DATA_DIR
from brightway_flows.sources import SourceList, source_flows_path

logger = structlog.get_logger(__name__)
from brightway_flows.transformers.unit_normalization import (
    build_units_index,
    resolve_unit_notation,
)


def normalize_cas_number(value: str) -> str:
    """Normalize CAS by stripping leading zeros in the first segment."""
    parts = value.split("-")
    if len(parts) != 3:
        return value
    first, second, third = parts
    if not (first.isdigit() and second.isdigit() and third.isdigit()):
        return value
    first = first.lstrip("0") or "0"
    return f"{first}-{second}-{third}"


def _mapping_file_for_version(version: str) -> str | None:
    """The `randonneur_data` correspondence table for *version*, if one exists.

    ``None`` rather than ``ValueError`` for a version nobody has mapped yet.
    `SourceList` documents every curated input as optional and
    `load_prepared_match_table` already returns ``[]`` for a list without a
    table, but raising here made that unreachable: a version with no table
    could not be *constructed*, let alone merged.  A list arriving with no
    correspondence table is the normal first state of any new list, and its
    rows go through algorithmic matching and land in the report for a curator.
    """
    mapping_by_version = {
        "3.9.1": "ecoinvent-3.9.1-biosphere-EF-3.1-biosphere",
        "3.10.1": "ecoinvent-3.10.1-biosphere-EF-3.1-biosphere",
        "3.11": "ecoinvent-3.11-biosphere-EF-3.1-biosphere",
        # ecoinvent 3.12 uses the same correspondence table as 3.11
        "3.12": "ecoinvent-3.11-biosphere-EF-3.1-biosphere",
    }
    return mapping_by_version.get(version)


def _load_replace_table(version: str) -> list[dict]:
    """Rows of *version*'s correspondence table; empty when it has none."""
    mapping_file = _mapping_file_for_version(version)
    if mapping_file is None:
        return []
    registry = rd.Registry()
    data = registry.get_file(mapping_file)
    return data["replace"]


def _text(value: Any) -> str:
    """xmltodict hands a leaf over as a string, or as a dict with ``#text``."""
    if isinstance(value, dict):
        return str(value.get("#text") or "").strip()
    return str(value or "").strip()


def property_definitions(properties_xml: Path) -> dict[str, tuple[str, str]]:
    """``Properties.xml`` as ``{property id: (name, unit)}``.

    The exchange carries only the property's id and an amount; the name --
    `heating value, net` -- and the unit the amount is in -- `MJ` -- are in the
    master data's property list, beside the exchanges.
    """
    payload = xmltodict.parse(properties_xml.read_text(encoding="utf-8"))
    rows = payload.get("validProperties", {}).get("property") or []
    if isinstance(rows, dict):
        rows = [rows]
    return {
        str(row["@id"]): (_text(row.get("name")), _text(row.get("unitName")))
        for row in rows
        if isinstance(row, dict) and row.get("@id")
    }


def statements_from_properties(
    obj: dict,
    definitions: dict[str, tuple[str, str]],
    *,
    flow_unit: str,
    version: str,
    source: str,
) -> list[PropertyStatement]:
    """What an exchange's ``<property>`` children state about one unit of it.

    ecoinvent gives `Oil, crude` a `heating value, net` of 43.4 and a `heating
    value, gross` of 46 from 3.9.1 on, each a property whose unit is megajoules
    and whose amount is per unit of the exchange, which is how the property's
    own comment reads it ("Expressed in MJ per unit of product").  Each becomes
    a :class:`~brightway_flows.domain.property_statements.PropertyStatement`
    `stated_by` ``vendor-flow``, its quantity matched by the property's name
    against the vocabulary's spellings.  A property whose name is no quantity
    the vocabulary knows -- `wet mass`, `carbon content, fossil` -- is passed
    over, and so is an amount of zero, which states nothing.  A property whose
    unit is itself a ratio (`kg/m3`) is read as that ratio; none is on an
    elementary exchange in the five releases read today.
    """
    raw = obj.get("property")
    if not raw:
        return []
    properties = raw if isinstance(raw, list) else [raw]
    statements: list[PropertyStatement] = []
    name = _text(obj.get("name"))
    for prop in properties:
        if not isinstance(prop, dict):
            continue
        definition = definitions.get(str(prop.get("@propertyId") or ""))
        if definition is None:
            continue
        label, prop_unit = definition
        slug = quantity_for_label(label)
        if slug is None:
            continue
        try:
            amount = float(prop.get("@amount"))
        except (TypeError, ValueError):
            continue
        if amount <= 0:
            continue
        ratio = parse_value_per_unit(f"{amount} {prop_unit}")
        if ratio is not None:
            _, unit, per_unit = ratio
        else:
            unit, per_unit = prop_unit, flow_unit
        if not unit or not per_unit:
            continue
        unit_kind = _kind_of(unit)
        if not unit_kind or unit_kind != quantity(slug).quantity_kind_iri:
            continue
        if unit_kind == _kind_of(per_unit) or not _kind_of(per_unit):
            continue
        comment = _text(prop.get("comment"))
        statements.append(
            vendor_statement(
                quantity=slug,
                value=amount,
                unit=unit,
                per_unit=per_unit,
                stated_by=StatementOrigin.VENDOR_FLOW,
                primary_source=[
                    f"ecoinvent {version} ElementaryExchanges.xml, exchange "
                    f"`{name}` ({obj.get('@id')}), property `{label}`: {amount} "
                    f"{prop_unit}" + (f" -- {comment}" if comment else "")
                ],
                derived_from=f"ecoinvent-{version} ElementaryExchanges.xml",
                generated_by=f"fetch_{source}",
                attributed_to=source,
                comment=(
                    f"ecoinvent's master data states the property `{label}` on "
                    f"the exchange" + (f": {comment}" if comment else ".")
                ),
            )
        )
    return statements


def _kind_of(unit: str) -> str:
    row = unit_row_for(unit)
    return str(row.get("quantity_kind_iri") or "") if row is not None else ""


def reformat(obj: dict) -> dict:
    data = {
        "uuid": obj["@id"],
        "identifier": obj["@id"],
        "unit": obj["unitName"]["#text"],
        "context": [
            obj["compartment"]["compartment"]["#text"],
            obj["compartment"]["subcompartment"]["#text"],
        ],
        "name": obj["name"]["#text"],
    }
    if obj.get("synonym") and isinstance(obj["synonym"], list):
        data["synonyms"] = [s["#text"] for s in obj["synonym"] if "#text" in s]
    elif obj.get("synonym") and "#text" in obj["synonym"]:
        data["synonyms"] = [obj["synonym"]["#text"]]
    if "@casNumber" in obj:
        data["cas_number"] = normalize_cas_number(obj["@casNumber"])
    return data


def remove_conflicting_synonyms(data: list[dict]) -> list[dict]:
    """
    Remove synonyms which conflict with the base names of other flows within the same category tree
    branch.

    For example, if flow `A` has a synonym `water` and a context `['ground']`, and flow `B` has the
    name `water` and the context `['ground', 'deep']`, then the synonym `water` would be removed
    from `A`. However, if `B` had the context `['something', 'else']`, then `water` would be kept,
    as it wouldn't directly overlap a different flow in the same category tree branch.
    """
    base_names = defaultdict(list)
    for obj in data:
        if obj.get("name") and obj.get("context"):
            base_names[obj["context"][0]].append(obj["name"].lower())

    for obj in data:
        if not (obj.get("synonyms") and obj.get("context")):
            continue
        obj["synonyms"] = [
            syn
            for syn in obj["synonyms"]
            if syn.lower() not in base_names[obj["context"][0]]
        ]

    return data


def ecospold2_biosphere_extractor(
    input_path: Path, version: str, output_path: Path | None = None,
) -> dict[str, Path]:
    if not input_path.name == "ElementaryExchanges.xml":
        raise ValueError("`input_path` must be for a `ElementaryExchanges.xml` file")
    if output_path is None:
        # The manifest, not the convention: the filename used to be built here
        # and again in `filesystem.ecoinvent_flows_filepath`, so the fetch and
        # the merge agreed only by coincidence (#12).
        output_path = source_flows_path(f"ecoinvent-{version}")
    unmatched_path = DATA_DIR / f"ecoinvent-biosphere-flows-unmatched-{version}.json"
    mapping_stats_path = DATA_DIR / f"ecoinvent-ef31-mapping-stats-{version}.json"
    with open(input_path) as fs:
        ei_xml = xmltodict.parse(fs.read(), strip_whitespace=False)[
            "validElementaryExchanges"
        ]["elementaryExchange"]

    source = f"ecoinvent-{version}"
    data = remove_conflicting_synonyms([reformat(obj) for obj in ei_xml])
    for flow in data:
        flow["source"] = source

    units_index = build_units_index()
    missing_units: dict[str, int] = {}
    for flow in data:
        raw_unit = flow.get("unit")
        if isinstance(raw_unit, str) and raw_unit.strip():
            resolved = resolve_unit_notation(raw_unit, units_index)
            if resolved is None:
                missing_units[raw_unit] = missing_units.get(raw_unit, 0) + 1
            else:
                canonical, unit_iri = resolved
                flow["unit"] = canonical
                if unit_iri:
                    flow["unit_iri"] = unit_iri
    if missing_units:
        raise ValueError(
            f"ecoinvent unit normalization: {len(missing_units)} unit(s) could not be resolved. "
            f"Add them to units.json or UNIT_ALIASES. "
            f"Unresolved: {sorted(missing_units)}"
        )

    # After the units are canonical, so a statement is per the unit the flow
    # is carried in (`sm3`, not `Sm3`).  The property list is the master
    # data's, beside the exchanges; a release shipped without it states no
    # property a reader can name, and the log says so.
    properties_xml = input_path.parent / "Properties.xml"
    if properties_xml.exists():
        definitions = property_definitions(properties_xml)
        stated = 0
        for flow, obj in zip(data, ei_xml):
            statements = statements_from_properties(
                obj, definitions, flow_unit=str(flow.get("unit") or ""),
                version=version, source=source,
            )
            if statements:
                flow["property_statements"] = [s.to_dict() for s in statements]
                stated += len(statements)
        logger.info(
            "ecoinvent_property_statements_extracted",
            version=version,
            flows=sum(1 for flow in data if "property_statements" in flow),
            statements=stated,
        )
    else:
        logger.warning("ecoinvent_properties_xml_missing", path=str(properties_xml))

    with open(output_path, "w") as fs:
        json.dump(data, fs, indent=2)

    replace_table = _load_replace_table(version)
    matched_source_uuids = {row["source"]["uuid"] for row in replace_table}

    unmatched = [flow for flow in data if flow["uuid"] not in matched_source_uuids]
    for flow in unmatched:
        flow["source"] = f"ecoinvent-{version}-unmatched"
    with open(unmatched_path, "w") as fs:
        json.dump(unmatched, fs, indent=2)

    target_to_sources: dict[str, dict] = defaultdict(
        lambda: {"target": None, "sources": {}}
    )
    context_pairs: dict[tuple[tuple[str, ...], tuple[str, ...]], dict] = defaultdict(
        lambda: {"count": 0, "source_uuids": set(), "target_uuids": set()}
    )

    for row in replace_table:
        source_row = row["source"]
        target_row = row["target"]

        target_uuid = target_row["uuid"]
        source_uuid = source_row["uuid"]
        target_to_sources[target_uuid]["target"] = target_row
        target_to_sources[target_uuid]["sources"][source_uuid] = source_row

        source_context = tuple(source_row.get("context", []))
        target_context = tuple(target_row.get("context", []))
        key = (source_context, target_context)
        context_pairs[key]["count"] += 1
        context_pairs[key]["source_uuids"].add(source_uuid)
        context_pairs[key]["target_uuids"].add(target_uuid)

    many_to_one = []
    for item in target_to_sources.values():
        sources = list(item["sources"].values())
        if len(sources) < 2:
            continue
        many_to_one.append({
            "target": item["target"],
            "source_count": len(sources),
            "sources": sorted(sources, key=lambda s: (s.get("name") or "").lower()),
        })
    many_to_one = sorted(
        many_to_one,
        key=lambda x: (-x["source_count"], (x["target"].get("name") or "").lower()),
    )

    context_stats = []
    for (source_ctx, target_ctx), stats in context_pairs.items():
        context_stats.append({
            "source_context": list(source_ctx),
            "target_context": list(target_ctx),
            "mapping_count": stats["count"],
            "unique_source_flows": len(stats["source_uuids"]),
            "unique_target_flows": len(stats["target_uuids"]),
        })
    context_stats = sorted(context_stats, key=lambda x: -x["mapping_count"])

    mapping_file = _mapping_file_for_version(version)
    mapping_stats = {
        "version": version,
        "mapping_file": mapping_file,
        "many_to_one": many_to_one,
        "context_stats": context_stats,
    }
    with open(mapping_stats_path, "w") as fs:
        json.dump(mapping_stats, fs, indent=2)

    return {
        "flows": output_path,
        "unmatched": unmatched_path,
        "mapping_stats": mapping_stats_path,
    }



# `get_ecoinvent_release(version)` was here until #15.  It is what `fetch` is,
# reached by a `--version` string instead of by the registry -- the same
# information arriving by a route the registry could not see, which is why
# adding a list meant adding a command.  `fetch-source ecoinvent-3.12` runs the
# adapter below; `download-ecoinvent-flows` is a deprecated alias for it.


def fetch(source: SourceList, *, force: bool = False) -> Path:
    """The :class:`~brightway_flows.sources.SourceAdapter` for ecoinvent.

    One adapter for all five ecoinvent manifests: they differ in `list_version`,
    and that is exactly what is read off *source* here.  Before #15 this was a
    dedicated CLI command taking a `--version` string, which is the same
    information arriving by a route the registry could not see.

    *force* is accepted because the protocol declares it and ignored because
    `ecoinvent_interface` owns the release cache: re-extracting is cheap, and
    re-downloading a release is its decision rather than ours to override.
    """
    return ecospold2_biosphere_extractor(
        _release_master_data(source.list_version),
        version=source.list_version,
        output_path=source.flows_path,
    )["flows"]


def _release_master_data(version: str) -> Path:
    """The `ElementaryExchanges.xml` of *version*, downloading the release first.

    ecoinvent publishes one of these per system model -- `cutoff`, `apos`,
    `consequential` and `EN15804` -- and this reads `cutoff` for every version.
    One release rather than four because the other three hold nothing cutoff does
    not, which is measured rather than assumed: `tools/
    compare_ecoinvent_system_models.py` compares all four releases of every
    registered version exchange by exchange, and only 3.8 disagrees, by the three
    `social / unspecified` flows its `additional_flows` file supplies.  A new
    version has to be run through that tool before this line can be trusted for
    it (#100).
    """
    ei = EcoinventRelease(Settings())
    release_dir = ei.get_release(
        version=version,
        system_model="cutoff",
        release_type=ReleaseType.ecospold,
    )
    return release_dir / "MasterData" / "ElementaryExchanges.xml"

