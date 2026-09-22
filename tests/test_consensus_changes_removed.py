"""`consensus_changes` is gone, and a rebuild removes it from an old file (#253).

The table held the `consensus_match` slice of the change log, kept for one
release while the consolidated webapp was built on `changelog`.  Every one of
its 200,484 rows on the 2026-08-07 build duplicated
`changelog WHERE transformer = 'consensus_match'` exactly -- same `uuid`,
`field`, `old_value_json`, `new_value_json` and `comment` -- differing only in
renumbering `change_index` from 1.  It was 0.83 GiB of an 8.13 GiB file, and
nothing read it.

Two things are pinned here, because dropping a table is only half of it:

- The writer does not create it.  Without this, a later change that reinstates
  the insert costs 0.83 GiB again and no test notices.
- The writer *drops* it.  A build deletes the database first, so this never
  fires there; anything that rebuilds in place -- the merge, a fixture, a
  developer re-running the writer -- would otherwise keep the orphaned rows
  forever, since nothing else would ever mention the table again.

What replaces it is not restated here: `changelog` carries `transformer`, and
`tests/test_review_tables.py` covers what it holds.
"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from brightway_flows.domain.context_registry import context_from_dict
from brightway_flows.domain.elementary_flow import ElementaryFlow
from brightway_flows.domain.flow import Flow
from brightway_flows.pipeline.sqlite import _write_consensus_sqlite


#: Air of unstated height.  These fixtures said `["Air"]` back when the
#: field held anything; the context they meant is this one.
_AIR = context_from_dict(
    {"dimension": "Environmental", "media": "Air", "strata": "Unknown"}
)

def _tables(db: Path) -> set[str]:
    conn = sqlite3.connect(db)
    try:
        return {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    finally:
        conn.close()


class ConsensusChangesRemovedTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "consensus-flows.sqlite3"
        patch = mock.patch(
            "brightway_flows.pipeline.sqlite.CONSENSUS_DB_FILEPATH", self.db
        )
        patch.start()
        self.addCleanup(patch.stop)

    def write(self) -> None:
        flow = Flow(uuid="flow-1", source="EF 3.1", unit="kg", context=_AIR)
        elementary = ElementaryFlow(
            elementary_flow_id="flow-1",
            flow_object_id="fo-1",
            source="EF 3.1",
            context=_AIR,
            context_iri="",
            unit="kg",
            unit_iri="",
            lcia_methods=[],
            general_comment=None,
            source_refs=[],
        )
        _write_consensus_sqlite([flow], [], [], [elementary])

    def test_writer_does_not_create_the_table(self):
        self.write()
        self.assertNotIn("consensus_changes", _tables(self.db))

    def test_writer_does_not_create_its_index(self):
        self.write()
        conn = sqlite3.connect(self.db)
        try:
            indexes = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'index'"
                )
            }
        finally:
            conn.close()
        self.assertNotIn("idx_consensus_changes_uuid", indexes)

    def test_rebuild_drops_a_table_left_by_an_earlier_version(self):
        """The 0.83 GiB an in-place rebuild would otherwise strand."""
        conn = sqlite3.connect(self.db)
        try:
            conn.execute(
                "CREATE TABLE consensus_changes ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, uuid TEXT NOT NULL, "
                "field TEXT, old_value_json TEXT, new_value_json TEXT, "
                "comment TEXT, change_index INTEGER)"
            )
            conn.execute(
                "INSERT INTO consensus_changes (uuid, field) VALUES ('flow-1', 'prefLabel')"
            )
            conn.commit()
        finally:
            conn.close()
        self.assertIn("consensus_changes", _tables(self.db))

        self.write()

        self.assertNotIn("consensus_changes", _tables(self.db))


if __name__ == "__main__":
    unittest.main()
