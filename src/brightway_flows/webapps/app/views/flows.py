"""`/flows` and `/flows/<uuid>`."""

from __future__ import annotations

from flask import Blueprint, abort, render_template, request

from brightway_flows.webapps.app import db
from brightway_flows.webapps.app.queries import factors as factor_queries
from brightway_flows.webapps.app.queries import flows as queries
from brightway_flows.webapps.app.queries.common import RANDOM_PAGE

blueprint = Blueprint("flows", __name__, url_prefix="/flows")


def _filters() -> queries.FlowFilters:
    """The query string as a record.

    `deprecated` defaults to `exclude` rather than to "no filter": a deprecated
    flow has been replaced, and a reader looking for a substance wants the row
    that is current.
    """
    return queries.FlowFilters(
        query=request.args.get("q", "").strip(),
        name_only=request.args.get("name_only") == "1",
        source=request.args.get("source", "").strip(),
        unit=request.args.get("unit", "").strip(),
        flow_type=request.args.get("type", "").strip(),
        origin_qualifier=request.args.get("qualifier", "").strip(),
        deprecated=request.args.get("deprecated", "exclude").strip() or "exclude",
        context={
            key: request.args.get(key, "").strip() for key in queries.CONTEXT_KEYS
        },
    )


def _args(filters: queries.FlowFilters, sort: str) -> dict[str, str]:
    """The filter state as URL parameters, for every link the page emits.

    Built here rather than in the template so that paging, sorting and removing
    a chip all carry exactly the same state -- the old flows page rebuilt this
    inline at each link, and dropped `name_only` from some of them.
    """
    args = {
        "q": filters.query,
        "name_only": "1" if filters.name_only else "",
        "source": filters.source,
        "unit": filters.unit,
        "type": filters.flow_type,
        "qualifier": filters.origin_qualifier,
        "deprecated": filters.deprecated,
        "sort": sort,
        **filters.context,
    }
    return {key: value for key, value in args.items() if value}


@blueprint.route("/")
def index():
    if not db.database_exists():
        return render_template("no_database.html")
    connection = db.get_connection()
    filters = _filters()
    sort = request.args.get("sort", "")
    # Nothing asked for at all: open somewhere in the middle rather than on the
    # first page of a list sorted by name.  79,391 flows are one alphabet deep,
    # and the ones a reader has ever seen are the ones beginning with a digit.
    # Anything in the query string -- a filter, a sort, a page -- is a question,
    # and a question gets its own answer.
    landing = not request.args
    return render_template(
        "flows.html",
        filters=filters,
        landed_at_random=landing,
        page=queries.flow_page(
            connection,
            filters,
            sort=sort,
            page=(
                RANDOM_PAGE if landing
                else request.args.get("page", 1, type=int)
            ),
        ),
        options=queries.filter_options(connection, filters),
        context_axes=queries.CONTEXT_AXES,
        sort=sort,
        args=_args(filters, sort),
    )


@blueprint.route("/<uuid>")
def detail(uuid: str):
    if not db.database_exists():
        return render_template("no_database.html")
    connection = db.get_connection()
    flow = queries.flow_detail(connection, uuid)
    if flow is None:
        abort(404)
    # Read here rather than in `flow_detail`, so that the flows query module
    # does not have to know what a factor is: the section that owns them owns
    # the query, and the page joins the two.
    #
    # The page's one table is the factors, so `sort` orders that and needs no
    # qualifier.
    sort = request.args.get("sort", "")
    return render_template(
        "flow_detail.html",
        flow=flow,
        sort=sort,
        args={"uuid": uuid},
        factors=factor_queries.for_flow(connection, uuid, sort=sort),
    )
