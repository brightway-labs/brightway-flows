"""Reading the heating values ecoinvent states on its elementary exchanges.

From 3.9.1 ecoinvent's `Oil, crude` exchange carries a `heating value, net` of
43.4 and a `heating value, gross` of 46 as `<property>` children, each in
megajoules per unit of the exchange; natural gas carries 36 and 40 per standard
cubic metre; 3.12 adds the pair to some thirty emission flows.  3.8 states
none.  The adapter reads them onto the flow as the vendor's own statements
(#407, phase B), matching the property's name against the quantity
vocabulary, so `wet mass` and `carbon content, fossil` pass by.

The exchanges here are copied from 3.12's `ElementaryExchanges.xml` as
`xmltodict` hands them over, and the property definitions from its
`Properties.xml` (`tests/vendor_statements.py`).
"""

import tempfile
import unittest
from pathlib import Path

from vendor_statements import (
    ECOINVENT_CRUDE_OIL,
    ECOINVENT_NATURAL_GAS,
    ECOINVENT_PROPERTY_DEFINITIONS,
)

from brightway_flows.domain.property_statements import StatementOrigin
from brightway_flows.integrations.ecoinvent import (
    property_definitions,
    statements_from_properties,
)

PROPERTIES_XML = """<?xml version="1.0" encoding="UTF-8"?>
<validProperties xmlns="http://www.EcoInvent.org/EcoSpold02">
  <property id="48c987bb-3144-4872-b5c7-b1389c40be25" defaultVariableName="Net_Heat_Value" unitId="980b811e-3905-4797-82a5-173f5568bc7e">
    <name xml:lang="en">heating value, net</name>
    <unitName xml:lang="en">MJ</unitName>
    <comment xml:lang="en">Measure of the thermal energy produced during the combustion of a product. Expressed in MJ per unit of product.</comment>
  </property>
  <property id="67f102e2-9cb6-4d20-aa16-bf74d8a03326" defaultVariableName="WM" unitId="487df68b-4994-4027-8fdc-a4dc298257b7">
    <name xml:lang="en">wet mass</name>
    <unitName xml:lang="en">kg</unitName>
  </property>
</validProperties>
"""


class PropertyDefinitionsTestCase(unittest.TestCase):
    def test_the_master_data_gives_each_property_its_name_and_unit(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Properties.xml"
            path.write_text(PROPERTIES_XML, encoding="utf-8")
            definitions = property_definitions(path)
        self.assertEqual(
            definitions,
            {
                "48c987bb-3144-4872-b5c7-b1389c40be25": ("heating value, net", "MJ"),
                "67f102e2-9cb6-4d20-aa16-bf74d8a03326": ("wet mass", "kg"),
            },
        )


class StatementsFromPropertiesTestCase(unittest.TestCase):
    def _read(self, obj, unit):
        return statements_from_properties(
            obj, ECOINVENT_PROPERTY_DEFINITIONS, flow_unit=unit,
            version="3.12", source="ecoinvent-3.12",
        )

    def test_crude_oil_states_a_net_and_a_gross_heating_value(self):
        statements = self._read(ECOINVENT_CRUDE_OIL, "kg")
        self.assertEqual(
            [(s.quantity, s.value, s.unit, s.per_unit) for s in statements],
            [
                ("net-calorific-value", 43.4, "MJ", "kg"),
                ("gross-calorific-value", 46.0, "MJ", "kg"),
            ],
        )
        for statement in statements:
            self.assertIs(statement.stated_by, StatementOrigin.VENDOR_FLOW)
            self.assertEqual(statement.provenance.was_attributed_to, "ecoinvent-3.12")
            self.assertIn("Meili et al. (2022)", statement.comment)
            self.assertIn("88d06db9", statement.provenance.had_primary_source[0])

    def test_wet_mass_is_no_quantity_the_vocabulary_names(self):
        statements = self._read(ECOINVENT_CRUDE_OIL, "kg")
        self.assertNotIn("mass", [s.quantity for s in statements])

    def test_natural_gas_is_per_the_flows_canonical_unit(self):
        """The exchange says `Sm3`; the flow is carried as `sm3`, and the
        statement is per the unit the flow is carried in, which is what keeps
        36 per standard cubic metre off a row in plain cubic metres (#292)."""
        statements = self._read(ECOINVENT_NATURAL_GAS, "sm3")
        self.assertEqual(
            sorted((s.quantity, s.value, s.per_unit) for s in statements),
            [("gross-calorific-value", 40.0, "sm3"), ("net-calorific-value", 36.0, "sm3")],
        )

    def test_an_exchange_without_properties_states_nothing(self):
        bare = {k: v for k, v in ECOINVENT_CRUDE_OIL.items() if k != "property"}
        self.assertEqual(self._read(bare, "kg"), [])

    def test_a_single_property_is_read_as_well_as_a_list(self):
        one = {**ECOINVENT_CRUDE_OIL, "property": ECOINVENT_CRUDE_OIL["property"][0]}
        self.assertEqual([s.value for s in self._read(one, "kg")], [43.4])

    def test_a_zero_or_an_unknown_property_states_nothing(self):
        zero = {
            **ECOINVENT_CRUDE_OIL,
            "property": [
                {"@propertyId": "48c987bb-3144-4872-b5c7-b1389c40be25", "@amount": "0"},
                {"@propertyId": "not-a-property", "@amount": "5"},
            ],
        }
        self.assertEqual(self._read(zero, "kg"), [])


if __name__ == "__main__":
    unittest.main()
