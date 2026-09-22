"""`/flow-objects/agricultural-chemicals`: the role axis, explained and filtered.

The same records as `/flow-objects`, narrowed to the substances that carry an
`agrochemical_use` role and headed by an account of what that role is.  A
narrowing rather than a new page of its own data, which is why the listing is
`substances.substance_page` with a `roles` filter and not a second query: a
reader who removes every filter here should get the same rows the main page
would give them, and two queries would eventually disagree about that.

The page exists because the axis is invisible without it.  A curator can find
`herbicide` on a substance's own page once they are looking at the substance;
nothing said which substances to look at, or that the answer for 766 of them
is "one of these twelve classes".
"""

from __future__ import annotations

from flask import Blueprint, render_template, request

from brightway_flows.webapps.app import db
from brightway_flows.webapps.app.queries import roles as queries
from brightway_flows.webapps.app.queries import substances as substance_queries

blueprint = Blueprint(
    "agrochemicals", __name__, url_prefix="/flow-objects/agricultural-chemicals"
)


@blueprint.route("/")
def index():
    if not db.database_exists():
        return render_template("no_database.html")
    connection = db.get_connection()
    # A database written before the flow objects were, which is what a data
    # directory looks like after an upgrade and before a rebuild.  A page, not
    # a 500 -- and not "nothing bears a role", which is a different claim.
    if not db.table_exists(connection, "flow_objects"):
        return render_template(
            "flow_objects_unavailable.html",
            view="Agricultural chemicals",
            active="agrochemicals",
            table="flow_objects",
        )
    family = queries.AGROCHEMICAL_FAMILY
    role = request.args.get("role", "").strip()
    # A chosen role narrows to that role; no choice shows the whole family.
    # Both are "bears at least one of these", so the unfiltered page is the
    # union of the twelve rather than a separate query with its own answer.
    selected = (role,) if role in queries.family_roles(family) else ()
    return render_template(
        "agrochemicals.html",
        tree=queries.role_tree(connection, family),
        role_options=queries.role_options(connection, family),
        evidence=queries.evidence_counts(connection, family),
        total=queries.substances_with_any_role(connection, family),
        other_family=queries.role_options(connection, queries.ENVIRONMENTAL_FATE_FAMILY),
        role=role if selected else "",
        query=request.args.get("q", "").strip(),
        origin_source=request.args.get("origin", "").strip(),
        origin_options=substance_queries.substance_origin_options(connection),
        sort=request.args.get("sort", ""),
        page=substance_queries.substance_page(
            connection,
            query=request.args.get("q", "").strip(),
            origin_source=request.args.get("origin", "").strip(),
            roles=selected or tuple(queries.family_roles(family)),
            sort=request.args.get("sort", ""),
            page=request.args.get("page", 1, type=int),
        ),
    )
