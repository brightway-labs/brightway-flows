"""Regrouping per-flow mappings into correspondences.

The integration side -- that the result expands to the right triples -- is in
`test_jsonld_export.py`.  These cover the decisions the regrouping makes on data
it cannot expect to be clean: a source IRI belonging to no known scheme, the
same mapping arriving twice, a release nobody told the export about.
"""

import unittest

from brightway_flows.domain.vocabulary import (
    QUDT_CONVERSION_MULTIPLIER_CURIE,
    SKOS_EXACT_MATCH_CURIE,
    SKOS_PREF_LABEL_CURIE,
    XKOS_SOURCE_CONCEPT_CURIE,
    XKOS_TARGET_CONCEPT_CURIE,
    ecoinvent_source_scheme,
    scheme_for_flow_iri,
)
from brightway_flows.sources import excluded_source_flows, known_source_lists
from brightway_flows.pipeline.correspondences import (
    CONSENSUS_SCHEME_IRI,
    association_iri,
    build_correspondences as _build_correspondences,
    creator,
)

CONSENSUS = "https://vocab.brightway.dev/elementary-flows/"
EF31 = "https://vocab.brightway.one/ef/3.1/flow/"


def build_correspondences(flows, **kwargs):
    """`correspondences.build_correspondences` over synthetic flows alone.

    The real function reads what each registered list refuses from the curated
    files, so a made-up document would otherwise pick up ecoinvent 3.8's three
    exclusions -- either onto a correspondence these tests built for another
    reason, or into `excluded_scheme_not_published`. `ExcludedSourceConceptsTestCase`
    covers what the default does.
    """
    kwargs.setdefault("excluded", {})
    return _build_correspondences(flows, **kwargs)


def association(source: str, target: str, **extra) -> dict:
    return {
        "@type": "xkos:ConceptAssociation",
        XKOS_SOURCE_CONCEPT_CURIE: {
            "@id": source,
            SKOS_PREF_LABEL_CURIE: "a label",
            SKOS_EXACT_MATCH_CURIE: {"@id": target},
        },
        XKOS_TARGET_CONCEPT_CURIE: {"@id": target},
        **extra,
    }


def flow(*associations) -> dict:
    return {"concept_associations": list(associations)}


class SchemeDetectionTestCase(unittest.TestCase):
    """Which source list a mapping came from is read off the source IRI."""

    def test_the_registered_schemes_are_recognised(self):
        cases = {
            f"{EF31}x": "ef-3.1",
            "https://vocab.brightway.one/simapro/professional/10.2/flow/y": "simapro-10.2",
        }
        for source, slug in cases.items():
            with self.subTest(source=source):
                self.assertEqual(scheme_for_flow_iri(source).slug, slug)

    def test_an_ecoinvent_release_is_read_from_the_iri(self):
        """No version list is passed in, so a new release still resolves.

        Told a fixed set of versions, the export would silently drop a release
        it had not been updated for -- and #226 added one.
        """
        for version in ("3.8", "3.12", "9.9"):
            with self.subTest(version=version):
                scheme = scheme_for_flow_iri(
                    f"https://vocab.brightway.one/ecoinvent/{version}/flow/x"
                )
                self.assertEqual(scheme, ecoinvent_source_scheme(version))

    def test_every_registered_source_list_reaches_a_scheme(self):
        """The registry and the export have to agree about what exists.

        Reading the release off the IRI means a new one resolves without the
        export being told about it, and the test above asserts that for three
        literal versions.  This asserts the property that actually matters:
        whatever `known_source_lists` offers to merge, the export can place.
        Adding a version to `ECOINVENT_VERSIONS` whose flows would then be
        dropped as belonging to no scheme fails here rather than in a run.
        """
        registry = known_source_lists()
        self.assertIn("ecoinvent-3.8", registry, "3.8 is registered (#226)")
        for key, source in sorted(registry.items()):
            with self.subTest(source=key):
                self.assertTrue(source.flow_iri_prefix, "a list must mint a prefix")
                scheme = scheme_for_flow_iri(f"{source.flow_iri_prefix}some-uuid")
                self.assertIsNotNone(scheme, f"{key} belongs to no scheme")
                self.assertEqual(scheme.slug, key)

    def test_an_unknown_source_belongs_to_no_scheme(self):
        self.assertIsNone(scheme_for_flow_iri("https://example.org/whatever/x"))

    def test_an_unknown_source_is_counted_not_guessed_at(self):
        _schemes, correspondences, counts = build_correspondences(
            [flow(association("https://example.org/x", f"{CONSENSUS}c-1"))]
        )
        self.assertEqual(correspondences, [])
        self.assertEqual(counts["skipped_unknown_scheme"], 1)


class AssociationIRITestCase(unittest.TestCase):
    def test_the_iri_is_derived_from_both_flows(self):
        scheme = scheme_for_flow_iri(f"{EF31}src-1")
        self.assertEqual(
            association_iri(scheme, f"{EF31}src-1", f"{CONSENSUS}tgt-1"),
            "https://vocab.brightway.dev/concept-associations/ef-3.1/src-1/tgt-1",
        )

    def test_the_same_mapping_gets_the_same_iri_every_time(self):
        """A rebuild must not rename every association in the graph."""
        payload = [flow(association(f"{EF31}s", f"{CONSENSUS}t"))]
        first = build_correspondences(payload)[1][0].made_of[0].jsonld_id
        second = build_correspondences(payload)[1][0].made_of[0].jsonld_id
        self.assertEqual(first, second)

    def test_the_same_pair_twice_makes_one_node(self):
        """Two flows can carry the same mapping; the graph holds it once."""
        pair = association(f"{EF31}s", f"{CONSENSUS}t")
        _schemes, correspondences, counts = build_correspondences(
            [flow(pair), flow(dict(pair))]
        )
        self.assertEqual(len(correspondences[0].made_of), 1)
        self.assertEqual(counts["deduplicated"], 1)


class CorrespondenceShapeTestCase(unittest.TestCase):
    def test_one_correspondence_per_source_list(self):
        _schemes, correspondences, _counts = build_correspondences([
            flow(
                association(f"{EF31}s1", f"{CONSENSUS}t1"),
                association(
                    "https://vocab.brightway.one/ecoinvent/3.12/flow/s2",
                    f"{CONSENSUS}t1",
                ),
            ),
        ])
        self.assertEqual(
            [c.jsonld_id for c in correspondences],
            [
                "https://vocab.brightway.dev/correspondences/ecoinvent-3.12",
                "https://vocab.brightway.dev/correspondences/ef-3.1",
            ],
        )

    def test_two_ecoinvent_releases_get_a_correspondence_each(self):
        """3.8 and 3.12 are merged in one run, and are separate source lists.

        Their flows share uuids across releases, so a single ecoinvent
        correspondence would conflate two schemes and make the association IRIs
        collide.  One per release keeps each mapping attributable.
        """
        _schemes, correspondences, _counts = build_correspondences([
            flow(
                association(
                    "https://vocab.brightway.one/ecoinvent/3.8/flow/shared-uuid",
                    f"{CONSENSUS}t1",
                ),
                association(
                    "https://vocab.brightway.one/ecoinvent/3.12/flow/shared-uuid",
                    f"{CONSENSUS}t1",
                ),
            ),
        ])
        # Ordered by slug, so "3.12" precedes "3.8" -- lexical, not numeric.
        self.assertEqual(
            [c.jsonld_id for c in correspondences],
            [
                "https://vocab.brightway.dev/correspondences/ecoinvent-3.12",
                "https://vocab.brightway.dev/correspondences/ecoinvent-3.8",
            ],
        )
        made_of = [a["@id"] for c in correspondences for a in c.to_dict()["xkos:madeOf"]]
        self.assertEqual(len(set(made_of)), 2, "the same uuid must not collide")

    def test_a_source_list_with_no_mappings_gets_no_correspondence(self):
        """An empty correspondence claims two schemes were compared and nothing
        matched, which is not the same as not having compared them."""
        _schemes, correspondences, _counts = build_correspondences([flow()])
        self.assertEqual(correspondences, [])

    def test_the_consensus_scheme_is_always_published(self):
        """Every flow is `skos:inScheme` it, so it has to be a node."""
        schemes, _correspondences, _counts = build_correspondences([])
        self.assertEqual([s.jsonld_id for s in schemes], [CONSENSUS_SCHEME_IRI])

    def test_each_correspondence_compares_its_scheme_to_the_consensus(self):
        _schemes, correspondences, _counts = build_correspondences(
            [flow(association(f"{EF31}s", f"{CONSENSUS}t"))]
        )
        self.assertEqual(
            correspondences[0].compares,
            [
                {"@id": "https://vocab.brightway.one/ef/3.1"},
                {"@id": CONSENSUS_SCHEME_IRI},
            ],
        )

    def test_the_source_concept_keeps_its_detail(self):
        """Label and match quality are statements about that concept."""
        _schemes, correspondences, _counts = build_correspondences(
            [flow(association(f"{EF31}s", f"{CONSENSUS}t"))]
        )
        source = correspondences[0].made_of[0].source_concept
        self.assertEqual(source[SKOS_PREF_LABEL_CURIE], "a label")
        self.assertEqual(source[SKOS_EXACT_MATCH_CURIE], {"@id": f"{CONSENSUS}t"})

    def test_a_conversion_multiplier_survives(self):
        _schemes, correspondences, _counts = build_correspondences([
            flow(association(
                f"{EF31}s", f"{CONSENSUS}t",
                **{QUDT_CONVERSION_MULTIPLIER_CURIE: 0.25},
            ))
        ])
        self.assertEqual(correspondences[0].made_of[0].conversion_multiplier, 0.25)

    def test_no_multiplier_means_the_key_is_absent(self):
        _schemes, correspondences, _counts = build_correspondences(
            [flow(association(f"{EF31}s", f"{CONSENSUS}t"))]
        )
        self.assertNotIn(
            QUDT_CONVERSION_MULTIPLIER_CURIE, correspondences[0].made_of[0].to_dict()
        )

    def test_the_associations_are_ordered(self):
        """Two runs over the same data must produce the same bytes."""
        payload = [flow(
            association(f"{EF31}z", f"{CONSENSUS}t"),
            association(f"{EF31}a", f"{CONSENSUS}t"),
            association(f"{EF31}m", f"{CONSENSUS}t"),
        )]
        made_of = build_correspondences(payload)[1][0].made_of
        self.assertEqual(
            [row.jsonld_id for row in made_of], sorted(row.jsonld_id for row in made_of)
        )


class ProvenanceTestCase(unittest.TestCase):
    """`dcterms:created` and `dcterms:creator`, which PyST requires.

    The distinction under test is whose claim each node is.  This project made
    the consensus list and made every correspondence; it did not make EF 3.1.
    """

    STAMP = "2026-08-06T09:00:00+00:00"

    def _build(self):
        return build_correspondences(
            [flow(association(f"{EF31}s1", f"{CONSENSUS}t1"))],
            created=self.STAMP,
        )

    def test_the_consensus_scheme_carries_both(self):
        schemes, _correspondences, _counts = self._build()
        consensus = next(s for s in schemes if s.jsonld_id == CONSENSUS_SCHEME_IRI)
        self.assertEqual(consensus.created, self.STAMP)
        self.assertEqual(consensus.creator, creator())

    def test_a_source_scheme_carries_neither(self):
        """Stamping this project as EF 3.1's creator would be false."""
        schemes, _correspondences, _counts = self._build()
        source = [s for s in schemes if s.jsonld_id != CONSENSUS_SCHEME_IRI]
        self.assertTrue(source, "no source scheme was built")
        for scheme in source:
            with self.subTest(scheme=scheme.jsonld_id):
                self.assertIsNone(scheme.created)
                self.assertIsNone(scheme.creator)

    def test_an_unset_field_is_absent_rather_than_null(self):
        """A `dcterms:created` of `null` is a statement; absence is not."""
        schemes, _correspondences, _counts = self._build()
        source = next(s for s in schemes if s.jsonld_id != CONSENSUS_SCHEME_IRI)
        payload = source.to_dict()
        self.assertNotIn("dcterms:created", payload)
        self.assertNotIn("dcterms:creator", payload)

    def test_every_correspondence_carries_both(self):
        _schemes, correspondences, _counts = self._build()
        self.assertTrue(correspondences)
        for row in correspondences:
            with self.subTest(correspondence=row.jsonld_id):
                self.assertEqual(row.created, self.STAMP)
                self.assertEqual(row.creator, creator())

    def test_one_document_carries_one_timestamp(self):
        """Read per node, two nodes built either side of a second disagree."""
        schemes, correspondences, _counts = build_correspondences([
            flow(
                association(f"{EF31}s1", f"{CONSENSUS}t1"),
                association(
                    "https://vocab.brightway.one/ecoinvent/3.12/flow/s2",
                    f"{CONSENSUS}t1",
                ),
            ),
        ])
        stamps = {row.created for row in correspondences}
        stamps |= {s.created for s in schemes if s.created is not None}
        self.assertEqual(len(stamps), 1, f"nodes disagree about the run: {stamps}")

    def test_the_stamp_defaults_to_now(self):
        """A caller that does not pass one still gets a well-formed value."""
        from datetime import datetime

        _schemes, correspondences, _counts = build_correspondences(
            [flow(association(f"{EF31}s1", f"{CONSENSUS}t1"))]
        )
        parsed = datetime.fromisoformat(correspondences[0].created)
        self.assertIsNotNone(parsed.tzinfo, "the stamp must carry an offset")

    def test_the_creator_names_the_project_and_a_version(self):
        self.assertTrue(creator().startswith("brightway-flows "))
        self.assertNotEqual(creator(), "brightway-flows ")


class MalformedInputTestCase(unittest.TestCase):
    """Dirty data is counted, not crashed on and not guessed at."""

    def test_a_missing_source_or_target_is_counted(self):
        _s, correspondences, counts = build_correspondences([
            flow(
                {XKOS_SOURCE_CONCEPT_CURIE: {"@id": f"{EF31}s"}},
                {XKOS_TARGET_CONCEPT_CURIE: {"@id": f"{CONSENSUS}t"}},
            )
        ])
        self.assertEqual(correspondences, [])
        self.assertEqual(counts["skipped_malformed"], 2)

    def test_an_empty_iri_is_counted(self):
        _s, _c, counts = build_correspondences([
            flow({
                XKOS_SOURCE_CONCEPT_CURIE: {"@id": ""},
                XKOS_TARGET_CONCEPT_CURIE: {"@id": f"{CONSENSUS}t"},
            })
        ])
        self.assertEqual(counts["skipped_missing_iri"], 1)

    def test_a_flow_without_associations_is_not_an_error(self):
        _s, correspondences, counts = build_correspondences(
            [{}, {"concept_associations": None}, flow()]
        )
        self.assertEqual(correspondences, [])
        self.assertEqual(counts, {})

    def test_exclusions_for_a_scheme_with_no_correspondence_are_counted(self):
        """Nowhere to hang them, and an empty correspondence would lie.

        `xkos:Correspondence` asserts that two schemes were compared. A build
        that did not merge the list has not compared anything, so minting one to
        carry the exclusions would be a stronger claim than the build supports.
        """
        _s, correspondences, counts = _build_correspondences([flow()])
        self.assertEqual(correspondences, [])
        # Every refused row in the shipped files, counted from the registry
        # rather than written down: the number grows whenever a list refuses
        # something, and a literal here would make that an unrelated failure.
        refused = sum(len(rows) for rows in excluded_source_flows().values())
        self.assertGreater(refused, 0)
        self.assertEqual(counts["excluded_scheme_not_published"], refused)

    def test_a_boolean_is_not_a_conversion_multiplier(self):
        """`bool` is an `int` subclass in Python and is not a number here."""
        _s, correspondences, _c = build_correspondences([
            flow(association(
                f"{EF31}s", f"{CONSENSUS}t",
                **{QUDT_CONVERSION_MULTIPLIER_CURIE: True},
            ))
        ])
        self.assertIsNone(correspondences[0].made_of[0].conversion_multiplier)


class ExcludedSourceConceptsTestCase(unittest.TestCase):
    """What a correspondence says about the flows it does *not* map.

    `xkos:madeOf` lists the pairs that were formed, and a source flow forming
    none is simply absent -- which reads the same whether it was examined and
    refused or never looked at. That ambiguity is what #115 cost: a consumer
    counted ecoinvent 3.8's master data against the associations, found three
    fewer, and filed a regression against a decision.
    """

    def _ecoinvent_38(self, **kwargs):
        _s, correspondences, counts = _build_correspondences(
            [
                flow(
                    association(
                        "https://vocab.brightway.one/ecoinvent/3.8/flow/mapped-uuid",
                        f"{CONSENSUS}t1",
                    )
                )
            ],
            **kwargs,
        )
        return correspondences[0], counts

    def test_the_three_refused_rows_are_published_on_the_correspondence(self):
        correspondence, counts = self._ecoinvent_38()
        published = correspondence.to_dict()["brightway:excludedSourceConcept"]
        self.assertEqual(
            {row["@id"].rsplit("/", 1)[-1] for row in published},
            {
                "22cbd60c-8017-49c4-ae6f-7f0c1c6ebf0b",
                "2d8d9c78-e7da-4b71-8c5e-8d1de08696c0",
                "c7075d71-2cfb-42ac-bd96-4661486e1ff7",
            },
        )
        self.assertEqual(counts["excluded_ecoinvent-3.8"], 3)

    def test_each_record_says_why_and_names_the_product_it_duplicates(self):
        """The answer to "where did this flow go?", where the asker is looking."""
        correspondence, _counts = self._ecoinvent_38()
        for row in correspondence.to_dict()["brightway:excludedSourceConcept"]:
            with self.subTest(flow=row["@id"]):
                self.assertIn("not an elementary flow", row["brightway:exclusionReason"])

    def test_a_record_carries_the_vendors_own_identity_for_the_flow(self):
        """Nothing was harmonised, so there is no consensus spelling to give --
        and the consumer is holding the vendor's file, not this one."""
        correspondence, _counts = self._ecoinvent_38()
        by_uuid = {
            row["@id"].rsplit("/", 1)[-1]: row
            for row in correspondence.to_dict()["brightway:excludedSourceConcept"]
        }
        argon = by_uuid["22cbd60c-8017-49c4-ae6f-7f0c1c6ebf0b"]
        self.assertEqual(argon["skos:prefLabel"], "venting of argon, crude, liquid")
        self.assertEqual(argon["context"], "social / unspecified")
        self.assertEqual(
            argon["qudt:hasUnit"],
            {"@id": "https://vocab.brightway.one/units/unit/KiloGM"},
        )

    def test_a_record_carries_no_mapping_property(self):
        """A `skos:exactMatch` here would name a concept that does not exist."""
        correspondence, _counts = self._ecoinvent_38()
        for row in correspondence.to_dict()["brightway:excludedSourceConcept"]:
            with self.subTest(flow=row["@id"]):
                self.assertEqual(
                    [key for key in row if key.startswith("skos:")], ["skos:prefLabel"]
                )

    def test_a_list_that_refuses_nothing_publishes_no_key(self):
        """Absent, not empty: the presence of the key is the finding."""
        _s, correspondences, _counts = _build_correspondences(
            [flow(association(f"{EF31}s", f"{CONSENSUS}t"))], excluded={}
        )
        self.assertNotIn(
            "brightway:excludedSourceConcept", correspondences[0].to_dict()
        )

    def test_the_iri_is_minted_from_the_scheme_not_stored_on_the_record(self):
        """A second copy of the prefix is a second place for it to go stale."""
        correspondence, _counts = self._ecoinvent_38()
        for row in correspondence.to_dict()["brightway:excludedSourceConcept"]:
            with self.subTest(flow=row["@id"]):
                self.assertTrue(
                    row["@id"].startswith(
                        "https://vocab.brightway.one/ecoinvent/3.8/flow/"
                    )
                )


if __name__ == "__main__":
    unittest.main()
