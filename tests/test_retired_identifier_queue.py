"""A retired identifier that stops resolving is reported, not dropped.

#102 renumbered all 2,561 minted flows in one build, and the old identifiers are
published as redirects from `retired-minted-flow-ids.json`.  A redirect is
emitted only where this build mints the flow it points at, which is right for a
build merging fewer source lists -- it mints fewer of them -- and wrong for a
flow curation has taken away.

#117 is the shape of the second case.  BAFU filed one cooling-water row in the
ground compartment, the list minted `Cooling water` in `Resource / Ground` for
it, and that flow had a retired identifier.  The filing was a slip, the row now
goes where its seven siblings go, the minted flow correctly stopped being
minted -- and the identifier stopped resolving, while the substance is still
published three contexts over.  Nothing said so: the export dropped the entry
and a counter went up.

These tests are about the reporting, not about a repair.  #344 is the repair,
and it needs somebody to decide what a redirect across a context boundary
promises.
"""

from __future__ import annotations

import sqlite3
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from brightway_flows.pipeline.redirects import (
    RetiredIdentifier,
    retirement_redirects,
)
from brightway_flows.pipeline.review_records import ReviewQueue, Severity


def _retirement(identifier: str, replaced_by: str, name: str = "Peat") -> RetiredIdentifier:
    return RetiredIdentifier(
        identifier=identifier,
        replaced_by=replaced_by,
        flow_object_id="fo-" + identifier[:8],
        context_iri="https://vocab.brightway.one/flow-contexts/reso-grou",
        name=name,
    )


class NothingIsCountedAndDroppedTestCase(unittest.TestCase):
    """Every retirement is published, or handed back to the caller.

    The count and the records come from one pass, so they cannot disagree --
    which is the property, and the reason `unresolved` is a list the caller
    passes in rather than a second walk over the file.
    """

    def test_a_resolvable_retirement_is_published_and_not_reported(self):
        rows = (_retirement("aaaa1111", "bbbb2222"),)
        unresolved: list[RetiredIdentifier] = []
        out, counts = retirement_redirects({"bbbb2222"}, rows, unresolved=unresolved)
        self.assertEqual(len(out), 1)
        self.assertEqual(counts["redirects_published"], 1)
        self.assertEqual(unresolved, [])

    def test_an_unresolvable_retirement_is_reported_and_not_published(self):
        rows = (_retirement("aaaa1111", "bbbb2222"),)
        unresolved: list[RetiredIdentifier] = []
        out, counts = retirement_redirects(set(), rows, unresolved=unresolved)
        self.assertEqual(out, [])
        self.assertEqual(counts["not_in_this_build"], 1)
        self.assertEqual([r.identifier for r in unresolved], ["aaaa1111"])

    def test_the_two_always_add_up(self):
        """The invariant #344 is about: nothing leaves without being counted."""
        rows = tuple(
            _retirement(f"id{n:06d}", f"tgt{n:05d}") for n in range(40)
        )
        published = {f"tgt{n:05d}" for n in range(0, 40, 3)}
        unresolved: list[RetiredIdentifier] = []
        out, counts = retirement_redirects(published, rows, unresolved=unresolved)
        self.assertEqual(
            counts["redirects_published"] + counts["not_in_this_build"], len(rows)
        )
        self.assertEqual(len(out), counts["redirects_published"])
        self.assertEqual(len(unresolved), counts["not_in_this_build"])

    def test_the_caller_need_not_ask_for_the_records(self):
        """Every call site that only wants the counts stays as it was."""
        rows = (_retirement("aaaa1111", "bbbb2222"),)
        out, counts = retirement_redirects(set(), rows)
        self.assertEqual(out, [])
        self.assertEqual(counts["not_in_this_build"], 1)


class _Database:
    """The two columns the queue writer reads, and nothing else."""

    def __init__(self, directory: str, flows: list[tuple[str, str, str, int]]):
        self.path = Path(directory) / "consensus-flows.sqlite3"
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute(
                "CREATE TABLE elementary_flows ("
                "uuid TEXT, flow_object_id TEXT, context_display TEXT, "
                "is_deprecated INTEGER)"
            )
            connection.executemany(
                "INSERT INTO elementary_flows VALUES (?, ?, ?, ?)", flows
            )
            connection.commit()


class TheQueueSaysWhatCanBeAnsweredTestCase(unittest.TestCase):
    """Three kinds of unresolvable retirement, told apart.

    The split is the whole value of the queue: 92 of the 160 on the build of 25
    August name a substance that is gone, 60 name one that survives in several
    contexts, and 8 have exactly one flow to point at.  Only the last is a
    curator's next five minutes.
    """

    def _items(self, flows, rows):
        from brightway_flows.pipeline import exporting

        with TemporaryDirectory() as directory:
            db = _Database(directory, flows)
            original = exporting.load_retired_minted_flow_ids
            exporting.load_retired_minted_flow_ids = lambda: rows
            try:
                return exporting.retired_identifier_queue_items(db.path)
            finally:
                exporting.load_retired_minted_flow_ids = original

    def test_a_substance_with_no_live_flow_is_information_only(self):
        rows = (_retirement("aaaa1111", "gone", name="Oils, Biogenic"),)
        items = self._items([], rows)
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item.queue_name, ReviewQueue.RETIRED_IDENTIFIER_UNRESOLVED)
        self.assertEqual(item.severity, Severity.INFO)
        self.assertFalse(item.payload["substance_still_published"])
        self.assertEqual(item.payload["surviving_flows"], [])
        self.assertEqual(item.payload["unambiguous_target"], "")
        self.assertIn("the substance is gone", item.title)

    def test_a_substance_with_one_live_flow_offers_that_flow(self):
        row = _retirement("aaaa1111", "gone", name="Groundwater")
        flows = [("surviving", row.flow_object_id, "Resource → Water → Unconfined aquifer", 0)]
        item = self._items(flows, (row,))[0]
        self.assertEqual(item.severity, Severity.REVIEW)
        self.assertTrue(item.payload["substance_still_published"])
        self.assertEqual(item.payload["unambiguous_target"], "surviving")
        self.assertNotIn("the substance is gone", item.title)

    def test_a_substance_in_several_contexts_offers_none_of_them(self):
        """The 60 that cannot be answered by counting.

        The retired identifier names the one context that is now empty, so
        picking among the others is a decision about the substance.  The queue
        lists them and chooses nothing.
        """
        row = _retirement("aaaa1111", "gone", name="Iron(2+)")
        flows = [
            ("a", row.flow_object_id, "Environmental → Water → Surface water", 0),
            ("b", row.flow_object_id, "Environmental → Air → Long-term", 0),
        ]
        item = self._items(flows, (row,))[0]
        self.assertEqual(item.severity, Severity.REVIEW)
        self.assertTrue(item.payload["substance_still_published"])
        self.assertEqual(item.payload["unambiguous_target"], "")
        self.assertEqual(len(item.payload["surviving_flows"]), 2)

    def test_a_deprecated_flow_does_not_count_as_a_survivor(self):
        """A deprecated flow is not somewhere an identifier can be sent."""
        row = _retirement("aaaa1111", "gone", name="Peat")
        flows = [("dead", row.flow_object_id, "Resource → Biotic", 1)]
        item = self._items(flows, (row,))[0]
        self.assertEqual(item.severity, Severity.INFO)
        self.assertFalse(item.payload["substance_still_published"])

    def test_every_unresolved_retirement_reaches_the_queue(self):
        """The count and the queue are one pass, and this says so."""
        from brightway_flows.pipeline import exporting

        rows = tuple(_retirement(f"id{n:06d}", "gone") for n in range(7))
        with TemporaryDirectory() as directory:
            db = _Database(directory, [])
            original = exporting.load_retired_minted_flow_ids
            exporting.load_retired_minted_flow_ids = lambda: rows
            try:
                counts = exporting.retirement_stats(db.path)
                items = exporting.retired_identifier_queue_items(db.path)
            finally:
                exporting.load_retired_minted_flow_ids = original
        self.assertEqual(len(items), counts["not_in_this_build"])
        self.assertEqual(counts["unresolved_substance_absent"], len(rows))


if __name__ == "__main__":
    unittest.main()
