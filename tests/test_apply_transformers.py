"""The transformer application loop, independent of where flows came from.

Extracted from `run_pipeline` so it can be called once per source list rather
than once per build.  Nothing tested it while it was inline, so these pin the
behaviour the sequential enrichment in #210 will depend on: every transformer
sees the whole list, changes apply last-writer-wins, and each changed field
records which transformer set it.
"""

import unittest

from brightway_flows.domain.flow import Flow
from brightway_flows.pipeline import Change, apply_transformers
from brightway_flows.sources import base_source_list

#: Which list these flows came from. `apply_transformers` asks for it and
#: does not work it out: the layering it runs needs a list identity for any
#: flow that arrives without `source_refs` (#13).
BASE = base_source_list()


class _Recorder:
    """A transformer that records what it was shown and proposes fixed changes."""

    def __init__(self, name, changes=()):
        self.name = name
        self._changes = list(changes)
        self.seen: list[list[str]] = []

    def setup(self) -> None:  # pragma: no cover - never called by this function
        raise AssertionError("setup() belongs to the caller, not the loop")

    def transform(self, flows):
        self.seen.append([f.uuid for f in flows])
        return list(self._changes)


def _flow(uuid, name="Carbon dioxide"):
    return Flow(uuid=uuid, source="EF 3.1", unit="kg",
                prefLabel=[{"@value": name, "@language": "en"}])


class ApplyTransformersTestCase(unittest.TestCase):
    def test_each_transformer_sees_every_flow(self):
        """Deduplication and consensus matching group across the list."""
        flows = [_flow("u-1"), _flow("u-2")]
        t = _Recorder("first")
        apply_transformers([t], flows, source_list=BASE)
        self.assertEqual(t.seen, [["u-1", "u-2"]])

    def test_a_change_is_applied_to_the_flow(self):
        flows = [_flow("u-1")]
        t = _Recorder("first", [Change("u-1", "unit", "m3")])
        apply_transformers([t], flows, source_list=BASE)
        self.assertEqual(flows[0].unit, "m3")

    def test_the_last_transformer_to_write_a_field_wins(self):
        flows = [_flow("u-1")]
        apply_transformers(
            [
                _Recorder("first", [Change("u-1", "unit", "m3")]),
                _Recorder("second", [Change("u-1", "unit", "kBq")]),
            ],
            flows,
            source_list=BASE,
        )
        self.assertEqual(flows[0].unit, "kBq")
        self.assertEqual(flows[0].pipeline_sources["unit"], "second")

    def test_the_change_log_records_what_each_change_replaced(self):
        flows = [_flow("u-1")]
        log = apply_transformers(
            [_Recorder("first", [Change("u-1", "unit", "m3", comment="why")])],
            flows,
            source_list=BASE,
        )
        self.assertEqual(len(log), 1)
        entry = log[0]
        self.assertEqual(entry.uuid, "u-1")
        self.assertEqual(entry.flow_name, "Carbon dioxide")
        self.assertEqual(entry.field_name, "unit")
        self.assertEqual(entry.old_value, "kg")
        self.assertEqual(entry.new_value, "m3")
        self.assertEqual(entry.transformer, "first")
        self.assertEqual(entry.comment, "why")

    def test_a_change_naming_an_unknown_flow_is_skipped(self):
        """A later list may propose against a uuid this call was not given."""
        flows = [_flow("u-1")]
        log = apply_transformers(
            [_Recorder("first", [Change("nope", "unit", "m3")])],
            flows,
            source_list=BASE,
        )
        self.assertEqual(log, [])
        self.assertEqual(flows[0].unit, "kg")

    def test_transformers_run_in_the_order_given(self):
        flows = [_flow("u-1")]
        log = apply_transformers(
            [
                _Recorder("first", [Change("u-1", "unit", "m3")]),
                _Recorder("second", [Change("u-1", "unit", "kBq")]),
            ],
            flows,
            source_list=BASE,
        )
        self.assertEqual([e.transformer for e in log], ["first", "second"])
        self.assertEqual([e.old_value for e in log], ["kg", "m3"])

    def test_setup_is_not_called(self):
        """It loads supplementary data once per build, not once per list."""
        flows = [_flow("u-1")]
        apply_transformers([_Recorder("first")], flows, source_list=BASE)  # _Recorder.setup raises


class AlreadyTransformedTestCase(unittest.TestCase):
    """A flow goes through this chain once (#213).

    The chain is ordered for a single pass over raw input and is not idempotent:
    `normalize_name_case` runs fifth and re-title-cases labels that
    `consensus_match` sets at fourteenth, and `rdkit_post_consensus` turns a
    settled property value into a list of near-duplicates.  So "has this been
    transformed?" is a property of
    the flow, which is what lets the merge hand over the consensus flows and a
    source list in one list without having to say which is which.
    """

    def test_a_flow_is_marked_afterwards(self):
        flows = [_flow("u-1")]
        apply_transformers([_Recorder("first")], flows, source_list=BASE)
        self.assertTrue(flows[0].transformed)

    def test_a_marked_flow_is_not_written_to(self):
        flows = [_flow("u-1"), _flow("s-1")]
        flows[0].transformed = True
        apply_transformers([_Recorder("first", [Change("u-1", "unit", "m3")])], flows, source_list=BASE)
        self.assertEqual(flows[0].unit, "kg")

    def test_an_unmarked_flow_in_the_same_list_still_is(self):
        flows = [_flow("u-1"), _flow("s-1")]
        flows[0].transformed = True
        apply_transformers([_Recorder("first", [Change("s-1", "unit", "m3")])], flows, source_list=BASE)
        self.assertEqual(flows[1].unit, "m3")

    def test_a_withheld_change_is_not_logged(self):
        """A change log naming changes that were not made is worse than none."""
        flows = [_flow("u-1"), _flow("s-1")]
        flows[0].transformed = True
        log = apply_transformers(
            [_Recorder("first", [
                Change("u-1", "unit", "m3"), Change("s-1", "unit", "m3"),
            ])],
            flows,
            source_list=BASE,
        )
        self.assertEqual([e.uuid for e in log], ["s-1"])

    def test_a_marked_flow_is_still_shown(self):
        """Narrowing what is written must not narrow what is seen: this is what
        deduplication and consensus matching group across."""
        flows = [_flow("u-1"), _flow("s-1")]
        flows[0].transformed = True
        t = _Recorder("first")
        apply_transformers([t], flows, source_list=BASE)
        self.assertEqual(t.seen, [["u-1", "s-1"]])

    def test_marking_happens_after_the_chain_not_during(self):
        """Marking a flow as each transformer finished with it would make every
        later transformer in the same pass skip it."""
        flows = [_flow("u-1")]
        apply_transformers(
            [
                _Recorder("first", [Change("u-1", "unit", "m3")]),
                _Recorder("second", [Change("u-1", "unit", "kBq")]),
            ],
            flows,
            source_list=BASE,
        )
        self.assertEqual(flows[0].unit, "kBq")

    def test_running_the_same_chain_twice_changes_nothing_the_second_time(self):
        """The invariant the flag exists for."""
        flows = [_flow("u-1")]
        transformers = [_Recorder("first", [Change("u-1", "unit", "m3")])]
        apply_transformers(transformers, flows, source_list=BASE)
        second = apply_transformers(transformers, flows, source_list=BASE)
        self.assertEqual(second, [])
        self.assertEqual(flows[0].unit, "m3")


class AnswersPerFlowTestCase(unittest.TestCase):
    """Which flows a transformer is shown, given what it does with them (#88).

    A transformer whose answer for a flow depends only on that flow is shown
    only the flows the chain can still write to.  It is not a narrowing of what
    the chain does -- the loop already discarded whatever such a transformer
    proposed for a finished flow -- it is a refusal to compute it first.
    """

    def test_a_per_flow_transformer_is_not_shown_finished_flows(self):
        flows = [_flow("u-1"), _flow("s-1")]
        flows[0].transformed = True
        t = _Recorder("first")
        t.answers_per_flow = True
        apply_transformers([t], flows, source_list=BASE)
        self.assertEqual(t.seen, [["s-1"]])

    def test_a_whole_list_transformer_is_still_shown_everything(self):
        """`consensus_match` asks whether two lists agree, and cannot be told
        only about one of them."""
        flows = [_flow("u-1"), _flow("s-1")]
        flows[0].transformed = True
        t = _Recorder("first")
        t.answers_per_flow = False
        apply_transformers([t], flows, source_list=BASE)
        self.assertEqual(t.seen, [["u-1", "s-1"]])

    def test_a_transformer_that_never_heard_of_the_flag_is_shown_everything(self):
        """A transformer is anything with `name` and `transform`; one that does
        not declare gets the answer that cannot be wrong."""
        flows = [_flow("u-1"), _flow("s-1")]
        flows[0].transformed = True
        t = _Recorder("first")
        self.assertFalse(hasattr(t, "answers_per_flow"))
        apply_transformers([t], flows, source_list=BASE)
        self.assertEqual(t.seen, [["u-1", "s-1"]])

    def test_the_base_list_run_is_shown_the_list_itself(self):
        """Nothing is finished on the transform stage, so there is nothing to
        hide and no copy to make -- the run is what it was before this existed."""
        flows = [_flow("u-1"), _flow("s-1")]
        t = _Recorder("first")
        t.answers_per_flow = True
        seen_objects = []
        t.transform = lambda shown: seen_objects.append(shown) or []
        apply_transformers([t], flows, source_list=BASE)
        self.assertIs(seen_objects[0], flows)

    def test_a_per_flow_transformer_can_still_write_to_what_it_was_shown(self):
        flows = [_flow("u-1"), _flow("s-1")]
        flows[0].transformed = True
        t = _Recorder("first", [Change("s-1", "unit", "m3")])
        t.answers_per_flow = True
        apply_transformers([t], flows, source_list=BASE)
        self.assertEqual(flows[1].unit, "m3")


class RegisteredChainClassificationTestCase(unittest.TestCase):
    """Which of the shipped transformers ask a question about the whole set.

    Pinned rather than derived, because getting it wrong is silent: a
    transformer wrongly marked per-flow keeps working on the base list, where
    nothing is hidden, and quietly answers a different question on every merge
    after it.  Adding a transformer to this set costs a build nothing; removing
    one from it is a claim that has to be checked against what it reads.
    """

    #: `consensus_match` needs the lists already merged to agree with.
    #: `rdkit_authoritative` asks whether a structure is unique in the build.
    #: `strip_cross_object_altlabels` asks whether a name belongs to some other
    #: object.  `strip_element_symbol_altlabels` first decides which flow object
    #: *is* the element for each symbol.  Each of those is a question about the
    #: set, and each is normally answered by consensus flows.
    WHOLE_LIST = {
        "consensus_match",
        "rdkit_authoritative",
        "registry_number_from_name",
        "strip_cross_object_altlabels",
        "strip_element_symbol_altlabels",
    }

    def test_exactly_the_whole_list_transformers_are_shown_everything(self):
        from brightway_flows.transformers import DEFAULT_TRANSFORMERS

        whole_list = {
            cls.name for cls in DEFAULT_TRANSFORMERS if not cls.answers_per_flow
        }
        self.assertEqual(whole_list, self.WHOLE_LIST)

    def test_every_registered_transformer_has_decided(self):
        from brightway_flows.transformers import DEFAULT_TRANSFORMERS

        for cls in DEFAULT_TRANSFORMERS:
            with self.subTest(transformer=cls.name):
                self.assertIsInstance(cls.answers_per_flow, bool)


if __name__ == "__main__":
    unittest.main()
