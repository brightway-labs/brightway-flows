"""EF 3.1 says where a factor applies, and until now nothing read it.

`Land use` states 213 numbers for one flow -- `from arable, irrigated, extensive`
-- and they are not duplicates: each is a different country, `<lcia:location>ES-CA`
against `<lcia:location>YE`, and the numbers differ by an order of magnitude.
The parser dropped the element, so all 213 reached the flow record as `Land use`
with nothing to tell them apart, and any reader picking one was picking at random.

Measured over the 25 method files of `EF-v3.1.zip`:

* **42,871 of 319,575 factors state a location**, in 223 distinct codes;
* eight methods state them -- `Land use` (36,252), `Water use` (2,299),
  `Acidification` (900), `EF-particulate Matter` (900),
  `Photochemical ozone formation - human health` (720), the two eutrophications
  (540 each), and 180 each on four toxicity categories;
* with the location, **`(flow, location)` names exactly one factor in every one of
  the 25 files** -- so EF's own data satisfies the one-factor-per-(flow,
  geography, category) rule the model states, and it was our extraction that
  could not express it.

The other 276,704 factors state none, and their rows are unchanged: a factor is
about a substance in a compartment, and only a model whose answer depends on where
the land or the water is needs a third thing.
"""

from __future__ import annotations

import unittest
from io import BytesIO
from zipfile import ZipFile

from brightway_flows.domain.lcia.records import (
    GEOGRAPHY_KEY,
    StatedFactor,
    stated_category,
)
from brightway_flows.integrations.ef31 import load_lcia_methods
from brightway_flows.pipeline.deduplication import factor_key

ILCD_ROOT = "EF-test/ILCD/"
LAND_USE = "b2ad6890-c78d-11e6-9d9d-cec0c932ce01"
#: `from arable, irrigated, extensive`, which EF characterises in 213 countries.
FLOW = "03b56eb6-cc68-4251-9317-06878cb27dff"
#: A flow of a method that states no location at all.
UNLOCATED_FLOW = "29059f2a-6556-11dd-ad8b-0800200c9a66"

_METHOD_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<LCIAMethodDataSet xmlns="http://lca.jrc.it/ILCD/LCIAMethod"
                   xmlns:common="http://lca.jrc.it/ILCD/Common">
 <LCIAMethodInformation>
  <dataSetInformation>
   <common:UUID>{LAND_USE}</common:UUID>
   <common:name xml:lang="en">Land use</common:name>
   <methodology>Environmental Footprint</methodology>
   <impactCategory>Land use</impactCategory>
   <impactIndicator>Soil quality index</impactIndicator>
  </dataSetInformation>
 </LCIAMethodInformation>
 <characterisationFactors>
  <factor>
   <referenceToFlowDataSet refObjectId="{FLOW}" type="flow data set"/>
   <location>ES-CA</location>
   <exchangeDirection>Input</exchangeDirection>
   <meanValue>-5.2281E+02</meanValue>
  </factor>
  <factor>
   <referenceToFlowDataSet refObjectId="{FLOW}" type="flow data set"/>
   <location>YE</location>
   <exchangeDirection>Input</exchangeDirection>
   <meanValue>-2.2700E+02</meanValue>
  </factor>
  <factor>
   <referenceToFlowDataSet refObjectId="{UNLOCATED_FLOW}" type="flow data set"/>
   <location />
   <exchangeDirection>Input</exchangeDirection>
   <meanValue>2.5E-07</meanValue>
  </factor>
 </characterisationFactors>
</LCIAMethodDataSet>
"""


def _zip_with_method() -> ZipFile:
    buf = BytesIO()
    with ZipFile(buf, "w") as zf:
        zf.writestr(f"{ILCD_ROOT}lciamethods/{LAND_USE}.xml", _METHOD_XML)
    buf.seek(0)
    return ZipFile(buf)


class TheParserReadsTheLocationTestCase(unittest.TestCase):
    def setUp(self):
        self.flow_cfs, self.methods_meta = load_lcia_methods(
            _zip_with_method(), ILCD_ROOT
        )

    def test_two_factors_for_one_flow_are_two_places(self):
        factors = self.flow_cfs[FLOW]
        self.assertEqual([f.geography for f in factors], ["ES-CA", "YE"])
        self.assertEqual([f.amount for f in factors], [-522.81, -227.0])

    def test_an_empty_location_is_no_location(self):
        """`<location />` is how EF writes "this factor is not about a place",
        and an empty string there would be a place called nothing."""
        self.assertIsNone(self.flow_cfs[UNLOCATED_FLOW][0].geography)

    def test_the_count_is_unchanged(self):
        """Reading the location adds no factor and drops none."""
        self.assertEqual(self.methods_meta[0]["factor_count"], 3)


class ThePublishedRowTestCase(unittest.TestCase):
    """A located row gains one key; an unlocated row is the row it was."""

    ROW = {
        "method_uuid": LAND_USE,
        "name": "Land use",
        "methodology": "Environmental Footprint",
        "impact_category": "Land use",
        "impact_indicator": "Soil quality index",
        "characterization_factor": -522.81,
    }

    def test_a_row_with_no_place_is_unchanged(self):
        factor = StatedFactor.from_flow_entry(self.ROW)
        self.assertIsNone(factor.geography)
        self.assertEqual(factor.to_flow_entry(), self.ROW)
        self.assertNotIn(GEOGRAPHY_KEY, factor.to_flow_entry())

    def test_a_located_row_round_trips(self):
        row = {**self.ROW, GEOGRAPHY_KEY: "ES-CA"}
        factor = StatedFactor.from_flow_entry(row)
        self.assertEqual(factor.geography, "ES-CA")
        self.assertEqual(factor.to_flow_entry(), row)
        self.assertEqual(list(factor.to_flow_entry()), list(row))

    def test_the_place_follows_the_number(self):
        """Where in the row it goes is published, so it is pinned rather than
        left to whichever order the code happens to build."""
        row = {**self.ROW, GEOGRAPHY_KEY: "ES-CA"}
        self.assertEqual(
            list(StatedFactor.from_flow_entry(row).to_flow_entry())[-2:],
            ["characterization_factor", GEOGRAPHY_KEY],
        )

    def test_the_place_is_not_a_source_specific_key(self):
        """It is a field of the record, not something in `extra`."""
        factor = StatedFactor.from_flow_entry({**self.ROW, GEOGRAPHY_KEY: "ES-CA"})
        self.assertEqual(factor.extra, {})


class TwoPlacesAreTwoFactorsTestCase(unittest.TestCase):
    """`factor_key` is what makes two rows one factor, and the place is part of it."""

    def _factor(self, geography):
        return StatedFactor(
            category=stated_category(uuid=LAND_USE, name="Land use"),
            flow_uuid=FLOW,
            amount=-522.81,
            geography=geography,
        )

    def test_two_places_do_not_settle_against_each_other(self):
        self.assertNotEqual(
            factor_key(self._factor("ES-CA")), factor_key(self._factor("YE"))
        )

    def test_one_place_is_one_factor(self):
        self.assertEqual(
            factor_key(self._factor("ES-CA")), factor_key(self._factor("ES-CA"))
        )

    def test_a_row_with_no_place_keys_on_the_method_alone(self):
        """276,704 of the 319,575 rows, whose key must not move: nothing about a
        factor that states no place has changed."""
        self.assertEqual(factor_key(self._factor(None)), LAND_USE)


if __name__ == "__main__":
    unittest.main()
