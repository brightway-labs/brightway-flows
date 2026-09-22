"""A deprecated identifier resolves, terminally, and says whether that is safe.

The export carries only non-deprecated flows, so before #39 a consumer holding
an identifier this project had deprecated saw the same thing as one holding an
identifier that was never harmonised: a lookup miss.  These tests cover the
three properties that close that, and the fourth that keeps it honest --

- every deprecated flow gets a record, so no published identifier is silent
- the target is the *end* of the replacement chain, not the next hop
- the reason distinguishes a merge of a flow with itself from one across a
  source-context distinction the consensus vocabulary cannot express
- a record is never emitted for a flow that is also in ``flows``, and the two
  halves of the document agree about which identifier a flow is published under
"""

import sqlite3
import tempfile
import unittest
from pathlib import Path

import orjson

from brightway_flows.additional_flows import ExcludedSourceFlow
from brightway_flows.domain.vocabulary import (
    CONSENSUS_ELEMENTARY_FLOW_IRI_PREFIX,
    DCTERMS_IS_REPLACED_BY,
    DEPRECATION_REASONS,
    OWL_DEPRECATED,
    OWL_DEPRECATED_CURIE,
    deprecation_reason_iri,
)
from brightway_flows.pipeline.exporting import strip_lcia_from_flows
from brightway_flows.pipeline.redirects import (
    build_redirects as _build_redirects,
    withdrawal_redirects,
)
from brightway_flows.pipeline.sqlite import read_source_contexts

#: Source lists, keyed as `read_source_contexts` keys them: name and version,
#: because a context one list renamed between two releases is two keys rather
#: than a difference within one.
EF = "EF 3.1"
ECOINVENT = "ecoinvent 3.12"

WATER = ["Emissions", "Emissions to water", "Emissions to water, unspecified"]
WATER_LONG_TERM = [
    "Emissions", "Emissions to water", "Emissions to water, unspecified (long-term)",
]
#: ecoinvent's spelling of the same place as `WATER`.  A different string, and
#: the reason the comparison is made per list rather than over the pool.
ECOINVENT_WATER = ["water", "unspecified"]


def build_redirects(flows, source_contexts=None, **kwargs):
    """`redirects.build_redirects` over synthetic flows alone.

    The real function reads two curated inputs no synthetic document knows
    about. The retirements neutralise themselves -- each is emitted only where
    the build publishes the flow it points at, and a made-up document publishes
    none -- but a withdrawal names no target, so nothing stops it, and three
    real ecoinvent identifiers would land in the output of every test below.

    They are left out here rather than expected everywhere, because what these
    tests are about is the deprecations. `WithdrawalsTestCase` covers what the
    default does.
    """
    kwargs.setdefault("withdrawals", ())
    return _build_redirects(flows, source_contexts, **kwargs)


def flow(identifier, *, replaced_by=None, **extra):
    """One `flow_json` payload, in the shape the export reads.

    It carries no `source_refs`: since #30 no stored payload does, which is
    why the deprecation reason is decided from a separate mapping and not from
    the flow in hand.
    """
    payload = {
        "uuid": identifier,
        "identifier": identifier,
        "source": "EF 3.1",
        "cas_numbers": [],
        "ec_numbers": [],
        "context_iri": "https://vocab.brightway.one/flow-contexts/envi-watr-unkn",
        "unit": "kg",
        "unit_iri": "https://vocab.brightway.one/units/unit/KiloGM",
        "prefLabel": [{"@value": identifier, "@language": "en"}],
        "altLabel": [],
        "properties": {},
        "references": [],
    }
    if replaced_by is not None:
        payload[OWL_DEPRECATED] = True
        payload["is_replaced_by_uuid"] = replaced_by
    payload.update(extra)
    return payload


def contexts(**by_identifier):
    """The mapping `read_source_contexts` produces, built by hand.

    Each flow's contexts are kept per source list -- `contexts(gone={"EF 3.1":
    [WATER]})` -- because that is what the reason is decided from: the lists
    both flows are in, and not the ones only one of them has (#59).
    """
    return {
        identifier: {
            source_list: frozenset(tuple(path) for path in paths)
            for source_list, paths in by_list.items()
        }
        for identifier, by_list in by_identifier.items()
    }


def reasons(redirects):
    return {
        r.identifier: r.deprecation_reason["@id"].rsplit("/", 1)[-1]
        for r in redirects
    }


class BuildRedirectsTestCase(unittest.TestCase):
    def test_every_deprecated_flow_gets_a_record(self):
        redirects, counts = build_redirects([
            flow("live"),
            flow("gone-a", replaced_by="live"),
            flow("gone-b", replaced_by="live"),
        ])
        self.assertEqual([r.identifier for r in redirects], ["gone-a", "gone-b"])
        self.assertEqual(counts["redirects"], 2)

    def test_no_records_when_nothing_is_deprecated(self):
        """An empty list, not an absent key.

        The whole point of the key is that a consumer can tell "nothing was
        deprecated" from "this export predates redirects", and it can only do
        that if the first case still writes something.
        """
        redirects, counts = build_redirects([flow("live")])
        self.assertEqual(redirects, [])
        self.assertEqual(counts["redirects"], 0)

    def test_the_record_carries_both_the_uuid_and_the_iri(self):
        redirect = build_redirects([flow("live"), flow("gone", replaced_by="live")])[0][0]
        self.assertEqual(redirect.identifier, "gone")
        self.assertEqual(redirect.replaced_by_identifier, "live")
        self.assertEqual(
            redirect.jsonld_id, f"{CONSENSUS_ELEMENTARY_FLOW_IRI_PREFIX}gone"
        )
        self.assertEqual(
            redirect.replaced_by,
            {"@id": f"{CONSENSUS_ELEMENTARY_FLOW_IRI_PREFIX}live"},
        )
        self.assertIs(redirect.deprecated, True)

    def test_a_chain_resolves_to_its_end_not_its_next_hop(self):
        """`a` names `b`, `b` names `c`, and only `c` is live.

        A consumer given `b` would have to look up a second redirect, and a
        third, and write the cycle guard below for itself.
        """
        redirects, _ = build_redirects([
            flow("c"),
            flow("a", replaced_by="b"),
            flow("b", replaced_by="c"),
        ])
        self.assertEqual(
            {r.identifier: r.replaced_by_identifier for r in redirects},
            {"a": "c", "b": "c"},
        )

    def test_a_replacement_cycle_is_counted_rather_than_looped_on(self):
        redirects, counts = build_redirects([
            flow("a", replaced_by="b"),
            flow("b", replaced_by="a"),
        ])
        self.assertEqual(counts["replacement_cycle"], 2)
        # Both still get a record: an unusable redirect is more informative
        # than silence, and the count is what makes it visible.
        self.assertEqual(len(redirects), 2)

    def test_a_target_outside_the_export_is_counted(self):
        _, counts = build_redirects([flow("gone", replaced_by="not-here")])
        self.assertEqual(counts["target_not_published"], 1)

    def test_a_deprecated_flow_with_no_replacement_is_skipped_and_counted(self):
        """No target means no redirect worth publishing.

        A record saying only "deprecated" would replace one silent miss with
        another, so this is a defect to report rather than a record to write.
        """
        redirects, counts = build_redirects([
            flow("live"),
            {**flow("gone"), OWL_DEPRECATED: True},
        ])
        self.assertEqual(redirects, [])
        self.assertEqual(counts["deprecated_without_replacement"], 1)

    def test_the_curie_spelling_of_the_deprecation_flag_is_read(self):
        """Both spellings reach the export, and the flows filter reads both.

        A redirect builder that read only the IRI form would publish a flow in
        `flows` *and* in `redirects`, which contradict each other.
        """
        redirects, _ = build_redirects([
            flow("live"),
            {**flow("gone"), OWL_DEPRECATED_CURIE: True, "is_replaced_by_uuid": "live"},
        ])
        self.assertEqual([r.identifier for r in redirects], ["gone"])

    def test_the_urn_uuid_form_of_the_replacement_link_is_read(self):
        redirects, _ = build_redirects([
            flow("live"),
            {
                **flow("gone"),
                OWL_DEPRECATED: True,
                DCTERMS_IS_REPLACED_BY: "urn:uuid:live",
            },
        ])
        self.assertEqual(redirects[0].replaced_by_identifier, "live")

    def test_a_merge_within_one_source_context_is_an_identity_merge(self):
        redirects, _ = build_redirects(
            [flow("live"), flow("gone", replaced_by="live")],
            contexts(live={EF: [WATER]}, gone={EF: [WATER]}),
        )
        self.assertEqual(reasons(redirects), {"gone": "identity-merge"})

    def test_a_list_only_the_survivor_is_in_is_not_a_collapse(self):
        """The shape all 46 of the 2026-08-12 build's collapses had (#59).

        The deprecated flow came from EF; the survivor from EF and ecoinvent,
        which words the same place differently.  Pooled into one set per flow
        the two differ, and the redirect was published as one to refuse -- but
        the extra element is a second list agreeing about where the survivor
        is, not a distinction the deprecated flow lost.  EF, the list both are
        in, puts them in the same context.
        """
        redirects, _ = build_redirects(
            [flow("live"), flow("gone", replaced_by="live")],
            contexts(
                live={EF: [WATER], ECOINVENT: [ECOINVENT_WATER]},
                gone={EF: [WATER]},
            ),
        )
        self.assertEqual(reasons(redirects), {"gone": "identity-merge"})

    def test_one_shared_list_disagreeing_is_enough_to_be_a_collapse(self):
        """Agreement everywhere else does not buy off one list's distinction.

        EF puts both flows in the same context, but ecoinvent -- which both
        also came from -- drew a line between them, and the merge crossed it.
        """
        redirects, _ = build_redirects(
            [flow("live"), flow("gone", replaced_by="live")],
            contexts(
                live={EF: [WATER], ECOINVENT: [["water", "surface water"]]},
                gone={EF: [WATER], ECOINVENT: [["water", "ground-"]]},
            ),
        )
        self.assertEqual(reasons(redirects), {"gone": "context-collapse"})

    def test_two_flows_sharing_no_source_list_are_unclassified(self):
        """Both sides have contexts, and still nothing to compare.

        Two lists word the same place differently, so EF's spelling against
        ecoinvent's says nothing about whether the two flows were ever in one
        place.  `unclassified` is documented as a case to refuse, which is the
        honest answer rather than a guess in either direction.
        """
        redirects, counts = build_redirects(
            [flow("live"), flow("gone", replaced_by="live")],
            contexts(live={ECOINVENT: [ECOINVENT_WATER]}, gone={EF: [WATER]}),
        )
        self.assertEqual(reasons(redirects), {"gone": "unclassified"})
        self.assertEqual(counts["reason_unclassified"], 1)

    def test_a_merge_across_source_contexts_is_a_context_collapse(self):
        """The case that costs a consumer real numbers.

        `Emissions to water, unspecified` and `… (long-term)` are different EF
        contexts that map to one consensus context, so the two flows compare
        equal and one is deprecated -- but their characterisation factors
        legitimately disagree (#36).  Following this redirect and overwriting
        would be a second arbitrary choice on top of the first.
        """
        redirects, _ = build_redirects(
            [flow("live"), flow("gone", replaced_by="live")],
            contexts(live={EF: [WATER]}, gone={EF: [WATER_LONG_TERM]}),
        )
        self.assertEqual(reasons(redirects), {"gone": "context-collapse"})

    def test_a_partial_context_overlap_is_still_a_collapse(self):
        """The deprecated flow has a context the survivor does not.

        Whatever that context contributed is lost by the merge, so this is the
        unsafe case even though the two sets are not disjoint.
        """
        redirects, _ = build_redirects(
            [flow("live"), flow("gone", replaced_by="live")],
            contexts(live={EF: [WATER]}, gone={EF: [WATER, WATER_LONG_TERM]}),
        )
        self.assertEqual(reasons(redirects), {"gone": "context-collapse"})

    def test_a_missing_source_context_is_unclassified_not_guessed(self):
        redirects, counts = build_redirects(
            [flow("live"), flow("gone", replaced_by="live")],
            contexts(gone={EF: [WATER]}),
        )
        self.assertEqual(reasons(redirects), {"gone": "unclassified"})
        self.assertEqual(counts["reason_unclassified"], 1)

    def test_no_mapping_at_all_classifies_nothing_rather_than_guessing(self):
        """The signature makes the mapping optional; the answer must not.

        A caller with only payloads cannot know why a flow was retired, and
        `unclassified` is documented as the value a consumer must treat as
        unsafe -- so omitting it costs safety, not correctness.
        """
        redirects, _ = build_redirects(
            [flow("live"), flow("gone", replaced_by="live")]
        )
        self.assertEqual(reasons(redirects), {"gone": "unclassified"})

    def test_every_reason_is_a_declared_term(self):
        """An undeclared reason raises rather than minting an IRI on the spot.

        The reason is the field a consumer branches on, so a second spelling of
        one of these would be a silent behaviour change downstream.
        """
        for reason in DEPRECATION_REASONS:
            with self.subTest(reason=reason):
                self.assertTrue(
                    deprecation_reason_iri(reason).endswith(f"/{reason}")
                )
        with self.assertRaises(ValueError):
            deprecation_reason_iri("merged")

    def test_the_identifier_of_a_merge_added_flow_is_resolved(self):
        """Flows the merge added carry only `elementary_flow_id`.

        The export publishes them under it, so a redirect must name the same
        key or it would point at an identifier no flow in the document uses.
        """
        redirects, counts = build_redirects([
            {"elementary_flow_id": "ef-live"},
            {
                "elementary_flow_id": "ef-gone",
                OWL_DEPRECATED: True,
                "is_replaced_by_uuid": "ef-live",
            },
        ])
        self.assertEqual(redirects[0].identifier, "ef-gone")
        self.assertEqual(redirects[0].replaced_by_identifier, "ef-live")
        self.assertEqual(counts["target_not_published"], 0)


class ReadSourceContextsTestCase(unittest.TestCase):
    """`elementary_flow_sources` is where the reason comes from.

    Not the payload: `flow_json` stopped carrying `source_refs` in #30, so a
    builder that read the payload would classify every redirect `unclassified`
    on a current database -- and on the 2026-08-07 build, which still has both,
    the payload copy calls 52 context collapses identity merges, because its
    copy of a merged flow's references is short.  Wrong in the direction that
    tells a consumer a redirect is safe.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = Path(self._tmp.name) / "consensus-flows.sqlite3"

    def build(self, rows, *, create_table=True):
        """*rows* are `(uuid, list name, list version, source metadata)`."""
        conn = sqlite3.connect(self.db)
        if create_table:
            conn.execute(
                "CREATE TABLE elementary_flow_sources ("
                "elementary_flow_uuid TEXT, list_name TEXT, list_version TEXT, "
                "source_metadata_json TEXT)"
            )
            conn.executemany(
                "INSERT INTO elementary_flow_sources VALUES (?, ?, ?, ?)",
                [
                    (uuid, name, version,
                     None if md is None else orjson.dumps(md).decode())
                    for uuid, name, version, md in rows
                ],
            )
        else:
            conn.execute("CREATE TABLE placeholder (x TEXT)")
        conn.commit()
        conn.close()

    def test_one_flow_collects_every_context_its_sources_carried(self):
        self.build([
            ("gone", "EF", "3.1", {"original_context": WATER}),
            ("gone", "EF", "3.1", {"original_context": WATER_LONG_TERM}),
            ("live", "EF", "3.1", {"original_context": WATER}),
        ])
        self.assertEqual(
            read_source_contexts(self.db),
            contexts(
                gone={EF: [WATER, WATER_LONG_TERM]},
                live={EF: [WATER]},
            ),
        )

    def test_the_contexts_of_two_lists_are_kept_apart(self):
        """One flow, two lists, and the two are not pooled.

        Pooled, this flow's set holds three paths and nothing says which list
        drew which -- so a deprecated flow with only the EF path compares
        unequal, and the redirect is published as one to refuse (#59).
        """
        self.build([
            ("live", "EF", "3.1", {"original_context": WATER}),
            ("live", "ecoinvent", "3.12", {"original_context": ECOINVENT_WATER}),
            ("live", "ecoinvent", "3.12", {"original_context": ["water", "ground-"]}),
        ])
        self.assertEqual(
            read_source_contexts(self.db),
            contexts(live={
                EF: [WATER],
                ECOINVENT: [ECOINVENT_WATER, ["water", "ground-"]],
            }),
        )

    def test_two_versions_of_one_list_are_two_keys(self):
        """A context renamed between releases is not a distinction it drew.

        Keyed by name alone, ecoinvent 3.8's spelling and 3.12's would sit in
        one set, and a flow present in only one release would compare unequal
        to one present in both -- the same error as pooling two lists, one
        level down.
        """
        self.build([
            ("live", "ecoinvent", "3.8", {"original_context": ["water", "unspecified"]}),
            ("live", "ecoinvent", "3.12", {"original_context": ["water", "unknown"]}),
        ])
        self.assertEqual(
            read_source_contexts(self.db),
            contexts(live={
                "ecoinvent 3.8": [["water", "unspecified"]],
                "ecoinvent 3.12": [["water", "unknown"]],
            }),
        )

    def test_a_flow_with_no_context_is_absent_rather_than_empty(self):
        """Absent and empty mean the same thing to `_classify`.

        Both produce `unclassified`, so this asserts the cheaper shape rather
        than a distinction the caller does not make.
        """
        self.build([
            ("no-metadata", "EF", "3.1", None),
            ("no-context", "EF", "3.1", {"input_dataset": "EF 3.1"}),
            ("live", "EF", "3.1", {"original_context": WATER}),
        ])
        self.assertEqual(read_source_contexts(self.db), contexts(live={EF: [WATER]}))

    def test_a_database_without_the_table_yields_nothing(self):
        """A bounded run writes no `elementary_flow_sources`.

        The export still has to be produced, with every redirect saying it
        cannot classify itself rather than the build failing.
        """
        self.build([], create_table=False)
        self.assertEqual(read_source_contexts(self.db), {})


class WithdrawalsTestCase(unittest.TestCase):
    """A deprecation with no survivor, because the flow should not have existed.

    Every other record here names where an identifier went. A withdrawal names
    nowhere, on purpose: the source row it was minted from is one this list has
    decided not to map, so the substance did not move -- it was never a
    substance of ours (#115). A consumer holding the identifier should drop the
    exchange, and the reason is what tells them so.
    """

    def _excluded(self, uuid="u1", withdrew="gone", **overrides):
        record = {
            "uuid": uuid,
            "name": "venting of something",
            "unit": "kg",
            "context": ("social", "unspecified"),
            "reason": "A product, not an elementary flow.",
            "source": "ecoinvent-3.8",
            "withdrew_identifier": withdrew,
        }
        record.update(overrides)
        return ExcludedSourceFlow(**record)

    def test_a_withdrawal_is_published_with_no_replacement(self):
        records, counts = withdrawal_redirects(set(), (self._excluded(),))
        self.assertEqual(len(records), 1)
        self.assertIsNone(records[0].replaced_by_identifier)
        self.assertIsNone(records[0].replaced_by)
        self.assertEqual(counts["withdrawals_published"], 1)

    def test_the_reason_says_the_row_was_withdrawn(self):
        records, _ = withdrawal_redirects(set(), (self._excluded(),))
        self.assertEqual(
            records[0].deprecation_reason,
            {"@id": deprecation_reason_iri("source-row-withdrawn")},
        )

    def test_a_row_excluded_before_it_was_ever_published_writes_nothing(self):
        """The ordinary case for every exclusion written from now on."""
        records, counts = withdrawal_redirects(
            set(), (self._excluded(withdrew=""),)
        )
        self.assertEqual(records, [])
        self.assertEqual(counts["withdrawn_never_published"], 1)

    def test_an_identifier_that_is_live_again_is_refused_and_counted(self):
        """The exclusion undone in one file and not the other.

        Publishing this would tell a consumer that a flow the very same
        document carries has been withdrawn.
        """
        records, counts = withdrawal_redirects({"gone"}, (self._excluded(),))
        self.assertEqual(records, [])
        self.assertEqual(counts["withdrawn_still_published"], 1)

    def test_the_reason_is_declared_in_the_published_vocabulary(self):
        self.assertIn("source-row-withdrawn", DEPRECATION_REASONS)


class RedirectsInTheDocumentTestCase(unittest.TestCase):
    """The two halves of the export have to agree with each other."""

    def setUp(self):
        self.export = strip_lcia_from_flows(
            [flow("live"), flow("gone", replaced_by="live")],
            contexts(live={EF: [WATER]}, gone={EF: [WATER_LONG_TERM]}),
        )

    def test_a_deprecated_flow_is_in_redirects_and_not_in_flows(self):
        self.assertEqual([f.identifier for f in self.export.flows], ["live"])
        self.assertIn("gone", [r.identifier for r in self.export.redirects])
        self.assertNotIn("gone", [f.identifier for f in self.export.flows])

    def test_every_redirect_that_names_a_target_names_a_published_flow(self):
        """A redirect onto an identifier the document does not carry is a miss
        wearing a record's clothes, which is what these records exist to remove.
        """
        published = {f.identifier for f in self.export.flows}
        for redirect in self.export.redirects:
            if redirect.replaced_by_identifier is None:
                continue
            with self.subTest(redirect=redirect.identifier):
                self.assertIn(redirect.replaced_by_identifier, published)

    def test_the_only_records_with_no_target_are_withdrawals(self):
        """Absence has to be a stated decision, never an unexplained hole.

        A deprecated flow whose replacement is missing is not written at all --
        see `test_a_deprecated_flow_with_no_replacement_is_skipped_and_counted`.
        So a record here with no `dcterms:isReplacedBy` can only be a withdrawal,
        and it says so.
        """
        for redirect in self.export.redirects:
            if redirect.replaced_by_identifier is not None:
                continue
            with self.subTest(redirect=redirect.identifier):
                self.assertIsNone(redirect.replaced_by)
                self.assertEqual(
                    redirect.deprecation_reason,
                    {"@id": deprecation_reason_iri("source-row-withdrawn")},
                )

    def test_a_withdrawal_omits_the_replacement_keys_rather_than_emptying_them(self):
        """`{}` or `""` would read as a replacement the document forgot to fill."""
        withdrawn = next(
            r for r in self.export.redirects if r.replaced_by_identifier is None
        )
        payload = withdrawn.to_dict()
        self.assertNotIn(DCTERMS_IS_REPLACED_BY, payload)
        self.assertNotIn("replaced_by_identifier", payload)
        self.assertEqual(payload[OWL_DEPRECATED], True)

    def test_the_serialised_record_uses_the_declared_predicates(self):
        payload = next(
            r for r in self.export.redirects if r.identifier == "gone"
        ).to_dict()
        self.assertEqual(payload[OWL_DEPRECATED], True)
        self.assertEqual(
            payload[DCTERMS_IS_REPLACED_BY],
            {"@id": f"{CONSENSUS_ELEMENTARY_FLOW_IRI_PREFIX}live"},
        )
        self.assertEqual(
            payload["https://vocab.brightway.one/terms/deprecationReason"],
            {"@id": deprecation_reason_iri("context-collapse")},
        )

    def test_the_withdrawals_are_the_three_ecoinvent_rows_this_list_refuses(self):
        """The default input, not a fixture: the registry is what publishes them.

        These are the three flows ecoinvent 3.8's APOS release duplicates from
        its product list into its elementary list, which this list published
        until #115 and now refuses. They are emitted whether or not a build
        merges ecoinvent 3.8 -- the claim is about an identifier this project
        published, and a build merging fewer lists does not un-withdraw it.
        """
        withdrawn = {
            r.identifier
            for r in self.export.redirects
            if r.replaced_by_identifier is None
        }
        self.assertEqual(withdrawn, {
            "3b5f85d9601a67605e692bb34b268dd3e2b6e41c",
            "e3378e2056920fcd33aaa3650e0c8ae90e47468d",
            "a2b1125471a3d31a3094deb35114e6e62d809d73",
        })

    def test_every_key_the_records_emit_is_declared_in_the_context(self):
        """A key the `@context` does not declare contributes nothing to the graph.

        `replaced_by_identifier` is declared as `null` on purpose -- it is the
        UUID lookup #39 asked for, and mapping it to a minted predicate would
        put a second, weaker name on `dcterms:isReplacedBy`.  Declared and
        dropped is a decision; undeclared is an oversight, and this cannot tell
        the difference unless the term is present.
        """
        context = self.export.jsonld_context
        for key in self.export.redirects[0].to_dict():
            with self.subTest(key=key):
                self.assertTrue(
                    key.startswith("@") or key.startswith("http") or key in context,
                    f"{key} is emitted but not declared in @context",
                )
        self.assertIn("replaced_by_identifier", context)
        self.assertIsNone(context["replaced_by_identifier"])
        self.assertEqual(context["redirects"], "@included")


if __name__ == "__main__":
    unittest.main()
