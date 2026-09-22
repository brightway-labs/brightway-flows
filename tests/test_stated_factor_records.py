"""A characterisation factor is a record, and the published row does not move.

`lcia_methods` on the flow record was a list of dicts from the first build until
now: 319,575 of them in the build of 2026-08-16, read with `.get()` in four
modules.  `flow_layers.contested_cas` compares two flows' factors to decide
which CAS number a substance keeps, and its defence against a shape it did not
expect was to skip the row -- a decision made on no evidence.

Converting it is only safe if the record re-publishes the row it read, byte for
byte, and these are the cases that has to hold for.  All of them are real:

* the six keys EF 3.1's 25 method files state, on 319,379 rows;
* those plus `superseded_values`, on 146, and plus `provenance` too, on 50 --
  written by `pipeline.deduplication` when two rows that turned out to be one
  flow state one factor differently (#63);
* the Stepwise input's rows, which state `"methodology": null` on all 9,629 of
  them and a seventh key, `characterization_factor_flow_unit`, on 307.  Nothing
  in the pipeline reads that key and nothing may drop it (rule 3).

The Stepwise shapes are the reason the record keeps `None` apart from `""` and
carries an `extra` bag: that list is not in a build today, and a conversion that
quietly rewrote its rows would be found by nobody until it was.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

import orjson

from brightway_flows.domain.common import Provenance
from brightway_flows.domain.elementary_flow import ElementaryFlow
from brightway_flows.domain.flow import Flow
from brightway_flows.domain.lcia.records import (
    FACTOR_AMOUNT_KEY,
    FACTOR_AMOUNT_KEY_ALTERNATIVE,
    StatedFactor,
    non_zero_factor_count,
    non_zero_factor_count_of_entries,
    stated_category,
)

SRC = Path(__file__).resolve().parents[1] / "src" / "brightway_flows"

#: One EF 3.1 row: kresoxim-methyl's freshwater ecotoxicity in agricultural
#: soil, the factor #64 is about.
EF_ROW = {
    "method_uuid": "05316e7a-b254-4bea-9cf0-6bf33eb5c630",
    "name": "Ecotoxicity, freshwater",
    "methodology": "Environmental Footprint",
    "impact_category": "Aquatic eco-toxicity",
    "impact_indicator": "Comparative Toxic Unit for ecosystems (CTUe) ",
    "characterization_factor": 134.73,
}

#: The same row after a collapse declined another flow's number for it.
EF_ROW_WITH_SUPERSEDED = {
    **EF_ROW,
    "superseded_values": [
        {
            "characterization_factor": 0.000118,
            "provenance": {
                "prov:wasGeneratedBy": "pipeline.deduplication",
                "prov:wasAttributedTo": "brightway-flows",
                "prov:hadPrimarySource": ["urn:uuid:ef-1"],
            },
            "relative_difference": 0.003828158230540196,
        }
    ],
}

#: And after the other flow's number was the more precise one, so this row's own
#: value was replaced and says so.
EF_ROW_WITH_PROVENANCE = {
    **EF_ROW,
    "provenance": {
        "prov:wasGeneratedBy": "pipeline.collision_decisions",
        "prov:wasAttributedTo": "brightway-flows",
        "prov:hadPrimarySource": ["urn:uuid:ef-2"],
        "prov:wasDerivedFrom": "elementary-flow-collision-decisions.json",
    },
    # No `relative_difference`: this pair crosses zero, where a relative
    # difference is not defined, and the writer omits the key rather than
    # stating null.  All 204 declined numbers in the build carry all three keys;
    # this is the shape the collision tests produce.
    "superseded_values": [
        {
            "characterization_factor": 0.0,
            "provenance": {
                "prov:wasGeneratedBy": "pipeline.collision_decisions",
                "prov:wasAttributedTo": "brightway-flows",
                "prov:hadPrimarySource": ["urn:uuid:ef-1"],
            },
        }
    ],
}

#: A Stepwise row: no methodology, and a unit the factor is stated per.
STEPWISE_ROW = {
    "method_uuid": "145b452d-3324-5136-9a3d-ac9c82f6093a",
    "name": "Stepwise_2006_IPCC2021_CorrectedNatureOccupation",
    "methodology": None,
    "impact_category": "Respiratory organics",
    "impact_indicator": "pers*ppm*h",
    "characterization_factor": 5.9e-05,
    "characterization_factor_flow_unit": "g",
}

REAL_ROWS = {
    "EF 3.1": EF_ROW,
    "a declined number recorded on it": EF_ROW_WITH_SUPERSEDED,
    "its own number replaced": EF_ROW_WITH_PROVENANCE,
    "Stepwise, with a seventh key": STEPWISE_ROW,
}


class TheRowGoesBackOutAsItCameInTestCase(unittest.TestCase):
    """`from_flow_entry` then `to_flow_entry` is the identity on real rows."""

    def test_every_real_shape_round_trips(self):
        for label, row in REAL_ROWS.items():
            with self.subTest(label):
                rebuilt = StatedFactor.from_flow_entry(row).to_flow_entry()
                self.assertEqual(rebuilt, row)

    def test_the_keys_come_back_in_the_same_order(self):
        """Key order is bytes: the artifacts are JSON, and a reordered key is a
        different file even where it is the same data."""
        for label, row in REAL_ROWS.items():
            with self.subTest(label):
                rebuilt = StatedFactor.from_flow_entry(row).to_flow_entry()
                self.assertEqual(list(rebuilt), list(row))

    def test_the_bytes_are_the_same_bytes(self):
        for label, row in REAL_ROWS.items():
            with self.subTest(label):
                rebuilt = StatedFactor.from_flow_entry(row).to_flow_entry()
                self.assertEqual(orjson.dumps(rebuilt), orjson.dumps(row))

    def test_a_null_is_not_an_empty_string(self):
        """Stepwise states `"methodology": null` on all 9,629 of its rows."""
        factor = StatedFactor.from_flow_entry(STEPWISE_ROW)
        self.assertIsNone(factor.category.methodology)
        self.assertIsNone(factor.to_flow_entry()["methodology"])

    def test_a_key_the_record_does_not_declare_is_kept(self):
        """Rule 3: a source-specific key goes in `extra` and is read from it."""
        factor = StatedFactor.from_flow_entry(STEPWISE_ROW)
        self.assertEqual(factor.extra, {"characterization_factor_flow_unit": "g"})

    def test_a_row_stating_fewer_keys_does_not_gain_any(self):
        """A key filled in here would appear in an artifact from nowhere."""
        row = {"name": "Climate change", "characterization_factor": 2590.0}
        self.assertEqual(StatedFactor.from_flow_entry(row).to_flow_entry(), row)

    def test_the_other_spelling_is_read_and_written_back_as_itself(self):
        """No shipped file uses it, and a record that renamed a publisher's key
        would publish a file the publisher did not write."""
        row = {**EF_ROW}
        row[FACTOR_AMOUNT_KEY_ALTERNATIVE] = row.pop(FACTOR_AMOUNT_KEY)
        factor = StatedFactor.from_flow_entry(row)
        self.assertEqual(factor.amount_key, FACTOR_AMOUNT_KEY_ALTERNATIVE)
        self.assertEqual(factor.to_flow_entry(), row)

    def test_a_row_with_no_number_is_refused(self):
        """A factor without a number is not a factor, and all 329,204 rows in
        the two files that carry them state one."""
        with self.assertRaises(ValueError):
            StatedFactor.from_flow_entry({**EF_ROW, "characterization_factor": None})
        with self.assertRaises(ValueError):
            StatedFactor.from_flow_entry({"name": "Climate change"})

    def test_a_category_is_one_object_however_many_rows_name_it(self):
        """25 categories stand behind 319,575 factors."""
        first = StatedFactor.from_flow_entry(EF_ROW)
        second = StatedFactor.from_flow_entry({**EF_ROW, "characterization_factor": 1.0})
        self.assertIs(first.category, second.category)


class TheFlowRecordPublishesWhatItReadTestCase(unittest.TestCase):
    """The codec `Flow` and `ElementaryFlow` declare for the field."""

    def _payload(self) -> dict:
        return {
            "uuid": "ef-1",
            "flow_object_id": "fo-1",
            "source": "EF 3.1",
            "lcia_methods": list(REAL_ROWS.values()),
        }

    def test_the_flow_record_round_trips_the_field(self):
        payload = self._payload()
        self.assertEqual(Flow.from_dict(payload).to_dict()["lcia_methods"],
                         payload["lcia_methods"])

    def test_the_flow_record_holds_records(self):
        flow = Flow.from_dict(self._payload())
        self.assertTrue(all(isinstance(f, StatedFactor) for f in flow.lcia_methods))

    def test_the_two_records_agree(self):
        """`merge.datastores` projects an elementary flow through `Flow` to build
        the column the merge reads, so the two codecs have to be one codec."""
        flow = Flow.from_dict(self._payload())
        elementary = ElementaryFlow(
            elementary_flow_id="ef-1",
            flow_object_id="fo-1",
            source="EF 3.1",
            context=None,  # type: ignore[arg-type]
            context_iri="",
            unit="kg",
            unit_iri=None,
            lcia_methods=flow.lcia_methods,
            general_comment=None,
        )
        self.assertEqual(
            elementary.to_dict()["lcia_methods"], flow.to_dict()["lcia_methods"]
        )


class ProvenanceReadsBackTestCase(unittest.TestCase):
    """`Provenance.to_dict` had no inverse, and a factor carries one."""

    def test_it_round_trips(self):
        for row in (EF_ROW_WITH_PROVENANCE["provenance"],
                    EF_ROW_WITH_SUPERSEDED["superseded_values"][0]["provenance"]):
            with self.subTest(row["prov:wasGeneratedBy"]):
                self.assertEqual(Provenance.from_dict(row).to_dict(), row)

    def test_a_key_it_cannot_hold_raises(self):
        """Dropping a key here would drop it from the next artifact."""
        with self.assertRaises(ValueError):
            Provenance.from_dict({
                "prov:wasGeneratedBy": "x",
                "prov:wasAttributedTo": "y",
                "prov:wasInfluencedBy": "z",
            })


class CountingFactorsTestCase(unittest.TestCase):
    """One rule, asked of a record and of the row it serialises to."""

    def test_the_two_forms_agree(self):
        rows = [
            EF_ROW,
            {**EF_ROW, "characterization_factor": 0.0},
            STEPWISE_ROW,
        ]
        records = [StatedFactor.from_flow_entry(row) for row in rows]
        self.assertEqual(non_zero_factor_count(records), 2)
        self.assertEqual(non_zero_factor_count_of_entries(rows), 2)

    def test_a_stated_zero_does_not_count(self):
        """#47 keeps the zeros; #36 and #44 own the question of whether they
        should count towards which duplicate survives, and until they answer it
        the answer here is no."""
        zero = stated_category(uuid="m", name="m")
        self.assertEqual(
            non_zero_factor_count(
                [StatedFactor(category=zero, flow_uuid="ef-1", amount=0.0)]
            ),
            0,
        )


class NothingElseReadsAFactorAsADictTestCase(unittest.TestCase):
    """The amount's key belongs to one module, and that is the boundary.

    Four modules used to name it, and the point of the record is that the number
    is reached by attribute everywhere the pipeline decides anything with it.  A
    module naming the key again is a module reading a record as a payload.
    """

    ALLOWED = {"domain/lcia/records.py"}

    def test_the_amount_key_is_named_in_one_module(self):
        offenders: list[str] = []
        for path in sorted(SRC.rglob("*.py")):
            relative = path.relative_to(SRC).as_posix()
            if relative in self.ALLOWED:
                continue
            for node in ast.walk(ast.parse(path.read_text())):
                if not isinstance(node, ast.Constant):
                    continue
                if node.value in (FACTOR_AMOUNT_KEY, FACTOR_AMOUNT_KEY_ALTERNATIVE):
                    offenders.append(f"{relative}:{node.lineno}")
        self.assertEqual(
            offenders,
            [],
            "a characterisation factor's amount is read by attribute; these "
            "name its key instead:\n  " + "\n  ".join(offenders),
        )


if __name__ == "__main__":
    unittest.main()
