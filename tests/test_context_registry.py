"""Context model invariants and IRI resolution.

Guards the contract that the context model is a shared definition, and the
specific defect that motivated ``domain.context_registry``: contexts were being
rebuilt by zipping ``Context.to_list()`` output positionally against a fixed key
tuple, which mis-assigned fields on every merge-created flow.
"""

import itertools
import unittest
from typing import ClassVar

import orjson

from brightway_flows.domain.context import (
    Context,
    Dimension,
    Geography,
    IndoorAirClass,
    LandUseClass,
    Media,
    PopulationDensity,
    ProhibitedContextCombinationError,
    VerticalStrata,
    WaterBody,
)
from brightway_flows.domain.context_registry import (
    CONTEXT_FIELDS,
    CONTEXTS_FILEPATH,
    UnknownContextIRIError,
    build_context_lookup,
    context_dict_for_iri,
    context_for_iri,
    context_to_dict,
)


def _all_valid_contexts() -> list[Context]:
    out = []
    none = [None]
    for combo in itertools.product(
        list(Dimension),
        list(Media) + none,
        list(VerticalStrata) + none,
        list(Geography) + none,
        list(WaterBody) + none,
        list(PopulationDensity) + none,
        list(IndoorAirClass) + none,
        list(LandUseClass) + none,
    ):
        try:
            out.append(
                Context(
                    dimension=combo[0],
                    media=combo[1],
                    strata=combo[2],
                    geography=combo[3],
                    water_body=combo[4],
                    population_density=combo[5],
                    indoor=combo[6],
                    land_use=combo[7],
                )
            )
        except ProhibitedContextCombinationError:
            pass
    return out


class ContextRoundTripTestCase(unittest.TestCase):
    def test_to_list_from_list_is_lossless_for_every_valid_context(self):
        """from_list must invert to_list exactly, with no collisions.

        If two distinct contexts serialised to the same list, from_list would
        silently return the wrong one.
        """
        contexts = _all_valid_contexts()
        self.assertGreater(len(contexts), 0)

        keys = [tuple(c.to_list()) for c in contexts]
        self.assertEqual(
            len(set(keys)),
            len(contexts),
            "to_list() is not injective — some contexts share a serialisation",
        )

        for context in contexts:
            with self.subTest(context=context):
                self.assertEqual(Context.from_list(context.to_list()), context)

    def test_from_list_rejects_unknown_values(self):
        with self.assertRaises(ValueError):
            Context.from_list(["Environmental", "Water", "Not A Real Water Body"])

    def test_to_list_omits_unknown_but_to_dict_keeps_it(self):
        """The exact asymmetry that made string round-tripping lossy.

        ``water_body="Unknown"`` disappears from to_list(), so a positional
        parse of that list cannot recover it — but the dict form must keep it.
        """
        context = Context(
            dimension=Dimension.ENVIRONMENTAL,
            media=Media.WATER,
            water_body=WaterBody.UNKNOWN,
        )
        self.assertEqual(context.to_list(), ["Environmental", "Water"])
        self.assertEqual(
            context_to_dict(context),
            {"dimension": "Environmental", "media": "Water", "water_body": "Unknown"},
        )


class ContextRegistryTestCase(unittest.TestCase):
    def test_every_vocabulary_row_is_a_valid_context(self):
        lookup = build_context_lookup()
        self.assertGreater(len(lookup), 0)
        for iri, context in lookup.items():
            with self.subTest(iri=iri):
                self.assertIsInstance(context, Context)

    def test_registry_matches_vocabulary_file_exactly(self):
        """context_dict_for_iri must reproduce the vocabulary row verbatim.

        Includes key order, so resolving via the registry does not reorder keys
        in existing output.
        """
        rows = orjson.loads(CONTEXTS_FILEPATH.read_bytes())
        for row in rows:
            iri = row["context_iri"]
            expected = {
                k: row[k] for k in CONTEXT_FIELDS if row.get(k) not in (None, "", [])
            }
            with self.subTest(iri=iri):
                resolved = context_dict_for_iri(iri)
                self.assertEqual(resolved, expected)
                self.assertEqual(list(resolved), list(expected))

    def test_unknown_iri_raises(self):
        with self.assertRaises(UnknownContextIRIError):
            context_for_iri("https://vocab.brightway.one/flow-contexts/does-not-exist")

    def test_context_manual_mapping_agrees_with_vocabulary(self):
        """The transformer's mapping file must not drift from the vocabulary.

        ``context-manual-mapping.json`` carries its own copy of the valid
        combinations; every IRI it references must resolve, and the values must
        match, or the two files describe different contexts.
        """
        from brightway_flows.context_mapping import MANUAL_MAPPING_FILEPATH

        payload = orjson.loads(MANUAL_MAPPING_FILEPATH.read_bytes())
        for row in payload.get("allowed_context_combinations", []):
            iri = row["context_iri"]
            expected = {
                k: v
                for k, v in row.items()
                if k != "context_iri" and v not in (None, "", [])
            }
            with self.subTest(iri=iri):
                self.assertEqual(context_dict_for_iri(iri), expected)

        for row in payload.get("default_context_mappings", []):
            iri = row.get("context_iri")
            if isinstance(iri, str) and iri:
                with self.subTest(iri=iri, source=row.get("source")):
                    context_for_iri(iri)


class MergeCreatedFlowContextTestCase(unittest.TestCase):
    """Regression tests for the contexts corrupted by positional parsing.

    Each IRI below produced a wrong ``context`` dict in a real merge run: the
    value belonging to ``water_body`` or ``geography`` landed in ``strata``, and
    ``"Unknown"`` values were dropped entirely.
    """

    CORRUPTED_BEFORE_FIX: ClassVar[dict[str, tuple[str, str]]] = {
        # iri suffix: the field the value actually belongs to
        "envi-wate-suwa": ("water_body", "Surface water"),
        "envi-wate-unaq": ("water_body", "Unconfined aquifer"),
        "envi-wate-ocea": ("water_body", "Ocean"),
        "envi-grou-silv": ("geography", "Silvicultural"),
        "envi-grou-agri": ("geography", "Agricultural"),
        "envi-grou-unkn": ("geography", "Unknown"),
        "envi-wate-unkn": ("water_body", "Unknown"),
    }
    PREFIX = "https://vocab.brightway.one/flow-contexts/"

    def test_values_land_in_the_correct_field(self):
        for suffix, (field, value) in self.CORRUPTED_BEFORE_FIX.items():
            with self.subTest(iri=suffix):
                resolved = context_dict_for_iri(f"{self.PREFIX}{suffix}")
                self.assertEqual(
                    resolved.get(field),
                    value,
                    f"{field} should be {value!r}, got {resolved!r}",
                )
                self.assertNotIn(
                    "strata",
                    resolved,
                    f"{suffix} must not carry a vertical strata: {resolved!r}",
                )

    def test_air_ground_level_retains_population_density(self):
        """envi-air-grle-unkn lost population_density entirely before the fix."""
        resolved = context_dict_for_iri(f"{self.PREFIX}envi-air-grle-unkn")
        self.assertEqual(resolved.get("strata"), "Ground level")
        self.assertEqual(resolved.get("population_density"), "Unknown")

    def test_every_vocabulary_context_survives_a_string_round_trip(self):
        """The corrupted rows failed exactly here.

        Their ``context`` dicts could not be constructed as a Context at all, so
        no round trip was possible.  Every registered context must serialise to
        strings and back without loss.
        """
        for iri, context in build_context_lookup().items():
            with self.subTest(iri=iri):
                self.assertEqual(Context.from_list(context.to_list()), context)
                self.assertEqual(context_to_dict(context), context_dict_for_iri(iri))


if __name__ == "__main__":
    unittest.main()
