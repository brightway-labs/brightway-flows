"""The register in `domain/rulings.py` and the `data/` directory agree.

Twenty-odd curated files were implemented twenty times -- eight packages, nine
filename suffixes, five loaders returning a record and fifteen returning a bag,
four caching conventions (#92). None of that was wrong exactly; it was that
nothing said what a curated file *was*, so nothing could say whether a new one
followed any convention at all.

The register says. These tests are what keeps it saying: a file added to `data/`
and not registered fails here, and so does a registered file that no longer
exists. Without that, a register is documentation, and documentation about
twenty files is wrong within a month.

Two rules about a loader are checked here, because both have a failure mode
nobody would see. A loader that takes an injectable `path` *and* is cached
serves the first test's fixture to every test after it. And a loader that hands
out a bag rather than records lets a misspelling at the reading end return
`None`, so the curator's ruling silently does not apply (#95).
"""

from __future__ import annotations

import ast
import dataclasses
import fnmatch
import importlib
import inspect
import unittest
from enum import Enum
from pathlib import Path
from typing import Any, get_args, get_origin, get_type_hints

from brightway_flows.domain.rulings import (
    CURATED_FILES,
    REFERENCE_DATA,
    RULINGS,
    VOCABULARIES,
)
from brightway_flows.filesystem import PACKAGE_DATA_DIR


def _shipped_files() -> set[str]:
    """Every data file the package ships, excluding the source manifests."""
    return {
        path.name
        for path in PACKAGE_DATA_DIR.iterdir()
        if path.is_file() and path.suffix in {".json", ".gz"}
    }


#: Every ruling's loader: the file it reads, the module it lives in, and its
#: name. Listed rather than discovered -- "a function in this module that reads
#: a file" is not decidable, and a detector that guessed would either miss the
#: case or fail on a helper -- and keyed by filename so that
#: `test_every_ruling_has_a_loader` can say which ruling is unaccounted for.
RULING_LOADERS = (
    ("elementary-flow-collision-decisions.json",
     "brightway_flows.pipeline.collision_decisions", "load_collision_rulings"),
    ("release-migration-rulings.json",
     "brightway_flows.releases.rulings", "load_release_migration_rulings"),
    ("lcia-factor-rulings.json",
     "brightway_flows.lcia.rulings", "load_factor_rulings"),
    ("lcia-factor-adoptions.json",
     "brightway_flows.lcia.adoptions", "load_factor_adoptions"),
    ("lcia-factor-adoptions-stepwise-2006.json",
     "brightway_flows.lcia.adoptions", "load_factor_adoptions"),
    ("lcia-misattributed-factors.json",
     "brightway_flows.lcia.misattributions", "load_misattributed_factors"),
    ("lcia-substance-decisions.json",
     "brightway_flows.lcia.substance_decisions", "load_substance_decisions"),
    ("lcia-rounded-printings.json",
     "brightway_flows.lcia.precision", "load_rounded_printings"),
    ("context-carry-rules.json",
     "brightway_flows.lcia.context_carry", "load_context_carry_rules"),
    ("particle-size-carry-rules.json",
     "brightway_flows.lcia.size_class_carry", "load_size_class_carry_rules"),
    ("lcia-factor-collision-rulings.json",
     "brightway_flows.lcia.collision_rulings", "load_collision_rulings"),
    ("preferred-label-decisions.json",
     "brightway_flows.domain.preferred_label_decisions",
     "load_preferred_label_decisions"),
    ("contested-cas-decisions.json",
     "brightway_flows.flow_layers.contested_cas", "load_decisions"),
    ("commonchemistry-structure-decisions.json",
     "brightway_flows.integrations.commonchemistry", "load_structure_decisions"),
    ("prepared-context-decisions.json",
     "brightway_flows.merge.prepared_context_decisions",
     "load_prepared_context_decision_index"),
    ("land-flow-groupings.json",
     "brightway_flows.merge.land_groupings", "load_land_flow_groupings"),
    ("source-name-places.json",
     "brightway_flows.flow_layers.synonyms", "load_place_vocabulary"),
    ("created-flow-unit-decisions.json",
     "brightway_flows.merge.unit_changes", "created_flow_unit_decisions"),
    ("published-units.json",
     "brightway_flows.merge.unit_changes", "published_units"),
    ("unit-change-allowlist.json",
     "brightway_flows.merge.unit_changes", "load_unit_change_allowlist"),
    ("flow-object-overrides.json",
     "brightway_flows.flow_layers.layering", "_load_overrides"),
    ("*-match-overrides.json",
     "brightway_flows.match_overrides", "load_match_overrides"),
    # Registered against `sources`, which resolves the path a manifest names;
    # the merge is where the file is read.
    ("ecoinvent-unmatched-pesticide-groupings.json",
     "brightway_flows.merge.additions", "_load_manual_additions"),
    ("correspondence-context-routing.json",
     "brightway_flows.correspondence_contexts", "permitted_coarsenings"),
    ("correspondence-context-routing.json",
     "brightway_flows.correspondence_contexts", "known_violations"),
    # Three arrays, three loaders: a compartment rule, a rule for one named
    # flow, and a rule selecting within a compartment by name prefix.
    ("context-manual-mapping.json", "brightway_flows.context_mapping", "_load_rows"),
    ("context-manual-mapping.json",
     "brightway_flows.context_mapping", "_load_flow_rows"),
    ("context-manual-mapping.json",
     "brightway_flows.context_mapping", "_load_name_rows"),
    ("altlabel-keep-list.json",
     "brightway_flows.transformers.strip_catalogue_altlabels", "load_keep_list"),
    ("colour-index-names.json",
     "brightway_flows.transformers.strip_product_families",
     "load_colour_index_names"),
    ("chebi-roles.json", "brightway_flows.flow_layers.roles", "load_allowed_roles"),
    ("curated-chebi-roles.json",
     "brightway_flows.flow_layers.roles", "load_curated_roles"),
    ("non-material-interventions.json",
     "brightway_flows.flow_layers.non_material", "_families"),
    ("retired-minted-flow-ids.json",
     "brightway_flows.pipeline.redirects", "load_retired_minted_flow_ids"),
)

#: The two rulings with no loader, and why. Both are randonneur payloads applied
#: to a source list before this project's records exist -- a fix names a field
#: on a vendor flow and says the vendor got it wrong, and an additional-flows
#: file is a list of vendor flows -- so what reads them is somebody else's
#: format, which rule 2 keeps as a dict and parses where it is read.
RULINGS_WITHOUT_A_LOADER = (
    "*-manual-fixes.json",
    "*additional-flows.json",
)

#: The vocabulary and reference-data loaders. They are not covered by the
#: returns-records rule -- that rule is about a curator's decision, and these
#: are tables the code looks things up in -- but the caching rule applies to
#: every loader of a curated file, so they are listed for it.
OTHER_LOADERS = (
    ("brightway_flows.domain.aggregate_measurements", "aggregate_measurements"),
    ("brightway_flows.domain.lcia.crosswalk", "impact_categories"),
    ("brightway_flows.domain.context_registry", "build_context_lookup"),
    ("brightway_flows.context_mapping", "consensus_context_strings"),
    ("brightway_flows.domain.materials", "material_concepts"),
    ("brightway_flows.domain.land_use_anchors", "anchor_snapshot"),
    ("brightway_flows.domain.particulate_size", "size_classes"),
    ("brightway_flows.domain.particulate_size",
     "particulate_class_by_source_flow"),
    ("brightway_flows.lcia.contradictions", "load_underlying_model_factors"),
    ("brightway_flows.integrations.ec_inventory", "load_ec_inventory"),
    ("brightway_flows.integrations.commonchemistry", "load_commonchemistry_index"),
)

#: Every loader, for the rule that applies to all of them.
EVERY_LOADER = tuple(
    (module, function) for _filename, module, function in RULING_LOADERS
) + OTHER_LOADERS


def _loader(module_name: str, function_name: str):
    return getattr(importlib.import_module(module_name), function_name)


class TheRegisterAndTheDirectoryAgreeTestCase(unittest.TestCase):
    def test_every_shipped_file_is_registered(self):
        """A new curated file is a decision about what kind of thing it is.

        This failing is the intended experience of adding one: say whether it is
        a ruling, a vocabulary or reference data, and what reads it.
        """
        registered = {entry.filename for entry in CURATED_FILES}
        patterns = {entry.filename for entry in CURATED_FILES if entry.is_pattern}
        unregistered = sorted(
            name
            for name in _shipped_files()
            if name not in registered
            and not any(fnmatch.fnmatch(name, pattern) for pattern in patterns)
        )
        self.assertEqual(
            unregistered, [],
            "these files in data/ are not in `domain.rulings`; add a row saying "
            "what each one decides and what reads it:\n  "
            + "\n  ".join(unregistered),
        )

    def test_every_registered_file_exists(self):
        missing = [
            entry.filename
            for entry in CURATED_FILES
            if not entry.is_pattern and not entry.path.exists()
        ]
        self.assertEqual(missing, [], f"registered but not shipped: {missing}")

    def test_every_pattern_matches_something(self):
        """A pattern with no files is a rule about nothing, and reads as though
        the per-list files are still there when they have been removed."""
        shipped = _shipped_files()
        for entry in CURATED_FILES:
            if not entry.is_pattern:
                continue
            with self.subTest(entry.filename):
                self.assertTrue(
                    any(fnmatch.fnmatch(name, entry.filename) for name in shipped),
                    f"no file in data/ matches {entry.filename}",
                )

    def test_no_file_is_registered_twice(self):
        names = [entry.filename for entry in CURATED_FILES]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        self.assertEqual(duplicates, [], f"registered more than once: {duplicates}")

    def test_the_three_kinds_do_not_overlap(self):
        for left, right, label in (
            (RULINGS, VOCABULARIES, "rulings/vocabularies"),
            (RULINGS, REFERENCE_DATA, "rulings/reference"),
            (VOCABULARIES, REFERENCE_DATA, "vocabularies/reference"),
        ):
            with self.subTest(label):
                shared = {e.filename for e in left} & {e.filename for e in right}
                self.assertEqual(shared, set())


class EveryRegisteredReaderExistsTestCase(unittest.TestCase):
    """`applied_by` is a claim about the code, so it is checked against it."""

    def test_the_module_named_by_each_row_imports(self):
        for entry in CURATED_FILES:
            with self.subTest(entry.filename):
                self.assertIsNotNone(importlib.import_module(entry.applied_by))

    def test_the_module_named_by_each_row_mentions_the_file(self):
        """Not that it *reads* it -- that cannot be checked statically -- but
        that the filename appears in the module claiming to apply it. A row
        naming the wrong module is worse than no row: it sends a reader
        somewhere the decision is not."""
        for entry in CURATED_FILES:
            if entry.is_pattern or entry.named_by_manifest:
                continue
            with self.subTest(entry.filename):
                source = Path(
                    importlib.import_module(entry.applied_by).__file__
                ).read_text()
                self.assertIn(entry.filename, source)

    def test_a_manifest_named_file_is_named_by_a_manifest(self):
        """The other half of the same claim. These three are reached through
        `data/sources/`, which is why no module mentions them -- adding a list's
        curated input is a manifest edit, not a Python change. If that stopped
        being true the row would be silently unverified."""
        manifests = "\n".join(
            path.read_text() for path in (PACKAGE_DATA_DIR / "sources").glob("*.json")
        )
        for entry in CURATED_FILES:
            if not entry.named_by_manifest:
                continue
            with self.subTest(entry.filename):
                # The correspondence tables are named without their suffix.
                stem = entry.filename.removesuffix(".json")
                self.assertIn(stem, manifests)


class TheCachingRuleHoldsTestCase(unittest.TestCase):
    """A cached loader must not take an injectable path.

    The rule already worked, by accident, everywhere anyone thought about it:
    the uncached loaders are the ones a test can point at a fixture. A loader
    that is both cached and path-taking serves the first caller's file to every
    caller after it, and a test suite is exactly where that happens.
    """

    def test_a_cached_loader_takes_no_path(self):
        offenders = []
        for module_name, function_name in EVERY_LOADER:
            function = _loader(module_name, function_name)
            cached = hasattr(function, "cache_clear")
            takes_path = "path" in inspect.signature(function).parameters
            if cached and takes_path:
                offenders.append(f"{module_name}.{function_name}")
        self.assertEqual(
            offenders, [],
            "cached and path-taking, so a test's fixture would be served to "
            "every later caller:\n  " + "\n  ".join(offenders),
        )

    def test_a_loader_that_takes_nothing_is_cached(self):
        """The other half. Re-parsing a curated file on every call is what #296
        was about; a loader with a fixed path has no reason not to be cached.

        A loader that takes *any* argument is left alone. A path makes the cache
        wrong, and any other argument -- the list being merged, say -- makes it
        keyed, so whether to cache is then a question about how often the answer
        is asked for rather than about correctness."""
        offenders = []
        for module_name, function_name in EVERY_LOADER:
            function = _loader(module_name, function_name)
            cached = hasattr(function, "cache_clear")
            takes_anything = bool(inspect.signature(function).parameters)
            if not cached and not takes_anything:
                offenders.append(f"{module_name}.{function_name}")
        self.assertEqual(
            offenders, [],
            "reads a fixed path on every call and is not cached:\n  "
            + "\n  ".join(offenders),
        )


class EveryRulingLoaderHandsOutRecordsTestCase(unittest.TestCase):
    """A ruling's loader hands out records, or the set it is a membership test
    for. Never a bag.

    #92 counted fifteen loaders returning a bag against five returning a
    record, and the register stated the rule without anything checking it. What
    the rule is *about* is a decision with fields: `contested_cas.load_decisions`
    handed out a `dict[str, Any]`, so `ruling["decison"]` was `None` and the
    ruling silently did not apply -- and a curator's ruling that looks applied
    and is not is the failure every decisions file here is written to avoid.

    A set is not that failure and is admitted. `altlabel-keep-list.json` is a
    list of labels a curator has ruled are names, and the only question asked of
    it is whether a label is one of them; wrapping each in a record would buy
    nothing and make the membership test worse. The distinction is *what the
    reading end asks*: a field, or membership.

    Only the return type is read, and not the fields of the records in it. A
    record may carry a bag -- `ContestedCas.evidence` is one, holding whatever
    the signal that decided had to say -- and that is a declared field whose
    contents are the point, which is what rule 3 says an `extra` bag is for.
    """

    #: What a loader may hand out that is not a record: the scalars a set or a
    #: key is made of.
    SCALARS = (str, int, float, bool, type(None))

    def _is_record(self, annotation: object) -> bool:
        return dataclasses.is_dataclass(annotation) or (
            isinstance(annotation, type) and issubclass(annotation, Enum)
        )

    def _bag_reasons(self, annotation: object, *, depth: int = 0) -> list[str]:
        """Why *annotation* is a bag, or `[]` if it is not."""
        if annotation is Any:
            return ["`Any`, which is a field nothing declares"]
        origin = get_origin(annotation)
        if depth and (annotation is dict or origin is dict):
            return ["a `dict` inside what it hands out, whose keys nothing declares"]
        arguments = [a for a in get_args(annotation) if a is not Ellipsis]
        if arguments:
            return [
                reason
                for argument in arguments
                for reason in self._bag_reasons(argument, depth=depth + 1)
            ]
        if origin is not None or annotation in self.SCALARS or self._is_record(annotation):
            return []
        return [f"`{getattr(annotation, '__name__', annotation)}`, which is neither a "
                f"scalar nor a record"]

    def test_no_ruling_loader_hands_out_a_bag(self):
        offenders = []
        for filename, module_name, function_name in RULING_LOADERS:
            function = _loader(module_name, function_name)
            returns = get_type_hints(function).get("return")
            if returns is None:
                # Saying nothing is the same as saying `Any`, and reads as
                # though nobody had to decide.
                offenders.append(
                    f"{module_name}.{function_name} ({filename}) does not say "
                    f"what it returns"
                )
                continue
            reasons = self._bag_reasons(returns)
            if reasons:
                offenders.append(
                    f"{module_name}.{function_name} ({filename}) returns "
                    + "; ".join(sorted(set(reasons)))
                )
        self.assertEqual(
            offenders, [],
            "a ruling's loader hands out records, or the set it is a membership "
            "test for:\n  " + "\n  ".join(offenders),
        )

    def test_every_ruling_has_a_loader(self):
        """Otherwise a ruling added tomorrow is exempt from the rule by being
        forgotten, which is how the last set of conventions came to hold on one
        side of the layering and not the other."""
        listed = {filename for filename, _module, _function in RULING_LOADERS}
        unaccounted = sorted(
            entry.filename
            for entry in RULINGS
            if entry.filename not in listed
            and not any(
                fnmatch.fnmatch(entry.filename, pattern)
                for pattern in RULINGS_WITHOUT_A_LOADER
            )
        )
        self.assertEqual(
            unaccounted, [],
            "these rulings have no loader listed in `RULING_LOADERS`; add the "
            "function that reads each one, or say in `RULINGS_WITHOUT_A_LOADER` "
            "why it has none:\n  " + "\n  ".join(unaccounted),
        )

    def test_every_listed_loader_reads_a_registered_ruling(self):
        """The other direction: a loader listed for a file the register does not
        call a ruling is being checked against the wrong rule."""
        registered = {entry.filename for entry in RULINGS}
        for filename, module_name, function_name in RULING_LOADERS:
            with self.subTest(f"{module_name}.{function_name}"):
                self.assertIn(filename, registered)


class TheConventionsPageStatesTheseNumbersTestCase(unittest.TestCase):
    """`conventions.md` says how many loaders answer membership and how many
    hand out records. Those are counts of the register above, and a count in
    prose drifts the moment a ruling is added.
    """

    PAGE = (
        Path(__file__).resolve().parent.parent / "docs" / "reference" / "conventions.md"
    )

    #: How the page writes a number, because prose spells them.
    WORDS = {
        1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six",
        7: "seven", 8: "eight", 9: "nine", 10: "ten", 11: "eleven",
        12: "twelve", 13: "thirteen", 14: "fourteen", 15: "fifteen",
        16: "sixteen", 17: "seventeen", 18: "eighteen", 19: "nineteen",
        20: "twenty", 21: "twenty-one", 22: "twenty-two", 23: "twenty-three",
        24: "twenty-four", 25: "twenty-five", 26: "twenty-six",
        27: "twenty-seven", 28: "twenty-eight", 29: "twenty-nine",
        30: "thirty", 31: "thirty-one", 32: "thirty-two", 33: "thirty-three",
        34: "thirty-four", 35: "thirty-five",
    }

    def _returns_a_set(self, module_name: str, function_name: str) -> bool:
        returns = get_type_hints(_loader(module_name, function_name)).get("return")
        return get_origin(returns) in (set, frozenset)

    def test_the_page_states_the_split_the_register_has(self):
        answering_membership = sum(
            1 for _filename, module, function in RULING_LOADERS
            if self._returns_a_set(module, function)
        )
        handing_out_records = len(RULING_LOADERS) - answering_membership
        # Wrapped as the page wraps it, so match on the words rather than the
        # lines.
        page = " ".join(self.PAGE.read_text().split())
        for fragment in (
            f"{self.WORDS[answering_membership].capitalize()} of the "
            f"{self.WORDS[len(RULING_LOADERS)]} loaders answer membership",
            f"the other {self.WORDS[handing_out_records]} hand out records",
        ):
            with self.subTest(fragment):
                self.assertIn(fragment, page)


class TheBareSchemaVersionNameIsTakenTestCase(unittest.TestCase):
    """`SCHEMA_VERSION` means the version of the list this project publishes.

    Three modules defined it and meant three unrelated things: the published
    schema, and the on-disk format of two different ruling files (#98). Two
    others had already been renamed for exactly this reason -- `store` and
    `review_tables` -- so the fix existed in the tree twice and had not been
    applied to the rest.

    A ruling file's own format version is `DECISIONS_SCHEMA_VERSION`, spelled
    per module, because the formats version independently.
    """

    #: The one module allowed the bare name, and what it means there.
    PUBLISHED = "brightway_flows/domain/schema.py"

    def _module_level_constants(self, name: str) -> list[str]:
        """Every source file assigning *name* at module level, as a path."""
        source_root = Path(__file__).parent.parent / "src"
        found = []
        for path in sorted(source_root.rglob("*.py")):
            tree = ast.parse(path.read_text())
            for node in tree.body:
                targets = (
                    node.targets if isinstance(node, ast.Assign)
                    else [node.target] if isinstance(node, ast.AnnAssign)
                    else []
                )
                if any(
                    isinstance(target, ast.Name) and target.id == name
                    for target in targets
                ):
                    found.append(str(path.relative_to(source_root)))
        return found

    def test_only_the_published_schema_claims_it(self):
        self.assertEqual(
            self._module_level_constants("SCHEMA_VERSION"), [self.PUBLISHED],
            "a second SCHEMA_VERSION means grepping the name that answers "
            "'what version does the list publish?' returns more than one "
            "answer; a version of something else names what it versions",
        )

    def test_a_ruling_file_spells_its_own_version(self):
        """The other half: the qualified name is in use, not just permitted."""
        self.assertEqual(
            self._module_level_constants("DECISIONS_SCHEMA_VERSION"),
            [
                "brightway_flows/domain/land_flow_classes.py",
                "brightway_flows/domain/particulate_size.py",
                "brightway_flows/flow_layers/roles.py",
                "brightway_flows/merge/land_groupings.py",
                "brightway_flows/merge/prepared_context_decisions.py",
                "brightway_flows/pipeline/collision_decisions.py",
            ],
        )


if __name__ == "__main__":
    unittest.main()
