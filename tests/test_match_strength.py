"""How strong a mapping is, once the whole source list is in view.

`skos:exactMatch` is symmetric and it chains: two of one list's flows declared
exact matches for the same consensus flow are, by entailment, exact matches for
each other.  The merge decides one row at a time and cannot see the second row
coming, which is how the 2026-08-13 build came to publish 21 ecoinvent 3.12
insecticides -- and kaolin, a clay -- as one substance (#76).

These cover the decision itself, the database pass that applies it to what
earlier runs stored, the export that publishes it, and the property over the
real artifact: no consensus flow may carry more than one exact match from one
source list.
"""

import gzip
import sqlite3
import tempfile
import unittest
from pathlib import Path

import orjson

from brightway_flows.domain.vocabulary import (
    SKOS_BROAD_MATCH_CURIE,
    SKOS_CLOSE_MATCH_CURIE,
    SKOS_EXACT_MATCH_CURIE,
    SKOS_NARROW_MATCH_CURIE,
    SKOS_PREF_LABEL_CURIE,
    SKOS_RELATED_MATCH_CURIE,
    XKOS_MADE_OF_CURIE,
    XKOS_SOURCE_CONCEPT_CURIE,
    XKOS_TARGET_CONCEPT_CURIE,
)
from brightway_flows.filesystem import HARMONISED_FLOWS_SIMPLE_FILEPATH
from brightway_flows.pipeline.correspondences import build_correspondences
from brightway_flows.pipeline.exporting import build_simple_export
from brightway_flows.pipeline.match_strength import (
    apply_match_strengths,
    match_property_key,
)
from brightway_flows.pipeline.sqlite import recompute_match_strengths

CONSENSUS = "https://vocab.brightway.dev/elementary-flows/"
ECOINVENT = "https://vocab.brightway.one/ecoinvent/3.12/flow/"
EF31 = "https://vocab.brightway.one/ef/3.1/flow/"


def association(source: str, target: str, match: str = SKOS_EXACT_MATCH_CURIE) -> dict:
    return {
        "@type": "xkos:ConceptAssociation",
        XKOS_SOURCE_CONCEPT_CURIE: {
            "@id": source,
            SKOS_PREF_LABEL_CURIE: source.rsplit("/", 1)[-1],
            match: {"@id": target},
        },
        XKOS_TARGET_CONCEPT_CURIE: {"@id": target},
    }


def matches(associations) -> list[str]:
    return [match_property_key(a[XKOS_SOURCE_CONCEPT_CURIE]) for a in associations]


class CatchAllFlowTestCase(unittest.TestCase):
    """The case in the report: many of one list's flows, one consensus flow."""

    def test_flows_sharing_a_consensus_flow_are_not_exact_matches(self):
        """Alanycarb and kaolin stop being the same substance.

        Both are ecoinvent 3.12 insecticide rows merged onto one
        `Insecticides, unspecified`.  Published as exact matches they entail
        each other; what is true, and more useful, is that each is narrower
        than the consensus flow -- `skos:broadMatch` read from the source.
        """
        insecticides = [
            association(f"{ECOINVENT}alanycarb", f"{CONSENSUS}insecticides"),
            association(f"{ECOINVENT}kaolin", f"{CONSENSUS}insecticides"),
        ]
        apply_match_strengths([insecticides])
        self.assertEqual(matches(insecticides), [SKOS_BROAD_MATCH_CURIE] * 2)

    def test_the_statement_keeps_the_flow_it_was_about(self):
        """Only the claim changes; what it is a claim about does not."""
        shared = [
            association(f"{ECOINVENT}a", f"{CONSENSUS}x"),
            association(f"{ECOINVENT}b", f"{CONSENSUS}x"),
        ]
        apply_match_strengths([shared])
        for entry in shared:
            source = entry[XKOS_SOURCE_CONCEPT_CURIE]
            self.assertEqual(source[SKOS_BROAD_MATCH_CURIE], {"@id": f"{CONSENSUS}x"})
            self.assertNotIn(SKOS_EXACT_MATCH_CURIE, source)

    def test_the_flows_need_not_share_a_record_to_be_counted(self):
        """The two ends are on different flows in the run, not one list.

        The count that matters spans every flow the run publishes, which is the
        whole reason the decision cannot be made where the mapping is written.
        """
        one = [association(f"{ECOINVENT}a", f"{CONSENSUS}x")]
        two = [association(f"{ECOINVENT}b", f"{CONSENSUS}x")]
        apply_match_strengths([one, two])
        self.assertEqual(matches(one) + matches(two), [SKOS_BROAD_MATCH_CURIE] * 2)


class WhatIsLeftAloneTestCase(unittest.TestCase):
    def test_a_one_to_one_pairing_stays_exact(self):
        pairs = [
            [association(f"{ECOINVENT}a", f"{CONSENSUS}x")],
            [association(f"{ECOINVENT}b", f"{CONSENSUS}y")],
        ]
        apply_match_strengths(pairs)
        self.assertEqual(
            [m for entry in pairs for m in matches(entry)],
            [SKOS_EXACT_MATCH_CURIE] * 2,
        )

    def test_a_close_match_is_neither_weakened_nor_promoted(self):
        """`skos:closeMatch` makes no claim that chains, so it is not the bug.

        It is also not evidence of subsumption: the algorithmic fallback wrote
        it because a row matched by identifier or label, and turning that into
        `skos:broadMatch` would assert a hierarchy nobody established.  A close
        match that happens to be alone on its flow is not promoted either.
        """
        shared = [
            association(f"{ECOINVENT}a", f"{CONSENSUS}x", SKOS_CLOSE_MATCH_CURIE),
            association(f"{ECOINVENT}b", f"{CONSENSUS}x"),
        ]
        alone = [association(f"{ECOINVENT}c", f"{CONSENSUS}y", SKOS_CLOSE_MATCH_CURIE)]
        apply_match_strengths([shared, alone])
        self.assertEqual(
            matches(shared), [SKOS_CLOSE_MATCH_CURIE, SKOS_BROAD_MATCH_CURIE]
        )
        self.assertEqual(matches(alone), [SKOS_CLOSE_MATCH_CURIE])

    def test_two_lists_on_one_flow_are_both_still_exact(self):
        """Exactness chains within a list, not between two of them.

        EF 3.1 and ecoinvent both mapping onto one consensus flow says the
        consensus flow is what they have in common -- which is the point of the
        list -- and entails nothing about the two source flows.
        """
        both = [
            association(f"{EF31}a", f"{CONSENSUS}x"),
            association(f"{ECOINVENT}b", f"{CONSENSUS}x"),
        ]
        apply_match_strengths([both])
        self.assertEqual(matches(both), [SKOS_EXACT_MATCH_CURIE] * 2)

    def test_a_mapping_from_no_registered_scheme_is_untouched(self):
        """Unplaceable, so its cardinality is unknown and nothing is claimed."""
        unknown = [
            association("https://example.org/flow/a", f"{CONSENSUS}x"),
            association("https://example.org/flow/b", f"{CONSENSUS}x"),
        ]
        counts = apply_match_strengths([unknown])
        self.assertEqual(matches(unknown), [SKOS_EXACT_MATCH_CURIE] * 2)
        self.assertEqual(counts["unplaced"], 2)


class WhichConceptIsWiderTestCase(unittest.TestCase):
    def test_a_source_flow_on_several_consensus_flows_is_the_wider_one(self):
        split = [
            association(f"{ECOINVENT}a", f"{CONSENSUS}x"),
            association(f"{ECOINVENT}a", f"{CONSENSUS}y"),
        ]
        apply_match_strengths([split])
        self.assertEqual(matches(split), [SKOS_NARROW_MATCH_CURIE] * 2)

    def test_wider_on_both_sides_is_only_related(self):
        """Neither concept contains the other, and nothing stronger is known."""
        tangled = [
            association(f"{ECOINVENT}a", f"{CONSENSUS}x"),
            association(f"{ECOINVENT}a", f"{CONSENSUS}y"),
            association(f"{ECOINVENT}b", f"{CONSENSUS}x"),
        ]
        apply_match_strengths([tangled])
        self.assertEqual(matches(tangled)[0], SKOS_RELATED_MATCH_CURIE)


class IdempotenceTestCase(unittest.TestCase):
    def test_running_twice_changes_nothing(self):
        """It runs on the records, on the database and again at export.

        Weakening only, never strengthening, is what makes that safe: a second
        pass over an already-corrected mapping has to be a no-op, or every run
        would walk the strength further down.
        """
        shared = [
            association(f"{ECOINVENT}a", f"{CONSENSUS}x"),
            association(f"{ECOINVENT}b", f"{CONSENSUS}x"),
        ]
        apply_match_strengths([shared])
        first = orjson.dumps(shared)
        counts = apply_match_strengths([shared])
        self.assertEqual(orjson.dumps(shared), first)
        self.assertEqual(
            [key for key in counts if key.startswith("weakened_")], []
        )


def build_db(path: Path, payloads) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE elementary_flows (uuid TEXT PRIMARY KEY, flow_object_id TEXT, "
        "flow_json TEXT)"
    )
    for payload in payloads:
        conn.execute(
            "INSERT INTO elementary_flows VALUES (?, ?, ?)",
            (payload["uuid"], "fo", orjson.dumps(payload).decode()),
        )
    conn.commit()
    conn.close()


def flow(uuid: str, *associations) -> dict:
    return {
        "uuid": uuid,
        "identifier": uuid,
        "source": "EF 3.1",
        "cas_numbers": [],
        "ec_numbers": [],
        "context_iri": "https://vocab.brightway.one/flow-contexts/envi-air",
        "unit": "kg",
        "unit_iri": "https://vocab.brightway.one/units/unit/KiloGM",
        "prefLabel": [{"@value": uuid, "@language": "en"}],
        "altLabel": [],
        "properties": {},
        "references": [],
        "concept_associations": list(associations),
    }


class StoredMappingsTestCase(unittest.TestCase):
    """What earlier runs wrote is corrected too, not only what this one writes.

    `merge/state.py` folds a stored association back into a rebuilt flow
    unchanged, so a strength written before this pass existed would otherwise
    survive every rebuild.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.db = self.root / "consensus-flows.sqlite3"

    def stored(self, uuid: str) -> list[dict]:
        conn = sqlite3.connect(self.db)
        try:
            (payload,) = conn.execute(
                "SELECT flow_json FROM elementary_flows WHERE uuid = ?", (uuid,)
            ).fetchone()
        finally:
            conn.close()
        return orjson.loads(payload)["concept_associations"]

    def test_the_database_pass_weakens_and_leaves_the_rest_alone(self):
        build_db(self.db, [
            flow(
                "shared",
                association(f"{ECOINVENT}a", f"{CONSENSUS}shared"),
                association(f"{ECOINVENT}b", f"{CONSENSUS}shared"),
            ),
            flow("alone", association(f"{ECOINVENT}c", f"{CONSENSUS}alone")),
        ])
        counts = recompute_match_strengths(self.db)
        self.assertEqual(counts["weakened_ecoinvent-3.12"], 2)
        self.assertEqual(matches(self.stored("shared")), [SKOS_BROAD_MATCH_CURIE] * 2)
        self.assertEqual(matches(self.stored("alone")), [SKOS_EXACT_MATCH_CURIE])

    def test_the_count_spans_flows_the_pass_does_not_rewrite(self):
        """Both ends are found even when only one row is touched.

        The two flows of a pairing sit in different rows, and a row is written
        back only if its own claims changed.
        """
        build_db(self.db, [
            flow("x", association(f"{ECOINVENT}a", f"{CONSENSUS}x")),
            flow("y", association(f"{ECOINVENT}a", f"{CONSENSUS}y")),
        ])
        recompute_match_strengths(self.db)
        self.assertEqual(matches(self.stored("x")), [SKOS_NARROW_MATCH_CURIE])
        self.assertEqual(matches(self.stored("y")), [SKOS_NARROW_MATCH_CURIE])

    def test_the_export_publishes_what_the_pass_settled(self):
        build_db(self.db, [
            flow(
                "shared",
                association(f"{ECOINVENT}a", f"{CONSENSUS}shared"),
                association(f"{ECOINVENT}b", f"{CONSENSUS}shared"),
            ),
        ])
        recompute_match_strengths(self.db)
        made_of = build_simple_export(self.db).correspondences[0].made_of
        self.assertEqual(
            [match_property_key(node.source_concept) for node in made_of],
            [SKOS_BROAD_MATCH_CURIE] * 2,
        )


class ExportIsTheLastWordTestCase(unittest.TestCase):
    """The export settles it again, because it is the last point before publishing.

    In a healthy run the records and the database have already been corrected
    and nothing here changes, which is what the counter reports.  A route into
    the export that skipped the pass -- a database written by an older build,
    say -- still cannot publish the false claim.
    """

    def test_an_uncorrected_payload_is_still_published_correctly(self):
        flows = [
            {"concept_associations": [
                association(f"{ECOINVENT}a", f"{CONSENSUS}x"),
                association(f"{ECOINVENT}b", f"{CONSENSUS}x"),
            ]},
        ]
        _schemes, correspondences, counts = build_correspondences(flows)
        published = [
            match_property_key(node.source_concept)
            for node in correspondences[0].made_of
        ]
        self.assertEqual(published, [SKOS_BROAD_MATCH_CURIE] * 2)
        self.assertEqual(counts["weakened_ecoinvent-3.12"], 2)

    def test_a_corrected_payload_is_published_unchanged(self):
        flows = [
            {"concept_associations": [
                association(f"{ECOINVENT}a", f"{CONSENSUS}x", SKOS_BROAD_MATCH_CURIE),
                association(f"{ECOINVENT}b", f"{CONSENSUS}x", SKOS_BROAD_MATCH_CURIE),
            ]},
        ]
        _schemes, _correspondences, counts = build_correspondences(flows)
        self.assertEqual([k for k in counts if k.startswith("weakened_")], [])

    def test_the_payload_handed_in_is_not_mutated(self):
        """The caller's flows are read, not edited.

        `build_simple_export` projects the same payloads onto the flows as well,
        and `correspondence_stats` builds the document a second time.
        """
        source = association(f"{ECOINVENT}a", f"{CONSENSUS}x")
        other = association(f"{ECOINVENT}b", f"{CONSENSUS}x")
        build_correspondences([{"concept_associations": [source, other]}])
        self.assertEqual(matches([source, other]), [SKOS_EXACT_MATCH_CURIE] * 2)


class ReviewAppTestCase(unittest.TestCase):
    """The curator reading the flow page sees the same word the export publishes.

    The `Match` column read the association's own keys, where the property has
    never been: it is on the source concept, because that is what it is a
    statement about.  Every row printed an em dash.
    """

    def test_the_property_is_read_off_the_source_concept(self):
        from brightway_flows.webapps.app.filters import match_type

        self.assertEqual(
            match_type(association(f"{ECOINVENT}a", f"{CONSENSUS}x")), "exactMatch"
        )
        self.assertEqual(
            match_type(
                association(f"{ECOINVENT}a", f"{CONSENSUS}x", SKOS_BROAD_MATCH_CURIE)
            ),
            "broadMatch",
        )

    def test_an_association_carrying_no_property_shows_nothing(self):
        from brightway_flows.webapps.app.filters import match_type

        self.assertEqual(match_type({XKOS_SOURCE_CONCEPT_CURIE: {"@id": "x"}}), "")


class PublishedArtifactTestCase(unittest.TestCase):
    """The property, over the export a real build produced.

    Skipped where there is none -- CI and a fresh checkout have no data
    directory -- so this is the check that runs on the machine that built the
    list, which is where the 2,309 false claims were counted.
    """

    def test_no_flow_carries_two_exact_matches_from_one_list(self):
        if not HARMONISED_FLOWS_SIMPLE_FILEPATH.exists():
            self.skipTest("harmonised-flows-simple.json.gz not present")
        document = orjson.loads(
            gzip.decompress(HARMONISED_FLOWS_SIMPLE_FILEPATH.read_bytes())
        )
        if not isinstance(document, dict) or "correspondences" not in document:
            self.skipTest("simple export predates the correspondences")
        offenders = []
        for correspondence in document["correspondences"]:
            exact_sources: dict[str, set[str]] = {}
            for node in correspondence.get(XKOS_MADE_OF_CURIE, []):
                source = node.get(XKOS_SOURCE_CONCEPT_CURIE, {})
                target = source.get(SKOS_EXACT_MATCH_CURIE)
                if not isinstance(target, dict):
                    continue
                exact_sources.setdefault(str(target.get("@id")), set()).add(
                    str(source.get("@id"))
                )
            offenders.extend(
                (correspondence.get("@id"), target, sorted(sources)[:3])
                for target, sources in exact_sources.items()
                if len(sources) > 1
            )
        self.assertEqual(
            offenders[:5],
            [],
            f"{len(offenders)} consensus flows carry more than one exact match "
            "from a single source list, which entails that those source flows "
            "are each other (#76).",
        )
