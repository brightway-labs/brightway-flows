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

import orjson
import structlog

from brightway_flows.domain.property_statements import (
    PropertyStatement,
    StatementOrigin,
    parse_value_per_unit,
    vendor_statement,
)
from brightway_flows.domain.quantities import (
    CALORIFIC_VALUE,
    quantity,
    quantity_for_label,
)
from brightway_flows.domain.units import unit_row_for
from brightway_flows.downloads import FILES_BRIGHTWAY_DEV, PinnedFile
from brightway_flows.integrations.ecoinvent import normalize_cas_number
from brightway_flows.sources import SourceList

logger = structlog.get_logger(__name__)

#: This project's copy of each export, by ``list_version``.  Stepwise 2006 is
#: distributed inside SimaPro rather than at a vendor URL, so this is a copy
#: taken from a SimaPro installation and published unchanged; the filename
#: carries the version.  The digest is the copy every build has read.
STEPWISE_DOWNLOADS: dict[str, PinnedFile] = {
    "2006-1.09": PinnedFile(
        urls=(f"{FILES_BRIGHTWAY_DEV}Stepwise2006_v1.09.csv",),
        sha256="32d74b52b5facb95b42376c0c9f685c072fcd89a943bdd56a61e47f31a0bba8b",
    ),
}

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

#: A line of the substance comment stating a property: a label, a colon, and
#: a value with its unit per the flow's -- ``Higher heating value (HHV): 19.1
#: MJ/kg``, ``Specific weight (for absolutely dry, u=0%): 650 kg/m3``.  The
#: label has to be one `quantities.json` spells; `Formula:` and `Synonyms:`
#: are the other lines these comments hold and name no quantity.
_PROPERTY_LINE = re.compile(r"^\s*(?P<label>[^:]+?)\s*:\s*(?P<rest>\S.*?)\s*$")

#: The method's energy category.  Its factor on a kilogram or cubic-metre flow
#: is the megajoules the method counts that unit of the flow as -- what a
#: Stepwise kilogram of coal *is*, to Stepwise -- and the one place the method
#: states an energy content.  The method says neither net nor gross: the
#: factor is the substance block's higher heating value for hard coal, the
#: lower one for `Coal, 18 MJ per kg`, and neither for natural gas.
STEPWISE_ENERGY_CATEGORY = "Non-renewable energy"


def _kind_of(unit: str) -> str:
    row = unit_row_for(unit)
    return str(row.get("quantity_kind_iri") or "") if row is not None else ""


def statements_from_substance_comment(
    comment: str,
    *,
    flow_unit: str,
    row_name: str,
    block: str,
    export: str,
    source: str,
) -> tuple[list[PropertyStatement], list[str]]:
    """What a SimaPro substance comment states about one unit of the flow.

    SimaPro's substance library writes a fuel's heating values into the free
    text beside its synonyms -- ``Higher heating value (HHV): 19.1 MJ/kg``,
    ``Lower heating value (LHV): 18.2 MJ/kg`` -- and a wood's ``Specific weight
    (for absolutely dry, u=0%): 650 kg/m3``.  Each is a
    :class:`~brightway_flows.domain.property_statements.PropertyStatement` the
    vendor makes, `stated_by` ``vendor-flow``, with the line quoted as its
    primary source.  The label is matched against the vocabulary's spellings
    (:func:`~brightway_flows.domain.quantities.quantity_for_label`), so the
    higher heating value is a gross calorific value and the lower a net one.

    Returns the statements and the lines that *looked* like one and were not
    read, for the caller to log: a unit `units.json` does not know (the
    library's `18.2 MH/kg` for hard coal is a typo in the vendor's file, and
    the net value of that coal stays a curated statement that says so), a
    value of zero, which converts nothing, or a value per a unit of another
    kind than the flow's own.  Not raised: this module reports what the file
    says, and a line it cannot read is reported as unread rather than guessed
    at.
    """
    statements: list[PropertyStatement] = []
    refused: list[str] = []
    flow_kind = _kind_of(flow_unit)
    for line in str(comment or "").splitlines():
        match = _PROPERTY_LINE.match(line)
        if match is None:
            continue
        slug = quantity_for_label(match["label"])
        if slug is None:
            continue
        parsed = parse_value_per_unit(match["rest"])
        if parsed is None:
            refused.append(line.strip())
            continue
        value, unit, per_unit = parsed
        unit_kind, per_kind = _kind_of(unit), _kind_of(per_unit)
        if (
            value <= 0
            or not unit_kind
            or not per_kind
            or unit_kind != quantity(slug).quantity_kind_iri
            or unit_kind == per_kind
            or (flow_kind and per_kind != flow_kind)
        ):
            refused.append(line.strip())
            continue
        statements.append(
            vendor_statement(
                quantity=slug,
                value=value,
                unit=unit,
                per_unit=per_unit,
                stated_by=StatementOrigin.VENDOR_FLOW,
                primary_source=[
                    f"{export}, substance block `{block}`, row `{row_name}`: "
                    f"`{line.strip()}`"
                ],
                derived_from=export,
                generated_by=f"fetch_{source}",
                attributed_to=source,
                comment=(
                    f"The vendor's substance library states it beside the "
                    f"flow's synonyms: `{line.strip()}`."
                ),
            )
        )
    return statements, refused


def _energy_factors(blocks: list[Any]) -> dict[tuple[str, str, str], tuple[float, str]]:
    """The method's energy factor on every flow it characterises.

    ``(name, compartment, subcompartment) -> (amount, the unit the factor is
    per)``, from :data:`STEPWISE_ENERGY_CATEGORY`.  Only the category whose
    unit is megajoules: a category by that name in another unit would be a
    different method's.
    """
    found: dict[tuple[str, str, str], tuple[float, str]] = {}
    for block in _named(blocks, "ImpactCategory"):
        if str(block.parsed.get("name") or "").strip() != STEPWISE_ENERGY_CATEGORY:
            continue
        unit = str(block.parsed.get("unit") or "").strip()
        if not unit.startswith("MJ"):
            raise ValueError(
                f"The method's {STEPWISE_ENERGY_CATEGORY!r} category is stated in "
                f"{unit!r}, not megajoules; its factors are not energy contents."
            )
        for factor in block.parsed.get("cfs", []):
            name = str(factor.get("name") or "").strip()
            context = [str(part) for part in (factor.get("context") or [])]
            if not name or len(context) != 2:
                continue
            found[(name, context[0], context[1])] = (
                float(factor.get("factor") or 0.0),
                str(factor.get("unit") or "").strip(),
            )
    return found


def _method_statement(
    *, name: str, compartment: str, subcompartment: str, amount: float, per_unit: str,
    export: str, source: str,
) -> PropertyStatement | None:
    """The method's energy factor as a statement about one unit of the flow.

    ``None`` where the factor states no property: zero (the method looked at
    standing wood and counts it as nothing), or per a unit that is itself an
    energy (`Energy, from coal` at 1 MJ per MJ is the unit table's fact).  The
    quantity is a calorific value of unstated basis, because that is all the
    method says; the list's statements file rules the uranium rows fission
    energy, which the method's number is for them.
    """
    if amount <= 0 or not per_unit:
        return None
    if _kind_of(per_unit) == quantity(CALORIFIC_VALUE).quantity_kind_iri:
        return None
    if not _kind_of(per_unit):
        return None
    return vendor_statement(
        quantity=CALORIFIC_VALUE,
        value=amount,
        unit="MJ",
        per_unit=per_unit,
        stated_by=StatementOrigin.VENDOR_METHOD,
        primary_source=[
            f"{export}, impact category `{STEPWISE_ENERGY_CATEGORY}`, row "
            f"`{compartment}; {subcompartment}; {name}`: {amount} MJ per {per_unit}"
        ],
        derived_from=export,
        generated_by=f"fetch_{source}",
        attributed_to=source,
        comment=(
            f"The factor the method's `{STEPWISE_ENERGY_CATEGORY}` category gives "
            f"one {per_unit} of this flow: what Stepwise counts that {per_unit} "
            f"as, in megajoules. The method states neither net nor gross."
        ),
    )


def download(source: SourceList, *, force: bool = False) -> Path:
    """The method export for *source*, downloaded unless it is already there.

    Downloaded from this project's copy of the release
    (:data:`STEPWISE_DOWNLOADS`) and checked against its digest.  *force*
    downloads it again.  A release with no copy is a person's next action, and
    the error says which file and where.
    """
    from brightway_flows.filesystem import stepwise_csv_path

    csv_path = stepwise_csv_path(source.list_version)
    pinned = STEPWISE_DOWNLOADS.get(source.list_version)
    if pinned is not None:
        pinned.download(csv_path, force=force)
    if not csv_path.exists():
        raise FileNotFoundError(
            f"Stepwise's SimaPro method export for {source.key} is not at "
            f"{csv_path}, and this project hosts no copy of that release: "
            "export it from SimaPro and place it there."
        )
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
    return flows_from_blocks(_blocks(csv_path), source=source, export=csv_path.name)


def flows_from_blocks(
    blocks: list[Any], *, source: str, export: str = ""
) -> list[dict[str, Any]]:
    """The flows *blocks* characterise, as source-list records.

    Faithful to what the export says.  A registry number is written as the
    substance block gives it, normalised only in the way every list's is --
    ``000071-36-3`` is 71-36-3 with SimaPro's zero padding, not a different
    number.  A characterised name the substance blocks have no row for is
    emitted with no unit and counted: it is the vendor's own gap, the loader
    drops such a row, and inventing a unit here would hide which rows are
    missing from a file a correction could name.

    Two things the export states about a unit of a flow are written as
    ``property_statements`` on the record, in the shape
    :class:`~brightway_flows.domain.property_statements.PropertyStatement`
    serialises to: the heating values and specific weights in the substance
    block's comment (:func:`statements_from_substance_comment`), and the
    megajoules the method's energy category gives the flow
    (:data:`STEPWISE_ENERGY_CATEGORY`).  The second is a factor, and the
    factors are otherwise read here and not written (the module docstring);
    this one is written because it is also the vendor's statement of what a
    kilogram of its coal *is*, which is what #407 asks a list for, and the
    merge converts by it only where the list's statements file rules that it
    should.  *export* is the file's name, for the statements' provenance.
    """
    substances = _substances(blocks)
    characterised = _characterised_flows(blocks)
    energy = _energy_factors(blocks)

    records: list[dict[str, Any]] = []
    unknown_compartments: dict[str, int] = defaultdict(int)
    without_substance_row: list[str] = []
    categories_seen: set[str] = set()
    unread_property_lines: list[str] = []
    statements_written = 0

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
        raw_comment = str(substance.get("comment") or "")
        synonyms, comment = parse_substance_comment(raw_comment)
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
        statements, refused = statements_from_substance_comment(
            raw_comment, flow_unit=unit, row_name=name, block=heading,
            export=export, source=source,
        )
        unread_property_lines.extend(f"{name}: {line}" for line in refused)
        factor = energy.get((name, compartment, subcompartment))
        if factor is not None:
            method = _method_statement(
                name=name, compartment=compartment, subcompartment=subcompartment,
                amount=factor[0], per_unit=factor[1], export=export, source=source,
            )
            if method is not None:
                statements.append(method)
        if statements:
            record["property_statements"] = [s.to_dict() for s in statements]
            statements_written += len(statements)
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
    if unread_property_lines:
        logger.warning(
            "stepwise_property_lines_not_read",
            count=len(unread_property_lines),
            lines=unread_property_lines[:10],
        )
    logger.info(
        "stepwise_elementary_flows_extracted",
        flows=len(records),
        with_cas=sum(1 for row in records if "cas_numbers" in row),
        with_synonyms=sum(1 for row in records if "synonyms" in row),
        with_property_statements=sum(
            1 for row in records if "property_statements" in row
        ),
        property_statements=statements_written,
        contexts=len({tuple(row["context"]) for row in records}),
        units=sorted({row["unit"] for row in records}),
        impact_categories=len(categories_seen),
        substances_without_factors=len(uncharacterised),
    )
    return records


def fetch(source: SourceList, *, force: bool = False) -> Path:
    """The :class:`~brightway_flows.sources.SourceAdapter` for Stepwise 2006.

    *force* downloads the export again (:func:`download`).  Parsing happens
    either way: the whole cost is one pass over a 1.1 MB text file.

    The method's own version is checked against the manifest's, because the two
    are one claim.  ``list_version`` is what the flows are published under and
    what this list's curated files are keyed to, so an export that says it is a
    different release is a file to register rather than one to read under this
    list's key.
    """
    csv_path = download(source, force=force)
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

    records = flows_from_blocks(
        blocks, source=source.source_label, export=csv_path.name
    )
    source.flows_path.write_bytes(orjson.dumps(records, option=orjson.OPT_INDENT_2))
    logger.info(
        "stepwise_flows_written", path=str(source.flows_path), flows=len(records)
    )
    return source.flows_path
