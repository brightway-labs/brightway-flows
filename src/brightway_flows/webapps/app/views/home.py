"""`/`: the homepage.  `plans/public-site.md` §3, from the Home boards.

`/` was the documentation until this step.  A reader arriving at a published
list is first asking what it is, where to get it and how to cite it; the
documentation answers the questions after that, and still does at `/docs/`,
where every link in an issue or a commit already points.

The page renders with no database and no `docs/` (§4): the counts and the
example are left out without a build, and the "Start here" links without the
documentation, rather than shown as zeros or as links to nothing.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from flask import Blueprint, current_app, render_template

from brightway_flows.webapps.app import db, start
from brightway_flows.webapps.app.queries import home as queries

blueprint = Blueprint("home", __name__)

#: The flow object the first example card shows: carbon dioxide, fossil, in
#: the build of 2026-09-16.  A build without it has no card, so an id that
#: changes loses the card rather than breaking the page.
EXAMPLE_FLOW_OBJECT_ID = "fo-130030e87e592b4c"

#: One card each, in this order.  Carbon dioxide first because it is the flow
#: every reader already knows; the other two are there to show that the lists
#: disagree about more than capitalisation, and both were measured on the
#: six-list build of 2026-09-04:
#:
#: - **Hexafluoroethane** (`fo-2eef9f5f`), 35 rows.  Five of the six lists call
#:   C2F6 a *hydro*fluorocarbon -- `HFC-116`, `Ethane, hexafluoro-, HFC-116` --
#:   and the molecule has no hydrogen in it.  Only ecoinvent 3.12 names the
#:   substance.  EF 3.1 also contradicts itself, shipping `PFC-116` beside
#:   `HFC-116` in four air compartments.
#: - **Paraquat** (`fo-d5e5a110`), 33 rows.  The disagreement running the other
#:   way: EF 3.1 alone is precise (`1,1'-dimethyl-4,4'-bipyridinium`, the ion)
#:   and the other five say `Paraquat` -- while EF's own flow *named* paraquat
#:   is the dichloride salt, 38% heavier for the same herbicide.
#:
#: Nothing else here knows how many there are, so a fourth is a fourth id.
EXAMPLE_FLOW_OBJECT_IDS: tuple[str, ...] = (
    EXAMPLE_FLOW_OBJECT_ID,
    "fo-2eef9f5fb57f623c",
    "fo-d5e5a11080bed5ec",
)


@dataclass(frozen=True)
class Harmonisation:
    """The documentation section that says what was done to one example's flow.

    `slug` is a page under `docs/` with the `#fragment` of the section, written
    the way the "Start here" links are (`start.Question`), so it is the same
    URL a reader would have been given in an issue.
    """

    slug: str
    label: str


#: One section per card, keyed by flow object id.
#:
#: A card sets three source lists' spellings of one substance side by side and
#: stops there, which leaves the reader with the question the project exists to
#: answer: what was done to make those one flow.  Each of the three was decided
#: differently, and the section is the one that records that decision rather
#: than the one that explains the machinery in general.
#:
#: - **Carbon dioxide, fossil**: the lists agree on the substance, and fossil
#:   and biogenic carbon dioxide share 124-38-9.  The origin qualifier is what
#:   keeps them two flow objects instead of one.
#: - **Hexafluoroethane**: EF 3.1 ships `HFC-116` beside `PFC-116` in four air
#:   compartments, both carrying 76-16-4.  The curator ruling that retires one
#:   onto the other is in the table that section carries.
#: - **Paraquat**: EF 3.1's flow named `paraquat` is the dichloride, and the
#:   decision was to correct the name, keep the number, and not keep the old
#:   name as a synonym.
#:
#: A card whose id is not here keeps its "View the flow object" link and loses
#: nothing else, so a fourth example is a fourth id first and a section when
#: one is written.
EXAMPLE_HARMONISATION: dict[str, Harmonisation] = {
    EXAMPLE_FLOW_OBJECT_ID: Harmonisation(
        "concepts/two-layers#when-two-similar-substances-stay-apart",
        "Why fossil and biogenic stay apart",
    ),
    "fo-2eef9f5fb57f623c": Harmonisation(
        "changes/ef-3.1#rows-merged-into-one-flow",
        "How EF's two rows were merged",
    ),
    "fo-d5e5a11080bed5ec": Harmonisation(
        "findings/relatives"
        "#paraquat-is-not-paraquat-dichloride-and-a-tonne-of-gypsum-is-not-a-tonne-of-anhydrite",
        "Why EF's paraquat was renamed",
    ),
}


#: The lists whose spellings a card sets side by side, as
#: `(list_name, list_version)`.
#:
#: Three rather than the Home board's two.  With two, a card can only show that
#: one list writes what another list writes differently; BAFU is a third
#: lineage -- the SimaPro-era ecoinvent-2 spellings, which AGRIBALYSE and
#: Stepwise also carry -- so a disagreement that is really two conventions
#: against one is visible as that rather than as a tie.  Every id above has a
#: row in all three; `load_example` drops a card where any of them does not.
EXAMPLE_SOURCE_LISTS: tuple[tuple[str, str], ...] = (
    ("ecoinvent", "3.12"),
    ("EF", "3.1"),
    ("bafu", "2026-v1"),
)


@blueprint.route("/")
def index():
    counts, examples = _from_build()
    return render_template(
        "home.html",
        counts=counts,
        examples=examples,
        harmonisation=EXAMPLE_HARMONISATION if _has_docs() else {},
        questions=start.links() if _has_docs() else (),
    )


def _has_docs() -> bool:
    return Path(current_app.config["CONSENSUS_DOCS_PATH"]).is_dir()


def _from_build() -> tuple[queries.HomeCounts | None, tuple[queries.Example, ...]]:
    """The counts and the example cards, or nothing where nothing can say.

    A database this code cannot read is the same as none, as on Download: the
    homepage is the first page a reader sees, and a 500 over a number on it
    would hide everything that does not depend on the build.

    An id this build has no card for is dropped rather than shown empty, so a
    band of three becomes a band of two rather than a hole.
    """
    if not db.database_exists():
        return None, ()
    try:
        connection = db.get_connection()
        counts = queries.load_counts(connection)
        examples = tuple(
            found
            for flow_object_id in EXAMPLE_FLOW_OBJECT_IDS
            if (found := queries.load_example(
                connection, flow_object_id, EXAMPLE_SOURCE_LISTS
            )) is not None
        )
        return counts, examples
    except sqlite3.DatabaseError:
        current_app.logger.warning("Homepage counts unavailable", exc_info=True)
        return None, ()
