"""Contexts are rejected when they are not contexts, or contradict their IRI.

Two checks, at two points.  `Flow.context` is a `Context`, so a record cannot
hold a shape the vocabulary would refuse -- the codec builds one on the way in
and the constructor's validators run.  What a record *can* hold is a valid
context filed under the wrong IRI, and a flow the mapping placed nowhere; both
are `validate_flow_contexts`, the gate every flow passes after the transformer
chain and before any artifact is written (#97).
"""

import unittest

from brightway_flows.domain.context import (
    Context,
    Dimension,
    Media,
    WaterBody,
)
from brightway_flows.domain.context_registry import (
    InvalidContextError,
    check_context_against_iri,
    context_dict_for_iri,
    context_from_dict,
    validate_flow_contexts,
)
from brightway_flows.domain.flow import Flow, ProvidedValues
from brightway_flows.domain.models import HarmonisedFlow

SUWA = "https://vocab.brightway.one/flow-contexts/envi-wate-suwa"
OCEAN = "https://vocab.brightway.one/flow-contexts/envi-wate-ocea"

# The shape produced by the deleted positional parser: the water body landed in
# `strata`.  It is the canonical example of a context that is both unconstructible
# and inconsistent with its own IRI.
CORRUPTED = {"dimension": "Environmental", "media": "Water", "strata": "Surface water"}


class ContextFromDictTestCase(unittest.TestCase):
    def test_values_are_coerced_to_enum_members(self):
        """Bare strings satisfy StrEnum comparisons but break to_list()."""
        context = context_from_dict(context_dict_for_iri(SUWA))
        self.assertIsInstance(context.dimension, Dimension)
        self.assertIsInstance(context.media, Media)
        self.assertIsInstance(context.water_body, WaterBody)
        self.assertEqual(context.to_list(), ["Environmental", "Water", "Surface water"])

    def test_round_trips_through_the_registry(self):
        as_dict = context_dict_for_iri(SUWA)
        self.assertEqual(context_from_dict(as_dict), Context(
            dimension=Dimension.ENVIRONMENTAL,
            media=Media.WATER,
            water_body=WaterBody.SURFACE_WATER,
        ))

    def test_rejects_the_corrupted_shape(self):
        with self.assertRaises(InvalidContextError):
            context_from_dict(CORRUPTED)

    def test_rejects_unknown_field(self):
        with self.assertRaises(InvalidContextError) as ctx:
            context_from_dict({"dimension": "Environmental", "media": "Air",
                               "strata": "Unknown", "nonsense": "x"})
        self.assertIn("nonsense", str(ctx.exception))

    def test_rejects_unknown_value(self):
        with self.assertRaises(InvalidContextError) as ctx:
            context_from_dict({"dimension": "Environmental", "media": "Water",
                               "water_body": "Lava"})
        self.assertIn("water_body", str(ctx.exception))

    def test_rejects_prohibited_combination(self):
        """Water media with no water body — a rule from the shared model."""
        with self.assertRaises(InvalidContextError):
            context_from_dict({"dimension": "Environmental", "media": "Water"})

    def test_rejects_missing_dimension(self):
        with self.assertRaises(InvalidContextError):
            context_from_dict({"media": "Water", "water_body": "Ocean"})


class CheckContextAgainstIRITestCase(unittest.TestCase):
    def test_valid_pair_passes(self):
        self.assertIsNone(
            check_context_against_iri(context_dict_for_iri(SUWA), SUWA)
        )

    def test_raw_list_context_is_skipped(self):
        """Pre-mapping source form; there is nothing structured to check yet."""
        self.assertIsNone(
            check_context_against_iri(["Emissions", "Emissions to air"], "")
        )
        self.assertIsNone(check_context_against_iri([], ""))
        self.assertIsNone(check_context_against_iri({}, ""))

    def test_corrupted_context_is_reported(self):
        problem = check_context_against_iri(CORRUPTED, SUWA)
        self.assertIsNotNone(problem)
        self.assertIn("invalid context", problem)

    def test_valid_context_contradicting_its_iri_is_reported(self):
        """Both sides are individually valid but describe different contexts."""
        ocean = context_dict_for_iri(
            "https://vocab.brightway.one/flow-contexts/envi-wate-ocea"
        )
        problem = check_context_against_iri(ocean, SUWA)
        self.assertIsNotNone(problem)
        self.assertIn("does not match context_iri", problem)

    def test_unregistered_iri_is_reported(self):
        problem = check_context_against_iri(
            context_dict_for_iri(SUWA),
            "https://vocab.brightway.one/flow-contexts/nope",
        )
        self.assertIsNotNone(problem)
        self.assertIn("not in the consensus vocabulary", problem)

    def test_structured_context_without_an_iri_still_must_be_valid(self):
        self.assertIsNotNone(check_context_against_iri(CORRUPTED, ""))
        self.assertIsNone(check_context_against_iri(context_dict_for_iri(SUWA), ""))


class ValidateFlowContextsTestCase(unittest.TestCase):
    def test_clean_flows_produce_no_problems(self):
        flows = [
            {"uuid": "a", "source": "EF 3.1",
             "context": context_dict_for_iri(SUWA), "context_iri": SUWA},
            {"uuid": "b", "source": "EF 3.1",
             "context": context_dict_for_iri(OCEAN), "context_iri": OCEAN},
        ]
        self.assertEqual(validate_flow_contexts(flows), [])

    def test_a_flow_the_mapping_never_placed_stops_the_run(self):
        """It used to pass: the flow kept the compartment strings its source
        list shipped, and this function skipped anything that was not a dict.
        Publishing it puts one list's own vocabulary into an artifact that is
        supposed to have none (#97)."""
        problems = validate_flow_contexts([
            Flow(uuid="unplaced", source="EF 3.1", provided=ProvidedValues(
                context=["Emissions", "Emissions to air"],
            )),
        ])
        self.assertEqual(len(problems), 1)
        self.assertIn("no consensus context", problems[0])
        self.assertIn("Emissions to air", problems[0])

    def test_corrupted_flow_is_reported_with_identity(self):
        flows = [
            {"uuid": "good", "source": "EF 3.1",
             "context": context_dict_for_iri(SUWA), "context_iri": SUWA},
            {"uuid": "bad", "source": "ecoinvent manual addition",
             "context": CORRUPTED, "context_iri": SUWA},
        ]
        problems = validate_flow_contexts(flows)
        self.assertEqual(len(problems), 1)
        self.assertIn("bad", problems[0])
        self.assertIn("ecoinvent manual addition", problems[0])

    def test_falls_back_to_elementary_flow_id_for_identity(self):
        problems = validate_flow_contexts(
            [{"elementary_flow_id": "ef-1", "context": CORRUPTED, "context_iri": SUWA}]
        )
        self.assertEqual(len(problems), 1)
        self.assertIn("ef-1", problems[0])


class FlowRecordContextTestCase(unittest.TestCase):
    """Where the boundary check moved to, and why.

    It was a Pydantic model validator on `HarmonisedFlow`, which reads *input
    files*.  An input file ships a compartment path and no `context_iri`, so the
    validator's own "skip the raw list form" branch skipped every row it ever
    saw.  The check belongs to the record that holds a consensus context, and to
    the run-wide gate that reads it (#97).
    """

    def test_a_record_refuses_a_context_that_is_not_one(self):
        with self.assertRaises(InvalidContextError):
            Flow.from_dict({"uuid": "u1", "source": "EF 3.1", "context": CORRUPTED})

    def test_the_gate_catches_a_context_that_contradicts_its_iri(self):
        """Both are constructible contexts, so nothing before the gate objects:
        this is a flow filed under the wrong IRI, not a malformed one."""
        flow = Flow.from_dict(
            {"uuid": "u2", "context": context_dict_for_iri(OCEAN), "context_iri": SUWA}
        )
        problems = validate_flow_contexts([flow])
        self.assertEqual(len(problems), 1)
        self.assertIn("does not match context_iri", problems[0])

    def test_an_input_boundary_carries_a_compartment_and_passes(self):
        """Every real input file supplies a raw list and no context_iri."""
        flow = HarmonisedFlow.from_dict(
            {"uuid": "u3", "source": "EF 3.1", "unit": "kg",
             "context": ["Emissions", "Emissions to air", "Emissions to air, indoor"]}
        )
        self.assertEqual(flow.context_iri, "")
        self.assertEqual(
            flow.context,
            ["Emissions", "Emissions to air", "Emissions to air, indoor"],
        )

    def test_a_consistent_context_survives_the_round_trip(self):
        as_dict = context_dict_for_iri(SUWA)
        flow = Flow.from_dict(
            {"uuid": "u4", "unit": "kg", "context": as_dict, "context_iri": SUWA}
        )
        self.assertEqual(flow.to_dict()["context"], as_dict)
        self.assertEqual(validate_flow_contexts([flow]), [])


if __name__ == "__main__":
    unittest.main()
