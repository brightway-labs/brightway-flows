"""The unit conversions a mapping publishes, and where each number comes from.

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
so 3.8 published none.  The tables are retired (#141) and the numbers are
stated once, reaching every version from one file.  Which file changed at
#407: the heating values, the density and the fission energy are in
`ecoinvent-property-statements.json`, each checked against the releases it
holds for and restated where a release measured differently, and the ore share
stays on its three rows of `ecoinvent-match-overrides.json`.  The sweep below
is what keeps any from being lost again.

**A statement is about the flow; a factor is about a pair.**  "One kilogram of
this brown coal is 9.41 MJ of calorific value" is something ecoinvent says
about its own flow, and since #407 it is kept as a property statement on that
flow, with its quantity, its unit, who said it and where (`domain.property_statements`).
9.41 is what a kilogram of it becomes on EF's `Brown Coal` in megajoules, and
that number is published on the `xkos:ConceptAssociation` and never as a
property of a consensus flow or a flow object -- asserted against the record
classes rather than against one run's output.  The merge derives the second
from the first when the pair's units bridge the statement
(`merge.conversions.conversion_to_publish`), publishes it with basis
`flow-property`, and names the quantity it came through.  An override row keeps
a `conversion_factor` only for a pair fact no property of the flow expresses:
the ore's share of its metal, mine gas from plain to standard cubic metres.

**A redirected pair re-earns it.**  The merge can pair a source flow with a
target the table did not name.  A curated factor follows only if the units it
was stated between are still the units of the pair, and a statement converts
only where its `per_unit` is the row's unit and its `unit` the target's -- 36
MJ per standard cubic metre is not 36 MJ per cubic metre, and ecoinvent changed
natural gas from one to the other at 3.9.  Which is also why the factor is
derived at the point of mapping rather than copied from a file: a statement
cannot outlive the unit it was made about.

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
from collections import defaultdict
from dataclasses import fields
from unittest import mock

import orjson

from brightway_flows.domain.common import Provenance
from brightway_flows.domain.context_registry import context_for_iri
from brightway_flows.domain.elementary_flow import ElementaryFlow
from brightway_flows.domain.flow_object import FlowObject
from brightway_flows.domain.property_statements import (
    ConversionRule,
    PropertyStatement,
    StatementOrigin,
    factor_between,
)
from brightway_flows.domain.simple_flow import SimpleFlow
from brightway_flows.domain.units import (
    CONVERSION_BASIS_KEY,
    CONVERSION_PROVENANCE_KEY,
    CONVERSION_QUANTITY_KEY,
    ConversionBasis,
    unit_table_factor,
)
from brightway_flows.domain.vocabulary import (
    QUANTITY_IRI_PREFIX,
    QUDT_CONVERSION_MULTIPLIER_CURIE,
    XKOS_SOURCE_CONCEPT_CURIE,
)
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
    _add_flow_in_missing_context,
    _record_prepared_match,
    record_algorithmic_match,
)
from brightway_flows.merge.state import (
    MatchAttempt,
    MergeAccumulator,
    SourceRow,
)
from brightway_flows.merge.unit_changes import (
    find_unit_mismatches,
    load_unit_change_allowlist,
)
from brightway_flows.sources import (
    PACKAGE_DATA_DIR,
    known_source_lists,
    load_prepared_match_table,
    resolve_source_list,
)
from brightway_flows.transformers.unit_normalization import build_units_index

#: ecoinvent source flow uuid -> (factor, target uuid).  Stable from 3.8 to
#: 3.12, which is what lets one table of expectations cover every version.
#: The oracle for both homes: six of these are read off a property statement
#: and three off an override row, and the number is the same whichever file
#: states it.
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

#: ecoinvent natural gas, the one flow whose vendor unit is a release's own.
GAS = "7c337428-fb1b-45c7-bbb2-2ee4d29e17ba"

#: The six flows whose factor is derived from a property statement -> (the
#: vendor's unit for the flow, the target's unit).  The pair a statement has
#: to bridge for the number in :data:`CONVERSIONS` to be the one published.
UNIT_PAIRS = {
    "024c9722-1e88-412b-8c4b-10c532be8dca": ("kg", "MJ"),
    "b6d0042d-0ef8-49ed-9162-a07ff1ccf750": ("kg", "MJ"),
    "88d06db9-59a1-4719-9174-afeb1fa4026a": ("kg", "MJ"),
    GAS: ("sm3", "MJ"),
    "2ba5e39b-adb6-4767-a51d-90c1cf32fe98": ("kg", "MJ"),
    "629ffbca-ca71-4e4b-a006-ca9bdd9cd1df": ("m3", "kg"),
}

#: (source flow uuid, release) -> the unit pair where a release ships the flow
#: in another unit.  One entry: 3.8 registers natural gas in plain cubic
#: metres, and 34.5 is per cubic metre.
UNIT_PAIRS_BY_RELEASE = {
    (GAS, "3.8"): ("m3", "MJ"),
}

#: The flows :data:`UNIT_PAIRS` names: the half of :data:`CONVERSIONS` whose
#: number is a fact about the flow.
PROPERTY_STATED = frozenset(UNIT_PAIRS)

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
#: #141's last follow-up).  The half of :data:`CONVERSIONS` whose number is a
#: fact about the pair, and so still on the override.
ELEMENTAL_CONTENT = {
    "78cd4852-e7b9-4301-adf7-51e730b0356a",
    "90a94ea5-bca4-483d-a591-2e886c0ff47f",
    "ec0fa5ce-51b4-4792-a8e8-c4ee668eddc3",
}

#: How many override rows #407 moved onto a statement, by list.  The count a
#: sweep over the statement files has to reach to be the sweep it claims.
MOVED_ROWS = {"ecoinvent": 6, "bafu": 11, "stepwise": 12, "agribalyse": 29}


def _source_uuid(row):
    side = row.get("source") or {}
    return str(side.get("uuid") or side.get("identifier") or "")


def _target_uuid(row):
    return str((row.get("target") or {}).get("uuid") or "")


def _ecoinvent_keys():
    return sorted(
        source.key for source in known_source_lists().values()
        if source.list_name == "ecoinvent"
    )


def _lists_with_statements():
    """Every registered list that has a property statements file, by key."""
    return sorted(
        (
            source for source in known_source_lists().values()
            if source.property_statements_path is not None
        ),
        key=lambda source: source.key,
    )


def _one_statement(loaded, source_uuid):
    """The one statement *loaded* makes about *source_uuid*."""
    (statement,) = loaded.statements[source_uuid]
    return statement


def _quantity_iri(slug):
    return f"{QUANTITY_IRI_PREFIX}{slug}"


class RespelledUnitTestCase(unittest.TestCase):
    """A measurement restated with its unit is read for the release that made it.

    ecoinvent registered natural gas in `m3` at 3.8 and `sm3` from 3.9.1, and
    restated the heating value in the same release: 34.5 MJ per cubic metre,
    then 36.0 per standard cubic metre.  Until #407 the override row carried
    one factor and a list of unit spellings it was said to hold for -- which is
    how 3.8's gas first lost its factor altogether (the first cut of #141,
    found by review on #336) and then was given a number its own workbook
    never stated.  The statement file says each release's own: `per_unit:
    sm3` for the default, and `by_release` putting 3.8 at 34.5 per `m3`.
    `load_property_statements` resolves one or the other for the release it
    is asked for and refuses nothing, because both are stated.
    """

    def _gas(self, key):
        loaded = resolve_source_list(key).load_property_statements()
        return _one_statement(loaded, GAS)

    def test_3_8_reads_its_own_value_per_cubic_metre(self):
        statement = self._gas("ecoinvent-3.8")
        self.assertEqual(
            (statement.value, statement.unit, statement.per_unit), (34.5, "MJ", "m3")
        )
        self.assertEqual(factor_between(statement, "m3", "MJ"), 34.5)

    def test_later_releases_read_the_standard_cubic_metre(self):
        statement = self._gas("ecoinvent-3.12")
        self.assertEqual(
            (statement.value, statement.unit, statement.per_unit), (36.0, "MJ", "sm3")
        )
        self.assertEqual(factor_between(statement, "sm3", "MJ"), 36.0)

    def test_a_standard_cubic_metre_is_not_a_cubic_metre(self):
        """`sm3` and `m3` are two quantity kinds in `units.json` (#292), so a
        statement per one answers nothing for a row in the other.  This is the
        half that stops the release form growing into "any spelling at all":
        3.8's row is in cubic metres and gets 3.8's number, and the 36.0 that
        was read per standard cubic metre never reaches it."""
        self.assertIsNone(factor_between(self._gas("ecoinvent-3.12"), "m3", "MJ"))
        self.assertIsNone(factor_between(self._gas("ecoinvent-3.8"), "sm3", "MJ"))

    def test_the_statement_still_refuses_a_unit_it_was_not_stated_for(self):
        # A heating value per cubic metre is not one per kilogram, and it does
        # not convert a volume into a mass either way round.
        statement = self._gas("ecoinvent-3.8")
        self.assertIsNone(factor_between(statement, "kg", "MJ"))
        self.assertIsNone(factor_between(statement, "m3", "kg"))

    def test_a_statement_with_no_release_entry_reads_the_same_in_every_release(self):
        # Brown coal states one number for all five releases, as every
        # statement did before `by_release` existed; the ordinary case must
        # read exactly as it always has.
        brown = {
            key: _one_statement(
                resolve_source_list(key).load_property_statements(),
                "024c9722-1e88-412b-8c4b-10c532be8dca",
            )
            for key in _ecoinvent_keys()
        }
        self.assertEqual(
            {(s.value, s.unit, s.per_unit) for s in brown.values()},
            {(9.41, "MJ", "kg")},
        )
        statement = brown["ecoinvent-3.8"]
        self.assertEqual(factor_between(statement, "kg", "MJ"), 9.41)
        self.assertIsNone(factor_between(statement, "m3", "MJ"))


class EveryVersionTestCase(unittest.TestCase):
    def test_five_versions_are_registered(self):
        """The sweeps below are only a sweep if every version is in them."""
        self.assertEqual(len(_ecoinvent_keys()), 5)

    def test_the_oracle_is_split_the_way_the_files_are(self):
        """Three on the override, six on a statement, and nothing in both."""
        self.assertEqual(ELEMENTAL_CONTENT | PROPERTY_STATED, set(CONVERSIONS))
        self.assertFalse(ELEMENTAL_CONTENT & PROPERTY_STATED)

    def test_every_version_converts_the_same_flows_to_the_same_targets(self):
        """Through the merge's own readers, not a hand-rolled filter: what a
        run publishes for a pair fact is what `conversion_from_prepared_rows`
        returns, and what it publishes for a property is what the list's
        statements file loads for that release.

        Nine since #141: the tables that used to carry the six energy-content
        factors are retired and the numbers live on this project's own rows.
        Six of those rows are statements since #407, and the three ore
        spellings are still override rows, because an ore's share of its metal
        is a fact about the pair.

        *Which* flows convert and *where they go* is the same in every release,
        because both are identity: a uuid names one flow in all of them, and
        the target is the override row's in both halves.  How much a unit of
        one is worth is not, which is the next test."""
        for key in _ecoinvent_keys():
            source = resolve_source_list(key)
            rows = {
                _source_uuid(row): row
                for row in load_prepared_match_table(source)
            }
            converting = {
                uuid for uuid, row in rows.items()
                if conversion_from_prepared_rows([row]) is not None
            }
            stated = set(source.load_property_statements().statements)
            with self.subTest(key=key):
                self.assertEqual(converting, ELEMENTAL_CONTENT)
                self.assertEqual(stated, PROPERTY_STATED)
            for source_uuid, (_, target_uuid) in CONVERSIONS.items():
                with self.subTest(key=key, flow=source_uuid):
                    self.assertEqual(_target_uuid(rows[source_uuid]), target_uuid)

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

        Compared with `==` and not to a tolerance: the number the file states
        is the number the mapping publishes, bit for bit, which is what
        `factor_between` promises for a statement written in the direction its
        mapping uses.  A tolerance here would let a rounding creep in unnoticed.
        """
        for key in _ecoinvent_keys():
            source = resolve_source_list(key)
            release = source.list_version
            loaded = source.load_property_statements()
            rows = {
                _source_uuid(row): row
                for row in load_prepared_match_table(source)
            }
            for source_uuid, (factor, _) in CONVERSIONS.items():
                expected = CONVERSIONS_BY_RELEASE.get((source_uuid, release), factor)
                with self.subTest(key=key, flow=source_uuid):
                    if source_uuid in ELEMENTAL_CONTENT:
                        self.assertEqual(
                            rows[source_uuid]["conversion_factor"], expected
                        )
                        continue
                    source_unit, target_unit = UNIT_PAIRS_BY_RELEASE.get(
                        (source_uuid, release), UNIT_PAIRS[source_uuid]
                    )
                    statement = _one_statement(loaded, source_uuid)
                    self.assertEqual(
                        factor_between(statement, source_unit, target_unit), expected
                    )

    def test_every_converting_row_names_both_of_its_units(self):
        """A factor with only one side is a number nobody can check.

        The pair is what makes it meaningful, and the merge refuses to carry a
        conversion onto a redirected target without both -- so a table that
        states one is a table whose factors quietly stop travelling.  A
        statement names both by construction (`unit` and `per_unit` are
        required fields), so this is about the rows that still state a factor.
        """
        for key in _ecoinvent_keys():
            for row in load_prepared_match_table(resolve_source_list(key)):
                if not isinstance(row.get("conversion_factor"), (int, float)):
                    continue
                with self.subTest(key=key, flow=_source_uuid(row)):
                    self.assertTrue(str((row.get("source") or {}).get("unit") or ""))
                    self.assertTrue(str((row.get("target") or {}).get("unit_name") or ""))

    def test_a_moved_row_keeps_no_factor_on_its_override(self):
        """One number, one home.

        The 58 rows #407 moved kept their override -- it is what names the
        target -- and lost their `conversion_factor`.  A row that grew one back
        would be a second copy of the statement, able to disagree with it; the
        loader refuses that only where the row also names its units, so the
        file is read here as well.
        """
        for source in _lists_with_statements():
            stated = source.load_property_statements().statements
            for row in load_prepared_match_table(source):
                if _source_uuid(row) not in stated:
                    continue
                with self.subTest(key=source.key, flow=_source_uuid(row)):
                    self.assertNotIn("conversion_factor", row)

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
        # Equality since #407: BAFU's energy-content rows are statements now,
        # so the two ore rows are the only pair facts BAFU's override states.
        self.assertEqual(set(BAFU_CONVERSIONS), set(converting))
        for source_uuid, (factor, target_uuid) in BAFU_CONVERSIONS.items():
            with self.subTest(flow=source_uuid):
                row = converting[source_uuid]
                self.assertEqual(row["conversion_factor"], factor)
                self.assertEqual(_target_uuid(row), target_uuid)


class AllowlistAgreementTestCase(unittest.TestCase):
    """Two files describe these pairs from opposite sides; they must agree.

    `unit-change-allowlist.json` says a dimensionally impossible mapping was
    reviewed and accepted, between which two units; the statement says by how
    much, between which two units.  A pair with a factor and no allowlist entry
    would be published *and* reported as an unreviewed mismatch on the same
    run, which is two answers to one question; an entry whose units are not
    the statement's would be a review of a pair that is not the one published.

    Swept over every list's statements file rather than over the rows that
    state a factor, because since #407 the rows that state a factor are the
    ore rows, whose units agree and which the allowlist has no business with.
    A sweep that read only those would pass over an empty set.  The target of
    a statement's pair is read off the list's own override row, which every
    stated flow has.
    """

    def _allowlisted(self):
        """The allowlist's rows by pair, with the units each was reviewed between."""
        payload = orjson.loads(
            (PACKAGE_DATA_DIR / "unit-change-allowlist.json").read_bytes()
        )
        return {
            (
                str(row["source_uuid"]).strip(),
                str(row["target_elementary_flow_id"]).strip(),
            ): row
            for row in payload["accepted"]
            if str(row.get("comment") or "").strip()
        }

    def _statement_pairs(self, source):
        """(source uuid, statement, target uuid) for every statement *source* makes.

        One per target the list's override names for the flow.  A statement
        whose flow has no override row yields nothing, and the first test
        below is what says that never happens.
        """
        loaded = source.load_property_statements()
        targets = defaultdict(list)
        for row in load_prepared_match_table(source):
            if _source_uuid(row) in loaded.statements:
                targets[_source_uuid(row)].append(_target_uuid(row))
        return [
            (source_uuid, statement, target_uuid)
            for source_uuid, statements in loaded.statements.items()
            for statement in statements
            for target_uuid in targets[source_uuid]
        ]

    def test_every_stated_flow_has_an_override_naming_its_target(self):
        """What makes the sweep a sweep: a statement is about a flow, and the
        pair it converts is only known once the override says where the flow
        goes.  The count is the 58 rows #407 moved, by list, so that a file
        losing its rows reads as a loss rather than as fewer things to check."""
        moved = defaultdict(set)
        for source in _lists_with_statements():
            loaded = source.load_property_statements()
            pairs = self._statement_pairs(source)
            with self.subTest(key=source.key):
                self.assertEqual(
                    {uuid for uuid, _, _ in pairs}, set(loaded.statements)
                )
            for source_uuid, _, target_uuid in pairs:
                moved[source.list_name].add((source_uuid, target_uuid))
        self.assertEqual({name: len(pairs) for name, pairs in moved.items()}, MOVED_ROWS)

    def test_every_conversion_across_units_is_allowlisted(self):
        """Every statement's pair is on the allowlist, between the statement's
        own units.

        Not the elemental ones: their units agree, so the guard never fires
        and an entry asserting otherwise would describe nothing.  ecoinvent's
        natural gas is the one flow whose vendor unit is a release's own, so
        its entry may name either of the units its statement is per across the
        releases; every other statement is per one unit, and the entry names
        that one.
        """
        allowed = load_unit_change_allowlist()
        entries = self._allowlisted()
        per_units = defaultdict(set)
        pairs = []
        for source in _lists_with_statements():
            for source_uuid, statement, target_uuid in self._statement_pairs(source):
                per_units[(source.list_name, source_uuid)].add(statement.per_unit)
                pairs.append((source, source_uuid, statement, target_uuid))
        self.assertTrue(pairs)
        for source, source_uuid, statement, target_uuid in pairs:
            with self.subTest(key=source.key, flow=source_uuid):
                self.assertIn((source_uuid, target_uuid), allowed)
                entry = entries[(source_uuid, target_uuid)]
                self.assertIn(
                    str(entry["source_unit"]),
                    per_units[(source.list_name, source_uuid)],
                )
                self.assertEqual(str(entry["target_unit"]), statement.unit)

    def test_every_pair_fact_across_units_is_allowlisted(self):
        """The other home: a factor an override still states between two
        units of different kinds -- AGRIBALYSE's coal-mine off-gas by the
        kilogram onto a flow in standard cubic metres -- is a reviewed crossing
        too.  The ore rows are skipped by the same rule as before: kilograms to
        kilograms is 1.0 in the unit table and raises no mismatch to review."""
        allowed = load_unit_change_allowlist()
        checked = 0
        for source in _lists_with_statements():
            for row in load_prepared_match_table(source):
                conversion = conversion_from_prepared_rows([row])
                if conversion is None:
                    continue
                if unit_table_factor(conversion.source_unit, conversion.target_unit) == 1.0:
                    continue
                checked += 1
                with self.subTest(key=source.key, flow=_source_uuid(row)):
                    self.assertIn((_source_uuid(row), _target_uuid(row)), allowed)
        # The three coal-mine off-gas rows of `agribalyse-3.2-match-overrides.json`.
        self.assertEqual(checked, 3)

    def test_an_allowlisted_pair_with_a_factor_says_so(self):
        """The entries used to argue no factor could be had. Now one can, and
        the reasoning has to say that rather than the opposite.

        ecoinvent's six, as it always was: these are the entries written when
        the tables still carried the factor and rewritten when #141 moved it,
        so each names `qudt:conversionMultiplier` as where the number now
        lives.  Read for one release, because the six statements and their
        override rows are the same file for all five."""
        entries = self._allowlisted()
        pairs = self._statement_pairs(resolve_source_list("ecoinvent-3.12"))
        self.assertEqual(len(pairs), MOVED_ROWS["ecoinvent"])
        for source_uuid, _, target_uuid in pairs:
            with self.subTest(flow=source_uuid):
                self.assertIn(
                    "qudt:conversionMultiplier",
                    entries[(source_uuid, target_uuid)]["comment"],
                )


class NotOnTheFlowTestCase(unittest.TestCase):
    """The factor is pairwise, so no published record may carry one.

    A statement is a fact about the flow and a factor a fact about a pair,
    and this test guards the second: `Flow.property_statements` is the first,
    and a `conversion_multiplier` on a consensus flow would be a pair's number
    with one side missing.
    """

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
        """The nine are the nine for a reason, whichever file states them.

        For a pair fact, the units and the factor the override row states;
        for a statement, the number read in the direction it is written -- so
        much `unit` per one `per_unit` -- which is also what the loader
        refuses when it is a unit-table fact with a second home.
        """
        for source in _lists_with_statements():
            for row in load_prepared_match_table(source):
                conversion = conversion_from_prepared_rows([row])
                if conversion is None:
                    continue
                with self.subTest(key=source.key, flow=_source_uuid(row)):
                    self.assertTrue(states_more_than_the_unit_table(
                        conversion.source_unit,
                        conversion.target_unit,
                        conversion.factor,
                    ))
            loaded = source.load_property_statements()
            for source_uuid, statements in loaded.statements.items():
                for statement in statements:
                    with self.subTest(
                        key=source.key, flow=source_uuid, quantity=statement.quantity
                    ):
                        self.assertTrue(states_more_than_the_unit_table(
                            statement.per_unit, statement.unit, statement.value
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


def _statement(
    quantity="calorific-value", value=9.41, unit="MJ", per_unit="kg",
    comment="Brown coal's energy content, read off the workbook.",
):
    """A statement of the shape `load_property_statements` builds."""
    return PropertyStatement(
        quantity=quantity,
        value=value,
        unit=unit,
        per_unit=per_unit,
        stated_by=StatementOrigin.CURATED,
        provenance=Provenance(
            was_generated_by="property_statements",
            was_attributed_to="brightway-flows",
            had_primary_source=["ecoinvent's EF 3.1 LCIA Implementation workbook"],
            was_derived_from="ecoinvent-property-statements.json",
        ),
        comment=comment,
    )


class FlowPropertyRouteTestCase(unittest.TestCase):
    """A row with no curated factor converts by what its list states about it.

    The route #407 added, driven through `record_algorithmic_match` the way
    `AlgorithmicRouteTestCase` drives the curated one.  The row arrives in the
    vendor's kilograms carrying its statements, the target is in megajoules,
    and what the mapping publishes is the statement's own number with basis
    `flow-property` and the quantity it came through.  The cases below are the
    order `conversion_to_publish` resolves in -- curated factor, statement,
    unit table -- and the two refusals that keep a statement from converting
    the wrong thing: a unit it was not made about, and a quantity the target
    does not measure.
    """

    def _record(
        self, *, statements, unit="kg", target_unit="MJ", conversion=None,
        reference_quantities=None, rules=(),
    ):
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
        indexes.source.merge_activity = "merge_ecoinvent"
        indexes.source.flow_iri_prefix = "https://example.invalid/flow/"
        indexes.source.match_overrides_path = (
            PACKAGE_DATA_DIR / "ecoinvent-match-overrides.json"
        )
        indexes.source.property_statements_path = (
            PACKAGE_DATA_DIR / "ecoinvent-property-statements.json"
        )
        indexes.mapping_file = "table"
        indexes.flow_object_label_by_id = {"fo-1": "Brown Coal"}
        indexes.reference_quantities = dict(reference_quantities or {})
        indexes.conversion_rules = tuple(rules)
        record_algorithmic_match(
            row=SourceRow(
                uuid="s-1", name="Coal, brown", synonyms=[], labels=[],
                context=["natural resource", "in ground"], context_iri="",
                context_normalized=(), unit=unit, unit_iri="", cas="", ec="",
                property_statements=tuple(statements),
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
        return target_row, accumulator

    def _mismatches(self, accumulator):
        """What `find_unit_mismatches` makes of the match, with nothing allowlisted."""
        return find_unit_mismatches(
            accumulator.algorithm_matches, units_index=build_units_index(), allowed=set()
        )

    def test_the_statement_is_the_published_multiplier(self):
        target_row, accumulator = self._record(statements=[_statement()])
        association = target_row.concept_associations[0]
        self.assertEqual(association[QUDT_CONVERSION_MULTIPLIER_CURIE], 9.41)
        self.assertEqual(association[CONVERSION_BASIS_KEY], ConversionBasis.FLOW_PROPERTY)
        metadata = target_row.source_refs[0]["source_metadata"]
        self.assertEqual(metadata[QUDT_CONVERSION_MULTIPLIER_CURIE], 9.41)
        self.assertEqual(metadata[CONVERSION_BASIS_KEY], ConversionBasis.FLOW_PROPERTY)
        (match,) = accumulator.algorithm_matches
        self.assertEqual(match.conversion_factor, 9.41)
        self.assertEqual(
            match.conversion_comment, "Brown coal's energy content, read off the workbook."
        )

    def test_the_mapping_names_the_quantity_it_came_through(self):
        """The fourth key a `flow-property` mapping carries, as the quantity's
        IRI: how a reader tells a gross value landing on a net flow from a net
        one.  With nothing in `reference_quantities`, a target in megajoules
        is a calorific value of unstated basis, and the statement is too."""
        target_row, _ = self._record(statements=[_statement()])
        metadata = target_row.source_refs[0]["source_metadata"]
        self.assertEqual(
            metadata[CONVERSION_QUANTITY_KEY],
            "https://vocab.brightway.one/quantity/calorific-value",
        )
        self.assertEqual(
            target_row.concept_associations[0][CONVERSION_QUANTITY_KEY],
            _quantity_iri("calorific-value"),
        )

    def test_the_provenance_names_the_file_and_the_statements_source(self):
        """Where the number came from is published beside it: the list's
        statements file, and what the statement itself cites."""
        target_row, _ = self._record(statements=[_statement()])
        metadata = target_row.source_refs[0]["source_metadata"]
        provenance = Provenance.from_dict(metadata[CONVERSION_PROVENANCE_KEY])
        self.assertEqual(provenance.was_derived_from, "ecoinvent-property-statements.json")
        self.assertIn("ecoinvent-property-statements.json", provenance.had_primary_source)
        self.assertIn(
            "ecoinvent's EF 3.1 LCIA Implementation workbook", provenance.had_primary_source
        )

    def test_a_converted_pair_is_not_a_unit_mismatch(self):
        """What `find_unit_mismatches` reads is the factor on the match, so a
        kilogram row converted onto a megajoule flow is no longer reported as
        a crossing nobody reviewed (#417)."""
        _, accumulator = self._record(statements=[_statement()])
        self.assertEqual(self._mismatches(accumulator), set())

    def test_a_curated_factor_that_holds_comes_first(self):
        """A pair fact outranks a flow fact.  Where an override states a
        factor between the pair's units it is the curator's decision about
        this pair, and the statement is not consulted."""
        target_row, _ = self._record(
            statements=[_statement()],
            conversion=UnitConversion(9.5, "kg", "MJ", basis=ConversionBasis.CURATED),
        )
        metadata = target_row.source_refs[0]["source_metadata"]
        self.assertEqual(metadata[QUDT_CONVERSION_MULTIPLIER_CURIE], 9.5)
        self.assertEqual(metadata[CONVERSION_BASIS_KEY], ConversionBasis.CURATED)
        self.assertNotIn(CONVERSION_QUANTITY_KEY, metadata)
        association = target_row.concept_associations[0]
        self.assertEqual(association[QUDT_CONVERSION_MULTIPLIER_CURIE], 9.5)
        self.assertEqual(association[CONVERSION_BASIS_KEY], ConversionBasis.CURATED)

    def test_a_curated_factor_that_no_longer_holds_yields_to_the_statement(self):
        """The ore share was stated kilograms to kilograms; on a pair that is
        kilograms to megajoules it says nothing, and the statement does."""
        target_row, _ = self._record(
            statements=[_statement()],
            conversion=UnitConversion(0.599, "kg", "kg", basis=ConversionBasis.CURATED),
        )
        metadata = target_row.source_refs[0]["source_metadata"]
        self.assertEqual(metadata[QUDT_CONVERSION_MULTIPLIER_CURIE], 9.41)
        self.assertEqual(metadata[CONVERSION_BASIS_KEY], ConversionBasis.FLOW_PROPERTY)

    def test_a_statement_per_standard_cubic_metre_converts_no_cubic_metre_row(self):
        """36 MJ per standard cubic metre is not 36 MJ per cubic metre (#292).

        The statement does not bridge the pair, the unit table has nothing
        between a volume and an energy, so the mapping carries no factor and
        the match is what it was before #407: a crossing for the allowlist to
        answer for, or `has_unit_mismatch` to report.
        """
        target_row, accumulator = self._record(
            statements=[_statement(quantity="net-calorific-value", value=36.0, per_unit="sm3")],
            unit="m3",
        )
        metadata = target_row.source_refs[0]["source_metadata"]
        self.assertNotIn(QUDT_CONVERSION_MULTIPLIER_CURIE, metadata)
        self.assertNotIn(CONVERSION_QUANTITY_KEY, metadata)
        self.assertNotIn(
            QUDT_CONVERSION_MULTIPLIER_CURIE, target_row.concept_associations[0]
        )
        (match,) = accumulator.algorithm_matches
        self.assertIsNone(match.conversion_factor)
        self.assertEqual(self._mismatches(accumulator), {"s-1"})

    def test_a_net_target_takes_the_net_statement_over_the_gross(self):
        """AGRIBALYSE states both heating values for one coal.  The target's
        reference quantity -- `Hard Coal` is net calorific value, by EF's own
        flow property -- is what picks, and the mapping says which it took."""
        target_row, _ = self._record(
            statements=[
                _statement(quantity="gross-calorific-value", value=19.1),
                _statement(quantity="net-calorific-value", value=18.2),
            ],
            reference_quantities={"elem-1": "net-calorific-value"},
        )
        metadata = target_row.source_refs[0]["source_metadata"]
        self.assertEqual(metadata[QUDT_CONVERSION_MULTIPLIER_CURIE], 18.2)
        self.assertEqual(
            metadata[CONVERSION_QUANTITY_KEY], _quantity_iri("net-calorific-value")
        )

    def test_a_gross_statement_converts_onto_a_net_target_only_by_a_rule(self):
        """Stepwise states gross values and its method counts them.  A gross
        value onto a net flow is a decision a person wrote down, in the list's
        `conversion_rules`; without the rule the pair converts by nothing, and
        with it the mapping publishes that it converted by the gross value."""
        gross = _statement(quantity="gross-calorific-value", value=19.1)
        net_target = {"elem-1": "net-calorific-value"}
        target_row, accumulator = self._record(
            statements=[gross], reference_quantities=net_target
        )
        self.assertNotIn(
            QUDT_CONVERSION_MULTIPLIER_CURIE, target_row.source_refs[0]["source_metadata"]
        )
        self.assertEqual(self._mismatches(accumulator), {"s-1"})

        rule = ConversionRule(
            onto="net-calorific-value",
            convert_by="gross-calorific-value",
            comment="Stepwise 2006 accounts its energy carriers by gross calorific value.",
        )
        target_row, accumulator = self._record(
            statements=[gross], reference_quantities=net_target, rules=[rule]
        )
        metadata = target_row.source_refs[0]["source_metadata"]
        self.assertEqual(metadata[QUDT_CONVERSION_MULTIPLIER_CURIE], 19.1)
        self.assertEqual(metadata[CONVERSION_BASIS_KEY], ConversionBasis.FLOW_PROPERTY)
        self.assertEqual(
            metadata[CONVERSION_QUANTITY_KEY], _quantity_iri("gross-calorific-value")
        )
        self.assertEqual(self._mismatches(accumulator), set())

    def test_a_fission_energy_never_converts_onto_a_calorific_value(self):
        """560,000 MJ per kilogram of uranium is not a heat of combustion.  A
        target in megajoules that nobody has said more about is a calorific
        value of unstated basis, and the fission energy does not convert onto
        it; it converts only onto a target ruled `fission-energy`, which is
        what the base list's statements file says of EF's `Uranium`."""
        fission = _statement(quantity="fission-energy", value=560000.0)
        target_row, _ = self._record(statements=[fission])
        self.assertNotIn(
            QUDT_CONVERSION_MULTIPLIER_CURIE, target_row.source_refs[0]["source_metadata"]
        )

        target_row, _ = self._record(
            statements=[fission], reference_quantities={"elem-1": "fission-energy"}
        )
        metadata = target_row.source_refs[0]["source_metadata"]
        self.assertEqual(metadata[QUDT_CONVERSION_MULTIPLIER_CURIE], 560000.0)
        self.assertEqual(metadata[CONVERSION_QUANTITY_KEY], _quantity_iri("fission-energy"))


class NewContextRouteMixin:
    """Drives `_add_flow_in_missing_context` for one row of one list.

    `_create` returns the flow the row minted and the accumulator it went
    into, so a test can read the mapping off the flow and the match record off
    the accumulator.
    """

    RIVER = "https://vocab.brightway.one/flow-contexts/envi-wate-rive"
    LIST_NAME: str
    LIST_VERSION: str
    SUBSTANCE: str

    def _create(self, *, conversion, unit):
        accumulator = MergeAccumulator()
        indexes = mock.Mock()
        indexes.source.list_name = self.LIST_NAME
        indexes.source.list_version = self.LIST_VERSION
        indexes.source.key = f"{self.LIST_NAME}-{self.LIST_VERSION}"
        indexes.source.merge_activity = f"merge_{self.LIST_NAME}"
        indexes.source.match_overrides_path = None
        indexes.source.algorithm_addition_source = self.LIST_NAME
        indexes.source.flow_iri_prefix = "https://example.invalid/flow/"
        indexes.mapping_file = ""
        indexes.context_expectations.resolve.return_value = self.RIVER
        indexes.consensus_context_strings = {}
        indexes.flow_objects_by_id = {}
        indexes.flow_object_label_by_id = {"fo-1": self.SUBSTANCE}
        created = _add_flow_in_missing_context(
            row=SourceRow(
                uuid="s-1", name=self.SUBSTANCE, synonyms=[], labels=[],
                context=["Emissions to water", "river"], context_iri="",
                context_normalized=(), unit=unit, unit_iri="", cas="", ec="",
                conversion=conversion,
            ),
            match=MatchAttempt(
                flow_object_id="fo-1", candidates=[], selected=None,
                selector_reason="no-candidate-in-context", selector_details={},
                basis="label", basis_value=self.SUBSTANCE,
            ),
            indexes=indexes,
            accumulator=accumulator,
        )
        self.assertTrue(created)
        (flow,) = accumulator.by_elem_id.values()
        return flow, accumulator


class NewContextRouteTestCase(NewContextRouteMixin, unittest.TestCase):
    """A rebased row that creates its context's flow still states the vendor's
    unit and the fix's factor (#370).

    AGRIBALYSE's `Water` released to rivers, by the kilogram, is rebased to
    cubic metres in its manual fixes.  The substance is known and the river has
    no flow for it, so the row creates one, and this route used to state the
    rebased unit as the vendor's and no factor: a consumer's kilograms
    published as cubic metres.
    """

    LIST_NAME = "agribalyse"
    LIST_VERSION = "3.2"
    SUBSTANCE = "Water"

    def test_the_mapping_states_the_vendors_unit_and_the_factor(self):
        flow, _ = self._create(conversion=UnitConversion(0.001, "kg", "m3"), unit="m3")
        self.assertEqual(flow.unit, "m3")
        metadata = flow.source_refs[0]["source_metadata"]
        self.assertEqual(metadata["unit"], "kg")
        self.assertEqual(metadata[QUDT_CONVERSION_MULTIPLIER_CURIE], 0.001)
        association = flow.concept_associations[0]
        self.assertEqual(association[QUDT_CONVERSION_MULTIPLIER_CURIE], 0.001)

    def test_a_row_no_fix_rebased_is_published_as_before(self):
        """The other half: no factor appears where no fix stated one."""
        flow, _ = self._create(conversion=None, unit="m3")
        metadata = flow.source_refs[0]["source_metadata"]
        self.assertEqual(metadata["unit"], "m3")
        self.assertNotIn(QUDT_CONVERSION_MULTIPLIER_CURIE, metadata)
        self.assertNotIn(QUDT_CONVERSION_MULTIPLIER_CURIE, flow.concept_associations[0])

    def test_the_match_record_carries_the_fixs_reasoning(self):
        """A curated factor's comment reaches the stored decision, as it does
        on a prepared match."""
        _, accumulator = self._create(
            conversion=UnitConversion(0.001, "kg", "m3", comment="water's density"),
            unit="m3",
        )
        (match,) = accumulator.algorithm_matches
        self.assertEqual(match.conversion_factor, 0.001)
        self.assertEqual(match.conversion_comment, "water's density")


class NewContextUnitTableTestCase(NewContextRouteMixin, unittest.TestCase):
    """A becquerel row that creates its context's kilobecquerel flow publishes
    the unit table's 0.001, as a row finding that flow already there does
    (#413).

    BAFU's `Antimony-122` released to rivers, in becquerels, is the first row
    to need a river flow for the substance, so it creates one in kilobecquerels
    -- the unit this list publishes activity in.  This route published the
    becquerel and no factor, while the 103 BAFU rows that found their flow
    already created carried 0.001.
    """

    LIST_NAME = "bafu"
    LIST_VERSION = "2026-v1"
    SUBSTANCE = "Antimony-122"

    def test_the_mapping_publishes_the_unit_tables_factor(self):
        flow, _ = self._create(conversion=None, unit="Bq")
        self.assertEqual(flow.unit, "kBq")
        metadata = flow.source_refs[0]["source_metadata"]
        self.assertEqual(metadata["unit"], "Bq")
        self.assertEqual(metadata[QUDT_CONVERSION_MULTIPLIER_CURIE], 0.001)
        self.assertEqual(metadata[CONVERSION_BASIS_KEY], ConversionBasis.UNIT_TABLE)
        association = flow.concept_associations[0]
        self.assertEqual(association[QUDT_CONVERSION_MULTIPLIER_CURIE], 0.001)
        self.assertEqual(
            association[CONVERSION_BASIS_KEY], ConversionBasis.UNIT_TABLE
        )

    def test_the_match_record_carries_the_factor(self):
        """What `find_unit_mismatches` reads, so the measure counts the row as
        converted because the mapping says so rather than because it could
        have.  No comment: the unit table states no reasoning."""
        _, accumulator = self._create(conversion=None, unit="Bq")
        (match,) = accumulator.algorithm_matches
        self.assertEqual(match.conversion_factor, 0.001)
        self.assertIsNone(match.conversion_comment)

    def test_a_row_in_the_published_unit_carries_none(self):
        """The other half: a kilobecquerel row on its kilobecquerel flow has
        nothing to convert."""
        flow, accumulator = self._create(conversion=None, unit="kBq")
        self.assertNotIn(
            QUDT_CONVERSION_MULTIPLIER_CURIE, flow.source_refs[0]["source_metadata"]
        )
        (match,) = accumulator.algorithm_matches
        self.assertIsNone(match.conversion_factor)


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
