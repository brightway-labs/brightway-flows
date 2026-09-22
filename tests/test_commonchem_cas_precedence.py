"""A registry number outranks a name, so a name match cannot overwrite a CAS.

`commonchem_cas_review` used to treat an exact name match in Common Chemistry as
definitive and *replace* the flow's CAS with it.  Common Chemistry is definitive
about which number a name maps to; that is not the same claim as "this flow,
which carries number Y and calls itself N, is wrong about Y".

Source lists pair a generic common name with the specific number that says what
is meant.  EF 3.1 ships `butanol` with `71-36-3` (1-butanol) and `ascorbic acid`
with `50-81-7` (L-ascorbic acid).  Looking up the generic name returns Common
Chemistry's generic registry entry -- `35296-72-1`, `62624-30-0` -- so the rule
traded the specific number for a vaguer one and discarded the only field that
disambiguated the name.  It did that to 52 flow objects in the August 2026
build, and 51 of the 51 discarded numbers were registered CAS numbers Common
Chemistry itself knows.

The rule now: an exact name match fills in a CAS the flow does not have, and
never replaces one it does.  See issue #246 and `docs/deciding/identity.md`.
"""

import unittest

from brightway_flows.domain.flow import Flow
from brightway_flows.transformers.commonchem_cas_review import (
    CommonchemCasReviewTransformer,
    CommonchemRecord,
)


def _record(name, cas):
    return CommonchemRecord(
        name=name, cas=cas, url=f"https://commonchemistry.cas.org/detail?cas_rn={cas}"
    )


class CasOutranksNameTestCase(unittest.TestCase):
    """The network and both caches are stubbed: under test is the change the
    transformer proposes, not how it reaches Common Chemistry."""

    def _transform(self, flow, *, name_hits, detail_by_cas=None):
        transformer = CommonchemCasReviewTransformer()
        transformer._prefetch_commonchem = lambda flows: None
        transformer._lookup_commonchemistry_detail_cached = (
            lambda cas: (detail_by_cas or {}).get(cas, {})
        )
        transformer._commonchem_exact_name_hits = lambda name: name_hits
        transformer._save_json_cache = lambda path, payload: None
        changes = transformer.transform([flow])
        return transformer, {c.field: c.new_value for c in changes}

    def _flow(self, name, cas=None):
        return Flow(
            uuid="u-1",
            name=name,
            source="ef-3.1",
            cas_numbers=list(cas or []),
            prefLabel=[{"@value": name, "@language": "en"}],
        )

    # ── the flow has a CAS: it wins ──────────────────────────────────────────

    def test_a_generic_name_match_does_not_replace_a_specific_cas(self):
        """EF's `butanol` keeps `71-36-3`; it does not become `35296-72-1`."""
        _, changes = self._transform(
            self._flow("butanol", ["71-36-3"]),
            name_hits=[_record("Butanol", "35296-72-1")],
        )
        self.assertNotIn("cas_numbers", changes)

    def test_no_provenance_is_written_for_a_change_that_did_not_happen(self):
        _, changes = self._transform(
            self._flow("butanol", ["71-36-3"]),
            name_hits=[_record("Butanol", "35296-72-1")],
        )
        self.assertNotIn("cas_number_sources", changes)

    def test_the_disagreement_is_still_reported(self):
        """Not applying it is not the same as not noticing it."""
        transformer, _ = self._transform(
            self._flow("butanol", ["71-36-3"]),
            name_hits=[_record("Butanol", "35296-72-1")],
        )
        self.assertEqual(len(transformer.commonchem_name_matches), 1)
        match = transformer.commonchem_name_matches[0]
        self.assertFalse(match.applied)
        self.assertEqual(match.current_cas_numbers, ["71-36-3"])
        self.assertEqual(match.commonchem_cas_numbers, ["35296-72-1"])

    def test_the_review_row_carries_the_outcome(self):
        """A curator has to be able to sort fill-ins from disagreements."""
        transformer, _ = self._transform(
            self._flow("butanol", ["71-36-3"]),
            name_hits=[_record("Butanol", "35296-72-1")],
        )
        payload = transformer.review_queue_items()[0].payload
        self.assertIs(payload["applied"], False)

    def test_a_name_match_may_not_add_to_an_existing_cas_either(self):
        """Adding a number changes the flow object's identity key just as much
        as replacing one, and on the same weak evidence."""
        _, changes = self._transform(
            self._flow("xylene", ["1330-20-7"]),
            name_hits=[_record("Xylene", "1330-20-7"), _record("Xylene", "95-47-6")],
        )
        self.assertNotIn("cas_numbers", changes)

    # ── the flow has no CAS: the name match is the best evidence there is ────

    def test_a_missing_cas_is_filled_in(self):
        _, changes = self._transform(
            self._flow("furathiocarb"),
            name_hits=[_record("Furathiocarb", "65907-30-4")],
        )
        self.assertEqual(changes["cas_numbers"], ["65907-30-4"])

    def test_a_fill_in_carries_provenance(self):
        _, changes = self._transform(
            self._flow("furathiocarb"),
            name_hits=[_record("Furathiocarb", "65907-30-4")],
        )
        provenance = changes["cas_number_sources"]["65907-30-4"]
        self.assertEqual(provenance["prov:wasGeneratedBy"], "commonchem_cas_review")
        self.assertEqual(
            provenance["prov:hadPrimarySource"],
            ["https://commonchemistry.cas.org/detail?cas_rn=65907-30-4"],
        )

    def test_a_fill_in_is_recorded_as_applied(self):
        transformer, _ = self._transform(
            self._flow("furathiocarb"),
            name_hits=[_record("Furathiocarb", "65907-30-4")],
        )
        self.assertTrue(transformer.commonchem_name_matches[0].applied)

    # ── agreement is not a finding ───────────────────────────────────────────

    def test_agreement_records_nothing(self):
        transformer, changes = self._transform(
            self._flow("furathiocarb", ["65907-30-4"]),
            name_hits=[_record("Furathiocarb", "65907-30-4")],
        )
        self.assertEqual(changes, {})
        self.assertEqual(transformer.commonchem_name_matches, [])

    # ── the cases the old rule got right, now reported rather than applied ───

    def test_a_genuine_error_is_reported_rather_than_silently_fixed(self):
        """EF's `1,3,5-triazine` carries `121-82-4`, which is RDX.

        A real finding, and still surfaced -- but the flow may be mislabelled
        rather than mis-numbered, and only a curator can say which.
        """
        transformer, changes = self._transform(
            self._flow("1,3,5-triazine", ["121-82-4"]),
            name_hits=[_record("1,3,5-Triazine", "290-87-9")],
        )
        self.assertNotIn("cas_numbers", changes)
        self.assertEqual(len(transformer.commonchem_name_matches), 1)
        self.assertFalse(transformer.commonchem_name_matches[0].applied)


class RealWorldRegressionTestCase(unittest.TestCase):
    """The five flows from `docs/deciding/identity.md`, kept in step with it."""

    CASES = [
        ("butanol", "71-36-3", "Butanol", "35296-72-1"),
        ("ascorbic acid", "50-81-7", "Ascorbic acid", "62624-30-0"),
        ("carbon", "7782-42-5", "Carbon", "7440-44-0"),
        ("iron oxide", "1345-25-1", "Iron oxide", "1332-37-2"),
        ("pyrethrin", "8003-34-7", "Pyrethrin", "88108-26-3"),
    ]

    def test_every_documented_flow_keeps_its_own_number(self):
        for flow_name, kept, cc_name, offered in self.CASES:
            with self.subTest(flow_name):
                transformer = CommonchemCasReviewTransformer()
                transformer._prefetch_commonchem = lambda flows: None
                transformer._lookup_commonchemistry_detail_cached = lambda cas: {}
                transformer._commonchem_exact_name_hits = lambda name: [
                    _record(cc_name, offered)
                ]
                transformer._save_json_cache = lambda path, payload: None
                flow = Flow(
                    uuid="u-1",
                    name=flow_name,
                    source="ef-3.1",
                    cas_numbers=[kept],
                    prefLabel=[{"@value": flow_name, "@language": "en"}],
                )
                fields = {c.field for c in transformer.transform([flow])}
                self.assertNotIn("cas_numbers", fields)
                self.assertEqual(flow.cas_numbers, [kept])


if __name__ == "__main__":
    unittest.main()
