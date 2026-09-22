"""Tests for label-based flow object matching with CAS cross-check.

"Granite" is both a common stone and a trade name for Penoxsulam (a herbicide,
CAS 219714-96-2). Without CAS cross-checking, a source flow named "Granite"
could be incorrectly matched to the Penoxsulam flow object.

Rules:
- Source WITH a CAS that matches a flow object: narrow label candidates to the
  CAS-matched set (prevents a source from being matched to a flow object it
  doesn't belong to when a better CAS-confirmed candidate is available).
- Source WITH a CAS that matches NO flow object: keep all label candidates
  (source CAS is unknown to our index — may be a salt/form variant; the
  multiple-candidates gate handles any remaining ambiguity).
- Source WITHOUT a CAS: label candidates are restricted to flow objects that
  also carry no CAS — prevents a no-CAS source from matching a chemical
  compound's trade name, while still allowing genuinely CAS-less substances
  (e.g. "Actinides, radioactive, unspecified") to be matched by label.
"""

from __future__ import annotations

import unittest

from brightway_flows.domain.flow_object import FlowObject
from brightway_flows.merge.matching import _build_indexes

CHEMINF_CAS = "http://semanticscience.org/resource/CHEMINF_000446"

PENOXSULAM_CAS = "219714-96-2"
GRANITE_STONE_CAS = "93763-70-3"

def _fo(**payload: object) -> FlowObject:
    """A flow object as `_load_working_set` builds one, from an abbreviated payload.

    `_build_indexes` reads records now, so a fixture that is a bare dict is not
    the thing the merge indexes.  The structural fields every stored object
    carries -- and none of these tests care about -- are filled in here so the
    fixtures stay about labels and registry numbers.
    """
    return FlowObject.from_dict(
        {"altLabel": [], "properties": {}, "references": [], "created_from": {}}
        | payload
    )


# Minimal flow objects fixture: Penoxsulam with "Granite" as an alt label.
FLOW_OBJECTS = [
    _fo(
        flow_object_id="fo-penoxsulam",
        prefLabel=[{"@value": "Penoxsulam", "@language": "en"}],
        altLabel=[{"@value": "Granite", "@language": "en"}],
        classifications={CHEMINF_CAS: {"@value": [PENOXSULAM_CAS]}},
    ),
    _fo(
        flow_object_id="fo-granite-stone",
        prefLabel=[{"@value": "Granite", "@language": "en"}],
        classifications={},
    ),
]


class TestLabelCasCrossCheck(unittest.TestCase):
    def setUp(self):
        self.cas_index, self.ec_index, self.label_index, self.pref_label_index = _build_indexes(FLOW_OBJECTS)

    def test_label_index_contains_granite(self):
        """Both flow objects should be reachable via the 'granite' label."""
        granite_hits = self.label_index.get("granite", set())
        self.assertIn("fo-penoxsulam", granite_hits)
        self.assertIn("fo-granite-stone", granite_hits)

    def test_cas_match_narrows_to_penoxsulam(self):
        """Source with Penoxsulam CAS + label 'Granite' → only Penoxsulam match."""
        label_candidates = self.label_index.get("granite", set())
        cas_matched = label_candidates & self.cas_index.get(PENOXSULAM_CAS, set())
        self.assertEqual(cas_matched, {"fo-penoxsulam"})

    def test_unknown_source_cas_keeps_all_label_candidates(self):
        """Source with a CAS not in the FO index keeps all label candidates.

        Stone CAS (93763-70-3) is not in any flow object, so cas_matched is
        empty and all label candidates are retained.  With two candidates
        (Penoxsulam + Granite stone) the pipeline emits
        'multiple-flow-object-candidates' — the false positive is still blocked.
        """
        label_candidates = self.label_index.get("granite", set())
        cas_matched = label_candidates & self.cas_index.get(GRANITE_STONE_CAS, set())
        self.assertEqual(cas_matched, set())
        # Both FOs remain — ambiguity is resolved by the multiple-candidates gate.
        self.assertEqual(label_candidates, {"fo-penoxsulam", "fo-granite-stone"})

    def test_unknown_cas_single_label_match_allowed(self):
        """Source CAS not in FO index + single label match → match allowed.

        Simulates 'Acrylate' (ecoinvent CAS 10344-93-1) matching the 'Acrylate'
        flow object (CAS 79-10-7).  The source CAS doesn't appear in any FO, so
        cas_matched is empty; the label candidate is kept and proceeds.
        """
        ACRYLATE_FO_CAS = "79-10-7"
        ECOINVENT_ACRYLATE_CAS = "10344-93-1"  # not in the FO index
        acrylate_flow_objects = [
            _fo(
                flow_object_id="fo-acrylate",
                prefLabel=[{"@value": "Acrylate", "@language": "en"}],
                classifications={CHEMINF_CAS: {"@value": [ACRYLATE_FO_CAS]}},
            )
        ]
        cas_idx, _, lbl_idx, _ = _build_indexes(acrylate_flow_objects)
        label_candidates = lbl_idx.get("acrylate", set())
        cas_matched = label_candidates & cas_idx.get(ECOINVENT_ACRYLATE_CAS, set())
        # Source CAS not in index → cas_matched empty → keep label candidates.
        self.assertEqual(cas_matched, set())
        self.assertEqual(label_candidates, {"fo-acrylate"})

    def test_no_source_cas_excludes_cas_flow_objects(self):
        """Source without a CAS must not match flow objects that carry a CAS.

        Granite (stone, no CAS) must not be matched to Penoxsulam (which has
        CAS 219714-96-2 and 'Granite' as a trade-name alt label).  The no-CAS
        source may only match flow objects that also have no CAS.
        """
        flow_objects_with_cas: set[str] = set().union(*self.cas_index.values())
        label_candidates = self.label_index.get("granite", set())
        result = label_candidates - flow_objects_with_cas
        # Penoxsulam is filtered out; Granite stone (no CAS in FO) may remain.
        self.assertNotIn("fo-penoxsulam", result)

    def test_no_source_cas_matches_no_cas_flow_object(self):
        """Source without a CAS can match a flow object that also has no CAS.

        This allows genuinely CAS-less flows like 'Actinides, radioactive,
        unspecified' to be matched by label to their corresponding CAS-less
        flow object.
        """
        flow_objects_with_cas: set[str] = set().union(*self.cas_index.values())
        label_candidates = self.label_index.get("granite", set())
        result = label_candidates - flow_objects_with_cas
        self.assertIn("fo-granite-stone", result)


    def test_no_cas_source_matches_cas_fo_via_preflabel_only(self):
        """No-CAS source may match a CAS-bearing FO when the hit is via prefLabel only.

        'Cyclaniliprole' (no source CAS) should match the 'Cyclaniliprole' FO
        (which has CAS 1031756-98-5) because the source name is the FO's primary
        name, not a trade-name alt label on a different substance.
        """
        CYCLANILIPROLE_CAS = "1031756-98-5"
        flow_objects = [
            _fo(
                flow_object_id="fo-cyclaniliprole",
                prefLabel=[{"@value": "Cyclaniliprole", "@language": "en"}],
                classifications={CHEMINF_CAS: {"@value": [CYCLANILIPROLE_CAS]}},
            ),
        ]
        cas_idx, _, lbl_idx, pref_idx = _build_indexes(flow_objects)
        flow_objects_with_cas: set[str] = set().union(*cas_idx.values())

        norm = "cyclaniliprole"
        pref_cas_hits = pref_idx.get(norm, set()) & flow_objects_with_cas
        self.assertEqual(pref_cas_hits, {"fo-cyclaniliprole"})

    def test_no_cas_source_blocked_via_altlabel_on_cas_fo(self):
        """No-CAS source must not match a CAS-bearing FO via altLabel only.

        'Granite' (no source CAS) must not match Penoxsulam (CAS 219714-96-2)
        even though 'Granite' is one of Penoxsulam's alt labels.
        """
        flow_objects_with_cas: set[str] = set().union(*self.cas_index.values())
        norm = "granite"
        pref_cas_hits = self.pref_label_index.get(norm, set()) & flow_objects_with_cas
        # 'granite' is not a prefLabel of any CAS-bearing FO.
        self.assertEqual(pref_cas_hits, set())


class TestCasAmbiguousNarrowing(unittest.TestCase):
    """When multiple FOs share a CAS, label intersection narrows the match.

    All water variants (plain, green, blue, grey) share CAS 7732-18-5.
    A source "Water, green" with CAS 7732-18-5 must resolve to the green
    water FO, not emit 'multiple-flow-object-candidates'.
    """

    WATER_CAS = "7732-18-5"

    WATER_FLOW_OBJECTS = [
        _fo(
            flow_object_id="fo-water",
            prefLabel=[{"@value": "Water", "@language": "en"}],
            classifications={CHEMINF_CAS: {"@value": ["7732-18-5"]}},
            origin_qualifier=None,
        ),
        _fo(
            flow_object_id="fo-water-green",
            prefLabel=[{"@value": "Water, green", "@language": "en"}],
            classifications={CHEMINF_CAS: {"@value": ["7732-18-5"]}},
            origin_qualifier="green_water",
        ),
        _fo(
            flow_object_id="fo-water-blue",
            prefLabel=[{"@value": "Water, blue", "@language": "en"}],
            classifications={CHEMINF_CAS: {"@value": ["7732-18-5"]}},
            origin_qualifier="blue_water",
        ),
        _fo(
            flow_object_id="fo-water-grey",
            prefLabel=[{"@value": "Water, grey", "@language": "en"}],
            classifications={CHEMINF_CAS: {"@value": ["7732-18-5"]}},
            origin_qualifier="grey_water",
        ),
    ]

    def setUp(self):
        self.cas_index, self.ec_index, self.label_index, self.pref_label_index = (
            _build_indexes(self.WATER_FLOW_OBJECTS)
        )

    def test_cas_alone_is_ambiguous(self):
        """CAS 7732-18-5 alone matches all four water FOs."""
        cas_hits = self.cas_index.get(self.WATER_CAS, set())
        self.assertEqual(len(cas_hits), 4)

    def test_qualifier_narrowing_resolves_green_water(self):
        """Qualifier 'green_water' on source name resolves to the green water FO."""
        from brightway_flows.qualifiers import detect_origin_qualifier
        qualifier_index: dict[str, set[str]] = {}
        for fo in self.WATER_FLOW_OBJECTS:
            if fo.origin_qualifier and fo.flow_object_id:
                qualifier_index.setdefault(fo.origin_qualifier, set()).add(
                    fo.flow_object_id
                )

        cas_hits = self.cas_index.get(self.WATER_CAS, set())
        source_qualifier = detect_origin_qualifier("Water, green")
        qual_narrowed = cas_hits & qualifier_index.get(source_qualifier or "", set())
        self.assertEqual(qual_narrowed, {"fo-water-green"})

    def test_qualifier_narrowing_resolves_plain_water(self):
        """No qualifier on source name 'Water' — qualifier narrowing yields nothing,
        so the pipeline falls through to the existing label-based narrowing."""
        from brightway_flows.qualifiers import detect_origin_qualifier
        qualifier_index: dict[str, set[str]] = {}
        for fo in self.WATER_FLOW_OBJECTS:
            if fo.origin_qualifier and fo.flow_object_id:
                qualifier_index.setdefault(fo.origin_qualifier, set()).add(
                    fo.flow_object_id
                )

        cas_hits = self.cas_index.get(self.WATER_CAS, set())
        source_qualifier = detect_origin_qualifier("Water")
        self.assertIsNone(source_qualifier)
        # No qualifier → qualifier narrowing skipped → label narrowing used instead
        label_hits = self.label_index.get("water", set())
        narrowed = label_hits & cas_hits
        self.assertEqual(narrowed, {"fo-water"})


class TestAltLabelCasGuard(unittest.TestCase):
    """ConsensusMatchTransformer must not assign a CAS to a no-CAS flow when
    that flow's name is already used as an altLabel of a CAS-bearing flow
    object in the same dataset.

    Scenario: EF 3.1 contains
      - "granite" (stone, no CAS)
      - "Penoxsulam" (herbicide, CAS 219714-96-2, altLabel "Granite")
    PubChem/CC both return 219714-96-2 for the query "granite" (trade name).
    The guard must block the CAS assignment because the dataset itself already
    distinguishes the two substances.
    """

    PENOXSULAM_CAS = "219714-96-2"
    CHEMINF_CAS = "http://semanticscience.org/resource/CHEMINF_000446"

    def _make_flow_objects(self):
        """Minimal FlowObject list: Penoxsulam with 'Granite' as altLabel."""
        from brightway_flows.domain.flow_object import FlowObject
        return [
            FlowObject(
                flow_object_id="fo-penoxsulam",
                prefLabel=[{"@value": "Penoxsulam", "@language": "en"}],
                altLabel=[{"@value": "Granite", "@language": "en"}],
                properties={},
                references=[],
                created_from={},
                classifications={
                    self.CHEMINF_CAS: {"@value": [self.PENOXSULAM_CAS]},
                },
            ),
        ]

    def test_altlabel_index_built_from_flow_objects(self):
        """altlabel_cas_in_dataset maps 'granite' → {219714-96-2}."""
        from brightway_flows.pipeline import normalize

        fo_list = self._make_flow_objects()
        altlabel_cas: dict[str, set[str]] = {}
        for fo in fo_list:
            fo_cas = set(
                (((fo.classifications or {}).get(self.CHEMINF_CAS, {}) or {}).get("@value") or [])
            )
            if not fo_cas:
                continue
            for al_item in (fo.altLabel or []):
                al_value = al_item.get("@value") if isinstance(al_item, dict) else None
                if not isinstance(al_value, str) or not al_value.strip():
                    continue
                norm_al = normalize(al_value)
                altlabel_cas.setdefault(norm_al, set()).update(fo_cas)

        self.assertIn("granite", altlabel_cas)
        self.assertIn(self.PENOXSULAM_CAS, altlabel_cas["granite"])

    def test_guard_blocks_cas_assignment(self):
        """Candidate CAS blocked when name is an altLabel of another CAS FO."""
        from brightway_flows.pipeline import normalize

        fo_list = self._make_flow_objects()
        altlabel_cas: dict[str, set[str]] = {}
        for fo in fo_list:
            fo_cas = set(
                (((fo.classifications or {}).get(self.CHEMINF_CAS, {}) or {}).get("@value") or [])
            )
            for al_item in (fo.altLabel or []):
                al_value = al_item.get("@value") if isinstance(al_item, dict) else None
                if isinstance(al_value, str) and al_value.strip():
                    altlabel_cas.setdefault(normalize(al_value), set()).update(fo_cas)

        # Simulate the guard check for flow_name="granite", cas_candidate=219714-96-2
        flow_name = "granite"
        cas_candidate = self.PENOXSULAM_CAS
        blocked = cas_candidate in altlabel_cas.get(normalize(flow_name), set())
        self.assertTrue(blocked, "CAS assignment should be blocked for 'granite'")

    def test_guard_does_not_block_unrelated_name(self):
        """Names not in the altLabel index are not blocked."""
        from brightway_flows.pipeline import normalize

        fo_list = self._make_flow_objects()
        altlabel_cas: dict[str, set[str]] = {}
        for fo in fo_list:
            fo_cas = set(
                (((fo.classifications or {}).get(self.CHEMINF_CAS, {}) or {}).get("@value") or [])
            )
            for al_item in (fo.altLabel or []):
                al_value = al_item.get("@value") if isinstance(al_item, dict) else None
                if isinstance(al_value, str) and al_value.strip():
                    altlabel_cas.setdefault(normalize(al_value), set()).update(fo_cas)

        blocked = self.PENOXSULAM_CAS in altlabel_cas.get(normalize("acetone"), set())
        self.assertFalse(blocked, "Unrelated name 'acetone' should not be blocked")


if __name__ == "__main__":
    unittest.main()
