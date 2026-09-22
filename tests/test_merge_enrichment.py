"""Each source list is enriched before it is matched (#213, step 2 of #210).

The loop itself is `apply_transformers`, covered by `test_apply_transformers.py`,
including the `Flow.transformed` flag that keeps it off the consensus flows.
What is new here is what the merge does around it: the consensus flows come back
out of the database as records and are shown to every transformer, the uuid
space the two sides now share has to stay collision-free, and the fields
enrichment displaces have to be read from `flow.provided` rather than off the
enriched record.

`_source_labels` is the answer to the other half.  Matching used to look up one
name and its synonyms, which breaks the moment enrichment renames the row --
`MCPA` became `(4-Chloro-2-methylphenoxy)acetic acid` and hit the index under
neither.
"""

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import orjson

from brightway_flows.domain.flow import Flow
from brightway_flows.merge.matching import _source_labels
from brightway_flows.merge.pipeline import _enrich_against_consensus
from brightway_flows.sources import resolve_source_list
from brightway_flows.pipeline import Change


def _flow(uuid: str, name: str | None = "Carbon dioxide", **overrides) -> Flow:
    payload = {
        "uuid": uuid,
        "identifier": uuid,
        "source": "EF 3.1",
        "unit": "kg",
        "cas_numbers": [],
        "altLabel": [],
        "prefLabel": [{"@value": name, "@language": "en"}] if name else None,
    }
    payload.update(overrides)
    return Flow.from_dict(payload)


class _Recorder:
    """A transformer that records what it was shown and proposes fixed changes."""

    def __init__(self, name, changes=()):
        self.name = name
        self._changes = list(changes)
        self.seen: list[list[str]] = []

    def setup(self) -> None:  # pragma: no cover - the merge must not call this
        raise AssertionError("setup() belongs to the build, not to each source list")

    def transform(self, flows):
        self.seen.append([f.uuid for f in flows])
        return list(self._changes)


class EnrichAgainstConsensusTestCase(unittest.TestCase):
    """The loop as the merge calls it: both sides shown, source side written."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = Path(self._tmp.name) / "consensus-flows.sqlite3"
        conn = sqlite3.connect(self.db)
        conn.execute("CREATE TABLE elementary_flows (uuid TEXT PRIMARY KEY, flow_json TEXT)")
        conn.commit()
        conn.close()
        patch = mock.patch(
            "brightway_flows.merge.pipeline.CONSENSUS_DB_FILEPATH", self.db
        )
        patch.start()
        self.addCleanup(patch.stop)
        self.source = resolve_source_list("ecoinvent-3.12")

    def add_consensus(self, flow: Flow):
        """A flow as the transform stage left it: written, and marked."""
        flow.transformed = True
        conn = sqlite3.connect(self.db)
        conn.execute(
            "INSERT INTO elementary_flows VALUES (?, ?)",
            (flow.uuid, orjson.dumps(flow.to_dict()).decode()),
        )
        conn.commit()
        conn.close()

    def consensus_json(self, uuid: str) -> dict:
        conn = sqlite3.connect(self.db)
        try:
            return orjson.loads(
                conn.execute(
                    "SELECT flow_json FROM elementary_flows WHERE uuid = ?", (uuid,)
                ).fetchone()[0]
            )
        finally:
            conn.close()

    def enrich(self, source_flows, transformers):
        _enrich_against_consensus(
            source=self.source, source_flows=source_flows, transformers=transformers
        )

    def test_both_sides_are_shown_to_every_transformer(self):
        """Deduplication and consensus matching compare and group across the
        list; showing them only the new rows blinds exactly that."""
        self.add_consensus(_flow("u-1"))
        recorder = _Recorder("probe")
        self.enrich([_flow("s-1", name="CO2")], [recorder])
        self.assertEqual(recorder.seen, [["u-1", "s-1"]])

    def test_source_flows_are_mutated_in_place(self):
        """They carry their enrichment into matching; that is the whole point."""
        self.add_consensus(_flow("u-1"))
        source_flow = _flow("s-1", name="carbon dioxide")
        self.enrich(
            [source_flow],
            [_Recorder("probe", [Change("s-1", "cas_numbers", ["124-38-9"])])],
        )
        self.assertEqual(source_flow.cas_numbers, ["124-38-9"])

    def test_the_flag_travels_through_the_database(self):
        """It is what tells the merge which side of its list is already done,
        so it has to survive the round trip through `flow_json`."""
        self.add_consensus(_flow("u-1"))
        self.assertIs(self.consensus_json("u-1")["_transformed"], True)

    def test_a_consensus_flow_is_not_changed(self):
        """The transform stage settled these values with the whole chain in
        order.  Running the chain again over its own output degrades them."""
        self.add_consensus(_flow("u-1"))
        self.enrich(
            [_flow("s-1")],
            [_Recorder("probe", [Change("u-1", "cas_numbers", ["124-38-9"])])],
        )
        self.assertEqual(self.consensus_json("u-1").get("cas_numbers"), [])

    def test_a_shared_uuid_is_refused(self):
        """A `Change` addresses its target by uuid, so both copies' changes
        route to the source row -- including changes a transformer derived from
        the consensus flow -- and `transformed` does not catch it, because the
        flow it is checked on is the unmarked source row.  Nothing is corrupted;
        the routing is wrong, and silently so.  #212 removed the file that
        produced collisions, and this makes a returning one loud."""
        self.add_consensus(_flow("u-1"))
        with self.assertRaises(ValueError) as caught:
            self.enrich([_flow("u-1")], [_Recorder("probe")])
        self.assertIn("u-1", str(caught.exception))


class SourceLabelsTestCase(unittest.TestCase):
    """A row is known by every one of its names at once, so all are looked up."""

    def test_the_enriched_label_comes_first(self):
        flow = _flow("s-1", name="(4-Chloro-2-methylphenoxy)acetic acid")
        flow.provided.name = "MCPA"
        self.assertEqual(_source_labels(flow)[0], "(4-Chloro-2-methylphenoxy)acetic acid")

    def test_the_shipped_name_is_still_there(self):
        """The failure this exists for: enrichment renamed the row and it hit
        the label index under neither name."""
        flow = _flow("s-1", name="(4-Chloro-2-methylphenoxy)acetic acid")
        flow.provided.name = "MCPA"
        self.assertIn("MCPA", _source_labels(flow))

    def test_shipped_synonyms_and_enriched_alt_labels_are_both_included(self):
        flow = _flow("s-1", name="Flurochloridone", altLabel=[
            {"@value": "R 40244", "@language": "en"},
        ])
        flow.provided.name = "Flurochloridone"
        flow.provided.synonyms = ["Racer"]
        self.assertEqual(
            _source_labels(flow), ["Flurochloridone", "Racer", "R 40244"]
        )

    def test_labels_are_deduplicated_case_insensitively(self):
        """The shipped name usually survives enrichment unchanged, so without
        this every row would look up the same string twice."""
        flow = _flow("s-1", name="Carbon Dioxide", altLabel=[
            {"@value": "carbon  dioxide", "@language": "en"},
        ])
        flow.provided.name = "carbon dioxide"
        self.assertEqual(_source_labels(flow), ["Carbon Dioxide"])

    def test_a_row_with_nothing_but_a_shipped_name_still_has_one_label(self):
        """A list merged without enrichment: no prefLabel, no altLabel."""
        flow = _flow("s-1", name=None)
        flow.provided.name = "MCPA"
        self.assertEqual(_source_labels(flow), ["MCPA"])

    def test_blank_labels_are_dropped(self):
        flow = _flow("s-1", name="Flurochloridone", altLabel=[
            {"@value": "   ", "@language": "en"},
        ])
        flow.provided.synonyms = ["", "  "]
        self.assertEqual(_source_labels(flow), ["Flurochloridone"])


if __name__ == "__main__":
    unittest.main()
