"""`/run`: what the last build did, what needs a curator, and what to download.

The four applications this replaces each open on their own data and none of
them can say what the run as a whole did -- the ETL dashboard counts its own
queues, the run report counts the merge, and neither knows about the other.
They are one build.

The page was the front door and is not any more: `/` is the documentation, which
is what somebody arriving at this site without knowing what a flow object is
needs first.  A curator wanting the build's own state comes here, and that is
one click from every page in the masthead.

The endpoint keeps the name `overview` while the URL does not, for the reason
`views.substances` keeps `substances` at `/flow-objects`: renaming it would
rewrite `url_for` in a dozen templates and change nothing anybody sees.
"""

from __future__ import annotations

from pathlib import Path

from flask import Blueprint, abort, current_app, render_template, send_file

from brightway_flows.webapps.app import artifacts, db
from brightway_flows.webapps.app.queries import overview as queries

blueprint = Blueprint("overview", __name__, url_prefix="/run")


def _found(key: str) -> artifacts.Artifact | None:
    """One artifact, looked for where this application reads."""
    return artifacts.artifact(
        key,
        Path(current_app.config["CONSENSUS_DB_PATH"]),
        Path(current_app.config["CONSENSUS_DATA_DIR"]),
    )


def _artifacts() -> list[artifacts.Artifact]:
    """What this run left behind, looked for where this application reads."""
    return artifacts.available(
        Path(current_app.config["CONSENSUS_DB_PATH"]),
        Path(current_app.config["CONSENSUS_DATA_DIR"]),
    )


@blueprint.route("/")
def index():
    """The run, or the one empty state.

    A missing database is the expected first state of a checkout, so it renders
    a page naming the path and the command that fills it, rather than a stack
    trace.  Every per-route `exists=False` branch in the old apps collapses into
    this one.
    """
    if not db.database_exists():
        return render_template("no_database.html"), 200
    return render_template(
        "overview.html",
        overview=queries.load_overview(db.get_connection()),
        artifacts=_artifacts(),
    )


@blueprint.route("/download/<key>")
def download(key: str):
    """One of the four files the build publishes.

    Sent with `conditional=True`, so a range request is answered and an
    interrupted 2.3 GB download can be resumed rather than started again.  A
    key this application does not know, or a file this build did not write, is a
    404: the page does not link to either, and a hand-typed URL should not be
    answered with an empty file.  The database is one of the four, with no
    condition on it: decision 8 came back that it may be published (#200).
    """
    found = _found(key)
    if found is None or not found.exists:
        abort(404)
    return send_file(
        found.path,
        as_attachment=True,
        download_name=found.filename,
        conditional=True,
    )
