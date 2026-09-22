"""`/download/`: the release, its files, and how to cite it.

`plans/public-site.md` §3.  The facts about the release -- the version, the
date, the DOI, the checksums -- are `publication.py`'s, read through
`placeholder`; this view supplies only what the build itself knows: which files
it wrote and how big they are. How the run that produced them went is
`/run/`'s to say -- this page links there once instead of repeating it.

All four artifacts, the database included and without a condition on it:
decision 8 came back that it may be published (#200), and a release that
offered three derived exports while withholding the file they were derived
from would offer the reader less than it has.

No database is not an empty state here.  The three exports are files beside
where the database would be, and a checkout with some of them and no database
still has something to offer.
"""

from __future__ import annotations

from pathlib import Path

from flask import Blueprint, current_app, render_template

from brightway_flows.webapps.app import artifacts

blueprint = Blueprint("download", __name__, url_prefix="/download")


@blueprint.route("/")
def index():
    database_path = Path(current_app.config["CONSENSUS_DB_PATH"])
    data_dir = Path(current_app.config["CONSENSUS_DATA_DIR"])
    return render_template(
        "download.html",
        files=[artifacts.artifact(key, database_path, data_dir) for key in artifacts.RELEASE_KEYS],
    )
