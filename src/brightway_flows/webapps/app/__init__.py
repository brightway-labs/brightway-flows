"""One application over one SQLite file.

Phase 1 of `plans/webapp-consolidation.md`: the shell.  This package will
replace `webapps/consensus`, `webapps/inputs`, `webapps/etl_review` and
`webapps/run_report` -- four Flask apps, four ports, four navigation bars and no
cross-links between them.  All four still run; nothing is removed until the
pages they own have been ported.

What is here is the frame: the factory, the read-only connection, the layout,
the stylesheet, the navigation, the empty state, and one route.

The navigation lists only routes that exist.  That is enforced rather than
intended -- `tests/test_webapp_shell.py` walks every `href` a template emits and
resolves it against the URL map.  Two of the pages this replaces are dead
exactly because nothing did that: `/duplicate-context-by-pattern` renders a
template that was never written, and `wsgi/merge.py` imports a module that was
deleted.

The sections themselves live in `sections.py`.  `/browse/` describes them as
well as linking to them, and it is a view, which cannot import this module.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from flask import Flask, render_template

from brightway_flows.assessment.expectations import EXPECTATIONS_DIR
from brightway_flows.filesystem import CONSENSUS_DB_FILEPATH, DATA_DIR
from brightway_flows.published_release import (
    PublishedRelease,
    ReleaseDownloadError,
    fetch_release,
    load_published_release,
    release_directory,
)
from brightway_flows.webapps.app import db, documentation, filters
from brightway_flows.webapps.app.publication import PUBLICATION
from brightway_flows.webapps.app.queries import navigation as navigation_queries
from brightway_flows.webapps.app.sections import (
    REPOSITORY_URL,
    SECTIONS,
    description,
    navigation,
)
from brightway_flows.webapps.app.views import (
    about,
    agrochemicals,
    browse,
    changes,
    checks,
    contexts,
    docs,
    download,
    elements,
    expectations,
    factors,
    flows,
    home,
    land,
    merge,
    overview,
    particles,
    queue,
    scores,
    search,
    substances,
    water,
)

_HERE = Path(__file__).resolve().parent

#: Set to `1` to serve the build in the data directory rather than the
#: published release: development, and curation of a build not yet released.
LOCAL_ENV = "BRIGHTWAY_FLOWS_WEBAPP_LOCAL"

#: Re-exported: `SECTIONS` and `navigation` are read from here by the tests and
#: by anything that asks the package what pages it has.
__all__ = ["LOCAL_ENV", "SECTIONS", "create_app", "navigation"]


def _serves_locally(local: bool | None, *, named: bool) -> bool:
    """Whether this application reads a build on this machine.

    Asked for outright wins.  Otherwise an application handed a database or a
    data directory reads what it was handed, and one handed neither reads the
    published release unless the variable says to stay local.
    """
    if local is not None:
        return local
    if named:
        return True
    return os.environ.get(LOCAL_ENV, "").strip().lower() in {"1", "true", "yes"}


def create_app(
    database_path: Path | None = None,
    docs_path: Path | None = None,
    data_dir: Path | None = None,
    expectations_path: Path | None = None,
    release_path: Path | None = None,
    local: bool | None = None,
) -> Flask:
    """Build the application.

    **Which data it reads.**  By default the published release: the one the
    release file names (*release_path*, else `BRIGHTWAY_FLOWS_RELEASE_FILE`,
    else `release.json` in the data directory), whose database is downloaded
    from Zenodo into `published/<version>/` of the data directory the first
    time and read from there afterwards.  The release's other five files are
    not fetched: no page reads them, and a reader is sent to Zenodo for them.  With *local*, with
    `BRIGHTWAY_FLOWS_WEBAPP_LOCAL=1`, or when *database_path* or *data_dir* is
    given, it reads the build on this machine instead, as it always did: the
    database from the data directory and the exports from beside it.  An
    installation with no release file has no release to download, and reads
    locally too.

    *docs_path* defaults to the `docs/` tree of the checkout this package is
    running from and *expectations_path* to the checkout's `expectations/`.
    Everything is a parameter so a test can point an app at a fixture without
    setting an environment variable.

    A missing database is a page, not a start-up failure, because the app is
    how you find out that the pipeline has not been run; the same is true of a
    missing `docs/`, and of a release that could not be downloaded.  A release
    file that is malformed, or that is named and is not there, is a start-up
    failure, with *local* as without: the file is where every page's version
    and DOI come from, and a file read in part or passed over would put some
    other release's name on the data.

    :raises ReleaseFileError: for such a release file.
    """
    app = Flask(
        __name__,
        template_folder=str(_HERE / "templates"),
        static_folder=str(_HERE / "static"),
        static_url_path="/static",
    )
    serves_locally = _serves_locally(
        local, named=database_path is not None or data_dir is not None
    )
    app.config["CONSENSUS_DB_PATH"] = Path(database_path or CONSENSUS_DB_FILEPATH)
    # Where the run's JSON exports are, for the downloads on the run page.  It
    # defaults to the database's own directory rather than to `DATA_DIR`, so an
    # application pointed at one build offers that build's files: `filesystem`
    # resolves `DATA_DIR` once, from the environment the process started in.
    app.config["CONSENSUS_DATA_DIR"] = Path(
        data_dir or app.config["CONSENSUS_DB_PATH"].parent or DATA_DIR
    )

    # The release file is looked for in the directory this application was
    # pointed at, so a fixture's directory with no such file names no release
    # whatever the machine's own data directory holds.
    release: PublishedRelease | None = load_published_release(
        release_path, data_dir=app.config["CONSENSUS_DATA_DIR"]
    )
    app.config["PUBLISHED_RELEASE"] = release
    #: The release this application downloaded its data for, or `None` where
    #: it reads a local build.  `no_database.html` reads it to say which of
    #: the two commands fills the gap.
    app.config["SERVED_RELEASE"] = None
    if release is not None and not serves_locally:
        directory = release_directory(release, DATA_DIR)
        try:
            fetch_release(release, directory, report=app.logger.warning)
        except ReleaseDownloadError:
            app.logger.exception("Release %s could not be downloaded", release.version)
        app.config["SERVED_RELEASE"] = release
        app.config["CONSENSUS_DB_PATH"] = directory / CONSENSUS_DB_FILEPATH.name
        app.config["CONSENSUS_DATA_DIR"] = directory

    def current_publication():
        """Every fact about the release, for one request.

        `PUBLICATION` is read here rather than held, so that the fixed facts
        and the release's are joined in one place, and a test that replaces
        one sees the page change.
        """
        return PUBLICATION.with_release(app.config["PUBLISHED_RELEASE"])

    app.config["CURRENT_PUBLICATION"] = current_publication
    app.config["CONSENSUS_DOCS_PATH"] = Path(
        docs_path
        or os.environ.get("BRIGHTWAY_FLOWS_DOCS_DIR")
        or documentation.default_root(_HERE)
    )

    # As the documentation: a deployment that is not a checkout names where its
    # copy of `expectations/` is, and one that has none gets a page saying so.
    app.config["CONSENSUS_EXPECTATIONS_PATH"] = Path(
        expectations_path
        or os.environ.get("BRIGHTWAY_FLOWS_EXPECTATIONS_DIR")
        or EXPECTATIONS_DIR
    )

    app.teardown_appcontext(db.close_connection)
    filters.register(app)
    for section in (overview, flows, substances, agrochemicals, land, water,
                    particles, elements, factors, scores, checks, queue, expectations, merge, changes,
                    contexts, docs, browse, download, about, search, home):
        app.register_blueprint(section.blueprint)
    # The flow-object pages answer to their old `/substances` addresses too.
    # See `views.substances.legacy_blueprint` for why.
    app.register_blueprint(substances.legacy_blueprint)

    def browse_counts() -> dict[str, int | None]:
        """The Browse panel's counts, read only when a page with a top bar asks.

        A function rather than a value, so a fragment -- which has no top bar --
        does not pay for two counts it never renders.  No database, or one this
        code cannot read, is no counts: the panel is on every page, including
        the documentation, which has to render without a build.
        """
        if not db.database_exists():
            return {}
        try:
            return navigation_queries.load_counts(db.get_connection()).by_section()
        except sqlite3.DatabaseError:
            app.logger.warning("Browse panel counts unavailable", exc_info=True)
            return {}

    @app.context_processor
    def _navigation():
        # `db_path` is for `no_database.html` and nothing else.  That page is
        # read by whoever runs the build, and its whole job is to name the file
        # that is missing and the command that writes it; every other page is
        # read by somebody who has no account on this machine, and a server's
        # directory layout tells them nothing.
        return {
            "nav_sections": navigation(),
            "browse_counts": browse_counts,
            "describe_section": description,
            "publication": current_publication(),
            "served_release": app.config["SERVED_RELEASE"],
            "repository_url": REPOSITORY_URL,
            "db_path": str(app.config["CONSENSUS_DB_PATH"]),
        }

    # `plans/public-site.md` §4: there was no custom error page before this,
    # so a mistyped flow UUID or a bug rendered Flask's own text, outside the
    # site's frame and with no way back in.
    @app.errorhandler(404)
    def _not_found(_error):
        return render_template(
            "error.html",
            code=404,
            heading="Page not found",
            explanation="There is nothing at that address.",
        ), 404

    @app.errorhandler(500)
    def _server_error(_error):
        # No details: this is what a reader sees, not what a curator debugs
        # from -- the traceback goes to the log, not the response.
        return render_template(
            "error.html",
            code=500,
            heading="Something went wrong",
            explanation="The page could not be rendered.",
        ), 500

    return app
