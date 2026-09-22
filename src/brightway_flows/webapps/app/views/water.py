"""`/flow-objects/water`: the water taxonomy, explained and filtered.

A section of the flow-object pages, like the land classes and the agricultural
chemicals, and for the same reason: a kind of water is a flow object.  What is
different is that the taxonomy is a **curated tree of seventeen concepts**
rather than a value computed from a flow's fields, so the page lists all of it
and says which parts of it this build reached -- while the filters, which are
about the flows rather than the kinds, narrow the table underneath.

The page exists because the distinction it draws is invisible without it.  A
curator looking at `Cooling water` can see the ENVO class on the substance's own
page; nothing said that cooling water and turbine water are two of seventeen
kinds, that the withdrawal and the return of each are a balanced pair, or that
the reason any of it exists is that those pairs used to collapse into one flow.
"""

from __future__ import annotations

from flask import Blueprint, render_template, request

from brightway_flows.webapps.app import db
from brightway_flows.webapps.app.queries import water as queries

blueprint = Blueprint("water", __name__, url_prefix="/flow-objects/water")

#: The filters on the flows table, by the name each is read under.
FILTERS = ("kind", "direction", "body")


@blueprint.route("/")
def index():
    if not db.database_exists():
        return render_template("no_database.html")
    connection = db.get_connection()
    filters = {name: request.args.get(name, "").strip() for name in FILTERS}
    overview = queries.water_overview(connection, filters=filters)
    if overview is None:
        return render_template(
            "flow_objects_unavailable.html",
            view="Water",
            active="water",
            table="flow_objects",
        )
    return render_template(
        "water.html",
        overview=overview,
        filters=filters,
        active_filters=[
            (name, name.capitalize(), _label(overview, name, value))
            for name in FILTERS
            if (value := filters.get(name))
        ],
    )


def _label(overview: queries.WaterOverview, name: str, value: str) -> str:
    """A filter's value as the reader picked it, rather than as it is stored.

    Only the kind differs: it is filtered by concept id, and a chip reading
    `sea_water` would be the one place on the page where a snake_case id stands
    where every other value is a display string.
    """
    if name != "kind":
        return value
    return next(
        (row.label for row in overview.rows if row.concept_id == value), value
    )
