"""The periodic table, and what hangs off one element.

`element_coverage` has said for a long time how many of the 118 elements the
list accounts for, and the overview shows the number.  A number is the wrong
shape for that answer: the elements a flow list is missing are not a random
27 of 118, they are the short-lived transactinides and a handful of noble
gases, and a table laid out as the periodic table says that at a glance where
`27 uncovered` says nothing at all.

An element's page then shows the two families that hang off it, which are held
in the record and were reachable from no page:

- **Nuclides.**  `Americium-241` is a flow object in its own right, typed
  `chemrof:Isotope`, carrying its nuclide, half life, decay modes and specific
  activity.  It points back at its element through
  `properties.relationships.parent_element_flow_object_id`.
- **Ions.**  `Antimony(3+)` and `Antimony(5+)` are two more flow objects
  pointing at the same element by the same field, with
  `relationship_type = "ion_of"`.

Both directions of that edge are in the data.  The element carries
`properties.isotopes.consensus_matched` and the isotope carries
`relationships`, and this module reads the **child's** statement rather than
the parent's list, for one reason: the ions are only in the child's, so
reading the parent's list would give an element its isotopes and silently no
ions at all.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any

from brightway_flows.pipeline.review_records import ElementStatus
from brightway_flows.webapps.app.db import table_exists
from brightway_flows.webapps.app.queries.common import load_json

#: `relationship_type` values, and what each family is called on the page.
ISOTOPE_OF = "isotope_of"
ION_OF = "ion_of"

#: Where each element sits in the table, as the table is drawn.
#:
#: Written out rather than computed.  Group and period are derivable from the
#: atomic number only by encoding the block lengths and then the exceptions,
#: which is more code than the answer and gets helium wrong -- its electron
#: configuration is s-block and it is drawn in group 18.  This is the layout,
#: and a layout is a picture.
#:
#: `None` is a gap.  `LANTHANIDES` and `ACTINIDES` are the two markers that
#: stand in group 3 of periods 6 and 7 for the f-block rows drawn beneath, so
#: every element appears in exactly one cell and none is drawn twice.
LANTHANIDES = "lanthanides"
ACTINIDES = "actinides"

PERIODIC_ROWS: tuple[tuple[Any, ...], ...] = (
    (1, *([None] * 16), 2),
    (3, 4, *([None] * 10), 5, 6, 7, 8, 9, 10),
    (11, 12, *([None] * 10), 13, 14, 15, 16, 17, 18),
    tuple(range(19, 37)),
    tuple(range(37, 55)),
    (55, 56, LANTHANIDES, *range(72, 87)),
    (87, 88, ACTINIDES, *range(104, 119)),
)

#: The two f-block rows, drawn under the table.  Indented by two cells so they
#: sit under the marker they belong to rather than under the alkali metals, and
#: padded to the same eighteen so both grids share one column width.
F_BLOCK_ROWS: tuple[tuple[Any, ...], ...] = (
    (None, None, *range(57, 72), None),
    (None, None, *range(89, 104), None),
)

#: What the two markers say in their cell.
MARKER_LABELS: dict[str, str] = {
    LANTHANIDES: "57–71",
    ACTINIDES: "89–103",
}


@dataclass
class ElementCell:
    """One cell of the periodic table.

    *status* is `element_coverage`'s, kept as its own value rather than reduced
    to a boolean: "a flow object exists but nothing in EF 3.1 references it" is
    a different state from "no flow object carries this atomic number", and the
    four elements in the first state are a curation question while the 27 in
    the second are a scope one.
    """

    atomic_number: int
    symbol: str = ""
    name: str = ""
    status: str = ""
    flow_object_id: str = ""
    pubchem_page_url: str = ""
    #: Flow objects that are a nuclide or an ion of this element.
    nuclide_count: int = 0
    ion_count: int = 0

    @property
    def is_linked(self) -> bool:
        return self.status == ElementStatus.LINKED

    @property
    def has_flow_object(self) -> bool:
        return bool(self.flow_object_id)

    @property
    def status_label(self) -> str:
        return {
            ElementStatus.LINKED: "in the list",
            ElementStatus.NOT_LINKED: "a flow object, unreferenced by EF 3.1",
            ElementStatus.MISSING: "not in the list",
        }.get(ElementStatus(self.status) if self.status else "", self.status)


@dataclass
class PeriodicTable:
    """Every cell, plus the counts the page states above it."""

    cells: dict[int, ElementCell] = field(default_factory=dict)
    linked: int = 0
    unreferenced: int = 0
    missing: int = 0

    @property
    def total(self) -> int:
        return len(self.cells)

    def row(self, row: tuple[Any, ...]) -> list[Any]:
        """One layout row as cells, gaps and markers, ready to render.

        A slot naming an atomic number `element_coverage` has no row for
        renders as a gap rather than as an empty cell with a number in it: a
        database written before an element existed should not claim the element
        is uncovered, which is a different statement from having no opinion.
        """
        return [
            self.cells.get(slot) if isinstance(slot, int) else slot for slot in row
        ]


@dataclass
class RelatedObject:
    """A nuclide or an ion of an element, as its row on the element page."""

    flow_object_id: str
    name: str = ""
    flow_type: str = ""
    relationship: str = ""
    #: The isotope block, verbatim, for the nuclides.  Empty for an ion, which
    #: has no such block -- and is why the two families share one row type but
    #: not one table.
    isotope: dict[str, Any] = field(default_factory=dict)
    linked_flows: int = 0

    @property
    def type_label(self) -> str:
        return self.flow_type.rsplit("/", 1)[-1] if self.flow_type else ""

    @property
    def nuclide(self) -> str:
        return str(self.isotope.get("nuclide") or "")

    @property
    def mass_number(self) -> int | None:
        value = self.isotope.get("mass_number")
        return int(value) if isinstance(value, int | float) else None

    @property
    def half_life(self) -> str:
        return str(self.isotope.get("half_life_and_uncertainty") or "")

    @property
    def decay_modes(self) -> str:
        return str(self.isotope.get("decay_modes") or "")

    @property
    def specific_activity(self) -> str:
        return str(self.isotope.get("specific_activity_bq_per_g") or "")

    @property
    def chemlin_url(self) -> str:
        return str(self.isotope.get("chemlin_url") or "")


@dataclass
class ElementDetail:
    """One element, and everything the list holds about it."""

    atomic_number: int
    symbol: str = ""
    name: str = ""
    status: str = ""
    flow_object_id: str = ""
    pubchem_page_url: str = ""
    #: The `element` block the PubChem enrichment wrote, verbatim.
    element: dict[str, Any] = field(default_factory=dict)
    #: The `isotopes` block, whose one field no child carries is the count of
    #: short-lived nuclides deliberately left out of the list.
    isotopes: dict[str, Any] = field(default_factory=dict)
    nuclides: list[RelatedObject] = field(default_factory=list)
    ions: list[RelatedObject] = field(default_factory=list)
    linked_flows: int = 0

    @property
    def status_label(self) -> str:
        return ElementCell(self.atomic_number, status=self.status).status_label

    @property
    def most_abundant_neutron_number(self) -> int | None:
        value = self.element.get("most_abundant_neutron_number")
        return int(value) if isinstance(value, int | float) else None

    @property
    def short_lived_not_in_list(self) -> int:
        """Nuclides PubChem knows about that this list does not carry.

        Stated rather than left as the difference between two numbers a reader
        would have to find.  It is the honest caption for the nuclide table:
        `Americium` shows one nuclide and PubChem lists 37, and without this
        the table reads as a claim that americium has one isotope.
        """
        value = self.isotopes.get("short_lived_not_in_consensus_count")
        return int(value) if isinstance(value, int | float) else 0


#: Whether a flow object is a child of an element, and of which one.  Read from
#: the child, because the ions are only recorded there; see the module
#: docstring.
_PARENT_ELEMENT = (
    "json_extract(fo.properties_json, '$.relationships.parent_element_flow_object_id')"
)
_RELATIONSHIP = (
    "json_extract(fo.properties_json, '$.relationships.relationship_type')"
)
_LINKED_FLOWS = (
    "(SELECT count(*) FROM elementary_flows ef "
    "WHERE ef.flow_object_id = fo.flow_object_id "
    "AND coalesce(ef.is_deprecated, 0) = 0)"
)


def _child_counts(connection: sqlite3.Connection) -> dict[tuple[str, str], int]:
    """``(parent flow object, relationship) -> children``, in one scan."""
    return {
        (str(row["parent"]), str(row["relationship"])): int(row["n"])
        for row in connection.execute(
            f"SELECT {_PARENT_ELEMENT} AS parent, {_RELATIONSHIP} AS relationship, "
            "count(*) AS n FROM flow_objects fo WHERE parent IS NOT NULL "
            "GROUP BY parent, relationship"
        )
    }


def periodic_table(connection: sqlite3.Connection) -> PeriodicTable | None:
    """Every element the build has a row for, ready to lay out.

    `None` when the database has no `element_coverage`, which is the state a
    database written before the review tables existed is in.  A page is a
    better answer than an empty table: nothing here is derivable from the flow
    objects alone, because an element with no flow object has nothing to derive
    it from -- which is exactly the case the table is drawn to show.
    """
    if not table_exists(connection, "element_coverage"):
        return None
    counts = _child_counts(connection)
    table = PeriodicTable()
    for row in connection.execute(
        "SELECT atomic_number, symbol, name, status, flow_object_id, "
        "pubchem_page_url FROM element_coverage ORDER BY atomic_number"
    ):
        flow_object_id = row["flow_object_id"] or ""
        cell = ElementCell(
            atomic_number=int(row["atomic_number"]),
            symbol=row["symbol"] or "",
            name=row["name"] or "",
            status=row["status"] or "",
            flow_object_id=flow_object_id,
            pubchem_page_url=row["pubchem_page_url"] or "",
            nuclide_count=counts.get((flow_object_id, ISOTOPE_OF), 0),
            ion_count=counts.get((flow_object_id, ION_OF), 0),
        )
        table.cells[cell.atomic_number] = cell
        if cell.status == ElementStatus.LINKED:
            table.linked += 1
        elif cell.status == ElementStatus.NOT_LINKED:
            table.unreferenced += 1
        else:
            table.missing += 1
    return table


def _related(connection: sqlite3.Connection, flow_object_id: str) -> list[RelatedObject]:
    """Every flow object naming *flow_object_id* as its parent element."""
    rows = connection.execute(
        "SELECT fo.flow_object_id, fo.pref_label_value, fo.flow_type, "
        f"{_RELATIONSHIP} AS relationship, "
        "json_extract(fo.properties_json, '$.isotope') AS isotope, "
        f"{_LINKED_FLOWS} AS linked_flows FROM flow_objects fo "
        f"WHERE {_PARENT_ELEMENT} = ?",
        (flow_object_id,),
    ).fetchall()
    return [
        RelatedObject(
            flow_object_id=row["flow_object_id"],
            name=row["pref_label_value"] or "",
            flow_type=row["flow_type"] or "",
            relationship=str(row["relationship"] or ""),
            isotope=load_json(row["isotope"], {}) or {},
            linked_flows=int(row["linked_flows"] or 0),
        )
        for row in rows
    ]


def element_detail(
    connection: sqlite3.Connection, atomic_number: int
) -> ElementDetail | None:
    """One element, its nuclides and its ions, or `None` if it has no row.

    The nuclides are ordered by mass number and the ions by name.  Ordering the
    nuclides by name would read `Uranium-234, Uranium-235, Uranium-238` today
    and break the moment a nuclide's label is not its element plus its mass
    number, which is what `Radon-222` versus `Radium-226` already looks like on
    one element's page.
    """
    if not table_exists(connection, "element_coverage"):
        return None
    row = connection.execute(
        "SELECT atomic_number, symbol, name, status, flow_object_id, "
        "pubchem_page_url FROM element_coverage WHERE atomic_number = ?",
        (atomic_number,),
    ).fetchone()
    if row is None:
        return None

    flow_object_id = row["flow_object_id"] or ""
    detail = ElementDetail(
        atomic_number=int(row["atomic_number"]),
        symbol=row["symbol"] or "",
        name=row["name"] or "",
        status=row["status"] or "",
        flow_object_id=flow_object_id,
        pubchem_page_url=row["pubchem_page_url"] or "",
    )
    if not flow_object_id:
        return detail

    own = connection.execute(
        "SELECT properties_json, "
        f"{_LINKED_FLOWS} AS linked_flows FROM flow_objects fo "
        "WHERE fo.flow_object_id = ?",
        (flow_object_id,),
    ).fetchone()
    if own is not None:
        properties = load_json(own["properties_json"], {}) or {}
        element = properties.get("element")
        isotopes = properties.get("isotopes")
        detail.element = element if isinstance(element, dict) else {}
        detail.isotopes = isotopes if isinstance(isotopes, dict) else {}
        detail.linked_flows = int(own["linked_flows"] or 0)

    related = _related(connection, flow_object_id)
    detail.nuclides = sorted(
        (item for item in related if item.relationship == ISOTOPE_OF),
        key=lambda item: (item.mass_number or 0, item.name.lower()),
    )
    detail.ions = sorted(
        (item for item in related if item.relationship == ION_OF),
        key=lambda item: item.name.lower(),
    )
    return detail


def element_by_symbol(connection: sqlite3.Connection, symbol: str) -> int | None:
    """The atomic number of *symbol*, matched without regard to case.

    The URL is the symbol because that is what a reader types and what the
    periodic table shows; the record is keyed by atomic number, which is the
    identity.  Matching case-insensitively means `/fe` reaches iron, and the
    canonical address stays `/Fe`.
    """
    if not table_exists(connection, "element_coverage"):
        return None
    row = connection.execute(
        "SELECT atomic_number FROM element_coverage WHERE lower(symbol) = ?",
        (symbol.strip().lower(),),
    ).fetchone()
    return None if row is None else int(row["atomic_number"])
