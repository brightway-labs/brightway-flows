"""#78: a vendor list can ship one flow in two units.

The merge asks whether a source row measures the same thing as the flow it
landed on, and it asked that only of rows it *matched*.  A row that matches
nothing creates a flow instead, and for those nothing asked anything -- so
BAFU's road noise arriving in kilometres and in metres, and its waste heat in
megajoules and in kilowatt-hours, produced flows nobody was told about.

The question a creation can answer is not the same one.  There is no target to
disagree with, because the row is the target; what can disagree is the rows
landing together.  Whichever way that is settled, a row measured in something
other than the flow it made is flagged exactly as a matched row is, and means
the same by it.
"""

import json
import tempfile
import unittest
from pathlib import Path
from tempfile import mkdtemp
from unittest import mock

import orjson

from brightway_flows.context_mapping import context_iri_by_source_context
from brightway_flows.domain.context_registry import context_from_dict
from brightway_flows.domain.elementary_flow import ElementaryFlow
from brightway_flows.domain.flow import Flow
from brightway_flows.domain.flow_object import FlowObject
from brightway_flows.merge import unit_changes
from brightway_flows.merge.contexts import ContextExpectations
from brightway_flows.merge.creations import create_flows_for_unmatched_rows
from brightway_flows.merge.report import UnmatchedReason, UnmatchedRow
from brightway_flows.merge.state import MergeAccumulator, MergeIndexes
from brightway_flows.merge.store import (
    MergeOutcome,
    MergeRunInput,
    write_merge_run,
)
from brightway_flows.merge.unit_changes import (
    DECIDED_BY_CURATOR,
    DECIDED_BY_PUBLISHED_UNIT,
    DECIDED_BY_UNIT_TABLE,
    UNDECIDED,
    CreatedFlowUnitError,
    PublishedUnitError,
    created_flow_unit_decisions,
    decide_created_flow_unit,
    is_a_reference_unit,
    published_unit_for,
    published_units,
)
import brightway_flows.pipeline.sqlite as sqlite_module
from brightway_flows.pipeline.sqlite import _write_consensus_sqlite
from brightway_flows.sources import known_source_lists, resolve_source_list
from brightway_flows.transformers.unit_normalization import build_units_index
from brightway_flows.webapps.app import create_app, db
from brightway_flows.webapps.app.queries import checks as check_queries

BAFU = "bafu-2026-v1"


#: What BAFU files its noise under: a burden that is not matter.
_NON_MATERIAL = context_from_dict(
    {"dimension": "Environmental", "media": "Other"}
)

class DecidingTestCase(unittest.TestCase):
    """Which unit the flow states, and where the answer came from."""

    def test_the_reference_unit_wins_whichever_row_came_first(self):
        for units in (["km", "m"], ["m", "km"]):
            with self.subTest(first=units[0]):
                decision = decide_created_flow_unit(units)
                self.assertEqual(decision.declared, "m")
                self.assertEqual(decision.decided_by, DECIDED_BY_UNIT_TABLE)

    def test_a_curated_row_beats_the_unit_table(self):
        """Order matters: a curator writing a decision means to be obeyed."""
        decision = decide_created_flow_unit(
            ["km", "m"], source_uuids=["u-km", "u-m"], decisions={"u-km": {}}
        )
        self.assertEqual(decision.declared, "km")
        self.assertEqual(decision.decided_by, DECIDED_BY_CURATOR)

    def test_two_multiples_and_no_reference_between_them_is_unresolved(self):
        """Megajoules against kilowatt-hours.  The coherent unit for an energy
        is the joule and BAFU offers neither, so preferring one multiple over
        another would be a convention invented here."""
        decision = decide_created_flow_unit(["MJ", "kwh"])
        self.assertEqual(decision.declared, "MJ")
        self.assertEqual(decision.decided_by, UNDECIDED)

    def test_one_unit_is_not_a_decision(self):
        decision = decide_created_flow_unit(["kg", "kg"])
        self.assertEqual(decision.units, ("kg",))
        self.assertFalse(decision.rows_disagree)
        self.assertEqual(decision.decided_by, DECIDED_BY_UNIT_TABLE)

    def test_no_units_decides_nothing(self):
        decision = decide_created_flow_unit([])
        self.assertEqual(decision.declared, "")
        self.assertFalse(decision.rows_disagree)

    def test_the_reference_unit_is_read_off_the_unit_table(self):
        for unit, expected in (
            ("m", True), ("km", False), ("kg", True), ("Bq", True),
            ("kBq", False), ("MJ", False), ("t.km", False),
        ):
            with self.subTest(unit=unit):
                self.assertEqual(is_a_reference_unit(unit), expected)


class PublishedUnitTestCase(unittest.TestCase):
    """#142: the unit this list publishes a quantity kind in wins the scale.

    EF 3.1 ships every radionuclide flow in kilobecquerels and BAFU ships its
    radionuclides in becquerels and kilobecquerels both, so a flow the pair
    mints has to state the kilobecquerel however the rows arrive -- not the
    becquerel, which is the SI reference and used to win the tie-break, and
    not whichever spelling the merge read first.
    """

    def test_the_published_unit_beats_the_reference_unit(self):
        for units in (["Bq", "kBq"], ["kBq", "Bq"]):
            with self.subTest(first=units[0]):
                decision = decide_created_flow_unit(units)
                self.assertEqual(decision.declared, "kBq")
                self.assertEqual(decision.decided_by, DECIDED_BY_PUBLISHED_UNIT)

    def test_a_lone_becquerel_row_still_mints_a_kilobecquerel_flow(self):
        """The convention is about the list, not an arbitration between rows,
        so it applies with nothing to arbitrate."""
        decision = decide_created_flow_unit(["Bq"])
        self.assertEqual(decision.declared, "kBq")
        self.assertEqual(decision.decided_by, DECIDED_BY_PUBLISHED_UNIT)
        self.assertFalse(decision.rows_disagree)

    def test_a_row_already_in_the_published_unit_is_left_alone(self):
        """The other half of the rule: a stated kilobecquerel is not a
        decision, and reads exactly as it did before the convention existed."""
        decision = decide_created_flow_unit(["kBq"])
        self.assertEqual(decision.declared, "kBq")
        self.assertEqual(decision.decided_by, DECIDED_BY_UNIT_TABLE)
        self.assertFalse(decision.rows_disagree)

    def test_a_curated_row_still_beats_the_published_unit(self):
        """A curator writing a decision means to be obeyed, over every table."""
        decision = decide_created_flow_unit(
            ["Bq", "kBq"], source_uuids=["u-bq", "u-kbq"], decisions={"u-bq": {}}
        )
        self.assertEqual(decision.declared, "Bq")
        self.assertEqual(decision.decided_by, DECIDED_BY_CURATOR)

    def test_quantity_kinds_with_no_convention_are_untouched(self):
        for units in (["kg"], ["m"], ["MJ", "kwh"], ["km", "m"]):
            with self.subTest(units=units):
                self.assertIsNone(published_unit_for(units))

    def test_units_of_two_kinds_are_not_restated(self):
        """A becquerel beside a kilogram is not a group the convention can
        wholly restate, so it says nothing and the later rules answer."""
        self.assertIsNone(published_unit_for(["Bq", "kg"]))

    def test_an_unknown_unit_disarms_the_convention(self):
        self.assertIsNone(published_unit_for(["Bq", "curies-per-fortnight"]))

    def test_the_shipped_file_loads_and_names_the_kilobecquerel(self):
        conventions = published_units()
        activity = [
            row for row in conventions.values() if row.notation == "kBq"
        ]
        self.assertEqual(len(activity), 1)
        self.assertGreater(len(activity[0].comment), 40)

    def test_no_shipped_convention_restates_the_reference_unit(self):
        """An entry naming the reference unit would silently shadow the
        reference-unit rule while asserting nothing beyond it."""
        for kind, row in published_units().items():
            with self.subTest(kind=kind):
                self.assertFalse(
                    is_a_reference_unit(row.notation),
                    f"{row.notation} is the reference unit already",
                )


class PublishedUnitsFileTestCase(unittest.TestCase):
    """What a published-unit convention has to carry to be one."""

    GOOD = {
        "quantity_kind_iri": "https://vocab.brightway.one/units/quantity-kind/Activity",
        "notation": "kBq",
        "comment": "because",
    }

    def _load(self, *rows):
        path = Path(mkdtemp()) / "published-units.json"
        path.write_bytes(orjson.dumps({"units": list(rows)}))
        with mock.patch.object(unit_changes, "PUBLISHED_UNITS_FILEPATH", path):
            unit_changes.published_units.cache_clear()
            try:
                return unit_changes.published_units()
            finally:
                unit_changes.published_units.cache_clear()

    def test_a_complete_convention_loads(self):
        loaded = self._load(self.GOOD)
        self.assertEqual(
            loaded[self.GOOD["quantity_kind_iri"]].notation, "kBq"
        )

    def test_every_required_field_is_required(self):
        for field in ("quantity_kind_iri", "notation", "comment"):
            with self.subTest(missing=field):
                row = {k: v for k, v in self.GOOD.items() if k != field}
                with self.assertRaises(PublishedUnitError) as caught:
                    self._load(row)
                self.assertIn(field, str(caught.exception))

    def test_a_unit_the_table_does_not_know_is_refused(self):
        with self.assertRaises(PublishedUnitError):
            self._load({**self.GOOD, "notation": "curies-per-fortnight"})

    def test_a_unit_of_another_quantity_kind_is_refused(self):
        with self.assertRaises(PublishedUnitError):
            self._load({**self.GOOD, "notation": "kg"})

    def test_two_units_for_one_kind_is_an_error_rather_than_last_wins(self):
        other = {**self.GOOD, "notation": "Bq"}
        with self.assertRaises(PublishedUnitError) as caught:
            self._load(self.GOOD, other)
        self.assertIn("One quantity kind, one published unit", str(caught.exception))

    def test_a_file_with_no_conventions_is_not_an_error(self):
        self.assertEqual(self._load(), {})


class DecisionsFileTestCase(unittest.TestCase):
    """What a curated decision has to carry, and what it must still describe."""

    GOOD = {
        "source": BAFU,
        "source_uuid": "u-1",
        "source_name": "Heat, waste",
        "source_unit": "MJ",
        "comment": "because",
    }

    def _load(self, *rows, source=BAFU):
        path = Path(mkdtemp()) / "created-flow-unit-decisions.json"
        path.write_bytes(orjson.dumps({"decisions": list(rows)}))
        with mock.patch.object(unit_changes, "DECISIONS_FILEPATH", path):
            unit_changes.created_flow_unit_decisions.cache_clear()
            try:
                return unit_changes.created_flow_unit_decisions(source)
            finally:
                unit_changes.created_flow_unit_decisions.cache_clear()

    def test_a_complete_decision_loads(self):
        self.assertEqual(set(self._load(self.GOOD)), {"u-1"})

    def test_every_required_field_is_required(self):
        for field in ("source", "source_uuid", "source_name", "source_unit", "comment"):
            with self.subTest(missing=field):
                row = {k: v for k, v in self.GOOD.items() if k != field}
                with self.assertRaises(CreatedFlowUnitError) as caught:
                    self._load(row)
                self.assertIn(field, str(caught.exception))

    def test_an_empty_field_counts_as_missing(self):
        for field in ("source_uuid", "source_unit", "comment"):
            with self.subTest(empty=field):
                with self.assertRaises(CreatedFlowUnitError):
                    self._load({**self.GOOD, field: "   "})

    def test_two_decisions_for_one_flow_is_an_error_rather_than_last_wins(self):
        other = {**self.GOOD, "source_unit": "kWh"}
        with self.assertRaises(CreatedFlowUnitError) as caught:
            self._load(self.GOOD, other)
        self.assertIn("One flow, one decision", str(caught.exception))

    def test_rows_for_other_lists_are_ignored(self):
        self.assertEqual(self._load(self.GOOD, source="somebody-else"), {})

    def test_a_file_with_no_decisions_is_not_an_error(self):
        self.assertEqual(self._load(), {})

    def test_every_shipped_decision_still_describes_a_row_its_list_ships(self):
        """A decision names a row by uuid and outlives the vendor changing it.

        The same argument `flow_specific_context_mappings` makes with
        `source_context`: a rule that keeps applying after what justified it
        moved is worse than one that fails.  These are few enough to check.
        """
        for key, source in known_source_lists().items():
            decisions = created_flow_unit_decisions(source.source_label)
            if not decisions:
                continue
            if not source.flows_path.exists():
                self.skipTest(f"vendor flow file not fetched: {source.flows_path.name}")
            shipped = {
                flow["uuid"]: flow
                for flow in json.loads(source.flows_path.read_bytes())
            }
            for uuid, row in decisions.items():
                with self.subTest(source=key, uuid=uuid):
                    flow = shipped.get(uuid)
                    self.assertIsNotNone(flow, "uuid is not in this list")
                    self.assertEqual(flow["name"], row.source_name)
                    self.assertEqual(flow["unit"], row.source_unit)

    def test_no_shipped_decision_restates_what_the_unit_table_already_says(self):
        """A decision exists where no rule could decide.  One naming a unit the
        table would have chosen anyway is not a decision, it is a duplicate that
        will go stale in silence when the table moves."""
        for source in known_source_lists().values():
            for uuid, row in created_flow_unit_decisions(source.source_label).items():
                with self.subTest(uuid=uuid):
                    self.assertFalse(
                        is_a_reference_unit(row.source_unit),
                        f"{row.source_name} states the reference unit already",
                    )

    def test_every_shipped_decision_carries_its_reasoning(self):
        for source in known_source_lists().values():
            for uuid, row in created_flow_unit_decisions(source.source_label).items():
                with self.subTest(uuid=uuid):
                    self.assertGreater(len(row.comment), 40)


def _merge_bafu(rows):
    """Run *rows* through the merge's creation path with BAFU's real rules."""
    source = resolve_source_list(BAFU)
    indexes = MergeIndexes(
        flow_objects_by_id={},
        flow_object_label_by_id={},
        cas_index={},
        ec_index={},
        label_index={},
        pref_label_index={},
        qualifier_index={},
        flow_objects_with_cas=set(),
        context_expectations=ContextExpectations(
            _by_source_context=dict(context_iri_by_source_context(BAFU)),
            _source_label=BAFU,
        ),
        consensus_context_strings={},
        prepared_context_decisions={},
        mapping_file=None,
        source=source,
    )
    unmatched = [
        UnmatchedRow(
            source_uuid=row["uuid"],
            source_name=row["name"],
            source_context=list(row["context"]),
            source_unit=row["unit"],
            source_cas="",
            source_ec="",
            reason=UnmatchedReason.NO_FLOW_OBJECT_CANDIDATE,
            matching_method="algorithm",
        )
        for row in rows
    ]
    flows = {
        row["uuid"]: Flow.from_dict({
            "uuid": row["uuid"],
            "identifier": row["uuid"],
            "source": BAFU,
            "unit": row["unit"],
            "prefLabel": [{"@value": row["name"], "@language": "en"}],
            "altLabel": [],
        })
        for row in rows
    }
    accumulator = MergeAccumulator()
    _objects, created = create_flows_for_unmatched_rows(
        unmatched=unmatched,
        source_flow_by_uuid=flows,
        units_index=build_units_index(),
        indexes=indexes,
        accumulator=accumulator,
    )
    return created, accumulator


class ThroughTheMergeTestCase(unittest.TestCase):
    """Over the rows BAFU actually ships, through the merge's own path."""

    def _rows(self, *prefixes):
        """Through the source list's own loader, not the file it reads.

        The merge is handed rows with the manual fixes already applied, and one
        of those matters here: #287 renames BAFU's stray `Energy, waste heat,
        air` to `Heat, waste`, so a third row joins the group this decision
        governs.  Reading the vendor file directly would test a group the merge
        never sees.
        """
        source = resolve_source_list(BAFU)
        if not source.flows_path.exists():
            self.skipTest(f"vendor flow file not fetched: {source.flows_path.name}")
        rows = [
            {
                "uuid": flow.uuid,
                "name": flow.name,
                "context": list(flow.provided.context),
                "unit": flow.unit,
            }
            for flow in source.load_flows()
            if (flow.name or "").lower().startswith(prefixes)
        ]
        self.assertTrue(rows, f"BAFU ships no rows named {prefixes}")
        return rows

    def test_the_renamed_stray_row_joins_the_group_it_was_renamed_into(self):
        """#287's half of this: `Energy, waste heat, air` became `Heat, waste`.

        It arrives in megajoules, which is what the decision already chose, so
        it adds no disagreement -- but it is in the group now, and a rename that
        brought a third unit with it would change the answer.
        """
        rows = self._rows("heat, waste")
        renamed = [row for row in rows if row["context"] == ["resources", "in air"]]
        self.assertEqual(len(renamed), 1, "the stray row is no longer renamed here")
        self.assertEqual(renamed[0]["unit"], "MJ")

    def test_waste_heat_takes_the_curated_unit_and_flags_the_other_row(self):
        """BAFU writes `Heat, waste` in megajoules in thirteen compartments and
        in kilowatt-hours in one, where it writes the megajoule row too."""
        created, accumulator = _merge_bafu(self._rows("heat, waste"))

        flagged = [row for row in created if row.has_unit_mismatch]
        self.assertEqual([row.source_unit for row in flagged], ["kWh"])
        self.assertEqual(flagged[0].unit_decision["declared"], "MJ")
        self.assertEqual(flagged[0].unit_decision["decided_by"], DECIDED_BY_CURATOR)
        self.assertEqual(
            {
                flow.unit for flow in accumulator.merged_elementary
                if flow.extra["prefLabel"][0]["@value"]
                .lower().startswith("heat, waste")
            },
            {"MJ"},
        )

    def test_road_noise_takes_the_reference_unit_and_flags_the_other_rows(self):
        created, accumulator = _merge_bafu(self._rows("noise, road"))

        flagged = [row for row in created if row.has_unit_mismatch]
        self.assertEqual({row.source_unit for row in flagged}, {"km"})
        self.assertEqual(
            {row.unit_decision["decided_by"] for row in flagged},
            {DECIDED_BY_UNIT_TABLE},
        )
        self.assertEqual(
            {flow.unit for flow in accumulator.merged_elementary}, {"m"}
        )

    def test_a_row_that_agrees_with_its_flow_is_not_flagged(self):
        """Only the row measured in something else.  The same rule the matched
        side follows, so a reader of the report needs one explanation."""
        created, _accumulator = _merge_bafu(self._rows("heat, waste", "noise, road"))

        agreeing = [row for row in created if not row.has_unit_mismatch]
        self.assertTrue(agreeing)
        for row in agreeing:
            with self.subTest(name=row.source_name, unit=row.source_unit):
                self.assertEqual(row.source_unit, row.unit_decision["declared"])

    def test_the_flag_reaches_the_merge_outcome(self):
        """`has_unit_mismatch` was 0 on every created outcome ever written."""
        created, _accumulator = _merge_bafu(self._rows("noise, road"))
        source = resolve_source_list(BAFU)

        outcomes = [
            MergeOutcome.from_created("run-1", source, row) for row in created
        ]
        flagged = [outcome for outcome in outcomes if outcome.has_unit_mismatch]
        self.assertEqual({outcome.source_unit for outcome in flagged}, {"km"})
        self.assertEqual({outcome.outcome for outcome in flagged}, {"created"})

    def test_the_outcome_carries_how_the_unit_was_settled(self):
        """`outcome` says which question was asked; the detail says who
        answered it, which is what separates a run that needs a curator from a
        run that does not."""
        created, _accumulator = _merge_bafu(self._rows("noise, road"))
        source = resolve_source_list(BAFU)

        outcome = MergeOutcome.from_created("run-1", source, created[0])
        self.assertEqual(
            outcome.detail["unit_decision"]["decided_by"], DECIDED_BY_UNIT_TABLE
        )


class ReviewPageTestCase(unittest.TestCase):
    """The page, because the flag has existed for months with nowhere to show.

    143 matched rows carried `has_unit_mismatch` in the last full run and no
    page in the review application read the column.
    """

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "consensus-flows.sqlite3"
        named = {
            "flow-noise": ("Noise, Road, Lorry, Average", "m"),
            "flow-heat": ("Heat, Waste", "MJ"),
        }
        flows = [
            Flow(
                uuid=uuid,
                source=BAFU,
                unit=unit,
                flow_object_id=f"fo-{uuid}",
                prefLabel=[{"@value": name, "@language": "en"}],
                context=_NON_MATERIAL,
            )
            for uuid, (name, unit) in named.items()
        ]
        objects = [
            FlowObject(
                flow_object_id=f"fo-{uuid}",
                prefLabel=[{"@value": name, "@language": "en"}],
                altLabel=[],
                classifications={},
                properties={},
                references=[],
                created_from={},
            )
            for uuid, (name, _unit) in named.items()
        ]
        elementary = [
            ElementaryFlow(
                elementary_flow_id=uuid,
                flow_object_id=f"fo-{uuid}",
                source=BAFU,
                context=_NON_MATERIAL,
                context_iri="",
                unit=unit,
                unit_iri="",
                lcia_methods=[],
                general_comment=None,
            )
            for uuid, (_name, unit) in named.items()
        ]
        # Through the pipeline's own writer, with its module-level path
        # redirected: a hand-built fixture would let these tests pass over a
        # shape the pipeline never produces.
        original = sqlite_module.CONSENSUS_DB_FILEPATH
        sqlite_module.CONSENSUS_DB_FILEPATH = self.path
        try:
            _write_consensus_sqlite(flows, [], objects, elementary)
        finally:
            sqlite_module.CONSENSUS_DB_FILEPATH = original
        write_merge_run(
            self.path,
            run_id="merge-1",
            started_at="2026-08-14T00:01:00+00:00",
            finished_at="2026-08-14T00:02:00+00:00",
            inputs=[MergeRunInput(run_id="merge-1", list_name="bafu",
                                  list_version="2026-v1", sequence=0, row_count=3)],
            outcomes=[
                self._flagged("u-km", "Noise, Road, Lorry, Average", "km", "created",
                              "flow-noise", {"units": ["km", "m"], "declared": "m",
                                             "decided_by": DECIDED_BY_UNIT_TABLE}),
                self._flagged("u-kwh", "Heat, Waste", "kWh", "created", "flow-heat",
                              {"units": ["kWh", "MJ"], "declared": "MJ",
                               "decided_by": UNDECIDED}),
                self._flagged("u-matched", "Coal, brown", "kg", "algorithm",
                              "flow-heat", None),
            ],
            stats={},
        )


    @staticmethod
    def _flagged(uuid, name, unit, outcome, target, decision):
        detail = {"unit_decision": decision} if decision else {}
        return MergeOutcome(
            run_id="merge-1", list_name="bafu", list_version="2026-v1",
            source_uuid=uuid, outcome=outcome, source_name=name, source_unit=unit,
            target_elementary_flow_id=target, has_unit_mismatch=True, detail=detail,
        )

    def connection(self):
        connection = db.connect(self.path)
        self.addCleanup(connection.close)
        return connection

    def client(self):
        app = create_app(self.path)
        app.config["TESTING"] = True
        return app.test_client()

    def test_the_check_counts_every_flagged_row_of_the_latest_run(self):
        checks = {check.key: check for check in check_queries.index(self.connection())}
        self.assertEqual(checks["unit-disagreements"].count, 3)
        self.assertTrue(checks["unit-disagreements"].available)

    def test_the_two_kinds_are_told_apart(self):
        page = check_queries.unit_disagreements(self.connection())
        kinds = {row.source_uuid: row.kind for row in page.rows}
        self.assertEqual(
            kinds, {"u-km": "created", "u-kwh": "created", "u-matched": "matched"}
        )

    def test_the_row_nobody_has_decided_comes_first(self):
        """The only one asking for anything."""
        page = check_queries.unit_disagreements(self.connection())
        self.assertEqual(page.rows[0].source_uuid, "u-kwh")
        self.assertTrue(page.rows[0].needs_a_decision)
        self.assertFalse(any(row.needs_a_decision for row in page.rows[1:]))

    def test_a_row_says_what_it_and_its_flow_measure(self):
        page = check_queries.unit_disagreements(self.connection())
        row = next(row for row in page.rows if row.source_uuid == "u-km")
        self.assertEqual(row.source_unit, "km")
        self.assertEqual(row.target_unit, "m")
        self.assertEqual(row.offered_units, ["km", "m"])
        self.assertEqual(row.target_name, "Noise, Road, Lorry, Average")

    def test_search_filters_in_sql(self):
        page = check_queries.unit_disagreements(self.connection(), query="noise")
        self.assertEqual([row.source_uuid for row in page.rows], ["u-km"])

    def test_the_route_renders(self):
        response = self.client().get("/checks/unit-disagreements")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Unit disagreements", response.data)
        self.assertIn(b"needs a decision", response.data)


if __name__ == "__main__":
    unittest.main()
