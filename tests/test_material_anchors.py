"""Every external class the material taxonomy cites, checked offline.

An ENVO accession is eight digits. A typo in one of them is a *different
published class*, with a different label and a different definition, that
resolves perfectly well — so nothing about the citation being wrong is visible
from inside the repository. `tools/resolve_material_anchors.py` asks the
authorities and writes `material-anchor-snapshot.json`; these tests are what
make that snapshot load-bearing rather than decorative.

Offline on purpose. A suite that reached OLS4 would fail on a train, and a
suite that reached it in CI would make an EBI outage look like a broken commit.
Refreshing is a deliberate act with a reviewable diff.
"""

import unittest

from brightway_flows.domain.materials import (
    agrovoc_anchor,
    anchor_snapshot,
    envo_anchor,
)
from brightway_flows.domain.vocabulary import Namespace


def _load():
    return anchor_snapshot()


class SnapshotShapeTestCase(unittest.TestCase):
    def test_it_carries_both_authorities(self):
        snapshot = _load()
        self.assertTrue(snapshot["envo"])
        self.assertTrue(snapshot["agrovoc"])

    def test_it_says_where_each_came_from(self):
        """Two resolvers, because OLS does not index AGROVOC. A reader has to be
        able to tell which authority answered without running the tool."""
        sources = _load()["sources"]
        self.assertIn("ols4", sources["envo"].lower())
        self.assertIn("agrovoc", sources["agrovoc"].lower())

    def test_every_envo_row_resolved_to_something(self):
        for accession, row in _load()["envo"].items():
            with self.subTest(accession=accession):
                self.assertTrue(row["label"], "no label — the accession may not exist")
                self.assertTrue(row["iri"].endswith(accession))
                self.assertEqual(row["curie"], accession.replace("_", ":"))

    def test_no_anchor_is_an_obsolete_class(self):
        """OBO deprecates rather than deletes, so an obsolete class still
        resolves and still has a label. Anchoring to one would look fine."""
        obsolete = [a for a, r in _load()["envo"].items() if r.get("obsolete")]
        self.assertEqual(obsolete, [])

    def test_every_agrovoc_row_resolved_to_something(self):
        for local_id, row in _load()["agrovoc"].items():
            with self.subTest(local_id=local_id):
                self.assertTrue(row["label"])
                self.assertEqual(row["curie"], f"agrovoc:{local_id}")


class LabelsTestCase(unittest.TestCase):
    """The labels the plan and the data files use, against the authorities.

    Spelled out rather than derived, because deriving them from the snapshot
    would make this test assert that the snapshot equals itself.
    """

    ENVO = {
        "ENVO_00002006": "liquid water",
        "ENVO_00002011": "fresh water",
        "ENVO_00002042": "surface water",
        "ENVO_04000007": "lake water",
        "ENVO_01000599": "river water",
        "ENVO_01001004": "groundwater",
        "ENVO_00003097": "bore hole water",
        "ENVO_00002010": "saline water",
        "ENVO_00002149": "sea water",
        "ENVO_00003044": "brine",
        "ENVO_01000600": "rainwater",
        "ENVO_03600002": "cooling water",
        "ENVO_00002001": "waste water",
        "ENVO_00002186": "contaminated water",
        "ENVO_01000266": "water vapour",
        "ENVO_01000268": "atmospheric water vapour",
        "ENVO_00002012": "hypersaline water",
        "ENVO_01000797": "gaseous environmental material",
        # Resolved so the taxonomy's provenance walk can reach the root through
        # them.  Without these, an edge ENVO does imply comes out as one of ours.
        "ENVO_00005792": "underground water",
        "ENVO_03605006": "stream water",
    }
    AGROVOC = {
        "c_5867fbf1": "green water",
        "c_b1215876": "cooling water",
        "c_6d63ccf3": "grey water",
        "c_66d531bb": "water footprint",
        "c_8309": "water",
    }

    def test_every_envo_accession_carries_the_label_we_cite_it_by(self):
        snapshot = _load()["envo"]
        for accession, label in self.ENVO.items():
            with self.subTest(accession=accession):
                self.assertEqual(snapshot[accession]["label"], label)

    def test_every_agrovoc_concept_carries_the_label_we_cite_it_by(self):
        snapshot = _load()["agrovoc"]
        for local_id, label in self.AGROVOC.items():
            with self.subTest(local_id=local_id):
                self.assertEqual(snapshot[local_id]["label"], label)

    def test_the_snapshot_holds_exactly_the_anchors_we_cite(self):
        """An anchor resolved and then dropped from the taxonomy is dead weight;
        one cited but never resolved is unchecked."""
        self.assertEqual(set(_load()["envo"]), set(self.ENVO))
        self.assertEqual(set(_load()["agrovoc"]), set(self.AGROVOC))


class WhatTheAuthoritiesActuallyAssertTestCase(unittest.TestCase):
    """The parents, which are why the snapshot records more than labels.

    The taxonomy asserts `lake water skos:broader surface water`. ENVO does not.
    Recording what ENVO *does* say is the only thing that keeps that divergence
    visible rather than merely absent — and if ENVO ever adds the edge, this is
    where we find out, because the test that says they are siblings starts
    failing.
    """

    @staticmethod
    def _parents(accession):
        return {p["id"] for p in _load()["envo"][accession]["parents"]}

    def test_envo_does_not_put_lake_water_under_surface_water(self):
        self.assertNotIn("ENVO:00002042", self._parents("ENVO_04000007"))
        self.assertIn("ENVO:00002006", self._parents("ENVO_04000007"))

    def test_envo_does_not_put_river_water_under_surface_water_either(self):
        """It routes it through `stream water`, which is a different claim from
        ours and equally not `surface water`."""
        self.assertNotIn("ENVO:00002042", self._parents("ENVO_01000599"))
        self.assertIn("ENVO:03605006", self._parents("ENVO_01000599"))

    def test_surface_water_is_their_sibling_rather_than_their_parent(self):
        self.assertIn("ENVO:00002006", self._parents("ENVO_00002042"))

    def test_water_vapour_is_not_under_liquid_water(self):
        """Which is why the scheme has two roots rather than one."""
        parents = self._parents("ENVO_01000266")
        self.assertNotIn("ENVO:00002006", parents)
        self.assertIn("ENVO:01000797", parents)

    def test_atmospheric_water_vapour_is_a_child_of_water_vapour(self):
        """So folding it in loses nothing: the `Air` media already says the
        vapour is in an atmosphere."""
        self.assertIn("ENVO:01000266", self._parents("ENVO_01000268"))

    def test_the_saline_branch_is_theirs_and_we_shorten_it(self):
        """`sea water` sits under `saline water`; `brine` sits under
        `hypersaline water`, which sits under it in turn. The scheme puts both
        under `saline_water` directly and records the step it skips."""
        self.assertIn("ENVO:00002010", self._parents("ENVO_00002149"))
        self.assertIn("ENVO:00002012", self._parents("ENVO_00003044"))

    def test_groundwater_hangs_off_underground_water(self):
        self.assertIn("ENVO:00005792", self._parents("ENVO_01001004"))

    def test_the_two_walk_through_classes_reach_liquid_water(self):
        """Why they are resolved at all. `underground water` and `stream water`
        are cited by nothing; they are here so the taxonomy can tell an edge ENVO
        implies from one we invented. Both land on liquid water, so groundwater
        and river water are reachable from the root and the scheme is only
        shortening their chains -- except that river water is then re-parented
        onto `surface water`, which is genuinely ours."""
        self.assertIn("ENVO:00002006", self._parents("ENVO_00005792"))
        self.assertIn("ENVO:00002006", self._parents("ENVO_03605006"))
        self.assertNotIn("ENVO:00002042", self._parents("ENVO_03605006"))


class QuotedDefinitionsTestCase(unittest.TestCase):
    """Definitions the plan quotes as evidence, quoted back at the authority.

    A quotation that has drifted is worse than no quotation: it reads as
    published wording and is ours.
    """

    def test_green_water_is_the_water_footprint_sense(self):
        """Q5's whole answer. If AGROVOC meant the algal-bloom sense this
        anchor would be wrong, and the scope note is what rules that out."""
        row = _load()["agrovoc"]["c_5867fbf1"]
        self.assertIn("fraction of rainfall that infiltrates into the soil", row["definition"])
        self.assertIn("available to plants", row["definition"])
        self.assertIn("planktonic algae", row["scope_note"])

    def test_green_water_is_a_kind_of_water_and_not_of_rainwater(self):
        """It is separate for accounting reasons, not physics — so AGROVOC
        filing it directly under `water` is the shape we mirror."""
        self.assertEqual(
            _load()["agrovoc"]["c_5867fbf1"]["broader"],
            ["http://aims.fao.org/aos/agrovoc/c_8309"],
        )

    def test_agrovoc_grey_water_is_domestic_wash_water(self):
        """The trap. ISO 14046 grey water is a computed assimilation volume;
        this is somebody's shower. An exactMatch here would be wrong in a way
        that looks right."""
        definition = _load()["agrovoc"]["c_6d63ccf3"]["definition"].lower()
        self.assertIn("wastewater", definition)
        self.assertIn("showers", definition)
        self.assertNotIn("assimilat", definition)

    def test_the_water_footprint_concept_is_an_indicator(self):
        """Which is why it is the relatedMatch for grey water rather than a
        material anchor."""
        self.assertIn(
            "indicator", _load()["agrovoc"]["c_66d531bb"]["definition"].lower()
        )

    def test_a_quoted_definition_says_where_it_came_from(self):
        """AGROVOC carries several definitions per concept and attributes each.
        Quoting one without the attribution makes theirs look like ours."""
        self.assertTrue(_load()["agrovoc"]["c_5867fbf1"]["definition_source"])


class LookupTestCase(unittest.TestCase):
    """The accessors, which take the shape a caller already holds."""

    def test_envo_is_looked_up_by_the_shape_an_iri_ends_in(self):
        """Underscore, not colon, so a caller holding an IRI does not translate."""
        self.assertEqual(envo_anchor("ENVO_00002149")["label"], "sea water")
        self.assertIsNone(envo_anchor("ENVO:00002149"))

    def test_an_uncited_class_is_none_rather_than_an_error(self):
        self.assertIsNone(envo_anchor("ENVO_99999999"))
        self.assertIsNone(agrovoc_anchor("c_nope"))

    def test_agrovoc_is_looked_up_by_its_local_id(self):
        self.assertEqual(agrovoc_anchor("c_5867fbf1")["label"], "green water")


class NamespacesTestCase(unittest.TestCase):
    def test_both_authorities_have_a_declared_namespace(self):
        self.assertEqual(Namespace.OBO, "http://purl.obolibrary.org/obo/")
        self.assertEqual(Namespace.AGROVOC, "http://aims.fao.org/aos/agrovoc/")

    def test_every_anchor_iri_sits_under_its_namespace(self):
        for row in _load()["envo"].values():
            with self.subTest(iri=row["iri"]):
                self.assertTrue(row["iri"].startswith(Namespace.OBO))
        for row in _load()["agrovoc"].values():
            with self.subTest(iri=row["iri"]):
                self.assertTrue(row["iri"].startswith(Namespace.AGROVOC))
