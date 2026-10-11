"""Reading the elementary flows of GreenDelta's openLCA LCIA method package.

GreenDelta publishes its LCIA methods for openLCA as one JSON-LD archive, and
unlike the 2.8.0 copy inside BAFU's distribution, which held EF 3.1 alone and
the 1,781 flows it characterised, the full package carries every
method GreenDelta implements -- 45 in 2.8.2 -- and the 61,211 elementary flows
they characterise between them.  That is a flow list, and this reads it as one.

**Most of the flows are GreenDelta's own.**  4,479 of 2.8.2's flows carry a UUID
one of the merged lists already ships (ecoinvent 3.8 or 3.12, or EF 3.1); the
other 56,732 do not.  So the package is merged like any other list, and
`greendelta_lcia` reaches GreenDelta's own flows through it.

**Every flow is characterised.**  The package ships no flow that no method
needs, so this is the reach of 45 methods and not an inventory list: a
substance no method characterises is absent, however common it is in
inventories.

What is read from each flow document is what a source-list record carries:

* ``category`` is the compartment.  openLCA writes it as one path,
  ``Elementary flows/Emission to air/unspecified``; the root is the same on
  every elementary flow and says nothing about the place, so the record's
  context is the rest of the path, split.
* the unit is the reference flow property's.  Every flow in 2.8.2 has exactly
  one property, so there is nothing to choose between.
* ``cas`` is written zero-padded on most rows -- ``000058-55-9`` -- and is
  normalised here as BAFU's are, so one number reaches one substance whichever
  list it came from.  A value that is not a CAS number in either spelling is
  kept as shipped, for the CAS transformer to report.
* ``synonyms`` is one string, semicolon-separated.

The names, the duplicates the package ships and the ion rows carrying an
element's CAS are deliberately left as they are: this module reports what the
file says, and correcting it is the manual-fixes file's job.

The characterisation factors are not read.  A list's factors reach a build
through a manifest's ``lcia`` block, and this one declares none.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Iterator
from zipfile import ZipFile

import orjson
import structlog

from brightway_flows.integrations.ecoinvent import normalize_cas_number
from brightway_flows.sources import SourceList

logger = structlog.get_logger(__name__)

_FLOWS = "flows/"

#: The ``flowType`` of a flow this list publishes.  openLCA also has product and
#: waste flows; a method package ships none, and one that did would not be a
#: list of elementary flows.
_ELEMENTARY = "ELEMENTARY_FLOW"

#: The first segment of every elementary flow's category path.
_ROOT = "Elementary flows"


class OpenLcaPackageError(RuntimeError):
    """The archive is not a package this reads."""


def _flow_documents(archive: Path) -> Iterator[dict[str, Any]]:
    """Every flow document in *archive*, in name order."""
    with ZipFile(archive) as zf:
        for member in sorted(zf.namelist()):
            if member.startswith(_FLOWS) and member.endswith(".json"):
                yield orjson.loads(zf.read(member))


def _context(category: str, *, flow_id: str) -> list[str]:
    """The compartment path, without the root every elementary flow shares."""
    parts = [part.strip() for part in category.split("/") if part.strip()]
    if not parts or parts[0] != _ROOT or len(parts) < 2:
        raise OpenLcaPackageError(
            f"Flow {flow_id} is filed under {category!r}, which is not a path "
            f"under {_ROOT!r}. Every elementary flow in the package is."
        )
    return parts[1:]


def _unit(flow: dict[str, Any]) -> str:
    """The reference unit, read off the reference flow property."""
    references = [
        factor
        for factor in flow.get("flowProperties") or ()
        if factor.get("isRefFlowProperty")
    ]
    if len(references) != 1:
        raise OpenLcaPackageError(
            f"Flow {flow.get('@id')} ({flow.get('name')!r}) has "
            f"{len(references)} reference flow properties; it needs one to "
            f"have a unit."
        )
    unit = str((references[0].get("flowProperty") or {}).get("refUnit") or "")
    if not unit:
        raise OpenLcaPackageError(
            f"Flow {flow.get('@id')} ({flow.get('name')!r}) states no unit on "
            f"its reference flow property."
        )
    return unit


def record(flow: dict[str, Any], *, source: str) -> dict[str, Any]:
    """One flow document as a source-list record."""
    flow_id = str(flow["@id"])
    out: dict[str, Any] = {
        "uuid": flow_id,
        "name": str(flow["name"]),
        "source": source,
        "context": _context(str(flow.get("category") or ""), flow_id=flow_id),
        "unit": _unit(flow),
    }
    if cas := str(flow.get("cas") or "").strip():
        out["cas_numbers"] = [normalize_cas_number(cas)]
    if formula := str(flow.get("formula") or "").strip():
        out["formula"] = formula
    if synonyms := [
        synonym.strip()
        for synonym in str(flow.get("synonyms") or "").split(";")
        if synonym.strip()
    ]:
        out["synonyms"] = synonyms
    return out


def extract_elementary_flows(archive: Path, *, source: str) -> list[dict[str, Any]]:
    """The package's elementary flows, as source-list records.

    :raises OpenLcaPackageError: if the archive holds no flows, a flow that is
        not elementary, or a flow whose compartment or unit cannot be read.
        Skipping one would publish a list missing a flow somebody's method
        characterises, with nothing to say so.
    """
    records: list[dict[str, Any]] = []
    flow_types: Counter[str] = Counter()
    for flow in _flow_documents(archive):
        flow_types[str(flow.get("flowType"))] += 1
        if flow.get("flowType") != _ELEMENTARY:
            continue
        records.append(record(flow, source=source))
    if not records:
        raise OpenLcaPackageError(f"{archive.name} holds no elementary flows.")
    if set(flow_types) != {_ELEMENTARY}:
        raise OpenLcaPackageError(
            f"{archive.name} holds flows that are not elementary: "
            f"{dict(flow_types)}. A method package ships none."
        )
    logger.info(
        "openlca_elementary_flows_extracted",
        archive=archive.name,
        flows=len(records),
        with_cas=sum(1 for r in records if "cas_numbers" in r),
        with_formula=sum(1 for r in records if "formula" in r),
        with_synonyms=sum(1 for r in records if "synonyms" in r),
    )
    return records


def fetch(source: SourceList, *, force: bool = False) -> Path:
    """The :class:`~brightway_flows.sources.SourceAdapter` for the package.

    *force* is accepted because the protocol has it and re-reads the archive
    either way: there is no download to skip.  GreenDelta distributes the
    package through openLCA Nexus rather than at a stable URL, so it is placed
    in the data directory by hand and a missing file is a person's next action.
    """
    from brightway_flows.filesystem import openlca_lcia_zip_path

    archive = openlca_lcia_zip_path(source.list_version)
    records = extract_elementary_flows(archive, source=source.source_label)
    source.flows_path.write_bytes(orjson.dumps(records, option=orjson.OPT_INDENT_2))
    logger.info(
        "openlca_flows_written", path=str(source.flows_path), flows=len(records)
    )
    return source.flows_path
