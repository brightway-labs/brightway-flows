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

from brightway_flows.filesystem import CONSENSUS_DB_FILEPATH, DATA_DIR
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

#: Re-exported: `SECTIONS` and `navigation` are read from here by the tests and
#: by anything that asks the package what pages it has.
__all__ = ["SECTIONS", "create_app", "navigation"]


def create_app(
    database_path: Path | None = None,
    docs_path: Path | None = None,
    data_dir: Path | None = None,
) -> Flask:
    """Build the application.

    *database_path* defaults to the platform data directory, *docs_path* to the
    `docs/` tree of the checkout this package is running from, and *data_dir* to
    the directory the database is in.  All three are parameters so a test can
    point an app at a fixture without setting an environment variable.  Nothing
    is read here: a missing database is a page, not a start-up failure, because
    the app is how you find out that the pipeline has not been run, and the same
    is true of a missing `docs/`.
    """
    app = Flask(
        __name__,
        template_folder=str(_HERE / "templates"),
        static_folder=str(_HERE / "static"),
        static_url_path="/static",
    )
    app.config["CONSENSUS_DB_PATH"] = Path(database_path or CONSENSUS_DB_FILEPATH)
    # Where the run's JSON exports are, for the downloads on the run page.  It
    # defaults to the database's own directory rather than to `DATA_DIR`, so an
    # application pointed at one build offers that build's files: `filesystem`
    # resolves `DATA_DIR` once, from the environment the process started in.
    app.config["CONSENSUS_DATA_DIR"] = Path(
        data_dir or app.config["CONSENSUS_DB_PATH"].parent or DATA_DIR
    )
    app.config["CONSENSUS_DOCS_PATH"] = Path(
        docs_path
        or os.environ.get("BRIGHTWAY_FLOWS_DOCS_DIR")
        or documentation.default_root(_HERE)
    )

    app.teardown_appcontext(db.close_connection)
    filters.register(app)
    for section in (overview, flows, substances, agrochemicals, land, water,
                    particles, elements, factors, scores, checks, queue, merge, changes,
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
            "publication": PUBLICATION,
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
