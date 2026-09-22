"""A ChEBI synonym's primary sources are ChEBI and the flow's list, not itself.

`_chebi_label_source` opened every provenance row it wrote with
`label:<the synonym itself>` (#250).  That is not a source: it names the string
the row is attached to, which `@value` already says.  It reached 258,206 of the
2,012,182 published elementary-flow alternative labels -- every row this
transformer writes -- and, once #247 carried label provenance onto flow
objects, it was published there too.

It was also captured before `strip_markup` ran, so it held the raw ChEBI
string.  For `N-D-Glucosyl-(2)-N'-nitrosomethylharnstoff` that made this field
the last place an unresolved `&#39;` reached a published artifact -- the exact
string `strip_markup`'s docstring names as the reason it resolves character
references at all.
"""

from __future__ import annotations

import unittest

from brightway_flows.domain.context_registry import context_from_dict
from brightway_flows.domain.flow import Flow
from brightway_flows.domain.labels import coerce_alt_labels
from brightway_flows.transformers.chebi_altlabels import ChebiAltLabelsTransformer

_CHEBI_IRI = "http://purl.obolibrary.org/obo/CHEBI_82334"

#: The escaped synonym, verbatim as ChEBI publishes it.  Its resolved form is
#: what gets published as a label.
_ESCAPED = "N-D-Glucosyl-(2)-N&#39;-nitrosomethylharnstoff"
_RESOLVED = "N-D-Glucosyl-(2)-N'-nitrosomethylharnstoff"


def _transformer(synonyms: list[str]) -> ChebiAltLabelsTransformer:
    """A transformer with a stubbed index, so `setup()` need not read ChEBI."""
    transformer = ChebiAltLabelsTransformer()
    transformer._chebi_records = {
        _CHEBI_IRI: {"synonyms": synonyms, "cas_numbers": ["142-83-6"]}
    }
    transformer._chebi_by_cas = {"142-83-6": [_CHEBI_IRI]}
    return transformer


def _flow() -> Flow:
    return Flow(
        uuid="u-1",
        source="EF 3.1",
        unit="kg",
        context=context_from_dict(
            {"dimension": "Environmental", "media": "Air", "strata": "Unknown"}
        ),
        cas_numbers=["142-83-6"],
        prefLabel=[{"@value": "Hexa-2,4-dienal", "@language": "en"}],
    )


def _labels(synonyms: list[str]):
    changes = _transformer(synonyms).transform([_flow()])
    assert changes, "the transformer proposed nothing to assert about"
    return coerce_alt_labels(changes[0].new_value)


class ChebiLabelSourceTestCase(unittest.TestCase):
    def test_the_synonym_is_not_its_own_primary_source(self):
        label = _labels(["(2E,4E)-hexa-2,4-dienal"])[0]
        self.assertNotIn(
            f"label:{label.value}", label.source["prov:hadPrimarySource"]
        )

    def test_no_primary_source_names_a_label_at_all(self):
        for label in _labels(["(2E,4E)-hexa-2,4-dienal", "sorbaldehyde"]):
            with self.subTest(label.value):
                hints = [
                    source
                    for source in label.source["prov:hadPrimarySource"]
                    if source.startswith("label:")
                ]
                self.assertEqual(hints, [])

    def test_the_real_sources_are_still_there(self):
        label = _labels(["(2E,4E)-hexa-2,4-dienal"])[0]
        self.assertEqual(
            label.source["prov:hadPrimarySource"], [_CHEBI_IRI, "EF 3.1"]
        )

    def test_the_activity_and_derivation_are_untouched(self):
        label = _labels(["(2E,4E)-hexa-2,4-dienal"])[0]
        self.assertEqual(label.source["prov:wasGeneratedBy"], "chebi_altlabels")
        self.assertEqual(
            label.source["prov:wasDerivedFrom"], "chebi synonym match"
        )

    def test_a_flow_with_no_source_list_still_gets_the_chebi_record(self):
        transformer = _transformer(["(2E,4E)-hexa-2,4-dienal"])
        flow = _flow()
        flow.source = ""
        changes = transformer.transform([flow])
        label = coerce_alt_labels(changes[0].new_value)[0]
        self.assertEqual(label.source["prov:hadPrimarySource"], [_CHEBI_IRI])


class UnresolvedMarkupTestCase(unittest.TestCase):
    """The 12 rows where the hint was not merely redundant but wrong."""

    def test_the_escaped_form_reaches_no_primary_source(self):
        for label in _labels([_ESCAPED]):
            with self.subTest(label.value):
                for source in label.source["prov:hadPrimarySource"]:
                    self.assertNotIn("&#39;", source)

    def test_the_label_itself_still_resolves_its_references(self):
        """Unchanged by this fix, and the reason the hint disagreed with it."""
        label = _labels([_ESCAPED])[0]
        self.assertEqual(label.value, _RESOLVED)


if __name__ == "__main__":
    unittest.main()
