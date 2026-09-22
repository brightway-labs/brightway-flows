"""
EF 3.1 declares characterisation factors of exactly zero, and they are data.

The loader used to skip them, which made "EF assessed this flow under this
method and the factor is zero" indistinguishable from "EF never assessed this
flow" -- 52,088 factors, 16.3% of the method files, and nearly half of
`Human toxicity, cancer` (#47).  The first factor in EF 3.1's
`Human toxicity, cancer_inorganics` file is one of them: `antimony (v)` to
agricultural soil, `<meanValue>0.0</meanValue>`.

Deduplication's "which duplicate holds more factors" tie-break deliberately
does not count them, so restoring the zeros does not silently change which
flow survives a collision (#36, #44).
"""

import unittest
from io import BytesIO
from zipfile import ZipFile

from brightway_flows.domain.lcia.records import (
    StatedFactor,
    non_zero_factor_count,
    stated_category,
)
from brightway_flows.integrations.ef31 import load_lcia_methods

ILCD_ROOT = "EF-test/ILCD/"

#: The flow carrying a stated zero, and the one carrying an ordinary factor.
_ZERO_FLOW = "47921e60-2827-4b38-95f6-8152c6f03f8c"
_NONZERO_FLOW = "29059f2a-6556-11dd-ad8b-0800200c9a66"
_METHOD_UUID = "01500b74-7ffb-463e-9bd4-72f17c2263ff"

_METHOD_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<LCIAMethodDataSet xmlns="http://lca.jrc.it/ILCD/LCIAMethod"
                   xmlns:common="http://lca.jrc.it/ILCD/Common">
 <LCIAMethodInformation>
  <dataSetInformation>
   <common:UUID>{_METHOD_UUID}</common:UUID>
   <common:name xml:lang="en">Human toxicity, cancer_inorganics</common:name>
   <methodology>Environmental Footprint</methodology>
   <impactCategory>Cancer human health effects</impactCategory>
   <impactIndicator>Comparative Toxic Unit for human (CTUh)</impactIndicator>
  </dataSetInformation>
 </LCIAMethodInformation>
 <characterisationFactors>
  <factor>
   <referenceToFlowDataSet refObjectId="{_ZERO_FLOW}" type="flow data set"/>
   <exchangeDirection>Output</exchangeDirection>
   <meanValue>0.0</meanValue>
  </factor>
  <factor>
   <referenceToFlowDataSet refObjectId="{_NONZERO_FLOW}" type="flow data set"/>
   <exchangeDirection>Output</exchangeDirection>
   <meanValue>2.5e-07</meanValue>
  </factor>
 </characterisationFactors>
</LCIAMethodDataSet>
"""


def _zip_with_method() -> ZipFile:
    buf = BytesIO()
    with ZipFile(buf, "w") as zf:
        zf.writestr(f"{ILCD_ROOT}lciamethods/{_METHOD_UUID}.xml", _METHOD_XML)
    buf.seek(0)
    return ZipFile(buf)


class TestStatedZeroFactorsAreIngested(unittest.TestCase):
    def setUp(self):
        self.flow_cfs, self.methods_meta = load_lcia_methods(
            _zip_with_method(), ILCD_ROOT
        )

    def test_zero_factor_reaches_the_flow(self):
        """A stated zero is a statement, and the flow must carry it."""
        self.assertIn(_ZERO_FLOW, self.flow_cfs)
        rows = self.flow_cfs[_ZERO_FLOW]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].amount, 0.0)

    def test_zero_factor_is_distinguishable_from_absence(self):
        """The whole point: 'characterised as zero' is not 'uncharacterised'."""
        never_assessed = "00000000-0000-0000-0000-000000000000"
        self.assertNotIn(never_assessed, self.flow_cfs)
        self.assertIn(_ZERO_FLOW, self.flow_cfs)

    def test_ordinary_factor_still_loads(self):
        rows = self.flow_cfs[_NONZERO_FLOW]
        self.assertEqual(rows[0].amount, 2.5e-07)

    def test_factor_count_includes_the_zero(self):
        self.assertEqual(self.methods_meta[0]["factor_count"], 2)

    def test_method_metadata_is_unchanged(self):
        meta = self.methods_meta[0]
        self.assertEqual(meta["name"], "Human toxicity, cancer_inorganics")
        self.assertEqual(meta["impact_category"], "Cancer human health effects")


class TestDeduplicationIgnoresStatedZeros(unittest.TestCase):
    """Restoring the zeros must not change which flow wins a duplicate group."""

    @staticmethod
    def _factors(*pairs: tuple[str, float]) -> list[StatedFactor]:
        return [
            StatedFactor(
                category=stated_category(uuid=None, name=name),
                flow_uuid="a-flow",
                amount=amount,
            )
            for name, amount in pairs
        ]

    def test_zero_valued_rows_do_not_count(self):
        methods = self._factors(
            ("Ecotoxicity, freshwater", 87.261), ("Human toxicity, cancer", 0.0)
        )
        self.assertEqual(non_zero_factor_count(methods), 1)

    def test_a_flow_characterised_only_as_zero_counts_as_none(self):
        methods = self._factors(("Human toxicity, cancer", 0.0))
        self.assertEqual(non_zero_factor_count(methods), 0)

    def test_nonzero_rows_are_unaffected(self):
        methods = self._factors(("a", 1.0), ("b", 2.0))
        self.assertEqual(non_zero_factor_count(methods), 2)


if __name__ == "__main__":
    unittest.main()
