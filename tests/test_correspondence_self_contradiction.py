"""One ecoinvent substance reaches one EF 3.1 substance, or somebody said why.

The ecoinvent -> EF 3.1 correspondence table is not an ecoinvent product and
carries no authority.  It is GLAD mappings plus, in its own words, "extra manual
and algorithmic matches", and it is incomplete -- so where it has no flow for a
substance in some compartment, it reaches for the nearest thing it can find.
That is a reasonable move for a mapping table and a bad thing for this list to
publish, because the result is that **one ecoinvent substance comes out of the
build as two**, and which one a consumer gets depends only on whether the
release was to air, to water or to soil.

The defect has been found nine times and always the same way: somebody noticed a
wrong number downstream.  #45 was chromium III scored with hexavalent
chromium's factors, #276 two pesticides routed to an amine and an aldehyde, #76
twenty-one insecticides published as one catch-all, #49 vanadium at ten times
its factor.  Each was fixed one substance at a time in
``ecoinvent-match-overrides.json``, which is applied to the table's rows before
the merge sees them.  Nothing ever went looking for the next one.

This is what goes looking.  It needs no chemistry judgement, because it does not
ask whether a target is *right* -- only whether the table gave two answers about
one substance while already holding the evidence that told them apart:

**The targets disagree with each other.**  Two rows of one ecoinvent flow reach
EF flows carrying different registry numbers.  The table has then said, in its
own data, that this one substance is two different chemicals.  This half needs
nothing but the table, and it is the half that sees the metal ions of #322 --
``Iron ion`` carries no registry number of its own, so nothing can be compared
*to* it, but `iron` and `iron (ii)` carry different ones and that is enough.

**The source's own number names one of them.**  Where the ecoinvent flow does
carry a registry number and one target matches it, the others are wrong by the
table's own account.  This half sees what the first cannot: a target with no
registry number at all, which is what every catch-all bucket is.  ecoinvent's
1,1,2-trichloroethane reaches `1,1,2-trichloroethane` in three compartments and
`Hydrocarbons, chlorinated` in seven, and only this half notices.

Neither half fires on the splits that are deliberate.  ecoinvent's single
`Carbon dioxide` flow legitimately becomes biogenic and land-use-change
variants, and `Water` becomes water and water vapour -- but those pairs carry
*one* registry number between them, so there is nothing to disagree about.  That
is why the rule keys on the number rather than on the fact of a split.

The table used to be read **twice** -- `_declared_match_table` for what the
vendor shipped, `load_prepared_match_table` for that with
`ecoinvent-match-overrides.json` applied -- and the difference between the two
readings was the argument for the whole module.  With the tables retired
(#141) the declared reading is empty and only the effective one remains: the
override rows themselves, which are now the whole correspondence.  Those rows
state no target registry number of their own, so the reading is **enriched
here** with each EF target's own numbers, by `target_uuid` from the base
list's flows -- without that join neither half of the rule can fire, and the
module would be asserting that an empty set stays empty.  A substance the old
declared reading found that the effective one did not was one somebody had
already settled -- and there were eight of those.  Four, #45, #276, #76 and
#49, were each originally found by a person reading a number that looked
wrong; **this check found all four from the table alone, without reading a
single characterisation factor**, which is the evidence that it would have
found them first.

The other four are the better evidence, because they were settled while this
module was being written, by changes that knew nothing about it, and it
noticed on its own both times -- by failing, and naming them.  #324 settled
MCPA, mecoprop-P and paraquat; the pinned population failed with 19 against 22.
#323 then settled both spellings of 1,1,1-trichloroethane; it failed with 18
against 19.  A curated decision takes a substance off the list, and nothing has
to remember to tell this file about it.

What the second reading still finds is #122's worklist, pinned in `TRACKED`
below so that a new ecoinvent release, or a new version of the correspondence
table, that starts sending a further substance to two places fails here instead
of waiting to be noticed downstream.
"""

from __future__ import annotations

import re
import unittest
from collections import defaultdict
from dataclasses import dataclass

import orjson

from brightway_flows.sources import (
    base_source_list,
    known_source_lists,
    load_prepared_match_table,
)

#: A registry number as the tables write it.  Both sides pad to nine digits in
#: places -- `000096-49-1` for 96-49-1 -- so the leading zeros come off before
#: anything is compared, and a value that is not a registry number at all is
#: read as absent rather than as a number nothing will match.
_REGISTRY_NUMBER = re.compile(r"\d{2,7}-\d\d-\d")


def registry_number(value: object) -> str:
    """*value* as a comparable registry number, or ``""`` where it is not one."""
    text = str(value or "").strip().lstrip("0")
    return text if _REGISTRY_NUMBER.fullmatch(text) else ""


@dataclass(frozen=True)
class Contradiction:
    """One ecoinvent substance the table gives more than one answer about."""

    #: The ecoinvent flow name, lowercased, which is the substance across all of
    #: its compartments.  Grouping on the name rather than the uuid is the whole
    #: point: a uuid is one compartment, and the disagreement is between them.
    source_name: str
    #: Every EF 3.1 substance the table sends it to, by name, lowercased.
    targets: tuple[str, ...]
    #: Which of the two halves fired.  Both, for most of them.
    reasons: tuple[str, ...]
    #: The source flow uuids involved, which is what an override names.
    source_uuids: frozenset[str]


TARGETS_DISAGREE = "targets disagree"
SOURCE_NUMBER_NAMES_ONE = "source number names one of them"


def contradictions(
    rows: list[dict], *, source_numbers: dict[str, str] | None = None
) -> dict[str, Contradiction]:
    """Where *rows* give more than one answer about one ecoinvent substance.

    *rows* are correspondence-table rows in randonneur's shape, before any
    override.  *source_numbers* maps a source flow uuid to that flow's own
    registry number, and is what the second half of the rule needs; without it
    only the first half runs, which is what a caller with no extracted source
    list can still ask.
    """
    numbers = source_numbers or {}
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        source = row.get("source") or {}
        name = str(source.get("name") or "").strip().lower()
        if name:
            grouped[name].append(row)

    found: dict[str, Contradiction] = {}
    for name, group in grouped.items():
        targets = {
            str((row.get("target") or {}).get("name") or "").strip().lower()
            for row in group
        }
        targets.discard("")
        if len(targets) < 2:
            continue

        reasons: list[str] = []
        target_numbers = {
            registry_number((row.get("target") or {}).get("CAS number"))
            for row in group
        }
        target_numbers.discard("")
        if len(target_numbers) > 1:
            reasons.append(TARGETS_DISAGREE)

        source_side = {
            numbers.get(str((row.get("source") or {}).get("uuid") or ""), "")
            for row in group
        }
        source_side.discard("")
        if source_side:
            matching = {
                str((row.get("target") or {}).get("name") or "").strip().lower()
                for row in group
                if registry_number((row.get("target") or {}).get("CAS number"))
                in source_side
            }
            matching.discard("")
            if matching and matching != targets:
                reasons.append(SOURCE_NUMBER_NAMES_ONE)

        if reasons:
            found[name] = Contradiction(
                source_name=name,
                targets=tuple(sorted(targets)),
                reasons=tuple(reasons),
                source_uuids=frozenset(
                    str((row.get("source") or {}).get("uuid") or "")
                    for row in group
                ) - {""},
            )
    return found


def _ecoinvent_sources():
    return [
        source
        for source in known_source_lists().values()
        if source.list_name == "ecoinvent"
    ]


def _source_registry_numbers(source) -> dict[str, str]:
    """Every flow's own registry number, by uuid, for one ecoinvent release."""
    rows = orjson.loads(source.flows_path.read_bytes())
    return {
        str(row.get("uuid") or ""): registry_number(row.get("cas_number"))
        for row in rows
    }


def _ef_registry_numbers() -> dict[str, str]:
    """Each EF 3.1 flow's own registry number, by uuid.

    The join the whole module now stands on: an override row states a target
    uuid and a target name but never a target registry number, so without the
    number the flow itself carries, neither half of `contradictions` can
    compare anything.  The enrichment asks the EF list rather than trusting
    the override, which is the point -- the rule is about what the *targets*
    say they are.
    """
    rows = orjson.loads(base_source_list().flows_path.read_bytes())
    numbers: dict[str, str] = {}
    for row in rows:
        for candidate in row.get("cas_numbers") or []:
            number = registry_number(candidate)
            if number:
                numbers[str(row.get("uuid") or "")] = number
                break
    return numbers


def _with_target_numbers(
    rows: list[dict], ef_numbers: dict[str, str]
) -> list[dict]:
    """*rows*, each target carrying the number its EF flow carries.

    A target that already states one keeps it; a target uuid the EF list does
    not know stays numberless, which reads as "nothing to disagree with" --
    exactly what an absent number meant when the tables stated their own.
    """
    enriched = []
    for row in rows:
        target = dict(row.get("target") or {})
        if not registry_number(target.get("CAS number")):
            number = ef_numbers.get(str(target.get("uuid") or ""))
            if number:
                target["CAS number"] = number
        enriched.append({**row, "target": target})
    return enriched


#: Every substance the shipped tables still contradict themselves about, and the
#: issue that tracks the decision.  This is #122's worklist, and an entry leaves
#: it when the change that settles that substance lands -- by a rewrite or a
#: decline in `ecoinvent-match-overrides.json`, which is what "settled" means
#: here and what the historical four demonstrate below.
#:
#: A name absent from this map is the point of the whole module: a new ecoinvent
#: release, or a new version of the correspondence table, that starts sending a
#: further substance to two places fails here rather than waiting for somebody
#: to notice a wrong number downstream.
TRACKED: dict[str, int] = {
    # Empty, and deliberately kept rather than deleted.  The last population --
    # #322's twelve metal ions, and #125's carbon -- was settled by retiring the
    # published tables outright (#141): the twelve are decided by the
    # element/ion rule of plans/retire-prepared-correspondence.md §3a, where the
    # name governs in every compartment and the air/soil-versus-water split
    # this check kept finding cannot be expressed, and the carbon releases are
    # curated rows in ecoinvent-match-overrides.json.  What this module audits
    # now is that file -- this project's own correspondence -- and a name
    # appearing here again means our own rows contradict themselves.
}

#: Found in the shipped table and *not* in what reaches the merge, because a
#: curated override settles each one.
#:
#: The first four were each found the hard way -- somebody read a number that
#: looked wrong -- and this check finds all four from the table alone, which is
#: the argument that it would have found them first.  The last three arrived by
#: the opposite route and are the better evidence: #119 came out of the same
#: sweep that produced #122, and its fix in #324 settled them here without
#: anybody touching this file.  A curated decision takes a substance off the
#: list, which is what makes the guard below mean something.
SETTLED_BY_OVERRIDES = {
    "chromium iii": 311,
    "fenoxaprop-p ethyl ester": 331,
    "trifloxystrobin": 405,
    "vanadium v": 333,
    "mcpa": 597,
    "mecoprop-p": 597,
    "paraquat": 597,
    "1,1,1-trichloroethane": 599,
    # #125's five, settled together.  Three are rewrites onto a flow EF 3.1
    # ships in every compartment concerned: nitrogen gas onto `dinitrogen`
    # rather than onto the nutrient measure whose own name excludes it,
    # ecoinvent's `Rabon` onto the EF copy carrying the 22248-79-9 ecoinvent
    # registers it as, and 1,1,2-trichloroethane off `Hydrocarbons,
    # chlorinated`.  Two are declines, where EF ships the right substance in
    # one compartment out of thirteen and the table reached for a salt or an
    # ester to cover the other twelve.
    "nitrogen": 611,
    "rabon": 611,
    "1,1,2-trichloroethane": 611,
    "glufosinate": 611,
    "quizalofop-p": 611,
}

#: The same thing, for a release that spells the flow the older way.  Named
#: apart because it is absent from the 3.11/3.12 table, so the rediscovery test
#: -- which reads 3.12 -- cannot ask about it.
SETTLED_IN_OLDER_RELEASES = {
    "ethane, 1,1,1-trichloro-, hcfc-140": 599,
    # The older spelling of the flow settled just above.  ecoinvent renamed it
    # `1,1,2-Trichloroethane` at 3.10.1 and registered it 79-00-5 throughout,
    # so one override row decides for both spellings and only this one is
    # invisible to a check that reads 3.12.
    "ethane, 1,1,2-trichloro-": 611,
    # 2,4-D is the reason this dict is not a formality.  The table sends the
    # herbicide acid to its sodium salt in the 3.9.1 and 3.10.1 tables and in
    # neither the 3.8 nor the 3.11/3.12 one -- so a build merging 3.12 and 3.8,
    # which is the pair every comparison uses, publishes all ten of its 2,4-D
    # rows correctly with no override written at all.  The defect is a fact
    # about two shipped tables rather than about a build, and there is nowhere
    # else it can be held.
    "2,4-d": 611,
}


def _row(name, uuid, target, number, source_uuid=None):
    return {
        "source": {"name": name, "uuid": source_uuid or uuid},
        "target": {"name": target, "uuid": uuid, "CAS number": number},
    }


class TheRuleItself(unittest.TestCase):
    """Both halves of the rule, and the cases that must not fire."""

    def test_targets_carrying_different_numbers_are_a_contradiction(self):
        # Needs nothing but the table: the two targets disagree about which
        # chemical this is, whatever the source flow does or does not carry.
        found = contradictions([
            _row("Iron ion", "a", "iron", "7439-89-6"),
            _row("Iron ion", "b", "iron (ii)", "15438-31-0"),
        ])
        self.assertEqual(set(found), {"iron ion"})
        self.assertIn(TARGETS_DISAGREE, found["iron ion"].reasons)

    def test_one_target_matching_the_source_number_is_a_contradiction(self):
        # The half that sees a catch-all: `hydrocarbons, chlorinated` carries no
        # number, so the targets cannot disagree with each other, and only the
        # source's own number says which of the two is right.
        found = contradictions(
            [
                _row("1,1,2-Trichloroethane", "a", "1,1,2-trichloroethane", "79-00-5"),
                _row("1,1,2-Trichloroethane", "b", "hydrocarbons, chlorinated", None),
            ],
            source_numbers={"a": "79-00-5", "b": "79-00-5"},
        )
        self.assertEqual(set(found), {"1,1,2-trichloroethane"})
        self.assertEqual(
            found["1,1,2-trichloroethane"].reasons, (SOURCE_NUMBER_NAMES_ONE,)
        )

    def test_a_deliberate_split_on_one_number_is_not_a_contradiction(self):
        # ecoinvent's single `Carbon dioxide` becomes biogenic and
        # land-use-change variants on purpose.  They are one chemical and carry
        # one number, so neither half fires -- which is why the rule keys on the
        # number rather than on the fact of a split.
        self.assertEqual(
            contradictions(
                [
                    _row("Carbon dioxide", "a", "carbon dioxide (biogenic)", "124-38-9"),
                    _row("Carbon dioxide", "b", "carbon dioxide (land use change)",
                         "124-38-9"),
                ],
                source_numbers={"a": "124-38-9", "b": "124-38-9"},
            ),
            {},
        )

    def test_one_substance_in_many_compartments_is_not_a_contradiction(self):
        # The ordinary case, and the one that would make this useless if it
        # fired: one target substance reached by every compartment of the source.
        self.assertEqual(
            contradictions([
                _row("Benzene", "a", "benzene", "71-43-2"),
                _row("Benzene", "b", "benzene", "71-43-2"),
                _row("Benzene", "c", "benzene", "71-43-2"),
            ]),
            {},
        )

    def test_the_source_half_is_silent_without_the_source_numbers(self):
        # A caller with no extracted source list still gets the first half
        # rather than an error, which is what lets a partial checkout ask the
        # question at all.
        rows = [
            _row("1,1,2-Trichloroethane", "a", "1,1,2-trichloroethane", "79-00-5"),
            _row("1,1,2-Trichloroethane", "b", "hydrocarbons, chlorinated", None),
        ]
        self.assertEqual(contradictions(rows), {})

    def test_padded_registry_numbers_compare_equal(self):
        # The tables pad to nine digits in places.  `000079-00-5` and `79-00-5`
        # are one number, and reading them as two would report every padded row
        # as a contradiction.
        self.assertEqual(registry_number("000079-00-5"), "79-00-5")
        self.assertEqual(registry_number("79-00-5"), "79-00-5")
        self.assertEqual(registry_number("not a number"), "")
        self.assertEqual(registry_number(None), "")


class TheShippedTables(unittest.TestCase):
    """What the correspondence tables this project actually loads still say."""

    @classmethod
    def setUpClass(cls):
        cls.sources = _ecoinvent_sources()
        missing = [s for s in cls.sources if not s.flows_path.exists()]
        if missing:
            raise unittest.SkipTest(
                f"ecoinvent flows not fetched: {missing[0].flows_path.name}"
            )
        ef_path = base_source_list().flows_path
        if not ef_path.exists():
            raise unittest.SkipTest(f"EF flows not fetched: {ef_path.name}")
        ef_numbers = _ef_registry_numbers()
        cls.effective = {}
        for source in cls.sources:
            numbers = _source_registry_numbers(source)
            cls.effective[source.key] = contradictions(
                _with_target_numbers(
                    load_prepared_match_table(source), ef_numbers
                ),
                source_numbers=numbers,
            )

    def test_every_live_contradiction_is_tracked_by_an_issue(self):
        # The guard.  A substance the tables contradict themselves about that
        # nobody has filed an issue for fails here, which is the whole point:
        # the next one is found by this test rather than by a curator reading a
        # characterisation factor that looks wrong.
        untracked = sorted(
            f"{source_key}: {name} -> {', '.join(found.targets)}"
            for source_key, live in self.effective.items()
            for name, found in live.items()
            if name not in TRACKED
        )
        self.assertEqual(untracked, [], "these are contradicted and filed nowhere")

    def test_the_population_is_the_one_602_measured(self):
        # Stated so that a table which stops contradicting itself about one of
        # these, or starts contradicting itself about more, is a visible change
        # rather than a silently different list.  3.11 and 3.12 share a table.
        #
        # These were 22/22/18/15 when this module was written, against `main`
        # before #324, and this test is what has reported every move since --
        # each time by failing, naming the substance, before anybody thought to
        # look.  #324 settled MCPA, mecoprop-P and paraquat (19 != 22); #323
        # then settled both spellings of 1,1,1-trichloroethane (18 != 19); #125
        # then settled its five (13 != 18).  Which is the intended way for the
        # number to move: deliberately, in the change that earns it.
        #
        # What is left is #322's twelve metals in every release, and `Carbon`
        # in the three that ship it -- one list of substances that needs a rule
        # decided before any row can be written, and one flow that needs a
        # chemist to say whether the releases are the element or a soot
        # measure.  Neither is a lookup, which is why #125 stopped here.
        # ... and #141 then settled everything left, by retiring the tables:
        # the twelve metals fell to the element/ion rule (plan §3a) and carbon
        # to curated rows.  What is read now is ecoinvent-match-overrides.json
        # itself, and the number to hold is zero -- our own correspondence
        # contradicting itself about a substance is exactly the defect this
        # module was built to catch, one authority earlier.
        for key in (
            "ecoinvent-3.12",
            "ecoinvent-3.11",
            "ecoinvent-3.10.1",
            "ecoinvent-3.9.1",
            "ecoinvent-3.8",
        ):
            with self.subTest(source=key):
                self.assertEqual(self.effective[key], {})

    def test_the_settled_names_stay_settled(self):
        # This used to be two tests: one proving the *shipped* tables still
        # contradicted themselves about every substance somebody had found the
        # hard way (#45, #276, #76, #49, #119, #121, #125), and one proving
        # the overrides settled each.  The shipped tables are retired (#141),
        # so there is no declared reading left to rediscover anything in -- the
        # history lives in those issues and in this file's git record.  What
        # remains checkable is the settlement itself: none of the hard-won
        # names may contradict itself in the correspondence this project now
        # authors.
        for source_key, live in self.effective.items():
            for name in list(SETTLED_BY_OVERRIDES) + list(SETTLED_IN_OLDER_RELEASES):
                with self.subTest(source=source_key, name=name):
                    self.assertNotIn(name, live)

    def test_nothing_is_tracked_that_no_table_contradicts(self):
        # Catches a stale entry: a name left in TRACKED after the change that
        # settled it would quietly widen what the guard tolerates.
        live = {name for found in self.effective.values() for name in found}
        self.assertEqual(sorted(set(TRACKED) - live), [])


if __name__ == "__main__":
    unittest.main()
