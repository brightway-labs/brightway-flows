"""A flow's list identity is given, never recovered from a display string.

`(list_name, list_version)` is published: it is what a `source_refs` entry
carries and what a row of `elementary_flow_sources` is keyed on.  Two places
used to re-derive that pair from `flow.source` -- a *display* string -- by
special-casing the base label, prefix-matching `ecoinvent-`, and otherwise
splitting on the first dash when the tail contained a digit.

`ecoinvent-3.12` survived that.  `US LCI`, `Stepwise 2006` and `ecoinvent 3.12`
would not have: each has no dash, so each would have shipped the whole display
string as the list name and an empty version, into both published places, and
nothing would have failed (#13).

So both places are asked instead.  The caller always has the list -- the
transform reads the base list, the merge consumes one it resolved -- and these
tests pin that the answer comes from there and from nowhere else.
"""

from __future__ import annotations

import unittest
from dataclasses import replace
from pathlib import Path

from brightway_flows.domain.context_registry import context_from_dict
from brightway_flows.domain.flow import Flow
from brightway_flows.flow_layers import resolve_flow_layers
from brightway_flows.pipeline import loading
from brightway_flows.pipeline.loading import _build_input_source_ref
from brightway_flows.sources import BASE_ROLE, SourceList, base_source_list

#: A list whose name has a space in it and whose display string is nothing like
#: its key.  The heuristic returned `("US LCI 1.0", "")` for this.
_SPACED = SourceList(
    list_name="US LCI",
    list_version="1.0",
    flows_path=Path("/nonexistent/us-lci-1.0.json"),
    declared_source_label="US LCI 1.0",
)

_ROW = {
    "uuid": "u-1",
    "name": "Carbon dioxide",
    "context": ["Emissions", "Emissions to air"],
    "unit": "kg",
}


#: Air of unstated height.  These fixtures said `["Air"]` back when the
#: field held anything; the context they meant is this one.
_AIR = context_from_dict(
    {"dimension": "Environmental", "media": "Air", "strata": "Unknown"}
)

class InputSourceRefTestCase(unittest.TestCase):
    """The reference attached to every row of the transform's input file."""

    def test_the_identity_comes_from_the_list(self):
        ref = _build_input_source_ref(
            {**_ROW, "source": _SPACED.source_label},
            source_list=replace(_SPACED, role=BASE_ROLE),
            input_file="/data/us-lci-1.0.json",
        )
        self.assertEqual(ref["list_name"], "US LCI")
        self.assertEqual(ref["list_version"], "1.0")

    def test_the_display_string_does_not_decide_it(self):
        """A row whose `source` says something else is still that list's row.

        It is read out of that list's flows file; there is no other way in.
        """
        ref = _build_input_source_ref(
            {**_ROW, "source": "whatever-the-vendor-wrote"},
            source_list=base_source_list(),
            input_file="/data/ef-31-flows.json",
        )
        base = base_source_list()
        self.assertEqual(ref["list_name"], base.list_name)
        self.assertEqual(ref["list_version"], base.list_version)

    def test_the_row_still_records_what_it_said(self):
        """The display string is metadata, not identity, and it is kept."""
        ref = _build_input_source_ref(
            {**_ROW, "source": "EF 3.1"},
            source_list=base_source_list(),
            input_file="/data/ef-31-flows.json",
        )
        self.assertEqual(ref["source_metadata"]["input_dataset"], "EF 3.1")
        self.assertEqual(
            ref["source_metadata"]["original_context"],
            ["Emissions", "Emissions to air"],
        )

    def test_it_asks_for_the_list(self):
        """The signature is the contract: nothing is inferred from the row."""
        import inspect

        self.assertIn(
            "source_list", inspect.signature(_build_input_source_ref).parameters
        )

    def test_the_parser_is_gone(self):
        for name in ("_parse_source_ref",):
            with self.subTest(name):
                self.assertFalse(hasattr(loading, name))


class LayeringSourceRefTestCase(unittest.TestCase):
    """The reference built for a flow that reaches the layering without one."""

    def _flow(self, source: str) -> Flow:
        return Flow(
            uuid="u-1",
            source=source,
            unit="kg",
            context=["Emissions", "Emissions to air"],
            prefLabel=[{"@value": "Carbon dioxide", "@language": "en"}],
        )

    def test_a_flow_with_no_reference_gets_the_list_it_was_told_about(self):
        _objects, elementary, _stats = resolve_flow_layers(
            [self._flow(_SPACED.source_label)], source_list=_SPACED
        )
        ref = elementary[0].source_refs[0]
        self.assertEqual(ref["list_name"], "US LCI")
        self.assertEqual(ref["list_version"], "1.0")

    def test_a_dash_in_the_display_string_is_not_a_version_boundary(self):
        """The case the heuristic was built for, and the reason it looked right.

        `ecoinvent-3.12` parsed correctly, which is why a list that did not
        could ship a blank version without anyone noticing.
        """
        stepwise = SourceList(
            list_name="Stepwise",
            list_version="2006",
            flows_path=Path("/nonexistent/stepwise-2006.json"),
            declared_source_label="Stepwise 2006",
        )
        _objects, elementary, _stats = resolve_flow_layers(
            [self._flow("Stepwise 2006")], source_list=stepwise
        )
        ref = elementary[0].source_refs[0]
        self.assertEqual((ref["list_name"], ref["list_version"]), ("Stepwise", "2006"))

    def test_deriving_one_is_counted(self):
        """It is the one place the identity is not already on the record.

        A build where this number moves is a build where something upstream
        stopped attaching references.
        """
        flow = self._flow(_SPACED.source_label)
        _objects, _elementary, stats = resolve_flow_layers(
            [flow], source_list=_SPACED
        )
        self.assertEqual(stats["derived_source_refs"], 1)

    def test_a_flow_that_brought_its_own_reference_keeps_it(self):
        """The transform's rows arrive with one, and it is not second-guessed."""
        flow = self._flow(_SPACED.source_label)
        flow.source_refs = [{
            "list_name": "ecoinvent",
            "list_version": "3.12",
            "source_flow_uuid": "u-1",
            "source_flow_name": "Carbon dioxide",
            "source_metadata": {},
        }]
        _objects, elementary, stats = resolve_flow_layers(
            [flow], source_list=_SPACED
        )
        ref = elementary[0].source_refs[0]
        self.assertEqual((ref["list_name"], ref["list_version"]), ("ecoinvent", "3.12"))
        self.assertEqual(stats["derived_source_refs"], 0)

    def test_it_asks_for_the_list(self):
        import inspect

        self.assertIn(
            "source_list", inspect.signature(resolve_flow_layers).parameters
        )


if __name__ == "__main__":
    unittest.main()
