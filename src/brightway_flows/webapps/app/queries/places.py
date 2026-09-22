"""The substance-in-two-places queue: an item is a group of places, not a row.

The counterpart of `queries/collisions.py`, and it is not a row for the same
reason that one is not.  A collision item is a group of flows in one place; this
one is a group of *places* holding one substance, and the question -- which of
these places is where the substance comes from? -- is answered by reading what
sits in each of them.

Through the shared `queue.html` it was three columns of deduplicated lists:
every place the substance is published in, every unit any of them measures it
in, and every list that published any of them.  Each cell was true and the row
did not say which went with which, so `Peat`, published as `MJ` in
`Resource -> Ground` by EF 3.1 and as `kg` in `Resource -> Biotic` by a row
ecoinvent's merge wrote, rendered as `Resource -> Biotic, Resource -> Ground`
beside `MJ, kg` beside `EF 3.1, ecoinvent algorithm addition` -- three pairs a
reader had to guess the pairing of, and guessing wrong reverses which side is
the one nobody characterised.  One row per place says it instead.

Nothing here is read from the database: `merge/places.py` already writes what
each place holds into the payload, per place, and this projects it.  A payload
from a run older than that field falls back to the contexts the item lists, so
the page degrades to the three-column display it replaces rather than to an
empty table.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from brightway_flows.webapps.app.queries.common import Page


@dataclass(frozen=True)
class Place:
    """One place a substance is published in, and what sits there.

    `units` and `sources` are lists because a place can hold more than one flow:
    two lists filing the substance in one compartment in two units is a unit
    disagreement, which is another queue's question, and this one still has to
    render the place it happens in.
    """

    context: str
    context_iri: str = ""
    units: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()
    flow_ids: tuple[str, ...] = ()
    factor_count: int = 0
    #: The flows here the merge wrote, rather than a source list.
    minted: tuple[str, ...] = ()
    #: True where no other place of this substance is a vaguer description of
    #: this one -- the place with nowhere else to belong, and so the one a
    #: ruling is about.
    belongs_nowhere_else: bool = False

    @property
    def was_minted(self) -> bool:
        return bool(self.minted)


@dataclass
class Split:
    """One substance, and every place it is published in."""

    item: Any
    places: list[Place] = field(default_factory=list)

    @property
    def substance(self) -> str:
        """What to call the substance: its label, falling back to its id."""
        return str(self.item.payload.get("substance") or self.item.flow_object_id)

    @property
    def stranded(self) -> list[Place]:
        return [place for place in self.places if place.belongs_nowhere_else]


def _strings(value: Any) -> tuple[str, ...]:
    """A payload list as strings, and anything else as nothing.

    The payload is JSON written by another run: a field it does not carry is
    absent rather than empty, and one carrying a scalar where a list is expected
    is a run this page cannot read that field from.
    """
    if not isinstance(value, list):
        return ()
    return tuple(str(entry) for entry in value if str(entry))


def _place(record: Any) -> Place | None:
    if not isinstance(record, dict):
        return None
    context = str(record.get("context") or record.get("context_iri") or "")
    if not context:
        return None
    return Place(
        context=context,
        context_iri=str(record.get("context_iri") or ""),
        units=_strings(record.get("units")),
        sources=_strings(record.get("sources")),
        flow_ids=_strings(record.get("elementary_flow_ids")),
        factor_count=int(record.get("lcia_factor_count") or 0),
        minted=_strings(record.get("minted_by_merge")),
        belongs_nowhere_else=bool(record.get("belongs_nowhere_else")),
    )


def places_of(item: Any) -> list[Place]:
    """One item's places, in the order the report wrote them.

    Sorted by nothing here: `merge/places.py` orders them by context IRI, and a
    page that re-sorted would put a substance's places in one order and the
    title naming them in another.
    """
    records = item.payload.get("places")
    if isinstance(records, list) and records:
        return [place for place in map(_place, records) if place is not None]
    # A payload from a run older than the per-place field. The contexts are all
    # it states, so they are all this shows: the units and the sources it also
    # lists are the unpaired sets this page exists to stop showing.
    return [Place(context=context) for context in _strings(item.payload.get("contexts"))]


def splits(page: Page[Any]) -> Page[Split]:
    """The same page of items, with each one's places read.

    Takes the page rather than querying for it, so the queue's paging, search
    and severity filter stay one piece of code for every queue and only the
    rendering differs.
    """
    return Page(
        rows=[Split(item=item, places=places_of(item)) for item in page.rows],
        total=page.total,
        number=page.number,
        size=page.size,
    )
