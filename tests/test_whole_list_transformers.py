"""The four whole-list transformers index over everything and decide over less.

`answers_per_flow` is a single flag, and these four say `False` to it because
each asks a question about the *set*.  But only the first half of each asks it.
The second half decides flow by flow, and `apply_transformers` drops a proposal
for a flow that is already `transformed` -- so deriving one is the work #88 is
about, one level further in than #91 reached.

Both halves need pinning, and the first is the one that would go wrong quietly:
a run that narrowed the *index* would stop finding the collisions these
transformers exist to find, and would still pass every test that only checks
what they propose.
"""

import unittest

from brightway_flows.domain.flow import Flow
from brightway_flows.domain.vocabulary import CHEMROF_MOLECULAR_FORMULA
from brightway_flows.pipeline import writable_flows
from brightway_flows.transformers.strip_cross_object_altlabels import (
    StripCrossObjectAltLabelsTransformer,
)
from brightway_flows.transformers.strip_element_symbol_altlabels import (
    StripElementSymbolAltLabelsTransformer,
)

def _flow(uuid, name, *, alt=(), transformed=False, object_id="", formula=None):
    flow = Flow(
        uuid=uuid,
        source="EF 3.1",
        unit="kg",
        prefLabel=[{"@value": name, "@language": "en"}],
        altLabel=[{"@value": value, "@language": "en"} for value in alt],
    )
    flow.transformed = transformed
    flow.flow_object_id = object_id
    if formula:
        flow.properties = {CHEMROF_MOLECULAR_FORMULA: {"@value": [formula]}}
    return flow


class WritableFlowsTestCase(unittest.TestCase):
    def test_it_is_the_flows_a_change_can_still_be_applied_to(self):
        flows = [_flow("u-1", "A", transformed=True), _flow("u-2", "B")]
        self.assertEqual([f.uuid for f in writable_flows(flows)], ["u-2"])

    def test_on_the_transform_stage_it_is_the_whole_list(self):
        """Nothing is finished until the chain has run, so the base list's run
        is what it was before this existed."""
        flows = [_flow("u-1", "A"), _flow("u-2", "B")]
        self.assertEqual([f.uuid for f in writable_flows(flows)], ["u-1", "u-2"])


class StripCrossObjectAltLabelsTestCase(unittest.TestCase):
    """"Is this synonym some other substance's name?" -- asked of every flow."""

    def test_a_finished_flow_still_claims_its_name(self):
        """The index has to see the consensus, or the rule is inert on a merge:
        the substance whose name the synonym belongs to is normally a flow the
        call cannot write to."""
        flows = [
            _flow("consensus", "Arsane", transformed=True),
            _flow("arriving", "Arsenic", alt=["Arsane"]),
        ]
        changes = StripCrossObjectAltLabelsTransformer().transform(flows)
        self.assertEqual([c.uuid for c in changes], ["arriving"])
        self.assertEqual(changes[0].new_value, [])

    def test_nothing_is_proposed_for_a_finished_flow(self):
        """It would be dropped on arrival, so it is not derived."""
        flows = [
            _flow("consensus", "Arsenic", alt=["Arsane"], transformed=True),
            _flow("arriving", "Arsane"),
        ]
        self.assertEqual(StripCrossObjectAltLabelsTransformer().transform(flows), [])

    def test_the_base_list_run_is_unchanged(self):
        """Nothing is finished, so every flow is decided about, as before."""
        flows = [
            _flow("u-1", "Arsenic", alt=["Arsane"]),
            _flow("u-2", "Arsane"),
        ]
        changes = StripCrossObjectAltLabelsTransformer().transform(flows)
        self.assertEqual([c.uuid for c in changes], ["u-1"])


class StripElementSymbolAltLabelsTestCase(unittest.TestCase):
    """Which substance *is* the element for each symbol -- decided over everything."""

    def _transformer(self):
        transformer = StripElementSymbolAltLabelsTransformer()
        transformer._element_symbols = frozenset({"Rn", "Na"})
        transformer._form_to_symbol = {
            "Rn": "Rn", "[Rn]": "Rn", "Na": "Na", "[Na]": "Na",
        }
        return transformer

    def test_a_finished_flow_can_be_the_element(self):
        """Pass 1 sees every flow: on a merge the element itself is a consensus
        flow, and an unclaimed symbol makes the rule inert."""
        flows = [
            _flow("consensus", "Radon", object_id="fo-radon",
                  formula="Rn", transformed=True),
            _flow("arriving", "Niton", alt=["Rn"], object_id="fo-other"),
        ]
        changes = self._transformer().transform(flows)
        self.assertEqual([c.uuid for c in changes], ["arriving"])

    def test_nothing_is_proposed_for_a_finished_flow(self):
        flows = [
            _flow("element", "Radon", object_id="fo-radon", formula="Rn"),
            _flow("consensus", "Niton", alt=["Rn"], object_id="fo-other",
                  transformed=True),
        ]
        self.assertEqual(self._transformer().transform(flows), [])

    def test_the_base_list_run_is_unchanged(self):
        flows = [
            _flow("u-1", "Radon", object_id="fo-radon", formula="Rn"),
            _flow("u-2", "Niton", alt=["Rn"], object_id="fo-other"),
        ]
        changes = self._transformer().transform(flows)
        self.assertEqual([c.uuid for c in changes], ["u-2"])


if __name__ == "__main__":
    unittest.main()
