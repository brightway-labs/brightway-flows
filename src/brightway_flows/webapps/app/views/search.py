"""`/search?q=`: one box, three kinds of result.  `plans/public-site.md` §3.

Server-rendered and complete with scripts blocked, like every other page: the
box in the top bar is a plain `GET` form, the filter links are links, and "Show
the other N" on the Exact match card is a `<details>`.

The flow half reads `queries.search`; the documentation half reads
`documentation.search`.  Each is left out when there is nothing for it to read
(§4): no database is no flow results and no flow filter links -- not a 0,
because this checkout cannot answer -- and no `docs/` is no Documentation
group.
"""

from __future__ import annotations

from pathlib import Path

from flask import Blueprint, current_app, redirect, render_template, request, url_for

from brightway_flows.webapps.app import db, documentation
from brightway_flows.webapps.app.queries import search as queries
from brightway_flows.webapps.app.queries.common import PAGE_SIZE, Page, clamp_page

blueprint = Blueprint("search", __name__)

#: What `type=` may be.  Anything else is All.
TYPES = ("objects", "flows", "docs")

#: How many of each group the All view shows before its "All N →" link, and how
#: many flow objects the Exact match card lists before folding the rest.
GROUP_PREVIEW = 4
EXACT_PREVIEW = 5


def _paged(rows: list, number: int) -> Page:
    """A list already in memory, as one page of `PAGE_SIZE`."""
    number = clamp_page(number, len(rows))
    start = (number - 1) * PAGE_SIZE
    return Page(rows=rows[start:start + PAGE_SIZE], total=len(rows), number=number)


@blueprint.route("/search")
def index():
    query = queries.normalise(request.args.get("q", ""))
    kind = request.args.get("type", "")
    kind = kind if kind in TYPES else ""
    number = request.args.get("page", 1, type=int)

    if not query:
        return render_template(
            "search.html", search_query="", kind="", identifier=None,
            exact=None, objects=None, flows=None, docs=None, totals={}, found=False,
        )

    has_database = db.database_exists()
    if has_database:
        connection = db.get_connection()
        uuid = queries.current_flow(connection, query)
        if uuid is not None:
            return redirect(url_for("flows.detail", uuid=uuid))

    # One query per group, each at the page the reader is on when it is the
    # group they chose and at the first page otherwise: the All view shows
    # the first four of each, and every count is the query's own total.
    exact = objects = flows = None
    if has_database:
        exact = queries.exact_match(connection, query)
        if exact is not None:
            # The card *is* the flow-object result for a registry number: an
            # InChIKey is in neither FTS table, so the text search would say 0
            # beside a card listing seven.
            objects = _paged(exact.objects, number if kind == "objects" else 1)
        else:
            objects = queries.flow_objects(
                connection, query, page=number if kind == "objects" else 1
            )
        flows = queries.elementary_flows(
            connection, query, page=number if kind == "flows" else 1
        )

    docs_root = Path(current_app.config["CONSENSUS_DOCS_PATH"])
    docs = None
    if docs_root.is_dir():
        docs = _paged(documentation.search(docs_root, query),
                      number if kind == "docs" else 1)

    totals = {
        key: group.total
        for key, group in (("objects", objects), ("flows", flows), ("docs", docs))
        if group is not None
    }
    return render_template(
        "search.html",
        search_query=query,
        kind=kind,
        identifier=queries.identifier_kind(query),
        # The list pages' `q`, so their count is the count here.
        list_query=queries.fts_terms(query),
        exact=exact,
        objects=objects,
        flows=flows,
        docs=docs,
        totals=totals,
        found=exact is not None or any(totals.values()),
        group_preview=GROUP_PREVIEW,
        exact_preview=EXACT_PREVIEW,
    )
