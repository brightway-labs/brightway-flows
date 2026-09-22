"""The two curated per-flow tables, reachable by a name instead of a uuid.

`water-flow-materials.json` and `land-flow-classes.json` answer the two
questions the docs say a name cannot settle -- which kind of water, which land
class -- and both are keyed on the vendor's row uuid, which a query does not
have.  But every row of both tables also records the vendor's `source_name` and
`source_context`, so the curation *is* reachable without the uuid: this module
is that reading, done once, so every caller reads the tables the same way
(#358).

The join is not name-alone, because the tables are not name-alone.  Both of the
water names two rows disagree about split cleanly by compartment: BAFU's
`Water` is water vapour in its air rows and water in its water rows, and
`Water, unspecified natural origin` is fossil groundwater at a fossil well,
groundwater in the ground and plain water in surface water.  So each table is
indexed under three keys per row, and a caller reads exactly the one that
matches what their compartment actually said:

1. the name in a resolved consensus context, for a caller whose compartment
   resolved to one;
2. the name across every context of a dimension, for a caller who wrote `Raw`
   and declined to name a medium -- the dimension is all they have said;
3. the name across the whole table, for a caller whose compartment could not
   be read at all.

A caller never reads a coarser rung than their compartment reaches, because
the coarser rungs hold rows from compartments they did not name: the
whole-table rung holds `Water, lake` -- a resource-side curation -- and
falling through to it from a resolved emission compartment would assert that
curation for an emission, crossing a boundary the caller drew.  A key two
rows disagree about **declines rather than arbitrates** -- the same rule
`material_by_source_flow` enforces per uuid.  On the current tables the third
rung is enough for every land name: no two rows disagree about one, which is
why `Occupation, arable` is answerable with no compartment at all.

The table rows' own compartments are resolved through
:func:`~brightway_flows.lookup.query.resolve_context` under the list each
row came from, so `bafu-2026-v1`'s `["resources", "in water"]` and a caller's
`["Raw", "in water"]` land on the same consensus context and the join holds --
which is the same reason the recorded tier resolves compartments rather than
comparing spellings.
"""

from __future__ import annotations

from functools import lru_cache

import structlog

from brightway_flows.context_mapping import normalize_mapping_text
from brightway_flows.domain.land_flow_classes import land_class_by_source_flow
from brightway_flows.domain.materials import material_by_source_flow
from brightway_flows.lookup.query import (
    FlowQuery,
    ResolvedContext,
    resolve_context,
)

logger = structlog.get_logger(__name__)

#: The rung key for the whole-table reading -- the one a caller whose
#: compartment could not be read at all is answered from.
_WHOLE_TABLE = ""

#: The stored value for a key two curated rows disagree about.  Kept in the
#: index rather than dropped, so the log can count the disagreements and so a
#: later reader of the index sees "the table disagrees here" rather than "the
#: table says nothing here".  A caller is answered ``""`` for both, because
#: there is nothing different they could do with the two.
_CONFLICT = None


@lru_cache(maxsize=1)
def _material_index() -> dict[tuple[str, str], str]:
    return _name_keyed(
        (
            (row["source"], row["source_name"], row.get("source_context") or [], row["node"])
            for row in material_by_source_flow().values()
        ),
        table="water-flow-materials",
    )


@lru_cache(maxsize=1)
def _land_class_index() -> dict[tuple[str, str], str]:
    return _name_keyed(
        (
            (row.source, row.source_name, list(row.source_context), row.key)
            for row in land_class_by_source_flow().values()
        ),
        table="land-flow-classes",
    )


def _name_keyed(rows, *, table: str) -> dict[tuple[str, str], str | None]:
    """``(normalised name, rung key) -> value``, one dict for all three rungs.

    The rung key is the row's resolved context IRI, its dimension prefixed
    ``dim:``, and :data:`_WHOLE_TABLE` -- three entries per row, so a caller is
    reachable at whichever single rung their own compartment turns out to be.
    A key two rows disagree about stores :data:`_CONFLICT`.
    """
    index: dict[tuple[str, str], str | None] = {}
    unresolved = 0
    for source, source_name, source_context, value in rows:
        name = normalize_mapping_text(source_name)
        if not name:
            continue
        resolved = resolve_context(
            FlowQuery(
                name=str(source_name),
                context=[str(part) for part in source_context],
                source_label=str(source),
            )
        )
        keys = [_WHOLE_TABLE]
        if dimension := resolved.dimension:
            keys.append(f"dim:{dimension}")
        if resolved.context_iri:
            keys.append(resolved.context_iri)
        else:
            unresolved += 1
        for key in keys:
            existing = index.get((name, key))
            if existing is not None and existing != value:
                index[(name, key)] = _CONFLICT
            elif (name, key) not in index:
                index[(name, key)] = value
    logger.info(
        "curated_name_index",
        table=table,
        keys=len(index),
        conflicted=sum(1 for value in index.values() if value is _CONFLICT),
        rows_without_context=unresolved,
    )
    return index


def _lookup(
    index: dict[tuple[str, str], str | None], name: str, context: ResolvedContext
) -> str:
    """The curated value for *name* at the caller's own rung, or ``""``.

    One rung, not a ladder: the rung is what the caller's compartment resolved
    to, and a compartment that resolved to a context or a dimension is never
    answered from a coarser rung, because the coarser rungs hold rows from
    compartments the caller did not name.  ``""`` where the rung has no entry
    and where it records a disagreement alike -- a coarser rung could
    "answer" the second, but only by overruling rows that disagree.
    """
    key = normalize_mapping_text(name)
    if not key:
        return ""
    if context.context_iri:
        rung = context.context_iri
    elif dimension := context.dimension:
        rung = f"dim:{dimension}"
    else:
        rung = _WHOLE_TABLE
    return index.get((key, rung)) or ""


def material_for_name(name: str, context: ResolvedContext) -> str:
    """Which material concept the water table records for *name*, or ``""``.

    ``""`` both where no row spells the name at the caller's rung and where
    two rows disagree there; a caller cannot act differently on the two, and
    the second is the one worth declining.
    """
    return _lookup(_material_index(), name, context)


def land_class_for_name(name: str, context: ResolvedContext) -> str:
    """Which land-use key the land table records for *name*, or ``""``."""
    return _lookup(_land_class_index(), name, context)
