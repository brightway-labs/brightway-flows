"""Reading Stepwise 2006's elementary flows.

Stepwise 2006 is not published as a flow list.  It is a SimaPro ``{methods}``
CSV export -- an LCIA method -- and its flows are the rows its nineteen impact
categories characterise.  Extraction is therefore a collapse, like BAFU's:
9,698 characterisation-factor rows down to the 6,064 distinct flows they name.

Two kinds of block say something about a flow, and only together do they say
enough:

1. ``Impact category`` blocks, whose factor rows carry the two-level SimaPro
   compartment (``Water; groundwater``), the name, and a registry number.  This
   is the **only** place a compartment exists, so it is what a flow is built
   from.
2. The trailing substance blocks (``Raw materials``, ``Airborne emissions``,
   ``Waterborne emissions``, ``Emissions to soil``, ``Social issues``,
   ``Economic issues``), which carry the unit the substance is *inventoried* in
   and a free-text comment holding its formula and synonyms.

The unit has to come from (2).  A factor row states the unit the **factor** is
expressed in, which is a scale variant of the flow's own -- the radionuclides
are inventoried in ``kBq`` and the 36 factor rows of ``Ionizing radiation`` are
stated per ``Bq`` -- so building a flow from the factor row's unit would publish
every activity flow a thousandfold out.

A substance in (2) that no category characterises is not a flow of this method
and is not emitted; the count is logged.

What is *not* done here is the reading of the names.  ``Occupation, arable``,
``Gas, natural/m3``, ``Uranium, 451 GJ per kg`` and ``Benzene, chloro-`` are
habits of the SimaPro lineage rather than facts about Stepwise, and the
manifest's ``simapro_origin`` is what hands them to the machinery that already
undoes them -- `simapro-lineage-manual-fixes.json`, the unit-suffix split, and
the name rules in :mod:`brightway_flows.simapro_names`.  The compartments go
out as the vendor wrote them, and where they belong is stated in
``context-manual-mapping.json``.  Both are the same rule: this module reports
what the file says, and nothing else.

The characterisation factors are read (a category's rows are how its flows are
found) and deliberately not written.  A list's factors reach the build through
the manifest's ``lcia`` block and ``characterise``, against methods the
manifest names -- not as a payload on a flow record.
"""

from __future__ import annotations

import re
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterator

import httpx
import orjson
import structlog
from tqdm import tqdm

from brightway_flows.integrations.ecoinvent import normalize_cas_number
from brightway_flows.sources import SourceList

logger = structlog.get_logger(__name__)

#: Where the export is served from.  Stepwise 2006 is distributed inside
#: SimaPro rather than at a vendor URL, so this is a copy taken from a SimaPro
#: installation and published unchanged; the filename carries the version.
STEPWISE_DOWNLOAD_PREFIX = "https://files.brightway.dev/"

#: The method's own name, as its ``Method`` block spells it.  Checked rather
#: than read: a file whose method is not this one is a different method wearing
#: this list's key.
STEPWISE_METHOD_NAME = "Stepwise_2006_IPCC2021_CorrectedNatureOccupation"

#: SimaPro's compartment, and the substance block that holds that compartment's
#: units and comments.  The compartment spellings are the factor rows'; the
#: block names are the vendor's own headings.
_BLOCK_BY_COMPARTMENT = {
    "Raw": "Raw materials",
    "Air": "Airborne emissions",
    "Water": "Waterborne emissions",
    "Soil": "Emissions to soil",
    "Social": "Social issues",
    "Economic": "Economic issues",
}

#: The same pairing read the other way, for asking of a substance block's row
#: whether any category characterises it.
_COMPARTMENT_BY_BLOCK = {
    heading: compartment for compartment, heading in _BLOCK_BY_COMPARTMENT.items()
}

#: What names a Stepwise flow.  A method file carries no identifiers at all, so
#: the identity is derived -- and derived from the four fields that are a flow
#: rather than a factor: the name, the two compartment levels, and the unit the
#: substance block inventories it in.
#:
#: The cost is BAFU's: a flow the vendor renames becomes a new flow rather than
#: the same one moved.  That is the trade taken there and it is taken here for
#: the same reason -- there is nothing else to key on, and a name change that
#: announces itself as one flow leaving and another arriving is a failure a
#: reader can see.
_IDENTITY_FIELDS = ("name", "compartment", "subcompartment", "unit")

#: Deliberately version-free, like BAFU's, and derived from the IRI stem rather
#: than written as a literal.  A flow that 1.09 and a later release both ship is
#: one flow.  Changing it is a one-way door: both are read once a build has
#: shipped.
STEPWISE_FLOW_NAMESPACE = uuid.uuid5(
    uuid.NAMESPACE_URL, "https://vocab.brightway.one/stepwise/"
)

#: A comment's synonym run ends at a blank line or at one of these headings.
#: ``Synonyms: a; b; c`` may wrap over several lines, and the formula and
#: heating-value lines are the only other things these comments hold.
_COMMENT_SECTION_BREAK = re.compile(
    r"^\s*(?:formula\s*:|higher heating value|lower heating value)",
    re.IGNORECASE,
)

#: A comment that says there is nothing to say.
_NO_FORMULA = "no formula available"


def stepwise_csv_url(csv_path: Path) -> str:
    """Where :func:`download` fetches *csv_path* from."""
    return f"{STEPWISE_DOWNLOAD_PREFIX}{csv_path.name}"


def download(csv_path: Path, *, force: bool = False) -> Path:
    """The method export, downloaded to *csv_path* unless it is already there."""
    if csv_path.exists() and not force:
        logger.info("stepwise_csv_already_downloaded", path=str(csv_path))
        return csv_path

    url = stepwise_csv_url(csv_path)
    logger.info("downloading_stepwise_csv", url=url, destination=str(csv_path))
    with httpx.stream("GET", url, follow_redirects=True, timeout=300) as response:
        response.raise_for_status()
        total = int(response.headers.get("content-length", 0))
        with csv_path.open("wb") as handle, tqdm(
            total=total or None, unit="B", unit_scale=True, desc=csv_path.name
        ) as progress:
            for chunk in response.iter_bytes(chunk_size=1024 * 64):
                handle.write(chunk)
                progress.update(len(chunk))
    return csv_path


def parse_substance_comment(comment: str) -> tuple[list[str], str]:
    """Split a SimaPro substance comment into ``(synonyms, what is left)``.

    The formula stays in the comment rather than becoming a structural
    property.  SimaPro writes a formula for ores and mixtures as readily as for
    compounds -- ``Bauxite`` is ``Al, Fe, O, OH`` -- so a field that means "this
    substance's molecular formula" would be false for the rows this list is
    least sure about.  The chemistry stages derive formulae from resolved
    identity instead, and a claim from the vendor would outrank them.

    >>> parse_substance_comment("Formula: Zn\\nSynonyms: Zinc metal; Blue powder")
    (['Zinc metal', 'Blue powder'], 'Formula: Zn')
    >>> parse_substance_comment("No formula available")
    ([], '')
    """
    if not comment or not comment.strip():
        return [], ""

    synonym_lines: list[str] = []
    other_lines: list[str] = []
    in_synonyms = False
    for line in comment.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("synonyms:"):
            in_synonyms = True
            synonym_lines.append(stripped[len("synonyms:"):].strip())
            continue
        if in_synonyms:
            if not stripped or _COMMENT_SECTION_BREAK.match(stripped):
                in_synonyms = False
                if stripped:
                    other_lines.append(stripped)
                continue
            synonym_lines.append(stripped)
            continue
        if stripped:
            other_lines.append(stripped)

    synonyms: list[str] = []
    seen: set[str] = set()
    for part in " ".join(synonym_lines).split(";"):
        candidate = part.strip()
        if not candidate or candidate.lower() in seen:
            continue
        seen.add(candidate.lower())
        synonyms.append(candidate)

    remaining = "\n".join(other_lines).strip()
    if remaining.lower() == _NO_FORMULA:
        remaining = ""
    return synonyms, remaining


def _flow_uuid(name: str, compartment: str, subcompartment: str, unit: str) -> str:
    """The identifier for one Stepwise flow, from the fields that are the flow."""
    return str(
        uuid.uuid5(
            STEPWISE_FLOW_NAMESPACE,
            "|".join((name, compartment, subcompartment, unit)),
        )
    )


def _blocks(csv_path: Path) -> list[Any]:
    """Every block of the export, parsed.

    Imported where it is used rather than at module scope: ``bw_simapro_csv``
    pulls in a stack this project needs for one list, and `cli` imports every
    integration at startup.
    """
    from bw_simapro_csv import SimaProCSV

    return list(SimaProCSV(csv_path, stderr_logs=False).blocks)


def _named(blocks: list[Any], class_name: str) -> Iterator[Any]:
    for block in blocks:
        if type(block).__name__ == class_name:
            yield block


def _method_block(blocks: list[Any]) -> dict[str, Any]:
    """The ``Method`` block's payload, or an empty one."""
    for block in _named(blocks, "Method"):
        if isinstance(block.parsed, dict):
            return block.parsed
    return {}


def method_revision(list_version: str) -> str:
    """The export's own version, out of the manifest's two-part one.

    ``2006-1.09`` is the 2006 method as its 1.09 export ships it, the way
    BAFU's ``2026-v1`` is the 2026 data as its first export ships it.  The
    file declares only the second half.
    """
    return list_version.split("-", 1)[-1]


def _method_version(method: dict[str, Any]) -> str:
    """SimaPro writes ``1;09`` and the parser hands it over as ``('1', '09')``."""
    raw = method.get("Version")
    if isinstance(raw, (list, tuple)):
        parts = [str(part).strip() for part in raw if str(part).strip()]
        return ".".join(parts)
    if isinstance(raw, str):
        return raw.strip().replace(";", ".")
    return ""


def _substances(blocks: list[Any]) -> dict[tuple[str, str], dict[str, Any]]:
    """The trailing substance blocks, keyed by ``(block heading, name)``."""
    index: dict[tuple[str, str], dict[str, Any]] = {}
    for block in _named(blocks, "GenericBiosphere"):
        for row in block.parsed:
            name = str(row.get("name") or "").strip()
            if name:
                index[(block.category, name)] = row
    return index


def _characterised_flows(blocks: list[Any]) -> dict[tuple[str, str, str], list[str]]:
    """Every ``(name, compartment, subcompartment)`` a category characterises.

    The value is which categories named it.  Not published -- a factor is the
    ``lcia`` block's business -- but counted, so the log says how much of the
    method the flows came out of: nineteen categories is the whole of it, and a
    parse that silently read one would otherwise look like a successful run
    with fewer flows in it.
    """
    found: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for block in _named(blocks, "ImpactCategory"):
        category = str(block.parsed.get("name") or "").strip()
        for factor in block.parsed.get("cfs", []):
            name = str(factor.get("name") or "").strip()
            context = [str(part) for part in (factor.get("context") or [])]
            if not name or len(context) != 2:
                continue
            found[(name, context[0], context[1])].append(category)
    return dict(found)


def extract_elementary_flows(csv_path: Path, *, source: str) -> list[dict[str, Any]]:
    """The flows Stepwise 2006 characterises, as source-list records."""
    return flows_from_blocks(_blocks(csv_path), source=source)


def flows_from_blocks(blocks: list[Any], *, source: str) -> list[dict[str, Any]]:
    """The flows *blocks* characterise, as source-list records.

    Faithful to what the export says.  A registry number is written as the
    substance block gives it, normalised only in the way every list's is --
    ``000071-36-3`` is 71-36-3 with SimaPro's zero padding, not a different
    number.  A characterised name the substance blocks have no row for is
    emitted with no unit and counted: it is the vendor's own gap, the loader
    drops such a row, and inventing a unit here would hide which rows are
    missing from a file a correction could name.
    """
    substances = _substances(blocks)
    characterised = _characterised_flows(blocks)

    records: list[dict[str, Any]] = []
    unknown_compartments: dict[str, int] = defaultdict(int)
    without_substance_row: list[str] = []
    categories_seen: set[str] = set()

    for (name, compartment, subcompartment), categories in sorted(
        characterised.items()
    ):
        categories_seen.update(categories)
        heading = _BLOCK_BY_COMPARTMENT.get(compartment)
        if heading is None:
            unknown_compartments[compartment] += 1
            continue
        substance = substances.get((heading, name))
        if substance is None:
            without_substance_row.append(f"{compartment} | {name}")
            substance = {}

        unit = str(substance.get("unit") or "").strip()
        synonyms, comment = parse_substance_comment(str(substance.get("comment") or ""))
        record: dict[str, Any] = {
            "uuid": _flow_uuid(name, compartment, subcompartment, unit),
            "name": name,
            "source": source,
            "context": [compartment, subcompartment],
            "unit": unit,
        }
        if cas_number := normalize_cas_number(str(substance.get("cas_number") or "")):
            # The list form, because the lineage's own fixes are written
            # against it: a list whose adapter emits the scalar is a list those
            # corrections silently pass over.
            record["cas_numbers"] = [cas_number]
        if synonyms:
            record["synonyms"] = synonyms
        if comment:
            record["general_comment"] = comment
        records.append(record)

    emitted = {(row["context"][0], row["name"]) for row in records}
    uncharacterised = sorted(
        f"{heading} | {name}"
        for (heading, name) in substances
        if (_COMPARTMENT_BY_BLOCK.get(heading, ""), name) not in emitted
    )

    if unknown_compartments:
        logger.warning(
            "stepwise_unknown_compartments", compartments=dict(unknown_compartments)
        )
    if without_substance_row:
        logger.warning(
            "stepwise_characterised_name_has_no_substance_row",
            count=len(without_substance_row),
            rows=without_substance_row[:10],
        )
    logger.info(
        "stepwise_elementary_flows_extracted",
        flows=len(records),
        with_cas=sum(1 for row in records if "cas_numbers" in row),
        with_synonyms=sum(1 for row in records if "synonyms" in row),
        contexts=len({tuple(row["context"]) for row in records}),
        units=sorted({row["unit"] for row in records}),
        impact_categories=len(categories_seen),
        substances_without_factors=len(uncharacterised),
    )
    return records


def fetch(source: SourceList, *, force: bool = False) -> Path:
    """The :class:`~brightway_flows.sources.SourceAdapter` for Stepwise 2006.

    *force* re-downloads the export.  Parsing happens either way: the whole cost
    is one pass over a 1.1 MB text file.

    The method's own version is checked against the manifest's, because the two
    are one claim.  ``list_version`` is what the flows are published under and
    what this list's curated files are keyed to, so an export that says it is a
    different release is a file to register rather than one to read under this
    list's key.
    """
    from brightway_flows.filesystem import stepwise_csv_path

    csv_path = download(stepwise_csv_path(source.list_version), force=force)
    blocks = _blocks(csv_path)
    method = _method_block(blocks)
    declared = _method_version(method)
    expected = method_revision(source.list_version)
    name = str(method.get("Name") or "").strip()
    if name != STEPWISE_METHOD_NAME or declared != expected:
        raise ValueError(
            f"{csv_path} is method {name!r} version {declared!r}; "
            f"{source.key} is {STEPWISE_METHOD_NAME!r} version {expected!r}. "
            "Register the other release rather than reading it under this "
            "list's key: its flows are published under this version and its "
            "context rules are keyed to it."
        )

    records = flows_from_blocks(blocks, source=source.source_label)
    source.flows_path.write_bytes(orjson.dumps(records, option=orjson.OPT_INDENT_2))
    logger.info(
        "stepwise_flows_written", path=str(source.flows_path), flows=len(records)
    )
    return source.flows_path
