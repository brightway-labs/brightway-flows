"""A consensus substance's property values: reference, source spread, class range.

`flow-object-property-values.json` states the reference value a curator chose
and the range the class spans; the merged lists' statements give the spread;
the pass writes all three onto `FlowObject.properties` under the quantity's
IRI in QUDT's shape, and keeps the two ranges apart (#407, phase C).
"""

import unittest
from collections import Counter
from unittest import mock

import orjson

from brightway_flows.domain.flow_object import FlowObject
from brightway_flows.domain.quantities import NET_CALORIFIC_VALUE, quantity
from brightway_flows.domain.vocabulary import QUDT_HAS_UNIT_CURIE, RDFS_LABEL_CURIE
from brightway_flows.flow_object_properties import (
    CLASS_RANGE_CURIE,
    FLOW_OBJECT_PROPERTY_VALUES_FILEPATH,
    MAX_VALUE_CURIE,
    MEASUREMENTS_CURIE,
    MIN_VALUE_CURIE,
    PER_UNIT_CURIE,
    QUANTITY_VALUE_CURIE,
    SOURCE_SPREAD_CURIE,
    VALUE_CURIE,
    ClassRange,
    FlowObjectPropertyValue,
    load_flow_object_property_values,
    property_entries,
    write_flow_object_property_values,
)
from brightway_flows.merge.property_rows import PropertyStatementRow

HARD_COAL = "fo-83837092807da333"


def _row(list_name, value, *, quantity_slug=NET_CALORIFIC_VALUE, per_unit="kg", used=True):
    return PropertyStatementRow(
        run_id="run", list_name=list_name, list_version="1", source_flow_uuid=f"{list_name}-coal",
        source_flow_name="Coal, hard", elementary_flow_uuid="ef", flow_object_id=HARD_COAL,
        quantity=quantity_slug, quantity_iri=quantity(quantity_slug).iri, value=value,
        unit="MJ", per_unit=per_unit, stated_by="vendor-flow", used_for_conversion=used,
        provenance={"prov:wasDerivedFrom": f"{list_name}.csv"}, comment="",
    )


def _reference(value=18.01, span=(11.5, 32.2)):
    return FlowObjectPropertyValue(
        flow_object_id=HARD_COAL, label="Hard Coal", quantity=NET_CALORIFIC_VALUE,
        value=value, unit="MJ", per_unit="kg", primary_source=["the workbook"],
        comment="why", class_range=None if span is None else ClassRange(
            min=span[0], max=span[1], basis="as received", primary_source=["IPCC"],
        ),
    )


class ShippedFileTestCase(unittest.TestCase):
    def test_the_file_loads_and_names_substances_the_build_has(self):
        values = load_flow_object_property_values()
        self.assertIn((HARD_COAL, NET_CALORIFIC_VALUE), values)
        for (object_id, slug), value in values.items():
            with self.subTest(label=value.label, quantity=slug):
                self.assertTrue(object_id.startswith("fo-"))
                self.assertGreater(value.value, 0)
                if value.class_range is not None:
                    self.assertLessEqual(value.class_range.min, value.value)
                    self.assertLessEqual(value.value, value.class_range.max)

    def test_every_entry_says_where_its_number_came_from(self):
        payload = orjson.loads(FLOW_OBJECT_PROPERTY_VALUES_FILEPATH.read_bytes())
        for entry in payload["values"]:
            with self.subTest(label=entry["label"]):
                self.assertTrue(entry["primary_source"])
                self.assertTrue(entry["comment"].strip())


class LoaderRefusalsTestCase(unittest.TestCase):
    def _load(self, **entry):
        base = {
            "flow_object_id": HARD_COAL, "label": "Hard Coal", "quantity": NET_CALORIFIC_VALUE,
            "value": 18.01, "unit": "MJ", "per_unit": "kg", "primary_source": ["the workbook"],
            "comment": "why",
        }
        base.update(entry)
        payload = orjson.dumps({"schema_version": 1, "values": [base]})
        load_flow_object_property_values.cache_clear()
        self.addCleanup(load_flow_object_property_values.cache_clear)
        with mock.patch.object(
            type(FLOW_OBJECT_PROPERTY_VALUES_FILEPATH), "read_bytes", lambda self: payload
        ):
            return load_flow_object_property_values()

    def test_a_reference_outside_its_own_class_range_is_refused(self):
        with self.assertRaises(ValueError) as caught:
            self._load(class_range={"min": 19.9, "max": 30.5, "basis": "x", "primary_source": ["IPCC"]})
        self.assertIn("outside its own class range", str(caught.exception))

    def test_a_unit_of_another_quantity_is_refused(self):
        with self.assertRaises(ValueError):
            self._load(unit="kg", per_unit="m3")

    def test_an_unknown_quantity_is_refused(self):
        with self.assertRaises(ValueError):
            self._load(quantity="heat")

    def test_a_good_entry_loads(self):
        values = self._load(class_range={"min": 11.5, "max": 32.2, "basis": "x", "primary_source": ["IPCC"]})
        self.assertEqual(values[(HARD_COAL, NET_CALORIFIC_VALUE)].class_range.max, 32.2)


class PropertyEntriesTestCase(unittest.TestCase):
    def test_the_entry_is_keyed_by_the_quantity_iri_in_qudts_shape(self):
        rows = [_row("agribalyse", 18.2), _row("bafu", 18.01), _row("stepwise", 19.1)]
        counts = Counter()
        entries = property_entries(
            HARD_COAL, rows=rows, curated={(HARD_COAL, NET_CALORIFIC_VALUE): _reference()}, counts=counts,
        )
        iri = quantity(NET_CALORIFIC_VALUE).iri
        self.assertEqual(set(entries), {iri})
        entry = entries[iri]
        self.assertEqual(entry[RDFS_LABEL_CURIE], "Net calorific value")
        self.assertEqual(entry["skos:broader"], quantity(NET_CALORIFIC_VALUE).qudt_match_iri)
        (measurement,) = entry[MEASUREMENTS_CURIE]
        self.assertEqual(measurement["@type"], QUANTITY_VALUE_CURIE)
        self.assertTrue(measurement[QUDT_HAS_UNIT_CURIE].endswith("/MegaJ"))
        self.assertTrue(measurement[PER_UNIT_CURIE].endswith("/KiloGM"))
        self.assertEqual(measurement[VALUE_CURIE], 18.01)
        self.assertEqual(
            measurement[SOURCE_SPREAD_CURIE],
            {MIN_VALUE_CURIE: 18.01, MAX_VALUE_CURIE: 19.1, "statements": 3,
             "lists": ["agribalyse 1", "bafu 1", "stepwise 1"]},
        )
        self.assertEqual(measurement[CLASS_RANGE_CURIE][MIN_VALUE_CURIE], 11.5)
        self.assertEqual(measurement[CLASS_RANGE_CURIE][MAX_VALUE_CURIE], 32.2)
        roles = [item["role"] for item in measurement["provenance"]]
        self.assertEqual(roles, ["reference-value", "statement", "statement", "statement"])
        self.assertEqual(counts["statements_outside_class_range"], 0)

    def test_a_statement_outside_the_class_range_is_counted_not_dropped(self):
        counts = Counter()
        entries = property_entries(
            HARD_COAL, rows=[_row("stepwise", 19.1), _row("odd", 40.0)],
            curated={(HARD_COAL, NET_CALORIFIC_VALUE): _reference(span=(11.5, 32.2))}, counts=counts,
        )
        (measurement,) = entries[quantity(NET_CALORIFIC_VALUE).iri][MEASUREMENTS_CURIE]
        self.assertEqual(measurement[SOURCE_SPREAD_CURIE][MAX_VALUE_CURIE], 40.0)
        self.assertEqual(counts["statements_outside_class_range"], 1)

    def test_one_measurement_per_unit_pair(self):
        entries = property_entries(
            HARD_COAL, rows=[_row("a", 18.2), _row("b", 35.0, per_unit="m3")], curated={},
        )
        measurements = entries[quantity(NET_CALORIFIC_VALUE).iri][MEASUREMENTS_CURIE]
        self.assertEqual(len(measurements), 2)
        for measurement in measurements:
            self.assertNotIn(VALUE_CURIE, measurement)
            self.assertNotIn(CLASS_RANGE_CURIE, measurement)

    def test_a_reference_with_no_statements_stands_alone(self):
        entries = property_entries(
            HARD_COAL, rows=[], curated={(HARD_COAL, NET_CALORIFIC_VALUE): _reference(span=None)},
        )
        (measurement,) = entries[quantity(NET_CALORIFIC_VALUE).iri][MEASUREMENTS_CURIE]
        self.assertEqual(measurement[VALUE_CURIE], 18.01)
        self.assertNotIn(SOURCE_SPREAD_CURIE, measurement)
        self.assertNotIn(CLASS_RANGE_CURIE, measurement)

    def test_the_two_ranges_are_two_keys(self):
        self.assertNotEqual(SOURCE_SPREAD_CURIE, CLASS_RANGE_CURIE)
        self.assertTrue(SOURCE_SPREAD_CURIE.startswith("brightway:"))
        self.assertTrue(MIN_VALUE_CURIE.startswith("schema:"))


class WritePassTestCase(unittest.TestCase):
    def _object(self, object_id=HARD_COAL):
        return FlowObject(
            flow_object_id=object_id, prefLabel=[], altLabel=[], properties={"x": 1},
            references=[], created_from={},
        )

    def test_writes_the_objects_with_rows_or_a_ruling_and_names_the_changed(self):
        coal, other = self._object(), self._object("fo-other")
        changed: set[str] = set()
        counts = write_flow_object_property_values(
            [coal, other],
            rows_by_object={HARD_COAL: [_row("stepwise", 19.1)]},
            curated={(HARD_COAL, NET_CALORIFIC_VALUE): _reference()},
            changed=changed,
        )
        self.assertEqual(changed, {HARD_COAL})
        self.assertEqual(counts["objects_written"], 1)
        self.assertEqual(counts["reference_values"], 1)
        self.assertEqual(coal.properties["x"], 1)
        self.assertIn(quantity(NET_CALORIFIC_VALUE).iri, coal.properties)
        self.assertEqual(other.properties, {"x": 1})

    def test_a_second_pass_with_the_same_answer_changes_nothing(self):
        coal = self._object()
        rows = {HARD_COAL: [_row("stepwise", 19.1)]}
        curated = {(HARD_COAL, NET_CALORIFIC_VALUE): _reference()}
        write_flow_object_property_values([coal], rows_by_object=rows, curated=curated)
        changed: set[str] = set()
        counts = write_flow_object_property_values(
            [coal], rows_by_object=rows, curated=curated, changed=changed
        )
        self.assertEqual(changed, set())
        self.assertEqual(counts["objects_written"], 0)


if __name__ == "__main__":
    unittest.main()
