"""How a writer into `consensus-flows.sqlite3` declares its tables.

Three writers fill that file -- `pipeline.sqlite._write_consensus_sqlite` for
the flow tables, `pipeline.review_tables.write_review_tables` for the review
tables, and `merge.store.write_source_outcomes` for the merge tables -- and
until #96 each said the same three things its own way: which relations it
owns, how it creates them, and which columns each `INSERT` fills.

The third is the one that could go wrong quietly.  A column list restated
inside an `INSERT` is a second copy of the `CREATE TABLE` above it, and the two
disagree in silence: add a column to the table and forget the insert, and every
row is written with that column left at its default.  `insert_statement` takes
the list the module already declares, so there is one copy to add to, and
`tests/test_sqlite_row_shape.py` fails if a declared list and the table it names
part company.

The first two differ between the writers on purpose, and the difference is
whether the rows outlive the run.  The flow and review tables are rewritten by
every build, so they are dropped and recreated -- `recreate` below, which is
also the upgrade path for a database an older revision left behind, since a
table that gained a column is dropped rather than filled in.  The merge tables
hold every previous run's outcomes, so they are `CREATE TABLE IF NOT EXISTS`
and migrate additively; see `merge.store._ADDED_OUTCOME_COLUMNS`.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence


def insert_statement(table: str, columns: Sequence[str]) -> str:
    """`INSERT INTO table (columns...) VALUES (?, ...)`, from one column list."""
    placeholders = ", ".join("?" * len(columns))
    return f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})"


def drop_relation(connection: sqlite3.Connection, name: str) -> None:
    """Remove *name* whether it is a table or a view.

    SQLite will not let either statement stand in for the other, and neither
    degrades to a no-op: `DROP VIEW IF EXISTS` on a table raises "use DROP TABLE
    to delete table", and the reverse raises its mirror image.  So the `IF
    EXISTS` form is not enough on its own, and the type has to be read first.

    This is the upgrade path for a relation that has changed kind.
    `provenance_activities` is a view now and was a table before; left in place
    the table would shadow the view -- the `CREATE VIEW` would fail, and the app
    would read stale rows from a relation nothing writes any more.
    """
    row = connection.execute(
        "SELECT type FROM sqlite_master WHERE name = ?", (name,)
    ).fetchone()
    if row is None:
        return
    connection.execute(f"DROP {'VIEW' if row[0] == 'view' else 'TABLE'} {name}")


def recreate(
    connection: sqlite3.Connection,
    *,
    relations: Sequence[str],
    schema: Sequence[str],
) -> None:
    """Drop every named relation, then run *schema*.

    Dropped rather than emptied because the schema is versioned by rewriting: a
    database left by an older revision has the old columns, and adding rows to
    it would produce a table that is half one shape and half another.  A
    relation a writer no longer creates belongs in *relations* too, so a rebuild
    in place does not leave its rows behind.

    Views go first whatever order they are named in, because one of them reads
    tables below it and SQLite will drop a table out from under a view without
    complaint, leaving a view that errors on use rather than one that is gone.
    """
    kinds = {
        row[0]: row[1]
        for row in connection.execute("SELECT name, type FROM sqlite_master")
    }
    for name in sorted(relations, key=lambda name: kinds.get(name) != "view"):
        drop_relation(connection, name)
    for statement in schema:
        connection.execute(statement)
