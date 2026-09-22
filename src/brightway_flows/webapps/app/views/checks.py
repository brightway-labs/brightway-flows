"""`/checks` and the six checks under it.

One blueprint rather than five, because the pages differ only in which query
they call and which columns they render, and an index that lists them with
their counts is most of the navigation they need.
"""

from __future__ import annotations

from flask import Blueprint, render_template, request

from brightway_flows.webapps.app import db
from brightway_flows.webapps.app.queries import checks as queries

blueprint = Blueprint("checks", __name__, url_prefix="/checks")


@blueprint.route("/")
def index():
    if not db.database_exists():
        return render_template("no_database.html")
    return render_template("checks.html", checks=queries.index(db.get_connection()))


@blueprint.route("/shared-labels")
def shared_labels():
    if not db.database_exists():
        return render_template("no_database.html")
    query = request.args.get("q", "").strip()
    return render_template(
        "check_shared_labels.html",
        query=query,
        page=queries.shared_labels(
            db.get_connection(), query=query,
            page=request.args.get("page", 1, type=int),
        ),
    )


@blueprint.route("/formula-mismatches")
def formula_mismatches():
    if not db.database_exists():
        return render_template("no_database.html")
    connection = db.get_connection()
    if not db.table_exists(connection, "formula_mismatches"):
        return render_template("check_unavailable.html", check="Formula mismatches",
                               table="formula_mismatches")
    query = request.args.get("q", "").strip()
    return render_template(
        "check_formula_mismatches.html",
        query=query,
        page=queries.formula_mismatches(
            connection, query=query, page=request.args.get("page", 1, type=int)
        ),
    )


@blueprint.route("/duplicate-contexts")
def duplicate_contexts():
    if not db.database_exists():
        return render_template("no_database.html")
    query = request.args.get("q", "").strip()
    return render_template(
        "check_duplicate_contexts.html",
        query=query,
        page=queries.duplicate_contexts(
            db.get_connection(), query=query,
            page=request.args.get("page", 1, type=int),
        ),
    )


@blueprint.route("/unit-disagreements")
def unit_disagreements():
    if not db.database_exists():
        return render_template("no_database.html")
    connection = db.get_connection()
    if not db.table_exists(connection, "merge_outcomes"):
        return render_template("check_unavailable.html", check="Unit disagreements",
                               table="merge_outcomes")
    query = request.args.get("q", "").strip()
    badge = request.args.get("badge", "").strip()
    badges, total = queries.unit_disagreement_badges(connection)
    return render_template(
        "check_unit_disagreements.html",
        query=query,
        badge=badge,
        badges=badges,
        badge_total=total,
        args={"q": query, "badge": badge},
        page=queries.unit_disagreements(
            connection, query=query, badge=badge,
            page=request.args.get("page", 1, type=int),
        ),
    )


@blueprint.route("/duplication-report")
def duplication_report():
    if not db.database_exists():
        return render_template("no_database.html")
    query = request.args.get("q", "").strip()
    return render_template(
        "check_duplication_report.html",
        query=query,
        page=queries.duplication_report(
            db.get_connection(), query=query,
            page=request.args.get("page", 1, type=int),
        ),
    )


@blueprint.route("/isotope-gaps")
def isotope_gaps():
    if not db.database_exists():
        return render_template("no_database.html")
    connection = db.get_connection()
    query = request.args.get("q", "").strip()
    source = request.args.get("source", "").strip()
    return render_template(
        "check_isotope_gaps.html",
        query=query,
        source=source,
        sources=queries.isotope_gap_sources(connection),
        page=queries.isotope_gaps(
            connection, query=query, source=source,
            page=request.args.get("page", 1, type=int),
        ),
    )
