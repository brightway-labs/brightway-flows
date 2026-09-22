"""The score artifact is refused unless it says what it claims to.

It is the one file this package reads that it did not write: brightway writes
it, under a Python this package is not installed in.  So the loader is the
whole defence, and each of these is a way an exporter could be wrong that the
comparison would otherwise carry into a report as a finding about the flow
list:

* a factor the scores did not use -- the recompute check;
* an inventory line or factor naming a flow the file does not describe;
* a score under a category the file does not describe, or one missing;
* a repeated flow, category, factor or unit process, which a dict-keyed
  format would have collapsed silently;
* a key the records do not declare, which the schema is closed against;
* a version this reader does not read.

And one way round: a valid document round-trips through the records and
back to the same bytes, so a fixture cut from a real export can be written
by the same code that reads it.
"""

from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path
from typing import Any

import orjson
from jsonschema import Draft202012Validator

from brightway_flows.domain.lcia.unit_process_scores import (
    ARTIFACT_SCHEMA_VERSION,
    ArtifactCategory,
    ArtifactFactor,
    ArtifactFlow,
    ArtifactRelease,
    InventoryLine,
    ScoreArtifact,
    ScoreArtifactError,
    UnitProcess,
    load_score_artifact,
    recompute,
    validate,
    write_score_artifact,
)
from brightway_flows.domain.schema import unit_process_scores_schema

CLIMATE = "EF v3.0|climate change|global warming potential (GWP100)"
FOSSILS = "EF v3.0|energy resources: non-renewable|abiotic depletion potential (ADP): fossil fuels"
CO2 = "349b29d1-3e58-4c66-98b9-9d1a076efd2e"
COAL = "3ab5bdb9-47ac-42b8-8d4f-b1a1bd3d70d6"
URANIUM = "24dea9a2-5f3c-4c94-9b6c-40e0c8d6b4b6"


def sample() -> ScoreArtifact:
    """Two unit processes, two categories, three flows, and scores that add up."""
    return ScoreArtifact(
        schema_version=ARTIFACT_SCHEMA_VERSION,
        release=ArtifactRelease(
            list_name="ecoinvent",
            list_version="3.8",
            system_model="apos",
            brightway_project="ecoinvent-3.8-apos",
            brightway_database="ecoinvent-3.8-apos",
            method_family="EF v3.0",
            generator={"bw2data": "4.5", "bw2calc": "2.1"},
            created_at="2026-08-25T10:00:00+00:00",
            sample_size=2,
            sample_seed=79,
        ),
        categories=[
            ArtifactCategory(
                key=CLIMATE,
                method_family="EF v3.0",
                category="climate change",
                indicator="global warming potential (GWP100)",
                unit="kg CO2-Eq",
            ),
            ArtifactCategory(
                key=FOSSILS,
                method_family="EF v3.0",
                category="energy resources: non-renewable",
                indicator="abiotic depletion potential (ADP): fossil fuels",
                unit="MJ, net calorific value",
            ),
        ],
        flows=[
            ArtifactFlow(CO2, "Carbon dioxide, fossil", "kilogram", ["air", "unspecified"], "124-38-9"),
            ArtifactFlow(COAL, "Coal, hard, unspecified, in ground", "kilogram", ["natural resource", "in ground"]),
            ArtifactFlow(URANIUM, "Uranium, in ground", "kilogram", ["natural resource", "in ground"], "7440-61-1"),
        ],
        factors=[
            ArtifactFactor(CLIMATE, CO2, 1.0),
            ArtifactFactor(FOSSILS, COAL, 18.0),
            ArtifactFactor(FOSSILS, URANIUM, 560000.0),
        ],
        unit_processes=[
            UnitProcess(
                activity_code="b09e51ef9d976bc64905c74fd99842fc",
                activity_uuid="035af6a2-9575-4ef8-825b-e056b37fc4b9",
                name="electricity production, wind, >3MW turbine, onshore",
                reference_product="electricity, high voltage",
                product_amount=1.0,
                product_unit="kilowatt hour",
                geography="SE",
                classifications={"ISIC rev.4 ecoinvent": "3510:Electric power generation"},
                inventory=[
                    InventoryLine(CO2, 0.0276),
                    InventoryLine(COAL, 0.0059),
                    InventoryLine(URANIUM, 6.0e-8),
                ],
                scores={CLIMATE: 0.0276, FOSSILS: 0.0059 * 18.0 + 6.0e-8 * 560000.0},
            ),
            UnitProcess(
                activity_code="0f1c2d3e4a5b6c7d8e9f0a1b2c3d4e5f",
                activity_uuid="5c3d0a1e-1111-4d9e-8f6a-2b2b2b2b2b2b",
                name="hard coal mine operation",
                reference_product="hard coal",
                product_amount=1.0,
                product_unit="kilogram",
                geography="CN",
                classifications={},
                inventory=[InventoryLine(COAL, 1.05), InventoryLine(CO2, 0.2)],
                scores={CLIMATE: 0.2, FOSSILS: 18.9},
            ),
        ],
    )


class RecordTestCase(unittest.TestCase):
    def test_a_valid_artifact_validates(self):
        validate(sample())

    def test_the_document_conforms_to_the_generated_schema(self):
        Draft202012Validator(unit_process_scores_schema()).validate(sample().to_dict())

    def test_round_trip(self):
        artifact = sample()
        self.assertEqual(ScoreArtifact.from_dict(artifact.to_dict()), artifact)

    def test_the_indexes_agree_with_the_lists(self):
        artifact = sample()
        self.assertEqual(artifact.factor_index()[(FOSSILS, COAL)], 18.0)
        self.assertEqual(set(artifact.factors_by_category()), {CLIMATE, FOSSILS})
        self.assertEqual(artifact.factors_by_category()[CLIMATE], {CO2: 1.0})
        self.assertEqual(artifact.release.key, "ecoinvent-3.8-apos")

    def test_a_wrong_type_names_where(self):
        payload = sample().to_dict()
        payload["unit_processes"][0]["inventory"][1]["amount"] = "a lot"
        with self.assertRaises(ScoreArtifactError) as caught:
            ScoreArtifact.from_dict(payload)
        self.assertIn("unit_processes.0.inventory.1.amount", str(caught.exception))


class RecomputeTestCase(unittest.TestCase):
    """The factors have to be the ones the scores used."""

    def test_a_score_the_factors_do_not_reproduce_is_refused(self):
        artifact = sample()
        artifact.unit_processes[0].scores[FOSSILS] *= 1.01
        with self.assertRaises(ScoreArtifactError) as caught:
            validate(artifact)
        self.assertIn("b09e51ef9d976bc64905c74fd99842fc", str(caught.exception))
        self.assertIn(FOSSILS, str(caught.exception))

    def test_summation_order_is_within_tolerance(self):
        process = sample().unit_processes[0]
        stated = process.scores[FOSSILS] * (1 + 1e-9)
        recompute(process, FOSSILS, {COAL: 18.0, URANIUM: 560000.0}, stated=stated)

    def test_a_flow_without_a_factor_contributes_nothing(self):
        """Absence is a zero factor here; the comparison reports it separately."""
        process = sample().unit_processes[0]
        self.assertEqual(recompute(process, CLIMATE, {CO2: 1.0}, stated=0.0276), 0.0276)

    def test_a_score_near_zero_is_held_to_what_cancelled(self):
        process = UnitProcess(
            "a", "a", "n", "p", 1.0, "kg", "GLO", {},
            inventory=[InventoryLine(CO2, 1.0), InventoryLine(COAL, -1.0)],
            scores={CLIMATE: 0.0},
        )
        recompute(process, CLIMATE, {CO2: 1.0, COAL: 1.0}, stated=1e-9)
        with self.assertRaises(ScoreArtifactError):
            recompute(process, CLIMATE, {CO2: 1.0, COAL: 1.0}, stated=1e-3)


class ReferentialTestCase(unittest.TestCase):
    def _refused(self, mutate, *, saying: str) -> None:
        artifact = sample()
        mutate(artifact)
        with self.assertRaises(ScoreArtifactError) as caught:
            validate(artifact)
        self.assertIn(saying, str(caught.exception))

    def test_a_factor_on_an_unknown_flow(self):
        self._refused(
            lambda a: a.factors.append(ArtifactFactor(CLIMATE, "nobody", 1.0)),
            saying="factors[" + CLIMATE + "/nobody]",
        )

    def test_a_factor_under_an_unknown_category(self):
        self._refused(
            lambda a: a.factors.append(ArtifactFactor("EF v3.0|x|y", CO2, 1.0)),
            saying="names a category not in categories",
        )

    def test_an_inventory_line_on_an_unknown_flow(self):
        self._refused(
            lambda a: a.unit_processes[1].inventory.append(InventoryLine("nobody", 1.0)),
            saying="inventory[nobody]",
        )

    def test_a_score_under_an_unknown_category(self):
        self._refused(
            lambda a: a.unit_processes[1].scores.update({"EF v3.0|x|y": 0.0}),
            saying="unknown 'EF v3.0|x|y'",
        )

    def test_a_missing_score(self):
        self._refused(
            lambda a: a.unit_processes[1].scores.pop(FOSSILS),
            saying="missing " + repr(FOSSILS),
        )

    def test_an_empty_inventory_is_data(self):
        """APOS by-products -- `hard coal ash` from concrete production -- carry
        every burden elsewhere: no inventory, scores of zero, and 5 of the
        first real 500-dataset export were one."""
        artifact = sample()
        artifact.unit_processes[1].inventory.clear()
        artifact.unit_processes[1].scores.update({CLIMATE: 0.0, FOSSILS: 0.0})
        validate(artifact)

    def test_a_zero_product_amount(self):
        def mutate(a):
            a.unit_processes[1] = UnitProcess(
                "z", "z", "n", "p", 0.0, "kg", "GLO", {},
                inventory=[InventoryLine(COAL, 1.0)],
                scores={CLIMATE: 0.0, FOSSILS: 18.0},
            )
        self._refused(mutate, saying="product_amount: zero")

    def test_a_non_finite_amount(self):
        self._refused(
            lambda a: a.factors.append(ArtifactFactor(CLIMATE, COAL, float("nan"))),
            saying="not a finite number",
        )

    def test_repeats_are_found_not_collapsed(self):
        self._refused(lambda a: a.flows.append(a.flows[0]), saying="flows: repeated")
        self._refused(lambda a: a.categories.append(a.categories[0]), saying="categories: repeated")
        self._refused(lambda a: a.factors.append(a.factors[0]), saying="factors: repeated")
        self._refused(
            lambda a: a.unit_processes.append(a.unit_processes[0]),
            saying="unit_processes: repeated",
        )
        self._refused(
            lambda a: a.unit_processes[1].inventory.append(InventoryLine(COAL, 0.0)),
            saying="inventory: repeated",
        )

    def test_nothing_scored(self):
        def mutate(a):
            a.categories.clear()
            a.factors.clear()
            for process in a.unit_processes:
                process.scores.clear()
        self._refused(mutate, saying="categories: empty")


class LoaderTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "unit-process-scores-ecoinvent-3.8-apos.json"

    def _write(self, payload: dict[str, Any]) -> Path:
        self.path.write_bytes(orjson.dumps(payload))
        return self.path

    def test_writes_and_reads_the_same_artifact(self):
        artifact = sample()
        write_score_artifact(artifact, self.path)
        self.assertEqual(load_score_artifact(self.path), artifact)

    def test_a_missing_file_names_the_exporter(self):
        with self.assertRaises(FileNotFoundError) as caught:
            load_score_artifact(self.path)
        self.assertIn("export_unit_process_scores.py", str(caught.exception))

    def test_not_json(self):
        self.path.write_bytes(b"{")
        with self.assertRaises(ScoreArtifactError) as caught:
            load_score_artifact(self.path)
        self.assertIn("not JSON", str(caught.exception))

    def test_another_version_is_refused(self):
        payload = sample().to_dict()
        payload["schema_version"] = ARTIFACT_SCHEMA_VERSION + 1
        with self.assertRaises(ScoreArtifactError) as caught:
            load_score_artifact(self._write(payload))
        self.assertIn("schema_version", str(caught.exception))

    def test_a_key_the_records_do_not_declare_is_refused(self):
        """Closed all the way down: an exporter that adds a key should hear so."""
        payload = sample().to_dict()
        payload["unit_processes"][0]["isic"] = "3510"
        with self.assertRaises(ScoreArtifactError) as caught:
            load_score_artifact(self._write(payload))
        self.assertIn("unit_processes/0", str(caught.exception))
        self.assertIn("isic", str(caught.exception))

    def test_a_number_spelled_as_a_string_is_refused(self):
        """Pydantic would read `"0.0059"` as 0.0059; the schema gate does not."""
        payload = sample().to_dict()
        payload["unit_processes"][0]["inventory"][1]["amount"] = "0.0059"
        with self.assertRaises(ScoreArtifactError) as caught:
            load_score_artifact(self._write(payload))
        self.assertIn("unit_processes/0/inventory/1/amount", str(caught.exception))

    def test_the_referential_checks_run_on_load(self):
        payload = sample().to_dict()
        payload["unit_processes"][0]["scores"][CLIMATE] = 1.0
        with self.assertRaises(ScoreArtifactError) as caught:
            load_score_artifact(self._write(payload))
        self.assertIn(self.path.name, str(caught.exception))
        self.assertIn("stated 1.0", str(caught.exception))

    def test_a_schema_variant_can_be_handed_in(self):
        payload = sample().to_dict()
        schema = copy.deepcopy(unit_process_scores_schema())
        schema["$defs"]["UnitProcess"]["additionalProperties"] = True
        payload["unit_processes"][0]["isic"] = "3510"
        self._write(payload)
        with self.assertRaises(ScoreArtifactError):
            load_score_artifact(self.path)
        load_score_artifact(self.path, schema=schema)
