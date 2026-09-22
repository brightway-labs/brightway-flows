"""`/flow-objects/elements`: the periodic table, and one element's page.

A section of the flow-object pages rather than a section of its own.  An
element **is** a flow object -- `Iron` is `fo-...` like benzene is -- and the
periodic table is a second way into the same records, not a second kind of
record.  The masthead therefore still says "Flow objects" while a reader is
here, and the sub-navigation says which view they are in.

The URL is the symbol and not the atomic number, because the symbol is what
the table shows and what a reader types.  `element_by_symbol` resolves it to
the atomic number, which is the identity the record is keyed by.
"""

from __future__ import annotations

from flask import Blueprint, abort, redirect, render_template, url_for

from brightway_flows.webapps.app import db
from brightway_flows.webapps.app.queries import elements as queries

#: Under the flow-object prefix, as a static rule.  Werkzeug sorts a rule with
#: no arguments ahead of one with a `path` converter, so this is reached rather
#: than `/flow-objects/<path:flow_object_id>` -- and
#: `tests/test_webapp_flow_object_views.py` pins that rather than trusting it.
blueprint = Blueprint("elements", __name__, url_prefix="/flow-objects/elements")


@blueprint.route("/")
def index():
    if not db.database_exists():
        return render_template("no_database.html")
    return render_template(
        "elements.html",
        table=queries.periodic_table(db.get_connection()),
        rows=queries.PERIODIC_ROWS,
        f_block_rows=queries.F_BLOCK_ROWS,
        marker_labels=queries.MARKER_LABELS,
    )


@blueprint.route("/<symbol>")
def detail(symbol: str):
    if not db.database_exists():
        return render_template("no_database.html")
    connection = db.get_connection()
    atomic_number = queries.element_by_symbol(connection, symbol)
    if atomic_number is None:
        abort(404)
    element = queries.element_detail(connection, atomic_number)
    if element is None:
        abort(404)
    # The canonical address is the symbol as the record spells it. `/fe`
    # answers, and then says where it lives, so a link copied out of the
    # address bar is the one the table would have given.
    if symbol != element.symbol:
        return redirect(url_for("elements.detail", symbol=element.symbol), code=301)
    return render_template("element_detail.html", element=element)
