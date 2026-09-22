"""`/merge`: what a run did with each source flow.

Four pages over one table. `merge_review` had twelve routes, three of which
showed the same 9,614 rows split on a boolean, and none of which could describe
a run that merged more than one source list.
"""

from __future__ import annotations

from flask import Blueprint, render_template, request

from brightway_flows.merge.store import Outcome
from brightway_flows.webapps.app import db
from brightway_flows.webapps.app.queries import merge as queries

blueprint = Blueprint("merge", __name__, url_prefix="/merge")


#: Candidates shown per row on the outcome list.  Enough to see what the
#: selector was choosing between; the detail page shows all of them.
_LIST_PAGE_CANDIDATES = 3


def _tribool(value: str) -> bool | None:
    """`yes` / `no` / anything else meaning "do not filter on this"."""
    return {"yes": True, "no": False}.get(value)


def _run():
    """The run being reported on, or an empty summary."""
    return queries.load_run(db.get_connection())


@blueprint.route("/")
def index():
    if not db.database_exists():
        return render_template("no_database.html")
    run = _run()
    if not run.exists:
        return render_template("merge_no_run.html")
    connection = db.get_connection()
    return render_template(
        "merge_summary.html",
        run=run,
        counts=queries.outcome_counts(connection, run.run_id),
        totals=queries.run_totals(connection, run.run_id),
        reasons=queries.reason_breakdown(connection, run.run_id),
        bases=queries.basis_breakdown(connection, run.run_id),
        conflicts=queries.conflicts(connection, run.run_id),
    )


@blueprint.route("/outcomes")
def outcomes():
    """Every source flow the run resolved, filtered.

    One page rather than six: prepared, algorithm, manual additions and the
    three unmatched views are this with different arguments.
    """
    if not db.database_exists():
        return render_template("no_database.html")
    run = _run()
    if not run.exists:
        return render_template("merge_no_run.html")

    raw_outcome = request.args.get("outcome", "")
    selected = None
    if raw_outcome:
        try:
            selected = Outcome(raw_outcome)
        except ValueError:
            # A hand-edited URL, not an error: show everything.
            selected = None

    connection = db.get_connection()
    # The other filters, shared by the page and by the counts on the chips: the
    # chip has to describe the rows the reader would get, not the rows the run
    # produced before anything else was narrowed.
    narrowing = {
        "run_id": run.run_id,
        "has_flow_object_candidates": _tribool(request.args.get("candidates", "")),
        "has_context_inconsistency": _tribool(request.args.get("inconsistent", "")),
        "source_list": request.args.get("source_list", "").strip(),
        "query": request.args.get("q", "").strip(),
    }
    page = queries.outcome_page(
        connection,
        outcome=selected,
        page=request.args.get("page", 1, type=int),
        **narrowing,
    )
    badges, badge_total = queries.outcome_badges(connection, **narrowing)
    return render_template(
        "merge_outcomes.html",
        run=run,
        page=page,
        # A list parallel to `page.rows`, not a mapping: the same source uuid
        # appears once per source list, so it is not a key.  Three candidates
        # per row is what fits in a cell; the detail page shows the rest.
        candidate_summaries=queries.candidate_summaries(
            connection, page.rows, limit=_LIST_PAGE_CANDIDATES
        ),
        outcome=raw_outcome,
        badges=badges,
        badge_total=badge_total,
        candidates=request.args.get("candidates", ""),
        inconsistent=request.args.get("inconsistent", ""),
        source_list=request.args.get("source_list", "").strip(),
        query=request.args.get("q", "").strip(),
        source_lists=queries.source_lists(connection, run.run_id),
    )


@blueprint.route("/outcomes/<path:source_uuid>")
def outcome_detail(source_uuid: str):
    """One source flow, across every list that carried it.

    A list, not one record: the same uuid can appear once per source list, and
    seeing them together is how a divergent mapping is understood.
    """
    if not db.database_exists():
        return render_template("no_database.html")
    run = _run()
    if not run.exists:
        return render_template("merge_no_run.html")
    connection = db.get_connection()
    outcomes = queries.outcome_detail(connection, run.run_id, source_uuid)
    return render_template(
        "merge_outcome_detail.html",
        run=run,
        source_uuid=source_uuid,
        outcomes=outcomes,
        # Uncapped here: this is the page a curator opens to decide between the
        # candidates, and a list cut off at three is what sent them here.
        candidate_summaries=queries.candidate_summaries(connection, outcomes),
        decode_detail=queries.decode_detail,
    )


@blueprint.route("/conflicts")
def conflicts():
    """Where two source lists disagree.

    Empty unless a run merged several, which is not the same as unchecked --
    the page says which.
    """
    if not db.database_exists():
        return render_template("no_database.html")
    run = _run()
    if not run.exists:
        return render_template("merge_no_run.html")
    connection = db.get_connection()
    return render_template(
        "merge_conflicts.html",
        run=run,
        conflicts=queries.conflicts(connection, run.run_id),
        source_lists=queries.source_lists(connection, run.run_id),
    )
