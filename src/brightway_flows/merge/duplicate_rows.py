"""Source rows a list ships twice, and which of the two is the valid one.

GreenDelta's openLCA package ships `Occupation, annual crop` once in
`Resource / land` and again in `Resource / unspecified`: same name, same unit,
same land class.  Both rows reach one consensus flow, which is right -- they are
one flow -- but nothing about two rows reaching one flow says so.  The land-fold
check (:mod:`brightway_flows.merge.land_groupings`) reads it as two land classes
folded together and stops the build, and the match strength reads it as two
flows sharing a consensus flow and weakens both mappings to `skos:broadMatch`.

`source-row-duplicates.json` says which it is.  Each entry names a duplicate,
the row kept as valid, and why that one, and the merge does three things with
it:

* it checks that the two reached the same consensus flow, and stops if not:
  the ruling says they are one flow, and a merge that separates them has made a
  decision nobody wrote down;
* it takes the duplicate out of the land-fold check, since two copies of one
  class are not a fold;
* it marks the duplicate's published mapping `owl:deprecated`, with
  `dcterms:isReplacedBy` pointing at the valid row, which also keeps it out of
  the count that decides match strength (:mod:`brightway_flows.pipeline.match_strength`),
  and says so in the mapping's provenance: the ruling file and the row kept
  join its `prov:hadPrimarySource`, so a reader of the association can see
  why the row is superseded and not only that it is.

The source-list counterpart of `elementary-flow-collision-decisions.json`,
which rules on two flows this project publishes.  A ruling names its list and
not its release, as a land grouping does: within one list a uuid names the same
flow across releases.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from functools import cache
from typing import Any

import orjson
import structlog

from brightway_flows.domain.common import Provenance
from brightway_flows.domain.elementary_flow import ElementaryFlow
from brightway_flows.domain.vocabulary import (
    DCTERMS_IS_REPLACED_BY_CURIE,
    OWL_DEPRECATED_CURIE,
    PROV_HAD_PRIMARY_SOURCE_CURIE,
    XKOS_SOURCE_CONCEPT_CURIE,
)
from brightway_flows.filesystem import PACKAGE_DATA_DIR

logger = structlog.get_logger(__name__)

DUPLICATES_FILEPATH = PACKAGE_DATA_DIR / "source-row-duplicates.json"

DECISIONS_SCHEMA_VERSION = 1

REQUIRED_FIELDS = ("list_name", "duplicate_uuid", "valid_uuid", "comment")


@dataclass(frozen=True)
class DuplicateRow:
    """One source row that is another row of the same list, shipped twice."""

    list_name: str
    duplicate_uuid: str
    valid_uuid: str
    comment: str


@cache
def load_source_row_duplicates() -> dict[tuple[str, str], DuplicateRow]:
    """Every ruling, keyed by ``(list_name, duplicate_uuid)``.

    :raises ValueError: if the file versions a format this module does not
        read, if an entry is missing a field, names itself as its own valid
        row, names a duplicate twice, or names as valid a row that is itself
        ruled a duplicate.  Each would leave a row looking decided when it is
        not.
    """
    if not DUPLICATES_FILEPATH.exists():
        return {}
    payload = orjson.loads(DUPLICATES_FILEPATH.read_bytes())
    version = payload.get("schema_version")
    if version != DECISIONS_SCHEMA_VERSION:
        raise ValueError(
            f"{DUPLICATES_FILEPATH.name} is schema_version {version!r}; this "
            f"reads {DECISIONS_SCHEMA_VERSION}."
        )
    entries = payload.get("duplicates")
    if not isinstance(entries, list):
        raise ValueError(f"{DUPLICATES_FILEPATH.name} has no 'duplicates' list.")

    out: dict[tuple[str, str], DuplicateRow] = {}
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(f"Entry {index} in {DUPLICATES_FILEPATH.name} is not an object.")
        values = {name: str(entry.get(name) or "").strip() for name in REQUIRED_FIELDS}
        missing = [name for name, value in values.items() if not value]
        if missing:
            raise ValueError(
                f"Entry {index} in {DUPLICATES_FILEPATH.name} has no "
                f"{', '.join(missing)}."
            )
        row = DuplicateRow(**values)
        if row.duplicate_uuid == row.valid_uuid:
            raise ValueError(
                f"Entry {index} in {DUPLICATES_FILEPATH.name} names "
                f"{row.duplicate_uuid} as a duplicate of itself."
            )
        key = (row.list_name, row.duplicate_uuid)
        if key in out:
            raise ValueError(
                f"Entry {index} in {DUPLICATES_FILEPATH.name} rules on "
                f"{row.duplicate_uuid} a second time."
            )
        out[key] = row
    for row in out.values():
        if (row.list_name, row.valid_uuid) in out:
            raise ValueError(
                f"{DUPLICATES_FILEPATH.name} keeps {row.valid_uuid} as the "
                f"valid {row.list_name} row for {row.duplicate_uuid}, and also "
                f"rules it a duplicate. Point the duplicate at the row kept."
            )
    return out


def duplicates_reaching_their_valid_row(
    targets: Mapping[str, str],
    *,
    list_name: str,
    source_label: str,
    source_uuids: Collection[str],
    duplicates: Mapping[tuple[str, str], DuplicateRow] | None = None,
) -> dict[str, DuplicateRow]:
    """The rulings this merge bears out, by duplicate uuid.

    *source_uuids* is every row this merge was given, and *targets* is where
    the rows that landed went, as the consensus flow's id by source uuid.  The
    two are kept apart because a row missing from each means a different thing:

    * a ruling naming a row that is not in *source_uuids* -- a release that
      does not ship it, or a bounded run that left it out -- is not this
      merge's to check, and is skipped;
    * a ruling whose rows were both given and neither landed has nothing to
      mark: both are published unmatched, together, and the count is logged;
    * a ruling whose rows were both given and only one landed is a split, as
      two rows landing apart is.  The ruling says they are one flow, and a
      merge that matched one copy and not the other has separated them.  Left
      as a skip, the copy ruled a duplicate would publish as the only live
      mapping, with nothing to say the ruling went unapplied.

    :raises ValueError: if a duplicate and its valid row were both given and
        did not land together, whether apart or only one of them.
    """
    rulings = {
        uuid: row
        for (ruled_list, uuid), row in (
            duplicates if duplicates is not None else load_source_row_duplicates()
        ).items()
        if ruled_list == list_name
    }
    borne_out: dict[str, DuplicateRow] = {}
    split: list[str] = []
    unmatched_pairs = 0
    for uuid, row in rulings.items():
        if uuid not in source_uuids or row.valid_uuid not in source_uuids:
            continue
        duplicate_target = targets.get(uuid)
        valid_target = targets.get(row.valid_uuid)
        if not duplicate_target and not valid_target:
            unmatched_pairs += 1
            continue
        if duplicate_target != valid_target:
            split.append(
                f"{uuid} reached {duplicate_target or 'nothing'}, its valid row "
                f"{row.valid_uuid} reached {valid_target or 'nothing'}"
            )
            continue
        borne_out[uuid] = row
    if split:
        raise ValueError(
            f"{len(split)} {source_label} row(s) ruled duplicates in "
            f"{DUPLICATES_FILEPATH.name} did not land with the row they "
            f"duplicate; refusing to write artifacts. Either the ruling is "
            f"wrong, or the merge placed one of the two by a route the other "
            f"did not take:\n  " + "\n  ".join(split)
        )
    if unmatched_pairs:
        logger.info(
            "duplicate_source_rows_unmatched_together",
            source=source_label,
            pairs=unmatched_pairs,
        )
    return borne_out


def mark_deprecated_mappings(
    flows: Iterable[ElementaryFlow],
    borne_out: Mapping[str, DuplicateRow],
    *,
    flow_iri_prefix: str,
    merge_activity: str,
) -> int:
    """Mark each borne-out duplicate's mapping deprecated, onto its valid row.

    Written on the source concept, beside its `skos:` mapping property, because
    both are statements about the vendor's flow: that it is superseded, and by
    which of the vendor's own flows.  The association's provenance is merged
    in the same change: the ruling file and the row kept are added to its
    `prov:hadPrimarySource`, beside the match's own sources, and an
    association with no provenance yet gets one generated by *merge_activity*.
    Returns how many mappings were marked.
    """
    by_iri = {
        f"{flow_iri_prefix}{uuid}": row for uuid, row in borne_out.items()
    }
    marked = 0
    for flow in flows:
        for association in flow.concept_associations or []:
            if not isinstance(association, dict):
                continue
            source = association.get(XKOS_SOURCE_CONCEPT_CURIE)
            if not isinstance(source, dict):
                continue
            row = by_iri.get(str(source.get("@id") or ""))
            if row is None:
                continue
            source[OWL_DEPRECATED_CURIE] = True
            source[DCTERMS_IS_REPLACED_BY_CURIE] = {
                "@id": f"{flow_iri_prefix}{row.valid_uuid}"
            }
            _merge_ruling_provenance(association, row, merge_activity=merge_activity)
            marked += 1
    return marked


def _merge_ruling_provenance(
    association: dict[str, Any], row: DuplicateRow, *, merge_activity: str
) -> None:
    """Add the ruling to the association's provenance, keeping what is there."""
    provenance = association.get("provenance")
    if not isinstance(provenance, dict):
        provenance = Provenance(
            was_generated_by=merge_activity, was_attributed_to="brightway-flows"
        ).to_dict()
        association["provenance"] = provenance
    sources = provenance.get(PROV_HAD_PRIMARY_SOURCE_CURIE)
    if not isinstance(sources, list):
        sources = []
        provenance[PROV_HAD_PRIMARY_SOURCE_CURIE] = sources
    for entry in (
        DUPLICATES_FILEPATH.name,
        f"duplicate_of={row.list_name}:{row.valid_uuid}",
    ):
        if entry not in sources:
            sources.append(entry)

