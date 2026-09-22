"""A published flow is called what its substance is called, or a curator knows why.

The name of a substance is written twice -- on the flow object, where every
correction lands, and on each flow, which is what the export publishes -- and
until `substance_label_v1` nothing carried a correction from the first copy to
the second: 886 published flows on the 2026-08-19 build carried a name their own
substance had superseded, and 149 substances appeared in the export under two
different names at once (#7).

What these pin: the substance's name is written onto its flows and the name the
flow had survives as a synonym of the flow; a spelling variant is corrected with
no synonym and no curator; and a flow whose own name answers for a *different*
substance -- the only visible symptom of a mis-grouping (#116) -- keeps its name
and reaches the `substance-label-conflict` queue instead, unless a ruling in
`preferred-label-decisions.json` has already answered the pair.  The same rule
applied to a whole database is pinned last, because the merge moves object
labels on flows it never rewrites and repairs them through that route.
"""

import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import orjson

from brightway_flows.domain.flow import Flow
from brightway_flows.domain.flow_object import FlowObject
from brightway_flows.domain.labels import coerce_alt_labels, flow_label_value
from brightway_flows.domain.preferred_label_decisions import (
    APPROVE,
    REJECT,
    LabelDecision,
    decision_key,
)
from brightway_flows.pipeline.review_records import ReviewQueue
from brightway_flows.pipeline.substance_labels import (
    PASS_NAME,
    SubstancePrefLabelPass,
    apply_substance_labels_to_database,
)


def make_object(object_id: str, label: str, *, alt: list[str] | None = None) -> FlowObject:
    return FlowObject(
        flow_object_id=object_id,
        prefLabel=[{"@value": label, "@language": "en"}],
        altLabel=[{"@value": value, "@language": "en"} for value in (alt or [])],
        properties={},
        references=[],
        created_from={},
    )


def make_flow(uuid: str, label: str, object_id: str, **kwargs) -> Flow:
    return Flow(
        uuid=uuid,
        source="EF 3.1",
        unit="kg",
        prefLabel=[{"@value": label, "@language": "en"}] if label else [],
        flow_object_id=object_id,
        **kwargs,
    )


def ruling(current: str, replacement: str, decision: str) -> dict:
    return {
        decision_key(current, replacement): LabelDecision(
            current=current, replacement=replacement, decision=decision
        )
    }


def alt_values(flow) -> list[str]:
    return [item.value for item in coerce_alt_labels(flow.altLabel)]


class SubstancePrefLabelTestCase(unittest.TestCase):
    def run_pass(self, flows, objects, decisions=None):
        substance_labels = SubstancePrefLabelPass(decisions=decisions or {})
        stats = substance_labels.apply(flows, objects)
        return substance_labels, stats

    def test_the_substances_name_reaches_its_flow(self):
        """What the pass is for.  #66 renamed the land class on the substance
        and the flow kept EF 3.1's spelling; the flow now takes the rename and
        the old spelling stays findable on the flow."""
        flow = make_flow("u-1", "From Arable, Irrigated, Extensive", "fo-1")
        _, stats = self.run_pass(
            [flow], [make_object("fo-1", "From cropland, irrigated, extensive")]
        )

        self.assertEqual(flow_label_value(flow), "From cropland, irrigated, extensive")
        self.assertIn("From Arable, Irrigated, Extensive", alt_values(flow))
        self.assertEqual(stats["renamed"], 1)
        self.assertEqual(stats["synonyms_demoted"], 1)
        self.assertEqual(stats["kept_awaiting_ruling"], 0)

    def test_an_agreeing_flow_is_left_alone(self):
        flow = make_flow("u-1", "HC Blue No. 1", "fo-1")
        before = flow.prefLabel
        _, stats = self.run_pass([flow], [make_object("fo-1", "HC Blue No. 1")])

        self.assertIs(flow.prefLabel, before)
        self.assertEqual(stats["agreeing"], 1)

    def test_a_spelling_variant_is_corrected_without_a_synonym(self):
        """`Hc Blue No. 1` beside twelve flows saying `HC Blue No. 1` is not two
        names.  The ruled spelling is written and nothing is demoted, because a
        case variant is not a name anybody searches for."""
        flow = make_flow("u-1", "Hc Blue No. 1", "fo-1")
        _, stats = self.run_pass([flow], [make_object("fo-1", "HC Blue No. 1")])

        self.assertEqual(flow_label_value(flow), "HC Blue No. 1")
        self.assertEqual(alt_values(flow), [])
        self.assertEqual(stats["respelled"], 1)
        self.assertEqual(stats["renamed"], 0)

    def test_an_unnamed_flow_takes_the_substances_name(self):
        flow = make_flow("u-1", "", "fo-1")
        _, stats = self.run_pass([flow], [make_object("fo-1", "Zytron")])

        self.assertEqual(flow_label_value(flow), "Zytron")
        self.assertEqual(stats["labelled"], 1)

    def test_the_written_label_says_what_wrote_it(self):
        flow = make_flow("u-1", "Mercury (ii)", "fo-1")
        self.run_pass([flow], [make_object("fo-1", "Mercury(2+)")])

        provenance = flow.prefLabel[0]["source"]
        self.assertEqual(provenance["prov:wasGeneratedBy"], PASS_NAME)

    def test_a_name_answering_for_another_substance_is_kept_and_queued(self):
        """The exception that is the point.  Five flows named `Water` sit on
        `Water vapour` while a substance named `Water` exists; renaming them
        would delete the only visible symptom of the grouping question (#116),
        so the flow keeps its name and a curator is asked."""
        flow = make_flow("u-1", "Water", "fo-vapour")
        substance_labels, stats = self.run_pass(
            [flow],
            [make_object("fo-vapour", "Water vapour"), make_object("fo-water", "Water")],
        )

        self.assertEqual(flow_label_value(flow), "Water")
        self.assertEqual(stats["kept_awaiting_ruling"], 1)
        self.assertEqual(stats["renamed"], 0)

        items = substance_labels.review_queue_items()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].queue_name, ReviewQueue.SUBSTANCE_LABEL_CONFLICT)
        self.assertEqual(items[0].payload["current"], "Water")
        self.assertEqual(items[0].payload["replacement"], "Water vapour")
        self.assertEqual(items[0].payload["other_claimants"], ["Water (fo-water)"])

    def test_a_conflict_is_one_queue_item_however_many_flows_share_it(self):
        flows = [
            make_flow("u-1", "Water", "fo-vapour"),
            make_flow("u-2", "Water", "fo-vapour"),
        ]
        substance_labels, stats = self.run_pass(
            flows,
            [make_object("fo-vapour", "Water vapour"), make_object("fo-water", "Water")],
        )

        items = substance_labels.review_queue_items()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].payload["flow_count"], 2)
        self.assertEqual(stats["kept_awaiting_ruling"], 2)

    def test_another_substances_synonym_also_counts_as_a_claim(self):
        """A synonym is how a reader reaches a substance, so a name published as
        one is as much a collision as a preferred label."""
        flow = make_flow("u-1", "Quicksilver", "fo-1")
        substance_labels, stats = self.run_pass(
            [flow],
            [
                make_object("fo-1", "Mercury(2+)"),
                make_object("fo-2", "Mercury", alt=["Quicksilver"]),
            ],
        )

        self.assertEqual(flow_label_value(flow), "Quicksilver")
        self.assertEqual(stats["kept_awaiting_ruling"], 1)
        self.assertEqual(len(substance_labels.review_queue_items()), 1)

    def test_an_approved_conflict_renames_and_withholds_the_synonym(self):
        """#113: a name that answers for two substances is published for
        neither.  The ruling says the grouping is right, so the rename happens
        and the colliding name is not kept as a synonym of this flow."""
        flow = make_flow("u-1", "Water", "fo-vapour")
        substance_labels, stats = self.run_pass(
            [flow],
            [make_object("fo-vapour", "Water vapour"), make_object("fo-water", "Water")],
            decisions=ruling("Water", "Water vapour", APPROVE),
        )

        self.assertEqual(flow_label_value(flow), "Water vapour")
        self.assertEqual(alt_values(flow), [])
        self.assertEqual(stats["demoted_names_withheld"], 1)
        self.assertEqual(substance_labels.review_queue_items(), [])

    def test_a_rejected_conflict_keeps_the_flows_name_and_is_not_queued(self):
        flow = make_flow("u-1", "Water", "fo-vapour")
        substance_labels, stats = self.run_pass(
            [flow],
            [make_object("fo-vapour", "Water vapour"), make_object("fo-water", "Water")],
            decisions=ruling("Water", "Water vapour", REJECT),
        )

        self.assertEqual(flow_label_value(flow), "Water")
        self.assertEqual(stats["kept_by_ruling"], 1)
        self.assertEqual(substance_labels.review_queue_items(), [])

    def test_a_synonym_the_flow_already_carries_is_not_doubled(self):
        flow = make_flow("u-1", "Mercury (ii)", "fo-1")
        flow.altLabel = [{"@value": "Mercury (II)", "@language": "en"}]
        self.run_pass([flow], [make_object("fo-1", "Mercury(2+)")])

        self.assertEqual(flow_label_value(flow), "Mercury(2+)")
        self.assertEqual(alt_values(flow), ["Mercury (II)"])

    def test_the_demoted_name_keeps_its_own_provenance(self):
        """#247: the name being demoted was written by whoever wrote it, and
        the synonym row says so rather than crediting this pass."""
        flow = make_flow("u-1", "Mercury (ii)", "fo-1")
        flow.prefLabel = [{
            "@value": "Mercury (ii)",
            "@language": "en",
            "source": {"prov:wasGeneratedBy": "bootstrap_labels"},
        }]
        self.run_pass([flow], [make_object("fo-1", "Mercury(2+)")])

        demoted = [row for row in flow.altLabel if row.get("@value") == "Mercury (ii)"]
        self.assertEqual(len(demoted), 1)
        self.assertEqual(
            demoted[0]["provenance"]["prov:wasGeneratedBy"], "bootstrap_labels"
        )

    def test_a_flow_without_a_substance_is_left_alone(self):
        flow = make_flow("u-1", "Anything", "")
        _, stats = self.run_pass([flow], [make_object("fo-1", "Something Else")])

        self.assertEqual(flow_label_value(flow), "Anything")
        self.assertEqual(stats["flows_with_a_substance"], 0)


class DatabaseApplierTestCase(unittest.TestCase):
    """The same rule over a written database, which is the merge's route.

    A merge moves object labels on flows it never rewrites -- a minted object's
    name wins a contest, `carry_member_names` demotes a second preferred label
    -- so the repair runs over the whole database after the merge's own writes
    and before the export.
    """

    def build_db(self, path: Path, objects, flows, payloads=None) -> None:
        connection = sqlite3.connect(path)
        connection.executescript(
            "CREATE TABLE flow_objects ("
            "flow_object_id TEXT, pref_label_value TEXT, alt_label_json TEXT);"
            "CREATE TABLE elementary_flows ("
            "uuid TEXT, flow_object_id TEXT, is_deprecated INTEGER, flow_json TEXT);"
            "CREATE TABLE flow_object_payloads ("
            "flow_object_id TEXT, payload_json TEXT);"
        )
        connection.executemany(
            "INSERT INTO flow_objects VALUES (?, ?, ?)",
            [
                (object_id, label, orjson.dumps(
                    [{"@value": value, "@language": "en"} for value in alt]
                ).decode())
                for object_id, label, alt in objects
            ],
        )
        connection.executemany(
            "INSERT INTO elementary_flows VALUES (?, ?, ?, ?)",
            [
                (uuid, object_id, deprecated, orjson.dumps(payload).decode())
                for uuid, object_id, deprecated, payload in flows
            ],
        )
        connection.executemany(
            "INSERT INTO flow_object_payloads VALUES (?, ?)",
            [
                (object_id, orjson.dumps(payload).decode())
                for object_id, payload in (payloads or [])
            ],
        )
        connection.commit()
        connection.close()

    def read_flow(self, path: Path, uuid: str) -> dict:
        connection = sqlite3.connect(path)
        try:
            row = connection.execute(
                "SELECT flow_json FROM elementary_flows WHERE uuid = ?", (uuid,)
            ).fetchone()
            return orjson.loads(row[0])
        finally:
            connection.close()

    def test_a_stale_flow_is_rewritten_and_a_deprecated_one_is_not(self):
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "consensus.sqlite3"
            self.build_db(
                db,
                objects=[("fo-1", "Mercury(2+)", [])],
                flows=[
                    ("u-1", "fo-1", 0,
                     {"uuid": "u-1", "prefLabel": [{"@value": "Mercury (ii)", "@language": "en"}]}),
                    ("u-2", "fo-1", 1,
                     {"uuid": "u-2", "prefLabel": [{"@value": "Mercury (ii)", "@language": "en"}]}),
                ],
            )
            stats, items = apply_substance_labels_to_database(db, decisions={})

            self.assertEqual(stats["renamed"], 1)
            self.assertEqual(stats["flows_rewritten"], 1)
            self.assertEqual(items, [])
            live = self.read_flow(db, "u-1")
            self.assertEqual(flow_label_value(live), "Mercury(2+)")
            self.assertIn(
                "Mercury (ii)",
                [row.get("@value") for row in live["altLabel"]],
            )
            deprecated = self.read_flow(db, "u-2")
            self.assertEqual(flow_label_value(deprecated), "Mercury (ii)")

    def test_a_label_inherited_from_the_hoisted_payload_is_compared_and_kept_current(self):
        """413 of the 886 stale flows had no `prefLabel` of their own -- it
        lived in the hoisted object payload (#253).  The comparison reads the
        merged view, and the rewrite touches only the flow's own keys."""
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "consensus.sqlite3"
            self.build_db(
                db,
                objects=[("fo-1", "From cropland, irrigated, extensive", [])],
                flows=[("u-1", "fo-1", 0, {"uuid": "u-1"})],
                payloads=[
                    ("fo-1", {"prefLabel": [
                        {"@value": "From Arable, Irrigated, Extensive", "@language": "en"}
                    ]})
                ],
            )
            stats, _ = apply_substance_labels_to_database(db, decisions={})

            self.assertEqual(stats["renamed"], 1)
            flow = self.read_flow(db, "u-1")
            self.assertEqual(
                flow_label_value(flow), "From cropland, irrigated, extensive"
            )
            self.assertIn(
                "From Arable, Irrigated, Extensive",
                [row.get("@value") for row in flow["altLabel"]],
            )

    def test_a_conflict_in_the_database_is_queued_not_rewritten(self):
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "consensus.sqlite3"
            self.build_db(
                db,
                objects=[("fo-vapour", "Water vapour", []), ("fo-water", "Water", [])],
                flows=[
                    ("u-1", "fo-vapour", 0,
                     {"uuid": "u-1", "prefLabel": [{"@value": "Water", "@language": "en"}],
                      "cas_numbers": ["7732-18-5"]}),
                    ("u-2", "fo-water", 0,
                     {"uuid": "u-2", "prefLabel": [{"@value": "Water", "@language": "en"}]}),
                ],
            )
            stats, items = apply_substance_labels_to_database(db, decisions={})

            self.assertEqual(stats["kept_awaiting_ruling"], 1)
            self.assertEqual(stats["flows_rewritten"], 0)
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0].queue_name, ReviewQueue.SUBSTANCE_LABEL_CONFLICT)
            self.assertEqual(items[0].cas, "7732-18-5")
            self.assertEqual(
                flow_label_value(self.read_flow(db, "u-1")), "Water"
            )


if __name__ == "__main__":
    unittest.main()
