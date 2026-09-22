"""The unit conversions ecoinvent's correspondence tables state, and where they go.

Nine ecoinvent flows do not mean, amount for amount, what the consensus flow
they map onto means.  Six are measured in a different quantity -- four fossil
carriers and uranium in mass or volume against an energy flow, and ocean water
in volume against a mass -- and without the factor a kilogram of hard coal is
characterised as if it were a megajoule, the 28x fossil-depletion underestimate
of #33.  Three are ore: `TiO2 ... in crude ore` in kilograms against EF 3.1's
elemental `titanium`, also in kilograms, where the units raise no objection at
all and 0.599 is titanium's share of the dioxide by mass.

It was thirteen until #80 and twelve until #111.  Coal-mine off-gas was the
seventh of the six: the tables sent it to EF 3.1's `natural gas` and paid 36 MJ
per standard cubic metre to do it, and it is not natural gas.  Pointed at EF's
own coal-mine flow, with every list's copy of that flow now in `sm3`, both sides
are the same substance measured the same way and there is nothing left to
convert.  The three that went at #111 are the obsolete land occupations, in m2
against an m2*a flow at a curated 1.0.  They are the only conversion this
project states across a *time* dimension and they still are -- what changed is
which side of the pair carries it.  Declining their mappings retired the fold
onto `arable` that made them a defect, and the assumed one-year duration moved
onto the manual fix that rebases the row's own unit from m2 to m2*a, where
`conversion_from_source_flow` reads it back.  A conversion disappearing from a
*table* is the shape a correct redirection takes, which is why the count is
pinned rather than the list alone.

Six properties are pinned here.

**Only what a unit table could not have said.**  A conversion is published only
where the stated factor is not the one `units.json` implies.  Litres to cubic
metres at 0.001 is exactly what the unit table says, so it is left there;
kilograms to megajoules has no entry to leave it to, and kilograms to kilograms
has one that says 1.0 and is wrong for an ore.

**Every version, not one.**  In the table era 3.9.1, 3.10.1 and 3.11 read
their tables from `randonneur_data` verbatim and 3.12 borrowed 3.11's, so they
had the quantity conversions all along; 3.8's composed table dropped the field,
so 3.8 published none.  The tables are retired (#141) and every conversion is
stated once, in `ecoinvent-match-overrides.json`, reaching every version from
there.  The sweep below is what keeps any from being lost again.

**The factor stays on the mapping.**  It is a statement about a pair, not about
either flow: 9.41 is not a fact about brown coal until it is 9.41 MJ per kg.  So
it is published on the `xkos:ConceptAssociation` and never as a property of a
consensus flow or a flow object, which is asserted against the record classes
rather than against one run's output.

**A redirected pair re-earns it.**  The merge can pair a source flow with a
target the table did not name.  The factor follows only if the units it was
stated between are still the units of the pair -- 36 MJ per standard cubic metre
is not 36 MJ per cubic metre, and ecoinvent changed natural gas from one to the
other at 3.9.  The same holds for a target rewritten in
`ecoinvent-match-overrides.json`, which is where a factor could survive its own
pair: the override drops whatever the table stated unless it states one itself,
so an inherited number cannot outlive the mapping it was about.

**What the merge accepts, the merge writes.**  The rule that admits a factor is
in one place, and the three write sites do not get a second opinion.  They used
to: each re-tested the number against 1.0, which is the blanket test the rule
replaced, so the three land occupations -- the only conversions whose factor
*is* 1.0 -- were computed correctly and then discarded on the way out.  #272.
The tests below drive the writers rather than the predicate, because a test on
the predicate alone passed throughout.  They drive them with a row written here
rather than one read off a curated table, because since #111 the 1.0 is stated
on a manual fix rather than on a table row, and the defect is about the writers
rather than about which file the row came from.
"""

import unittest
from dataclasses import fields
from unittest import mock

import orjson

from brightway_flows.domain.context_registry import context_for_iri
from brightway_flows.domain.elementary_flow import ElementaryFlow
from brightway_flows.domain.flow_object import FlowObject
from brightway_flows.domain.simple_flow import SimpleFlow
from brightway_flows.domain.vocabulary import (
    QUDT_CONVERSION_MULTIPLIER_CURIE,
    XKOS_SOURCE_CONCEPT_CURIE,
)
from brightway_flows.domain.units import unit_table_factor
from brightway_flows.merge.conversions import (
    UnitConversion,
    conversion_from_prepared_rows,
    crosses_a_time_dimension,
    states_more_than_the_unit_table,
)
from brightway_flows.merge.prepared_context_decisions import (
    PreparedContextDecision,
)
from brightway_flows.merge.rows import (
    _record_prepared_match,
    record_algorithmic_match,
)
from brightway_flows.merge.state import (
    MatchAttempt,
    MergeAccumulator,
    SourceRow,
)
from brightway_flows.sources import (
    PACKAGE_DATA_DIR,
    known_source_lists,
    load_prepared_match_table,
    resolve_source_list,
)

#: ecoinvent source flow uuid -> (factor, target uuid).  Stable from 3.8 to
#: 3.12, which is what lets one table of expectations cover every version.
CONVERSIONS = {
    "024c9722-1e88-412b-8c4b-10c532be8dca": (9.41, "fe0acd60-3ddc-11dd-a6f9-0050c2490048"),
    "b6d0042d-0ef8-49ed-9162-a07ff1ccf750": (18.01, "fe0acd60-3ddc-11dd-a6fc-0050c2490048"),
    "88d06db9-59a1-4719-9174-afeb1fa4026a": (43.4, "fe0acd60-3ddc-11dd-a6f8-0050c2490048"),
    "7c337428-fb1b-45c7-bbb2-2ee4d29e17ba": (36.0, "fe0acd60-3ddc-11dd-a6fa-0050c2490048"),
    "2ba5e39b-adb6-4767-a51d-90c1cf32fe98": (560000.0, "3e4d2966-6556-11dd-ad8b-0800200c9a66"),
    "629ffbca-ca71-4e4b-a006-ca9bdd9cd1df": (1025.0, "172a3db9-6556-11dd-ad8b-0800200c9a66"),
    # Ore to element, kg to kg: curated, because the route this project takes
    # states no factor and the route it does not take states 0.599.
    "78cd4852-e7b9-4301-adf7-51e730b0356a": (0.599, "2906898f-6556-11dd-ad8b-0800200c9a66"),
    "90a94ea5-bca4-483d-a591-2e886c0ff47f": (0.599, "2906898f-6556-11dd-ad8b-0800200c9a66"),
    "ec0fa5ce-51b4-4792-a8e8-c4ee668eddc3": (0.599, "2906898f-6556-11dd-ad8b-0800200c9a66"),
}

#: (ecoinvent source flow uuid, release) -> the factor that release converts
#: by, where it is not the default in :data:`CONVERSIONS`.  Two entries, both
#: 3.8's: ecoinvent revised crude oil's and natural gas's lower heating values
#: at 3.9 following Meili et al. (2021) and rebuilt the oil and gas datasets on
#: them, so 3.8's inventories were built on the older pair.  Read from
#: `LCIA Implementation v3.8.xlsx`, `energy resources: non-renewable`.  The
#: other seven carriers are the same number in all five workbooks. (#162)
CONVERSIONS_BY_RELEASE = {
    ("88d06db9-59a1-4719-9174-afeb1fa4026a", "3.8"): 42.3,
    ("7c337428-fb1b-45c7-bbb2-2ee4d29e17ba", "3.8"): 34.5,
}

#: BAFU source flow uuid -> (factor, target uuid).  BAFU carries the ore flow
#: in ecoinvent 3.8's old spelling under its own uuids, and the same 0.599
#: decision covers them -- stated in `bafu-2026-v1-match-overrides.json`,
#: because an override lives in the file of the list whose uuids it names.
#: They sat in the ecoinvent file until an independent review of #336 found
#: them inert there and the build minting a duplicate `Titanium Dioxide`.
BAFU_CONVERSIONS = {
    "52b760ca-3444-564a-a215-271d4af41250": (0.599, "2906898f-6556-11dd-ad8b-0800200c9a66"),
    "73746710-2506-50d1-811a-521b48526172": (0.599, "2906898f-6556-11dd-ad8b-0800200c9a66"),
}

#: The ore flows above, which ecoinvent replaced with elemental `Titanium` at
#: 3.10.1.  A version that does not ship a uuid leaves its row inert, because
#: the merge walks the source flows -- so 3.8 is the release these decide for,
#: and the override rows' own comments are where the reasoning reads back
#: (the composed 3.8 table that used to restate them went to git history,
#: #141's last follow-up).
ELEMENTAL_CONTENT = {
    "78cd4852-e7b9-4301-adf7-51e730b0356a",
    "90a94ea5-bca4-483d-a591-2e886c0ff47f",
    "ec0fa5ce-51b4-4792-a8e8-c4ee668eddc3",
}


def _source_uuid(row):
    side = row.get("source") or {}
    return str(side.get("uuid") or side.get("identifier") or "")


def _ecoinvent_keys():
    return sorted(
        source.key for source in known_source_lists().values()
        if source.list_name == "ecoinvent"
    )


class RespelledUnitTestCase(unittest.TestCase):
    """A factor stated for two spellings of one unit holds for each.

    ecoinvent registered natural gas in `m3` at 3.8 and `sm3` from 3.9.1
    without restating any amount.  A factor checked against only the newest
    spelling is silently dropped for the release shipping the older one --
    a structlog warning and nothing else -- which is how 3.8's gas row lost
    its 36.0 MJ in the first cut of #141, found by review on #336.
    """

    GAS = "7c337428-fb1b-45c7-bbb2-2ee4d29e17ba"

    def _gas_conversion(self, key):
        rows = load_prepared_match_table(resolve_source_list(key))
        row = next(r for r in rows if _source_uuid(r) == self.GAS)
        return conversion_from_prepared_rows([row])

    def test_the_factor_holds_for_both_spellings(self):
        conversion = self._gas_conversion("ecoinvent-3.8")
        self.assertIsNotNone(conversion)
        for spelling in ("m3", "sm3"):
            with self.subTest(spelling=spelling):
                self.assertTrue(
                    conversion.holds_between(
                        source_unit=spelling, target_unit="MJ"
                    )
                )

    def test_the_factor_still_refuses_a_unit_it_was_not_stated_for(self):
        # The half that stops the list form growing into "any unit at all":
        # a spelling is a name for the same quantity, not a licence.
        conversion = self._gas_conversion("ecoinvent-3.8")
        self.assertFalse(
            conversion.holds_between(source_unit="kg", target_unit="MJ")
        )
        self.assertFalse(
            conversion.holds_between(source_unit="m3", target_unit="kg")
        )

    def test_a_single_spelling_row_is_unchanged(self):
        # Brown coal states one spelling, as every row did before this field
        # existed; the ordinary case must read exactly as it always has.
        rows = load_prepared_match_table(resolve_source_list("ecoinvent-3.8"))
        row = next(
            r
            for r in rows
            if _source_uuid(r) == "024c9722-1e88-412b-8c4b-10c532be8dca"
        )
        self.assertNotIn("unit_alternates", row["source"])
        conversion = conversion_from_prepared_rows([row])
        self.assertTrue(
            conversion.holds_between(source_unit="kg", target_unit="MJ")
        )
        self.assertFalse(
            conversion.holds_between(source_unit="m3", target_unit="MJ")
        )


class EveryVersionTestCase(unittest.TestCase):
    def test_five_versions_are_registered(self):
        """The sweeps below are only a sweep if every version is in them."""
        self.assertEqual(len(_ecoinvent_keys()), 5)

    def test_every_version_converts_the_same_flows_to_the_same_targets(self):
        """Through the merge's own predicate, not a hand-rolled filter: what a
        run publishes is what `conversion_from_prepared_rows` returns.

        Nine since #141: the tables that used to carry the six energy-content
        factors are retired and the factors live on this project's own rows,
        beside the three ore spellings.

        *Which* flows convert and *where they go* is the same in every release,
        because both are identity: a uuid names one flow in all of them. How
        much a unit of one is worth is not, which is the next test."""
        for key in _ecoinvent_keys():
            converting = {
                _source_uuid(row): row
                for row in load_prepared_match_table(resolve_source_list(key))
                if conversion_from_prepared_rows([row]) is not None
            }
            with self.subTest(key=key):
                self.assertEqual(set(converting), set(CONVERSIONS))
            for source_uuid, (_, target_uuid) in CONVERSIONS.items():
                with self.subTest(key=key, flow=source_uuid):
                    row = converting[source_uuid]
                    self.assertEqual(str(row["target"].get("uuid") or ""), target_uuid)

    def test_each_version_converts_by_its_own_heating_value(self):
        """ecoinvent restated two of these numbers, so two releases disagree.

        Crude oil is 42.3 MJ/kg in ecoinvent 3.8 and 43.4 from 3.9.1 on; natural
        gas is 34.5 per cubic metre and then 36.0 per standard cubic metre.
        ecoinvent revised both at 3.9 following Meili et al. (2021) and rebuilt
        its oil and gas datasets on them, so converting a 3.8 inventory with the
        later number uses a heating value that release never had -- 2.6% high on
        oil and 4.3% on gas.

        The other seven are the same in all five, and read from the same place:
        every value here is the `energy resources: non-renewable` factor in that
        release's own `LCIA Implementation` workbook, where a characterisation
        factor on a kilogram flow under an indicator defined per megajoule is
        the energy content. (#162)
        """
        for key in _ecoinvent_keys():
            release = resolve_source_list(key).list_version
            converting = {
                _source_uuid(row): row
                for row in load_prepared_match_table(resolve_source_list(key))
                if conversion_from_prepared_rows([row]) is not None
            }
            for source_uuid, (factor, _) in CONVERSIONS.items():
                expected = CONVERSIONS_BY_RELEASE.get(
                    (source_uuid, release), factor
                )
                with self.subTest(key=key, flow=source_uuid):
                    self.assertEqual(
                        converting[source_uuid]["conversion_factor"], expected
                    )

    def test_every_converting_row_names_both_of_its_units(self):
        """A factor with only one side is a number nobody can check.

        The pair is what makes it meaningful, and the merge refuses to carry a
        conversion onto a redirected target without both -- so a table that
        states one is a table whose factors quietly stop travelling.
        """
        for key in _ecoinvent_keys():
            for row in load_prepared_match_table(resolve_source_list(key)):
                if not isinstance(row.get("conversion_factor"), (int, float)):
                    continue
                with self.subTest(key=key, flow=_source_uuid(row)):
                    self.assertTrue(str((row.get("source") or {}).get("unit") or ""))
                    self.assertTrue(str((row.get("target") or {}).get("unit_name") or ""))


    def test_bafu_states_its_own_ore_conversions(self):
        """The two BAFU spellings of the ore flow convert, in BAFU's own file.

        Same predicate as the ecoinvent sweep: what `conversion_from_prepared_rows`
        returns is what a run publishes, so a row that drifts out of
        `bafu-2026-v1-match-overrides.json` -- or back into a file BAFU never
        reads, which is where these two started -- fails here.
        """
        converting = {
            _source_uuid(row): row
            for row in load_prepared_match_table(
                resolve_source_list("bafu-2026-v1")
            )
            if conversion_from_prepared_rows([row]) is not None
        }
        # Containment, not equality: BAFU's file carries its own energy-content
        # rows too, and those have their own tests.  This one is about the two
        # ore rows being in the file BAFU actually reads.
        self.assertLessEqual(set(BAFU_CONVERSIONS), set(converting))
        for source_uuid, (factor, target_uuid) in BAFU_CONVERSIONS.items():
            with self.subTest(flow=source_uuid):
                row = converting[source_uuid]
                self.assertEqual(row["conversion_factor"], factor)
                self.assertEqual(
                    str(row["target"].get("uuid") or ""), target_uuid
                )


class AllowlistAgreementTestCase(unittest.TestCase):
    """Two files describe these pairs from opposite sides; they must agree.

    `unit-change-allowlist.json` says a dimensionally impossible mapping was
    reviewed and accepted; the conversion says by how much.  A pair with a
    factor and no allowlist entry would be published *and* reported as an
    unreviewed mismatch on the same run, which is two answers to one question.
    """

    def _allowlisted(self):
        payload = orjson.loads(
            (PACKAGE_DATA_DIR / "unit-change-allowlist.json").read_bytes()
        )
        return {
            str(row["source_uuid"]).strip(): row
            for row in payload["accepted"]
            if str(row.get("comment") or "").strip()
        }

    def test_every_conversion_across_units_is_allowlisted(self):
        """Not the elemental ones: their units agree, so the guard never fires
        and an entry asserting otherwise would describe nothing."""
        allowlisted = self._allowlisted()
        for row in load_prepared_match_table(resolve_source_list("ecoinvent-3.12")):
            conversion = conversion_from_prepared_rows([row])
            if conversion is None:
                continue
            if unit_table_factor(conversion.source_unit, conversion.target_unit) == 1.0:
                continue
            with self.subTest(flow=_source_uuid(row)):
                self.assertIn(_source_uuid(row), allowlisted)

    def test_an_allowlisted_pair_with_a_factor_says_so(self):
        """The entries used to argue no factor could be had. Now one can, and
        the reasoning has to say that rather than the opposite."""
        allowlisted = self._allowlisted()
        for row in load_prepared_match_table(resolve_source_list("ecoinvent-3.12")):
            conversion = conversion_from_prepared_rows([row])
            entry = allowlisted.get(_source_uuid(row))
            if conversion is None or entry is None:
                continue
            with self.subTest(flow=_source_uuid(row)):
                self.assertIn("qudt:conversionMultiplier", entry["comment"])


class NotOnTheFlowTestCase(unittest.TestCase):
    """The factor is pairwise, so no published record may carry one."""

    def test_no_record_class_has_a_conversion_field(self):
        for record in (SimpleFlow, ElementaryFlow, FlowObject):
            names = {f.name for f in fields(record)}
            aliases = set(getattr(record, "_ALIASES", {}).values())
            with self.subTest(record.__name__):
                self.assertNotIn("conversion_multiplier", names)
                self.assertNotIn("conversion_factor", names)
                self.assertNotIn(QUDT_CONVERSION_MULTIPLIER_CURIE, aliases)


class PairwiseTestCase(unittest.TestCase):
    def _conversion(self, **fields):
        row = {"factor": 9.41, "source_unit": "kg", "target_unit": "MJ"}
        row.update(fields)
        return UnitConversion(**row)

    def test_it_holds_for_the_units_it_was_stated_between(self):
        self.assertTrue(
            self._conversion().holds_between(source_unit="kg", target_unit="MJ")
        )

    def test_a_different_spelling_of_the_same_unit_still_holds(self):
        """Tables and flow records spell units in their own house style."""
        self.assertTrue(
            self._conversion().holds_between(source_unit="kilogram", target_unit="MJ")
        )

    def test_a_standard_cubic_metre_is_not_a_cubic_metre(self):
        """ecoinvent moved natural gas from m3 to Sm3 at 3.9, and 36 MJ per
        standard cubic metre is not 36 MJ per cubic metre."""
        conversion = self._conversion(factor=36.0, source_unit="Sm3")
        self.assertFalse(
            conversion.holds_between(source_unit="m3", target_unit="MJ")
        )

    def test_a_redirected_target_of_another_unit_does_not_hold(self):
        self.assertFalse(
            self._conversion().holds_between(source_unit="kg", target_unit="kg")
        )

    def test_a_factor_with_no_stated_target_unit_never_holds(self):
        """Unpaired, it cannot be checked, and unchecked it converts a mass
        into an energy by a number measured for something else."""
        conversion = self._conversion(target_unit="")
        self.assertFalse(
            conversion.holds_between(source_unit="kg", target_unit="MJ")
        )

    def test_a_factor_the_unit_table_already_states_does_not_hold(self):
        """`units.json` already carries litres to cubic metres on the unit."""
        conversion = self._conversion(factor=0.001, source_unit="l", target_unit="m3")
        self.assertFalse(
            conversion.holds_between(source_unit="l", target_unit="m3")
        )

    def test_an_elemental_content_between_identical_units_does_hold(self):
        """The units agree and the substances do not, which is the whole
        reason the factor has to be stated somewhere."""
        conversion = self._conversion(factor=0.599, source_unit="kg", target_unit="kg")
        self.assertTrue(
            conversion.holds_between(source_unit="kg", target_unit="kg")
        )


class UnitTableTestCase(unittest.TestCase):
    def test_it_knows_litres_from_cubic_metres(self):
        self.assertAlmostEqual(unit_table_factor("l", "m3"), 0.001)

    def test_it_knows_a_unit_against_itself(self):
        self.assertAlmostEqual(unit_table_factor("kg", "kg"), 1.0)

    def test_it_says_nothing_across_quantity_kinds(self):
        self.assertIsNone(unit_table_factor("kg", "MJ"))
        self.assertIsNone(unit_table_factor("m3", "kg"))

    def test_it_says_nothing_about_a_unit_it_does_not_carry(self):
        self.assertIsNone(unit_table_factor("bushels", "MJ"))

    def test_mass_to_energy_says_more(self):
        self.assertTrue(states_more_than_the_unit_table("kg", "MJ", 9.41))

    def test_an_elemental_share_says_more(self):
        """kg to kg is 1.0 in the unit table, and an ore is not its metal."""
        self.assertTrue(states_more_than_the_unit_table("kg", "kg", 0.599))

    def test_restating_the_unit_table_says_nothing(self):
        self.assertFalse(states_more_than_the_unit_table("l", "m3", 0.001))
        self.assertFalse(states_more_than_the_unit_table("kg", "kg", 1.0))

    def test_an_unknown_unit_is_published_rather_than_dropped(self):
        """Nothing downstream could have supplied it, so silence is not safe."""
        self.assertTrue(states_more_than_the_unit_table("bushels", "MJ", 9.41))

    def test_every_published_conversion_says_more_than_the_unit_table(self):
        """The nine are the nine for a reason."""
        for key in _ecoinvent_keys():
            for row in load_prepared_match_table(resolve_source_list(key)):
                conversion = conversion_from_prepared_rows([row])
                if conversion is None:
                    continue
                with self.subTest(key=key, flow=_source_uuid(row)):
                    self.assertTrue(states_more_than_the_unit_table(
                        conversion.source_unit,
                        conversion.target_unit,
                        conversion.factor,
                    ))


class SelectionTestCase(unittest.TestCase):
    def _row(self, **fields):
        row = {
            "source": {"uuid": "s-1", "unit": "kg"},
            "target": {"uuid": "t-1", "unit_name": "MJ"},
        }
        row.update(fields)
        return row

    def test_a_stated_factor_is_read_with_both_units(self):
        conversion = conversion_from_prepared_rows(
            [self._row(conversion_factor=9.41, comment="Net calorific value.")]
        )
        self.assertEqual(conversion.factor, 9.41)
        self.assertEqual(conversion.source_unit, "kg")
        self.assertEqual(conversion.target_unit, "MJ")
        self.assertEqual(conversion.comment, "Net calorific value.")

    def test_a_row_with_no_factor_yields_nothing(self):
        self.assertIsNone(conversion_from_prepared_rows([self._row()]))

    def test_a_factor_of_one_across_quantity_kinds_is_a_conversion(self):
        """"Is it 1.0?" is not the test; "does the unit table say it?" is.
        Nothing converts kilograms to megajoules, so 1.0 there is a claim."""
        conversion = conversion_from_prepared_rows(
            [self._row(conversion_factor=1.0)]
        )
        self.assertEqual(conversion.factor, 1.0)

    def test_a_boolean_is_not_a_factor(self):
        self.assertIsNone(
            conversion_from_prepared_rows([self._row(conversion_factor=True)])
        )

    def test_a_conversion_within_one_quantity_kind_is_not_published(self):
        """Downstream reads litres-to-cubic-metres off `units.json`."""
        self.assertIsNone(conversion_from_prepared_rows([self._row(
            source={"uuid": "s-1", "unit": "l"},
            target={"uuid": "t-1", "unit_name": "m3"},
            conversion_factor=0.001,
        )]))

    def _occupation(self, **fields):
        row = {
            "source": {"uuid": "s-1", "unit": "m2"},
            "target": {"uuid": "t-1", "unit_name": "m2*a"},
            "conversion_factor": 1.0,
        }
        row.update(fields)
        return row

    def test_a_time_crossing_factor_from_a_table_is_refused(self):
        """The tables state 1.0 for the obsolete occupation flows. Taking it
        would republish somebody else's assumed duration as a measurement."""
        self.assertIsNone(conversion_from_prepared_rows([self._occupation()]))

    def test_a_time_crossing_factor_from_an_override_is_taken(self):
        """Same number, asserted here instead of inherited."""
        conversion = conversion_from_prepared_rows(
            [self._occupation(route="override")]
        )
        self.assertEqual(conversion.factor, 1.0)
        self.assertEqual(conversion.source_unit, "m2")
        self.assertEqual(conversion.target_unit, "m2*a")

    def test_a_factor_of_one_within_a_quantity_kind_is_still_nothing(self):
        """`route` does not make a no-op meaningful: kg to kg at 1.0 is what
        the unit table already says, curated or not."""
        self.assertIsNone(conversion_from_prepared_rows([self._row(
            conversion_factor=1.0, route="override",
            source={"uuid": "s-1", "unit": "kg"},
            target={"uuid": "t-1", "unit_name": "kg"},
        )]))

    def test_a_crossing_row_later_in_the_list_is_still_found(self):
        """Skipping a same-kind row must not abandon the search."""
        conversion = conversion_from_prepared_rows([
            self._row(
                source={"uuid": "s-1", "unit": "l"},
                target={"uuid": "t-1", "unit_name": "m3"},
                conversion_factor=0.001,
            ),
            self._row(conversion_factor=9.41),
        ])
        self.assertEqual(conversion.factor, 9.41)


#: Two real context IRIs, one per fixture: what a resource in the ground is
#: taken from, and the land-occupation context the curated row targets.
IN_GROUND = "https://vocab.brightway.one/flow-contexts/reso-grou"
OCCUPATION = "https://vocab.brightway.one/flow-contexts/laus-occu"


class AlgorithmicRouteTestCase(unittest.TestCase):
    """A rejected target does not repeal the substance's calorific value."""

    def _record(self, *, conversion, target_unit):
        target_row = ElementaryFlow(
            elementary_flow_id="elem-1",
            flow_object_id="fo-1",
            source="EF 3.1",
            context=context_for_iri(IN_GROUND),
            context_iri=IN_GROUND,
            unit=target_unit,
            unit_iri="",
            lcia_methods=[],
            general_comment=None,
        )
        accumulator = MergeAccumulator()
        accumulator.by_elem_id["elem-1"] = target_row
        indexes = mock.Mock()
        indexes.source.list_name = "ecoinvent"
        indexes.source.list_version = "3.12"
        indexes.source.key = "ecoinvent-3.12"
        indexes.source.flow_iri_prefix = "https://example.invalid/flow/"
        indexes.mapping_file = "table"
        indexes.flow_object_label_by_id = {"fo-1": "Brown Coal"}
        record_algorithmic_match(
            row=SourceRow(
                uuid="s-1", name="Coal, brown", synonyms=[], labels=[],
                context=["natural resource", "in ground"], context_iri="",
                context_normalized=(), unit="kg", unit_iri="", cas="", ec="",
            ),
            match=MatchAttempt(
                flow_object_id="fo-1", candidates=[], selected=target_row,
                selector_reason="single-candidate", selector_details={},
                basis="label", basis_value="Coal, brown",
            ),
            indexes=indexes,
            accumulator=accumulator,
            conversion=conversion,
        )
        return target_row

    def test_the_factor_reaches_a_target_the_table_did_not_name(self):
        target_row = self._record(
            conversion=UnitConversion(9.41, "kg", "MJ"), target_unit="MJ"
        )
        association = target_row.concept_associations[0]
        self.assertEqual(association[QUDT_CONVERSION_MULTIPLIER_CURIE], 9.41)
        ref_metadata = target_row.source_refs[0]["source_metadata"]
        self.assertEqual(ref_metadata[QUDT_CONVERSION_MULTIPLIER_CURIE], 9.41)

    def test_it_is_dropped_when_the_new_pair_has_other_units(self):
        target_row = self._record(
            conversion=UnitConversion(9.41, "kg", "MJ"), target_unit="kg"
        )
        association = target_row.concept_associations[0]
        self.assertNotIn(QUDT_CONVERSION_MULTIPLIER_CURIE, association)
        self.assertNotIn(
            QUDT_CONVERSION_MULTIPLIER_CURIE,
            target_row.source_refs[0]["source_metadata"],
        )

    def test_the_pair_is_still_recorded_without_the_factor(self):
        """Dropping a conversion must not drop the mapping with it."""
        target_row = self._record(
            conversion=UnitConversion(9.41, "kg", "MJ"), target_unit="kg"
        )
        association = target_row.concept_associations[0]
        self.assertEqual(
            association[XKOS_SOURCE_CONCEPT_CURIE]["@id"],
            "https://example.invalid/flow/s-1",
        )

    def test_a_row_the_table_says_nothing_about_carries_no_factor(self):
        target_row = self._record(conversion=None, target_unit="MJ")
        self.assertNotIn(
            QUDT_CONVERSION_MULTIPLIER_CURIE, target_row.concept_associations[0]
        )


class ReachesTheExportTestCase(unittest.TestCase):
    """The conversion the merge accepted is the conversion it publishes.

    A factor of exactly 1.0 across a time dimension, through the same function a
    prepared match goes through, because the defect this pins was never in what
    the merge decided -- only in what it wrote down: three write sites each
    re-tested the number against 1.0 and threw away the one class of conversion
    the rule admits at that value (#272).

    Written here rather than read off a curated file, which is how it used to be
    driven.  The three obsolete land occupations were the only curated rows that
    stated 1.0, and #111 declined them -- so a test that insisted on a real row
    would now be a test of whether anybody had happened to add another.  What is
    under test is the writers, and a row is a row.
    """

    #: `arable`, EF 3.1's m2*a land-occupation flow: a real target, so the
    #: context and unit the writers see are the ones a run would give them.
    TARGET = "b88d3b6d-229e-477e-bce1-e16376f75c7b"
    #: `Occupation, arable, conservation tillage (obsolete)`, published in m2 --
    #: the flow the defect was found on, and still the honest example of a
    #: mapping that asserts a duration.
    SOURCE = "fdb1b2d0-f537-401e-b845-1d93da512174"
    COMMENT = "Assumed conversion: the occupation lasted one year."

    def _curated_row(self, source_uuid):
        """A prepared row of the shape an override produces, at 1.0."""
        return {
            "source": {
                "uuid": source_uuid,
                "name": "Occupation, arable, conservation tillage (obsolete)",
                "unit": "m2",
                "context": ["natural resource", "land"],
            },
            "target": {"uuid": self.TARGET, "name": "arable", "unit_name": "m2*a"},
            "conversion_factor": 1.0,
            "comment": self.COMMENT,
            "route": "override",
        }

    def _record(self, source_uuid):
        prepared_row = self._curated_row(source_uuid)
        target_row = ElementaryFlow(
            elementary_flow_id=self.TARGET,
            flow_object_id="fo-1",
            source="EF 3.1",
            context=context_for_iri(OCCUPATION),
            context_iri=OCCUPATION,
            unit="m2.a",
            unit_iri="",
            lcia_methods=[],
            general_comment=None,
        )
        accumulator = MergeAccumulator()
        indexes = mock.Mock()
        indexes.source.list_name = "ecoinvent"
        indexes.source.list_version = "3.12"
        indexes.source.key = "ecoinvent-3.12"
        indexes.source.flow_iri_prefix = "https://example.invalid/flow/"
        indexes.mapping_file = "table"
        indexes.flow_object_label_by_id = {"fo-1": "arable"}
        source = prepared_row["source"]
        _record_prepared_match(
            row=SourceRow(
                uuid=source_uuid, name=str(source["name"]), synonyms=[], labels=[],
                context=list(source["context"]), context_iri="",
                context_normalized=(), unit=str(source["unit"]), unit_iri="",
                cas="", ec="",
            ),
            prepared_rows=[prepared_row],
            target_row=target_row,
            target_uuid=self.TARGET,
            resolved_target_uuid=self.TARGET,
            target_resolution="direct",
            target_trace=[],
            decision_action=PreparedContextDecision.MAPPED,
            indexes=indexes,
            accumulator=accumulator,
        )
        return target_row, accumulator

    def test_the_merge_accepts_the_row_this_pins(self):
        """The fixture is a conversion the merge would carry, not a dict.

        Asked of the merge's own predicate rather than of the literal above,
        because a row this file writes and this file checks tests nothing: what
        makes the three tests below meaningful is that
        `conversion_from_prepared_rows` says yes to it, at exactly 1.0, across a
        time dimension.
        """
        conversion = conversion_from_prepared_rows([self._curated_row(self.SOURCE)])
        self.assertIsNotNone(conversion)
        self.assertEqual(conversion.factor, 1.0)
        self.assertEqual(conversion.source_unit, "m2")
        self.assertEqual(conversion.target_unit, "m2*a")

    def test_the_association_carries_the_multiplier(self):
        """Where a consumer reads it: without this the merged list states an
        m2 flow is an m2*a flow, and says nothing about the duration."""
        target_row, _ = self._record(self.SOURCE)
        association = target_row.concept_associations[0]
        self.assertEqual(association[QUDT_CONVERSION_MULTIPLIER_CURIE], 1.0)

    def test_the_source_ref_carries_the_multiplier(self):
        target_row, _ = self._record(self.SOURCE)
        metadata = target_row.source_refs[0]["source_metadata"]
        self.assertEqual(metadata[QUDT_CONVERSION_MULTIPLIER_CURIE], 1.0)

    def test_the_merge_report_carries_the_multiplier_and_its_reasoning(self):
        target_row, accumulator = self._record(self.SOURCE)
        match = accumulator.prepared_matches[0]
        self.assertEqual(match.conversion_factor, 1.0)
        self.assertIn("the occupation lasted one year", match.conversion_comment)

    def test_no_prepared_row_states_a_time_crossing_factor_today(self):
        """Why the fixture above is written here rather than read.

        The three obsolete land occupations were the only rows that ever stated
        one, and #111 declined their mappings; the duration they assert moved
        onto the manual fix that rebases their unit, which
        `conversion_from_source_flow` reads rather than this function. This is
        the assertion that says so: if a prepared row states one again, the tests
        above should be driven from it instead of from a literal.
        """
        for key in _ecoinvent_keys():
            for row in load_prepared_match_table(resolve_source_list(key)):
                conversion = conversion_from_prepared_rows([row])
                if conversion is None:
                    continue
                with self.subTest(key=key, flow=_source_uuid(row)):
                    self.assertFalse(crosses_a_time_dimension(
                        conversion.source_unit, conversion.target_unit
                    ))


if __name__ == "__main__":
    unittest.main()
