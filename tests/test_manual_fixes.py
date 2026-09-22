"""One mechanism applies hand-authored corrections to any input list.

The motivating case is EF 3.1 shipping one substance's identifier on another.
EINECS 232-319-8 names *pyrethrins*, the natural mixture; EF 3.1 puts it on both
`jasmolin i` and `jasmolin ii`, two distinct constituents with their own CAS
numbers and formulae. Identifiers are how the merge decides two things are the
same substance, so carrying the mixture's number on both made them
indistinguishable and every source flow naming the mixture ambiguous:
ecoinvent's `Pyrethrins` resolved to two flow objects and was reported as
`multiple-flow-object-candidates` in six contexts.

That is a different *kind* of error from the ecoinvent fixes, which replace a
wrong CAS. Both are expressed as data in the same shape rather than as two
functions, which is what these assert.
"""

import tempfile
import unittest
from pathlib import Path

import orjson
from structlog.testing import capture_logs

from brightway_flows.context_mapping import (
    context_iri_by_source_context,
    flow_context_iri,
    name_prefix_context_iri,
    normalize_context_key,
)
from brightway_flows.domain.context import Dimension
from brightway_flows.domain.context_registry import context_for_iri
from brightway_flows.integrations.ef31 import MANUAL_FIXES_FILEPATH
from brightway_flows.manual_fixes import (
    MUTABLE_FIELDS,
    RETAIN_ORIGINAL_KEY,
    UNIT_CONVERSION_KEY,
    apply_manual_fixes,
)
from brightway_flows.pipeline.loading import _normalize_input_flow_record
from brightway_flows.sources import (
    PACKAGE_DATA_DIR,
    base_source_list,
    known_source_lists,
)

MIXTURE_EC = "232-319-8"
JASMOLIN_I = "4466-14-2"
JASMOLIN_II = "1172-63-0"


def _write(tmp, fixes):
    path = Path(tmp) / "fixes.json"
    path.write_bytes(orjson.dumps({"schema_version": 1, "fixes": fixes}))
    return path


def _flow(uuid, name, cas, ec):
    return {
        "uuid": uuid, "name": name,
        "cas_numbers": [cas] if cas else [],
        "ec_numbers": [ec] if ec else [],
    }


class RemovingAValueFromAListFieldTestCase(unittest.TestCase):
    """`remove_value`, the operation the mixture case needs.

    Replacing the field would be the wrong shape: the other entries in it are
    correct and have to survive.
    """

    def setUp(self):
        self.flows = [
            _flow("u-1", "jasmolin i", JASMOLIN_I, MIXTURE_EC),
            _flow("u-2", "jasmolin ii", JASMOLIN_II, MIXTURE_EC),
        ]
        self.fixes = [
            {"match": {"cas_numbers": cas}, "field": "ec_numbers",
             "remove_value": MIXTURE_EC, "comment": "mixture identifier"}
            for cas in (JASMOLIN_I, JASMOLIN_II)
        ]

    def test_the_mixture_ec_is_gone_from_both_constituents(self):
        with tempfile.TemporaryDirectory() as tmp:
            apply_manual_fixes(self.flows, _write(tmp, self.fixes))
        for flow in self.flows:
            self.assertEqual(flow["ec_numbers"], [], flow["name"])

    def test_the_two_are_distinguishable_afterwards(self):
        """The property the fix buys, not just the edit it makes."""
        with tempfile.TemporaryDirectory() as tmp:
            apply_manual_fixes(self.flows, _write(tmp, self.fixes))
        self.assertEqual(
            set(self.flows[0]["ec_numbers"]) & set(self.flows[1]["ec_numbers"]), set()
        )

    def test_the_constituents_keep_their_own_cas(self):
        with tempfile.TemporaryDirectory() as tmp:
            apply_manual_fixes(self.flows, _write(tmp, self.fixes))
        self.assertEqual(self.flows[0]["cas_numbers"], [JASMOLIN_I])
        self.assertEqual(self.flows[1]["cas_numbers"], [JASMOLIN_II])

    def test_other_values_in_the_same_field_survive(self):
        flow = _flow("u-1", "jasmolin i", JASMOLIN_I, MIXTURE_EC)
        flow["ec_numbers"] = [MIXTURE_EC, "200-000-0"]
        with tempfile.TemporaryDirectory() as tmp:
            apply_manual_fixes([flow], _write(tmp, self.fixes))
        self.assertEqual(flow["ec_numbers"], ["200-000-0"])

    def test_applying_twice_changes_nothing_further(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(tmp, self.fixes)
            apply_manual_fixes(self.flows, path)
            once = orjson.dumps(self.flows)
            apply_manual_fixes(self.flows, path)
            self.assertEqual(orjson.dumps(self.flows), once)


class RemovingAValueFromAScalarFieldTestCase(unittest.TestCase):
    """The same operation on the singular fields source lists actually ship.

    ecoinvent gives one `cas_number`, a string, where extracted EF 3.1 rows
    give a `cas_numbers` list.  A wrong identifier has to come off either
    shape, and there is no replacement to write: the flow simply has no
    registry number, which is what a nutrient load reported as a mass of
    nitrogen has (#57).

    This was silently a no-op until then.  A `remove_value` on a scalar fell
    through the list check, reported itself applied with `rows_changed=0`, and
    left the value in place -- so ecoinvent's brine kept water's registry
    number in all five versions after a curator had taken it off, and the
    fixes file went on asserting a correction that was not happening.
    """

    def test_the_wrong_number_is_gone(self):
        flow = {"uuid": "u-1", "name": "Nitrogen, organic bound",
                "cas_number": "7727-37-9"}
        fixes = [{"match": {"name": "Nitrogen, organic bound"}, "field": "cas_number",
                  "remove_value": "7727-37-9", "comment": "dinitrogen's number"}]
        with tempfile.TemporaryDirectory() as tmp:
            apply_manual_fixes([flow], _write(tmp, fixes))
        self.assertIsNone(flow["cas_number"])

    def test_the_row_reads_as_carrying_no_number_at_all(self):
        """The property the removal buys, not the edit it makes.

        `pipeline.loading` folds the singular field into `cas_numbers`, and
        what it must produce is an empty list -- a flow the CAS branch of the
        layering never groups.
        """
        flow = {"uuid": "u-1", "name": "Nitrogen, organic bound",
                "cas_number": "7727-37-9"}
        fixes = [{"match": {"name": "Nitrogen, organic bound"}, "field": "cas_number",
                  "remove_value": "7727-37-9", "comment": "dinitrogen's number"}]
        with tempfile.TemporaryDirectory() as tmp:
            apply_manual_fixes([flow], _write(tmp, fixes))
        self.assertEqual(_normalize_input_flow_record(flow)["cas_numbers"], [])

    def test_a_row_holding_a_different_value_is_untouched(self):
        """ecoinvent's own `Nitrogen` rows keep 7727-37-9: it is theirs."""
        flow = {"uuid": "u-2", "name": "Nitrogen, organic bound",
                "cas_number": "17778-88-0"}
        fixes = [{"match": {"name": "Nitrogen, organic bound"}, "field": "cas_number",
                  "remove_value": "7727-37-9", "comment": "dinitrogen's number"}]
        with tempfile.TemporaryDirectory() as tmp:
            apply_manual_fixes([flow], _write(tmp, fixes))
        self.assertEqual(flow["cas_number"], "17778-88-0")

    def test_applying_twice_changes_nothing_further(self):
        flow = {"uuid": "u-1", "name": "Nitrogen, organic bound",
                "cas_number": "7727-37-9"}
        fixes = [{"match": {"name": "Nitrogen, organic bound"}, "field": "cas_number",
                  "remove_value": "7727-37-9", "comment": "dinitrogen's number"}]
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(tmp, fixes)
            apply_manual_fixes([flow], path)
            once = orjson.dumps(flow)
            apply_manual_fixes([flow], path)
        self.assertEqual(orjson.dumps(flow), once)


class MatchingOnAnyFieldTestCase(unittest.TestCase):
    def test_one_rule_reaches_every_context_of_a_substance(self):
        """EF 3.1 repeats a substance once per context -- 13 flows each.

        A uuid-keyed rule would state itself 26 times for the two jasmolins and
        go stale the moment a context is added.
        """
        many = [_flow(f"u-{i}", "jasmolin i", JASMOLIN_I, MIXTURE_EC) for i in range(13)]
        fixes = [{"match": {"cas_numbers": JASMOLIN_I}, "field": "ec_numbers",
                  "remove_value": MIXTURE_EC, "comment": "one rule, every context"}]
        with tempfile.TemporaryDirectory() as tmp:
            apply_manual_fixes(many, _write(tmp, fixes))
        self.assertTrue(all(f["ec_numbers"] == [] for f in many))

    def test_a_substance_that_really_is_the_mixture_is_untouched(self):
        """The fix is about constituents, not about the number itself."""
        mixture = _flow("u-9", "pyrethrins", "8003-34-7", MIXTURE_EC)
        fixes = [{"match": {"cas_numbers": JASMOLIN_I}, "field": "ec_numbers",
                  "remove_value": MIXTURE_EC, "comment": "constituent only"}]
        with tempfile.TemporaryDirectory() as tmp:
            apply_manual_fixes([mixture], _write(tmp, fixes))
        self.assertEqual(mixture["ec_numbers"], [MIXTURE_EC])

    def test_uuid_is_shorthand_for_a_match_on_uuid(self):
        """What every existing fixes file is written in terms of."""
        flow = {"uuid": "u-1", "cas_number": "58-89-9"}
        fixes = [{"uuid": "u-1", "field": "cas_number",
                  "new_value": "319-86-8", "comment": "delta- not gamma-lindane"}]
        with tempfile.TemporaryDirectory() as tmp:
            apply_manual_fixes([flow], _write(tmp, fixes))
        self.assertEqual(flow["cas_number"], "319-86-8")


class ReplacingAValueTestCase(unittest.TestCase):
    def test_original_value_guards_a_stale_fix(self):
        """A fix that no longer describes the data is skipped, not applied."""
        flow = {"uuid": "u-1", "cas_number": "something-else"}
        fixes = [{"uuid": "u-1", "field": "cas_number", "original_value": "58-89-9",
                  "new_value": "319-86-8", "comment": "guarded"}]
        with tempfile.TemporaryDirectory() as tmp:
            apply_manual_fixes([flow], _write(tmp, fixes))
        self.assertEqual(flow["cas_number"], "something-else")

    def test_a_guarded_fix_applied_twice_is_quiet_the_second_time(self):
        """Already applied is not the same as stale, and must not read as it.

        The base list has its fixes applied twice -- once by `extract`, once by
        the transform reading that file back (#237) -- so the second pass sees
        the new value.  Without this, `original_value` would then fail to match
        and a fix that worked would warn about itself on every build.
        """
        flow = {"uuid": "u-1", "cas_number": "58-89-9"}
        fixes = [{"uuid": "u-1", "field": "cas_number", "original_value": "58-89-9",
                  "new_value": "319-86-8", "comment": "guarded"}]
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(tmp, fixes)
            apply_manual_fixes([flow], path)
            self.assertEqual(flow["cas_number"], "319-86-8")
            with capture_logs() as second_pass:
                apply_manual_fixes([flow], path)

        self.assertEqual(flow["cas_number"], "319-86-8")
        self.assertEqual(
            [entry for entry in second_pass
             if entry["event"] == "manual_fix_original_value_mismatch"],
            [],
        )

    def test_a_rename_applied_twice_does_not_report_itself_as_stale(self):
        """A fix that changes the field it matches on cannot match a second
        time: the rows now hold the new name and the criterion still names the
        old one. `Palladium-234m` -> `Protactinium-234m` warned on every second
        pass that it had matched nothing -- which reads exactly like the fix
        having gone stale, and that warning is the only signal a curator has
        for a fix that really has.
        """
        flow = {"uuid": "u-1", "name": "Palladium-234m"}
        fixes = [{"match": {"name": "Palladium-234m"}, "field": "name",
                  "new_value": "Protactinium-234m", "comment": "wrong element"}]
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(tmp, fixes)
            apply_manual_fixes([flow], path)
            self.assertEqual(flow["name"], "Protactinium-234m")
            with capture_logs() as second_pass:
                apply_manual_fixes([flow], path)

        events = [entry["event"] for entry in second_pass]
        self.assertIn("manual_fix_already_applied", events)
        self.assertNotIn("manual_fix_matched_nothing", events)

    def test_a_rename_that_really_matches_nothing_still_warns(self):
        """The signal has to survive being made quieter."""
        flow = {"uuid": "u-1", "name": "Something else entirely"}
        fixes = [{"match": {"name": "Palladium-234m"}, "field": "name",
                  "new_value": "Protactinium-234m", "comment": "wrong element"}]
        with tempfile.TemporaryDirectory() as tmp:
            with capture_logs() as logs:
                apply_manual_fixes([flow], _write(tmp, fixes))
        self.assertIn(
            "manual_fix_matched_nothing", [entry["event"] for entry in logs]
        )

    def test_an_unguarded_fix_applied_twice_changes_nothing_further(self):
        flow = {"uuid": "u-1", "cas_number": "58-89-9"}
        fixes = [{"uuid": "u-1", "field": "cas_number",
                  "new_value": "319-86-8", "comment": "unguarded"}]
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(tmp, fixes)
            apply_manual_fixes([flow], path)
            once = orjson.dumps(flow)
            apply_manual_fixes([flow], path)
        self.assertEqual(orjson.dumps(flow), once)


class AuthoringMistakesFailLoudlyTestCase(unittest.TestCase):
    """A fix that silently does nothing is worse than one that raises: the
    file goes on asserting a correction that is not happening."""

    def _apply(self, fix):
        with tempfile.TemporaryDirectory() as tmp:
            apply_manual_fixes([], _write(tmp, [fix]))

    def test_a_fix_without_a_comment_is_refused(self):
        with self.assertRaises(ValueError):
            self._apply({"uuid": "u-1", "field": "name", "new_value": "x"})

    def test_a_fix_naming_an_unknown_field_is_refused(self):
        with self.assertRaises(ValueError):
            self._apply({"uuid": "u-1", "field": "nonesuch",
                         "new_value": "x", "comment": "typo in field"})

    def test_a_fix_with_neither_operation_is_refused(self):
        with self.assertRaises(ValueError):
            self._apply({"uuid": "u-1", "field": "name", "comment": "no op"})

    def test_a_fix_with_both_operations_is_refused(self):
        with self.assertRaises(ValueError):
            self._apply({"uuid": "u-1", "field": "name", "new_value": "x",
                         "remove_value": "y", "comment": "ambiguous"})

    def test_a_fix_matching_on_nothing_is_refused(self):
        with self.assertRaises(ValueError):
            self._apply({"field": "name", "new_value": "x", "comment": "no criteria"})

    def test_a_missing_file_is_not_an_error(self):
        """A list with no corrections is the normal state of a new list."""
        flows = [{"uuid": "u-1"}]
        apply_manual_fixes(flows, Path("/nonexistent/fixes.json"))
        self.assertEqual(flows, [{"uuid": "u-1"}])


class TheCheckedInFilesAreValidTestCase(unittest.TestCase):
    def test_the_ef31_fixes_load_and_state_their_reasons(self):
        payload = orjson.loads(MANUAL_FIXES_FILEPATH.read_bytes())
        fixes = payload["fixes"]
        self.assertTrue(fixes)
        for fix in fixes:
            with self.subTest(match=fix.get("match")):
                self.assertTrue(str(fix.get("comment") or "").strip())
                self.assertIn(fix["field"], MUTABLE_FIELDS)

    def test_the_ef31_fixes_apply_to_realistic_rows(self):
        flows = [
            _flow("u-1", "jasmolin i", JASMOLIN_I, MIXTURE_EC),
            _flow("u-2", "jasmolin ii", JASMOLIN_II, MIXTURE_EC),
            _flow("u-3", "pyrethrins", "8003-34-7", MIXTURE_EC),
        ]
        apply_manual_fixes(flows, MANUAL_FIXES_FILEPATH, label="EF 3.1")
        self.assertEqual(flows[0]["ec_numbers"], [])
        self.assertEqual(flows[1]["ec_numbers"], [])
        self.assertEqual(flows[2]["ec_numbers"], [MIXTURE_EC])


class FluoresceinIsTheSodiumSaltTestCase(unittest.TestCase):
    """#312, asked of the shipped file rather than of a fixture.

    EF 3.1 names twelve of thirteen flows `Fluorescein`, which is the free
    acid, while every one of the thirteen carries 518-47-8 and 208-253-0, which
    are the disodium salt's.  The fix is stated once against the registry
    number, so what has to hold is both halves of that: every row carrying the
    salt's number is renamed, and a row carrying the acid's is not.

    The second half is the one worth a test.  A fix keyed on a name would have
    caught the twelve and missed the thirteenth; a fix keyed on the *word*
    fluorescein would reach the acid too, and the acid is a different substance
    with a different mass, a different solubility and a different fingerprint.
    """

    SALT = "518-47-8"
    SALT_EC = "208-253-0"
    ACID = "2321-07-5"
    NAME = "Fluorescein sodium"

    def _fixed(self, flows):
        apply_manual_fixes(flows, MANUAL_FIXES_FILEPATH, label="EF 3.1")
        return flows

    def test_every_context_of_the_salt_is_renamed(self):
        """Thirteen contexts under three spellings, one statement."""
        flows = [
            _flow("u-1", "Fluorescein", self.SALT, self.SALT_EC),
            _flow("u-2", "fluorescein", self.SALT, self.SALT_EC),
            _flow(
                "u-3",
                "disodium 2-(3-oxo-6-oxidoxanthen-9-yl)benzoate",
                self.SALT,
                self.SALT_EC,
            ),
        ]
        self._fixed(flows)
        self.assertEqual([row["name"] for row in flows], [self.NAME] * 3)

    def test_the_free_acid_keeps_its_name(self):
        """The half that stops this growing into a rule about a word."""
        acid = _flow("u-4", "Fluorescein", self.ACID, "219-031-8")
        self._fixed([acid])
        self.assertEqual(acid["name"], "Fluorescein")

    def test_the_replaced_name_is_not_kept_as_a_label(self):
        """`retain_original_as_synonym` asserts the replaced string is a name
        the substance has, and `Fluorescein` is not one: every fluorescein name
        Common Chemistry holds for 518-47-8 qualifies the word.  Publishing it
        would republish, as an alternative label, the confusion #312 is about.
        """
        flow = _flow("u-5", "Fluorescein", self.SALT, self.SALT_EC)
        self._fixed([flow])
        self.assertNotIn("altLabel", flow)

    def test_applying_twice_changes_nothing_further(self):
        """The base list applies its fixes at extract and again on read (#237),
        and this fix matches on a field it does not write, so it matches both
        times."""
        flows = [_flow("u-6", "Fluorescein", self.SALT, self.SALT_EC)]
        once = orjson.dumps(self._fixed(flows))
        self.assertEqual(orjson.dumps(self._fixed(flows)), once)


class PenteneMixtureIsNotOnePenteneTestCase(unittest.TestCase):
    """#157, asked of the shipped file rather than of a fixture.

    EF 3.1 names two substances `1-pentene`: the molecule, CAS 109-67-1, and
    the mixture of pentene isomers, CAS 25377-72-4, which has no InChIKey and
    carries the same factors as `cis-2-pentene` and `trans-2-pentene`.  The fix
    is stated once against the mixture's registry number, so both halves of
    that have to hold: every row carrying the mixture's number is renamed, and
    a row carrying the molecule's is not.

    The second half is the one worth a test.  A fix keyed on the name would
    have renamed both substances and left the list with no `1-pentene` at all.
    """

    MIXTURE = "25377-72-4"
    MIXTURE_EC = "246-916-6"
    MOLECULE = "109-67-1"
    MOLECULE_EC = "203-694-5"
    SHIPPED_NAME = "1-pentene"
    NAME = "Pentylene"

    def _fixed(self, flows):
        apply_manual_fixes(flows, MANUAL_FIXES_FILEPATH, label="EF 3.1")
        return flows

    def test_every_context_of_the_mixture_is_renamed(self):
        """Thirteen contexts under one spelling, one statement."""
        flows = [
            _flow(f"u-{index}", self.SHIPPED_NAME, self.MIXTURE, self.MIXTURE_EC)
            for index in range(3)
        ]
        self._fixed(flows)
        self.assertEqual([row["name"] for row in flows], [self.NAME] * 3)

    def test_the_molecule_keeps_the_name_that_is_its_own(self):
        """The half that stops this becoming a rule about a word."""
        molecule = _flow("u-4", self.SHIPPED_NAME, self.MOLECULE, self.MOLECULE_EC)
        self._fixed([molecule])
        self.assertEqual(molecule["name"], self.SHIPPED_NAME)

    def test_the_replaced_name_is_not_kept_as_a_label(self):
        """`retain_original_as_synonym` asserts the replaced string is a name
        the substance has, and `1-pentene` is the other substance's name.
        Keeping it would republish, as an alternative label, the ambiguity
        #157 is about.
        """
        flow = _flow("u-5", self.SHIPPED_NAME, self.MIXTURE, self.MIXTURE_EC)
        self._fixed([flow])
        self.assertNotIn("altLabel", flow)

    def test_applying_twice_changes_nothing_further(self):
        """The base list applies its fixes at extract and again on read (#237),
        and this fix matches on a field it does not write, so it matches both
        times."""
        flows = [_flow("u-6", self.SHIPPED_NAME, self.MIXTURE, self.MIXTURE_EC)]
        once = orjson.dumps(self._fixed(flows))
        self.assertEqual(orjson.dumps(self._fixed(flows)), once)


class TrichloroethaneIsomersTestCase(unittest.TestCase):
    """#121, asked of the shipped file rather than of a fixture.

    1,1,1-trichloroethane is the degreasing solvent the Montreal Protocol
    controls because it eats ozone; 1,1,2-trichloroethane is a suspected
    carcinogen with no effect on ozone at all.  One chlorine sits on a
    different carbon.  EF 3.1 names five flows -- the five air compartments --
    `1,1,1-trichloroethane` and gives every one of them 79-00-5, which is
    1,1,2's number, 1,1,2's synonyms and 1,1,2's toxicity factors, while
    1,1,2's other eight compartments are named correctly.

    The fix is stated once against the pair, so what has to hold is both
    halves of that: a flow carrying the carcinogen's number under the
    solvent's name is renamed, and a flow carrying the solvent's own number is
    not.  The second half is the one worth a test.  EF publishes the solvent
    thirteen times as `hcfc-140` and four more as `methyl chloroform`, and a
    fix keyed on the name alone would rename a substance that was never
    misnamed the moment either of those spellings changed.
    """

    CARCINOGEN = "79-00-5"
    SOLVENT = "71-55-6"
    CARCINOGEN_EC = "201-166-9"
    WRONG_NAME = "1,1,1-trichloroethane"
    RIGHT_NAME = "1,1,2-trichloroethane"

    #: The three spellings EF ships on the mislabelled flows that name the
    #: wrong isomer.  They are 1,1,2's own synonyms with the name substituted
    #: -- the correctly named flows carry `1,1,2-TRICHLOROETHANE (VINYL
    #: TRICHLORIDE)` where these carry the 1,1,1 spelling -- which is a third
    #: thing saying the name is the half that is wrong.
    ISOMER_SPELLINGS = (
        "1,1,1-trichloroethane (VINYL TRICHLORIDE)",
        "1,1,1-trichloroethane, 14C-2-labeled",
        "1,1,1-trichloroethane, 36Cl-labeled",
    )

    #: A spelling that really is 1,1,2's, on the same rows, which must survive.
    #: The removals name three strings, not a substring.
    KEPT_SPELLING = "Ethane, 1,1,2-trichloro-"

    def _row(self, uuid, name, cas, synonyms):
        return {
            "uuid": uuid,
            "name": name,
            "cas_numbers": [cas],
            "ec_numbers": [self.CARCINOGEN_EC],
            "synonyms": list(synonyms),
        }

    def _mislabelled(self, uuid="u-1"):
        return self._row(
            uuid,
            self.WRONG_NAME,
            self.CARCINOGEN,
            [*self.ISOMER_SPELLINGS, self.KEPT_SPELLING, "Vinyl trichloride"],
        )

    def _fixed(self, flows):
        apply_manual_fixes(flows, MANUAL_FIXES_FILEPATH, label="EF 3.1")
        return flows

    def test_every_air_compartment_is_renamed(self):
        """Five contexts, one statement, keyed on the number they share."""
        flows = [self._mislabelled(f"u-{n}") for n in range(5)]
        self._fixed(flows)
        self.assertEqual([row["name"] for row in flows], [self.RIGHT_NAME] * 5)

    def test_a_flow_carrying_the_solvents_own_number_keeps_its_name(self):
        """The half that stops this growing into a rule about a name.

        No EF 3.1 flow is shipped this way -- the solvent is `hcfc-140` and
        `methyl chloroform` -- and that is the point: the guard has to hold
        against a release that starts spelling it out, because renaming the
        solvent to its isomer is the very error being corrected, in reverse.
        """
        solvent = self._row("u-6", self.WRONG_NAME, self.SOLVENT, [])
        self._fixed([solvent])
        self.assertEqual(solvent["name"], self.WRONG_NAME)

    def test_the_replaced_name_is_not_kept_as_a_label(self):
        """`retain_original_as_synonym` asserts the replaced string is a name
        the substance genuinely has, and `1,1,1-trichloroethane` is not one:
        it names a different molecule, which is the whole of #121.  Publishing
        it as an alternative label would re-assert by name the identity the
        registry number denies.
        """
        flow = self._mislabelled()
        self._fixed([flow])
        self.assertNotIn("altLabel", flow)

    def test_the_isomers_spellings_leave_the_synonyms(self):
        """A synonym is what the label rules and the name index read, so a
        1,1,1 spelling left here would place a solvent row on the carcinogen
        by the same route the name did."""
        flow = self._mislabelled()
        self._fixed([flow])
        self.assertEqual(
            [s for s in flow["synonyms"] if s in self.ISOMER_SPELLINGS], []
        )

    def test_the_substances_own_spellings_survive(self):
        """The removal names three strings rather than a substring: every
        other name on the row is 1,1,2's and correct."""
        flow = self._mislabelled()
        self._fixed([flow])
        self.assertIn(self.KEPT_SPELLING, flow["synonyms"])
        self.assertIn("Vinyl trichloride", flow["synonyms"])

    def test_a_correctly_named_flow_is_left_alone(self):
        """The eight compartments EF names correctly share the registry number
        the fix matches on, so they are matched and must come through
        unchanged."""
        correct = self._row(
            "u-7", self.RIGHT_NAME, self.CARCINOGEN, [self.KEPT_SPELLING]
        )
        before = orjson.dumps(correct)
        self._fixed([correct])
        self.assertEqual(orjson.dumps(correct), before)

    def test_applying_twice_changes_nothing_further(self):
        """The base list applies its fixes at extract and again on read (#237).

        The rename matches on the field it writes, so the second pass finds the
        rows under the new name; the synonym removals match on the registry
        number, which the fixes never touch, so they match both times and find
        nothing left to remove.
        """
        flows = [self._mislabelled()]
        once = orjson.dumps(self._fixed(flows))
        self.assertEqual(orjson.dumps(self._fixed(flows)), once)


class OrganicBoundNitrogenIsNotNitrogenGasTestCase(unittest.TestCase):
    """#57, asked of every list that ships the rows rather than of one file.

    Organic-bound nitrogen is a nutrient load -- the nitrogen inside a
    discharge's organic matter, reported as a mass of nitrogen -- and
    dinitrogen is the inert gas that is most of the air.  EF 3.1 and all five
    ecoinvent versions give the organic-bound rows 7727-37-9, which is the
    gas's number, and a shared registry number is how this project decides two
    things are one substance: the rows were fused, renamed `Dinitrogen`, and
    published with the gas's structure and synonyms.

    A fix in one list would not settle it, because the merge only needs one
    list still asserting the identity to rebuild it -- which is why this reads
    the whole set, the way `test_cross_version_manual_fixes` does.  It skips a
    list that has not been fetched, and the file-level guards above still hold
    without the data.
    """

    GAS = "7727-37-9"
    GAS_SYNONYMS = frozenset({"dinitrogen", "molecular nitrogen"})

    #: How many organic-bound rows each list ships, because it is not one
    #: number.  EF 3.1 and every ecoinvent version have five; BAFU has four,
    #: filing the load in `groundwater, long-term`, `ocean`, `river` and
    #: `unspecified` where ecoinvent also has `surface water`.  Pinned per list
    #: rather than asserted as a single literal: the guard is that a list
    #: cannot quietly lose these rows and make the checks below vacuous, and a
    #: literal that only fits ecoinvent's compartment list makes registering
    #: any other list look like a regression.
    ROWS_PER_LIST = {"bafu-2026-v1": 4}
    DEFAULT_ROWS = 5

    @classmethod
    def setUpClass(cls):
        sources = {base_source_list().key: base_source_list(), **known_source_lists()}
        missing = [key for key, s in sources.items() if not s.flows_path.exists()]
        if missing:
            raise unittest.SkipTest(f"flows not fetched for {', '.join(sorted(missing))}")
        cls.fixed = {}
        for key, source in sources.items():
            flows = orjson.loads(source.flows_path.read_bytes())
            if source.manual_fixes_path is not None:
                apply_manual_fixes(flows, source.manual_fixes_path, label=key)
            cls.fixed[key] = [
                _normalize_input_flow_record(row, source_hint=key) or row
                for row in flows
            ]

    def _organic_bound(self, flows):
        return [f for f in flows if "organic bound" in str(f.get("name") or "").lower()]

    def test_every_list_ships_the_rows_this_is_about(self):
        """So a list quietly losing them cannot make the guards below vacuous."""
        for key, flows in self.fixed.items():
            with self.subTest(source=key):
                self.assertEqual(
                    len(self._organic_bound(flows)),
                    self.ROWS_PER_LIST.get(key, self.DEFAULT_ROWS),
                )

    def test_no_list_still_calls_a_nutrient_load_nitrogen_gas(self):
        for key, flows in self.fixed.items():
            for flow in self._organic_bound(flows):
                with self.subTest(source=key, uuid=flow.get("uuid")):
                    self.assertNotIn(self.GAS, flow.get("cas_numbers") or [])

    def test_the_gas_synonyms_are_gone_too(self):
        """A synonym is what the label rules and the name index read.

        ecoinvent gives the organic-bound rows the synonym set of its own
        `Nitrogen` rows from 3.9.1 on, so leaving those would re-assert by name
        the identity the registry number no longer asserts.
        """
        for key, flows in self.fixed.items():
            for flow in self._organic_bound(flows):
                with self.subTest(source=key, uuid=flow.get("uuid")):
                    named = {str(s).lower() for s in (flow.get("synonyms") or ())}
                    self.assertEqual(named & self.GAS_SYNONYMS, set())

    def test_the_gas_keeps_its_own_number(self):
        """The removal is about the wrong rows, not about the number."""
        for key, flows in self.fixed.items():
            claiming = {
                str(f.get("name") or "").lower()
                for f in flows
                if self.GAS in (f.get("cas_numbers") or [])
            }
            with self.subTest(source=key):
                self.assertTrue(claiming, f"{key} lost 7727-37-9 altogether")
                self.assertNotIn("nitrogen, organic bound", claiming)

    def test_one_name_is_left_claiming_the_number_in_each_list(self):
        """What makes the contested-registry-number question go away (#34).

        The gate could not answer it: the signal it decides on is the source
        list giving the two names different characterisation factors, and
        neither name carries any factor at all, so it stayed merged and filed
        the question.  With the number on one name there is no contest to ask
        about.
        """
        for key, flows in self.fixed.items():
            claiming = {
                str(f.get("name") or "").lower()
                for f in flows
                if self.GAS in (f.get("cas_numbers") or [])
            }
            with self.subTest(source=key):
                self.assertEqual(len(claiming), 1, claiming)


class WasteHeatIsNotSomethingYouExtractTestCase(unittest.TestCase):
    """#75, asked of every list the same way the nitrogen case is.

    Waste heat is heat a process could not use and dumped -- into the air,
    into a river, into the ground.  It is an output, and every list carries it
    as one: EF 3.1 as `waste heat` in twelve contexts, ecoinvent as `Heat,
    waste` in thirteen or fourteen, BAFU as `Heat, waste` in fourteen.  BAFU
    also has a fifteenth row, `Energy, waste heat, air`, filed under
    `resources / in air`, and the compartment rule believed it: the published
    list said waste heat was both an emission and a resource.

    Two halves, in the two files that hold those kinds of statement.  The name
    is a manual fix, because `Energy, waste heat, air` is a second name for a
    flow this list already ships as `Heat, waste`.  The compartment is a
    per-flow rule in `context-manual-mapping.json`, because BAFU has the row on
    the wrong side of the system boundary and the compartment it is in is right
    for the ten others in it.  Both are asserted here, because either alone
    leaves the row wrong.

    It skips a list that has not been fetched, as the nitrogen case does.
    """

    #: The stray, and the row it is a second name for: same compartment once
    #: corrected, same unit, same substance.
    STRAY = "f4729c09-f11a-5414-a907-c29aed8807f0"
    SIBLING = "a444355b-4415-5025-8f38-9c43dcccf91e"
    BAFU = "bafu-2026-v1"
    AIR_UNSPECIFIED = "https://vocab.brightway.one/flow-contexts/envi-air-unkn"

    #: What each list ships, so that a list quietly losing the rows cannot make
    #: the check below vacuous.  Not one number: the lists disagree about how
    #: many compartments waste heat is released into, which is not what this is
    #: about.
    ROWS_PER_LIST = {
        "EF-3.1": 12,
        "bafu-2026-v1": 15,
        "ecoinvent-3.8": 14,
        "ecoinvent-3.9.1": 14,
        "ecoinvent-3.10.1": 13,
        "ecoinvent-3.11": 13,
        "ecoinvent-3.12": 13,
        # None. Stepwise is an LCIA method and characterises no waste heat, so
        # it ships no row for one -- pinned at zero rather than left out, so a
        # revision that adds one arrives here instead of being placed by
        # whatever compartment rule it lands under.
        "stepwise-2006-1.09": 0,
        # `Heat, waste` in thirteen emission compartments, all of them on the
        # right side of the system boundary -- AGRIBALYSE ships no resource-side
        # stray for the BAFU half of this case to apply to.
        "agribalyse-3.2": 13,
    }

    @classmethod
    def setUpClass(cls):
        sources = {base_source_list().key: base_source_list(), **known_source_lists()}
        missing = [key for key, s in sources.items() if not s.flows_path.exists()]
        if missing:
            raise unittest.SkipTest(f"flows not fetched for {', '.join(sorted(missing))}")
        cls.sources = sources
        cls.fixed = {}
        for key, source in sources.items():
            flows = orjson.loads(source.flows_path.read_bytes())
            if source.manual_fixes_path is not None:
                apply_manual_fixes(flows, source.manual_fixes_path, label=key)
            cls.fixed[key] = flows

    def _waste_heat(self, flows):
        """Every spelling, including the one the fix takes away.

        Matching the corrected names only would make the check below pass on an
        uncorrected list: `Energy, waste heat, air` is not `Heat, waste`, and a
        test that cannot see the row it is about asserts nothing.
        """
        return [
            f
            for f in flows
            if any(
                spelling in str(f.get("name") or "").lower()
                for spelling in ("waste heat", "heat, waste")
            )
        ]

    def _resolve(self, key, flow):
        """The context the transform would reach, by its own three steps."""
        label = self.sources[key].source_label
        context = flow["context"]
        return (
            flow_context_iri(label, flow["uuid"], context)
            or name_prefix_context_iri(label, str(flow.get("name") or ""), context)
            or context_iri_by_source_context(label).get(normalize_context_key(context))
        )

    def test_every_list_ships_the_rows_this_is_about(self):
        for key, flows in self.fixed.items():
            with self.subTest(source=key):
                self.assertEqual(
                    len(self._waste_heat(flows)), self.ROWS_PER_LIST[key]
                )

    def test_no_list_publishes_waste_heat_as_a_resource(self):
        """The defect, stated as the property that has to hold everywhere.

        A resource and an emission are opposites, and a list that says both
        hands a characterisation method a number on the wrong side of the
        boundary or, more likely, one it never looks for.
        """
        for key, flows in self.fixed.items():
            for flow in self._waste_heat(flows):
                with self.subTest(source=key, uuid=flow["uuid"]):
                    iri = self._resolve(key, flow)
                    self.assertIsNotNone(iri, "no rule places this row")
                    self.assertEqual(
                        context_for_iri(iri).dimension, Dimension.ENVIRONMENTAL
                    )

    def test_the_stray_row_is_the_flow_bafu_already_ships(self):
        """Renamed to the vendor's own name for it, not invented for the fix.

        `Heat, waste` in `emissions to air / unspecified` in MJ is already in
        this list.  With the name corrected and the compartment rule applied,
        the stray is that row: same substance, same context, same unit.
        """
        by_uuid = {f["uuid"]: f for f in self.fixed[self.BAFU]}
        stray, sibling = by_uuid[self.STRAY], by_uuid[self.SIBLING]
        self.assertEqual(stray["name"], sibling["name"])
        self.assertEqual(stray["unit"], sibling["unit"])
        self.assertEqual(
            self._resolve(self.BAFU, stray), self._resolve(self.BAFU, sibling)
        )
        self.assertEqual(self._resolve(self.BAFU, stray), self.AIR_UNSPECIFIED)

    def test_the_name_it_had_is_gone_from_the_list(self):
        """A fix that stopped matching would leave the old name in place, and
        the row would go back to being a substance of its own."""
        names = {str(f.get("name") or "") for f in self.fixed[self.BAFU]}
        self.assertNotIn("Energy, waste heat, air", names)

    def test_the_compartment_rule_alone_would_still_call_it_a_resource(self):
        """Why the per-flow rule is needed, and that it is what is doing the
        work: `resources / in air` is right for the ten rows beside this one --
        air itself, nitrogen, oxygen, krypton, xenon, carbon dioxide in air,
        wind and sunlight -- and this is the only row in it that is an output.
        """
        compartment = context_iri_by_source_context(self.BAFU)[
            normalize_context_key(["resources", "in air"])
        ]
        self.assertEqual(context_for_iri(compartment).dimension, Dimension.RESOURCE)


class BafuReportsTheSameThreeMeasurementsEfDoesTestCase(unittest.TestCase):
    """#68 left three pairs unmerged; this is what closes them.

    Chemical oxygen demand, five-day biochemical oxygen demand and total
    organic carbon are each one quantity produced by one procedure, and each
    was being published twice: once as EF 3.1's `chemical oxygen demand`, once
    as BAFU's `COD, Chemical Oxygen Demand`.  The whole of the difference is
    the prefix, and neither row carries a registry number the other shares, so
    nothing but the names could have brought them together.

    `DOC, Dissolved Organic Carbon` is the control.  BAFU ships it too, it
    needs no fix, and it lands on EF's flow object today -- for no better
    reason than that EF happens to ship the prefixed spelling itself.  That is
    what makes these three an accident of spelling rather than a judgement
    about the quantities.

    Asserted against both lists as they are actually loaded, rather than
    against a hand-built row, because the claim is about two files agreeing.
    Skipped when a list has not been fetched, like the nitrogen case above.
    """

    #: BAFU's name, and the name EF 3.1 ships for the same quantity.
    PAIRS = {
        "COD, Chemical Oxygen Demand": "chemical oxygen demand",
        "BOD5, Biological Oxygen Demand": "biological oxygen demand",
        "TOC, Total Organic Carbon": "total organic carbon",
    }
    #: Ships identically in both lists, so it is matched by BAFU's own name.
    CONTROL = "DOC, Dissolved Organic Carbon"

    @classmethod
    def setUpClass(cls):
        bafu = known_source_lists().get("bafu-2026-v1")
        if bafu is None:
            raise unittest.SkipTest("BAFU 2026 v1 is not registered")
        base = base_source_list()
        missing = [s.key for s in (bafu, base) if not s.flows_path.exists()]
        if missing:
            raise unittest.SkipTest(f"flows not fetched for {', '.join(sorted(missing))}")

        rows = orjson.loads(bafu.flows_path.read_bytes())
        apply_manual_fixes(rows, bafu.manual_fixes_path, label=bafu.key)
        cls.bafu_rows = [
            _normalize_input_flow_record(row, source_hint=bafu.key) or row for row in rows
        ]
        cls.base_names = {
            str(row.get("name") or "").strip().lower()
            for row in orjson.loads(base.flows_path.read_bytes())
        }

    def _rows_named(self, name):
        return [row for row in self.bafu_rows if row.get("name") == name]

    def _labels(self, row):
        """The names the merge looks a row up by: what it shipped, plus synonyms."""
        return [str(row.get("name") or ""), *(row.get("synonyms") or ())]

    def test_bafu_still_ships_the_rows_this_is_about(self):
        """So a renamed row cannot make the rest of these vacuous."""
        for name in [*self.PAIRS, self.CONTROL]:
            with self.subTest(name=name):
                self.assertTrue(self._rows_named(name))

    def test_the_base_list_ships_the_flow_each_one_should_reach(self):
        for bafu_name, base_name in self.PAIRS.items():
            with self.subTest(name=bafu_name):
                self.assertIn(base_name, self.base_names)

    def test_every_row_is_looked_up_under_a_name_the_base_list_knows(self):
        """The whole of the fix: one shared string, and the merge does the rest."""
        for bafu_name, base_name in self.PAIRS.items():
            for row in self._rows_named(bafu_name):
                with self.subTest(name=bafu_name, uuid=row.get("uuid")):
                    labels = {label.strip().lower() for label in self._labels(row)}
                    self.assertIn(base_name, labels)

    def test_bafu_keeps_its_own_spelling(self):
        """A synonym, not a rename: the name BAFU published is what it published.

        `bootstrap_labels` reads the shipped name and its synonyms and then
        purges both, so the added string is read by the merge and published
        nowhere.  Renaming the row instead would put EF's spelling into
        `source_refs` as though BAFU had used it.
        """
        for bafu_name in self.PAIRS:
            for row in self._rows_named(bafu_name):
                with self.subTest(name=bafu_name, uuid=row.get("uuid")):
                    self.assertEqual(row.get("name"), bafu_name)

    def test_the_control_needs_no_synonym_to_reach_its_flow(self):
        for row in self._rows_named(self.CONTROL):
            with self.subTest(uuid=row.get("uuid")):
                self.assertEqual(row.get("synonyms"), [])
                self.assertIn(self.CONTROL.lower(), self.base_names)

    def test_the_registry_number_on_cod_is_left_for_the_typing_pass(self):
        """17612-50-9 names no compound, and #68 withdraws it on the object.

        Removing it here would pre-empt that and leave no record of a number
        the list really did carry.  It cannot affect the match either way: EF's
        flow object has no registry number for it to disagree with.
        """
        numbers = {
            number
            for row in self._rows_named("COD, Chemical Oxygen Demand")
            for number in (row.get("cas_numbers") or ())
        }
        self.assertEqual(numbers, {"17612-50-9"})


class BiomassEnergyIsOneResourceNotTwoTestCase(unittest.TestCase):
    """The energy in a forest's wood, published once instead of twice (#74).

    EF 3.1 calls this resource `biomass` and the list publishes it as `Biomass`.
    ecoinvent calls it `Energy, gross calorific value, in biomass` and reaches
    EF's flow through its correspondence table, which carries the two uuids and
    says nothing that would leave ecoinvent's *name* anywhere a later list could
    find it.  BAFU then shipped that same string, matched nothing, and minted a
    second substance -- the most heavily used resource flow it has, in 394 of
    the release's 11,947 datasets.

    So the fix is the same shape as the COD one above: one shared string, added
    as a synonym, and the merge does the rest.  The claim it rests on is not
    made here either -- two published correspondence tables already say these
    are one flow, and `test_the_pairing_is_one_ecoinvents_table_already_makes`
    reads one of them back.

    `Energy, gross calorific value, in biomass, primary forest` is the control.
    Same family, same compartment, same unit, no registry number on either side,
    and it needs no fix at all -- EF happens to ship that name unchanged.  That
    is what makes this an accident of spelling rather than a judgement about the
    resource.
    """

    NAME = "Energy, gross calorific value, in biomass"
    #: What EF 3.1 ships, and so what the flow object is reachable under.
    BASE_NAME = "biomass"
    #: EF 3.1's flow, and the target both ecoinvent tables name for `NAME`.
    BASE_UUID = "fe0acd60-3ddc-11dd-a6fd-0050c2490048"
    #: Ships under a name EF uses too, so it needs no synonym.
    CONTROL = "Energy, gross calorific value, in biomass, primary forest"
    #: A negative amount of this same resource, decided by #69 and following
    #: this row onto the same object.
    SIBLING = "Energy, gross calorific value, in biomass, resource correction"
    #: The three compartments BAFU files `NAME` in, as it spells them.
    COMPARTMENTS = {
        ("resources", "biotic"),
        ("resources", "unspecified"),
        ("resources", "in air"),
    }

    @classmethod
    def setUpClass(cls):
        bafu = known_source_lists().get("bafu-2026-v1")
        if bafu is None:
            raise unittest.SkipTest("BAFU 2026 v1 is not registered")
        base = base_source_list()
        missing = [s.key for s in (bafu, base) if not s.flows_path.exists()]
        if missing:
            raise unittest.SkipTest(f"flows not fetched for {', '.join(sorted(missing))}")

        rows = orjson.loads(bafu.flows_path.read_bytes())
        apply_manual_fixes(rows, bafu.manual_fixes_path, label=bafu.key)
        cls.bafu_rows = [
            _normalize_input_flow_record(row, source_hint=bafu.key) or row for row in rows
        ]
        cls.base_rows = orjson.loads(base.flows_path.read_bytes())

    def _rows_named(self, name):
        return [row for row in self.bafu_rows if row.get("name") == name]

    def _labels(self, row):
        """The names the merge looks a row up by: what it shipped, plus synonyms."""
        return {
            str(label).strip().lower()
            for label in (str(row.get("name") or ""), *(row.get("synonyms") or ()))
        }

    def test_bafu_still_ships_the_rows_this_is_about(self):
        """So a renamed row cannot make the rest of these vacuous."""
        for name in (self.NAME, self.CONTROL, self.SIBLING):
            with self.subTest(name=name):
                self.assertTrue(self._rows_named(name))

    def test_the_three_compartments_are_the_ones_the_fix_describes(self):
        """A fourth would reach the shared object unread, so it is asserted."""
        self.assertEqual(
            {tuple(row.get("context") or ()) for row in self._rows_named(self.NAME)},
            self.COMPARTMENTS,
        )

    def test_every_row_is_looked_up_under_a_name_the_base_list_knows(self):
        """The whole of the fix: one shared string, and the merge does the rest."""
        for row in self._rows_named(self.NAME):
            with self.subTest(uuid=row.get("uuid")):
                self.assertIn(self.BASE_NAME, self._labels(row))

    def test_the_base_list_ships_that_flow_in_the_same_unit(self):
        """`biomass`, MJ, a renewable energy resource from the biosphere."""
        flows = [row for row in self.base_rows if row.get("uuid") == self.BASE_UUID]
        self.assertEqual(len(flows), 1)
        self.assertEqual(flows[0].get("name"), self.BASE_NAME)
        self.assertEqual(flows[0].get("unit"), "MJ")
        self.assertEqual(
            {str(row.get("unit") or "") for row in self._rows_named(self.NAME)},
            {"MJ"},
        )

    def test_neither_side_carries_a_registry_number(self):
        """Which is why nothing but the names could have brought them together.

        An amount of energy has no registry number to carry, so the shared
        string is the only evidence there is or could be.
        """
        flow = next(row for row in self.base_rows if row.get("uuid") == self.BASE_UUID)
        self.assertEqual(flow.get("cas_numbers"), [])
        for row in self._rows_named(self.NAME):
            with self.subTest(uuid=row.get("uuid")):
                self.assertEqual(row.get("cas_numbers") or [], [])

    # `test_the_pairing_is_one_ecoinvents_table_already_makes` read the
    # composed 3.8 table to prove two lists had already published this
    # equivalence.  The table went to git history with #141's last follow-up;
    # the equivalence it witnessed is frozen there (every `Energy, gross
    # calorific value, in biomass` row -> EF's `energy from biomass`), and the
    # synonym's live justification is the pairing the merge itself now makes,
    # which the tests around this comment hold.


    def test_bafu_keeps_its_own_spelling(self):
        """A synonym, not a rename: the name BAFU published is what it published.

        `bootstrap_labels` reads the shipped name and its synonyms and then
        purges both, so the added string is read by the merge and published
        nowhere.  Renaming the row instead would put EF's spelling into
        `source_refs` as though BAFU had used it.
        """
        for row in self._rows_named(self.NAME):
            with self.subTest(uuid=row.get("uuid")):
                self.assertEqual(row.get("name"), self.NAME)

    def test_the_control_needs_no_synonym_to_reach_its_flow(self):
        base_names = {str(row.get("name") or "").strip().lower() for row in self.base_rows}
        self.assertIn(self.CONTROL.lower(), base_names)
        for row in self._rows_named(self.CONTROL):
            with self.subTest(uuid=row.get("uuid")):
                self.assertEqual(row.get("synonyms"), [])

    def test_the_resource_correction_sibling_follows_this_row(self):
        """It was left alone here, and #69 then decided what it is.

        A correction is a negative amount of the resource it corrects -- BAFU
        writes the resource's own registry number on nine of its eleven
        corrections, and this is one of the two where there was no number to
        write.  So it is looked up under the same name this row is, by a fix of
        its own keyed on its own whole name.

        `tests/test_bafu_resource_corrections.py` holds that family and its
        evidence.  What this asserts is only that the two have not drifted
        apart: a resource and its correction on different objects is the fault
        both fixes exist to prevent.
        """
        rows = self._rows_named(self.SIBLING)
        self.assertTrue(rows)
        for row in rows:
            with self.subTest(uuid=row.get("uuid")):
                self.assertIn(self.BASE_NAME, self._labels(row))


class RebasingARowOntoAnotherUnitTestCase(unittest.TestCase):
    """A unit rewrite may state the factor between the two units.

    Rewriting a unit is not like rewriting a wrong CAS. A vendor measuring
    standing wood in kilograms is not mistaken; it is measuring the same
    resource another way, and rebasing it onto the unit the rest of the list
    uses throws that away unless the factor comes with it. Stated here, it is
    published as `qudt:conversionMultiplier` on the flow's mapping -- the same
    place a factor from a correspondence table lands, and the only place a list
    that has no table can say it.
    """

    FIX = {
        "match": {"name": "Wood, unspecified, standing/kg"},
        "field": "unit",
        "original_value": "kg",
        "new_value": "m3",
        "conversion_factor": 0.00204,
        "comment": "0.49 oven-dry tonnes per m3, IPCC Table 4.14",
    }

    def _row(self):
        return {"uuid": "u-1", "name": "Wood, unspecified, standing/kg", "unit": "kg"}

    def _apply(self, fix, rows):
        with tempfile.TemporaryDirectory() as tmp:
            apply_manual_fixes(rows, _write(tmp, [fix]))
        return rows

    def test_the_unit_is_rewritten_and_the_pair_recorded(self):
        row = self._apply(self.FIX, [self._row()])[0]
        self.assertEqual(row["unit"], "m3")
        self.assertEqual(row[UNIT_CONVERSION_KEY], {
            "source_unit": "kg",
            "target_unit": "m3",
            "factor": 0.00204,
            "comment": "0.49 oven-dry tonnes per m3, IPCC Table 4.14",
        })

    def test_the_record_survives_normalisation(self):
        """`Flow.extra` round-trips keys the record class does not declare,
        which is how the merge reads this back."""
        row = self._apply(self.FIX, [self._row()])[0]
        normalised = _normalize_input_flow_record(row, source_hint="bafu-2026-v1")
        self.assertIn(UNIT_CONVERSION_KEY, normalised)

    def test_a_second_pass_still_records_which_unit_it_was(self):
        """Both halves come from the fix, not from the row, so a row that
        already holds the new unit can still say what it was rebased from."""
        row = self._row()
        row["unit"] = "m3"
        applied = self._apply(self.FIX, [row])[0]
        self.assertEqual(applied[UNIT_CONVERSION_KEY]["source_unit"], "kg")

    def test_a_unit_rewrite_that_states_no_factor_records_nothing(self):
        """Most unit fixes are corrections of a mistyped unit, where there is
        no conversion to state and nothing to publish."""
        fix = {k: v for k, v in self.FIX.items() if k != "conversion_factor"}
        row = self._apply(fix, [self._row()])[0]
        self.assertEqual(row["unit"], "m3")
        self.assertNotIn(UNIT_CONVERSION_KEY, row)

    def test_a_factor_on_a_field_that_is_not_a_unit_is_refused(self):
        """There is nothing for it to convert, so it would be inert."""
        with self.assertRaises(ValueError) as ctx:
            self._apply({"uuid": "u-1", "field": "name", "new_value": "x",
                         "original_value": "y", "conversion_factor": 2.0,
                         "comment": "wrong field"}, [self._row()])
        self.assertIn("conversion_factor", str(ctx.exception))

    def test_a_factor_without_the_original_unit_is_refused(self):
        """A factor is a statement about a pair, so the fix has to name both."""
        fix = {k: v for k, v in self.FIX.items() if k != "original_value"}
        with self.assertRaises(ValueError) as ctx:
            self._apply(fix, [self._row()])
        self.assertIn("original_value", str(ctx.exception))

    def test_a_factor_that_is_not_a_positive_number_is_refused(self):
        for value in (0, -1, "0.5", True, float("inf")):
            with self.subTest(factor=value):
                with self.assertRaises(ValueError):
                    self._apply({**self.FIX, "conversion_factor": value}, [self._row()])


if __name__ == "__main__":
    unittest.main()


def _alt_label_values(flow):
    return [
        entry.get("@value") if isinstance(entry, dict) else entry
        for entry in flow.get("altLabel", [])
    ]


class TheNameAFixReplacesStaysSearchableTestCase(unittest.TestCase):
    """A corrected name that was a real name is kept as an alternative label.

    ecoinvent and EF 3.1 both write `Silver-110` for what is measured as
    `Silver-110m`, and the correction is right (#24).  What it also does is
    delete the only string a consumer holding one of those inventories knows the
    substance by: the vendor's spelling is not published anywhere else, because
    `bootstrap_labels` moves `name` into `prefLabel` and clears the legacy
    `synonyms` field without reading it.

    Opt-in, because most of what these files rewrite is not a name -- see the
    refusal cases below.
    """

    def setUp(self):
        self.fix = {
            "match": {"name": "Silver-110"},
            "field": "name",
            "original_value": "Silver-110",
            "new_value": "Silver-110m",
            RETAIN_ORIGINAL_KEY: True,
            "comment": "Ag-110m is the isomer a reactor-effluent inventory reports.",
        }

    def _apply(self, flows, fix=None):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(tmp, [fix or self.fix])
            return apply_manual_fixes(flows, path, label="ecoinvent-3.12")

    def test_the_vendor_spelling_survives_the_rename(self):
        flows = [_flow("u1", "Silver-110", None, None)]
        self._apply(flows)
        self.assertEqual(flows[0]["name"], "Silver-110m")
        self.assertEqual(_alt_label_values(flows[0]), ["Silver-110"])

    def test_the_retained_label_carries_its_provenance(self):
        flows = [_flow("u1", "Silver-110", None, None)]
        self._apply(flows)
        entry = flows[0]["altLabel"][0]
        self.assertEqual(entry["@value"], "Silver-110")
        self.assertEqual(
            entry["source"]["prov:wasGeneratedBy"], "manual_fixes"
        )
        self.assertEqual(
            entry["source"]["prov:wasDerivedFrom"],
            "name the fix replaced, retained as altLabel",
        )

    def test_applying_twice_does_not_add_it_twice(self):
        flows = [_flow("u1", "Silver-110", None, None)]
        self._apply(flows)
        self._apply(flows)
        self.assertEqual(_alt_label_values(flows[0]), ["Silver-110"])

    def test_a_label_the_row_already_carries_is_not_repeated(self):
        flows = [_flow("u1", "Silver-110", None, None)]
        flows[0]["altLabel"] = [{"@value": "silver-110", "@language": "en"}]
        self._apply(flows)
        self.assertEqual(_alt_label_values(flows[0]), ["silver-110"])

    def test_labels_the_row_already_had_survive(self):
        flows = [_flow("u1", "Silver-110", None, None)]
        flows[0]["altLabel"] = [{"@value": "110Ag", "@language": "en"}]
        self._apply(flows)
        self.assertEqual(_alt_label_values(flows[0]), ["110Ag", "Silver-110"])


    def test_the_retained_label_survives_into_the_flow_record(self):
        """`altLabel` and not `synonyms`, and this is why it has to be.

        `bootstrap_labels` moves `name` into `prefLabel` and clears both legacy
        fields without reading them, so a spelling written to `synonyms` reaches
        the merge and is then thrown away.  `altLabel` is the one field on a
        source row that the record carries through untouched, which is what
        makes the label reach the published substance.
        """
        flows = [_flow("u1", "Silver-110", None, None)]
        self._apply(flows)
        record = _normalize_input_flow_record(flows[0])
        self.assertEqual(
            [entry["@value"] for entry in record["altLabel"]], ["Silver-110"]
        )

    def test_a_fix_that_does_not_ask_keeps_nothing(self):
        """The default, and it is the right one for most of these files.

        `Palladium-234m` corrected to `Protactinium-234m` names a different
        element, and the column-wrap repairs replace strings that are not words.
        Retaining those would publish a wrong name and a corrupted one as things
        the substance is called.
        """
        fix = dict(self.fix)
        del fix[RETAIN_ORIGINAL_KEY]
        flows = [_flow("u1", "Silver-110", None, None)]
        self._apply(flows, fix)
        self.assertEqual(flows[0]["name"], "Silver-110m")
        self.assertEqual(_alt_label_values(flows[0]), [])

    def test_a_fix_on_another_field_keeps_nothing(self):
        """The flag means one thing, and it is about the name.

        A CAS this project replaces is wrong, not a second identifier the
        substance also has, so there is nothing to retain and no field to
        retain it in.
        """
        fix = {
            "match": {"name": "Uranium-238"},
            "field": "cas_number",
            "new_value": "24678-82-8",
            RETAIN_ORIGINAL_KEY: True,
            "comment": "7440-61-1 is the element's number, not the nuclide's.",
        }
        flows = [{"uuid": "u1", "name": "Uranium-238", "cas_number": "7440-61-1"}]
        self._apply(flows, fix)
        self.assertEqual(flows[0]["cas_number"], "24678-82-8")
        self.assertEqual(_alt_label_values(flows[0]), [])

    def test_rows_the_stored_extraction_already_renamed_still_get_the_label(self):
        """The pass that renames is not the only pass that has to retain.

        The base list applies its fixes twice, once when `extract` writes the
        derived artifact and once when the transform reads it back (#237), and
        a flag added to a fix *after* the last extraction meets rows that
        already hold the new name.  The rename branch is then never reached, so
        the flag wrote nothing on that build or any later one -- `Silver-110`
        was missing from the published list for exactly that reason, which is
        what the flag exists to prevent.
        """
        flows = [_flow("u1", "Silver-110m", None, None)]
        self._apply(flows)
        self.assertEqual(flows[0]["name"], "Silver-110m")
        self.assertEqual(_alt_label_values(flows[0]), ["Silver-110"])

    def test_restoring_it_is_idempotent(self):
        flows = [_flow("u1", "Silver-110m", None, None)]
        self._apply(flows)
        self._apply(flows)
        self.assertEqual(_alt_label_values(flows[0]), ["Silver-110"])

    def test_an_already_renamed_row_gains_nothing_where_the_fix_does_not_ask(self):
        """The other half: the restoration follows the flag, not the branch."""
        fix = dict(self.fix)
        del fix[RETAIN_ORIGINAL_KEY]
        flows = [_flow("u1", "Silver-110m", None, None)]
        self._apply(flows, fix)
        self.assertEqual(_alt_label_values(flows[0]), [])

    def test_a_fix_that_fills_an_empty_name_retains_nothing(self):
        """There is no vendor spelling to keep where the row had none."""
        fix = dict(self.fix)
        fix["match"] = {"uuid": "u1"}
        del fix["original_value"]
        flows = [{"uuid": "u1", "name": ""}]
        self._apply(flows, fix)
        self.assertEqual(_alt_label_values(flows[0]), [])


class TheCheckedInSilverFixesAskForTheSpellingTestCase(unittest.TestCase):
    """Every list that corrects `Silver-110` keeps the vendor's spelling.

    Stated over the files rather than over one of them because the correction is
    made on all of them -- if the two lists disagreed about the name the merge
    would have to arbitrate -- and a flag added to one and forgotten on the
    others would publish the synonym for some source lists and not others.
    """

    def test_every_silver_110m_rename_retains_the_original(self):
        renames = []
        for path in sorted(PACKAGE_DATA_DIR.glob("*manual-fixes.json")):
            payload = orjson.loads(path.read_bytes())
            for fix in payload.get("fixes", []):
                if fix.get("field") != "name":
                    continue
                if str(fix.get("new_value", "")).strip().lower() != "silver-110m":
                    continue
                renames.append((path.name, fix))
        self.assertTrue(renames, "no Silver-110m rename found in the fixes files")
        for name, fix in renames:
            with self.subTest(file=name):
                self.assertTrue(fix.get(RETAIN_ORIGINAL_KEY), name)


class MCPAMethylIsNotAnIoxynilEsterTestCase(unittest.TestCase):
    """#46, asked of the five shipped ecoinvent files rather than of a fixture.

    ecoinvent ships this row named `Ioxynil methyl ester` while carrying
    2436-73-9, and the two name different molecules.  Every ioxynil is a
    diiodobenzonitrile; 2436-73-9 is C10H11ClO3 and has no iodine in it at all,
    being MCPA's methyl ester.  The project's decision is that the number is
    right and the name is wrong, so the fix is keyed on the number.

    Both halves of that keying need a test.  Every row carrying the number is
    renamed, and -- the half that matters -- no row of the ioxynil family is
    touched, because the wrong name contains the word `ioxynil` and a fix that
    read the word would reach three correctly named flows carrying three
    correct registry numbers.
    """

    CAS = "2436-73-9"
    OLD = "Ioxynil methyl ester"
    NEW = "MCPA-methyl"
    #: The family the fix must not reach: ecoinvent's other ioxynil flows, each
    #: correctly named and correctly registered.
    SIBLINGS = (
        ("Ioxynil", "1689-83-4"),
        ("Ioxynil octanoate", "3861-47-0"),
        ("Ioxynil sodium", "2961-62-8"),
    )

    def _paths(self):
        return [
            source.manual_fixes_path
            for source in known_source_lists().values()
            if source.list_name == "ecoinvent" and source.manual_fixes_path
        ]

    def _row(self, uuid, name, cas):
        return {
            "uuid": uuid,
            "name": name,
            "cas_number": cas,
            "context": ["soil", "agricultural"],
        }

    def _fixed(self, rows, path):
        apply_manual_fixes(rows, path, label=path.name)
        return rows

    def test_every_version_states_the_correction(self):
        """All five ship the row under the same UUIDs, so all five state it.

        A version that did not would hand the merge two lists disagreeing about
        what 2436-73-9 is called, which is what these files exist to prevent.
        """
        paths = self._paths()
        self.assertEqual(len(paths), 5)
        for path in paths:
            with self.subTest(file=path.name):
                fixes = orjson.loads(path.read_bytes())["fixes"]
                self.assertTrue(
                    any(
                        fix.get("field") == "name"
                        and fix.get("new_value") == self.NEW
                        and fix.get("match", {}).get("cas_number") == self.CAS
                        for fix in fixes
                    ),
                    f"{path.name} does not correct {self.CAS}",
                )

    def test_every_context_of_the_ester_is_renamed(self):
        """3.11 and 3.12 ship seven contexts; one statement reaches them all."""
        for path in self._paths():
            with self.subTest(file=path.name):
                rows = [
                    self._row(f"u-{index}", self.OLD, self.CAS) for index in range(7)
                ]
                self._fixed(rows, path)
                self.assertEqual([row["name"] for row in rows], [self.NEW] * 7)

    def test_the_ioxynil_family_keeps_its_names(self):
        """The half that stops this becoming a rule about a word."""
        for path in self._paths():
            for name, cas in self.SIBLINGS:
                with self.subTest(file=path.name, substance=name):
                    row = self._row("u-sibling", name, cas)
                    self._fixed([row], path)
                    self.assertEqual(row["name"], name)

    def test_the_replaced_name_is_not_kept_as_a_label(self):
        """`retain_original_as_synonym` asserts the replaced string is a name
        the substance genuinely has.  `Ioxynil methyl ester` is not one: it
        names a different substance, so republishing it as an alternative label
        would re-assert by name the confusion #46 is about, and would leave an
        ioxynil ester findable under a substance that is not one.
        """
        for path in self._paths():
            with self.subTest(file=path.name):
                row = self._row("u-label", self.OLD, self.CAS)
                self._fixed([row], path)
                self.assertNotIn("altLabel", row)

    def test_a_row_the_guard_does_not_recognise_is_left_alone(self):
        """`original_value` guards the rename, so the fix declines a row whose
        name it does not recognise rather than renaming it blind."""
        for path in self._paths():
            with self.subTest(file=path.name):
                row = self._row("u-respelt", "Ioxynil methylester", self.CAS)
                self._fixed([row], path)
                self.assertEqual(row["name"], "Ioxynil methylester")

    def test_applying_twice_changes_nothing_further(self):
        """The base list applies its fixes at extract and again on read (#237),
        and this fix matches on a field it does not write, so it matches both
        times."""
        for path in self._paths():
            with self.subTest(file=path.name):
                rows = [self._row("u-twice", self.OLD, self.CAS)]
                once = orjson.dumps(self._fixed(rows, path))
                self.assertEqual(orjson.dumps(self._fixed(rows, path)), once)


class TheCasQueueRulingsTestCase(unittest.TestCase):
    """#110, asked of the shipped EF 3.1 file rather than of a fixture.

    Three rulings taken off the `cas-ambiguous` queue, and they fail in three
    different ways, which is why each gets both halves tested.

    Borax carries a registry number that has been superseded, so the flow and
    ChEBI's record for the same mineral never meet.  The three `Formate` rows
    carry no identifier at all, so nothing published says what they are.  And
    the rows numbered as D-lactic acid are named for the parent term, which is
    the name of the racemate -- a substance this list already publishes
    separately, under the racemate's own number.

    The negative halves matter more than usual here.  All three substances have
    close neighbours in EF 3.1 that a slightly wider fix would reach: borax
    beside the anhydrous `disodium tetraborate`, `Formate` beside a dozen
    formate esters and salts, and the D acid beside the L acid and the mixture.
    """

    BORAX_SUPERSEDED = "12447-40-4"
    BORAX_CURRENT = "1303-96-4"
    FORMATE = "71-47-6"
    D_LACTIC = "10326-41-7"
    RACEMATE = "50-21-5"

    def _fixed(self, flows):
        apply_manual_fixes(flows, MANUAL_FIXES_FILEPATH, label="EF 3.1")
        return flows

    # -- borax ------------------------------------------------------------

    def test_borax_is_renumbered_to_the_current_registry_number(self):
        flow = _flow("u-borax", "borax", self.BORAX_SUPERSEDED, "")
        self._fixed([flow])
        self.assertEqual(flow["cas_numbers"], [self.BORAX_CURRENT])

    def test_the_anhydrous_tetraborate_keeps_its_own_number(self):
        """The half that stops this becoming a rule about a mineral family.

        `disodium tetraborate` is 1330-43-4 and is the salt without its ten
        waters -- a different substance with a different mass, which EF 3.1
        ships as its own thirteen rows.
        """
        flow = _flow("u-anhydrous", "disodium tetraborate", "1330-43-4", "215-540-4")
        self._fixed([flow])
        self.assertEqual(flow["cas_numbers"], ["1330-43-4"])

    def test_the_borate_rows_are_still_stripped_of_the_borax_number(self):
        """#106's fix and this one act on the same number in one file, and the
        order they are written in must not matter: `Borate` loses the number
        rather than being renumbered with borax.
        """
        flow = _flow("u-borate", "Borate", self.BORAX_SUPERSEDED, "")
        self._fixed([flow])
        self.assertEqual(flow["cas_numbers"], [])

    # -- formate ----------------------------------------------------------

    def test_the_formate_rows_are_given_the_anions_number(self):
        flow = _flow("u-formate", "Formate", "", "")
        self._fixed([flow])
        self.assertEqual(flow["cas_numbers"], [self.FORMATE])

    def test_a_formate_ester_or_salt_is_left_alone(self):
        """The half that stops this becoming a rule about a word.

        EF 3.1 ships more than a dozen rows whose name contains `formate`, and
        every one of them is a different substance with its own number.
        """
        for name, cas in (
            ("methyl formate", "107-31-3"),
            ("sodium formate", "141-53-7"),
            ("potassium formate", "590-29-4"),
            ("2-formyloxyethyl formate", "629-15-2"),
        ):
            with self.subTest(substance=name):
                flow = _flow("u-ester", name, cas, "")
                self._fixed([flow])
                self.assertEqual(flow["cas_numbers"], [cas])

    def test_a_formate_row_that_already_states_a_number_is_left_alone(self):
        """The fix supplies an identity to rows that have none; it must not
        overrule one a later release of EF states for itself."""
        flow = _flow("u-numbered", "Formate", "64-18-6", "")
        self._fixed([flow])
        self.assertEqual(flow["cas_numbers"], ["64-18-6"])

    # -- D-lactic acid ----------------------------------------------------

    def test_the_d_acid_is_renamed_for_its_stereochemistry(self):
        flow = _flow("u-d", "2-hydroxypropanoic acid", self.D_LACTIC, "233-713-2")
        self._fixed([flow])
        self.assertEqual(flow["name"], "D-Lactic acid")

    def test_the_racemate_and_the_l_acid_keep_their_names(self):
        """The half that keeps the three lactic acids three substances."""
        for name, cas in (
            ("lactic acid", self.RACEMATE),
            ("l-(+)-lactic acid", "79-33-4"),
        ):
            with self.subTest(substance=name):
                flow = _flow("u-other", name, cas, "")
                self._fixed([flow])
                self.assertEqual(flow["name"], name)

    def test_the_racemates_number_is_never_written_onto_the_d_rows(self):
        """What the queue proposed and this ruling refuses.  Stated as a test
        because it is the one outcome that would be silently wrong: 50-21-5 on
        these rows fuses them onto the mixture the list already publishes.
        """
        flow = _flow("u-d2", "2-hydroxypropanoic acid", self.D_LACTIC, "233-713-2")
        self._fixed([flow])
        self.assertEqual(flow["cas_numbers"], [self.D_LACTIC])

    def test_the_parent_term_is_not_kept_as_a_label(self):
        """`retain_original_as_synonym` asserts the replaced string is a name
        the substance genuinely has.  `2-hydroxypropanoic acid` is the name
        with the stereochemistry left unsaid, and both ChEBI records holding it
        -- `rac-lactic acid` and `2-hydroxypropanoic acid` -- carry the
        racemate's number.  Republishing it on the D acid would put the
        mixture's name on one enantiomer, next to the flow object that has the
        better claim to it.
        """
        flow = _flow("u-d3", "2-hydroxypropanoic acid", self.D_LACTIC, "233-713-2")
        self._fixed([flow])
        self.assertNotIn("altLabel", flow)

    # -- all three --------------------------------------------------------

    def test_applying_twice_changes_nothing_further(self):
        """The base list applies its fixes at extract and again on read (#237).

        The renumberings match on the name, and the rename matches on the name
        it replaces, so each is asked a second time about a row it has already
        changed and has to decline it quietly.
        """
        flows = [
            _flow("u-borax", "borax", self.BORAX_SUPERSEDED, ""),
            _flow("u-formate", "Formate", "", ""),
            _flow("u-d", "2-hydroxypropanoic acid", self.D_LACTIC, "233-713-2"),
        ]
        once = orjson.dumps(self._fixed(flows))
        self.assertEqual(orjson.dumps(self._fixed(flows)), once)


class CommonNamesGivenToChemicalRelativesTestCase(unittest.TestCase):
    """#119, asked of the shipped file rather than of a fixture.

    Six times, EF 3.1 puts a substance's ordinary name on a chemical relative
    of it -- the sodium salt instead of the acid, the chloride salt instead of
    the ion, the racemic mixture instead of the pure active half, anhydrite
    instead of gypsum -- while keeping the registry number of the relative it
    really shipped.  Four of the corrections are stated against that number,
    because it is the half of the row that is right and because EF spells the
    same name two ways.

    Both halves of each correction are checked, and the second half is the one
    worth a test.  The substance the name belongs to is in EF 3.1 too, in
    thirteen compartments, and a fix keyed on the *word* would rename it as
    well -- so paraquat, MCPA and mecoprop-P each get a row here carrying the
    other registry number, which must come through untouched.
    """

    #: The relative EF named after the substance, and what the correction calls
    #: it: registry number -> corrected name.  Mecoprop is not here: its number
    #: is corrected too, so its rename is keyed on the name instead and is
    #: checked by :class:`MecopropIsFiledUnderTheCurrentNumberTestCase`.
    RENAMED = {
        "1910-42-5": "Paraquat dichloride",
        "3653-48-3": "MCPA-sodium",
        "144740-54-5": "Flupyrsulfuron-methyl sodium",
        # The sixth: `1,3,5-triazine` on RDX, the trinitro derivative of the
        # hydrogenated ring, whose number, EC number, synonyms and USEtox
        # factors all say RDX (#199).
        "121-82-4": "RDX",
    }

    #: The substance whose name was being spent, with EF 3.1's own spelling for
    #: it.  Nothing here may be renamed.
    LEFT_ALONE = {
        "4685-14-7": "1,1'-dimethyl-4,4'-bipyridinium",
        "94-74-6": "2-methyl-4-chlorophenoxyacetic acid",
        "16484-77-8": "(R)-2-(4-chloro-2-methylphenoxy)propionic acid",
        # The real 1,3,5-triazine is on no EF 3.1 flow; Stepwise ships it, and a
        # row carrying its number must come through the RDX correction untouched.
        "290-87-9": "1,3,5-triazine",
    }

    #: EF 3.1's only resource-from-ground flow for the calcium sulfates.  Named
    #: `gypsum`, carrying anhydrite's 7778-18-9, and corrected by uuid because
    #: the same number is on thirteen `calcium sulfate` flows that are right.
    GYPSUM_UUID = "08a91e70-3ddc-11dd-97f8-0050c2490048"
    ANHYDROUS = "7778-18-9"

    def _fixed(self, flows):
        apply_manual_fixes(flows, MANUAL_FIXES_FILEPATH, label="EF 3.1")
        return flows

    def test_every_spelling_of_the_relative_is_renamed(self):
        """EF writes `MCPA` on eleven flows and `mcpa` on two, and
        `Flupyrsulfuron-methyl` on one and lower case on twelve.  A correction
        keyed on the number reaches both spellings with one statement."""
        for cas, corrected in self.RENAMED.items():
            with self.subTest(cas=cas):
                flows = [
                    _flow("u-upper", "Paraquat", cas, ""),
                    _flow("u-lower", "paraquat", cas, ""),
                ]
                self._fixed(flows)
                self.assertEqual([row["name"] for row in flows], [corrected] * 2)

    def test_the_substance_the_name_belongs_to_keeps_it(self):
        """The half that stops this growing into a rule about a word."""
        for cas, ef_name in self.LEFT_ALONE.items():
            with self.subTest(cas=cas):
                flow = _flow("u-parent", ef_name, cas, "")
                self._fixed([flow])
                self.assertEqual(flow["name"], ef_name)

    def test_the_replaced_names_are_not_kept_as_labels(self):
        """Each replaced string names a different substance that EF 3.1 also
        ships, so retaining it would republish the confusion as a synonym and
        leave a name-matching step landing exactly where it lands today."""
        for cas in self.RENAMED:
            with self.subTest(cas=cas):
                flow = _flow("u-1", "whatever EF called it", cas, "")
                self._fixed([flow])
                self.assertNotIn("altLabel", flow)

    def test_the_resource_flow_is_corrected_by_uuid(self):
        """7778-18-9 is on fourteen EF 3.1 flows: this one, named `gypsum`, and
        thirteen already named `calcium sulfate`.  Only this one is renamed."""
        wrong = _flow(self.GYPSUM_UUID, "gypsum", self.ANHYDROUS, "")
        right = _flow("u-emission", "calcium sulfate", self.ANHYDROUS, "231-900-3")
        self._fixed([wrong, right])
        self.assertEqual(wrong["name"], "Calcium sulfate")
        self.assertEqual(right["name"], "calcium sulfate")

    def test_the_hydrate_is_not_claimed_by_the_dry_salt(self):
        """`Gypsum` is the hydrate's name, 13397-24-5, and is not retained: it
        is what ecoinvent's and BAFU's gypsum rows look themselves up under."""
        flow = _flow(self.GYPSUM_UUID, "gypsum", self.ANHYDROUS, "")
        self._fixed([flow])
        self.assertNotIn("altLabel", flow)

    def test_applying_twice_changes_nothing_further(self):
        """The base list applies its fixes at extract and again on read (#237),
        and these match on fields they do not write, so they match both times."""
        flows = [_flow(f"u-{cas}", "paraquat", cas, "") for cas in self.RENAMED]
        flows.append(_flow(self.GYPSUM_UUID, "gypsum", self.ANHYDROUS, ""))
        once = orjson.dumps(self._fixed(flows))
        self.assertEqual(orjson.dumps(self._fixed(flows)), once)


class MecopropIsFiledUnderTheCurrentNumberTestCase(unittest.TestCase):
    """EF 3.1 files mecoprop under a superseded registry number (#119).

    The number in current use is 93-65-2.  Common Chemistry, asked for EF's
    7085-19-0, returns a record whose own registry number is 93-65-2, named
    `Mecoprop` -- the service resolving the older entry onto the current one
    rather than holding two substances -- and ChEBI files the molecule under
    93-65-2 as well.  ecoinvent and BAFU both already use the current number,
    so EF is the only list of the three holding the old one.

    Three corrections have to compose on one row, and the order and the
    criteria are the whole of what this checks.  The rename is keyed on the
    name it replaces, which is the one shape `apply_manual_fixes` recognises as
    already applied; the two number corrections are keyed on the *corrected*
    name and guarded by `original_value`.  The base list applies its fixes
    twice (#237), so a criterion that read a field being changed would report
    itself stale on every build.
    """

    EF_NAME = "mecoprop-p"
    SUPERSEDED = "7085-19-0"
    CURRENT = "93-65-2"
    SUPERSEDED_EC = "230-386-8"
    CURRENT_EC = "202-264-4"

    def _flow(self):
        return {
            "uuid": "1869f676-53ad-4251-a3a4-414dffc81380",
            "name": self.EF_NAME,
            "cas_numbers": [self.SUPERSEDED],
            "ec_numbers": [self.SUPERSEDED_EC],
        }

    def _apply(self, flows):
        apply_manual_fixes(flows, MANUAL_FIXES_FILEPATH, label="EF 3.1")
        return flows

    def test_the_three_corrections_compose_in_one_pass(self):
        flow = self._flow()
        self._apply([flow])
        self.assertEqual(flow["name"], "Mecoprop")
        self.assertEqual(flow["cas_numbers"], [self.CURRENT])
        self.assertEqual(flow["ec_numbers"], [self.CURRENT_EC])

    def test_the_row_says_which_numbers_ef_shipped(self):
        """This project has no structured slot for a superseded identifier, so
        the number EF published survives in the row's own comment or not at
        all.  An inventory written against EF 3.1 carries 7085-19-0."""
        flow = self._flow()
        self._apply([flow])
        comment = flow.get("general_comment") or ""
        self.assertIn(self.SUPERSEDED, comment)
        self.assertIn(self.SUPERSEDED_EC, comment)
        self.assertIn(self.CURRENT, comment)

    def test_a_second_pass_is_quiet(self):
        """The base list applies its fixes at extract and again when the
        transform reads the derived file back.  A stale-fix warning is the one
        signal a curator has, so these three must not spend it on themselves."""
        flows = [self._flow()]
        self._apply(flows)
        with capture_logs() as second_pass:
            self._apply(flows)
        # Scoped to these four entries by their criteria: every other fix in
        # the shipped file warns that it matched nothing, because this fixture
        # holds one flow rather than all 94,062.
        mine = ({"name": self.EF_NAME}, {"name": "Mecoprop"})
        complaints = [
            (entry["event"], entry.get("field"))
            for entry in second_pass
            if entry.get("criteria") in mine
            and entry["event"] in (
                "manual_fix_matched_nothing", "manual_fix_original_value_mismatch"
            )
        ]
        self.assertEqual(complaints, [])

    def test_applying_twice_changes_nothing_further(self):
        flows = [self._flow()]
        once = orjson.dumps(self._apply(flows))
        self.assertEqual(orjson.dumps(self._apply(flows)), once)

    def test_the_pure_enantiomer_is_untouched(self):
        """mecoprop-P is a different substance with its own thirteen flows, and
        the correction must not reach it: it is what the mixture was being
        confused with."""
        enantiomer = {
            "uuid": "11fa7c35-31ac-42d8-89b7-878646fdecd6",
            "name": "(R)-2-(4-chloro-2-methylphenoxy)propionic acid",
            "cas_numbers": ["16484-77-8"],
            "ec_numbers": ["240-539-0"],
        }
        before = orjson.dumps(enantiomer)
        self._apply([enantiomer])
        self.assertEqual(orjson.dumps(enantiomer), before)

    def test_a_row_already_holding_the_current_number_is_left_alone(self):
        """The `original_value` guard, asked the other way round: a future EF
        release that files mecoprop under 93-65-2 itself must not be rewritten
        by a correction that has nothing left to correct."""
        flow = self._flow()
        flow["cas_numbers"] = [self.CURRENT]
        flow["ec_numbers"] = [self.CURRENT_EC]
        self._apply([flow])
        self.assertEqual(flow["cas_numbers"], [self.CURRENT])
        self.assertEqual(flow["ec_numbers"], [self.CURRENT_EC])


class BafuAnhydriteSaysWhatItIsTestCase(unittest.TestCase):
    """BAFU ships anhydrite with no registry number at all (#119).

    Anhydrite is anhydrous calcium sulfate, 7778-18-9 -- the number Common
    Chemistry, ECHA, ecoinvent and EF 3.1 all use for it.  BAFU's row states
    none, so it matched nothing and minted a substance of its own while
    ecoinvent's anhydrite sat on EF's flow: one mineral, two lists, two
    published substances.

    Gypsum is deliberately *not* merged with it.  It is the dihydrate,
    13397-24-5, a different mineral with a different mass, and it gets a
    consensus flow of its own that both lists' gypsum rows reach.  The two
    cases are checked together here because the pair is the point: the same
    file makes one join and leaves the other apart, and a change that collapsed
    them would pass a test that only looked at anhydrite.
    """

    ANHYDROUS = "7778-18-9"
    GYPSUM = "13397-24-5"

    def _bafu(self):
        for key, source in known_source_lists().items():
            if source.list_name == "bafu":
                return key, source
        raise AssertionError("no BAFU source list registered")

    def _apply(self, flows):
        key, source = self._bafu()
        apply_manual_fixes(flows, source.manual_fixes_path, label=key)
        return flows

    def _row(self, name, **extra):
        return {
            "uuid": "e644328c-982a-597a-8459-d26bcad7cafa",
            "name": name,
            "context": ["resources", "in ground"],
            "unit": "kg",
            **extra,
        }

    def test_the_row_gains_the_number_it_ships_without(self):
        """The record has no `cas_numbers` key at all, which is why the guard
        is `null` and not `[]`: an empty list would be a mismatch, and the fix
        would warn and decline to apply."""
        flow = self._row("Anhydrite")
        self.assertNotIn("cas_numbers", flow)
        self._apply([flow])
        self.assertEqual(flow["cas_numbers"], [self.ANHYDROUS])

    def test_gypsum_is_left_under_its_own_number(self):
        """The half that says the two minerals stay apart.  A kilogram of
        gypsum is not a kilogram of anhydrite -- 172.172 g/mol against
        136.141 -- and nothing here converts between them."""
        flow = self._row("Gypsum", cas_numbers=[self.GYPSUM])
        self._apply([flow])
        self.assertEqual(flow["cas_numbers"], [self.GYPSUM])

    def test_a_release_that_states_its_own_number_is_not_overwritten(self):
        """`original_value` guards it: the correction is about a row that says
        nothing, not about one that says something else."""
        flow = self._row("Anhydrite", cas_numbers=["some-other-number"])
        with capture_logs() as logs:
            self._apply([flow])
        self.assertEqual(flow["cas_numbers"], ["some-other-number"])
        self.assertIn(
            "manual_fix_original_value_mismatch",
            [entry["event"] for entry in logs],
        )

    def test_applying_twice_changes_nothing_further(self):
        flows = [self._row("Anhydrite")]
        once = orjson.dumps(self._apply(flows))
        self.assertEqual(orjson.dumps(self._apply(flows)), once)


class GypsumIsNotCalciumAndNotSulfateTestCase(unittest.TestCase):
    """A word of a phrase is not a name of the thing (#119).

    ecoinvent ships `Gypsum` with one real synonym, `Calcium sulfate
    dihydrate`, and beside it that phrase's individual words as synonyms of
    their own: `calcium`, `sulfate` and `dihydrate` in 3.8, `sulfate` and
    `dihydrate` from 3.9.1 on.  A synonym is a name the merge looks a row up
    under, so each fragment is a way for gypsum to reach something it is not,
    and two of them name substances this list publishes.

    Both halves are checked, and the second is the point.  The phrase itself
    has to survive: it is what gypsum is, and it is the only one of the four
    strings that names it.  A fix keyed on the *word* `sulfate` appearing
    anywhere would take it too.
    """

    UUID = "11a2a7b1-ab2f-47b8-9e29-6f33d5207fa6"
    PHRASE = "Calcium sulfate dihydrate"

    #: What each release actually ships beside the phrase, read off the five
    #: extracted lists on 2026-08-20.  Spelled per release rather than as one
    #: set, because a correction that matched nothing would warn, and because
    #: the difference is the fact worth recording: 3.8 splits the phrase into
    #: all three of its words and every release after it drops the first.
    FRAGMENTS = {
        "ecoinvent-3.8": ("calcium", "sulfate", "dihydrate"),
        "ecoinvent-3.9.1": ("sulfate", "dihydrate"),
        "ecoinvent-3.10.1": ("sulfate", "dihydrate"),
        "ecoinvent-3.11": ("sulfate", "dihydrate"),
        "ecoinvent-3.12": ("sulfate", "dihydrate"),
    }

    def _sources(self):
        return {
            key: source
            for key, source in known_source_lists().items()
            if source.list_name == "ecoinvent"
        }

    def _fixed(self, key, source, synonyms):
        flow = {
            "uuid": self.UUID,
            "name": "Gypsum",
            "cas_number": "13397-24-5",
            "synonyms": list(synonyms),
        }
        apply_manual_fixes([flow], source.manual_fixes_path, label=key)
        return flow

    def test_every_version_takes_the_fragments_off(self):
        """Stated per release because the fixes files are per release, and a
        release that keeps a fragment is a release where the row can still be
        looked up under it."""
        for key, source in sorted(self._sources().items()):
            with self.subTest(key=key):
                shipped = self.FRAGMENTS[key]
                flow = self._fixed(key, source, [*shipped, self.PHRASE])
                self.assertEqual(flow["synonyms"], [self.PHRASE])

    def test_the_phrase_gypsum_actually_is_survives(self):
        """The half that stops this becoming a rule about a word."""
        for key, source in sorted(self._sources().items()):
            with self.subTest(key=key):
                flow = self._fixed(key, source, [self.PHRASE])
                self.assertEqual(flow["synonyms"], [self.PHRASE])

    def test_applying_twice_changes_nothing_further(self):
        for key, source in sorted(self._sources().items()):
            with self.subTest(key=key):
                flow = {
                    "uuid": self.UUID,
                    "name": "Gypsum",
                    "cas_number": "13397-24-5",
                    "synonyms": [*self.FRAGMENTS[key], self.PHRASE],
                }
                apply_manual_fixes([flow], source.manual_fixes_path, label=key)
                once = orjson.dumps(flow)
                apply_manual_fixes([flow], source.manual_fixes_path, label=key)
                self.assertEqual(orjson.dumps(flow), once)


class AgribalyseSpellingsReachTheirSubstancesTestCase(unittest.TestCase):
    """AGRIBALYSE spells substances the list already publishes (#187).

    Twenty-nine rows, six substances, one habit: the vendor writes the
    abbreviation first with the full name in parentheses, a mineral
    family-first, a bucket with a comma where EF writes parentheses -- or
    ships a shared English name without its registry number.  Every substance
    is published, with flows in the exact compartments the rows use, and the
    first five-list build minted duplicates beside all of them.  The fixes
    give each row what its siblings in other lists carry: the published name
    as a synonym the merge can read, or the substance's own number.
    """

    #: Vendor spelling -> the synonym the fix writes.
    SYNONYMS = {
        "COD (Chemical Oxygen Demand)": "Chemical Oxygen Demand",
        "COD (Chemical Oxygen Demand), FR": "Chemical Oxygen Demand",
        "BOD5 (Biological Oxygen Demand)": "Biological Oxygen Demand",
        "BOD5 (Biological Oxygen Demand), FR": "Biological Oxygen Demand",
        "BOD5 (Biological Oxygen Demand), CN": "Biological Oxygen Demand",
        "AOX, Adsorbable Organic Halogen": "Adsorbable Organic Halogen Compounds",
        "Clay, bentonite": "Bentonite",
        "Hydrocarbons, unspecified": "Hydrocarbons (unspecified)",
    }

    def _source(self):
        source = known_source_lists().get("agribalyse-3.2")
        if source is None:
            raise unittest.SkipTest("AGRIBALYSE 3.2 is not registered")
        return source

    def _row(self, name, **extra):
        return {
            "uuid": "cf8f4c7c-5059-5cbb-a8a4-88f4da128bb5",
            "name": name,
            "context": ["Emissions to water", "river"],
            "unit": "kg",
            **extra,
        }

    def test_each_spelling_gains_the_published_name_as_a_synonym(self):
        source = self._source()
        for vendor, published in sorted(self.SYNONYMS.items()):
            with self.subTest(vendor=vendor):
                flow = self._row(vendor)
                apply_manual_fixes(
                    [flow], source.manual_fixes_path, label=source.key, quiet=True
                )
                self.assertEqual(flow.get("synonyms"), [published])

    def test_silicon_tetrafluoride_gains_its_number(self):
        """The mechanism the other lists use: ecoinvent and BAFU ship the same
        English spelling with 7783-61-1 and reach EF's `Silicium
        Tetrafluoride` by it."""
        source = self._source()
        flow = self._row("Silicon tetrafluoride", context=["Emissions to air"])
        self.assertNotIn("cas_numbers", flow)
        apply_manual_fixes(
            [flow], source.manual_fixes_path, label=source.key, quiet=True
        )
        self.assertEqual(flow.get("cas_numbers"), ["7783-61-1"])

    def test_a_spelling_outside_the_family_stays_untouched(self):
        """The half that stops the fixes growing into a rule about words:
        `Clay, Unspecified` is also AGRIBALYSE's, one comma away from the
        bentonite row, and it is a different question (#190), not a synonym
        of Bentonite."""
        source = self._source()
        for name in ("Clay, Unspecified", "AOX, Adsorbable Organic Halogen As Cl"):
            with self.subTest(name=name):
                flow = self._row(name)
                apply_manual_fixes(
                    [flow], source.manual_fixes_path, label=source.key, quiet=True
                )
                self.assertNotIn("synonyms", flow)
                self.assertNotIn("cas_numbers", flow)

    def test_applying_twice_changes_nothing_further(self):
        source = self._source()
        flow = self._row("COD (Chemical Oxygen Demand)")
        apply_manual_fixes([flow], source.manual_fixes_path, label=source.key, quiet=True)
        once = orjson.dumps(flow)
        apply_manual_fixes([flow], source.manual_fixes_path, label=source.key, quiet=True)
        self.assertEqual(orjson.dumps(flow), once)


class AgribalyseSiblingNumbersTestCase(unittest.TestCase):
    """AGRIBALYSE ships a substance a sibling list reaches by number (#190).

    Thirty-seven rows on the first five-list build (1 September 2026,
    b0b8d76) minted a substance the list already publishes, and in every case
    another merged list ships the same name *with* the registry number that
    reaches it.  Three shapes: the number left off (`Benzovindiflupyr`,
    `Steatite`, the eight graded `in mixed ore` metals); a number nothing
    resolves (`Arsenic (V)` under 61805-96-7); and EF 3.1's own wrong number,
    corrected on EF's rows since #49 and still shipped by SimaPro's copy
    (`Vanadium (V)` under vanadium(2+)'s 15121-26-3).  One more row is EF's
    `Palladium-234m` typo, corrected the way EF's fix corrects it.
    """

    #: Vendor spelling -> the number the fix writes onto a row shipped bare.
    NUMBERS = {
        "Chromium (IV)": "15723-28-1",
        "Benzovindiflupyr": "1072957-71-1",
        "Zeta-cypermethrin": "52315-07-8",
        "Bicarbonate, ion": "71-52-3",
        "Phosphorus oxychloride": "10025-87-3",
        "Steatite": "14378-12-2",
        "Dioxins (TEQ)": "1746-01-6",
        "Cobalt, Co 5.0E-2%, in mixed ore": "7440-48-4",
        "Copper, Cu 6.8E-1%, in mixed ore": "7440-50-8",
        "Gold, Au 1.0E-7%, in mixed ore": "7440-57-5",
        "Nickel, Ni 2.5E+0%, in mixed ore": "7440-02-0",
        "Palladium, Pd 1.6E-6%, in mixed ore": "7440-05-3",
        "Platinum, Pt 4.7E-7%, in mixed ore": "7440-06-4",
        "Rhodium, Rh 1.6E-7%, in mixed ore": "7440-16-6",
        "Silver, Ag 1.8E-6%, in mixed ore": "7440-22-4",
    }

    #: Vendor spelling -> (the number the vendor wrote, the number it should be).
    REPLACED = {
        "Vanadium (V)": ("15121-26-3", "22537-31-1"),
        "Arsenic (V)": ("61805-96-7", "17428-41-0"),
        # The element's number on a name that states a charge (#198): the
        # rows reached bare lithium and potassium while ecoinvent's `Lithium
        # I` and `Potassium I` reached the ions.
        "Lithium (I)": ("7439-93-2", "17341-24-1"),
        "Potassium (I)": ("7440-09-7", "24203-36-9"),
    }

    #: Vendor spelling -> the element's number the fix takes off a generic ion
    #: name (#198): a name saying `Ion` without a charge is its own substance
    #: and no number names it, as ecoinvent's own 3.9.1 deletion says.
    REMOVED = {
        "Antimony, ion": "7440-36-0",
        "Chromium, ion": "7440-47-3",
        "Copper, ion": "7440-50-8",
        "Iron, ion": "7439-89-6",
        "Tin, ion": "7440-31-5",
        "Titanium, ion": "7440-32-6",
    }

    def _source(self):
        source = known_source_lists().get("agribalyse-3.2")
        if source is None:
            raise unittest.SkipTest("AGRIBALYSE 3.2 is not registered")
        return source

    def _apply(self, flow):
        source = self._source()
        apply_manual_fixes([flow], source.manual_fixes_path, label=source.key, quiet=True)
        return flow

    def _row(self, name, **extra):
        return {"uuid": "u-1", "name": name, "context": ["Emissions to water"], "unit": "kg", **extra}

    def test_each_bare_row_gains_the_number_its_sibling_carries(self):
        for vendor, number in sorted(self.NUMBERS.items()):
            with self.subTest(vendor=vendor):
                flow = self._apply(self._row(vendor))
                self.assertEqual(flow.get("cas_numbers"), [number])
                self.assertEqual(flow["name"], vendor)

    def test_a_wrong_number_is_replaced_and_the_vendor_s_recorded(self):
        for vendor, (wrong, right) in sorted(self.REPLACED.items()):
            with self.subTest(vendor=vendor):
                flow = self._apply(self._row(vendor, cas_numbers=[wrong]))
                self.assertEqual(flow["cas_numbers"], [right])

    def test_a_generic_ion_loses_the_elements_number(self):
        for vendor, element_cas in sorted(self.REMOVED.items()):
            with self.subTest(vendor=vendor):
                flow = self._apply(self._row(vendor, cas_numbers=[element_cas]))
                self.assertEqual(flow["cas_numbers"], [])
                self.assertEqual(flow["name"], vendor)

    def test_a_generic_ion_carrying_another_number_is_left_alone(self):
        """The deletion is pinned to the element's number: a generic ion row
        somebody has already given a different number is not this fix's."""
        for vendor in sorted(self.REMOVED):
            with self.subTest(vendor=vendor):
                flow = self._apply(self._row(vendor, cas_numbers=["1-2-3"]))
                self.assertEqual(flow["cas_numbers"], ["1-2-3"])

    def test_a_row_of_the_same_name_carrying_another_number_is_left_alone(self):
        """The guard on a replacement: the fix is pinned to the number the
        vendor wrote, so a row that already carries the right one -- or any
        other -- is not rewritten."""
        for vendor, (_wrong, right) in sorted(self.REPLACED.items()):
            with self.subTest(vendor=vendor):
                flow = self._apply(self._row(vendor, cas_numbers=[right]))
                self.assertEqual(flow["cas_numbers"], [right])

    def test_the_elements_own_rows_keep_their_own_numbers(self):
        """The other half of the metals: AGRIBALYSE's plain `Vanadium`,
        `Arsenic` and `Cobalt` rows carry the elements' numbers and are a
        different substance from the ion or the graded ore."""
        for name, number in (("Vanadium", "7440-62-2"), ("Arsenic", "7440-38-2"), ("Cobalt", "7440-48-4"),
                             ("Lithium", "7439-93-2"), ("Potassium", "7440-09-7"),
                             ("Antimony", "7440-36-0"), ("Chromium", "7440-47-3"), ("Copper", "7440-50-8"),
                             ("Iron", "7439-89-6"), ("Tin", "7440-31-5"), ("Titanium", "7440-32-6")):
            with self.subTest(name=name):
                flow = self._apply(self._row(name, cas_numbers=[number]))
                self.assertEqual(flow["cas_numbers"], [number])
                self.assertEqual(flow["name"], name)

    def test_the_unspecified_dioxin_row_is_not_read_as_a_toxic_equivalent(self):
        flow = self._apply(self._row("Dioxins (unspec.)"))
        self.assertNotIn("cas_numbers", flow)

    def test_palladium_234m_is_renamed_to_the_nuclide_it_misspells(self):
        flow = self._apply(self._row("Palladium-234m", context=["Emissions to soil"], unit="kBq"))
        self.assertEqual(flow["name"], "Protactinium-234m")
        self.assertNotIn("altLabel", flow)
        self.assertNotIn("synonyms", flow)

    def test_the_vendor_ships_every_row_this_is_about(self):
        """Each fix is keyed on a spelling the vendor actually wrote; a fix
        for a name the file does not carry corrects nothing and hides that it
        has drifted."""
        source = self._source()
        if not source.flows_path.exists():
            raise unittest.SkipTest("AGRIBALYSE 3.2 is not extracted here")
        shipped = {row["name"] for row in orjson.loads(source.flows_path.read_bytes())}
        for vendor in sorted({*self.NUMBERS, *self.REPLACED, *self.REMOVED, "Palladium-234m"}):
            with self.subTest(vendor=vendor):
                self.assertIn(vendor, shipped)
        pa = [row for row in orjson.loads(source.flows_path.read_bytes()) if row["name"] == "Palladium-234m"]
        self.assertEqual([row["uuid"] for row in pa], ["acb30f3b-3401-52c6-b8c7-1a923c65365d"])

    def test_applying_twice_changes_nothing_further(self):
        for vendor in ("Vanadium (V)", "Cobalt, Co 5.0E-2%, in mixed ore", "Palladium-234m"):
            with self.subTest(vendor=vendor):
                extra = {"cas_numbers": ["15121-26-3"]} if vendor == "Vanadium (V)" else {}
                flow = self._apply(self._row(vendor, **extra))
                once = orjson.dumps(flow)
                self._apply(flow)
                self.assertEqual(orjson.dumps(flow), once)


class AgribalysePublishedSynonymsTestCase(unittest.TestCase):
    """AGRIBALYSE spells a published substance one word away (#190).

    Four rows whose substance another list's row already made -- BAFU's
    `Metals, unspecified`, ecoinvent's two `Discarded fish, ..., to ocean`
    buckets, EF's `Calcium Sulfate` -- under a spelling the substance does not
    answer to.  The fix is the one #187 used: the published name as a synonym
    the merge reads and `bootstrap_labels` purges.
    """

    SYNONYMS = {
        "Metals (unspecified)": "Metals, unspecified",
        "Discarded fish, demersal": "Discarded fish, demersal, to ocean",
        "Discarded fish, pelagic": "Discarded fish, pelagic, to ocean",
    }

    def _source(self):
        source = known_source_lists().get("agribalyse-3.2")
        if source is None:
            raise unittest.SkipTest("AGRIBALYSE 3.2 is not registered")
        return source

    def _apply(self, flow):
        source = self._source()
        apply_manual_fixes([flow], source.manual_fixes_path, label=source.key, quiet=True)
        return flow

    def _row(self, name, **extra):
        return {"uuid": "u-1", "name": name, "context": ["Emissions to water"], "unit": "kg", **extra}

    def test_each_spelling_gains_the_published_name_as_a_synonym(self):
        for vendor, published in sorted(self.SYNONYMS.items()):
            with self.subTest(vendor=vendor):
                flow = self._apply(self._row(vendor))
                self.assertEqual(flow.get("synonyms"), [published])
                self.assertNotIn("cas_numbers", flow)

    def test_anhydrite_gains_the_compound_s_name_and_keeps_the_mineral_s_number(self):
        flow = self._apply(self._row("Anhydrite", context=["Resources", "in ground"], cas_numbers=["14798-04-0"]))
        self.assertEqual(flow["synonyms"], ["Calcium sulfate"])
        self.assertEqual(flow["cas_numbers"], ["14798-04-0"])

    def test_an_anhydrite_row_under_another_number_is_left_alone(self):
        """Pinned to the mineral's number: a row carrying anything else is a
        different claim and is not read as the compound on its name."""
        flow = self._apply(self._row("Anhydrite", cas_numbers=["7778-18-9"]))
        self.assertNotIn("synonyms", flow)

    def test_the_fish_the_vendor_still_has_in_the_sea_is_not_bycatch(self):
        """AGRIBALYSE also ships `Fish, demersal, in ocean` -- the resource,
        not the discard -- one word away again, and it is a different flow
        the list publishes separately."""
        for name in ("Fish, demersal, in ocean", "Fish, pelagic, in ocean", "Metals, unspecified"):
            with self.subTest(name=name):
                flow = self._apply(self._row(name))
                self.assertNotIn("synonyms", flow)

    def test_the_vendor_ships_every_row_this_is_about(self):
        source = self._source()
        if not source.flows_path.exists():
            raise unittest.SkipTest("AGRIBALYSE 3.2 is not extracted here")
        shipped = {row["name"] for row in orjson.loads(source.flows_path.read_bytes())}
        for vendor in sorted({*self.SYNONYMS, "Anhydrite"}):
            with self.subTest(vendor=vendor):
                self.assertIn(vendor, shipped)

    def test_applying_twice_changes_nothing_further(self):
        flow = self._apply(self._row("Discarded fish, pelagic"))
        once = orjson.dumps(flow)
        self._apply(flow)
        self.assertEqual(orjson.dumps(flow), once)


class AgribalyseTwiceShippedContextsTestCase(unittest.TestCase):
    """The compartment a row's own qualified twin uses wins (#368, #369).

    AGRIBALYSE ships seven substances twice -- once under a qualified
    compartment that lands correctly, once under a bare or wrong one -- and
    takes sulfur from water in 24 exchanges whose every amount is zero while
    taking it from the ground 2,182 times.  Each wrong copy is re-filed to
    the compartment its twin (or, for sulfur, its 2,182-use sibling) uses,
    the treatment `Peat` and `Energy, from wood` already got in this file.
    See agribalyse-land-and-sulfur-contexts.md.
    """

    #: uuid -> (vendor name, the compartment it is re-filed to)
    ROWS = {
        "359eb641-e485-56e1-9fbb-77a040545d51": ("Sulfur", ["Resources", "in ground"]),
        "c5af798d-f5b6-53b5-a551-545bb4c36a95": ("Carbon dioxide, in air", ["Resources", "in air"]),
        "bac7fc5d-dd32-5837-b62b-a4dcb72a14c1": ("Air", ["Resources", "in air"]),
        "39b6549b-bf36-5ccf-84fe-b96ca3a96dce": ("Oxygen", ["Resources", "in air"]),
        # The one of the eight with a unit written into the name; the fix is
        # keyed on the uuid, so it lands before the unit split reads the tail.
        "c8e821e3-5907-5ca0-96d1-d6a4670233eb": ("Wood, unspecified, standing/m3", ["Resources", "biotic"]),
        "bee24501-d997-503a-9eb2-28e5d84ddedb": ("Wood, soft, standing", ["Resources", "biotic"]),
        "98acbe41-6e69-5cb0-8f60-559aad3fb946": ("Fish, demersal, in ocean", ["Resources", "biotic"]),
        "77d55a91-e42c-50f1-8cac-3e2d9ad20c7d": ("Fish, pelagic, in ocean", ["Resources", "biotic"]),
    }

    def _source(self):
        source = known_source_lists().get("agribalyse-3.2")
        if source is None:
            raise unittest.SkipTest("AGRIBALYSE 3.2 is not registered")
        return source

    def _apply(self, flow):
        source = self._source()
        apply_manual_fixes([flow], source.manual_fixes_path, label=source.key, quiet=True)
        return flow

    def test_each_misfiled_copy_is_refiled_to_its_twins_compartment(self):
        for uuid, (name, context) in sorted(self.ROWS.items()):
            with self.subTest(name=name):
                flow = self._apply({"uuid": uuid, "name": name, "context": ["Resources"], "unit": "kg"})
                self.assertEqual(flow["context"], context)

    def test_the_qualified_twins_are_not_touched(self):
        """uuid-keyed on purpose: the vendor's correctly filed copies of the
        same names carry other uuids and keep their compartments."""
        for name, context in (
            ("Carbon dioxide, in air", ["Resources", "in air"]),
            ("Fish, demersal, in ocean", ["Resources", "biotic"]),
            ("Sulfur", ["Resources", "in ground"]),
        ):
            with self.subTest(name=name):
                flow = self._apply({"uuid": "u-other", "name": name, "context": list(context), "unit": "kg"})
                self.assertEqual(flow["context"], context)

    def test_the_vendor_ships_every_row_this_is_about(self):
        source = self._source()
        if not source.flows_path.exists():
            raise unittest.SkipTest("AGRIBALYSE 3.2 is not extracted here")
        shipped = {row["uuid"]: row["name"] for row in orjson.loads(source.flows_path.read_bytes())}
        for uuid, (name, _context) in sorted(self.ROWS.items()):
            with self.subTest(name=name):
                self.assertEqual(shipped.get(uuid), name)


class BetaCyfluthrinIsItsOwnSubstanceTestCase(unittest.TestCase):
    """The beta product separates from the mixture at the registry number (#188).

    Cyfluthrin, 68359-37-5, is the commercial mixture of eight isomers;
    beta-cyfluthrin is the product enriched in the two most active
    diastereoisomeric pairs, and PPDB gives it its own number, 1820573-27-0
    (record 74).  Every ecoinvent release ships its rows under the beta name
    with the mixture's number, so the merge folded them into the plain
    substance by CAS while AGRIBALYSE's number-less beta rows minted a
    number-less copy beside it.  The fix writes the product's own number on
    the beta rows in every release's file; a row that says plain Cyfluthrin
    is not touched, which is what keeps the correction from growing into a
    rule about the mixture.
    """

    MIXTURE = "68359-37-5"
    BETA = "1820573-27-0"

    def _release_fix_paths(self):
        paths = sorted(PACKAGE_DATA_DIR.glob("ecoinvent-*-manual-fixes.json"))
        self.assertEqual(len(paths), 5, paths)
        return paths

    def test_every_release_carries_the_same_correction(self):
        for path in self._release_fix_paths():
            with self.subTest(file=path.name):
                fixes = [
                    f for f in orjson.loads(path.read_bytes())["fixes"]
                    if f.get("match", {}).get("name") == "Beta-cyfluthrin"
                ]
                self.assertEqual(len(fixes), 1)
                fix = fixes[0]
                self.assertEqual(fix["field"], "cas_number")
                self.assertEqual(fix["original_value"], self.MIXTURE)
                self.assertEqual(fix["new_value"], self.BETA)
                self.assertTrue(str(fix.get("comment") or "").strip())

    def test_a_beta_row_takes_the_products_own_number(self):
        for path in self._release_fix_paths():
            with self.subTest(file=path.name):
                flow = {"uuid": "u-1", "name": "Beta-cyfluthrin",
                        "cas_number": self.MIXTURE}
                apply_manual_fixes([flow], path, label="ecoinvent")
                self.assertEqual(flow["cas_number"], self.BETA)

    def test_a_plain_cyfluthrin_row_keeps_the_mixtures_number(self):
        for path in self._release_fix_paths():
            with self.subTest(file=path.name):
                flow = {"uuid": "u-2", "name": "Cyfluthrin",
                        "cas_number": self.MIXTURE}
                apply_manual_fixes([flow], path, label="ecoinvent")
                self.assertEqual(flow["cas_number"], self.MIXTURE)

    def test_the_merged_releases_load_the_corrected_number(self):
        """The whole route, not just the table: `load_flows` applies the fix."""
        for key in ("ecoinvent-3.12", "ecoinvent-3.8"):
            source = known_source_lists()[key]
            if not source.flows_path.exists():
                raise unittest.SkipTest(f"{key} has not been fetched here")
            with self.subTest(list=key):
                rows = [
                    r for r in source.load_flows()
                    if "cyfluthrin" in (r.name or "").lower()
                ]
                self.assertTrue(rows)
                for row in rows:
                    self.assertEqual(row.name, "Beta-cyfluthrin")
                    self.assertEqual(list(row.cas_numbers), [self.BETA])


class EcoinventStatesTheElementOnTwoIonsTestCase(unittest.TestCase):
    """ecoinvent writes the element's number on two names that state a charge
    (#198): `Strontium II` under 7440-24-6 and `Caesium I` under 7440-46-2, the
    slip `Molybdenum VI` made in 3.10.1 (#181).  Every other Roman-numeral
    metal in the release carries the ion's number.  The ruling is that the
    name is the vendor's statement of what the flow is, so the three releases
    that state the charge correct the number.  3.8 and 3.9.1 name the same
    uuids bare and are left alone: a bare name is the element, and their rows
    follow 3.12's corrected identity through the canonical-identities file.
    """

    RELEASES = ("ecoinvent-3.10.1", "ecoinvent-3.11", "ecoinvent-3.12")

    #: Vendor name -> (the element's number ecoinvent wrote, the ion's number).
    REPLACED = {
        "Strontium II": ("7440-24-6", "22537-39-9"),
        "Caesium I": ("7440-46-2", "18459-37-5"),
    }

    def _apply(self, key, flow):
        source = known_source_lists().get(key)
        if source is None:
            raise unittest.SkipTest(f"{key} is not registered")
        apply_manual_fixes([flow], source.manual_fixes_path, label=key, quiet=True)
        return flow

    def _row(self, name, cas):
        return {"uuid": "u-1", "name": name, "context": ["water", "ocean"], "unit": "kg", "cas_number": cas}

    def test_each_release_that_states_the_charge_corrects_the_number(self):
        for key in self.RELEASES:
            for vendor, (wrong, right) in sorted(self.REPLACED.items()):
                with self.subTest(release=key, vendor=vendor):
                    self.assertEqual(self._apply(key, self._row(vendor, wrong))["cas_number"], right)

    def test_a_row_already_carrying_the_ions_number_is_left_alone(self):
        for key in self.RELEASES:
            for vendor, (_wrong, right) in sorted(self.REPLACED.items()):
                with self.subTest(release=key, vendor=vendor):
                    self.assertEqual(self._apply(key, self._row(vendor, right))["cas_number"], right)

    def test_the_bare_element_keeps_the_elements_number(self):
        """ecoinvent's `Strontium` and `Caesium` resource rows are the metals."""
        for key in self.RELEASES:
            for name, number in (("Strontium", "7440-24-6"), ("Caesium", "7440-46-2")):
                with self.subTest(release=key, name=name):
                    flow = self._apply(key, self._row(name, number))
                    self.assertEqual((flow["name"], flow["cas_number"]), (name, number))

    def test_the_releases_that_name_them_bare_have_no_such_fix(self):
        for key in ("ecoinvent-3.8", "ecoinvent-3.9.1"):
            for vendor, (wrong, _right) in sorted(self.REPLACED.items()):
                with self.subTest(release=key, vendor=vendor):
                    self.assertEqual(self._apply(key, self._row(vendor, wrong))["cas_number"], wrong)

    def test_the_canonical_identity_carries_the_corrected_number_to_the_bare_releases(self):
        """The 3.8 row for `abb7f444…` is `Strontium` under 7440-24-6; 3.12
        calls the uuid `Strontium II` and, corrected, numbers it 22537-39-9.
        The derived file is what carries that to 3.8."""
        from brightway_flows.merge.species import load_canonical_identities

        identities = load_canonical_identities()
        for uuid, expected in (
            ("abb7f444-e74a-46b5-a6a5-080a847cbbc5", ("Strontium II", "22537-39-9")),
            ("e189eb4e-0f6a-4054-aaf8-47df28c87ec4", ("Caesium I", "18459-37-5")),
        ):
            with self.subTest(uuid=uuid):
                identity = identities[uuid]
                self.assertEqual((identity.name, identity.cas_number), expected)
