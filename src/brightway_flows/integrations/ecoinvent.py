import json
from collections import defaultdict
from pathlib import Path

import randonneur_data as rd
import xmltodict
from ecoinvent_interface import EcoinventRelease, ReleaseType, Settings

from brightway_flows.filesystem import DATA_DIR
from brightway_flows.sources import SourceList, source_flows_path
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

