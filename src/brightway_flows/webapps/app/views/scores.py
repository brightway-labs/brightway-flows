"""`/scores`: a vendor's datasets scored with its factors and with ours.

Three pages, by question:

* `/scores/` -- per compared release, the table the hand analysis drew
  for one activity, drawn for the sample: a row per category, how many
  datasets agree, how many are within 2x, and the median of ours over theirs;
* `/scores/<release>/category/<key>` -- one category opened: the vendor's
  flows ranked by how much of the category's total they move, with why;
* `/scores/<release>/dataset/<code>` -- one dataset, every category both
  ways, and under one of them every flow -- the #209 hand analysis, on demand.

Every one renders `scores_unavailable.html` where `compare-scores` has not
run.  "Nobody has asked yet" is not "the scores agree".
"""

from __future__ import annotations

from flask import Blueprint, abort, render_template, request

from brightway_flows.webapps.app import db
from brightway_flows.webapps.app.queries import scores as queries

blueprint = Blueprint("scores", __name__, url_prefix="/scores")


def _unavailable() -> str | None:
    if not db.database_exists():
        return render_template("no_database.html")
    if not queries.available(db.get_connection()):
        return render_template("scores_unavailable.html")
    return None


@blueprint.route("/")
def index():
    if unavailable := _unavailable():
        return unavailable
    connection = db.get_connection()
    return render_template(
        "scores.html",
        run=queries.run(connection),
        releases=queries.releases(connection),
    )


@blueprint.route("/<release>/category/<path:category_key>")
def category(release: str, category_key: str):
    if unavailable := _unavailable():
        return unavailable
    connection = db.get_connection()
    detail = queries.category(connection, release, category_key)
    if detail is None:
        abort(404)
    reason = request.args.get("reason", "").strip()
    args = {"release": release, "category_key": category_key}
    if reason:
        args["reason"] = reason
    return render_template(
        "score_category.html",
        detail=detail,
        reason=reason,
        args=args,
        page=queries.priorities(
            connection, detail, reason=reason, page=request.args.get("page", 1, type=int)
        ),
    )


@blueprint.route("/<release>/datasets")
def datasets(release: str):
    if unavailable := _unavailable():
        return unavailable
    connection = db.get_connection()
    card = queries.release(connection, release)
    if card is None:
        abort(404)
    query = request.args.get("q", "").strip()
    args = {"release": release, **({"q": query} if query else {})}
    return render_template(
        "score_datasets.html",
        release=card,
        query=query,
        args=args,
        page=queries.datasets(connection, card, query=query, page=request.args.get("page", 1, type=int)),
    )


@blueprint.route("/<release>/dataset/<activity_code>")
def dataset(release: str, activity_code: str):
    if unavailable := _unavailable():
        return unavailable
    connection = db.get_connection()
    detail = queries.dataset(connection, release, activity_code)
    if detail is None:
        abort(404)
    chosen = request.args.get("category", "").strip()
    if chosen and chosen not in {s.category_key for s in detail.scores}:
        abort(404)
    rows = queries.contributions(connection, detail, chosen) if chosen else []
    return render_template(
        "score_dataset.html",
        detail=detail,
        chosen=chosen,
        chosen_score=next((s for s in detail.scores if s.category_key == chosen), None),
        contributions=rows,
    )
