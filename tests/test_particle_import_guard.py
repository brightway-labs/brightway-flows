"""A particle row nobody has read stops the merge (`plans/particle-family.md` §3).

`Particulates, SPM` fell through to the label branch on the build of 2 September
2026, matched nothing, and minted a substance with no window and no factor; so
did Stepwise's `Particulates, < 10 um` and `(mobile)`, beside the PM10 the list
already published.  Nobody was told.  The land taxonomy refuses the same outcome
for its family -- a name in a compartment told apart by name that matches no
rule raises, and the merge stops (#52) -- and this is that refusal for
particles (#196).

What is pinned:

- **The prefix test is the tool's.**  A row is a particle row when its name
  begins with `particle` or `particulate`, which is how
  `tools/build_particulate_flow_classes.py` selects the rows it shows a curator,
  so what the tool would have listed as unplaced and what the merge refuses are
  one population.  `Soot` and `Zinc, fume or dust` are not in it.
- **A read row is placed by its window, as before.**  The guard runs only where
  the table has no row.
- **The lookup declines rather than raising.**  A question is not a build.
"""

import unittest

from brightway_flows.domain.particulate_size import (
    UnreadParticleRowError,
    names_a_particle_by_size,
    particulate_class_by_source_flow,
)
from brightway_flows.merge.contexts import ContextExpectations
from brightway_flows.merge.matching import resolve_flow_object
from brightway_flows.merge.report import UnmatchedReason
from brightway_flows.merge.state import MergeAccumulator, MergeIndexes, SourceRow
from brightway_flows.sources import resolve_source_list

STEPWISE = "stepwise-2006-1.09"


def _row(name, *, uuid="s-unread", cas=""):
    return SourceRow(
        uuid=uuid, name=name, synonyms=[], labels=[name],
        context=["Air", "(unspecified)"], context_iri="",
        context_normalized=(), unit="kg", unit_iri="", cas=cas, ec="",
    )


def _indexes(**label_index):
    return MergeIndexes(
        flow_objects_by_id={}, flow_object_label_by_id={},
        cas_index={}, ec_index={},
        label_index=dict(label_index), pref_label_index=dict(label_index),
        qualifier_index={},
        flow_objects_with_cas=set(),
        context_expectations=ContextExpectations(
            _by_source_context={}, _source_label="test"
        ),
        consensus_context_strings={},
        prepared_context_decisions={}, mapping_file=None,
        source=resolve_source_list(STEPWISE),
    )


class TheNameTestTestCase(unittest.TestCase):
    def test_the_size_cut_spellings_are_particle_rows(self):
        for name in (
            "Particulates, < 10 um",
            "Particulates, SPM",
            "Particulate Matter, > 2.5 um and < 10um",
            "particles (PM10)",
            "  PARTICULATES, unspecified",
        ):
            with self.subTest(name):
                self.assertTrue(names_a_particle_by_size(name))

    def test_composition_names_are_not(self):
        """The chemistry rules place these; they say what the particles are
        made of, not where the sample was cut."""
        for name in ("Soot", "Zinc, fume or dust", "Silicate particles", "Corn dust (biomass)", ""):
            with self.subTest(name):
                self.assertFalse(names_a_particle_by_size(name))


class TheMergeStopsTestCase(unittest.TestCase):
    def test_an_unread_particle_row_raises_and_names_itself(self):
        with self.assertRaises(UnreadParticleRowError) as caught:
            resolve_flow_object(
                row=_row("Particulates, foo"), indexes=_indexes(), accumulator=MergeAccumulator()
            )
        message = str(caught.exception)
        self.assertIn("'Particulates, foo'", message)
        self.assertIn("s-unread", message)
        self.assertIn(STEPWISE, message)
        self.assertIn("tools/build_particulate_flow_classes.py", message)

    def test_a_label_hit_does_not_rescue_it(self):
        """The label is not the row's to trust: that is how BAFU's coarse band
        reached PM10 (#153), and the guard runs before the label branch."""
        indexes = _indexes(**{"particulates, foo": {"fo-somewhere"}})
        with self.assertRaises(UnreadParticleRowError):
            resolve_flow_object(
                row=_row("Particulates, foo"), indexes=indexes, accumulator=MergeAccumulator()
            )

    def test_a_read_row_is_placed_by_its_window(self):
        """Stepwise's plain PM10 spelling, which minted a substance of its own
        until the list joined the table's sources."""
        rows = particulate_class_by_source_flow()
        (key,) = [k for k, v in rows.items() if k[0] == STEPWISE and v.source_name == "Particulates, < 10 um"]
        accumulator = MergeAccumulator()
        resolution = resolve_flow_object(
            row=_row("Particulates, < 10 um", uuid=key[1]),
            indexes=_indexes(),
            accumulator=accumulator,
        )
        # The window's object is not in this fixture's index, so the answer is
        # `create it`: recorded, and not an error.
        self.assertIsNone(resolution)
        self.assertEqual(len(accumulator.unmatched), 1)
        self.assertEqual(accumulator.unmatched[0].reason, UnmatchedReason.NO_FLOW_OBJECT_CANDIDATE)

    def test_a_row_that_is_not_a_particle_row_is_untouched(self):
        accumulator = MergeAccumulator()
        resolution = resolve_flow_object(
            row=_row("Soot"), indexes=_indexes(), accumulator=accumulator
        )
        self.assertIsNone(resolution)
        self.assertEqual(len(accumulator.unmatched), 1)


class EveryShippedParticleRowIsReadTestCase(unittest.TestCase):
    """The guard fires on nothing the registered lists ship today: every row the
    tool selects by the same prefix test has a reading.  Measured by the tool's
    own `unplaced: 0` on 2 September 2026, and held here so a new vendor row
    is met by a failing test before it is met by a failing build."""

    def test_the_table_reads_every_prefix_matching_row_of_every_source(self):
        import json
        from pathlib import Path

        from brightway_flows.sources import registered_source_list

        read = {(k[0], k[1]) for k in particulate_class_by_source_flow()}
        for key in (
            "EF-3.1", "ecoinvent-3.8", "ecoinvent-3.12", "bafu-2026-v1",
            "stepwise-2006-1.09", "agribalyse-3.2",
        ):
            source = registered_source_list(key)
            path = Path(source.flows_path)
            if not path.exists():  # pragma: no cover -- a machine without the extraction
                self.skipTest(f"{key} is not extracted here")
            for flow in json.loads(path.read_bytes()):
                if names_a_particle_by_size(flow["name"]):
                    with self.subTest(key, name=flow["name"]):
                        self.assertIn((source.source_label, flow["uuid"]), read)


if __name__ == "__main__":
    unittest.main()
