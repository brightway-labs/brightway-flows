"""`/flow-objects/particles`: the particle size windows, explained and filtered.

A section of the flow-object pages, like the kinds of water and the land
classes, and for the same reason: a size window is a flow object.  The scheme is
seven curated windows rather than a value computed from a flow's fields, so the
page lists all of it and says which parts this build reached, where each list's
particle rows landed, what each method states for each window and what this
list carries across them -- and whether a particle row nobody has read would
stop the next merge (`plans/particle-family.md` §5, #196).
"""

from __future__ import annotations

from flask import Blueprint, render_template, request

from brightway_flows.webapps.app import db
from brightway_flows.webapps.app.queries import particles as queries

blueprint = Blueprint("particles", __name__, url_prefix="/flow-objects/particles")

#: The filters on the flows table, by the name each is read under.
FILTERS = ("window", "source")


@blueprint.route("/")
def index():
    if not db.database_exists():
        return render_template("no_database.html")
    connection = db.get_connection()
    filters = {name: request.args.get(name, "").strip() for name in FILTERS}
    overview = queries.particles_overview(connection, filters=filters)
    if overview is None:
        return render_template(
            "flow_objects_unavailable.html",
            view="Particles",
            active="particles",
            table="flow_objects",
        )
    return render_template(
        "particles.html",
        overview=overview,
        filters=filters,
        active_filters=[
            (name, name.capitalize(), _label(overview, name, value))
            for name in FILTERS
            if (value := filters.get(name))
        ],
    )


def _label(overview: queries.ParticlesOverview, name: str, value: str) -> str:
    """A filter's value as the reader picked it, rather than as it is stored."""
    if name == "window":
        for row in overview.rows:
            if row.concept_id == value:
                return row.label
    return value
