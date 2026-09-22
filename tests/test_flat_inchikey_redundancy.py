"""A key with the stereochemistry taken off is not a second identity (#50).

`L-tryptophan` published two InChIKeys: `QIVBCDIJIAJPQS-VIFPVBQESA-N`, which is
its own, and `QIVBCDIJIAJPQS-UHFFFAOYSA-N`, which is the same skeleton with the
stereochemistry deleted -- and is `DL-tryptophan`'s real key.  Both sat in one
slot with nothing marking which was which, so anything using the field as an
identity read the substance as having two candidate structures, and a merge rule
keying on it fused two substances that are different.  419 flow objects and
5,416 elementary flows on the 2026-08-12 build.

Nothing is lost by dropping the flat one.  Block 1 of an InChIKey hashes
connectivity alone, so the flat key is the specific key with block 2 replaced by
`UHFFFAOYSA` -- a consumer who wants it can write it out from the key that
survives, without a chemistry toolkit and without the structure.

What is pinned here:

- **The rule groups by skeleton, not by record.**  A record holding a flat key
  for a skeleton it has no specific key for keeps it: that is the wrong-hit
  structure of #6 and #38, and it is the only evidence the wrong hit is
  there.  47 of the 474 flat keys sharing a record with a specific one.
- **Every stage that writes the slot refuses it at the write**, in both
  directions -- the flat key is not added when the specific one is already
  there, and is withdrawn when the specific one arrives afterwards.  Refusing at
  the write rather than sweeping at the end is what keeps the value out of the
  stages that read the slot between the two.
- **The normalisation is the net for the path that has no stage**, because
  `merge.creations` writes flow objects into SQLite without the transform
  engine.
"""

import unittest
from typing import Any

from brightway_flows.domain.flow import Flow
from brightway_flows.domain.flow_object import FlowObject
from brightway_flows.domain.inchikey import without_redundant_flat_keys
from brightway_flows.domain.property_values import (
    normalise_records,
    redundant_flat_inchikey_slots,
)
from brightway_flows.domain.vocabulary import (
    CHEMROF_INCHI2D_KEY_STRING,
    CHEMROF_SMILES_STRING,
)
from brightway_flows.transformers.enrich_references import (
    EnrichReferencesTransformer,
)
from brightway_flows.transformers.rdkit_enrichment import (
    RDKitPreConsensusTransformer,
)
from brightway_flows.transformers.rdkit_post_consensus import (
    RDKitPostConsensusTransformer,
)

#: L-tryptophan's own key, and the flat form of the same skeleton -- which is
#: what `DL-tryptophan` (54-12-6) is registered as.
TRP_SPECIFIC = "QIVBCDIJIAJPQS-VIFPVBQESA-N"
TRP_FLAT = "QIVBCDIJIAJPQS-UHFFFAOYSA-N"
#: The same substance, drawn with and without its stereochemistry.
TRP_SPECIFIC_SMILES = "N[C@@H](Cc1c[nH]c2ccccc12)C(=O)O"
TRP_FLAT_SMILES = "C1=CC=C2C(=C1)C(=CN2)CC(C(=O)O)N"

#: `D-menthol` carries its own key, that key's flat form, and a third key that
#: belongs to a different chemical altogether.
MENTHOL_SPECIFIC = "NOOLISFMXDJSKH-AEJSXWLSSA-N"
MENTHOL_FLAT = "NOOLISFMXDJSKH-UHFFFAOYSA-N"
MENTHOL_WRONG_HIT = "TWDOPJXHIBEHIL-UHFFFAOYSA-N"


def _key_property(values: list[str]) -> dict[str, Any]:
    return {
        CHEMROF_INCHI2D_KEY_STRING: {
            "@id": CHEMROF_INCHI2D_KEY_STRING,
            "rdfs:label": "InChIKey",
            "@value": list(values),
            "provenance": {"prov:wasGeneratedBy": "enrich_references.chebi_semantic"},
        }
    }


def _smiles_property(values: list[str]) -> dict[str, Any]:
    return {
        CHEMROF_SMILES_STRING: {
            "@id": CHEMROF_SMILES_STRING,
            "rdfs:label": "SMILES",
            "@value": list(values),
            "provenance": {"prov:wasGeneratedBy": "enrich_references.pubchem_semantic"},
        }
    }


def _flow(properties: dict[str, Any]) -> Flow:
    return Flow(
        uuid="u-1",
        source="EF 3.1",
        unit="kg",
        prefLabel=[{"@value": "L-tryptophan", "@language": "en"}],
        properties=properties,
    )


def _flow_object(properties: dict[str, Any]) -> FlowObject:
    return FlowObject(
        flow_object_id="fo-tryptophan",
        prefLabel=[{"@value": "L-tryptophan", "@language": "en"}],
        altLabel=[],
        properties=properties,
        references=[],
        created_from={},
        classifications={},
    )


def _applied(transformer: Any, flow: Flow) -> dict[str, Any]:
    """The properties the transformer proposes, or the ones it left alone."""
    for change in transformer.transform([flow]):
        if change.field == "properties":
            return change.new_value
    return flow.properties


def _keys(properties: dict[str, Any]) -> list[str]:
    return properties[CHEMROF_INCHI2D_KEY_STRING]["@value"]


class RuleTestCase(unittest.TestCase):
    """What `without_redundant_flat_keys` keeps and what it drops."""

    def test_the_flat_form_of_a_key_the_record_states_is_dropped(self):
        self.assertEqual(
            without_redundant_flat_keys([TRP_FLAT, TRP_SPECIFIC]), [TRP_SPECIFIC]
        )

    def test_a_flat_key_for_another_skeleton_is_kept(self):
        """`D-menthol`'s third key is a wrong hit (#38), not a simplification:
        nothing else in the record states that structure, and dropping it would
        take away the only evidence that it is there."""
        self.assertEqual(
            without_redundant_flat_keys(
                [MENTHOL_FLAT, MENTHOL_SPECIFIC, MENTHOL_WRONG_HIT]
            ),
            [MENTHOL_SPECIFIC, MENTHOL_WRONG_HIT],
        )

    def test_a_record_with_only_flat_keys_is_untouched(self):
        """`DL-tryptophan` is a substance whose real key is flat."""
        self.assertEqual(without_redundant_flat_keys([TRP_FLAT]), [TRP_FLAT])

    def test_a_flat_key_in_another_protonation_state_is_kept(self):
        """Block 3 is a difference in the substance, so the flat key is not the
        flat form of *this* specific key."""
        other_protonation = f"{TRP_FLAT[:-1]}O"
        self.assertEqual(
            without_redundant_flat_keys([other_protonation, TRP_SPECIFIC]),
            [other_protonation, TRP_SPECIFIC],
        )

    def test_a_flat_key_from_another_inchi_version_is_kept(self):
        """Two hashing schemes, not two statements about one substance."""
        version_b = TRP_FLAT.replace("-UHFFFAOYSA-", "-UHFFFAOYSB-")
        self.assertEqual(
            without_redundant_flat_keys([version_b, TRP_SPECIFIC]),
            [version_b, TRP_SPECIFIC],
        )

    def test_a_non_standard_flat_key_is_dropped_too(self):
        """A flat hash states nothing about stereochemistry however it was
        computed -- non-standard options can suppress stereochemistry the
        substance has -- so it is never the more specific of the two."""
        non_standard_flat = TRP_FLAT.replace("-UHFFFAOYSA-", "-UHFFFAOYNA-")
        self.assertEqual(
            without_redundant_flat_keys([non_standard_flat, TRP_SPECIFIC]),
            [TRP_SPECIFIC],
        )

    def test_a_value_that_is_not_a_key_is_returned_untouched(self):
        """Whatever put it there meant something this does not understand."""
        self.assertEqual(
            without_redundant_flat_keys(["not-a-key", TRP_FLAT, TRP_SPECIFIC]),
            ["not-a-key", TRP_SPECIFIC],
        )

    def test_the_order_of_the_values_is_preserved(self):
        self.assertEqual(
            without_redundant_flat_keys([MENTHOL_WRONG_HIT, MENTHOL_SPECIFIC]),
            [MENTHOL_WRONG_HIT, MENTHOL_SPECIFIC],
        )


class RDKitStageTestCase(unittest.TestCase):
    """Both RDKit stages, in both orders the two keys can arrive in.

    The flat key is what these stages produced 363 of 419 times: `_parse_mol`
    hashes the first SMILES it can parse, and a source's stereochemistry-free
    drawing sorts ahead of the specific one often enough.
    """

    def setUp(self):
        self.stages = (
            RDKitPreConsensusTransformer(),
            RDKitPostConsensusTransformer(),
        )

    def test_the_flat_key_is_not_added_to_a_record_that_states_the_specific_one(self):
        for stage in self.stages:
            with self.subTest(stage=stage.name):
                flow = _flow(
                    _smiles_property([TRP_FLAT_SMILES]) | _key_property([TRP_SPECIFIC])
                )
                self.assertEqual(_keys(_applied(stage, flow)), [TRP_SPECIFIC])

    def test_a_specific_key_withdraws_the_flat_key_already_there(self):
        """The other order.  It does not arise in the 2026-08-12 build -- 426 of
        427 flat keys were added after the specific one and none before -- and
        leaving it out would make the rule correct only for as long as
        `DEFAULT_TRANSFORMERS` keeps its current order."""
        for stage in self.stages:
            with self.subTest(stage=stage.name):
                flow = _flow(
                    _smiles_property([TRP_SPECIFIC_SMILES]) | _key_property([TRP_FLAT])
                )
                self.assertEqual(_keys(_applied(stage, flow)), [TRP_SPECIFIC])

    def test_a_flat_key_is_still_added_to_a_record_that_has_no_specific_one(self):
        """The stages are not being told to stop computing flat keys.  A
        substance registered without stereochemistry has one for its identity,
        and #223 is what happens to a flow with no identity at all."""
        for stage in self.stages:
            with self.subTest(stage=stage.name):
                flow = _flow(_smiles_property([TRP_FLAT_SMILES]))
                self.assertEqual(_keys(_applied(stage, flow)), [TRP_FLAT])

    def test_the_refused_key_is_not_reported_as_added(self):
        """A value that was not written is not a change to announce, and the
        stage's own provenance does not belong on a slot it did not touch."""
        flow = _flow(
            _smiles_property([TRP_FLAT_SMILES]) | _key_property([TRP_SPECIFIC])
        )
        for change in RDKitPreConsensusTransformer().transform([flow]):
            self.assertNotIn("inchi2d_key_string", change.comment)


class EnrichReferencesTestCase(unittest.TestCase):
    """The stage that supplies the flat key on its own for 59 of the 419.

    ChEBI, PubChem and Common Chemistry all write into one slot here, so the
    question is asked of the slot once they have all had their say.
    """

    def test_the_flat_key_is_dropped_from_the_merged_slot(self):
        semantic = _key_property([TRP_FLAT, TRP_SPECIFIC])
        EnrichReferencesTransformer()._drop_redundant_flat_inchikeys(semantic)
        self.assertEqual(_keys(semantic), [TRP_SPECIFIC])

    def test_the_sources_that_supplied_it_are_still_named(self):
        """Provenance is per property rather than per value, so the attestation
        of every source stays on the slot the flat key left."""
        semantic = _key_property([TRP_FLAT, TRP_SPECIFIC])
        EnrichReferencesTransformer()._drop_redundant_flat_inchikeys(semantic)
        self.assertEqual(
            semantic[CHEMROF_INCHI2D_KEY_STRING]["provenance"],
            {"prov:wasGeneratedBy": "enrich_references.chebi_semantic"},
        )


class NormalisationTestCase(unittest.TestCase):
    """The net for records assembled where no stage runs."""

    def test_a_record_reaching_the_export_with_both_keys_leaves_with_one(self):
        record = _flow_object(_key_property([TRP_FLAT, TRP_SPECIFIC]))
        counts = normalise_records([record])
        self.assertEqual(_keys(record.properties), [TRP_SPECIFIC])
        self.assertEqual(counts["inchikeys_redundant_flat_dropped"], 1)

    def test_it_is_idempotent(self):
        """The export runs the normalisation on its own output."""
        record = _flow_object(_key_property([TRP_FLAT, TRP_SPECIFIC]))
        normalise_records([record])
        counts = normalise_records([record])
        self.assertEqual(_keys(record.properties), [TRP_SPECIFIC])
        self.assertEqual(counts["inchikeys_redundant_flat_dropped"], 0)

    def test_the_acceptance_measure_reads_the_record_as_published(self):
        self.assertEqual(
            redundant_flat_inchikey_slots(_key_property([TRP_FLAT, TRP_SPECIFIC])), 1
        )
        self.assertEqual(
            redundant_flat_inchikey_slots(_key_property([TRP_SPECIFIC])), 0
        )
        self.assertEqual(
            redundant_flat_inchikey_slots(
                _key_property([MENTHOL_SPECIFIC, MENTHOL_WRONG_HIT])
            ),
            0,
        )


if __name__ == "__main__":
    unittest.main()
