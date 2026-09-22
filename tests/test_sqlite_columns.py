"""Every declared column list against the table it inserts into.

The three writers into `consensus-flows.sqlite3` each declare, per table, the
columns their `INSERT` fills -- `pipeline.sqlite`, `pipeline.review_tables` and
`merge.store`, all through `pipeline.sqlite_schema.insert_statement`.  That
declaration is a second statement of what the `CREATE TABLE` beside it says,
and the two can disagree without anything failing: a column added to the table
and not to the list is simply never written, and every row carries its default.
`has_unit_mismatch` was added to `merge_outcomes` that way and had to be added
in two places to work.

So the lists are checked against the real tables, created here by the same
functions a build calls.  A column added to a `CREATE TABLE` alone fails here,
naming the list it is missing from.
"""

import sqlite3
import unittest

from brightway_flows.lcia.scores.store import (
    _CATEGORY_COLUMNS as _SCORE_CATEGORY_COLUMNS,
    _COMPARISON_COLUMNS,
    _CONTRIBUTION_COLUMNS,
    _PRIORITY_COLUMNS,
    _RELEASE_COLUMNS,
    _RUN_COLUMNS as _SCORE_RUN_COLUMNS,
    _UNIT_PROCESS_COLUMNS,
    create_score_tables,
)
from brightway_flows.merge.store import (
    _CONFLICT_COLUMNS,
    _OUTCOME_COLUMNS,
    _RUN_COLUMNS as _MERGE_RUN_COLUMNS,
    _RUN_INPUT_COLUMNS,
    create_merge_tables,
)
from brightway_flows.pipeline.review_tables import (
    _CHANGE_COLUMNS,
    _CHANGELOG_FLOW_COLUMNS,
    _COVERAGE_COLUMNS,
    _MAPPING_COLUMNS,
    _MISMATCH_COLUMNS,
    _QUEUE_COLUMNS,
    _RUN_COLUMNS,
    _STAT_COLUMNS,
    create_review_tables,
)
from brightway_flows.pipeline.sqlite import (
    _ELEMENTARY_FLOW_COLUMNS,
    _ELEMENTARY_FLOW_FTS_COLUMNS,
    _ELEMENTARY_FLOW_SOURCE_COLUMNS,
    _FLOW_OBJECT_COLUMNS,
    _FLOW_OBJECT_FTS_COLUMNS,
    _FLOW_OBJECT_PAYLOAD_COLUMNS,
    _RELATIONS,
    _SCHEMA,
)
from brightway_flows.pipeline.sqlite_schema import insert_statement, recreate

#: table -> the columns no `INSERT` names, and why.
NOT_INSERTED = {
    # An autoincrement surrogate key: SQLite fills it.  The row's identity is
    # the unique constraint on the four reference columns, not this.
    "elementary_flow_sources": ("id",),
    # Written by the `UPDATE` in `finish_run`, because they are not known when
    # the row is inserted: a run opens its row before it does the work.
    "merge_runs": ("finished_at", "stats_json"),
    # The same shape: `lcia.scores.store.finish_run` fills both once every
    # release has been compared.
    "score_runs": ("finished_at", "stats_json"),
}

DECLARATIONS = {
    "flow_objects": _FLOW_OBJECT_COLUMNS,
    "flow_objects_fts": _FLOW_OBJECT_FTS_COLUMNS,
    "flow_object_payloads": _FLOW_OBJECT_PAYLOAD_COLUMNS,
    "elementary_flows": _ELEMENTARY_FLOW_COLUMNS,
    "elementary_flows_fts": _ELEMENTARY_FLOW_FTS_COLUMNS,
    "elementary_flow_sources": _ELEMENTARY_FLOW_SOURCE_COLUMNS,
    "pipeline_runs": _RUN_COLUMNS,
    "run_stats": _STAT_COLUMNS,
    "changelog": _CHANGE_COLUMNS,
    "changelog_flows": _CHANGELOG_FLOW_COLUMNS,
    "review_queue": _QUEUE_COLUMNS,
    "formula_mismatches": _MISMATCH_COLUMNS,
    "element_coverage": _COVERAGE_COLUMNS,
    "context_default_mappings": _MAPPING_COLUMNS,
    "merge_runs": _MERGE_RUN_COLUMNS,
    "merge_run_inputs": _RUN_INPUT_COLUMNS,
    "merge_outcomes": _OUTCOME_COLUMNS,
    "merge_conflicts": _CONFLICT_COLUMNS,
    "score_runs": _SCORE_RUN_COLUMNS,
    "score_releases": _RELEASE_COLUMNS,
    "score_unit_processes": _UNIT_PROCESS_COLUMNS,
    "score_categories": _SCORE_CATEGORY_COLUMNS,
    "score_comparisons": _COMPARISON_COLUMNS,
    "score_contributions": _CONTRIBUTION_COLUMNS,
    "score_flow_priorities": _PRIORITY_COLUMNS,
}


def _database() -> sqlite3.Connection:
    """One in-memory database with all the writers' tables in it.

    All of them, in one file, because that is what a build produces: the flow
    tables, the review tables beside them, the merge tables the merge adds,
    and the score tables `compare-scores` adds after `characterise`.
    """
    connection = sqlite3.connect(":memory:")
    recreate(connection, relations=_RELATIONS, schema=_SCHEMA)
    create_review_tables(connection)
    create_merge_tables(connection)
    create_score_tables(connection)
    return connection


class DeclaredColumnsTestCase(unittest.TestCase):
    def setUp(self):
        self.connection = _database()
        self.addCleanup(self.connection.close)

    def columns_of(self, table: str) -> list[str]:
        return [row[1] for row in self.connection.execute(f"PRAGMA table_info({table})")]

    def test_every_declared_column_list_matches_its_table(self):
        for table, declared in DECLARATIONS.items():
            with self.subTest(table=table):
                actual = self.columns_of(table)
                self.assertNotEqual(actual, [], f"{table} was not created")
                skipped = NOT_INSERTED.get(table, ())
                self.assertEqual(
                    [column for column in actual if column not in skipped],
                    list(declared),
                    f"the column list for {table} and the table itself have "
                    "parted company; a column added to one needs the other",
                )

    def test_every_declared_column_list_can_be_inserted_into(self):
        """The statement `insert_statement` builds is one SQLite accepts.

        A column list that names a column the table does not have passes the
        check above only if the table has it under another name; this fails on
        the statement itself.
        """
        for table, declared in DECLARATIONS.items():
            with self.subTest(table=table):
                statement = insert_statement(table, declared)
                self.connection.execute(f"EXPLAIN {statement}", [None] * len(declared))


class RelationsTestCase(unittest.TestCase):
    """`_RELATIONS` is the drop list, so it has to name what `_SCHEMA` creates.

    A table created and not listed survives a rebuild in place with the
    previous run's rows in it -- which is what `consensus_changes` did, for
    0.83 GiB, and why the retired names stay on the list.
    """

    def test_every_relation_the_flow_schema_creates_is_dropped_first(self):
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        recreate(connection, relations=_RELATIONS, schema=_SCHEMA)
        created = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'view') "
                "AND name NOT LIKE 'sqlite_%'"
            )
        }
        # fts5 maintains shadow tables of its own; they go with the virtual
        # table that owns them.
        shadows = {
            name for name in created
            if any(name.startswith(f"{owner}_") for owner in _RELATIONS)
        }
        self.assertEqual(sorted(created - shadows - set(_RELATIONS)), [])

    def test_recreating_twice_leaves_one_database(self):
        """The writer is run twice into one file by every test that builds a
        fixture, and once by a build into a file an older revision left."""
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        recreate(connection, relations=_RELATIONS, schema=_SCHEMA)
        recreate(connection, relations=_RELATIONS, schema=_SCHEMA)


class DroppingChangedRelationsTestCase(unittest.TestCase):
    """A relation that changed kind is still dropped.

    `provenance_activities` is a view now and was a table before, and SQLite
    will not let `DROP VIEW` remove a table or `DROP TABLE` remove a view.  A
    database written before that change has the table, and left in place it
    shadows the view: the `CREATE VIEW` fails and the app reads rows nothing
    writes.
    """

    def test_a_table_where_the_schema_now_has_a_view(self):
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        connection.execute("CREATE TABLE consensus_flows (uuid TEXT)")
        connection.execute("INSERT INTO consensus_flows VALUES ('stale')")
        recreate(connection, relations=_RELATIONS, schema=_SCHEMA)
        kind = connection.execute(
            "SELECT type FROM sqlite_master WHERE name = 'consensus_flows'"
        ).fetchone()
        self.assertEqual(kind[0], "view")


if __name__ == "__main__":
    unittest.main()
