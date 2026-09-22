"""The evaluator, against a fixture database small enough to read.

Every case here is a shape the real build produces, reduced to the two or three
rows that make it: rows that tie, rows that mint a substance of their own, a
catch-all several names collapse onto, a flow published twenty times in one
context.  The numbers are not the real ones -- the point is the grading, and a
fixture with 95,000 flows in it would not be a test.

The last test in the file is the one that keeps the rest honest: it reads the
real schema out of the modules that write it and checks that every column the
assessment queries is still there.  A fixture agrees with whatever the fixture
declares, so without that check a column renamed in `merge/store.py` would leave
these tests passing and `assess` broken on the only database anybody runs it
against.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from brightway_flows.assessment import assess, load_expectations
from brightway_flows.assessment.evaluate import Status
from brightway_flows.assessment.expectations import Expectation
from brightway_flows.assessment.measures import Direction
from brightway_flows.domain.vocabulary import (
    CHEMINF_CAS_REGISTRY_NUMBER,
    RDFS_LABEL_CURIE,
    RO_HAS_ROLE_IRI,
)

RUN = "run-1"

FIXTURE_SCHEMA = (
    """CREATE TABLE pipeline_runs (run_id TEXT PRIMARY KEY, timestamp TEXT NOT NULL,
       schema_version INTEGER NOT NULL, dry_run INTEGER NOT NULL DEFAULT 0,
       max_flows INTEGER, input_files_json TEXT NOT NULL DEFAULT '[]',
       transformer_names_json TEXT NOT NULL DEFAULT '[]',
       flow_count INTEGER NOT NULL DEFAULT 0, change_count INTEGER NOT NULL DEFAULT 0)""",
    """CREATE TABLE run_stats (stage TEXT NOT NULL, key TEXT NOT NULL,
       value INTEGER NOT NULL, PRIMARY KEY (stage, key))""",
    """CREATE TABLE review_queue (queue_name TEXT NOT NULL, item_key TEXT NOT NULL,
       item_index INTEGER NOT NULL DEFAULT 0, title TEXT NOT NULL DEFAULT '',
       severity TEXT NOT NULL DEFAULT 'info',
       elementary_flow_uuid TEXT NOT NULL DEFAULT '',
       flow_object_id TEXT NOT NULL DEFAULT '', cas TEXT NOT NULL DEFAULT '',
       payload_json TEXT NOT NULL DEFAULT '{}', PRIMARY KEY (queue_name, item_key))""",
    """CREATE TABLE merge_runs (run_id TEXT PRIMARY KEY, started_at TEXT NOT NULL,
       finished_at TEXT, schema_version INTEGER NOT NULL, stats_json TEXT)""",
    """CREATE TABLE merge_run_inputs (run_id TEXT NOT NULL, list_name TEXT NOT NULL,
       list_version TEXT NOT NULL, sequence INTEGER NOT NULL, source_path TEXT,
       prepared_match_table TEXT, row_count INTEGER NOT NULL DEFAULT 0,
       PRIMARY KEY (run_id, list_name, list_version))""",
    """CREATE TABLE merge_outcomes (run_id TEXT NOT NULL, list_name TEXT NOT NULL,
       list_version TEXT NOT NULL, source_uuid TEXT NOT NULL, outcome TEXT NOT NULL,
       source_name TEXT, source_context_json TEXT, source_unit TEXT, source_cas TEXT,
       source_ec TEXT, reason TEXT, flow_object_id TEXT,
       target_elementary_flow_id TEXT, basis TEXT, basis_value TEXT,
       matching_method TEXT, has_flow_object_candidates INTEGER,
       has_context_inconsistency INTEGER NOT NULL DEFAULT 0,
       has_unit_mismatch INTEGER NOT NULL DEFAULT 0, detail_json TEXT,
       PRIMARY KEY (run_id, list_name, list_version, source_uuid))""",
    """CREATE TABLE merge_conflicts (run_id TEXT NOT NULL,
       target_elementary_flow_id TEXT NOT NULL, kind TEXT NOT NULL,
       claimants_json TEXT NOT NULL)""",
    """CREATE TABLE flow_objects (flow_object_id TEXT PRIMARY KEY, pref_label_value TEXT,
       pref_label_json TEXT, alt_label_json TEXT, classifications_json TEXT,
       properties_json TEXT, references_json TEXT, flow_object_json TEXT,
       origin_qualifier TEXT, parent_flow_object_id TEXT, parent_intervention_id TEXT,
       flow_type TEXT NOT NULL DEFAULT 'unclassified')""",
    """CREATE TABLE elementary_flows (uuid TEXT PRIMARY KEY, flow_object_id TEXT,
       pref_label_value TEXT, source TEXT, unit TEXT,
       lcia_factor_count INTEGER NOT NULL DEFAULT 0,
       is_deprecated INTEGER NOT NULL DEFAULT 0, replaced_by_uuid TEXT,
       context_display TEXT, context_iri TEXT, context_json TEXT,
       context_dimension TEXT, context_media TEXT, context_strata TEXT,
       context_indoor TEXT, context_population_density TEXT, context_geography TEXT,
       context_water_body TEXT, context_land_use TEXT,
       consensus_change_count INTEGER NOT NULL DEFAULT 0, flow_json TEXT)""",
    """CREATE TABLE flow_object_payloads (flow_object_id TEXT PRIMARY KEY,
       payload_json TEXT)""",
    # `characterise` writes this, not `build`, and what it counted about itself
    # arrives as the `factors.*` measure family. Here so that an expectation
    # naming one of them is checked for typos like every other key: a build with
    # no characterisation behind it produces the family not at all, and a
    # misspelling in it would read as a stale expectation forever.
    """CREATE TABLE lcia_runs (run_id TEXT PRIMARY KEY, started_at TEXT NOT NULL,
       finished_at TEXT, build_run_id TEXT, stats_json TEXT)""",
)


def _cas(*numbers: str) -> str:
    return json.dumps({CHEMINF_CAS_REGISTRY_NUMBER: {"@value": list(numbers)}})


def _roles(*labels: str) -> str:
    """A serialised flow object publishing *labels* as `RO:0000087` roles.

    Written the way the record serialises it -- under the full predicate IRI,
    with `rdfs:label` on each entry -- because that is what the evaluator has to
    read, and a fixture that used a friendlier shape would test nothing.
    """
    return json.dumps({
        RO_HAS_ROLE_IRI: [
            {"@id": f"http://purl.obolibrary.org/obo/CHEBI_{index}",
             RDFS_LABEL_CURIE: label}
            for index, label in enumerate(labels)
        ]
    })


def build_fixture(path: Path) -> None:
    """A database with one of each shape the real build produces."""
    connection = sqlite3.connect(path)
    for statement in FIXTURE_SCHEMA:
        connection.execute(statement)

    connection.execute(
        "INSERT INTO pipeline_runs (run_id, timestamp, schema_version, flow_count) "
        "VALUES ('pipe-1', '2026-08-14T12:00:00+00:00', 1, 6)"
    )
    connection.execute(
        "INSERT INTO merge_runs (run_id, started_at, finished_at, schema_version) "
        "VALUES (?, '2026-08-14T12:00:00+00:00', '2026-08-14T12:30:00+00:00', 1)",
        (RUN,),
    )
    connection.execute(
        "INSERT INTO merge_run_inputs (run_id, list_name, list_version, sequence, row_count) "
        "VALUES (?, 'bafu', '2026-v1', 0, 5)",
        (RUN,),
    )
    connection.execute(
        "INSERT INTO run_stats (stage, key, value) VALUES ('merge_collisions', 'minted', 3)"
    )
    connection.executemany(
        "INSERT INTO review_queue (queue_name, item_key) VALUES (?, ?)",
        [("contested-cas", "a"), ("contested-cas", "b")],
    )
    connection.execute(
        "INSERT INTO lcia_runs (run_id, started_at, finished_at, build_run_id, "
        "stats_json) VALUES ('lcia-1', '2026-08-17T12:00:00+00:00', "
        "'2026-08-17T12:05:00+00:00', 'pipe-1', ?)",
        (json.dumps({"consensus_contradicted-factor_factors": 988}),),
    )

    connection.executemany(
        "INSERT INTO flow_objects (flow_object_id, pref_label_value, "
        "classifications_json, flow_object_json) VALUES (?, ?, ?, ?)",
        [
            ("fo-water", "Water", _cas("7732-18-5"), "{}"),
            ("fo-lake", "Lake Water", _cas("7732-18-5"), "{}"),
            ("fo-silver-m", "Silver-110m", _cas("14391-76-7"), "{}"),
            ("fo-silver", "Silver-110", "{}", "{}"),
            # The one object carrying alternative labels, because `alt_label`
            # is read out of `alt_label_json` and every other object here has
            # none.  One of the two is the part number EF 3.1 published the
            # substance under before it was renamed.
            ("fo-hexafluoroethane", "Hexafluoroethane", _cas("76-16-4"), "{}"),
            # The one object carrying a role, because `roles` is read out of the
            # serialised record and not out of a column.
            ("fo-herbicides", "Herbicides, Unspecified", "{}", _roles("herbicide")),
        ],
    )
    connection.execute(
        "UPDATE flow_objects SET alt_label_json = ? WHERE flow_object_id = ?",
        (
            json.dumps([
                {"@value": "HFC-116", "@language": "en"},
                {"@value": "Perfluoroethane", "@language": "en"},
            ]),
            "fo-hexafluoroethane",
        ),
    )
    connection.executemany(
        "INSERT INTO flow_object_payloads (flow_object_id, payload_json) VALUES (?, '{}')",
        [("fo-water",), ("fo-lake",), ("fo-silver-m",), ("fo-herbicides",)],
    )
    connection.executemany(
        "INSERT INTO elementary_flows (uuid, flow_object_id, unit, lcia_factor_count, "
        "is_deprecated, replaced_by_uuid, context_display, context_iri) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("ef-water-river", "fo-water", "m3", 2, 0, "", "Water → River", "iri:river"),
            ("ef-lake", "fo-lake", "m3", 0, 0, "", "Water → Lake", "iri:lake"),
            ("ef-silver-m", "fo-silver-m", "Bq", 1, 0, "", "Water → River", "iri:river"),
            ("ef-silver-air", "fo-silver", "Bq", 0, 0, "", "Air → Rural", "iri:air"),
            # One characterised catch-all and two empty copies of it, in one
            # context: the shape #60 records, reduced to three rows.
            ("ef-herb-1", "fo-herbicides", "kg", 4, 0, "", "Ground → Agricultural", "iri:ag"),
            ("ef-herb-2", "fo-herbicides", "kg", 0, 0, "", "Ground → Agricultural", "iri:ag"),
            ("ef-herb-3", "fo-herbicides", "kg", 0, 0, "", "Ground → Agricultural", "iri:ag"),
            # Deprecated, and pointed at its replacement.
            ("ef-old", "fo-water", "m3", 0, 1, "ef-water-river", "Water → River", "iri:river"),
        ],
    )

    tie_detail = json.dumps({
        "algorithm_details": {
            "elementary_candidate_count": 2,
            "selector_model": "score=(2*unit_exact)+context_overlap",
            "top_candidates": [
                {"elementary_flow_id": "ef-water-river", "score": 3, "unit": "m3",
                 "context": ["Water", "River"]},
                {"elementary_flow_id": "ef-lake", "score": 3, "unit": "m3",
                 "context": ["Water", "Lake"]},
            ],
        },
    })
    connection.executemany(
        "INSERT INTO merge_outcomes (run_id, list_name, list_version, source_uuid, outcome, "
        "source_name, source_context_json, source_unit, source_cas, reason, flow_object_id, "
        "target_elementary_flow_id, basis, matching_method, has_unit_mismatch, "
        "has_context_inconsistency, detail_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            # Two rows named `Water`, both refused on a tie.
            (RUN, "bafu", "2026-v1", "u-water-1", "unmatched", "Water",
             '["emissions to water","river"]', "m3", "7732-18-5",
             "multiple-flow-object-candidates", "", "", "", "algorithm", 0, 0, tie_detail),
            (RUN, "bafu", "2026-v1", "u-water-2", "unmatched", "Water",
             '["emissions to water","ocean"]', "m3", "7732-18-5",
             "multiple-flow-object-candidates", "", "", "", "algorithm", 0, 0, tie_detail),
            # One source name read two ways: one row matches the metastable
            # nuclide, the other mints a substance of its own.
            (RUN, "bafu", "2026-v1", "u-silver-1", "algorithm", "Silver-110",
             '["emissions to water","river"]', "Bq", "", "", "fo-silver-m",
             "ef-silver-m", "cas", "algorithm", 0, 0, "{}"),
            (RUN, "bafu", "2026-v1", "u-silver-2", "created", "Silver-110",
             '["emissions to air","low. pop."]', "Bq", "", "", "fo-silver",
             "ef-silver-air", "", "flow_object_creation", 0, 0, "{}"),
            # A named substance routed to a catch-all, in a unit the flow does
            # not declare.
            (RUN, "bafu", "2026-v1", "u-chlorfenapyr", "prepared", "Chlorfenapyr",
             '["emissions to soil","agricultural"]', "g", "122453-73-0", "",
             "fo-herbicides", "ef-herb-1", "", "prepared", 1, 1, "{}"),
        ],
    )
    connection.commit()
    connection.close()


def expectation(identifier: str, kind: str, selector: dict, claims: dict, **kwargs) -> Expectation:
    return Expectation(
        id=identifier,
        title=f"{identifier} holds",
        kind=kind,
        selector=selector,
        claims=claims,
        **kwargs,
    )


class AssessmentTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.database = Path(cls._tmp.name) / "fixture.sqlite3"
        build_fixture(cls.database)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def grade(self, *expectations: Expectation):
        return assess(self.database, expectations=expectations).results

    # -- statuses ---------------------------------------------------------

    def test_a_holding_claim_is_met(self):
        (result,) = self.grade(expectation(
            "e", "source_row", {"list": "bafu", "name": "Water"}, {"outcome": "unmatched"},
        ))
        self.assertIs(result.status, Status.MET)
        self.assertEqual(result.matched_rows, 2)
        self.assertEqual(result.evidence, (), "a met expectation carries no evidence")

    def test_a_failing_claim_is_unmet_and_says_what_happened(self):
        (result,) = self.grade(expectation(
            "e", "source_row", {"list": "bafu", "name": "Water"},
            {"outcome": "matched", "target_name": "Water"},
        ))
        self.assertIs(result.status, Status.UNMET)
        claims = {claim.claim: claim for claim in result.claims}
        self.assertFalse(claims["outcome"].met)
        self.assertEqual(claims["outcome"].actual, {"unmatched": 2})

    def test_a_selector_that_matches_nothing_is_unresolved_not_unmet(self):
        """The distinction the whole status vocabulary exists for."""
        (result,) = self.grade(expectation(
            "e", "source_row", {"list": "bafu", "name": "Nothing By This Name"},
            {"outcome": "matched"},
        ))
        self.assertIs(result.status, Status.UNRESOLVED)
        self.assertIn("nothing in this build matches", result.message)

    def test_a_missing_table_is_an_error_not_a_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            empty = Path(tmp) / "empty.sqlite3"
            sqlite3.connect(empty).close()
            results = assess(empty, expectations=(expectation(
                "e", "source_row", {"list": "bafu"}, {"outcome": "matched"},
            ),)).results
        self.assertIs(results[0].status, Status.ERROR)
        self.assertIn("merge_outcomes", results[0].message)

    def test_a_missing_database_says_what_to_run(self):
        with self.assertRaises(FileNotFoundError) as caught:
            assess(Path("/nonexistent/consensus-flows.sqlite3"), expectations=())
        self.assertIn("build", str(caught.exception))

    # -- claims -----------------------------------------------------------

    def test_the_evidence_carries_the_candidates_the_selector_scored(self):
        """The half of a failure that a reader can act on."""
        (result,) = self.grade(expectation(
            "e", "source_row", {"list": "bafu", "name": "Water"}, {"outcome": "matched"},
        ))
        candidates = result.evidence[0]["scored_candidates"]
        self.assertEqual(len(candidates), 2)
        self.assertEqual({c["score"] for c in candidates}, {3})
        self.assertEqual(
            {c["elementary_flow_id"] for c in candidates}, {"ef-water-river", "ef-lake"}
        )

    def test_outcome_aliases_cover_the_ways_a_row_can_land(self):
        rows = {"list": "bafu", "name": "Silver-110"}
        met, unmet = self.grade(
            expectation("a", "source_row", rows, {"outcome": "placed"}),
            expectation("b", "source_row", rows, {"outcome": "matched"}),
        )
        self.assertIs(met.status, Status.MET, "one matched and one was created")
        self.assertIs(unmet.status, Status.UNMET, "one of the two was created")

    def test_not_outcome_negates(self):
        (result,) = self.grade(expectation(
            "e", "source_row", {"list": "bafu", "name": "Silver-110"},
            {"not_outcome": "created"},
        ))
        self.assertIs(result.status, Status.UNMET)

    def test_same_target_and_same_substance_are_different_questions(self):
        """Four rows in four contexts reach four flows, correctly, and may
        still reach two substances, which is the defect."""
        rows = {"list": "bafu", "name": "Silver-110"}
        by_flow, by_substance = self.grade(
            expectation("a", "source_row", rows, {"distinct_targets": True}),
            expectation("b", "source_row", rows, {"same_substance": True}),
        )
        self.assertIs(by_flow.status, Status.MET, "two rows, two flows: not fused")
        self.assertIs(by_substance.status, Status.UNMET, "but two substances")
        self.assertEqual(by_substance.claims[0].note, "2 distinct substances")

    def test_a_row_that_reached_nothing_is_reported_as_such(self):
        (result,) = self.grade(expectation(
            "e", "source_row", {"list": "bafu", "name": "Water"}, {"same_substance": True},
        ))
        self.assertIn("reached none", result.claims[0].note)

    def test_the_flow_selector_counts_the_published_list(self):
        (result,) = self.grade(expectation(
            "e", "flow",
            {"name": "Herbicides, Unspecified", "context_display": "Ground → Agricultural"},
            {"count": 1},
        ))
        self.assertIs(result.status, Status.UNMET)
        self.assertEqual(result.claims[0].actual, 3)

    def test_a_deprecated_flow_is_left_out_unless_asked_for(self):
        """A successful deduplication would otherwise look like it changed
        nothing, because the row it deprecated is still in the table."""
        active, everything = self.grade(
            expectation("a", "flow", {"name": "Water"}, {"count": 1}),
            expectation("b", "flow", {"name": "Water", "include_deprecated": True}, {"count": 2}),
        )
        self.assertIs(active.status, Status.MET)
        self.assertIs(everything.status, Status.MET)

    def test_a_substance_is_selected_by_its_published_registry_number(self):
        (result,) = self.grade(expectation(
            "e", "substance", {"cas": "7732-18-5"}, {"count": 2},
        ))
        self.assertIs(result.status, Status.MET)

    def test_a_cas_selector_does_not_match_a_number_that_merely_contains_it(self):
        """The `LIKE` that narrows the query would; the confirmation in Python
        is what stops a wrong substance passing a CAS claim."""
        (result,) = self.grade(expectation(
            "e", "substance", {"cas": "732-18-5"}, {"exists": False},
        ))
        self.assertIs(result.status, Status.MET)

    def test_absence_is_an_answer_rather_than_an_unresolved_subject(self):
        (result,) = self.grade(expectation(
            "e", "flow", {"name": "Not A Flow"}, {"exists": False},
        ))
        self.assertIs(result.status, Status.MET)

    def test_a_substance_can_be_asked_what_it_is_used_for(self):
        """What a substance *is* and what it is *for* are two questions, and
        until #269 the list could only answer the first.  An expectation about
        #206 or #76 is a claim about the second: a named pesticide published as
        itself is only an improvement if it still says which class it belongs
        to, because that is what a consumer reads to find a factor."""
        (result,) = self.grade(expectation(
            "e", "substance", {"label": "Herbicides, Unspecified"},
            {"roles": "herbicide"},
        ))
        self.assertIs(result.status, Status.MET)

    def test_a_role_the_substance_does_not_publish_is_unmet(self):
        """And the report says which roles it does publish, so the answer to
        "why not" is in the failure rather than in a second query."""
        (result,) = self.grade(expectation(
            "e", "substance", {"label": "Herbicides, Unspecified"},
            {"roles": "insecticide"},
        ))
        self.assertIs(result.status, Status.UNMET)
        self.assertEqual(result.claims[0].actual, ["herbicide"])

    def test_a_substance_with_no_roles_is_unmet_rather_than_unresolved(self):
        """The subject is there; it simply says nothing about what it is for.
        Reporting that as `unresolved` would read as "this substance has gone
        away", which is the diagnosis `evaluate` is at pains to keep separate."""
        (result,) = self.grade(expectation(
            "e", "substance", {"label": "Silver-110"}, {"roles": "insecticide"},
        ))
        self.assertIs(result.status, Status.UNMET)

    def test_a_substance_can_be_asked_what_else_it_is_called(self):
        """Half of a rename is that the old name goes on finding the substance,
        and until #104 that half could not be claimed at all.  `HFC-134a` is the
        only string an inventory written against EF 3.1 holds for the
        refrigerant, so `label` alone reports a rename as done while the string
        a user searches by has been dropped."""
        (result,) = self.grade(expectation(
            "e", "substance", {"cas": "76-16-4"}, {"alt_label": "HFC-116"},
        ))
        self.assertIs(result.status, Status.MET)

    def test_the_source_s_own_spelling_is_matched_without_regard_to_case(self):
        """EF 3.1 ships one substance's name as both `HFC-23` and `hfc-23`, so
        an expectation pinned to one spelling would fail on the release that
        shipped the other.  Unlike `roles`, which is a vocabulary term."""
        (result,) = self.grade(expectation(
            "e", "substance", {"cas": "76-16-4"}, {"alt_label": "hfc-116"},
        ))
        self.assertIs(result.status, Status.MET)

    def test_a_label_the_substance_does_not_carry_is_unmet(self):
        (result,) = self.grade(expectation(
            "e", "substance", {"cas": "76-16-4"}, {"alt_label": "PFC-116"},
        ))
        self.assertIs(result.status, Status.UNMET)
        self.assertEqual(result.claims[0].actual, ["HFC-116", "Perfluoroethane"])

    def test_a_substance_with_no_alternative_labels_is_unmet_not_unresolved(self):
        (result,) = self.grade(expectation(
            "e", "substance", {"label": "Silver-110"}, {"alt_label": "Silver-110m"},
        ))
        self.assertIs(result.status, Status.UNMET)

    def test_a_bound_reads_the_same_on_a_row_as_on_a_set(self):
        (result,) = self.grade(expectation(
            "e", "substance", {"cas": "7732-18-5"}, {"flow_count": {"at_least": 1}},
        ))
        self.assertIs(result.status, Status.MET)

    def test_a_measure_claim_compares_the_number(self):
        met, unmet = self.grade(
            expectation("a", "measure", {"key": "flows.deprecated"}, {"equals": 1}),
            expectation("b", "measure", {"key": "flows.deprecated"}, {"at_most": 0}),
        )
        self.assertIs(met.status, Status.MET)
        self.assertIs(unmet.status, Status.UNMET)
        self.assertEqual(unmet.claims[0].actual, 1)

    def test_an_unknown_measure_is_unresolved(self):
        (result,) = self.grade(expectation(
            "e", "measure", {"key": "flows.nonesuch"}, {"at_most": 0},
        ))
        self.assertIs(result.status, Status.UNRESOLVED)

    def test_a_claim_holds_only_if_every_matched_row_satisfies_it(self):
        (result,) = self.grade(expectation(
            "e", "source_row", {"list": "bafu"}, {"unit_mismatch": False},
        ))
        self.assertIs(result.status, Status.UNMET)
        self.assertEqual(result.claims[0].note, "1 of 5 rows")

    def test_the_measures_are_collected_once_however_many_expectations_read_them(self):
        """`_resolve_measure` used to collect the whole registry itself.

        Six measure expectations therefore ran it seven times -- 0.40s each
        against the real 1.8 GB build, 2.4s of it repeated, and growing with
        every measure expectation added.
        """
        import brightway_flows.assessment.evaluate as evaluate

        calls = 0
        real = evaluate.collect_measures

        def counting(connection, **kwargs):
            nonlocal calls
            calls += 1
            return real(connection, **kwargs)

        with unittest.mock.patch.object(evaluate, "collect_measures", counting):
            assess(self.database, expectations=tuple(
                expectation(str(i), "measure", {"key": "flows.total"}, {"at_least": 1})
                for i in range(6)
            ))
        self.assertEqual(calls, 1)

    def test_a_vanished_measure_reads_as_its_stated_absent_value(self):
        """`value_when_absent` keeps an `at_most: 0` claim alive at zero.

        The stats tables write no row for nothing, so the moment a bounded
        count reaches zero its key vanishes and the claim it anchored turned
        unresolved -- which is how #118's factor-collision bound was lost
        (found by review on #336).  With the value stated, absence is the
        number it means; without it, absence stays "the subject went
        missing", both halves pinned here.
        """
        (result,) = assess(self.database, expectations=(
            expectation(
                "gone",
                "measure",
                {"key": "no.such.measure", "value_when_absent": 0},
                {"at_most": 0},
            ),
        )).results
        self.assertIs(result.status, Status.MET)
        (result,) = assess(self.database, expectations=(
            expectation(
                "gone", "measure", {"key": "no.such.measure"}, {"at_most": 0},
            ),
        )).results
        self.assertIs(result.status, Status.UNRESOLVED)

    def test_an_unrecognised_bound_fails_closed(self):
        """The loader rejects `{"at_mst": 3}` now, so this is unreachable from a
        file. It is pinned anyway: the version that returned `True` here is what
        let a misspelled bound report **met**, and a reader of `_within_bound`
        should not have to check the loader to know which way it fails.
        """
        from brightway_flows.assessment.evaluate import _within_bound

        self.assertFalse(_within_bound({"at_mst": 3}, 1))
        self.assertFalse(_within_bound({}, 1))
        self.assertTrue(_within_bound({"at_most": 3}, 1))

    # -- pending ----------------------------------------------------------

    def test_a_pending_expectation_is_graded_but_does_not_fail_the_run(self):
        assessment = assess(self.database, expectations=(
            expectation("a", "source_row", {"list": "bafu", "name": "Water"},
                        {"outcome": "matched"}, pending=True),
            expectation("b", "source_row", {"list": "bafu", "name": "Water"},
                        {"outcome": "matched"}),
        ))
        self.assertEqual(assessment.counts["unmet"], 2)
        self.assertEqual([r.expectation.id for r in assessment.failures], ["b"])

    # -- measures ---------------------------------------------------------

    def test_the_measures_describe_the_build(self):
        measures = assess(self.database, expectations=()).measures
        self.assertEqual(measures["flows.total"].value, 8)
        self.assertEqual(measures["flows.deprecated"].value, 1)
        self.assertEqual(measures["flows.deprecated_without_replacement"].value, 0)
        self.assertEqual(measures["substances.total"].value, 6)
        self.assertEqual(measures["substances.without_payload"].value, 2)
        self.assertEqual(measures["merge.bafu-2026-v1.rows"].value, 5)
        self.assertEqual(measures["merge.bafu-2026-v1.unmatched"].value, 2)
        self.assertEqual(measures["merge.bafu-2026-v1.on_existing_flow"].value, 2)
        self.assertEqual(measures["merge.bafu-2026-v1.unit_mismatch"].value, 1)
        self.assertEqual(measures["queue.contested-cas"].value, 2)
        # From `lcia_runs.stats_json`, which `characterise` wrote and `build` did
        # not: what a run counted about itself is a measure like any other.
        self.assertEqual(
            measures["factors.consensus_contradicted-factor_factors"].value, 988
        )

    def test_the_pipeline_counters_are_folded_in_rather_than_restated(self):
        """`run_stats` exists to be asked run over run; this is what asks it."""
        measures = assess(self.database, expectations=()).measures
        self.assertEqual(measures["stats.merge_collisions.minted"].value, 3)

    def test_a_direction_is_only_claimed_where_it_is_unambiguous(self):
        """`created` going down is not progress -- a genuinely new substance
        should mint a flow -- so it carries no direction and the report says
        `moved` rather than passing a judgement nobody made."""
        measures = assess(self.database, expectations=()).measures
        self.assertIs(measures["merge.bafu-2026-v1.unmatched"].direction, Direction.LOWER)
        self.assertIs(measures["merge.bafu-2026-v1.created"].direction, Direction.NEUTRAL)
        self.assertIs(measures["merge.bafu-2026-v1.on_existing_flow"].direction, Direction.HIGHER)


class BaselineTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.database = Path(cls._tmp.name) / "fixture.sqlite3"
        build_fixture(cls.database)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_a_recorded_baseline_reports_what_moved_and_which_way(self):
        from brightway_flows.assessment import (
            compare_to_baseline,
            load_baseline,
            write_baseline,
        )

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            first = assess(self.database, expectations=(
                expectation("a", "measure", {"key": "flows.deprecated"}, {"at_most": 0}),
            ))
            write_baseline(first, directory=directory)

            # Pretend the next build placed one more row and left one fewer
            # unmatched, by rewriting what was recorded.
            baseline = load_baseline(directory)
            doctored = dict(baseline.measures)
            doctored["merge.bafu-2026-v1.unmatched"] = 5
            doctored["merge.bafu-2026-v1.created"] = 0
            comparison = compare_to_baseline(
                first, baseline=type(baseline)(
                    measures=doctored, statuses={"a": "met"}, recorded=baseline.recorded,
                ),
            )

        moved = {delta.key: delta.verdict for delta in comparison.measures}
        self.assertEqual(moved["merge.bafu-2026-v1.unmatched"], "improved")
        self.assertEqual(moved["merge.bafu-2026-v1.created"], "moved")
        self.assertEqual(
            [(c.expectation_id, c.verdict) for c in comparison.statuses], [("a", "regressed")]
        )

    def test_a_baseline_from_a_different_source_set_is_not_comparable(self):
        """`build` merges nothing unless asked (#99), so two runs of the same
        pipeline with different `--source` lists produce the same shape of
        result and mean different things. Compared, every `merge.*` measure of
        a list only one of them merged reports as gone -- a catastrophic
        regression that is only a different flag.
        """
        from brightway_flows.assessment import compare_to_baseline
        from brightway_flows.assessment.baseline import Baseline

        assessment = assess(self.database, expectations=())
        self.assertEqual(assessment.run.sources, ("bafu-2026-v1",))
        comparison = compare_to_baseline(assessment, baseline=Baseline(
            measures={"flows.total": 8},
            recorded={"sources": ["ecoinvent-3.12", "bafu-2026-v1"]},
        ))
        self.assertIn("ecoinvent-3.12", comparison.incomparable)
        self.assertEqual(comparison.measures, ())

    def test_the_same_source_set_still_compares(self):
        from brightway_flows.assessment import compare_to_baseline
        from brightway_flows.assessment.baseline import Baseline

        assessment = assess(self.database, expectations=())
        comparison = compare_to_baseline(assessment, baseline=Baseline(
            measures={"flows.total": 1},
            recorded={"sources": ["bafu-2026-v1"]},
        ))
        self.assertEqual(comparison.incomparable, "")
        # Every other measure reads as `new`, because this baseline records only
        # one; what matters is that the comparison ran at all.
        moved = {delta.key: delta.verdict for delta in comparison.measures}
        self.assertEqual(moved["flows.total"], "moved")

    def test_a_bounded_run_is_never_recorded_as_a_baseline(self):
        """It measures a prefix of the base list; recorded, it would report
        every count as collapsed on the next full build."""
        from brightway_flows.assessment.baseline import BaselineError, write_baseline

        connection = sqlite3.connect(self.database)
        connection.execute("UPDATE pipeline_runs SET max_flows = 100")
        connection.commit()
        connection.close()
        try:
            assessment = assess(self.database, expectations=())
            with tempfile.TemporaryDirectory() as tmp:
                with self.assertRaises(BaselineError):
                    write_baseline(assessment, directory=Path(tmp))
                comparison = None
                from brightway_flows.assessment import compare_to_baseline
                from brightway_flows.assessment.baseline import Baseline

                comparison = compare_to_baseline(
                    assessment, baseline=Baseline(measures={"flows.total": 1})
                )
            self.assertIn("bounded", comparison.incomparable)
        finally:
            connection = sqlite3.connect(self.database)
            connection.execute("UPDATE pipeline_runs SET max_flows = NULL")
            connection.commit()
            connection.close()

    def test_no_baseline_is_not_an_error(self):
        from brightway_flows.assessment import compare_to_baseline

        with tempfile.TemporaryDirectory() as tmp:
            comparison = compare_to_baseline(
                assess(self.database, expectations=()), directory=Path(tmp)
            )
        self.assertIn("no baseline recorded", comparison.incomparable)


class ReportTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.database = Path(cls._tmp.name) / "fixture.sqlite3"
        build_fixture(cls.database)
        cls.assessment = assess(cls.database, expectations=(
            expectation("a", "source_row", {"list": "bafu", "name": "Water"},
                        {"outcome": "matched"}),
            expectation("b", "measure", {"key": "flows.total"}, {"at_least": 1}),
        ))

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_the_terminal_report_leads_with_what_failed(self):
        from brightway_flows.assessment.report import terminal_lines

        text = "\n".join(terminal_lines(self.assessment))
        self.assertIn("WHERE EACH LIST LANDS", text)
        self.assertIn("bafu-2026-v1", text)
        self.assertIn("a holds", text)
        self.assertNotIn("b holds", text, "a met expectation is not listed without --verbose")
        self.assertIn("b holds", "\n".join(terminal_lines(self.assessment, verbose=True)))

    def test_every_merged_list_reaches_the_placement_table(self):
        """A version string contains a dot, so a key split on dots finds
        `ecoinvent-3` and drops the list; the table reads the run instead."""
        from brightway_flows.assessment.report import terminal_lines

        lines = [line for line in terminal_lines(self.assessment) if "2026-v1" in line]
        self.assertTrue(any(line.strip().startswith("bafu-2026-v1") for line in lines))

    def test_the_json_report_is_stable_and_complete(self):
        from brightway_flows.assessment.report import as_json

        payload = json.loads(as_json(self.assessment))
        self.assertEqual(len(payload["expectations"]), 2)
        self.assertEqual(payload["counts"]["unmet"], 1)
        self.assertIn("flows.total", payload["measures"])
        self.assertEqual(as_json(self.assessment), as_json(self.assessment))

    def test_the_html_report_is_self_contained(self):
        from brightway_flows.assessment.report import as_html

        page = as_html(self.assessment)
        self.assertIn("<title>", page)
        for forbidden in ("<html", "<body", "http://", "https://"):
            self.assertNotIn(forbidden, page, f"{forbidden} would break the artifact sandbox")
        self.assertIn("prefers-color-scheme", page)


class SchemaAgreementTestCase(unittest.TestCase):
    """The fixture agrees with itself; this checks it agrees with the build.

    Without it, a column renamed in `merge/store.py` leaves every test above
    passing and `assess` broken against the only database anybody runs it on.
    """

    def test_the_columns_the_assessment_reads_are_the_ones_the_merge_writes(self):
        from brightway_flows.merge.store import SCHEMA

        ddl = " ".join(SCHEMA)
        for column in (
            "run_id", "list_name", "list_version", "source_uuid", "outcome",
            "source_name", "source_context_json", "source_unit", "source_cas",
            "reason", "flow_object_id", "target_elementary_flow_id", "basis",
            "basis_value", "matching_method", "has_context_inconsistency",
            "has_unit_mismatch", "detail_json",
        ):
            with self.subTest(column):
                self.assertIn(column, ddl)

    def test_the_columns_the_assessment_reads_are_the_ones_the_pipeline_writes(self):
        import brightway_flows.pipeline.sqlite as pipeline_sqlite

        source = Path(pipeline_sqlite.__file__).read_text()
        for column in (
            "lcia_factor_count", "is_deprecated", "replaced_by_uuid",
            "context_display", "context_iri", "pref_label_value",
            "classifications_json", "flow_object_id",
        ):
            with self.subTest(column):
                self.assertIn(column, source)

    def test_the_fixture_declares_no_column_the_real_schema_lacks(self):
        """The other direction: a fixture column that does not exist in the
        build would let a query pass here and fail there."""
        from brightway_flows.merge.store import SCHEMA

        real = " ".join(SCHEMA)
        fixture = next(s for s in FIXTURE_SCHEMA if "merge_outcomes" in s)
        body = fixture[fixture.index("(") + 1: fixture.rindex(")")]
        for part in body.split(","):
            name = part.split()[0].strip()
            if name.upper() == "PRIMARY":
                continue
            with self.subTest(name):
                self.assertIn(name, real)


class RepositoryExpectationsTestCase(unittest.TestCase):
    """The files this repository ships are answerable, not merely loadable."""

    def test_every_expectation_names_a_subject_the_evaluator_can_resolve(self):
        for expectation_ in load_expectations():
            with self.subTest(expectation_.id):
                self.assertIn(
                    expectation_.kind,
                    {"source_row", "flow", "substance", "factor", "measure"},
                )

    def test_every_measure_expectation_names_a_measure_this_build_produces(self):
        """A measure key with a typo resolves to nothing and reports as
        unresolved forever, which reads as a stale expectation rather than as
        the misspelling it is.
        """
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / "fixture.sqlite3"
            build_fixture(database)
            available = set(assess(database, expectations=()).measures)
        # The fixture merges one list; keys naming another list's placement are
        # real but not present here, so only the shape can be checked.
        prefixes = tuple(sorted({key.split(".")[0] for key in available}))
        for expectation_ in load_expectations():
            if expectation_.kind != "measure":
                continue
            key = expectation_.selector["key"]
            with self.subTest(expectation_.id):
                self.assertTrue(
                    key.startswith(prefixes),
                    f"{key} is not in any measure family this build produces: {prefixes}",
                )


if __name__ == "__main__":
    unittest.main()
