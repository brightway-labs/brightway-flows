"""Which mappings a build publishes, and what they claim.

Two things were wrong at once (#244). GLAD -- an 11 MB, 124,318-row EF 3.1 to
SimaPro correspondence table -- was downloaded and parsed by every `extract` to
feed a builder that no run registered, so it cost every build and published
nothing. And the builder, had it been switched on, would have minted one IRI per
`TargetFlowUUID`: that column identifies a *substance*, so 25,732 of the 31,907
IRIs it minted stood for more than one consensus flow, each with its own
`skos:exactMatch`. `skos:exactMatch` is symmetric and transitive, so publishing
that would have entailed that Beryllium and Beryllium(2+) are the same concept.

These cover both: a correspondence table is read only by a run that asked for
it, and what it publishes is a claim the table supports.
"""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import orjson

from brightway_flows.domain.context_registry import context_for_iri

AIR_IRI = "https://vocab.brightway.one/flow-contexts/envi-air-unkn"
from brightway_flows.domain.elementary_flow import ElementaryFlow
from brightway_flows.domain.vocabulary import (
    QUDT_CONVERSION_MULTIPLIER_CURIE,
    QUDT_HAS_UNIT_CURIE,
    SKOS_BROAD_MATCH_CURIE,
    SKOS_EXACT_MATCH_CURIE,
    SKOS_NARROW_MATCH_CURIE,
    SKOS_PREF_LABEL_CURIE,
    SKOS_RELATED_MATCH_CURIE,
    source_scheme,
)
from brightway_flows.pipeline import concept_associations as ca
from brightway_flows.domain.vocabulary import scheme_for_flow_iri
from brightway_flows.sources import (
    PAIR_SOURCES,
    ConceptAssociationSpec,
    SourceList,
    base_source_list,
    resolve_source_list,
)

SIMAPRO = source_scheme("simapro-10.2")
SIMAPRO_PREFIX = SIMAPRO.flow_prefix


def _flow(flow_id, *, unit="kg", refs=None, deprecated=None, replaced_by=None):
    return ElementaryFlow(
        elementary_flow_id=flow_id,
        flow_object_id=f"obj-{flow_id}",
        source="EF 3.1",
        source_refs=refs,
        context=context_for_iri(AIR_IRI),
        context_iri=AIR_IRI,
        unit=unit,
        unit_iri="",
        lcia_methods=[],
        general_comment=None,
        owl_deprecated=deprecated,
        is_replaced_by_uuid=replaced_by,
    )


def _glad_row(source_uuid, target_uuid, context, **overrides):
    row = {
        "SourceListName": "ILCD/EF 3.1",
        "SourceFlowUUID": source_uuid,
        "SourceUnit": "kg",
        "MatchCondition": "=",
        "ConversionFactor": 1,
        "TargetListName": "SimaPro/Professional 10.2",
        "TargetFlowName": f"Flow {target_uuid}",
        "TargetFlowUUID": target_uuid,
        "TargetFlowContext": context,
        "TargetUnit": "kg",
        "TargetGeography": None,
    }
    row.update(overrides)
    return row


def _simapro_list(**overrides):
    """A list whose flows originate in SimaPro, as a manifest would declare it."""
    defaults = dict(
        list_name="stepwise",
        list_version="2006",
        flows_path=Path("/nonexistent/stepwise-2006-flows.json"),
        flow_iri_prefix="https://vocab.brightway.one/stepwise/2006/flow/",
        concept_associations=ConceptAssociationSpec(
            scheme="simapro-10.2", pairs_from="glad"
        ),
    )
    defaults.update(overrides)
    return SourceList(**defaults)


class _GladFixture:
    """Runs a set of GLAD rows against a set of flows, in a temp data directory."""

    def __init__(self, rows, flows, source=None):
        self.rows = rows
        self.flows = flows
        self.source = source or _simapro_list()

    def __enter__(self):
        self._tmp = tempfile.TemporaryDirectory()
        path = Path(self._tmp.name) / "glad.json"
        path.write_bytes(orjson.dumps(self.rows))
        self._patch = mock.patch.object(
            ca, "glad_ilcd_to_simapro_path", lambda: path
        )
        self._patch.start()
        builders = ca.builders_for([self.source])
        ca._attach_concept_associations(self.flows, builders)
        return {
            flow.elementary_flow_id: flow.concept_associations or []
            for flow in self.flows
        }

    def __exit__(self, *exc):
        self._patch.stop()
        self._tmp.cleanup()
        return False


def _sources_of(associations):
    return [row["xkos:sourceConcept"] for row in associations]


def _match_of(source_node):
    """The one SKOS mapping property on a source concept."""
    matches = [
        key for key in source_node
        if key.startswith("skos:") and key.endswith("Match")
    ]
    assert len(matches) == 1, matches
    return matches[0]


class ManifestVocabularyTestCase(unittest.TestCase):
    """A manifest may only ask for something that can be built."""

    def test_every_declared_pair_source_has_an_implementation(self):
        self.assertEqual(set(PAIR_SOURCES), set(ca._PAIR_SOURCES))

    def test_an_unknown_pair_source_fails_when_the_manifest_is_read(self):
        with self.assertRaises(ValueError) as caught:
            ConceptAssociationSpec.from_manifest(
                {"scheme": "ef-3.1", "pairs_from": "telepathy"},
                path=Path("made-up.json"),
            )
        self.assertIn("telepathy", str(caught.exception))

    def test_an_unregistered_scheme_fails_when_the_manifest_is_read(self):
        """Not at export time. An association whose source belongs to no
        registered scheme is dropped and counted, so a slug typo would publish
        nothing and say nothing."""
        with self.assertRaises(ValueError) as caught:
            ConceptAssociationSpec.from_manifest(
                {"scheme": "simapro-9.9", "pairs_from": "glad"},
                path=Path("made-up.json"),
            )
        self.assertIn("simapro-9.9", str(caught.exception))

    def test_the_base_list_declares_the_builder_that_used_to_be_hard_coded(self):
        spec = base_source_list().concept_associations
        self.assertIsNotNone(spec)
        self.assertEqual(spec.scheme, "ef-3.1")
        self.assertEqual(spec.pairs_from, "source_refs")


class ActivationTestCase(unittest.TestCase):
    """A correspondence table is read by a run that has a use for it."""

    def test_the_base_list_always_contributes_its_mappings(self):
        builders = ca.builders_for([base_source_list()])
        self.assertEqual([b.name for b in builders], ["ef-3.1"])

    def test_a_list_declaring_none_adds_no_builder(self):
        """ecoinvent's mappings are written by the merge, onto the flows, so it
        declares no builder and must not acquire one by being merged."""
        ecoinvent = resolve_source_list("ecoinvent-3.12")
        self.assertIsNone(ecoinvent.concept_associations)
        builders = ca.builders_for([base_source_list(), ecoinvent])
        self.assertEqual([b.name for b in builders], ["ef-3.1"])

    def test_glad_is_not_opened_by_a_run_that_names_no_simapro_list(self):
        """The whole of #244: the table cost every build and fed nothing."""
        with mock.patch.object(ca, "glad_ilcd_to_simapro_path") as located:
            builders = ca.builders_for([
                base_source_list(), resolve_source_list("ecoinvent-3.12")
            ])
            ca._attach_concept_associations([_flow("f-1")], builders)
        located.assert_not_called()

    def test_a_simapro_derived_list_switches_it_on(self):
        builders = ca.builders_for([base_source_list(), _simapro_list()])
        self.assertEqual([b.name for b in builders], ["ef-3.1", "simapro-10.2"])

    def test_a_missing_table_is_a_warning_and_no_mappings(self):
        """Not a crash: a data directory without the table is what a first run
        on a new machine looks like."""
        builders = ca.builders_for([_simapro_list()])
        flows = [_flow("f-1")]
        with mock.patch.object(
            ca, "glad_ilcd_to_simapro_path", lambda: Path("/nonexistent/glad.json")
        ):
            ca._attach_concept_associations(flows, builders)
        self.assertIsNone(flows[0].concept_associations)


class SourceRefMappingsTestCase(unittest.TestCase):
    """The EF 3.1 mappings, which ship today and must not move."""

    def _built(self):
        flows = [
            _flow(
                "u-1",
                refs=[{
                    "list_name": "EF",
                    "source_flow_uuid": "u-1",
                    "source_flow_name": "Carbon dioxide",
                    "source_metadata": {
                        "original_context": ["Emissions", "Emissions to air"]
                    },
                }],
            )
        ]
        ca._attach_concept_associations(flows, ca.builders_for([base_source_list()]))
        return flows[0].concept_associations

    def test_the_source_concept_is_unchanged_in_shape_and_order(self):
        (association,) = self._built()
        source = association["xkos:sourceConcept"]
        self.assertEqual(
            list(source),
            ["@id", SKOS_PREF_LABEL_CURIE, "context", QUDT_HAS_UNIT_CURIE,
             SKOS_EXACT_MATCH_CURIE],
        )
        self.assertEqual(source["@id"], "https://vocab.brightway.one/ef/3.1/flow/u-1")
        self.assertEqual(source["context"], "Emissions/Emissions to air")

    def test_the_primary_source_comes_from_the_manifest(self):
        (association,) = self._built()
        self.assertEqual(
            association["provenance"]["prov:hadPrimarySource"],
            ["https://eplca.jrc.ec.europa.eu/permalink/EF3_1/EF-v3.1.zip"],
        )

    def test_a_ref_from_another_list_is_not_claimed(self):
        flows = [
            _flow("u-1", refs=[{
                "list_name": "ecoinvent",
                "source_flow_uuid": "e-1",
                "source_flow_name": "Carbon dioxide",
                "source_metadata": {},
            }])
        ]
        ca._attach_concept_associations(flows, ca.builders_for([base_source_list()]))
        self.assertIsNone(flows[0].concept_associations)


class GladIriTestCase(unittest.TestCase):
    """`TargetFlowUUID` names a substance. A SimaPro flow is one in a compartment."""

    def test_one_substance_in_two_compartments_is_two_concepts(self):
        rows = [
            _glad_row("f-1", "sp-1", "Airborne emissions/indoor"),
            _glad_row("f-2", "sp-1", "Airborne emissions/high. pop."),
        ]
        with _GladFixture(rows, [_flow("f-1"), _flow("f-2")]) as built:
            first = _sources_of(built["f-1"])[0]["@id"]
            second = _sources_of(built["f-2"])[0]["@id"]
        self.assertEqual(first, f"{SIMAPRO_PREFIX}sp-1/airborne-emissions-indoor")
        self.assertEqual(second, f"{SIMAPRO_PREFIX}sp-1/airborne-emissions-high-pop")
        self.assertNotEqual(first, second)

    def test_two_compartments_of_one_substance_on_one_flow_stay_apart(self):
        """The Beryllium case: six air subcompartments collapsed onto one
        consensus flow, all minting the same IRI."""
        rows = [
            _glad_row("f-1", "sp-1", "Airborne emissions/indoor"),
            _glad_row("f-1", "sp-1", "Airborne emissions/(unspecified)"),
        ]
        with _GladFixture(rows, [_flow("f-1")]) as built:
            iris = [node["@id"] for node in _sources_of(built["f-1"])]
        self.assertEqual(len(set(iris)), 2)

    def test_rows_differing_only_outside_the_iri_are_one_association(self):
        """99 GLAD rows differ only by `TargetGeography`, which the source
        concept does not carry. One pair, one association."""
        rows = [
            _glad_row("f-1", "sp-1", "Raw materials/land", TargetGeography=None),
            _glad_row("f-1", "sp-1", "Raw materials/land", TargetGeography="RS"),
        ]
        with _GladFixture(rows, [_flow("f-1")]) as built:
            self.assertEqual(len(built["f-1"]), 1)

    def test_a_row_with_no_compartment_names_no_flow_and_is_dropped(self):
        rows = [_glad_row("f-1", "sp-1", "/")]
        with _GladFixture(rows, [_flow("f-1")]) as built:
            self.assertEqual(built["f-1"], [])

    def test_the_minted_iri_belongs_to_the_scheme_the_export_recovers(self):
        """`build_correspondences` works out which scheme a mapping belongs to
        by matching the source IRI against the registered prefixes, so a minted
        IRI that does not start with one is dropped."""
        rows = [_glad_row("f-1", "sp-1", "Airborne emissions/indoor")]
        with _GladFixture(rows, [_flow("f-1")]) as built:
            iri = _sources_of(built["f-1"])[0]["@id"]
        self.assertEqual(scheme_for_flow_iri(iri), SIMAPRO)


class GladMatchPropertyTestCase(unittest.TestCase):
    """`MatchCondition` is `=` on all 124,318 rows and cannot be believed."""

    def test_a_one_to_one_pair_is_an_exact_match(self):
        rows = [_glad_row("f-1", "sp-1", "Airborne emissions/indoor")]
        with _GladFixture(rows, [_flow("f-1")]) as built:
            self.assertEqual(_match_of(_sources_of(built["f-1"])[0]), SKOS_EXACT_MATCH_CURIE)

    def test_many_simapro_flows_on_one_consensus_flow_are_narrower(self):
        """SimaPro's per-country water flows: 441 of them on one consensus flow,
        each a narrower concept, none of them equal to it."""
        rows = [
            _glad_row("f-1", "sp-1", "Raw materials/", TargetFlowName="Water, well, AU-NSW"),
            _glad_row("f-1", "sp-2", "Raw materials/", TargetFlowName="Water, well, AU-QLD"),
        ]
        with _GladFixture(rows, [_flow("f-1")]) as built:
            matches = {_match_of(node) for node in _sources_of(built["f-1"])}
        self.assertEqual(matches, {SKOS_BROAD_MATCH_CURIE})

    def test_one_simapro_flow_on_many_consensus_flows_is_broader(self):
        rows = [
            _glad_row("f-1", "sp-1", "Airborne emissions/indoor"),
            _glad_row("f-2", "sp-1", "Airborne emissions/indoor"),
        ]
        with _GladFixture(rows, [_flow("f-1"), _flow("f-2")]) as built:
            matches = {
                _match_of(_sources_of(built[key])[0]) for key in ("f-1", "f-2")
            }
        self.assertEqual(matches, {SKOS_NARROW_MATCH_CURIE})

    def test_many_to_many_is_related_rather_than_guessed(self):
        rows = [
            _glad_row("f-1", "sp-1", "Airborne emissions/indoor"),
            _glad_row("f-2", "sp-1", "Airborne emissions/indoor"),
            _glad_row("f-1", "sp-2", "Airborne emissions/indoor"),
        ]
        with _GladFixture(rows, [_flow("f-1"), _flow("f-2")]) as built:
            by_iri = {
                node["@id"]: _match_of(node) for node in _sources_of(built["f-1"])
            }
        self.assertEqual(
            by_iri[f"{SIMAPRO_PREFIX}sp-1/airborne-emissions-indoor"],
            SKOS_RELATED_MATCH_CURIE,
        )
        self.assertEqual(
            by_iri[f"{SIMAPRO_PREFIX}sp-2/airborne-emissions-indoor"],
            SKOS_BROAD_MATCH_CURIE,
        )


class GladDeprecationTestCase(unittest.TestCase):
    """A table pairs with the list as it was; the duplicate pass moves it after."""

    def test_a_mapping_onto_a_deprecated_flow_follows_the_replacement(self):
        rows = [_glad_row("gone", "sp-1", "Airborne emissions/indoor")]
        flows = [
            _flow("kept"),
            _flow("gone", deprecated=True, replaced_by="kept"),
        ]
        with _GladFixture(rows, flows) as built:
            self.assertEqual(len(built["kept"]), 1)
            self.assertEqual(built["gone"], [])

    def test_a_chain_of_replacements_is_followed_to_the_live_flow(self):
        rows = [_glad_row("first", "sp-1", "Airborne emissions/indoor")]
        flows = [
            _flow("first", deprecated=True, replaced_by="second"),
            _flow("second", deprecated=True, replaced_by="third"),
            _flow("third"),
        ]
        with _GladFixture(rows, flows) as built:
            self.assertEqual(len(built["third"]), 1)

    def test_a_deprecated_flow_with_no_replacement_drops_its_mapping(self):
        rows = [_glad_row("gone", "sp-1", "Airborne emissions/indoor")]
        with _GladFixture(rows, [_flow("gone", deprecated=True)]) as built:
            self.assertEqual(built["gone"], [])

    def test_a_row_naming_no_flow_in_this_list_is_dropped(self):
        rows = [_glad_row("stranger", "sp-1", "Airborne emissions/indoor")]
        with _GladFixture(rows, [_flow("f-1")]) as built:
            self.assertEqual(built["f-1"], [])


class GladValuesTestCase(unittest.TestCase):
    def test_the_target_unit_is_published_as_an_iri(self):
        rows = [_glad_row("f-1", "sp-1", "Waterborne emissions/river", TargetUnit="m3")]
        with _GladFixture(rows, [_flow("f-1")]) as built:
            node = _sources_of(built["f-1"])[0]
        self.assertEqual(
            node[QUDT_HAS_UNIT_CURIE],
            {"@id": "https://vocab.brightway.one/units/unit/M3"},
        )

    def test_glads_separator_free_unit_spellings_resolve(self):
        """`m2a` is `m2*a`, which both lists agree on. 1,556 source concepts
        shipped with no unit over punctuation."""
        rows = [_glad_row("f-1", "sp-1", "Raw materials/land", TargetUnit="m2a")]
        with _GladFixture(rows, [_flow("f-1")]) as built:
            node = _sources_of(built["f-1"])[0]
        self.assertEqual(
            node[QUDT_HAS_UNIT_CURIE],
            {"@id": "https://vocab.brightway.one/units/unit/M2-YR"},
        )

    def test_a_real_conversion_factor_is_published(self):
        rows = [_glad_row(
            "f-1", "sp-1", "Waterborne emissions/ocean",
            TargetUnit="m3", ConversionFactor=0.001,
        )]
        with _GladFixture(rows, [_flow("f-1")]) as built:
            self.assertEqual(built["f-1"][0][QUDT_CONVERSION_MULTIPLIER_CURIE], 0.001)

    def test_a_factor_of_one_is_not_published(self):
        rows = [_glad_row("f-1", "sp-1", "Airborne emissions/indoor")]
        with _GladFixture(rows, [_flow("f-1")]) as built:
            self.assertNotIn(QUDT_CONVERSION_MULTIPLIER_CURIE, built["f-1"][0])

    def test_the_primary_source_is_the_table_when_the_manifest_names_none(self):
        rows = [_glad_row("f-1", "sp-1", "Airborne emissions/indoor")]
        with _GladFixture(rows, [_flow("f-1")]) as built:
            provenance = built["f-1"][0]["provenance"]
        self.assertEqual(
            provenance["prov:hadPrimarySource"], [ca.GLAD_PRIMARY_SOURCE]
        )

    def test_a_manifest_may_name_its_own_primary_source(self):
        source = _simapro_list(
            concept_associations=ConceptAssociationSpec(
                scheme="simapro-10.2",
                pairs_from="glad",
                primary_source="https://example.invalid/fork",
            )
        )
        rows = [_glad_row("f-1", "sp-1", "Airborne emissions/indoor")]
        with _GladFixture(rows, [_flow("f-1")], source=source) as built:
            provenance = built["f-1"][0]["provenance"]
        self.assertEqual(
            provenance["prov:hadPrimarySource"], ["https://example.invalid/fork"]
        )


class BuilderCompositionTestCase(unittest.TestCase):
    """Two builders on one run put both lists' mappings on the same flow."""

    def test_both_lists_reach_the_flow(self):
        flows = [
            _flow("f-1", refs=[{
                "list_name": "EF",
                "source_flow_uuid": "f-1",
                "source_flow_name": "Carbon dioxide",
                "source_metadata": {"original_context": ["Emissions"]},
            }])
        ]
        rows = [_glad_row("f-1", "sp-1", "Airborne emissions/indoor")]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "glad.json"
            path.write_bytes(orjson.dumps(rows))
            with mock.patch.object(ca, "glad_ilcd_to_simapro_path", lambda: path):
                builders = ca.builders_for([base_source_list(), _simapro_list()])
                ca._attach_concept_associations(flows, builders)
        iris = [node["@id"] for node in _sources_of(flows[0].concept_associations)]
        self.assertEqual(len(iris), 2)
        self.assertEqual(
            sorted(scheme_for_flow_iri(iri).slug for iri in iris),
            ["ef-3.1", "simapro-10.2"],
        )


if __name__ == "__main__":
    unittest.main()
