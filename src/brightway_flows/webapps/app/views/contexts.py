"""`/contexts`: the rules mapping each source's compartments onto consensus contexts."""

from __future__ import annotations

from flask import Blueprint, render_template, request

from brightway_flows.webapps.app import db
from brightway_flows.webapps.app.queries import contexts as queries

blueprint = Blueprint("contexts", __name__)


@blueprint.route("/contexts")
def index():
    if not db.database_exists():
        return render_template("no_database.html")
    connection = db.get_connection()
    if not queries.available(connection):
        return render_template(
            "check_unavailable.html",
            check="Context mappings",
            table="context_default_mappings",
        )
    query = request.args.get("q", "").strip()
    source = request.args.get("source", "").strip()
    return render_template(
        "contexts.html",
        query=query,
        source=source,
        args={"q": query, "source": source},
        sources=queries.sources(connection),
        page=queries.mapping_page(
            connection, query=query, source=source,
            page=request.args.get("page", 1, type=int),
        ),
    )
