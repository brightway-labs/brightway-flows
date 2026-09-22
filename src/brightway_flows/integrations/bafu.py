"""Reading BAFU's elementary flows.

BAFU distributes process datasets in ecoSpold v1, not a flow list: there are
11,947 of them and the elementary flows are exchanges inside, repeated once per
process that uses them.  Extraction is therefore a collapse -- 293,747 exchanges
down to the 2,679 distinct flows they name.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterator
from zipfile import ZipFile

import orjson
import structlog
from lxml import etree

from brightway_flows.integrations.ecoinvent import normalize_cas_number
from brightway_flows.simapro_names import (
    canonical_geography_code,
    split_geography_suffix,
)
from brightway_flows.sources import SourceList

logger = structlog.get_logger(__name__)


#: ecoSpold v1 files an exchange's role in an ``inputGroup`` or ``outputGroup``
#: child.  Group 4 is nature on both sides -- resources coming in, emissions
#: going out -- and is the whole of what makes an exchange elementary.  The
#: other groups are technosphere (5), the reference product (0) and so on.
_ELEMENTARY_GROUP = "4"
_GROUP_ELEMENTS = ("inputGroup", "outputGroup")

#: What names a BAFU flow.
#:
#: ecoSpold v1 also carries a `number` on every exchange, and within one export
#: it maps one-to-one onto ``(name, category)``.  It is deliberately **not**
#: used as the identity, for two reasons.  The 2025 extraction kept no numbers,
#: so nothing else can line the releases up -- and, more importantly, the
#: numbers are not promised to be stable across exports.  BAFU ships more than
#: one a year, and an identity built on a number that silently renumbers would
#: move flows between releases with nothing detecting it: worse than the
#: name-derived scheme's failure, which at least announces itself as a flow
#: appearing and another disappearing.
#:
#: The cost of name-derived identity is that a flow BAFU renames becomes a new
#: flow rather than the same one moved.  That is the trade taken here.
#:
#: ``name`` is the name **after** the geography is taken out of it, where that
#: happens, and the place joins these as a fifth field -- see
#: :func:`_flow_uuid`.  A regionalised row is not the same flow as its
#: unregionalised sibling and must not fuse with it: it is BAFU's own flow, it
#: keeps its own identifier, and it is what its correspondence cites.
_IDENTITY_FIELDS = ("name", "category", "subCategory", "unit")

#: Deliberately version-free, unlike the IRI prefix.  A flow that 2026 v1 and
#: v2 both ship is one flow, and giving each export its own namespace would
#: make every one of them new.  Derived from the IRI stem rather than written
#: as a literal, so the identifier and what it is published under cannot drift.
#: Changing it is a one-way door: both are read once a build has shipped.
BAFU_FLOW_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "https://vocab.brightway.one/bafu/")


def _flow_uuid(
    name: str, category: str, sub_category: str, unit: str, location: str = ""
) -> str:
    """The identifier for one BAFU flow.

    *location* is appended only when there is one, so the 2,417 flows that
    carry no geography keep the identifiers they were first published with.
    Only the 262 regionalised ones are renumbered, and they have to be: with
    the place taken out of the name, `Water, AE` and `Water, AR` are the same
    four fields in the same context, and without the place in the seed they
    would fuse into one flow and take BAFU's distinction with them.

    The code seeds this **as the vendor wrote it**, not canonicalised. Reading
    `CS` as Serbia is a statement about the place, not about the row, and doing
    it here would fuse `Water, CS` with `Water, RS` the day a release puts both
    in one context.
    """
    fields = (name, category, sub_category, unit)
    return str(
        uuid.uuid5(
            BAFU_FLOW_NAMESPACE,
            "|".join((*fields, location) if location else fields),
        )
    )


def _elementary_exchanges(archive: Path) -> Iterator[dict[str, str]]:
    """Every elementary exchange in *archive*, as its raw attributes.

    Takes the vendor's zip or an unpacked directory of it.  The zip is read
    without unpacking: it is 38 MB compressed against 225 MB on disk, and
    nothing here needs a second pass over a file.
    """

    def _from_xml(payload: bytes) -> Iterator[dict[str, str]]:
        root = etree.fromstring(payload)
        for exchange in root.iter():
            if etree.QName(exchange).localname != "exchange":
                continue
            for child in exchange:
                if etree.QName(child).localname not in _GROUP_ELEMENTS:
                    continue
                if (child.text or "").strip() == _ELEMENTARY_GROUP:
                    yield dict(exchange.attrib)
                break

    if archive.is_dir():
        for path in sorted(archive.rglob("*.xml")):
            yield from _from_xml(path.read_bytes())
        return

    with ZipFile(archive) as zf:
        for member in sorted(zf.namelist()):
            if member.endswith(".xml"):
                yield from _from_xml(zf.read(member))


def extract_elementary_flows(
    archive: Path, *, source: str, split_geography: bool = False
) -> list[dict[str, Any]]:
    """The distinct elementary flows in *archive*, as source-list records.

    Faithful to what BAFU ships.  Where the same flow carries a CAS number in
    two spellings -- ``000071-43-2`` and ``71-43-2`` are both in the data -- the
    two collapse, because they are one number written twice.  Where it carries
    two genuinely different numbers they are both kept, and the flow ships
    ambiguous: twelve records do, all of them a metal in an ``unspecified``
    subcompartment carrying both the element's CAS and its ion's.  Dropping one
    here would be a curation decision taken where nothing can review it, and
    would leave the manual-fixes file with nothing to correct.

    *split_geography* takes the place out of the name and into a field of its
    own -- ``Water, AE`` becomes ``Water`` in ``AE`` (#65).  Off by default and
    passed from the list's ``simapro_origin``, because writing the geography
    into the name is a habit of SimaPro's lineage and reading a trailing field
    as a place is a guess anywhere else.  It is a **rewrite of the row**, not an
    annotation: what reaches the pipeline is the row BAFU would have shipped had
    it modelled geography the way this list does, so every rule between here and
    matching sees a name it recognises.  The name as shipped is kept on
    ``original_name``, for the record and for nothing else to read.
    """
    grouped: dict[tuple[str, ...], list[dict[str, str]]] = defaultdict(list)
    for exchange in _elementary_exchanges(archive):
        shipped = exchange.get("name", "")
        name, location = shipped, ""
        if split_geography and (split := split_geography_suffix(shipped)):
            name, location = split
        fields = tuple(
            name if field == "name" else exchange.get(field, "")
            for field in _IDENTITY_FIELDS
        )
        # The name as shipped rides in the key rather than being looked up
        # again: it is a function of the fields above, so it groups with them
        # and no row can contribute a name its own key did not produce.
        grouped[(*fields, location, shipped if location else "")].append(exchange)

    def _values(rows: list[dict[str, str]], field: str) -> list[str]:
        return sorted({(row.get(field) or "").strip() for row in rows} - {""})

    records: list[dict[str, Any]] = []
    for key, rows in sorted(grouped.items()):
        name, category, sub_category, unit, location, shipped = key
        record: dict[str, Any] = {
            "uuid": _flow_uuid(name, category, sub_category, unit, location),
            "name": name,
            "source": source,
            "context": [category, sub_category],
            "unit": unit,
        }
        if location:
            # Canonical here and written into the identity above: what the row
            # is keyed on should be what the vendor shipped, and what the row
            # reports should be a place that exists.
            record["location"] = canonical_geography_code(location)
            record["original_name"] = shipped
        if cas_numbers := sorted(
            {normalize_cas_number(value) for value in _values(rows, "CASNumber")}
        ):
            record["cas_numbers"] = cas_numbers
        if formulae := _values(rows, "formula"):
            record["formula"] = formulae[0] if len(formulae) == 1 else formulae
        records.append(record)

    ambiguous = [r["name"] for r in records if len(r.get("cas_numbers", ())) > 1]
    logger.info(
        "bafu_elementary_flows_extracted",
        flows=len(records),
        exchanges=sum(len(rows) for rows in grouped.values()),
        with_cas=sum(1 for r in records if "cas_numbers" in r),
        with_formula=sum(1 for r in records if "formula" in r),
        with_location=sum(1 for r in records if "location" in r),
        ambiguous_cas=len(ambiguous),
        ambiguous_cas_names=sorted(set(ambiguous)),
    )
    return records


def fetch(source: SourceList, *, force: bool = False) -> Path:
    """The :class:`~brightway_flows.sources.SourceAdapter` for BAFU.

    *force* is accepted because the protocol has it and re-reads the archive
    either way: the whole cost is one pass over a 38 MB zip, so there is no
    download to skip and nothing to cache.

    Unlike EF 3.1's, this adapter has nothing to download from.  BAFU hands the
    archive over rather than publishing it at a stable URL, so a missing file is
    a person's next action and the error says which file and where.
    """
    from brightway_flows.filesystem import bafu_ecospold_zip_path

    archive = bafu_ecospold_zip_path(source.list_version)
    if not archive.exists():
        raise FileNotFoundError(
            f"BAFU's ecoSpold archive for {source.key} is not at {archive}. It is "
            "not downloadable: obtain it from BAFU and place it there."
        )

    records = extract_elementary_flows(
        archive,
        source=source.source_label,
        # The manifest's word, not the lineage flag: BAFU says
        # `geography_split: "extraction"` because the split is part of the
        # identity its uuids are derived from, and #192 found that reading the
        # flag here made the split look lineage-wide when it ran for exactly
        # one list. It stays a gate either way: reading a trailing field as a
        # place is right for a list SimaPro shaped and a guess for any other.
        split_geography=source.geography_split == "extraction",
    )
    source.flows_path.write_bytes(orjson.dumps(records, option=orjson.OPT_INDENT_2))
    logger.info(
        "bafu_flows_written", path=str(source.flows_path), flows=len(records)
    )
    return source.flows_path
