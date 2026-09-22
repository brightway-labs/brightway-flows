"""The element name is written over a flow's own label only when ruled on.

Every flow that resolves to a `chemrof:ChemicalElement` used to be renamed to
that element's name, titlecased, unconditionally -- so a flow whose own name was
more specific than its object's lost that specificity at publication, and the
`Plutonium-alpha` -> `Plutonium` rejection then in `preferred-label-decisions.json`
could not stop it (#16).  That row is retired: #238 gave the aggregate its own
flow object, so the pair no longer reaches this pass at all.

What these pin is that the titlecase still happens where it is only a titlecase,
that anything else is a proposal the decisions file rules on, and that a refused
proposal reaches a curator rather than disappearing.
"""

import unittest

from brightway_flows.domain.flow import Flow
from brightway_flows.domain.flow_object import FlowObject
from brightway_flows.domain.labels import flow_label_value
from brightway_flows.domain.preferred_label_decisions import (
    APPROVE,
    DEFAULT_APPROVED_RULES,
    REJECT,
    LabelDecision,
    decision_key,
    load_preferred_label_decisions,
)
from brightway_flows.domain.vocabulary import CHEMROF_CHEMICAL_ELEMENT
from brightway_flows.pipeline.element_labels import ElementPrefLabelPass
from brightway_flows.pipeline.review_records import ReviewQueue, ReviewQueueProvider


def make_object(object_id: str, label: str, *, element: bool = True) -> FlowObject:
    return FlowObject(
        flow_object_id=object_id,
        prefLabel=[{"@value": label, "@language": "en"}],
        altLabel=[],
        properties={},
        references=[],
        created_from={},
        types=[CHEMROF_CHEMICAL_ELEMENT] if element else ["chemrof:ChemicalSubstance"],
    )


def make_flow(uuid: str, label: str, object_id: str, **kwargs) -> Flow:
    return Flow(
        uuid=uuid,
        source="EF 3.1",
        unit="kg",
        prefLabel=[{"@value": label, "@language": "en"}],
        flow_object_id=object_id,
        **kwargs,
    )


def ruling(current: str, replacement: str, decision: str) -> dict:
    return {
        decision_key(current, replacement): LabelDecision(
            current=current, replacement=replacement, decision=decision
        )
    }


class ElementPrefLabelTestCase(unittest.TestCase):
    def run_pass(self, flows, objects, decisions=None):
        element_labels = ElementPrefLabelPass(decisions=decisions or {})
        stats = element_labels.apply(flows, objects)
        return element_labels, stats

    def test_a_casing_difference_is_still_applied(self):
        """What the pass is for.  A source list says `nitrogen`, the published
        list says `Nitrogen`, and no curator is asked about the difference."""
        flow = make_flow("u-1", "nitrogen", "fo-1")
        _, stats = self.run_pass([flow], [make_object("fo-1", "nitrogen")])

        self.assertEqual(flow_label_value(flow), "Nitrogen")
        self.assertEqual(stats["titlecased"], 1)
        self.assertEqual(stats["undecided"], 0)

    def test_the_written_label_says_what_wrote_it(self):
        flow = make_flow("u-1", "nitrogen", "fo-1")
        self.run_pass([flow], [make_object("fo-1", "nitrogen")])

        provenance = flow.prefLabel[0]["source"]
        self.assertEqual(
            provenance["prov:wasGeneratedBy"], "flow_layers.pubchem_element_enrichment"
        )

    def test_a_more_specific_name_is_not_flattened_without_a_ruling(self):
        """The condition #16 is about: the flow's own name is more specific
        than its object's, so publishing the element's name would name a
        broader substance than the flow is."""
        flow = make_flow("u-1", "Plutonium-alpha", "fo-1")
        element_labels, stats = self.run_pass([flow], [make_object("fo-1", "plutonium")])

        self.assertEqual(flow_label_value(flow), "Plutonium-alpha")
        self.assertEqual(stats["undecided"], 1)
        self.assertEqual(stats["renamed"], 0)
        self.assertEqual(len(element_labels.undecided_label_replacements), 1)

    def test_a_rejected_rename_is_refused_and_not_queued(self):
        """A ruling is an answer, so it does not go back on the pile."""
        flow = make_flow("u-1", "Plutonium-alpha", "fo-1")
        element_labels, stats = self.run_pass(
            [flow],
            [make_object("fo-1", "plutonium")],
            decisions=ruling("Plutonium-alpha", "Plutonium", REJECT),
        )

        self.assertEqual(flow_label_value(flow), "Plutonium-alpha")
        self.assertEqual(stats["rejected"], 1)
        self.assertEqual(element_labels.review_queue_items(), [])

    def test_an_approved_rename_is_applied(self):
        flow = make_flow("u-1", "Plutonium-alpha", "fo-1")
        _, stats = self.run_pass(
            [flow],
            [make_object("fo-1", "plutonium")],
            decisions=ruling("Plutonium-alpha", "Plutonium", APPROVE),
        )

        self.assertEqual(flow_label_value(flow), "Plutonium")
        self.assertEqual(stats["renamed"], 1)

    def test_the_shipped_file_no_longer_needs_the_plutonium_row(self):
        """#238 retired it, and refusing by default is what replaces it.

        The row existed because this pass would otherwise publish `Plutonium`
        over `Plutonium-alpha`. It cannot now: the aggregate has its own flow
        object and never reaches an element here. Were the split ever to break,
        the label is still safe -- an unruled rename defers -- and the deferral
        is visible in the review queue, which a standing rejection would have
        hidden.
        """
        flow = make_flow("u-1", "Plutonium-alpha", "fo-1")
        element_labels, stats = self.run_pass(
            [flow],
            [make_object("fo-1", "plutonium")],
            decisions=load_preferred_label_decisions(),
        )

        self.assertEqual(flow_label_value(flow), "Plutonium-alpha")
        self.assertEqual(stats["rejected"], 0)
        self.assertEqual(stats["undecided"], 1)
        self.assertEqual(len(element_labels.review_queue_items()), 1)

    def test_a_flow_with_no_label_gets_one(self):
        """There is no replacement to rule on, and the alternative is
        publishing a flow with no label at all."""
        flow = make_flow("u-1", "", "fo-1")
        flow.prefLabel = []
        _, stats = self.run_pass([flow], [make_object("fo-1", "nitrogen")])

        self.assertEqual(flow_label_value(flow), "Nitrogen")
        self.assertEqual(stats["labelled"], 1)
        self.assertEqual(stats["undecided"], 0)

    def test_a_flow_whose_substance_is_not_an_element_is_untouched(self):
        flow = make_flow("u-1", "sodium chloride", "fo-1")
        _, stats = self.run_pass(
            [flow], [make_object("fo-1", "sodium chloride", element=False)]
        )

        self.assertEqual(flow_label_value(flow), "sodium chloride")
        self.assertEqual(stats["element_objects"], 0)

    def test_this_pass_is_not_trusted_by_default(self):
        """Trusting a rule by default is a claim about its error rate, measured
        over a full run.  Nothing has been measured about this one."""
        self.assertNotIn(ElementPrefLabelPass.name, DEFAULT_APPROVED_RULES)


class ElementRenameQueueTestCase(unittest.TestCase):
    """A rename that silently did not happen is work forgotten."""

    def queue(self, flows, objects):
        element_labels = ElementPrefLabelPass(decisions={})
        element_labels.apply(flows, objects)
        return element_labels.review_queue_items()

    def test_a_refused_rename_reaches_the_curator(self):
        items = self.queue(
            [make_flow("u-1", "Plutonium-alpha", "fo-1", cas_numbers=["7440-07-5"])],
            [make_object("fo-1", "plutonium")],
        )

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].queue_name, ReviewQueue.UNDECIDED_LABEL_REPLACEMENT)
        self.assertEqual(items[0].title, "Plutonium-alpha → Plutonium")
        self.assertEqual(items[0].cas, "7440-07-5")
        self.assertEqual(
            items[0].payload["rule"], "flow_layers.pubchem_element_enrichment"
        )

    def test_several_flows_of_one_pair_are_one_row(self):
        items = self.queue(
            [
                make_flow("u-1", "Plutonium-alpha", "fo-1"),
                make_flow("u-2", "plutonium-alpha", "fo-1"),
            ],
            [make_object("fo-1", "plutonium")],
        )

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].payload["flow_count"], 2)

    def test_the_queue_key_names_the_stage_that_proposed_the_pair(self):
        """`review_queue` is keyed on `(queue_name, item_key)`, and two stages
        can now propose the same rename -- one ruling binds both, but they are
        two rows of work, and a shared key would be a primary-key collision."""
        items = self.queue(
            [make_flow("u-1", "Plutonium-alpha", "fo-1")],
            [make_object("fo-1", "plutonium")],
        )

        self.assertTrue(
            items[0].item_key.startswith("flow_layers.pubchem_element_enrichment:")
        )

    def test_the_pass_is_a_queue_provider(self):
        """`collect_review_queue_items` asks whatever it is handed for its
        items; a pass that is not recognised as a provider produces none."""
        self.assertIsInstance(ElementPrefLabelPass(decisions={}), ReviewQueueProvider)


if __name__ == "__main__":
    unittest.main()
