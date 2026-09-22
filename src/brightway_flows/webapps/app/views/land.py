"""`/flow-objects/land`: the land taxonomy, explained and filtered.

A section of the flow-object pages, like the elements and the agricultural
chemicals, and for the same reason: a land class is a flow object.  What is
different is that it is a flow object with **seventeen** axes rather than one,
which is why this page filters rather than lists -- `Forest` alone is nine
published classes, and the question a reader has is almost always about a
combination of two or three of them.
"""

from __future__ import annotations

from flask import Blueprint, render_template, request

from brightway_flows.webapps.app import db
from brightway_flows.webapps.app.queries import land as queries

blueprint = Blueprint("land", __name__, url_prefix="/flow-objects/land")


@blueprint.route("/")
def index():
    if not db.database_exists():
        return render_template("no_database.html")
    connection = db.get_connection()
    # One filter per axis, read by the same names the value type declares, so
    # adding an axis to `domain/land_use.py` is a filter here and not a second
    # list to remember.
    filters = {
        axis: request.args.get(axis, "").strip() for axis, _label, _enum in queries.FILTER_AXES
    }
    overview = queries.land_overview(connection, filters=filters)
    if overview is None:
        return render_template(
            "flow_objects_unavailable.html",
            view="Land",
            active="land",
            table="flow_objects",
        )
    return render_template(
        "land.html",
        overview=overview,
        axes=queries.FILTER_AXES,
        filters=filters,
        active_filters=[
            (axis, label, value)
            for axis, label, _enum in queries.FILTER_AXES
            if (value := filters.get(axis))
        ],
    )
