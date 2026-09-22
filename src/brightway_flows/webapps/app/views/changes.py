"""`/changes`, and the two on-demand history routes.

The history routes render twice over: as a full page, and -- with `?fragment=1`
-- as the section alone. The detail page ships a `<details>` wrapping a plain
link to the full page, and script upgrades it to fetch the fragment on first
open. With JavaScript off the link still works.

That is the whole point of the split: a detail page reads no history unless
someone asks for it, and `tests/test_webapp_sections.py` asserts the query is
never issued while one renders.
"""

from __future__ import annotations

from flask import Blueprint, render_template, request

from brightway_flows.webapps.app import db
from brightway_flows.webapps.app.queries import changes as queries
from brightway_flows.webapps.app.queries import flows as flow_queries
from brightway_flows.webapps.app.queries import substances as substance_queries

blueprint = Blueprint("changes", __name__)


def _is_fragment() -> bool:
    return request.args.get("fragment") == "1"


@blueprint.route("/changes")
def index():
    """Every change, from every transformer.

    This was the inputs app's `/changelog`, which read `transform-log.json` into
    a module global at import and filtered the whole list in Python -- a file
    written only when someone passed `--write-transform-log`, so the page was
    usually empty.
    """
    if not db.database_exists():
        return render_template("no_database.html")
    connection = db.get_connection()
    if not queries.available(connection):
        return render_template(
            "check_unavailable.html", check="Changes", table="changelog"
        )
    query = request.args.get("q", "").strip()
    transformer = request.args.get("transformer", "").strip()
    field_name = request.args.get("field", "").strip()
    sort = request.args.get("sort", "")
    return render_template(
        "changes.html",
        query=query,
        transformer=transformer,
        field_name=field_name,
        sort=sort,
        args={"q": query, "transformer": transformer, "field": field_name,
              "sort": sort},
        transformers=queries.transformers(connection),
        fields=queries.fields(connection),
        page=queries.change_page(
            connection, query=query, transformer=transformer,
            field_name=field_name, sort=sort,
            page=request.args.get("page", 1, type=int),
        ),
    )


@blueprint.route("/flows/<uuid>/changes")
def flow(uuid: str):
    if not db.database_exists():
        return render_template("no_database.html")
    connection = db.get_connection()
    history = queries.flow_history(
        connection, uuid, page=request.args.get("page", 1, type=int)
    )
    template = "partials/history.html" if _is_fragment() else "flow_changes.html"
    return render_template(
        template,
        history=history,
        uuid=uuid,
        subject=flow_queries.flow_detail(connection, uuid),
    )


@blueprint.route("/flow-objects/<path:flow_object_id>/changes")
def substance(flow_object_id: str):
    if not db.database_exists():
        return render_template("no_database.html")
    connection = db.get_connection()
    history = queries.substance_history(
        connection, flow_object_id, page=request.args.get("page", 1, type=int)
    )
    template = (
        "partials/history.html" if _is_fragment() else "substance_changes.html"
    )
    return render_template(
        template,
        history=history,
        flow_object_id=flow_object_id,
        subject=substance_queries.substance_detail(connection, flow_object_id),
    )
