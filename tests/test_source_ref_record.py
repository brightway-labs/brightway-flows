"""One record for a source reference, and the shape it publishes is unmoved.

#92 counted three models of "which source list a flow came from":
`domain.models.SourceRef` (Pydantic, reached only as the element type of
`HarmonisedFlow.source_refs`), `flow_layers.layering.FlowSourceRef` (a
dataclass with the identical five fields, `asdict()`-ed on the line after it was
built) and `webapps.app.queries.flows.SourceReference` (the read side). What was
actually stored was a bare dict, and every reader did `ref.get("list_name")`.

`docs/reference/architecture.md` names the rule: *avoid parallel models for the
same concept*.

Two things have to hold for the consolidation to be safe, and neither is
obvious:

1. **The published shape must not move.** These references reach
   `elementary_flow_sources`, which is the only copy of them anything keeps
   (#30), so a reordered or renamed key is a published change.
2. **The boundary must still validate.** The Pydantic model was doing real work
   as `HarmonisedFlow`'s field type. Pydantic validates a stdlib dataclass the
   same way -- but that is a fact about Pydantic, not an obvious one, and if it
   ever stops being true the input-file check disappears silently.
"""

from __future__ import annotations

import unittest

import pydantic

from brightway_flows.domain.models import HarmonisedFlow
from brightway_flows.domain.source_ref import SourceRef

_REFERENCE = {
    "list_name": "EF",
    "list_version": "3.1",
    "source_flow_uuid": "u-1",
    "source_flow_name": "Carbon dioxide",
    "source_metadata": {"original_context": ["air", "unspecified"]},
}


class ThePublishedShapeIsUnmovedTestCase(unittest.TestCase):
    def test_the_keys_and_their_order_are_what_asdict_produced(self):
        """`asdict()` emitted declaration order; so does `to_dict()`."""
        self.assertEqual(
            list(SourceRef.from_dict(_REFERENCE).to_dict()),
            [
                "list_name",
                "list_version",
                "source_flow_uuid",
                "source_flow_name",
                "source_metadata",
            ],
        )

    def test_a_reference_round_trips(self):
        self.assertEqual(SourceRef.from_dict(_REFERENCE).to_dict(), _REFERENCE)

    def test_a_list_version_may_be_absent(self):
        """The Pydantic model defaulted it, so an input file naming a list
        without pinning a release still validated.  `kw_only` is what lets the
        dataclass keep both that default and its place in the key order."""
        without = {k: v for k, v in _REFERENCE.items() if k != "list_version"}
        self.assertEqual(SourceRef.from_dict(without).list_version, "")


class TheBoundaryStillValidatesTestCase(unittest.TestCase):
    """`HarmonisedFlow.source_refs` is `list[SourceRef]`, and that is not
    decoration: it is the check on an input file's references."""

    def test_a_reference_reaches_the_model_as_a_record(self):
        flow = HarmonisedFlow.from_dict({"uuid": "u-1", "source_refs": [_REFERENCE]})
        self.assertIsInstance(flow.source_refs[0], SourceRef)
        self.assertEqual(flow.source_refs[0].list_name, "EF")

    def test_a_flow_serialises_its_references_unchanged(self):
        payload = {"uuid": "u-1", "source_refs": [_REFERENCE]}
        self.assertEqual(
            HarmonisedFlow.from_dict(payload).to_dict()["source_refs"], [_REFERENCE]
        )

    def test_a_reference_missing_a_required_field_is_refused(self):
        with self.assertRaises(pydantic.ValidationError):
            HarmonisedFlow.from_dict({
                "uuid": "u-1",
                "source_refs": [{"list_name": "EF"}],
            })


class TheOldModelsAreGoneTestCase(unittest.TestCase):
    """Pinned rather than trusted: re-adding either is one line, and the point
    of the consolidation is that the next reference has one place to be."""

    def test_the_layering_no_longer_declares_its_own(self):
        import brightway_flows.flow_layers.layering as layering

        self.assertFalse(hasattr(layering, "FlowSourceRef"))

    def test_the_layering_builds_the_shared_record(self):
        import brightway_flows.flow_layers.layering as layering

        self.assertIs(layering.SourceRef, SourceRef)


if __name__ == "__main__":
    unittest.main()
