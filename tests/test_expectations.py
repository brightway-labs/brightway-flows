"""Every file in `expectations/` loads, and says something this build can check.

This is the cheap half of the assessment, and the half that runs in CI: it needs
no database, only the files.  It exists because the expensive half cannot run
without a 1.8 GB artifact that takes half an hour to produce, and an expectation
with a typo in it would otherwise sit in the repository looking like a check and
testing nothing until somebody ran a build.

What it does *not* do is grade anything.  `brightway-flows assess` does
that, against a real build; see `tests/test_assessment.py` for the evaluator's
own tests, which run against a fixture database built in the test.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from brightway_flows.assessment.expectations import (
    AGGREGATE_CLAIMS,
    BASELINE_FILENAME,
    EXPECTATIONS_DIR,
    OUTCOME_VALUES,
    SUBJECT_CLAIMS,
    SUBJECT_SELECTORS,
    ExpectationFileError,
    load_expectations,
)


class ExpectationFilesTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.expectations = load_expectations()

    def test_the_directory_is_there_and_documented(self):
        """A contributor is told what to write before they write it."""
        self.assertTrue(EXPECTATIONS_DIR.is_dir(), f"{EXPECTATIONS_DIR} is missing")
        self.assertTrue((EXPECTATIONS_DIR / "README.md").exists())

    def test_every_file_loads(self):
        """The whole point: a typo is a failure here, not a silent pass there.

        `load_expectations` validates against a closed list of subject kinds,
        selectors and claims, so `"target_unti"` raises rather than being
        dropped -- which would leave an expectation that passes on a build
        nobody checked the unit of.
        """
        self.assertTrue(self.expectations, "no expectations found")

    def test_ids_are_unique_and_stable_shaped(self):
        """The id is what the baseline records a status against."""
        ids = [expectation.id for expectation in self.expectations]
        self.assertEqual(len(ids), len(set(ids)))
        for identifier in ids:
            self.assertEqual(identifier, identifier.strip().lower())
            self.assertNotIn(" ", identifier)

    def test_every_expectation_says_what_should_be_true(self):
        """A title is what the report prints, so it has to be a sentence."""
        for expectation in self.expectations:
            with self.subTest(expectation.id):
                self.assertGreater(
                    len(expectation.title.split()), 3,
                    "a title has to read as the sentence that should be true",
                )

    def test_a_pending_expectation_explains_itself(self):
        """`pending` means "we know this is not true yet" -- say why."""
        for expectation in self.expectations:
            if expectation.pending:
                with self.subTest(expectation.id):
                    self.assertTrue(
                        expectation.comment,
                        "a pending expectation needs a comment saying what the "
                        "build does today, measured",
                    )

    def test_claims_are_ones_the_evaluator_implements(self):
        """The vocabulary and the code cannot drift apart unnoticed.

        Every claim named in `SUBJECT_CLAIMS` has to be reachable in
        `evaluate`: either an aggregate it handles by name, one of the two
        outcome claims, a measure bound, or a fact the resolver puts on a row.
        A claim declared and not implemented would load, evaluate as "this
        build records no such fact", and report as unmet forever.
        """
        from brightway_flows.assessment.evaluate import _FACT_FOR_CLAIM

        handled_by_name = AGGREGATE_CLAIMS | {
            "exists", "outcome", "not_outcome", "equals", "at_most", "at_least",
        }
        # The facts each resolver puts on a row, as the resolvers write them.
        facts = {
            "source_row": {
                "outcome", "reason", "basis", "target_uuid", "target_name",
                "target_unit", "target_context_iri", "target_context_display",
                "target_cas", "target_characterised", "target_deprecated",
                "target_substance_id", "unit_mismatch", "context_inconsistency",
                # Read from `elementary_flow_sources` rather than from
                # `merge_outcomes`: whether the decision reached the list, and
                # the factor the merge wrote for the row's pair.
                "published", "conversion_factor",
            },
            "flow": {
                "uuid", "name", "unit", "context_iri", "context_display",
                "characterised", "deprecated", "replaced_by", "substance_id",
                "substance_cas",
                # One per implementation of an LCIA method, from
                # `_factors_by_implementation`. `characterised` is still the
                # JRC's non-zero count, which is what `lcia_factor_count` holds.
                "jrc_factors", "ecoinvent_factors", "consensus_factors",
            },
            "substance": {
                "id", "label", "cas", "ec", "flow_count", "has_payload",
                "flow_type", "alt_label", "roles",
                "inchikey_count", "formula_count",
            },
            "factor": {
                "flow_uuid", "flow_name", "substance_cas", "context_display",
                "context_iri", "category", "implemented_by", "derivation",
                # The number itself, compared to the significant figures the
                # claim states rather than exactly -- see `AMOUNT_CLAIMS`.
                "amount",
            },
            "measure": {"key", "value"},
        }
        for kind, claims in SUBJECT_CLAIMS.items():
            for claim in claims:
                with self.subTest(kind=kind, claim=claim):
                    self.assertTrue(
                        claim in handled_by_name
                        or _FACT_FOR_CLAIM.get(claim, claim) in facts[kind],
                        f"{kind}.{claim} is declared but nothing evaluates it",
                    )

    def test_the_baseline_covers_every_expectation(self):
        """A recorded baseline that has lost an id cannot report its movement.

        Missing is allowed only for an expectation added since the baseline was
        recorded; a stale entry naming an expectation that no longer exists is
        also allowed, and is how a renamed id loses its history.  Both are
        reported here rather than failed, because the fix for either is to
        re-run `assess --record` against a full build, which cannot be done in
        a test.
        """
        path = EXPECTATIONS_DIR / BASELINE_FILENAME
        if not path.exists():
            self.skipTest("no baseline recorded yet")
        recorded = set(json.loads(path.read_text())["expectations"])
        current = {expectation.id for expectation in self.expectations}
        self.assertFalse(
            recorded - current,
            f"the baseline records ids no expectation defines: {sorted(recorded - current)}. "
            "Re-run `assess --record` after a full build.",
        )


class ExpectationValidationTestCase(unittest.TestCase):
    """The loader rejects what it should, message by message."""

    def _write(self, tmp: Path, payload: dict) -> Path:
        path = tmp / "0001-example.json"
        path.write_text(json.dumps(payload))
        return path

    def setUp(self) -> None:
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.directory = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.valid = {
            "schema_version": 1,
            "description": "example",
            "expectations": [{
                "id": "0001-example",
                "title": "The example row lands on the example flow",
                "subject": {"kind": "source_row", "list": "bafu", "name": "Water"},
                "expect": {"outcome": "matched"},
            }],
        }

    def test_a_valid_file_loads(self):
        self._write(self.directory, self.valid)
        loaded = load_expectations(self.directory)
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].kind, "source_row")
        self.assertEqual(loaded[0].source_file, "0001-example.json")

    def test_an_unknown_claim_is_rejected(self):
        """The failure mode this whole mechanism exists to prevent."""
        self.valid["expectations"][0]["expect"] = {"target_unti": "m3"}
        self._write(self.directory, self.valid)
        with self.assertRaises(ExpectationFileError) as caught:
            load_expectations(self.directory)
        self.assertIn("target_unti", str(caught.exception))

    def test_an_unknown_selector_is_rejected(self):
        self.valid["expectations"][0]["subject"]["nmae"] = "Water"
        self._write(self.directory, self.valid)
        with self.assertRaises(ExpectationFileError):
            load_expectations(self.directory)

    def test_an_unknown_subject_kind_is_rejected(self):
        self.valid["expectations"][0]["subject"] = {"kind": "flows", "uuid": "x"}
        self._write(self.directory, self.valid)
        with self.assertRaises(ExpectationFileError):
            load_expectations(self.directory)

    def test_a_misspelled_outcome_is_rejected_at_load(self):
        """Not at evaluation: an outcome nothing matches would resolve to zero
        rows and be reported as a subject that has left the build, which is the
        wrong diagnosis entirely.
        """
        self.valid["expectations"][0]["expect"] = {"outcome": "matchd"}
        self._write(self.directory, self.valid)
        with self.assertRaises(ExpectationFileError) as caught:
            load_expectations(self.directory)
        self.assertIn("matchd", str(caught.exception))
        for outcome in OUTCOME_VALUES:
            self.assertIn(outcome, str(caught.exception))

    def test_a_misspelled_bound_key_is_rejected(self):
        """The worst failure available, and the one that got through.

        `{"at_mst": 3}` loaded, reached a comparison that recognised none of its
        keys, and reported **met**. A misspelling that turns a check into a pass
        is indistinguishable from a check that holds.
        """
        self.valid["expectations"][0]["subject"] = {"kind": "flow", "name": "Water"}
        self.valid["expectations"][0]["expect"] = {"count": {"at_mst": 3}}
        self._write(self.directory, self.valid)
        with self.assertRaises(ExpectationFileError) as caught:
            load_expectations(self.directory)
        self.assertIn("at_mst", str(caught.exception))

    def test_a_bound_with_a_value_that_is_not_a_number_is_rejected(self):
        """It used to raise `TypeError` out of `assess`, taking every other
        expectation with it and naming no file."""
        self.valid["expectations"][0]["subject"] = {"kind": "measure", "key": "flows.total"}
        self.valid["expectations"][0]["expect"] = {"at_most": "five"}
        self._write(self.directory, self.valid)
        with self.assertRaises(ExpectationFileError) as caught:
            load_expectations(self.directory)
        self.assertIn("at_most", str(caught.exception))

    def test_an_empty_bound_is_rejected(self):
        self.valid["expectations"][0]["subject"] = {"kind": "flow", "name": "Water"}
        self.valid["expectations"][0]["expect"] = {"count": {}}
        self._write(self.directory, self.valid)
        with self.assertRaises(ExpectationFileError):
            load_expectations(self.directory)

    def test_a_count_that_is_a_string_is_rejected(self):
        self.valid["expectations"][0]["subject"] = {"kind": "flow", "name": "Water"}
        self.valid["expectations"][0]["expect"] = {"count": "1"}
        self._write(self.directory, self.valid)
        with self.assertRaises(ExpectationFileError):
            load_expectations(self.directory)

    def test_a_boolean_written_as_a_string_is_rejected(self):
        """`"true"` compares unequal to `True` and makes the expectation unmet
        on every build, which reads as a defect in the pipeline."""
        self.valid["expectations"][0]["subject"] = {"kind": "flow", "name": "Water"}
        self.valid["expectations"][0]["expect"] = {"characterised": "true"}
        self._write(self.directory, self.valid)
        with self.assertRaises(ExpectationFileError) as caught:
            load_expectations(self.directory)
        self.assertIn("true or false", str(caught.exception))

    def test_a_bound_key_written_as_a_boolean_is_rejected(self):
        """`bool` is an `int` in Python, so `{"at_most": true}` would compare a
        count against 1."""
        self.valid["expectations"][0]["subject"] = {"kind": "flow", "name": "Water"}
        self.valid["expectations"][0]["expect"] = {"count": {"at_most": True}}
        self._write(self.directory, self.valid)
        with self.assertRaises(ExpectationFileError):
            load_expectations(self.directory)

    def test_a_context_written_as_a_string_is_rejected(self):
        """It matched nothing, and "matched nothing" is reported as a subject
        that has left the build -- the wrong diagnosis for a malformed file."""
        self.valid["expectations"][0]["subject"] = {
            "kind": "source_row", "list": "bafu", "context": "air",
        }
        self._write(self.directory, self.valid)
        with self.assertRaises(ExpectationFileError) as caught:
            load_expectations(self.directory)
        self.assertIn("list of strings", str(caught.exception))

    def test_an_empty_selector_value_is_rejected(self):
        self.valid["expectations"][0]["subject"] = {"kind": "flow", "name": "  "}
        self._write(self.directory, self.valid)
        with self.assertRaises(ExpectationFileError):
            load_expectations(self.directory)

    def test_include_deprecated_has_to_be_a_boolean(self):
        self.valid["expectations"][0]["subject"] = {
            "kind": "flow", "name": "Water", "include_deprecated": "yes",
        }
        self._write(self.directory, self.valid)
        with self.assertRaises(ExpectationFileError):
            load_expectations(self.directory)

    def test_a_well_formed_bound_still_loads(self):
        """The checks above must not have made the format unusable."""
        self.valid["expectations"][0]["subject"] = {"kind": "flow", "name": "Water"}
        for bound in (3, {"at_most": 5}, {"at_least": 1, "at_most": 3}, {"equals": 0}):
            with self.subTest(bound=bound):
                self.valid["expectations"][0]["expect"] = {"count": bound}
                self._write(self.directory, self.valid)
                self.assertEqual(load_expectations(self.directory)[0].claims["count"], bound)

    def test_a_subject_with_no_selector_is_rejected(self):
        self.valid["expectations"][0]["subject"] = {"kind": "flow"}
        self._write(self.directory, self.valid)
        with self.assertRaises(ExpectationFileError):
            load_expectations(self.directory)

    def test_a_duplicate_id_is_rejected(self):
        self.valid["expectations"].append(dict(self.valid["expectations"][0]))
        self._write(self.directory, self.valid)
        with self.assertRaises(ExpectationFileError) as caught:
            load_expectations(self.directory)
        self.assertIn("duplicate", str(caught.exception))

    def test_a_future_schema_version_is_rejected(self):
        self.valid["schema_version"] = 99
        self._write(self.directory, self.valid)
        with self.assertRaises(ExpectationFileError):
            load_expectations(self.directory)

    def test_the_baseline_is_not_read_as_an_expectation_file(self):
        self._write(self.directory, self.valid)
        (self.directory / BASELINE_FILENAME).write_text(
            json.dumps({"schema_version": 1, "measures": {}, "expectations": {}})
        )
        self.assertEqual(len(load_expectations(self.directory)), 1)

    def test_every_kind_has_selectors_and_claims(self):
        self.assertEqual(set(SUBJECT_SELECTORS), set(SUBJECT_CLAIMS))


if __name__ == "__main__":
    unittest.main()
