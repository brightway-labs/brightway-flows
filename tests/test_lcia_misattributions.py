"""A factor stated against the wrong substance moves, and only when it should.

#126: EF 3.1 gives 1,1,2-trichloroethane an ozone-depletion factor of 0.14 and
gives 1,1,1-trichloroethane -- the Montreal Protocol solvent the number describes
-- none at all.  `lcia.rulings` cannot express the correction, because a ruling
answers a queue item and nothing here is inconsistent as far as the pipeline can
see: EF states a number, both transcriptions agree, and no implementation states
the factor for the right substance, so no `publish` verdict could name one.

Both halves of the rule are tested, which is the part that matters.  A move that
relocates the factor is easy; what stops it growing into a rule that overrides the
method is the set of cases where it declines to fire -- the destination already
carrying the number, the source stating something the row never saw, and the
destination having no flow in the compartment the factor came from.
"""

from __future__ import annotations

import json
import unittest
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from brightway_flows.domain.lcia.crosswalk import ef_method
from brightway_flows.lcia.misattributions import (
    MOVED,
    MisattributedFactor,
    MisattributedFactorError,
    load_misattributed_factors,
    move_factors,
    stated_by_substance,
)

SOURCE = "fo-the-carcinogen"
DESTINATION = "fo-the-solvent"
SLUG = "ozone-depletion"

RURAL = "https://vocab.brightway.one/flow-contexts/envi-air-mest15me-ru10pesq"
URBAN = "https://vocab.brightway.one/flow-contexts/envi-air-grle-ur10pesq"
WATER = "https://vocab.brightway.one/flow-contexts/envi-wate-unkn"


@dataclass(frozen=True)
class FakeFactor:
    amount: float


@dataclass(frozen=True)
class FakeRow:
    """Enough of a `MatchedFactor` for the mover: a flow, a number, a derivation."""

    elementary_flow_uuid: str
    factor: FakeFactor
    derivation: str | None = None


def flows(**extra):
    """The two substances, one flow each in rural air, plus whatever a test adds."""
    base = {
        "carcinogen-rural": {
            "flow_object_id": SOURCE, "context_iri": RURAL, "deprecated": False,
        },
        "solvent-rural": {
            "flow_object_id": DESTINATION, "context_iri": RURAL, "deprecated": False,
        },
    }
    base.update(extra)
    return base


def move(**overrides):
    fields = {
        "category_slug": SLUG,
        "from_flow_object_id": SOURCE,
        "to_flow_object_id": DESTINATION,
        "stated_about_the_source": {"European Commission — JRC": (0.14,)},
        "stated_about_the_destination": {},
        "comment": "why",
    }
    fields.update(overrides)
    return MisattributedFactor(**fields)


def apply(rows, *, moves, flow_table, stated):
    return move_factors(
        rows,
        moves={m.key: m for m in moves},
        slug_of=lambda _row: SLUG,
        flows=flow_table,
        stated=stated,
    )


STATED_TODAY = {
    (SLUG, SOURCE): {"European Commission — JRC": (0.14,)},
}


class TheFactorMoves(unittest.TestCase):
    """The half the issue is about."""

    def test_the_factor_lands_on_the_other_substance(self):
        rows = [FakeRow("carcinogen-rural", FakeFactor(0.14), "sole")]
        out, counts = apply(
            rows, moves=[move()], flow_table=flows(), stated=STATED_TODAY
        )
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].elementary_flow_uuid, "solvent-rural")
        self.assertEqual(counts["moved"], 1)

    def test_the_amount_is_the_methods_own(self):
        # The whole argument for a move rather than an asserted number: what is
        # known is which substance the factor is about, not what it should be.
        rows = [FakeRow("carcinogen-rural", FakeFactor(0.14), "sole")]
        out, _ = apply(rows, moves=[move()], flow_table=flows(), stated=STATED_TODAY)
        self.assertEqual(out[0].factor.amount, 0.14)

    def test_a_moved_factor_says_it_was_moved(self):
        # Distinguishable from `sole`, which is nobody else having spoken, and
        # from `agreed`, which is the pipeline finding nothing to decide.
        rows = [FakeRow("carcinogen-rural", FakeFactor(0.14), "sole")]
        out, _ = apply(rows, moves=[move()], flow_table=flows(), stated=STATED_TODAY)
        self.assertEqual(out[0].derivation, MOVED)

    def test_the_source_substance_keeps_nothing(self):
        # The other half of #126's claim: the carcinogen must stop carrying it.
        rows = [FakeRow("carcinogen-rural", FakeFactor(0.14), "sole")]
        out, _ = apply(rows, moves=[move()], flow_table=flows(), stated=STATED_TODAY)
        self.assertEqual(
            [row.elementary_flow_uuid for row in out], ["solvent-rural"]
        )

    def test_it_lands_in_the_compartment_the_factor_came_from(self):
        # The bound on the rule.  Two compartments in, two out, each on its own
        # -- a move cannot pool a substance's factors and spread them.
        flow_table = flows(
            **{
                "carcinogen-urban": {
                    "flow_object_id": SOURCE, "context_iri": URBAN,
                    "deprecated": False,
                },
                "solvent-urban": {
                    "flow_object_id": DESTINATION, "context_iri": URBAN,
                    "deprecated": False,
                },
            }
        )
        rows = [
            FakeRow("carcinogen-rural", FakeFactor(0.14), "sole"),
            FakeRow("carcinogen-urban", FakeFactor(0.14), "sole"),
        ]
        out, counts = apply(
            rows, moves=[move()], flow_table=flow_table, stated=STATED_TODAY
        )
        self.assertEqual(
            sorted(row.elementary_flow_uuid for row in out),
            ["solvent-rural", "solvent-urban"],
        )
        self.assertEqual(counts["moved"], 2)

    def test_another_substances_factors_are_left_alone(self):
        # A row about one substance decides about that substance.
        flow_table = flows(
            **{
                "bystander": {
                    "flow_object_id": "fo-someone-else", "context_iri": RURAL,
                    "deprecated": False,
                }
            }
        )
        rows = [
            FakeRow("carcinogen-rural", FakeFactor(0.14), "sole"),
            FakeRow("bystander", FakeFactor(99.0), "sole"),
        ]
        out, _ = apply(
            rows, moves=[move()], flow_table=flow_table, stated=STATED_TODAY
        )
        bystander = [row for row in out if row.elementary_flow_uuid == "bystander"]
        self.assertEqual(len(bystander), 1)
        self.assertEqual(bystander[0].derivation, "sole")


class TheFactorStaysPut(unittest.TestCase):
    """The half that stops this becoming a rule that overrides the method."""

    def test_a_destination_that_already_states_it_is_left_alone(self):
        # EF fixing this at source undoes the move with nobody editing the file,
        # which is the whole point of recording both sides.  Moving it again
        # would have this project assert a duplicate.
        stated = dict(STATED_TODAY)
        stated[(SLUG, DESTINATION)] = {"European Commission — JRC": (0.14,)}
        rows = [FakeRow("carcinogen-rural", FakeFactor(0.14), "sole")]
        out, counts = apply(
            rows, moves=[move()], flow_table=flows(), stated=stated
        )
        self.assertEqual(out[0].elementary_flow_uuid, "carcinogen-rural")
        self.assertEqual(counts["not_about_this_build"], 1)
        self.assertNotIn("moved", counts)

    def test_a_source_stating_a_number_the_row_never_saw_is_left_alone(self):
        # EF restating the factor is EF saying something this row was not written
        # about.
        stated = {(SLUG, SOURCE): {"European Commission — JRC": (0.07,)}}
        rows = [FakeRow("carcinogen-rural", FakeFactor(0.07), "sole")]
        out, counts = apply(rows, moves=[move()], flow_table=flows(), stated=stated)
        self.assertEqual(out[0].elementary_flow_uuid, "carcinogen-rural")
        self.assertEqual(counts["not_about_this_build"], 1)

    def test_an_implementation_the_row_never_heard_from_is_left_alone(self):
        # A third implementation arriving changes what the question means.
        stated = {
            (SLUG, SOURCE): {
                "European Commission — JRC": (0.14,),
                "ecoinvent Centre": (0.14,),
            }
        }
        rows = [FakeRow("carcinogen-rural", FakeFactor(0.14), "sole")]
        out, counts = apply(rows, moves=[move()], flow_table=flows(), stated=stated)
        self.assertEqual(out[0].elementary_flow_uuid, "carcinogen-rural")
        self.assertEqual(counts["not_about_this_build"], 1)

    def test_a_source_that_has_gone_silent_is_left_alone(self):
        # EF withdrawing the factor leaves nothing to move, and a row that fired
        # anyway would be asserting a number nobody states.
        rows = [FakeRow("carcinogen-rural", FakeFactor(0.14), "sole")]
        out, counts = apply(rows, moves=[move()], flow_table=flows(), stated={})
        self.assertEqual(out[0].elementary_flow_uuid, "carcinogen-rural")
        self.assertEqual(counts["not_about_this_build"], 1)

    def test_a_factor_with_nowhere_to_land_is_dropped_and_counted(self):
        # The destination has no flow in the compartment the factor came from.
        # Publishing it against some other compartment would be the move
        # inventing coverage; leaving it would publish it against the substance
        # the row says it is not about.
        flow_table = {
            "carcinogen-water": {
                "flow_object_id": SOURCE, "context_iri": WATER, "deprecated": False,
            },
            "solvent-rural": {
                "flow_object_id": DESTINATION, "context_iri": RURAL,
                "deprecated": False,
            },
        }
        rows = [FakeRow("carcinogen-water", FakeFactor(0.14), "sole")]
        out, counts = apply(
            rows, moves=[move()], flow_table=flow_table, stated=STATED_TODAY
        )
        self.assertEqual(out, [])
        self.assertEqual(counts["no_flow_in_that_compartment"], 1)

    def test_a_deprecated_destination_flow_is_not_somewhere_to_publish(self):
        # A deprecated flow is a redirect, not a place a number can live.
        flow_table = flows(
            **{
                "solvent-rural-old": {
                    "flow_object_id": DESTINATION, "context_iri": RURAL,
                    "deprecated": True,
                }
            }
        )
        rows = [FakeRow("carcinogen-rural", FakeFactor(0.14), "sole")]
        out, _ = apply(
            rows, moves=[move()], flow_table=flow_table, stated=STATED_TODAY
        )
        self.assertEqual(out[0].elementary_flow_uuid, "solvent-rural")

    def test_no_moves_leaves_the_list_identical(self):
        rows = [FakeRow("carcinogen-rural", FakeFactor(0.14), "sole")]
        out, counts = apply(rows, moves=[], flow_table=flows(), stated=STATED_TODAY)
        self.assertEqual(out, rows)
        self.assertEqual(counts, {})


class TheFileIsRead(unittest.TestCase):
    """What the loader refuses, and why each refusal is worth having."""

    def write(self, payload):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "moves.json"
        path.write_text(json.dumps(payload))
        return path

    def row(self, **overrides):
        base = {
            "category_slug": SLUG,
            "from_flow_object_id": SOURCE,
            "to_flow_object_id": DESTINATION,
            "stated_about_the_source": {"European Commission — JRC": [0.14]},
            "stated_about_the_destination": {},
            "comment": "why",
        }
        base.update(overrides)
        return base

    def test_a_well_formed_file_loads(self):
        path = self.write(
            {"schema_version": 1, "method": "ef", "description": "d", "moves": [self.row()]}
        )
        loaded = load_misattributed_factors(path)
        self.assertEqual(list(loaded), [(SLUG, SOURCE)])
        self.assertEqual(
            loaded[(SLUG, SOURCE)].stated_about_the_source,
            {"European Commission — JRC": (0.14,)},
        )

    def test_an_empty_destination_is_allowed_and_is_the_point(self):
        # "No implementation states this factor for that substance" is the
        # destination's ordinary state and half of why the move is needed.  It
        # must not be confused with a row that says nothing about the side.
        path = self.write(
            {"schema_version": 1, "method": "ef", "description": "d", "moves": [self.row()]}
        )
        self.assertEqual(
            load_misattributed_factors(path)[(SLUG, SOURCE)]
            .stated_about_the_destination,
            {},
        )

    def test_a_row_with_no_comment_is_refused(self):
        path = self.write(
            {"schema_version": 1, "method": "ef", "description": "d",
             "moves": [self.row(comment="  ")]}
        )
        with self.assertRaises(MisattributedFactorError):
            load_misattributed_factors(path)

    def test_a_row_that_says_nothing_about_a_side_is_refused(self):
        # A row with no recorded state could never fail the guard, so it would be
        # a standing instruction rather than a claim about a published state.
        for field in ("stated_about_the_source", "stated_about_the_destination"):
            with self.subTest(field=field):
                payload = self.row()
                del payload[field]
                path = self.write(
                    {"schema_version": 1, "method": "ef", "description": "d", "moves": [payload]}
                )
                with self.assertRaises(MisattributedFactorError):
                    load_misattributed_factors(path)

    def test_a_row_moving_a_factor_to_itself_is_refused(self):
        path = self.write(
            {"schema_version": 1, "method": "ef", "description": "d",
             "moves": [self.row(to_flow_object_id=SOURCE)]}
        )
        with self.assertRaises(MisattributedFactorError):
            load_misattributed_factors(path)

    def test_two_rows_about_one_substance_and_category_are_refused(self):
        # One substance and category, one decision -- otherwise the last row read
        # wins, which is not a decision anybody made.
        path = self.write(
            {"schema_version": 1, "method": "ef", "description": "d",
             "moves": [self.row(), self.row(to_flow_object_id="fo-third")]}
        )
        with self.assertRaises(MisattributedFactorError):
            load_misattributed_factors(path)

    def test_a_wrong_schema_version_is_refused(self):
        path = self.write(
            {"schema_version": 99, "description": "d", "moves": [self.row()]}
        )
        with self.assertRaises(MisattributedFactorError):
            load_misattributed_factors(path)

    def test_a_missing_file_is_no_moves_rather_than_an_error(self):
        self.assertEqual(load_misattributed_factors(Path("/nowhere/at/all")), {})


#: The reference implementation of EF 3.1.  A record and not the string it
#: publishes under: `stated_by_substance` is given the implementations the run
#: holds, and keys its answer on the name each of them states.
JRC_IMPL = ef_method().reference


class TheStatedIndex(unittest.TestCase):
    """`stated_by_substance` is what the guard is asked about."""

    def test_it_groups_every_compartment_under_one_substance(self):
        # EF states 0.14 in five air compartments and the row records `[0.14]`,
        # not the number five -- so the index has to collapse them.
        matched = {
            JRC_IMPL: {
                ("carcinogen-rural", SLUG, ""): FakeRow(
                    "carcinogen-rural", FakeFactor(0.14)
                ),
                ("carcinogen-urban", SLUG, ""): FakeRow(
                    "carcinogen-urban", FakeFactor(0.14)
                ),
            }
        }
        flow_table = {
            "carcinogen-rural": {"flow_object_id": SOURCE},
            "carcinogen-urban": {"flow_object_id": SOURCE},
        }
        index = stated_by_substance(matched, flows=flow_table)
        self.assertEqual(set(index[(SLUG, SOURCE)][JRC_IMPL.name]), {0.14})

    def test_a_flow_with_no_substance_is_skipped(self):
        matched = {
            JRC_IMPL: {("orphan", SLUG, ""): FakeRow("orphan", FakeFactor(1.0))}
        }
        self.assertEqual(stated_by_substance(matched, flows={}), {})


class TheCuratedFileHoldsWhatIssue615Says(unittest.TestCase):
    """The shipped file, read as a person would check it."""

    @classmethod
    def setUpClass(cls):
        cls.moves = load_misattributed_factors()

    def test_it_carries_the_one_move_615_asks_for(self):
        self.assertEqual(len(self.moves), 1)
        move = next(iter(self.moves.values()))
        self.assertEqual(move.category_slug, "ozone-depletion")
        self.assertEqual(move.from_substance, "1,1,2-trichloroethane")
        self.assertEqual(move.to_substance, "1,1,1-Trichloroethane")

    def test_the_row_records_the_number_it_is_about(self):
        move = next(iter(self.moves.values()))
        self.assertEqual(
            move.stated_about_the_source, {"European Commission — JRC": (0.14,)}
        )

    def test_the_row_records_that_the_solvent_carries_nothing(self):
        # The half that makes the move undo itself if EF ever fixes this.
        move = next(iter(self.moves.values()))
        self.assertEqual(move.stated_about_the_destination, {})

    def test_every_row_states_its_reasoning(self):
        for key, move in self.moves.items():
            with self.subTest(key=key):
                self.assertTrue(move.comment.strip())


if __name__ == "__main__":
    unittest.main()
