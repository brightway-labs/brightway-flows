"""#66: every land-use axis value is cited, or recorded as ours.

The material taxonomy's discipline, applied to a second scheme: an accession is
eight digits, a typo in one of them is a different published class that still
resolves, and the only defence is to check what the authority actually says.
`data/land-anchor-snapshot.json` is that check, and it runs offline.

What is pinned here:

1. **Every citation resolves, and says what we say it says.** A label that drifts
   upstream shows up as a failure, not as a reader's surprise.
2. **The realm rule holds.** A terrestrial cover cites ENVO, an aquatic one IUCN
   GET, and neither is a preference a curator can override.
3. **No value is undecided.** Anchored or explicitly ours -- a new axis value
   that nobody thought about fails rather than joining `UNANCHORED` by default.
"""

import json
import unittest
from pathlib import Path

from brightway_flows.domain.land_use import (
    QUALIFIER_AXES,
    Direction,
    LandCover,
    LandUse,
    ManagementIntensity,
    Irrigation,
)
from brightway_flows.domain.land_use_anchors import (
    COVER_ANCHORS,
    COVER_REALMS,
    BROAD_MATCH,
    CLOSE_MATCH,
    EXACT_MATCH,
    REGIME_ANCHORS,
    RELATED_MATCH,
    SNAPSHOT_FILEPATH,
    UNANCHORED,
    Anchor,
    Authority,
    LandAnchorError,
    Realm,
    anchor_snapshot,
    anchors_for,
    check_cover_authority,
    check_every_value_is_decided,
    cited_identifiers,
)

OBSERVED_PATH = Path(__file__).parent / "data" / "observed-land-classes.json"

VALID_PREDICATES = {EXACT_MATCH, CLOSE_MATCH, BROAD_MATCH, RELATED_MATCH}


class SnapshotTestCase(unittest.TestCase):
    """Nothing is cited that was not resolved."""

    def test_every_cited_identifier_is_in_the_snapshot(self):
        snapshot = anchor_snapshot()
        for authority, identifiers in cited_identifiers().items():
            for identifier in identifiers:
                with self.subTest(authority=authority.value, id=identifier):
                    self.assertIn(identifier, snapshot[authority.value])

    def test_every_asserted_label_is_the_published_one(self):
        """The check that makes a mistyped accession fail offline.

        `ENVO_01000891` and `ENVO_01000892` both resolve, and neither is a typo
        a reader would catch: one is pastureland and one is cropland.
        """
        snapshot = anchor_snapshot()
        for anchors in (COVER_ANCHORS, REGIME_ANCHORS):
            for key, anchor in anchors.items():
                with self.subTest(value=key.name, id=anchor.identifier):
                    published = snapshot[anchor.authority.value][anchor.identifier]
                    self.assertEqual(
                        anchor.label.strip().lower(),
                        published["label"].strip().lower(),
                    )

    def test_no_cited_envo_class_is_obsolete_upstream(self):
        snapshot = anchor_snapshot()
        for accession, term in snapshot["envo"].items():
            with self.subTest(accession=accession):
                self.assertFalse(term["obsolete"])

    def test_the_snapshot_records_which_get_file_it_read(self):
        """GET's w3id currently redirects to a demo server, so the file we read
        has to be identifiable by more than its URL."""
        payload = json.loads(SNAPSHOT_FILEPATH.read_bytes())
        self.assertRegex(payload["get_turtle_sha256"], r"^[0-9a-f]{64}$")
        self.assertIn("w3id.org/iucn-get", json.dumps(payload["get"]))

    def test_nothing_is_resolved_that_is_not_cited(self):
        """A snapshot that outgrew the module would hide a removed anchor."""
        snapshot = anchor_snapshot()
        cited = cited_identifiers()
        for authority in Authority:
            with self.subTest(authority=authority.value):
                self.assertEqual(set(snapshot[authority.value]), cited[authority])


class RealmRuleTestCase(unittest.TestCase):
    """Which authority types a cover follows the realm, not a preference."""

    def test_the_realm_rule_holds(self):
        check_cover_authority()

    def test_every_cover_has_a_realm(self):
        self.assertEqual(set(COVER_REALMS), set(LandCover))

    def test_an_aquatic_cover_may_not_cite_envo(self):
        """ENVO's terrestrial branch does not reach a sea floor or a canal."""
        original = COVER_ANCHORS[LandCover.SEABED]
        COVER_ANCHORS[LandCover.SEABED] = Anchor(
            Authority.ENVO, "ENVO_00000482", "sea floor", EXACT_MATCH
        )
        try:
            with self.assertRaises(LandAnchorError):
                check_cover_authority()
        finally:
            COVER_ANCHORS[LandCover.SEABED] = original

    def test_a_terrestrial_cover_may_not_cite_get(self):
        """GET's `T7.4` is the whole built environment at once -- buildings,
        paved surfaces, transport infrastructure, parks, excavations and refuse
        areas -- and our lists characterise those separately."""
        original = COVER_ANCHORS[LandCover.URBAN]
        COVER_ANCHORS[LandCover.URBAN] = Anchor(
            Authority.GET, "EFG_T7_4", "Urban and industrial ecosystems", EXACT_MATCH
        )
        try:
            with self.assertRaises(LandAnchorError):
                check_cover_authority()
        finally:
            COVER_ANCHORS[LandCover.URBAN] = original

    def test_the_aquatic_covers_are_the_ones_the_plan_names(self):
        aquatic = {
            cover for cover, realm in COVER_REALMS.items() if realm is Realm.AQUATIC
        }
        self.assertEqual(
            aquatic,
            {
                LandCover.LAKE,
                LandCover.RIVER,
                LandCover.INLAND_WATER,
                LandCover.WATER_BODY,
                LandCover.WATERCOURSE,
                LandCover.SEA,
                LandCover.SEABED,
            },
        )


class DecidedTestCase(unittest.TestCase):
    """Silence about a value is a decision, not an oversight."""

    def test_every_value_is_anchored_or_recorded_as_ours(self):
        check_every_value_is_decided()

    def test_a_new_value_with_no_decision_fails(self):
        """The failure mode this exists for: an axis value ships with no
        citation because nobody thought about it, which is indistinguishable
        from one we decided to leave unanchored."""
        reason = UNANCHORED.pop(ManagementIntensity.DIVERSE_INTENSIVE)
        try:
            with self.assertRaises(LandAnchorError):
                check_every_value_is_decided()
        finally:
            UNANCHORED[ManagementIntensity.DIVERSE_INTENSIVE] = reason

    def test_nothing_is_both_anchored_and_recorded_as_ours(self):
        anchored = set(COVER_ANCHORS) | set(REGIME_ANCHORS)
        self.assertEqual(anchored & set(UNANCHORED), set())

    def test_diverse_intensive_is_ours_and_says_so(self):
        """BAFU's intensity, the one value in the scheme with nothing to cite."""
        self.assertIn(ManagementIntensity.DIVERSE_INTENSIVE, UNANCHORED)
        self.assertIn("AGROVOC", UNANCHORED[ManagementIntensity.DIVERSE_INTENSIVE])

    def test_unanchored_names_only_values_this_scheme_has(self):
        known = {value for enum in (LandCover, *QUALIFIER_AXES.values()) for value in enum}
        self.assertLessEqual(set(UNANCHORED), known)


class ComputedAnchorsTestCase(unittest.TestCase):
    """A land class states nothing of its own; its fields do the citing."""

    def test_a_class_cites_what_its_fields_cite(self):
        land_use = LandUse(
            direction=Direction.OCCUPATION,
            cover=LandCover.CROPLAND,
            irrigation=Irrigation.RAINFED,
            intensity=ManagementIntensity.INTENSIVE,
        )
        self.assertEqual(
            [(anchor.authority.value, anchor.identifier) for anchor in anchors_for(land_use)],
            [("envo", "ENVO_01000892"), ("agrovoc", "c_6436"), ("agrovoc", "c_3906")],
        )

    def test_two_classes_sharing_a_field_cannot_disagree_about_it(self):
        """The reason the anchors hang off the values: `cropland` is cited once,
        so no class can carry a second opinion about what cropland is."""
        rainfed = LandUse(
            direction=Direction.OCCUPATION,
            cover=LandCover.CROPLAND,
            irrigation=Irrigation.RAINFED,
        )
        irrigated = LandUse(
            direction=Direction.TRANSFORMATION_TO,
            cover=LandCover.CROPLAND,
            irrigation=Irrigation.IRRIGATED,
        )
        self.assertEqual(anchors_for(rainfed)[0], anchors_for(irrigated)[0])

    def test_an_unanchored_field_contributes_nothing_rather_than_a_blank(self):
        land_use = LandUse(
            direction=Direction.OCCUPATION,
            cover=LandCover.CROPLAND,
            intensity=ManagementIntensity.DIVERSE_INTENSIVE,
        )
        self.assertEqual(
            [anchor.identifier for anchor in anchors_for(land_use)], ["ENVO_01000892"]
        )

    def test_every_observed_land_class_cites_something(self):
        """Every class a source list ships reaches at least one authority.

        Not every *field* is anchored, but a published land class with no
        citation at all would be a substance-with-no-chemistry again, in a new
        costume.
        """
        records = json.loads(OBSERVED_PATH.read_bytes())["land_classes"]
        for record in records:
            land_use = LandUse.from_dict(
                {
                    key: value
                    for key, value in record.items()
                    if key not in ("key", "label", "spellings")
                }
            )
            with self.subTest(key=land_use.key):
                if land_use.cover is LandCover.UNSPECIFIED:
                    continue  # the source said nothing; see UNANCHORED
                self.assertTrue(anchors_for(land_use))


class PredicateTestCase(unittest.TestCase):
    """`exactMatch` is earned rather than assumed."""

    def test_every_predicate_is_a_skos_mapping_property(self):
        for anchors in (COVER_ANCHORS, REGIME_ANCHORS):
            for key, anchor in anchors.items():
                with self.subTest(value=key.name):
                    self.assertIn(anchor.predicate, VALID_PREDICATES)

    def test_most_anchors_claim_less_than_equality(self):
        """The material taxonomy claimed `exactMatch` sixteen times out of
        seventeen. This scheme claims it rarely, because our values are mostly
        narrower or coarser than the published classes -- and a scheme that
        claimed equality everywhere would be asserting things ENVO does not."""
        anchors = [*COVER_ANCHORS.values(), *REGIME_ANCHORS.values()]
        exact = [anchor for anchor in anchors if anchor.predicate == EXACT_MATCH]
        self.assertLess(len(exact), len(anchors) / 2)

    def test_a_weaker_predicate_carries_its_reason(self):
        """A `closeMatch` without a comment is a claim nobody can check."""
        for anchors in (COVER_ANCHORS, REGIME_ANCHORS):
            for key, anchor in anchors.items():
                if anchor.predicate in (EXACT_MATCH, RELATED_MATCH):
                    continue
                with self.subTest(value=key.name):
                    self.assertTrue(anchor.comment)

    def test_an_iri_is_built_from_the_authoritys_namespace(self):
        self.assertEqual(
            COVER_ANCHORS[LandCover.CROPLAND].iri,
            "http://purl.obolibrary.org/obo/ENVO_01000892",
        )
        self.assertEqual(
            COVER_ANCHORS[LandCover.SEABED].iri,
            "https://w3id.org/iucn-get/Biome_M3",
        )
        self.assertEqual(
            REGIME_ANCHORS[Irrigation.RAINFED].iri,
            "http://aims.fao.org/aos/agrovoc/c_6436",
        )


if __name__ == "__main__":
    unittest.main()
