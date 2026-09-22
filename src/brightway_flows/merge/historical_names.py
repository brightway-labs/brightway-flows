"""Names ecoinvent retired, read as evidence of last resort.

ecoinvent has renamed flows at every release since 2.2: `Basalt, in ground`
became `Basalt`, `Carbon dioxide, biogenic` became `Carbon dioxide, non-fossil`,
and the misspelt `Bicyclorpyrone` became `Bicyclopyrone`.  A list built on an
older release still ships the old spelling, and a row carrying one describes a
substance this list already holds while matching nothing -- ecoinvent 3.8's
`Sulfate, ion` and `Laterite, in ground` each minted a duplicate of an object
the same build had already published under the newer name.

The remedy is one file, `data/ecoinvent-historical-names.json`, derived
mechanically from the vendor's own 2.2 -> 3.12 correspondence by
``tools/derive_ecoinvent_historical_names.py`` and checked in for review.  Each
entry says: this retired name, wherever it appears, is the newest release's
name for the same flow.  It is the element/ion rule's reading -- the newest
release is the vendor's current opinion (`merge/species.py`) -- carried from
uuid space into name space, for rows that arrive without ecoinvent uuids.

**Consulted last, like the SimaPro spellings and for the same reason.**
:func:`brightway_flows.merge.matching.resolve_flow_object` reaches for this
file only after every registry number and every name the source actually
shipped has failed, rewrites the row's names through it, and looks the results
up in the ordinary label index under its own basis, ``historical-name``.  An
entry that is wrong can therefore only touch a row that was going to be
reported unmatched -- or minted as a duplicate -- anyway.  Unlike the SimaPro
rewriting, the lookup is not gated to a lineage: every entry is a string the
vendor itself shipped for a known flow, a dictionary rather than a pattern, so
there is no derived guess to confine.

**What must not arrive through this file.**  The derivation drops -- and this
loader refuses, so a hand edit cannot smuggle one back in -- three families the
correspondence also contains:

* a **bare element name** (`Cadmium`): in water it became `Cadmium II`, in air
  it stayed the element, so the right object depends on the compartment, which
  a name alias cannot see.  The element/ion family is `merge/species.py`'s
  business.
* a **generic ion moved to a stated charge** (`Calcium, ion` -> `Calcium II`):
  writing the charge in would be this file assigning an oxidation state, which
  is the species rule's decision, not an alias's.
* an **occupation or transformation name**: land rows match by decomposed land
  class (`land-flow-groupings.json`), not by label, and a name cannot separate
  `Transformation, from` and `to` once both reach one object.

A malformed entry raises (rule 14): an alias silently skipped is a row that
looks matchable and is not.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import orjson

from brightway_flows.context_mapping import normalize_mapping_text
from brightway_flows.filesystem import PACKAGE_DATA_DIR
from brightway_flows.merge.species import parse_species

#: The derived file. One constant per data file (rule 5).
HISTORICAL_NAMES_FILEPATH = PACKAGE_DATA_DIR / "ecoinvent-historical-names.json"

#: Bumped when the file's shape changes; module-local (rule 13).
HISTORICAL_NAMES_SCHEMA_VERSION = 1

#: Land rows match by decomposed land class, never by label, so a land name in
#: this file would claim a decision the land machinery already owns.
LAND_NAME_PREFIXES = ("occupation,", "transformation,")


class HistoricalNameError(ValueError):
    """A historical-names file that cannot be read as one.

    Raised rather than skipped (rule 14): an alias silently ignored is a row
    that looks matchable and is not.
    """


@dataclass(frozen=True)
class HistoricalName:
    """One retired vendor name, and the newest release's name for that flow."""

    #: The retired name, verbatim as an earlier release shipped it.
    historical_name: str
    #: The newest release's name for the same flow, verbatim.
    canonical_name: str
    #: The release whose statement the canonical name is.
    decided_by: str


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise HistoricalNameError(message)


def _refuse_species_families(position: int, entry: HistoricalName) -> None:
    """The element/ion families the file's docstring promises are absent."""
    source = parse_species(entry.historical_name)
    if source is None:
        return
    target = parse_species(entry.canonical_name)
    _require(
        source.kind != "bare",
        f"entry {position} ({entry.historical_name!r}) is a bare element name; "
        f"which species a bare element is depends on the compartment, and that "
        f"is merge/species.py's decision, not an alias's",
    )
    _require(
        target is not None
        and target.element == source.element
        and target.kind == source.kind,
        f"entry {position} ({entry.historical_name!r} -> "
        f"{entry.canonical_name!r}) changes what is stated about an element's "
        f"species; assigning or removing a charge is merge/species.py's "
        f"decision, not an alias's",
    )


def load_historical_names(path: Path | None = None) -> dict[str, HistoricalName]:
    """The retired names, keyed by their normalised spelling.

    Not cached: the path is injectable, and a test's file must not be answered
    with the derived one (rule 13).
    """
    filepath = path or HISTORICAL_NAMES_FILEPATH
    if not filepath.exists():
        return {}
    payload = orjson.loads(filepath.read_bytes())
    _require(isinstance(payload, dict), f"{filepath.name} is not an object")
    version = payload.get("schema_version")
    _require(
        version == HISTORICAL_NAMES_SCHEMA_VERSION,
        f"{filepath.name} is schema version {version!r}; this reads "
        f"{HISTORICAL_NAMES_SCHEMA_VERSION}",
    )
    rows = payload.get("names")
    _require(isinstance(rows, list), f"{filepath.name} carries no names list")

    index: dict[str, HistoricalName] = {}
    for position, row in enumerate(rows):
        _require(isinstance(row, dict), f"entry {position} is not an object")
        historical = str(row.get("historical_name") or "").strip()
        canonical = str(row.get("canonical_name") or "").strip()
        decided_by = str(row.get("decided_by") or "").strip()
        _require(bool(historical), f"entry {position} names no historical name")
        _require(
            bool(canonical),
            f"entry {position} ({historical!r}) names no canonical name",
        )
        _require(
            bool(decided_by),
            f"entry {position} ({historical!r}) says no release decided it",
        )
        key = normalize_mapping_text(historical)
        _require(
            key != normalize_mapping_text(canonical),
            f"entry {position} ({historical!r}) maps a name to its own "
            f"spelling, which decides nothing and must not exist",
        )
        _require(
            key not in index,
            f"entry {position} is the second for {historical!r}; a name with "
            f"two answers is decided by context, which an alias cannot see",
        )
        _require(
            not key.startswith(LAND_NAME_PREFIXES),
            f"entry {position} ({historical!r}) is a land name; land rows are "
            f"decided by the curated land classes, not by label",
        )
        entry = HistoricalName(
            historical_name=historical,
            canonical_name=canonical,
            decided_by=decided_by,
        )
        _refuse_species_families(position, entry)
        index[key] = entry
    return index
