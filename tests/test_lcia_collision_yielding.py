"""A row stated under another publisher's identifier gives way in a collision.

GreenDelta's package ships `Paraquat` in surface water twice: under ecoinvent's
uuid at 17,533 (ecotoxicity, freshwater), which is ecoinvent's own number because
ecoinvent maps its row to EF's paraquat dichloride, and as its own row at 190,560,
EF's number for paraquat.  Both reach one consensus flow, 10.9x apart, and
`settle` published neither (#439).  The manifest now names the lists whose rows
give way, so GreenDelta's own row is published and the finding still says what
collided and which row gave way.

Tested on both sides: the rule only ever removes a row named as giving way, and
only publishes where what is left states one number.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from brightway_flows.domain.lcia.records import StatedFactor, stated_category
from brightway_flows.lcia.collisions import settle
from brightway_flows.lcia.matching import MatchedFactor
from brightway_flows.sources import LciaSpec

FLOW = "flow-paraquat-surface-water"
ECOINVENT_COPY = "43a76088-0000-0000-0000-000000000000"
OWN = "3e67ef78-0000-0000-0000-000000000000"
OWN_AGAIN = "11111111-0000-0000-0000-000000000000"


def _candidate(source_uuid, amount):
    return MatchedFactor(
        elementary_flow_uuid=FLOW,
        factor=StatedFactor(
            category=stated_category(uuid="ef", name="Ecotoxicity, freshwater"),
            flow_uuid=source_uuid,
            amount=amount,
        ),
        source_flow_uuid=source_uuid,
    )


def _settle(candidates, yielding=()):
    return settle(
        candidates,
        elementary_flow_uuid=FLOW,
        implemented_by="GreenDelta",
        category="Ecotoxicity, freshwater",
        geography=None,
        yielding=yielding,
    )


class YieldingTestCase(unittest.TestCase):
    def test_the_own_row_is_published_and_the_collision_is_still_reported(self):
        kept, finding = _settle(
            [_candidate(ECOINVENT_COPY, 17533.0), _candidate(OWN, 190560.0)],
            yielding={ECOINVENT_COPY},
        )
        self.assertEqual(kept.source_flow_uuid, OWN)
        self.assertEqual(finding.context["yielded"], {"published": OWN, "gave_way": [ECOINVENT_COPY]})
        self.assertIn("gives way", finding.detail)

    def test_nothing_is_published_without_rows_named_to_give_way(self):
        kept, finding = _settle([_candidate(ECOINVENT_COPY, 17533.0), _candidate(OWN, 190560.0)])
        self.assertIsNone(kept)
        self.assertNotIn("yielded", finding.context)

    def test_nothing_is_published_where_every_row_gives_way(self):
        """Two copies of other publishers' rows: no own row to prefer."""
        kept, _ = _settle(
            [_candidate(ECOINVENT_COPY, 17533.0), _candidate(OWN, 190560.0)],
            yielding={ECOINVENT_COPY, OWN},
        )
        self.assertIsNone(kept)

    def test_nothing_is_published_where_the_own_rows_disagree(self):
        """Giving way removes a row; it does not choose between the rest."""
        kept, finding = _settle(
            [_candidate(ECOINVENT_COPY, 17533.0), _candidate(OWN, 190560.0), _candidate(OWN_AGAIN, 5.0)],
            yielding={ECOINVENT_COPY},
        )
        self.assertIsNone(kept)
        self.assertNotIn("yielded", finding.context)

    def test_rows_that_agree_never_ask(self):
        """An ecoinvent copy that agrees is published as before, with no finding."""
        kept, finding = _settle(
            [_candidate(ECOINVENT_COPY, 190560.0), _candidate(OWN, 190560.0)],
            yielding={ECOINVENT_COPY},
        )
        self.assertIsNotNone(kept)
        self.assertIsNone(finding)


class ManifestTestCase(unittest.TestCase):
    PATH = Path("bafu-2026-v1.json")

    def _spec(self, **extra):
        payload = {
            "adapter": "brightway_flows.integrations.greendelta_lcia:fetch",
            "factors": "factors.json",
            "methods": [{"name": "EF 3.1 Method (adapted)"}],
            "resolve_through": ["ecoinvent-3.12", "ecoinvent-3.8", "openlca-2.8.2"],
            **extra,
        }
        return LciaSpec.from_manifest(payload, path=self.PATH)

    def test_absent_means_nothing_gives_way(self):
        self.assertEqual(self._spec().yields_in_a_collision, ())

    def test_it_names_lists_from_the_chain(self):
        spec = self._spec(yields_in_a_collision=["ecoinvent-3.12", "ecoinvent-3.8"])
        self.assertEqual(spec.yields_in_a_collision, ("ecoinvent-3.12", "ecoinvent-3.8"))

    def test_a_list_outside_the_chain_is_refused(self):
        with self.assertRaises(ValueError):
            self._spec(yields_in_a_collision=["agribalyse-3.2"])

    def test_the_greendelta_manifest_gives_way_to_ecoinvent_only(self):
        from brightway_flows.lcia.sources import registered_lists

        spec = registered_lists()["bafu-2026-v1"].lcia
        self.assertEqual(spec.yields_in_a_collision, ("ecoinvent-3.12", "ecoinvent-3.8"))


if __name__ == "__main__":
    unittest.main()
