"""`/cases`: the claims in `expectations/`, by the file that states them.

Two pages, and neither needs a database: the claims and their recorded statuses
are files in the checkout, so this section renders on a machine that has never
run a build, as the documentation does.
"""

from __future__ import annotations

from pathlib import Path

from flask import Blueprint, abort, current_app, render_template, request

from brightway_flows.webapps.app.queries import cases
from brightway_flows.webapps.app.queries.common import Page, clamp_page

blueprint = Blueprint("cases", __name__, url_prefix="/cases")


def _load() -> cases.Cases:
    return cases.load_cases(Path(current_app.config["CONSENSUS_EXPECTATIONS_PATH"]))


@blueprint.route("/")
def index():
    loaded = _load()
    query = request.args.get("q", "").strip()
    state = request.args.get("state", "").strip()
    source = request.args.get("source", "").strip()
    sort = request.args.get("sort", cases.DEFAULT_SORT).strip()
    # The chips count what the search and the list select, so a reader can see
    # how many of *these* cases are unmet before choosing to look at them.
    searched = cases.select(loaded.cases, query=query, source=source, sort=sort)
    counts = cases.Cases(tuple(searched), loaded.recorded).state_counts
    selected = [case for case in searched if not state or case.state == state]
    number = clamp_page(request.args.get("page", 1, type=int), len(selected))
    page = Page(total=len(selected), number=number)
    page.rows = selected[(number - 1) * page.size:number * page.size]
    return render_template(
        "cases.html",
        page=page,
        query=query,
        state=state,
        source=source,
        sort=sort,
        args={"q": query, "state": state, "source": source, "sort": sort},
        states=[(s.value, s.value, counts[s]) for s in cases.State if counts[s]],
        state_total=len(searched),
        meanings=cases.STATE_MEANINGS,
        sources=loaded.lists,
        recorded=loaded.recorded,
    )


@blueprint.route("/<case_id>")
def detail(case_id: str):
    loaded = _load()
    case = loaded.get(case_id)
    if case is None:
        abort(404)
    return render_template(
        "case_detail.html",
        case=case,
        recorded=loaded.recorded,
        meanings=cases.STATE_MEANINGS,
    )
