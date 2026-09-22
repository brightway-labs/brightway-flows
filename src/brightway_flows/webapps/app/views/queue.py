"""`/queue` and `/queue/<name>`.

One route for every queue. The ETL review app had eight routes over six JSON
files and eight templates; most queues differ only in which columns they render,
so the columns are data and the template is one. The exceptions are the queues
whose item is not a row: `elementary-flow-collision`, a group of flows in one
place (#61), and `substance-in-two-places`, a group of places holding one
substance. Each names its own template and its own reader; the route, the
paging, the search and the severity filter are still this one.
"""

from __future__ import annotations

from flask import Blueprint, abort, render_template, request

from brightway_flows.webapps.app import db
from brightway_flows.webapps.app.queries import collisions as collision_queries
from brightway_flows.webapps.app.queries import factors as factor_queries
from brightway_flows.webapps.app.queries import places as place_queries
from brightway_flows.webapps.app.queries import queue as queries

blueprint = Blueprint("queue", __name__, url_prefix="/queue")


@blueprint.route("/")
def index():
    if not db.database_exists():
        return render_template("no_database.html")
    return render_template(
        "queues.html", sections=queries.grouped(db.get_connection())
    )


@blueprint.route("/<name>")
def detail(name: str):
    """One queue.

    An unknown name is a 404 rather than an empty table: the queue names are a
    closed set, and a typo that renders "nothing to do" is worse than one that
    says the page does not exist.
    """
    definition = queries.definition(name)
    if definition is None:
        abort(404)
    if not db.database_exists():
        return render_template("no_database.html")

    connection = db.get_connection()
    query = request.args.get("q", "").strip()
    severity = request.args.get("severity", "").strip()
    page = queries.items(
        connection, name, query=query, severity=severity,
        page=request.args.get("page", 1, type=int),
    )
    if name == queries.COLLISIONS:
        # The same page of items, with each item's flows read and compared.
        page = collision_queries.groups(connection, page)
    elif name == queries.PLACES:
        # The same page of items, with each item's places read: one row per
        # place, so the unit and the source list are on the context they belong
        # to rather than in a second and third list beside it.
        page = place_queries.splits(page)
    elif name in queries.FACTOR_QUEUES:
        # The same page of items, with the evidence a factor ruling needs:
        # where each flow came from, what the pipeline did to it, and every
        # number anybody states about it.  The queue name goes with it: one of
        # the three asks a question whose evidence the other two do not need.
        page = factor_queries.questions(connection, page, queue=name)
    badges, badge_total = queries.severity_badges(connection, name, query=query)
    return render_template(
        definition.template,
        definition=definition,
        query=query,
        severity=severity,
        badges=badges,
        badge_total=badge_total,
        args={"q": query, "severity": severity},
        page=page,
    )
