"""`/expectations`: what is in `expectations/`, by the file that states it.

Two pages, and neither needs a database: the expectations and their recorded
statuses are files in the checkout, so this section renders on a machine that
has never run a build, as the documentation does.
"""

from __future__ import annotations

from pathlib import Path

from flask import Blueprint, abort, current_app, render_template, request

from brightway_flows.webapps.app.queries import expectations
from brightway_flows.webapps.app.queries.common import Page, clamp_page

blueprint = Blueprint("expectations", __name__, url_prefix="/expectations")


def _root() -> Path:
    return Path(current_app.config["CONSENSUS_EXPECTATIONS_PATH"])


def _missing(root: Path):
    """The page for a directory that is not there.

    As for the documentation: the package installs without `expectations/`, and
    an empty table under "no file matches these filters" would say something
    that is not true of the checkout the package was built from.
    """
    return render_template("no_expectations.html", expectations_path=str(root))


@blueprint.route("/")
def index():
    root = _root()
    if not root.is_dir():
        return _missing(root)
    loaded = expectations.load_files(root)
    query = request.args.get("q", "").strip()
    state = request.args.get("state", "").strip()
    source = request.args.get("source", "").strip()
    sort = request.args.get("sort", expectations.DEFAULT_SORT).strip()
    # The chips count what the search and the list select, so a reader can see
    # how many of *these* files are unmet before choosing to look at them.
    searched = expectations.select(loaded.files, query=query, source=source, sort=sort)
    counts = expectations.ExpectationFiles(tuple(searched), loaded.recorded).state_counts
    selected = [file for file in searched if not state or file.state == state]
    number = clamp_page(request.args.get("page", 1, type=int), len(selected))
    page = Page(total=len(selected), number=number)
    page.rows = selected[(number - 1) * page.size:number * page.size]
    return render_template(
        "expectations.html",
        page=page,
        query=query,
        state=state,
        source=source,
        sort=sort,
        args={"q": query, "state": state, "source": source, "sort": sort},
        states=[(s.value, s.value, counts[s]) for s in expectations.State if counts[s]],
        state_total=len(searched),
        meanings=expectations.STATE_MEANINGS,
        sources=loaded.lists,
        recorded=loaded.recorded,
    )


@blueprint.route("/<file_id>")
def detail(file_id: str):
    root = _root()
    if not root.is_dir():
        return _missing(root)
    loaded = expectations.load_files(root)
    file = loaded.get(file_id)
    if file is None:
        abort(404)
    return render_template(
        "expectation_file.html",
        file=file,
        recorded=loaded.recorded,
        meanings=expectations.STATE_MEANINGS,
    )
