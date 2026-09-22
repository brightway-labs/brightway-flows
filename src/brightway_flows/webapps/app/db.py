"""One read-only connection per request, and nothing loaded at import time.

The applications this replaces open the database differently in each route, and
two of them read large JSON files into module globals while the module is being
imported -- 189 MB and a 267 MB cache in the inputs app, rebuilt on every worker
start, and a 1.26 GB file parsed per request in the ETL app.  A worker that
cannot start until it has read a gigabyte is a worker that cannot be restarted
under load, and a global loaded at import is a global that goes stale the moment
the pipeline runs again.

So: nothing at import, one connection per request, closed when the request ends,
and opened read-only twice over -- `mode=ro` in the URI so SQLite refuses to
create the file, and `PRAGMA query_only` so a stray `INSERT` in a query module
raises instead of writing to the artifact the pipeline owns.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from flask import current_app, g

#: Key on `flask.g` holding the request's connection.
_CONNECTION_KEY = "consensus_db"


class DatabaseMissingError(FileNotFoundError):
    """The database is not where the app was told to look.

    Raised rather than returned so that a query module cannot half-work; the
    view layer turns it into the one empty state in `layout.html`, which names
    the path and the command that produces it.
    """


def database_path() -> Path:
    """Where this app instance reads from.

    On the app config rather than imported from `filesystem`, so a test can
    point an app at a fixture database without touching the environment.
    """
    return Path(current_app.config["CONSENSUS_DB_PATH"])


def database_exists() -> bool:
    return database_path().exists()


def connect(path: Path) -> sqlite3.Connection:
    """A read-only connection to *path*.

    Flask-free, so `queries/` can be unit-tested against a fixture database
    without an application context.
    """
    if not path.exists():
        raise DatabaseMissingError(str(path))
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection


def get_connection() -> sqlite3.Connection:
    """The current request's connection, opened on first use."""
    connection = g.get(_CONNECTION_KEY)
    if connection is None:
        connection = connect(database_path())
        setattr(g, _CONNECTION_KEY, connection)
    return connection


def close_connection(_exception: BaseException | None = None) -> None:
    """Registered on `teardown_appcontext`; safe when no connection was opened."""
    connection = g.pop(_CONNECTION_KEY, None)
    if connection is not None:
        connection.close()


def table_exists(connection: sqlite3.Connection, name: str) -> bool:
    """Whether *name* is a table or view in this database.

    Every count on the overview goes through this.  A database written before a
    table existed is the normal state of a data directory that has not been
    rebuilt since an upgrade, and the honest answer there is "not known", not a
    stack trace and not a zero -- zero would read as "nothing to review".
    """
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?",
        (name,),
    ).fetchone()
    return row is not None


def column_exists(connection: sqlite3.Connection, table: str, column: str) -> bool:
    """Whether *table* has *column* yet, for the same reason `table_exists` asks.

    The merge tables are `CREATE TABLE IF NOT EXISTS` and hold every run they
    have ever seen, so a page can be asked about a run written before a column
    existed.  The column arrives when a merge next runs; until then the honest
    answer is that this database does not record it.
    """
    return any(
        row[1] == column
        for row in connection.execute(f"PRAGMA table_info({table})")
    )


def count(connection: sqlite3.Connection, table: str) -> int | None:
    """Rows in *table*, or None if this database has no such table."""
    if not table_exists(connection, table):
        return None
    return int(connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0])
