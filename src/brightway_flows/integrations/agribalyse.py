"""Reading AGRIBALYSE 3.2's elementary flows.

AGRIBALYSE is not published as a flow list either.  It is a SimaPro
``{processes}`` CSV export -- ADEME's French agricultural database, 20,440
processes -- and its flows are the rows those processes exchange with the
environment.  Extraction is therefore a collapse, larger than Stepwise's by
three orders of magnitude: 6,535,117 biosphere-exchange rows down to the 5,528
distinct flows they name.

Two kinds of block say something about a flow, exactly as in a method export:

1. The per-process exchange blocks (``Emissions to air``, ``Emissions to
   water``, ``Emissions to soil``, ``Resources``, ``Final waste flows``),
   whose rows carry the name, the sub-compartment and the unit the exchange is
   stated in.  This is the only place a compartment exists.
2. The trailing substance blocks (``Raw materials``, ``Airborne emissions``,
   ``Waterborne emissions``, ``Emissions to soil``, ``Final waste flows``),
   which carry the unit the substance is *inventoried* in, its registry
   number, and a free-text comment holding its formula and synonyms.

The unit comes from (2), for Stepwise's reason inverted: an exchange row's
unit is whatever scale variant the process author typed, and one flow stated
in ``g`` here and ``kg`` there is one flow, not two.  Every one of the 5,528
distinct names joins to a substance block in this export, so unlike Stepwise
there is no counted remainder.

``Final waste flows`` is read and emitted like every other compartment, and
refused one step later: all 43 of its rows are recorded under ``excluded`` in
``agribalyse-3.2-additional-flows.json``, which removes them when the list is
loaded and publishes each refusal on the list's correspondence.  The refusal
is a decision (#189) -- a SimaPro final-waste row is an accounting device at
the product-system boundary, not an exchange with the environment, and the
consensus vocabulary has no waste compartment -- and the excluded list is
where decisions of that kind live, so this module no longer withholds
anything of its own.  One mechanism refuses; this one just reports what the
file says.

What is *not* done here is the reading of the names.  ``Water, river, FR``,
``Gas, natural/m3`` and friends are habits of the SimaPro lineage, and the
manifest's ``simapro_origin`` hands them to the machinery that already undoes
them.  The compartments go out as the vendor wrote them, and where they belong
is stated in ``context-manual-mapping.json``.  This module reports what the
file says, and nothing else.

The export carries no version claim of its own -- a ``{processes}`` header
names a project (``AGRIBALYSE - unit``) but no release -- so the filename is
the version statement, the way BAFU's archive name is.  The project name *is*
checked: a file whose header names another project is a different database
wearing this list's key.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterator

import orjson
import structlog

from brightway_flows.integrations.ecoinvent import normalize_cas_number
from brightway_flows.integrations.stepwise import parse_substance_comment
from brightway_flows.sources import SourceList

logger = structlog.get_logger(__name__)

#: The header's own project name, checked rather than read.
AGRIBALYSE_PROJECT_NAME = "AGRIBALYSE - unit"

#: The per-process exchange block, and the trailing substance block that holds
#: that compartment's units, registry numbers and comments.  The block names
#: are the vendor's own headings on both sides; ``Final waste flows`` uses one
#: heading for both.  Its rows are extracted here and refused by the
#: ``excluded`` list (see the module docstring), so that the refusal has an
#: identity to name.
_SUBSTANCE_BLOCK_BY_COMPARTMENT = {
    "Resources": "Raw materials",
    "Emissions to air": "Airborne emissions",
    "Emissions to water": "Waterborne emissions",
    "Emissions to soil": "Emissions to soil",
    "Final waste flows": "Final waste flows",
}

#: What names an AGRIBALYSE flow.  A process export carries no flow
#: identifiers (``Export platform IDs: No``), so the identity is derived from
#: the four fields that are a flow rather than an exchange: the name, the two
#: compartment levels, and the unit the substance block inventories it in.
#: The cost and the trade are Stepwise's and BAFU's, taken for the same
#: reason: there is nothing else to key on.
_IDENTITY_FIELDS = ("name", "compartment", "subcompartment", "unit")

#: Deliberately version-free, like BAFU's and Stepwise's, and derived from the
#: IRI stem rather than written as a literal.  A flow that 3.2 and a later
#: release both ship is one flow.  Changing it is a one-way door once a build
#: has shipped.
AGRIBALYSE_FLOW_NAMESPACE = uuid.uuid5(
    uuid.NAMESPACE_URL, "https://vocab.brightway.one/agribalyse/"
)


def _flow_uuid(name: str, compartment: str, subcompartment: str, unit: str) -> str:
    """The identifier for one AGRIBALYSE flow, from the fields that are the flow."""
    return str(
        uuid.uuid5(
            AGRIBALYSE_FLOW_NAMESPACE,
            "|".join((name, compartment, subcompartment, unit)),
        )
    )


def _parsed(csv_path: Path) -> Any:
    """The export, parsed.

    Imported where it is used rather than at module scope, for Stepwise's
    reason: ``bw_simapro_csv`` pulls in a stack this project needs for two
    lists, and `cli` imports every integration at startup.
    """
    from bw_simapro_csv import SimaProCSV

    return SimaProCSV(csv_path, stderr_logs=False)


def _named(blocks: list[Any], class_name: str) -> Iterator[Any]:
    for block in blocks:
        if type(block).__name__ == class_name:
            yield block


def _substances(blocks: list[Any]) -> dict[tuple[str, str], dict[str, Any]]:
    """The trailing substance blocks, keyed by ``(block heading, name)``."""
    index: dict[tuple[str, str], dict[str, Any]] = {}
    for block in _named(blocks, "GenericBiosphere"):
        for row in block.parsed:
            name = str(row.get("name") or "").strip()
            if name:
                index[(block.category, name)] = row
    return index


def _exchanged_flows(blocks: list[Any]) -> dict[tuple[str, str, str], int]:
    """Every ``(compartment, name, subcompartment)`` a process exchanges.

    The value is how many exchange rows named it.  Not published -- an amount
    is inventory, not a flow -- but logged, so a parse that silently read half
    the processes would not look like a successful run with fewer flows.
    """
    found: dict[tuple[str, str, str], int] = defaultdict(int)
    for process in _named(blocks, "Process"):
        for category, sub_block in process.blocks.items():
            if category not in _SUBSTANCE_BLOCK_BY_COMPARTMENT:
                continue
            for row in sub_block.parsed:
                name = str(row.get("name") or "").strip()
                context = row.get("context") or ("", "")
                if not name:
                    continue
                found[(category, name, str(context[1]).strip())] += 1
    return dict(found)


def extract_elementary_flows(csv_path: Path, *, source: str) -> list[dict[str, Any]]:
    """The flows AGRIBALYSE's processes exchange, as source-list records."""
    return flows_from_blocks(list(_parsed(csv_path).blocks), source=source)


def flows_from_blocks(blocks: list[Any], *, source: str) -> list[dict[str, Any]]:
    """The flows *blocks* exchange, as source-list records.

    Faithful to what the export says.  A registry number is written as the
    substance block gives it, normalised only in the way every list's is.  An
    exchanged name the substance blocks have no row for is dropped and
    counted, for Stepwise's reason: inventing a unit would hide which rows are
    missing from a file a correction could name.  (In the 3.2 export that
    count is zero.)
    """
    substances = _substances(blocks)
    exchanged = _exchanged_flows(blocks)

    records: list[dict[str, Any]] = []
    without_substance_row: list[str] = []
    exchange_rows_seen = 0

    for (compartment, name, subcompartment), count in sorted(exchanged.items()):
        exchange_rows_seen += count
        heading = _SUBSTANCE_BLOCK_BY_COMPARTMENT[compartment]
        substance = substances.get((heading, name))
        if substance is None:
            without_substance_row.append(f"{compartment} | {name}")
            continue

        unit = str(substance.get("unit") or "").strip()
        synonyms, comment = parse_substance_comment(str(substance.get("comment") or ""))
        context = [compartment, subcompartment] if subcompartment else [compartment]
        record: dict[str, Any] = {
            "uuid": _flow_uuid(name, compartment, subcompartment, unit),
            "name": name,
            "source": source,
            "context": context,
            "unit": unit,
        }
        if cas_number := normalize_cas_number(str(substance.get("cas_number") or "")):
            # The list form, because the lineage's own fixes are written
            # against it.
            record["cas_numbers"] = [cas_number]
        if synonyms:
            record["synonyms"] = synonyms
        if comment:
            record["general_comment"] = comment
        records.append(record)

    if without_substance_row:
        logger.warning(
            "agribalyse_exchanged_name_has_no_substance_row",
            count=len(without_substance_row),
            rows=without_substance_row[:10],
        )
    logger.info(
        "agribalyse_elementary_flows_extracted",
        flows=len(records),
        exchange_rows=exchange_rows_seen,
        with_cas=sum(1 for row in records if "cas_numbers" in row),
        with_synonyms=sum(1 for row in records if "synonyms" in row),
        contexts=len({tuple(row["context"]) for row in records}),
        units=sorted({row["unit"] for row in records}),
    )
    return records


def fetch(source: SourceList, *, force: bool = False) -> Path:
    """The :class:`~brightway_flows.sources.SourceAdapter` for AGRIBALYSE.

    *force* is accepted because the protocol has it and re-reads the export
    either way: there is no download to skip.  Like BAFU's archive, the export
    has no stable vendor URL -- ADEME distributes it on request -- so a
    missing file is a person's next action and the error says which file and
    where.

    The header's project name is checked, because it is the only claim the
    file makes about itself: a ``{processes}`` export states no release, so
    the version lives in the filename and the manifest, and a file whose
    header names a different project is a different database wearing this
    list's key.
    """
    from brightway_flows.filesystem import agribalyse_csv_path

    csv_path = agribalyse_csv_path(source.list_version)
    if not csv_path.exists():
        raise FileNotFoundError(
            f"AGRIBALYSE's SimaPro export for {source.key} is not at {csv_path}. "
            "It has no stable download URL: obtain it from ADEME and place it "
            "there."
        )

    parsed = _parsed(csv_path)
    project = str(parsed.header.get("project") or "").strip()
    if project != AGRIBALYSE_PROJECT_NAME:
        raise ValueError(
            f"{csv_path} is an export of project {project!r}; {source.key} is "
            f"{AGRIBALYSE_PROJECT_NAME!r}. Register the other database rather "
            "than reading it under this list's key."
        )

    records = flows_from_blocks(list(parsed.blocks), source=source.source_label)
    source.flows_path.write_bytes(orjson.dumps(records, option=orjson.OPT_INDENT_2))
    logger.info(
        "agribalyse_flows_written", path=str(source.flows_path), flows=len(records)
    )
    return source.flows_path
