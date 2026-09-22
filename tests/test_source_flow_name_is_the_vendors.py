"""A published mapping names the vendor's row the way the vendor did.

#149: `elementary_flow_sources.source_flow_name` is documented as "verbatim as
the source list wrote them, not normalised", and EF 3.1's rows honour that.
The merged lists did not.  A merged list is enriched before it is matched, and
the merge built each row's name as the label enrichment settled on, then wrote
that name into the mapping -- so BAFU's `Zinc II` was published as having been
called `Zinc(2+)`, while `Cadmium II` one row over, which enrichment happened
not to rename, kept its string.  About 5,300 rows across ecoinvent 3.12, 3.8
and BAFU published this list's name for the row where the vendor's belongs.

The fix keeps two names on the row: `name`, what the merge matches on, and
`shipped_name`, what the vendor wrote (`flow.provided.name`, which is what the
merge already reads for the row's compartment).  Every writer of a mapping
publishes the second.  These tests cover the matched path; the created path is
in `test_merge_creations.py`.
"""

from __future__ import annotations

import unittest

from brightway_flows.domain.elementary_flow import ElementaryFlow
from brightway_flows.domain.context_registry import context_for_iri
from brightway_flows.merge.provenance import _append_source_ref
from brightway_flows.merge.state import SourceRow
from brightway_flows.sources import resolve_source_list

AIR = "https://vocab.brightway.one/flow-contexts/envi-air-grle-ur10pesq"


def _row(name: str, shipped_name: str = "") -> SourceRow:
    return SourceRow(
        uuid="2dfdcb86-5a4f-5237-aaa6-97f2c69f4643",
        name=name,
        synonyms=[],
        labels=[name],
        context=["emissions to air", "high. pop."],
        context_iri=AIR,
        context_normalized=("Environmental", "Air"),
        unit="kg",
        unit_iri="",
        cas="23713-49-7",
        ec="",
        shipped_name=shipped_name,
    )


def _target() -> ElementaryFlow:
    return ElementaryFlow(
        elementary_flow_id="26c4d73c-92c3-4f08-a8d1-62f99bbb7676",
        flow_object_id="fo-2a649a3e6abb5944",
        source="EF 3.1",
        context=context_for_iri(AIR),
        context_iri=AIR,
        unit="kg",
        unit_iri="",
        lcia_methods=[],
        general_comment="",
    )


def _append(row: SourceRow, target: ElementaryFlow) -> dict:
    _append_source_ref(
        target,
        source=resolve_source_list("bafu-2026-v1"),
        source_uuid=row.uuid,
        source_name=row.name,
        source_shipped_name=row.shipped_name,
        source_context=row.context,
        source_unit=row.unit,
        source_cas=row.cas,
        source_ec=row.ec,
        merge_basis="cas",
        merge_method="algorithm",
        selector_reason="exact-context-iri-match",
        mapping_file="",
        provenance={},
    )
    return target.source_refs[0]


class TheMappingNamesTheVendorsRow(unittest.TestCase):
    def test_the_vendors_name_is_published_not_the_enriched_one(self):
        # The worked example.  BAFU wrote `Zinc II`; enrichment renamed the row
        # `Zinc(2+)` because two vocabularies agree on that spelling for its
        # number, and the merge matched on the renamed one.  The mapping says
        # what BAFU said.
        ref = _append(_row("Zinc(2+)", shipped_name="Zinc II"), _target())
        self.assertEqual(ref["source_flow_name"], "Zinc II")

    def test_the_merge_still_matches_on_the_enriched_name(self):
        # Not a rename of the row: `name` is what matching reads and is left
        # alone.  Only what the mapping *records* changes.
        row = _row("Zinc(2+)", shipped_name="Zinc II")
        self.assertEqual(row.name, "Zinc(2+)")
        self.assertEqual(row.vendor_name, "Zinc II")

    def test_a_row_without_a_shipped_name_falls_back_to_the_one_it_has(self):
        # The other half.  A row built without a record -- a fixture, a path
        # that never saw `provided` -- has no vendor string, and publishing an
        # empty one would be worse than publishing the name it matched on.
        ref = _append(_row("Cadmium II"), _target())
        self.assertEqual(ref["source_flow_name"], "Cadmium II")
        self.assertEqual(_row("Cadmium II").vendor_name, "Cadmium II")

    def test_the_shipped_name_survives_being_left_out_by_a_caller(self):
        # `_append_source_ref` has callers that predate the field; one that
        # does not pass it must publish the name it did pass, not raise.
        target = _target()
        _append_source_ref(
            target,
            source=resolve_source_list("bafu-2026-v1"),
            source_uuid="u",
            source_name="Cadmium II",
            source_context=["emissions to air"],
            source_unit="kg",
            source_cas="",
            source_ec="",
            merge_basis="label",
            merge_method="algorithm",
            selector_reason="",
            mapping_file="",
            provenance={},
        )
        self.assertEqual(target.source_refs[0]["source_flow_name"], "Cadmium II")


if __name__ == "__main__":
    unittest.main()
