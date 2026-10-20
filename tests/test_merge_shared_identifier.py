"""A source row that carries a consensus flow's own uuid goes onto that flow.

GreenDelta's openLCA package ships 125 of EF 3.1's flows under EF's uuids,
renamed in ecoinvent's spelling -- `Particulates, < 10 um` is EF's
`particles (PM10)`.  The merge reads the uuid as the vendor's statement of which
flow the row is, and keeps the row out of the enrichment, which addresses a
change by uuid and would have sent changes meant for the consensus flow to it.
"""

from __future__ import annotations

import unittest

from brightway_flows.domain.flow import Flow
from brightway_flows.merge.rows import (
    SHARED_IDENTIFIER_BASIS,
    shared_identifier_rows,
)

PM10 = "08a91e70-3ddc-11dd-9537-0050c2490048"
OTHER = "0000b186-aea3-4c0a-b0c2-c284de7cdf92"


def _flow(uuid: str) -> Flow:
    return Flow.from_dict({
        "uuid": uuid,
        "name": "Particulates, < 10 um",
        "context": ["Emission to air", "unspecified"],
        "unit": "kg",
    })


class SharedIdentifierRowsTestCase(unittest.TestCase):
    def test_a_shared_uuid_is_prepared_onto_itself(self):
        rows = shared_identifier_rows(
            [_flow(PM10), _flow(OTHER)], consensus_ids={PM10}, declared=[]
        )
        self.assertEqual(rows, [{
            "source": {"uuid": PM10},
            "target": {"uuid": PM10},
            "basis": SHARED_IDENTIFIER_BASIS,
        }])

    def test_a_declared_decision_is_kept(self):
        declared = [{"source": {"uuid": PM10}, "target": {"uuid": OTHER}}]
        self.assertEqual(
            shared_identifier_rows(
                [_flow(PM10)], consensus_ids={PM10}, declared=declared
            ),
            [],
        )

    def test_nothing_shared_is_nothing_prepared(self):
        self.assertEqual(
            shared_identifier_rows([_flow(OTHER)], consensus_ids={PM10}, declared=[]),
            [],
        )


if __name__ == "__main__":
    unittest.main()
