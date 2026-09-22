"""Reading names SimaPro shaped: CAS-index inversion (#285), valence and
ion spellings (#286), the geography written into the name (#65).

`Benzene, Chloro-` and `chlorobenzene` are one substance; so are `Arsenic V`
and `Arsenic (v)`. Both are spellings SimaPro's lineage carries and this list
does not use, and nothing bridges either on its own -- the names share no
string, so label matching fails, and the rows carrying them have no registry
number, so identifier matching has nothing to work with. Those two are
*aliases*: a second name to try, and only once everything else has failed.

`Water, AE` is a different thing and is handled differently. It is not another
way to spell a substance -- it is a substance with a **geography** attached,
and geography is something this list holds elsewhere. So it is split rather
than aliased, in the adapter rather than during matching, and what the tests
here cover is the rule itself; `test_bafu_extraction` covers it being applied.

The unit written into the name -- `Water/m3` -- is the second split, and runs
at the other end of a build, in `load_flows`. `PreparingARowTestCase` covers
the third point, which belongs to neither end: somebody who hands this project
one row has been through no adapter and no `load_flows`, so both splits run
there together (#328).

All of them are only right for a list SimaPro shaped. Applied anywhere else,
de-inverting a name, reading a trailing capital letter as an oxidation state,
or reading a trailing field as a place is not a correction but a guess.
"""

from __future__ import annotations

import dataclasses
import unittest

import orjson

from brightway_flows.merge.contexts import ContextExpectations
from brightway_flows.merge.matching import resolve_flow_object
from brightway_flows.merge.state import MergeAccumulator, MergeIndexes, SourceRow
from brightway_flows.simapro_names import (
    GEOGRAPHY_CODES,
    PREPARATION_STEPS,
    WITHDRAWN_GEOGRAPHY_CODES,
    bracket_fusion_locants,
    canonical_geography_code,
    deinvert_cas_index_name,
    deinvert_phrase_name,
    name_without_unit_suffix,
    prepare_row_for_matching,
    simapro_name_aliases,
    split_geography_suffix,
    unit_suffix_rewrites,
    unspecified_ion,
    valence_in_parentheses,
)
from brightway_flows.sources import known_source_lists, resolve_source_list


def geography_base(name: str) -> str | None:
    """The name with the place taken off, or ``None`` if it carries none.

    A test helper rather than production code: what the splitter returns is a
    pair, and most of what is asserted below is about the half that stays.
    """
    split = split_geography_suffix(name)
    return split[0] if split is not None else None


#: No registered list sets `simapro_origin` until BAFU lands (#282), so these
#: put the flag on one rather than naming a manifest that is not there yet.
#: Which list it is does not matter and should not: the flag is what gates,
#: not the identity of the vendor.
def _source(*, simapro: bool):
    return dataclasses.replace(
        resolve_source_list("ecoinvent-3.12"), simapro_origin=simapro
    )

#: Every inverted name BAFU 2026 v1 ships, verbatim, with what it means.
#: The real set rather than a sample: this is the whole of what the rule has to
#: get right, and a BAFU release adding a shape it cannot read should fail here.
BAFU_INVERTED = {
    "Acetylene, Dichloro-": "dichloroacetylene",
    "Benzene, 1,2,4-trimethyl-": "1,2,4-trimethylbenzene",
    "Benzene, 1,2-dichloro-": "1,2-dichlorobenzene",
    "Benzene, Chloro-": "chlorobenzene",
    "Benzene, Dichloro-": "dichlorobenzene",
    "Benzene, Pentachloronitro-": "pentachloronitrobenzene",
    "Butadiene, Hexachloro-": "hexachlorobutadiene",
    "Chlorosilane, Trimethyl-": "trimethylchlorosilane",
    "Ethane, 1,1,2,2-tetrachloro-": "1,1,2,2-tetrachloroethane",
    "Ethane, 1,1-dichloro-": "1,1-dichloroethane",
    "Ethane, 1,2-dibromo-": "1,2-dibromoethane",
    "Ethane, Chloro-": "chloroethane",
    "Ethene, 1,1-dichloro-": "1,1-dichloroethene",
    "Ethene, 1,2-dichloro-": "1,2-dichloroethene",
    "Ethene, Trichloro-": "trichloroethene",
    "Phenol, 2,4-dichloro-": "2,4-dichlorophenol",
    "Phenol, 2-chloro-": "2-chlorophenol",
    "Phenol, 4-chloro-": "4-chlorophenol",
    "Propane, 1,2-dichloro-": "1,2-dichloropropane",
    "Propane, Perfluorocyclo-": "perfluorocyclopropane",
    "Thiazole, 2-(thiocyanatemethylthio)benzo-": (
        "2-(thiocyanatemethylthio)benzothiazole"
    ),
    "Toluene, 2-chloro-": "2-chlorotoluene",
}

#: Shapes where the join needs a hyphen. Both are nomenclature rather than
#: guesswork: a substituent runs straight into its parent (`chlorobenzene`)
#: unless the parent leads with a locant or the substituent is a bare
#: positional descriptor, and then the hyphen is required.
#:
#: `2-Butene, 2-methyl-` is BAFU's. `Xylene, o-` is not — BAFU ships no bare
#: descriptor — and is here because the spelling belongs to the convention
#: rather than to one export.
HYPHEN_JOINED = {
    "2-Butene, 2-methyl-": "2-methyl-2-butene",
    "Xylene, o-": "o-xylene",
}

#: The trailing hyphen belongs to the parent's own name rather than marking an
#: attachment: `dibenzo-p-dioxin` is one word. Reading that needs chemistry
#: this rule does not have, so it declines.
POSITIONAL_TAIL = ("Dioxin, 2,3,7,8 Tetrachlorodibenzo-p-",)

#: Names with a comma that are *not* inversions, and must come back untouched.
#: Each is a real BAFU name and each would be mangled by a rule that keyed on
#: the comma alone -- which is why the trailing hyphen is the signal.
NOT_INVERTED = (
    "Water, cooling, unspecified natural origin",
    "Water, RER",
    "Gas, natural/m3",
    "Occupation, annual crop",
    "Nitrogen, organic bound",
    "Carbon dioxide, biogenic",
    "Arsenic, Ion",
    "Benzene",
    "",
)


#: Every phrase inversion BAFU 2026 v1 ships whose other spelling the list
#: already holds, with the flow object it names.  Eight names, and not one of
#: them a chemical -- which is why the CAS-index rule was never going to find
#: them: its signal is the attachment hyphen, and a phrase has none.
#:
#: Read off the real name set as the merge sees it: extracted with the
#: geography taken out of the name (#65) and with this list's manual fixes
#: applied, which is what puts `Gas, natural` here at all -- BAFU spells it
#: `Gas, natural/m3` and #67 takes the unit off.
#:
#: Five are placed by the rule, 19 rows of them, `Heat, waste` being 15. The
#: three water and gas names carry a registry number and are decided by the CAS
#: branch before an alias is consulted -- see the test that says so.
BAFU_PHRASES = {
    "Clay, bentonite": "bentonite clay",
    "Coal, brown": "brown coal",
    "Coal, hard": "hard coal",
    "Gas, natural": "natural gas",
    "Heat, waste": "waste heat",
    "Oil, crude": "crude oil",
    "Water, lake": "lake water",
    "Water, river": "river water",
}

#: One real BAFU name per shape the phrase rule declines, and what each is
#: instead.  Every one of them would come back as a string nothing says.
#:
#: No geography row here, because there is no BAFU name left to put in one:
#: #65 takes the place out at extraction, and `Water, RER` never arrives. The
#: rule still declines it, and the test that says so stands on its own.
NOT_PHRASES = {
    "Benzene, chloro-": "a substituent; the CAS-index rule owns it",
    "Dioxin, 2,3,7,8 Tetrachlorodibenzo-p-": "declined there, and stays declined",
    "Arsenic, ion": "a charge; the ion rule owns it",
    "Energy, from coal": "a prepositional phrase, already in order",
    "Carbon dioxide, in air": "the same, with a different preposition",
    "Gas, natural/m3": "the unit is in the name (#67), and comes off first",
    "COD, Chemical Oxygen Demand": "an acronym and its expansion",
    "Particulates, < 10 um": "a measurement, which does not front a noun",
    "1,4-Butanediol": "the comma is inside a locant",
    "Dibenz(a,h)anthracene": "the comma is inside a bracket",
    "Water, cooling, unspecified natural origin": "two commas: a list, not a pair",
    "Benzene": "no comma at all",
    "": "",
}


class DeinversionTestCase(unittest.TestCase):
    def test_every_name_bafu_ships_this_way(self):
        for name, expected in sorted(BAFU_INVERTED.items()):
            with self.subTest(name=name):
                self.assertEqual(deinvert_cas_index_name(name), expected)

    def test_the_substituent_keeps_its_own_commas(self):
        """The split is at the first comma, not the last.

        `Benzene, 1,2-dichloro-` is one parent and one substituent carrying
        locants, not three fields. Splitting on the last comma would give
        `2-dichloroBenzene, 1`."""
        self.assertEqual(
            deinvert_cas_index_name("Benzene, 1,2-dichloro-"), "1,2-dichlorobenzene"
        )

    def test_a_parent_may_contain_spaces(self):
        """`Acetic acid, chloro-` is chloroacetic acid, and that is right."""
        self.assertEqual(
            deinvert_cas_index_name("Acetic acid, chloro-"), "chloroacetic acid"
        )

    def test_a_name_without_the_trailing_hyphen_is_not_an_inversion(self):
        """The hyphen marks where the substituent attaches, and is the signal.

        Without it every comma-bearing name would be swept up: `Water, RER` is
        a geography (#65) and `Gas, natural/m3` is a unit (#67), and turning
        either into a chemical would be an invention."""
        for name in NOT_INVERTED:
            with self.subTest(name=name):
                self.assertIsNone(deinvert_cas_index_name(name))

    def test_the_join_takes_a_hyphen_where_nomenclature_needs_one(self):
        """`2-Butene, 2-methyl-` is 2-methyl-2-butene, not 2-methyl2-butene.

        Found by running the rule over every BAFU row rather than over the
        unmatched ones. That flow already matched, so a plain concatenation
        would have hung a wrong spelling on a flow that was already right --
        the failure this rule exists to avoid, pointed the other way."""
        for name, expected in sorted(HYPHEN_JOINED.items()):
            with self.subTest(name=name):
                self.assertEqual(deinvert_cas_index_name(name), expected)

    def test_a_positional_descriptor_tail_is_declined(self):
        """In `Dioxin, 2,3,7,8 Tetrachlorodibenzo-p-` the trailing hyphen is
        part of `dibenzo-p-dioxin`, not a mark of where a substituent attaches.

        Concatenating gives `…dibenzo-pdioxin`. Knowing better needs to know
        that `dibenzo-p-dioxin` is one word, so the rule declines instead."""
        for name in POSITIONAL_TAIL:
            with self.subTest(name=name):
                self.assertIsNone(deinvert_cas_index_name(name))

    def test_a_trailing_trade_name_is_declined(self):
        """`Ethane, 1,1,1,2-tetrafluoro-, HFC-134a` has a family name after the
        substituent. There is a right answer, but reading it needs a rule this
        one does not have, so it declines rather than guessing."""
        self.assertIsNone(
            deinvert_cas_index_name("Ethane, 1,1,1,2-tetrafluoro-, HFC-134a")
        )

    def test_aliases_never_repeat_the_name_itself(self):
        self.assertEqual(simapro_name_aliases("chlorobenzene"), [])
        self.assertEqual(simapro_name_aliases("Benzene, Chloro-"), ["chlorobenzene"])


#: Every fused-ring name the three merged lists ship in round brackets, and the
#: nomenclature spelling of each.  Four of BAFU's minted a second copy of a
#: substance this list already publishes (#103); the rest carry registry
#: numbers and match on those, and are here so a change to the rule has to
#: answer for them too.
BRACKETED_FUSION_NAMES = {
    "Benz(a)anthracene": "benz[a]anthracene",
    "Benzo(a)anthracene": "benzo[a]anthracene",
    "Benzo(a)pyrene": "benzo[a]pyrene",
    "Benzo(b)fluoranthene": "benzo[b]fluoranthene",
    "Benzo(g,h,i)perylene": "benzo[g,h,i]perylene",
    "Benzo(ghi)perylene": "benzo[ghi]perylene",
    "Benzo(k)fluoranthene": "benzo[k]fluoranthene",
    "Dibenz(a,h)anthracene": "dibenz[a,h]anthracene",
    "Indeno(1,2,3-cd)pyrene": "indeno[1,2,3-cd]pyrene",
}

#: What must stay declined, and why each would be wrong.  The valence pair is
#: the one that matters: an oxidation state is written in the same brackets in
#: the same place, and `Iron(iii)oxide` runs it straight into the next word, so
#: only the letters tell the two apart.
NOT_A_FUSION_LOCANT = (
    "Thiazole, 2-(thiocyanatemethylthio)benzo-",  # a substituent, not a locant
    "Particulates, < 10 Um (stationary)",         # a qualifier
    "Octene (mixture Of Isomers)",                # a qualifier
    "Copper(ii) Sulphide",                        # an oxidation state
    "Iron(iii)oxide",                             # an oxidation state, no space
    "Arsenic (V)",                                # a valence, #286's to read
    "Benzene",                                    # no brackets at all
)


class BracketedFusionLocantTestCase(unittest.TestCase):
    """`Benzo(a)anthracene` is benzo[a]anthracene (#103).

    A polycyclic aromatic hydrocarbon is named for the rings it is built from
    and the bond they are fused at, and that bond's letter belongs in square
    brackets.  A list exported as flat text writes round ones instead, and the
    two spellings never meet.

    Nothing is added or removed by this rule -- unlike every other alias here,
    which constructs a name that appears nowhere in the source list, this one
    retypes the name that is already there.
    """

    def test_every_fused_ring_name_the_merged_lists_ship(self):
        for name, expected in sorted(BRACKETED_FUSION_NAMES.items()):
            with self.subTest(name=name):
                self.assertEqual(bracket_fusion_locants(name), expected)

    def test_what_is_not_a_fusion_locant_is_declined(self):
        for name in NOT_A_FUSION_LOCANT:
            with self.subTest(name=name):
                self.assertIsNone(bracket_fusion_locants(name))

    def test_a_name_with_two_locants_converts_both(self):
        """`Benzo(b)naphtho(1,2-d)thiophene` is one substance with two fusions,
        and a name half in each convention is a spelling nobody uses."""
        self.assertEqual(
            bracket_fusion_locants("Benzo(b)naphtho(1,2-d)thiophene"),
            "benzo[b]naphtho[1,2-d]thiophene",
        )

    def test_a_name_mixing_a_locant_with_something_else_is_declined_whole(self):
        """Converting the half this rule can read would assert that the half it
        cannot is a locant.  Better to decline and have the row reported."""
        self.assertIsNone(bracket_fusion_locants("Naphtho(2,1-a)fluoranthene(mixed)"))

    def test_a_locant_must_sit_inside_a_word(self):
        """The parent ring before it and the rest of the name after.  This is
        the whole difference between a fusion locant and an oxidation state."""
        self.assertIsNone(bracket_fusion_locants("Benzo(a)"))
        self.assertIsNone(bracket_fusion_locants("(a)anthracene"))
        self.assertIsNone(bracket_fusion_locants("Copper (ii) sulphide"))

    def test_the_entry_point_offers_it(self):
        self.assertIn("benzo[a]anthracene", simapro_name_aliases("Benzo(a)anthracene"))


class PhraseInversionTestCase(unittest.TestCase):
    """`Heat, waste` is waste heat (#288).

    The same habit as the chemical inversion -- a flat sorted column files
    everything about heat under `Heat` -- and a different join, because these
    are two words rather than a substituent running into its parent.
    `wasteheat` is not a word, which is why the hyphen-keyed rule could not be
    loosened to reach these and a second rule is what reaches them.

    None of the eight is a chemical, and that is the point: the CAS-index rule
    keys on the attachment hyphen, and an ordinary phrase has none, so five of
    them minted a second flow object beside a flow the list already held.
    """

    def test_every_phrase_bafu_ships_that_the_list_already_holds(self):
        for name, expected in sorted(BAFU_PHRASES.items()):
            with self.subTest(name=name):
                self.assertEqual(deinvert_phrase_name(name), expected)

    def test_the_join_is_a_space_and_not_a_concatenation(self):
        """What separates this rule from the chemical one. `chlorobenzene` is a
        word and `wasteheat` is not, so the two cannot be one rule with a
        looser signal."""
        self.assertEqual(deinvert_phrase_name("Heat, waste"), "waste heat")
        self.assertNotIn("wasteheat", simapro_name_aliases("Heat, waste"))

    def test_every_shape_it_declines(self):
        for name, why in sorted(NOT_PHRASES.items()):
            with self.subTest(name=name, why=why):
                self.assertIsNone(deinvert_phrase_name(name))

    def test_a_name_the_chemical_rule_declines_does_not_fall_through(self):
        """`Dioxin, 2,3,7,8 Tetrachlorodibenzo-p-` is declined there because
        reading it needs to know that `dibenzo-p-dioxin` is one word. Swapping
        the halves instead would spell it a third way, which is not better for
        being different."""
        for name in POSITIONAL_TAIL:
            with self.subTest(name=name):
                self.assertIsNone(deinvert_cas_index_name(name))
                self.assertEqual(simapro_name_aliases(name), [])

    def test_a_head_that_is_a_word_is_not_an_acronym(self):
        """The acronym guard is about `COD, Chemical Oxygen Demand`, where the
        second half expands the first. It must not reach a head that is simply
        a short word."""
        self.assertEqual(deinvert_phrase_name("Oil, crude"), "crude oil")
        self.assertIsNone(deinvert_phrase_name("TOC, Total Organic Carbon"))

    def test_the_entry_point_offers_it(self):
        self.assertEqual(simapro_name_aliases("Heat, waste"), ["waste heat"])

    def test_an_alias_that_names_nothing_is_inert_rather_than_wrong(self):
        """Most of what the rule speaks for finds nothing, and that costs
        nothing: an alias is a lookup key, not a claim about a substance, and
        one that matches no label leaves the row exactly as unmatched as it
        was. 67 of BAFU's 1,011 names get one; eight of them name a flow
        object."""
        self.assertEqual(
            deinvert_phrase_name("Aldehydes, unspecified"), "unspecified aldehydes"
        )

    def test_a_geography_is_declined_by_asking_the_list_that_defines_one(self):
        """`Water, RER` is a place, and #65 owns it. Two things follow.

        BAFU does not send one this far any more -- the adapter splits it, so
        what arrives is `Water` with `RER` in a field -- but the entry point
        promises to say nothing about a geography, and a list whose adapter
        does not split would arrive here with one. So the guard stays, and it
        asks `GEOGRAPHY_CODES` instead of deciding for itself: an upper-case
        short-token test beside that whitelist is a second opinion that can
        come to disagree with it.
        """
        self.assertEqual(split_geography_suffix("Water, RER"), ("Water", "RER"))
        self.assertIsNone(deinvert_phrase_name("Water, RER"))
        self.assertEqual(simapro_name_aliases("Water, AE"), [])
        # `Europe` is a region code and eight letters long, so a shape test
        # would have missed it and the whitelist does not.
        self.assertIn("Europe", GEOGRAPHY_CODES)
        self.assertIsNone(deinvert_phrase_name("Water, Europe"))


class ValenceAndIonTestCase(unittest.TestCase):
    """`Arsenic V` and `Iron, ion` (#286).

    A Roman numeral after an element is its oxidation state, not decoration:
    arsenic III and arsenic V behave differently in water and are characterised
    differently. The list holds them as separate substances and spells them
    with parentheses.
    """

    #: Every valence name BAFU 2026 v1 ships. Four of them already match by
    #: CAS, and the objects they land on are spelled `Cadmium (ii)`,
    #: `Chromium (iii)`, `Mercury (ii)` and `Nickel (ii)` -- which is where the
    #: parenthesised form comes from. It is read off the list's own data rather
    #: than invented, and those four are the corroboration.
    VALENCE = {
        "Arsenic V": "arsenic (v)",
        "Cadmium II": "cadmium (ii)",
        "Calcium II": "calcium (ii)",
        "Chromium III": "chromium (iii)",
        "Chromium VI": "chromium (vi)",
        "Lead II": "lead (ii)",
        "Mercury II": "mercury (ii)",
        "Nickel II": "nickel (ii)",
        "Vanadium V": "vanadium (v)",
        "Zinc II": "zinc (ii)",
    }

    #: Every `X, ion` name BAFU ships.
    IONS = {
        "Ammonium, ion": "ammonium ion",
        "Arsenic, ion": "arsenic ion",
        "Iron, ion": "iron ion",
        "Perchlorate, ion": "perchlorate ion",
    }

    def test_every_valence_name_bafu_ships(self):
        for name, expected in sorted(self.VALENCE.items()):
            with self.subTest(name=name):
                self.assertEqual(valence_in_parentheses(name), expected)

    def test_every_ion_name_bafu_ships(self):
        for name, expected in sorted(self.IONS.items()):
            with self.subTest(name=name):
                self.assertEqual(unspecified_ion(name), expected)

    def test_a_geography_suffix_is_not_a_valence(self):
        """`VI` is also the ISO code for the Virgin Islands, and BAFU writes
        geographies with a comma -- which is what keeps the two apart (#65)."""
        for name in ("Water, VI", "Water, RER", "Nitrogen dioxide, RAF"):
            with self.subTest(name=name):
                self.assertIsNone(valence_in_parentheses(name))

    def test_the_base_of_a_valence_is_a_single_element_word(self):
        """Valence notation is about elements. Requiring one word keeps the
        rule off anything else ending in a capital letter."""
        for name in ("Some flow name V", "Water, cooling V"):
            with self.subTest(name=name):
                self.assertIsNone(valence_in_parentheses(name))

    def test_an_ion_alias_can_never_reach_the_uncharged_element(self):
        """The failure #286 names, and the guarantee is the shape of the alias.

        It always ends in ` ion`. A neutral element is spelled `Iron` and
        answers to `Iron`, so nothing this produces can land on it."""
        for name in self.IONS:
            with self.subTest(name=name):
                alias = unspecified_ion(name)
                self.assertTrue(alias.endswith(" ion"))
                self.assertNotEqual(alias, name.split(",")[0].strip().lower())

    def test_an_element_on_its_own_is_neither(self):
        for name in ("Iron", "Perchlorate", "Arsenic", ""):
            with self.subTest(name=name):
                self.assertIsNone(valence_in_parentheses(name))
                self.assertIsNone(unspecified_ion(name))

    def test_the_entry_point_offers_both(self):
        self.assertEqual(simapro_name_aliases("Arsenic V"), ["arsenic (v)"])
        self.assertEqual(simapro_name_aliases("Iron, ion"), ["iron ion"])


class FallbackOrderTestCase(unittest.TestCase):
    """Where the derived spelling sits: last, and only once everything failed.

    That ordering is what makes this safe, more than the rule is. A derived
    name is a weaker claim than a registry number or a name the vendor shipped,
    so it is reached only after both come back empty, and a row that matches by
    CAS or by its own label never has one considered at all.

    The alternative -- writing the spelling on as an alternative label before
    matching -- puts it in front of every such row, including the ones already
    matching, where the CAS branch narrows on labels and a wrong spelling can
    move a match that was right. Two of BAFU's names are exactly that row.
    """

    CHLOROBENZENE = "fo-chlorobenzene"
    OTHER = "fo-other"

    def _indexes(self, *, simapro, cas_index=None):
        return MergeIndexes(
            flow_objects_by_id={},
            flow_object_label_by_id={},
            cas_index=cas_index or {},
            ec_index={},
            label_index={"chlorobenzene": {self.CHLOROBENZENE}},
            pref_label_index={"chlorobenzene": {self.CHLOROBENZENE}},
            qualifier_index={},
            flow_objects_with_cas=set(),
            context_expectations=ContextExpectations(
                _by_source_context={}, _source_label="test"
            ),
            consensus_context_strings={},
            prepared_context_decisions={},
            mapping_file=None,
            source=_source(simapro=simapro),
        )

    def _row(self, name, *, cas=""):
        return SourceRow(
            uuid="s-1", name=name, synonyms=[], labels=[name],
            context=["emissions to air"], context_iri="", context_normalized=(),
            unit="kg", unit_iri="", cas=cas, ec="",
        )

    def _resolve(self, row, indexes):
        return resolve_flow_object(
            row=row, indexes=indexes, accumulator=MergeAccumulator()
        )

    def test_a_row_nothing_else_placed_matches_on_the_derived_spelling(self):
        resolution = self._resolve(
            self._row("Benzene, Chloro-"), self._indexes(simapro=True)
        )
        self.assertIsNotNone(resolution)
        self.assertEqual(resolution.flow_object_id, self.CHLOROBENZENE)
        self.assertEqual(resolution.basis, "simapro-name-pattern")

    def test_a_list_simapro_did_not_shape_is_left_unmatched(self):
        """The gate. On ecoinvent this is a guess at a structure, not a fix."""
        self.assertIsNone(
            self._resolve(
                self._row("Benzene, Chloro-"), self._indexes(simapro=False)
            )
        )

    def test_a_row_its_own_name_places_never_reaches_the_pattern(self):
        """`basis` says `label`: the shipped name won and nothing was derived."""
        resolution = self._resolve(
            self._row("chlorobenzene"), self._indexes(simapro=True)
        )
        self.assertEqual(resolution.basis, "label")

    def test_a_row_its_cas_places_never_reaches_the_pattern(self):
        """The case the ordering exists for.

        `2-Butene, 2-methyl-` and `Dioxin, 2,3,7,8 Tetrachlorodibenzo-p-` both
        matched in the first full build. Reached before matching rather than
        after, a wrong derived spelling would have been extra evidence on a row
        that was already right."""
        resolution = self._resolve(
            self._row("Benzene, Chloro-", cas="7440-00-0"),
            self._indexes(simapro=True, cas_index={"7440-00-0": {self.OTHER}}),
        )
        self.assertEqual(resolution.flow_object_id, self.OTHER)
        self.assertEqual(resolution.basis, "cas")

    def test_a_phrase_row_resolves_to_the_spelling_the_list_uses(self):
        """`Heat, waste` is the fourteen-row case (#288): BAFU's waste heat
        minted a second `Heat, Waste` object beside EF 3.1's `Waste Heat`."""
        indexes = self._indexes(simapro=True)
        indexes.label_index["waste heat"] = {"fo-waste-heat"}
        resolution = self._resolve(self._row("Heat, waste"), indexes)
        self.assertEqual(resolution.flow_object_id, "fo-waste-heat")
        self.assertEqual(resolution.basis, "simapro-name-pattern")

    def test_a_phrase_row_on_a_list_simapro_did_not_shape_stays_unmatched(self):
        """The same gate the chemical rule has, for the same reason: read
        anywhere else, a comma is not a habit and swapping across it is a
        guess."""
        indexes = self._indexes(simapro=False)
        indexes.label_index["waste heat"] = {"fo-waste-heat"}
        self.assertIsNone(self._resolve(self._row("Heat, waste"), indexes))

    def test_a_phrase_row_its_cas_ties_is_reached_after_the_tie_is_declared(self):
        """The row the ordering used to leave unmatched, and now does not.

        `Water, lake` and `Water, river` carry water's registry number,
        7732-18-5, which twelve flow objects share; `Gas, natural` carries
        8006-14-2, which the coal-mine off-gas wears as well as natural gas
        (#80). The CAS branch runs first, so all three came back
        `multiple-flow-object-candidates` in the first full build with BAFU
        registered, and a derived name was never consulted for a row that got
        that far.

        #86 is that question answered. The spelling is still not extra
        evidence during matching -- it is asked once every rule has run and the
        answer is *several substances*, which is a row that was going to be
        reported unmatched either way. So a wrong alias still costs a review
        rather than moving a match that was right, which is the ordering this
        file defends, and it has to hit a candidate's **preferred** name: `lake
        water` is what the list calls that substance, not one of the things it
        is also called.
        """
        indexes = self._indexes(
            simapro=True, cas_index={"7732-18-5": {self.OTHER, "fo-lake-water"}}
        )
        indexes.label_index["lake water"] = {"fo-lake-water"}
        indexes.pref_label_index["lake water"] = {"fo-lake-water"}
        resolution = self._resolve(
            self._row("Water, lake", cas="7732-18-5"), indexes
        )
        self.assertEqual(resolution.flow_object_id, "fo-lake-water")
        self.assertEqual(resolution.basis, "cas+preferred-name")

    def test_an_alias_that_is_only_an_alternative_name_does_not_break_the_tie(self):
        """The guard on the rule above. A substance that merely *also* goes by
        the spelling is not the one the row names, and eleven of the twelve
        waters answer to `water` that way -- correctly, since they are all
        water. Only the preferred name counts."""
        indexes = self._indexes(
            simapro=True, cas_index={"7732-18-5": {self.OTHER, "fo-lake-water"}}
        )
        indexes.label_index["lake water"] = {"fo-lake-water"}
        self.assertIsNone(
            self._resolve(self._row("Water, lake", cas="7732-18-5"), indexes)
        )

    def test_a_valence_row_resolves_to_the_parenthesised_form(self):
        indexes = self._indexes(simapro=True)
        indexes.label_index["arsenic (v)"] = {"fo-arsenic-v"}
        resolution = self._resolve(self._row("Arsenic V"), indexes)
        self.assertEqual(resolution.flow_object_id, "fo-arsenic-v")
        self.assertEqual(resolution.basis, "simapro-name-pattern")

    def test_several_ionic_forms_are_reported_rather_than_chosen_between(self):
        """What decides an unspecified ion is the list's inventory, not the
        environment it was emitted to.

        Where the list holds one ionic form under the name, that is what the
        row means. Where it holds several -- iron is ferrous and ferric, and
        they are different substances -- picking one would be assigning a
        toxicity and a mobility by regex. `multiple-flow-object-candidates` is
        the reviewable answer.

        No redox guess is made or wanted: `Iron, ion` arrives in `emissions to
        water / unspecified`, which names no water body, and Fe(II) against
        Fe(III) is decided by conditions the compartment does not record.
        """
        indexes = self._indexes(simapro=True)
        indexes.label_index["iron ion"] = {"fo-iron-2", "fo-iron-3"}
        accumulator = MergeAccumulator()
        resolution = resolve_flow_object(
            row=self._row("Iron, ion"), indexes=indexes, accumulator=accumulator
        )
        self.assertIsNone(resolution)

    def test_one_ionic_form_is_unambiguous_and_matches(self):
        """Perchlorate's case. `Perchlorate` carries charge -1 and the formula
        `ClO4-`: there is no neutral perchlorate, so the alias is the same
        species spelled twice rather than a charge being assigned."""
        indexes = self._indexes(simapro=True)
        indexes.label_index["perchlorate ion"] = {"fo-perchlorate"}
        resolution = self._resolve(self._row("Perchlorate, ion"), indexes)
        self.assertEqual(resolution.flow_object_id, "fo-perchlorate")

    def test_an_unspecified_ion_does_not_fall_back_to_the_element(self):
        """`Iron, ion` must not become `Iron`.

        The list holds `Iron(2+)` and `Iron(3+)`, which are different
        substances, and the row does not say which. Unmatched is the reviewable
        outcome; the neutral element would be a wrong one."""
        indexes = self._indexes(simapro=True)
        indexes.label_index["iron"] = {"fo-iron-metal"}
        indexes.pref_label_index["iron"] = {"fo-iron-metal"}
        self.assertIsNone(self._resolve(self._row("Iron, ion"), indexes))

    def test_a_spelling_the_list_does_not_hold_stays_unmatched(self):
        """The reported, reviewable outcome -- not a silent guess.

        `perfluorocyclopropane` and `2-(thiocyanatemethylthio)benzothiazole` are
        BAFU's two, and are meant to become new flows."""
        self.assertIsNone(
            self._resolve(
                self._row("Propane, perfluorocyclo-"), self._indexes(simapro=True)
            )
        )


class GeographySuffixTestCase(unittest.TestCase):
    """`Water, AE` and `Water, RER` (#65).

    BAFU writes the country into the flow's name. This list does not model
    geography there at all -- it records where a flow happened in the flow's
    context -- so 181 names arrive describing water we already hold, spelled
    with a place on the end, and match nothing. Read as shipped they become 181
    parallel waters; read with the place taken out they are eleven flows.

    The rule is here; `test_bafu_extraction` covers it being applied. It is a
    **split**, not an alias: both halves are returned, both exactly as the
    vendor spelled them, and it is the adapter that decides what to do with
    each. That is what lets the place become a field of its own instead of a
    second name to try.
    """

    #: Every regionalised name BAFU 2026 v1 ships, as base label and the codes
    #: written onto it. The real set rather than a sample, so a release that
    #: regionalises something new fails here instead of drifting.
    BAFU_REGIONALISED = {
        "Nitrogen dioxide": ["RAF"],
        "Occupation, traffic area, rail network": ["CH"],
        "Occupation, traffic area, rail/road embankment": ["CH"],
        "Water": """
            AE AO AR AT AU AZ BA BE BO BR CA CH CL CM CN CO CS CZ
            DE DK DZ EC EG ES Europe FI FR GB GQ GR HR HU ID IE IL
            IN IQ IR IS IT JP KE KR KW KZ LU LY MA MK MX MY MZ NG
            NL NO NZ OECD OM PE PL PT QA RAF RER RO RS RU SA SE SI
            SK TH TM TR TT TW UA US UZ VE ZA
            """.split(),
        "Water, cooling, unspecified natural origin": "CH CN DE KR RER US".split(),
        "Water, embodied in product": "CH ES KE MX PE".split(),
        "Water, lake": ["RER"],
        "Water, river": "CH KE RER".split(),
        "Water, unspecified": ["Europe"],
        "Water, unspecified natural origin": """
            AE AO AR AT AU AZ BA BE BO BR CA CH CL CM CN CO CZ DE
            DK DZ EC EG ES FI FR GB GLO GQ GR HR HU ID IE IL IN IQ
            IR IT JP KE KR KW KZ LU LY MA MK MX MY NG NL NO NZ
            OECD OM PE PL PT QA RAF RER RO RS RU SA SE SI SK TH TM
            TR TT TW UA US UZ VE ZA
            """.split(),
        "Water, well": "CH GLO RER".split(),
    }

    def _shipped(self):
        for base, codes in sorted(self.BAFU_REGIONALISED.items()):
            for code in codes:
                yield f"{base}, {code}", base, code

    def test_every_regionalised_name_bafu_ships_loses_its_place(self):
        for name, base, _code in self._shipped():
            with self.subTest(name=name):
                self.assertEqual(geography_base(name), base)

    def test_the_shipped_set_is_larger_than_the_issue_measured(self):
        """181, where #65 counted 177. The four it missed are `Water, Europe`,
        `Water, OECD`, `Water, unspecified natural origin, OECD` and `Water,
        unspecified, Europe` -- regionalised names whose place is spelled as a
        word, which a rule reading two- and three-letter codes cannot see."""
        self.assertEqual(sum(1 for _ in self._shipped()), 181)
        self.assertEqual(len(self.BAFU_REGIONALISED), 11)

    def test_both_halves_come_back_as_the_vendor_spelled_them(self):
        """Nothing is lower-cased or tidied. The name is what the flow will be
        called, and the code is what its identity is keyed on, so a rule that
        rewrote either would be deciding something that is not its to
        decide."""
        self.assertEqual(
            split_geography_suffix("Water, cooling, unspecified natural origin, US"),
            ("Water, cooling, unspecified natural origin", "US"),
        )

    def test_a_titlecased_name_is_read_the_same_way(self):
        """Matching is case-insensitive even though the output is not, so a
        release that changes its casing is still read. The base label is what
        makes that safe, not the capitalisation of the code."""
        self.assertEqual(
            split_geography_suffix("Water, Unspecified Natural Origin, KW"),
            ("Water, Unspecified Natural Origin", "KW"),
        )

    def test_a_withdrawn_code_is_split_as_written(self):
        """`CS` was Serbia and Montenegro; ISO withdrew it when the state
        dissolved in 2006. The splitter still hands it back as `CS`, because
        this half is about the row: it is what BAFU shipped and what the flow's
        identity is seeded on."""
        self.assertEqual(split_geography_suffix("Water, CS"), ("Water", "CS"))

    #: Every regionalised land name AGRIBALYSE 3.2 ships (#351) -- the same
    #: habit as BAFU's rail rows, on four base labels. The real set rather
    #: than a sample, for the reason BAFU's set above is.
    AGRIBALYSE_REGIONALISED = {
        "Occupation, annual crop": ["CN", "TH"],
        "Transformation, from annual crop": ["CN", "TH"],
        "Transformation, from permanent crop": ["CN", "TH"],
        "Transformation, to annual crop": ["CN", "TH"],
    }

    def test_every_regionalised_land_name_agribalyse_ships_loses_its_place(self):
        for base, codes in sorted(self.AGRIBALYSE_REGIONALISED.items()):
            for code in codes:
                name = f"{base}, {code}"
                with self.subTest(name=name):
                    self.assertEqual(split_geography_suffix(name), (base, code))

    def test_a_land_label_the_whitelist_does_not_carry_keeps_its_tail(self):
        """The whitelist stays exactly as wide as what a vendor ships. AGRIBALYSE
        regionalises no `to permanent crop` row, so that spelling is not
        whitelisted, and a name that ends in a country code anyway is handed
        back whole rather than split on a guess."""
        self.assertIsNone(
            split_geography_suffix("Transformation, to permanent crop, CN")
        )

    #: Every regionalised *substance* AGRIBALYSE 3.2 ships (#190, #192): nine
    #: bases once the splitter reads the whole file rather than the four rows
    #: #364 patched by synonym. The real set rather than a sample, as above --
    #: and the custom geographies (`RAS`, `RNA`, the US grid regions) are in
    #: these lists on purpose, each glossed by the vendor's own row comment.
    AGRIBALYSE_REGIONALISED_SUBSTANCES = {
        "NMVOC, non-methane volatile organic compounds": "FR RER".split(),
        "Nitrogen oxides": ["CN"],
        "Sulfur oxides": ["FR"],
        "Sulfur dioxide": "AT BE BG CN CZ DE DK EE ES FR GB GR HU IT NL PL PT RO SE".split(),
        "Ammonia": "AU CN FR RAF RAS RER RLA RNA RU TH".split(),
        "Nitrate": "CN TH".split(),
        "Nitrogen monoxide": "CN TH".split(),
        "Phosphorus": "CN RER TH".split(),
        "Water, turbine use, unspecified natural origin": (
            "AR ASCC AT AU BA BE BG BR CA CH CL CN CO CZ DE DK EE ES FI FR "
            "GB GLO GR HICC HR HU ID IE IN IR IS IT JP KR LT LU LV MK MX MY "
            "NL NO NP PE PL PT RER RFC RNA RO RS RU SE SERC SI SK TH TR TRE "
            "TW TZ UA US ZA"
        ).split(),
    }

    def test_every_regionalised_substance_agribalyse_ships_loses_its_place(self):
        for base, codes in sorted(self.AGRIBALYSE_REGIONALISED_SUBSTANCES.items()):
            for code in codes:
                name = f"{base}, {code}"
                with self.subTest(name=name):
                    self.assertEqual(split_geography_suffix(name), (base, code))

    def test_a_substance_the_whitelist_does_not_carry_keeps_its_tail(self):
        """AGRIBALYSE also ships `COD (Chemical Oxygen Demand), FR` and
        `BOD5 (Biological Oxygen Demand), CN`, and those are not whitelisted
        here: #187 gave them the published name as a synonym, which places
        the row without reading a place off it. A name that ends in a code
        anyway is handed back whole."""
        for name in (
            "COD (Chemical Oxygen Demand), FR",
            "BOD5 (Biological Oxygen Demand), CN",
            "Carbon dioxide, FR",
        ):
            with self.subTest(name=name):
                self.assertIsNone(split_geography_suffix(name))

    def test_a_withdrawn_code_is_reported_as_its_successor(self):
        """And this half is about the place. BAFU ships `Water, CS` in 64
        exchanges with real amounts, so it is not a dead entry -- it is read as
        Serbia, which is the successor holding the territory."""
        self.assertEqual(canonical_geography_code("CS"), "RS")
        self.assertEqual(WITHDRAWN_GEOGRAPHY_CODES, {"CS": "RS"})

    def test_keeping_the_two_apart_is_what_stops_two_rows_fusing(self):
        """`Water, CS` and `Water, RS` are two rows BAFU ships. Canonicalising
        in the splitter would give them one identity the day a release puts
        both in one context, and one of them would vanish."""
        self.assertNotEqual(
            split_geography_suffix("Water, CS"), split_geography_suffix("Water, RS")
        )
        self.assertEqual(
            canonical_geography_code("CS"), canonical_geography_code("RS")
        )

    def test_a_code_that_was_never_withdrawn_is_returned_unchanged(self):
        for code in ("CH", "IN", "RER", "OECD"):
            with self.subTest(code=code):
                self.assertEqual(canonical_geography_code(code), code)

    def test_the_whole_of_iso_3166_is_admitted_not_only_what_bafu_uses(self):
        """#65 asks that a release adding a country not need the rule
        rewritten. BAFU uses 76 alpha-2 codes today; all 249 are accepted, and
        the base labels are what keeps that safe."""
        shipped = {code for _name, _base, code in self._shipped()}
        self.assertEqual(shipped - GEOGRAPHY_CODES, set())
        for unused in ("PY", "VU", "SS", "TV"):
            with self.subTest(code=unused):
                self.assertNotIn(unused, shipped)
                self.assertEqual(geography_base(f"Water, {unused}"), "Water")

    def test_a_region_code_is_admitted_one_at_a_time(self):
        """ISO 3166 is a standard with a defined meaning for every member;
        these are a vendor's list with none behind them. Each is its own
        decision, and `RoW` -- "everywhere this dataset does not cover", which
        has no fixed extent -- is deliberately not one of them."""
        for code in ("Europe", "GLO", "OECD", "RAF", "RER"):
            with self.subTest(code=code):
                self.assertEqual(geography_base(f"Water, {code}"), "Water")
        self.assertIsNone(geography_base("Water, RoW"))

    def test_a_base_label_the_list_does_not_name_is_left_alone(self):
        """The whitelist is the whole safety of the rule. `Methane, NL` is a
        perfectly well-formed regionalised name and is still declined: nothing
        has agreed that any list holds a methane the suffix belongs to, and
        inventing one from a comma is the failure being avoided. (`Ammonia,
        NL` used to be the example here, until #192's review found AGRIBALYSE
        genuinely regionalising ammonia and admitted the base.)"""
        for name in ("Methane, NL", "Carbon dioxide, CH", "Copper, US"):
            with self.subTest(name=name):
                self.assertIsNone(geography_base(name))

    def test_indium_is_not_india(self):
        """The case this rule exists not to break. BAFU ships `Silver, 0.007%
        in sulfide, Ag 0.004%, Pb, Zn, Cd, In`, where `In` is indium, and
        `Water, IN`, where `IN` is India. Capitalisation is the only thing
        separating them in the name -- so the rule does not rest on it, and
        declines the first on its base label instead."""
        self.assertIsNone(
            geography_base("Silver, 0.007% in sulfide, Ag 0.004%, Pb, Zn, Cd, In")
        )
        self.assertEqual(geography_base("Water, IN"), "Water")

    def test_a_water_name_with_no_place_on_the_end_is_left_alone(self):
        """Every other `Water, …` name BAFU ships. Each ends in a
        comma-separated word, and none of those words is a place."""
        for name in (
            "Water",
            "Water, fossil",
            "Water, lake",
            "Water, river",
            "Water, well",
            "Water, process, surface",
            "Water, salt, ocean",
            "Water, salt, sole",
            "Water, turbine use, unspecified natural origin",
        ):
            with self.subTest(name=name):
                self.assertIsNone(geography_base(name))

    def test_the_place_has_to_be_the_last_field(self):
        """`Water, CH, deep` says something about the water after the place,
        and this rule does not know what. Left alone rather than reordered."""
        self.assertIsNone(geography_base("Water, CH, deep"))

    def test_a_space_before_the_comma_is_declined(self):
        """A space before a comma is a typo, and a rule that reads through one
        is guessing at what the writer meant."""
        self.assertIsNone(geography_base("Water , CH"))

    def test_a_missing_space_after_the_comma_is_read(self):
        """Where `flowmapper.fields.split_location_suffix` requires that space,
        here the base labels carry the safety it was carrying there, so a
        release shipping `Water,CH` is read rather than silently skipped."""
        self.assertEqual(geography_base("Water,CH"), "Water")
        self.assertEqual(geography_base("Water,  \tCH"), "Water")

    def test_a_lone_place_is_not_a_flow(self):
        for name in ("", ", CH", "CH"):
            with self.subTest(name=name):
                self.assertIsNone(geography_base(name))

    def test_the_alias_entry_point_does_not_offer_it(self):
        """Deliberately absent. A geography is not another name for the
        substance, so offering `water` as a spelling of `Water, AE` would put
        the place-stripped name in front of the matcher while leaving the row
        still called `Water, AE` -- which is the shape this stopped being."""
        self.assertEqual(simapro_name_aliases("Water, AE"), [])
        self.assertEqual(simapro_name_aliases("Water"), [])

    def test_a_valence_is_not_a_place_and_a_place_is_not_a_valence(self):
        """`VI` is the Virgin Islands and also six. The comma is what separates
        them: `Vanadium V` is a valence, `Water, VI` is a place."""
        self.assertIsNone(valence_in_parentheses("Water, VI"))
        self.assertEqual(geography_base("Water, VI"), "Water")
        self.assertIsNone(geography_base("Vanadium V"))


class FetchedRegionalisedNamesTestCase(unittest.TestCase):
    """The literal table above, checked against the flows BAFU actually ships.

    The table is written out rather than computed so the rule can be tested
    without the vendor archive, which is not downloadable and not checked in.
    This is the other half of that trade: where the list has been fetched, the
    two are required to agree, so a release that regionalises a new flow --  or
    stops regionalising one -- fails here rather than quietly changing what the
    rule covers.

    The fetched list is read through `original_name`, because that is the only
    place a regionalised name survives once the adapter has run: `name` is the
    flow without its place, and this asks whether the rule saw the same 181
    names the table claims.

    Skips where the list has not been fetched, as the extraction tests do.
    """

    @classmethod
    def setUpClass(cls):
        source = known_source_lists()["bafu-2026-v1"]
        if not source.flows_path.exists():
            raise unittest.SkipTest(
                f"{source.flows_path.name} not present; run "
                f"`{source.fetch_command}`"
            )
        cls.flows = orjson.loads(source.flows_path.read_bytes())
        cls.names = sorted({str(flow.get("name") or "") for flow in cls.flows})
        cls.shipped_names = sorted(
            {str(flow["original_name"]) for flow in cls.flows if "original_name" in flow}
        )

    def test_the_table_is_every_name_the_rule_split(self):
        expected = {name for name, _base, _code in GeographySuffixTestCase()._shipped()}
        self.assertEqual(set(self.shipped_names), expected)

    def test_the_table_agrees_with_the_adapter_on_both_halves(self):
        """Not only which names were split, but into what. The base is the
        flow's name and the code is what its identity is seeded on, so a table
        that agreed on the names alone would not be pinning much."""
        expected = {
            name: (base, code)
            for name, base, code in GeographySuffixTestCase()._shipped()
        }
        for flow in self.flows:
            if "original_name" not in flow:
                continue
            with self.subTest(name=flow["original_name"]):
                base, code = expected[flow["original_name"]]
                self.assertEqual(flow["name"], base)
                self.assertEqual(flow["location"], canonical_geography_code(code))

    def test_nothing_else_in_the_list_is_touched(self):
        """1,010 distinct names now, from 1,187 before. Every one of them is a
        name BAFU wrote, and none of them still carries a place."""
        self.assertEqual(len(self.names), 1010)
        self.assertEqual(len(self.shipped_names), 181)
        self.assertEqual([n for n in self.names if geography_base(n)], [])

    def test_which_base_labels_bafu_also_ships_unregionalised(self):
        """Seven of the eleven, so taking the place out usually lands the row on
        a sibling in the same list rather than reaching for a stranger.

        The four that it does not are named here rather than left to be
        discovered. Two of them -- `Water, cooling, unspecified natural origin`
        and `Water, unspecified natural origin` -- are not really absent: BAFU
        ships each of them with the unit written into the name instead, as
        `…/m3`, which is #67's habit and not this one. Undoing that habit is
        what would reunite them."""
        unregionalised = {
            str(flow["name"]).casefold()
            for flow in self.flows
            if "location" not in flow
        }
        missing = sorted(
            base
            for base in GeographySuffixTestCase.BAFU_REGIONALISED
            if base.casefold() not in unregionalised
        )
        self.assertEqual(
            missing,
            [
                "Water, cooling, unspecified natural origin",
                "Water, embodied in product",
                "Water, unspecified",
                "Water, unspecified natural origin",
            ],
        )
        for base in ("Water, cooling, unspecified natural origin",
                     "Water, unspecified natural origin"):
            with self.subTest(base=base):
                self.assertIn(f"{base}/m3".casefold(), unregionalised)


#: Every unit-suffixed name BAFU 2026 v1 ships, with the unit its record
#: declares and what the name is once the copy comes off.  The real set rather
#: than a sample, for the same reason the inverted names above are: this is the
#: whole of what the rule has to read, and a release adding a shape it reads
#: differently should fail here.
#:
#: The unit given here is the one the record declares for that spelling.  Two
#: of these names are also shipped over a `Nm3` record, where the name and the
#: field disagree and nothing is stripped -- see `BAFU_UNIT_DISAGREES`.
BAFU_UNIT_SUFFIXED = (
    ("Gas, mine, off-gas, process, coal mining/m3", "m3",
     "Gas, mine, off-gas, process, coal mining"),
    ("Gas, natural/m3", "m3", "Gas, natural"),
    ("Waste water/m3", "m3", "Waste water"),
    ("Water, cooling, unspecified natural origin/m3", "m3",
     "Water, cooling, unspecified natural origin"),
    ("Water, process, unspecified natural origin/kg", "kg",
     "Water, process, unspecified natural origin"),
    ("Water, process, unspecified natural origin/m3", "m3",
     "Water, process, unspecified natural origin"),
    ("Water, unspecified natural origin/m3", "m3",
     "Water, unspecified natural origin"),
    ("Water/m3", "m3", "Water"),
    ("Wood, unspecified, standing/kg", "kg", "Wood, unspecified, standing"),
    ("Wood, unspecified, standing/m3", "m3", "Wood, unspecified, standing"),
)

#: The two rows whose name and unit field disagree about the measure.
BAFU_UNIT_DISAGREES = (
    ("Gas, mine, off-gas, process, coal mining/m3", "Nm3"),
    ("Gas, natural/m3", "Nm3"),
)

#: Names BAFU ships with a slash that is part of the name.  The tail has a
#: space in it, so the pattern never reaches the unit comparison at all.
BAFU_SLASH_IN_NAME = (
    ("Occupation, traffic area, rail/road embankment", "m2a"),
    ("Transformation, from traffic area, rail/road embankment", "m2"),
    ("Transformation, to traffic area, rail/road embankment", "m2"),
)


class UnitSuffixTestCase(unittest.TestCase):
    """The unit, written into the name after a slash (#67).

    SimaPro keys its flows on names alone, so a substance measured two ways has
    to say which way in the name.  This list carries the unit as its own field,
    so the copy in the name says the same thing twice -- and stops the row
    matching anything, because no flow object anywhere answers to a name with a
    unit stuck on the end.
    """

    def test_every_name_bafu_ships_this_way(self):
        for name, unit, expected in BAFU_UNIT_SUFFIXED:
            with self.subTest(name=name):
                self.assertEqual(name_without_unit_suffix(name, unit), expected)

    def test_a_tail_that_is_not_this_row_s_unit_is_declined(self):
        """`Nm3` is a normal cubic metre: gas at a stated temperature and
        pressure, and a different measure from a cubic metre.  BAFU ships two
        rows spelled `/m3` whose unit field says `Nm3`, so the name and the
        field disagree about which was meant.  That is a curator's question,
        and it is answered in the list's manual fixes."""
        for name, unit in BAFU_UNIT_DISAGREES:
            with self.subTest(name=name):
                self.assertIsNone(name_without_unit_suffix(name, unit))

    def test_a_slash_that_belongs_to_the_name_is_left_alone(self):
        for name, unit in BAFU_SLASH_IN_NAME:
            with self.subTest(name=name):
                self.assertIsNone(name_without_unit_suffix(name, unit))

    def test_a_name_with_no_unit_on_it_is_left_alone(self):
        for name in ("Water", "Iodine, 0.03% in water", "Benzene, chloro-", ""):
            with self.subTest(name=name):
                self.assertIsNone(name_without_unit_suffix(name, "kg"))

    def test_a_row_with_no_unit_strips_nothing(self):
        """The unit field is what makes the tail a duplicate.  With nothing to
        compare against there is no evidence the tail is a unit at all."""
        self.assertIsNone(name_without_unit_suffix("Water/m3", ""))

    def test_the_comparison_is_case_insensitive(self):
        self.assertEqual(name_without_unit_suffix("Water/M3", "m3"), "Water")
        self.assertEqual(name_without_unit_suffix("Water/m3", "M3"), "Water")


class UnitSuffixOverTheWholeListTestCase(unittest.TestCase):
    """Every suffix that is a copy of the unit field comes off (#67).

    This used to be the place where a suffix could survive: where two rows
    would strip to one name in two units, the suffix was read as the only thing
    telling them apart and both kept it.  That is no longer the rule, and the
    reason is that it never worked.  A flow's identity is its substance and its
    context, `(flow_object_id, context_iri)` is unique, and the unit is not in
    it -- so two rows agreeing on a substance and a compartment reach one flow
    whatever their names say.  Keeping the suffix kept two *names* apart above a
    single flow, and cost both rows their match, because no flow object answers
    to a name with a unit stuck on the end.

    Whether two such rows are one quantity is still a real question.  It is
    answered by a curator reading the vendor's archive and stating a conversion
    in that list's manual fixes, not by a rule reading names.
    """

    def test_a_suffix_that_is_only_a_copy_comes_off(self):
        self.assertEqual(
            unit_suffix_rewrites([("Water/m3", "m3"), ("Carbon dioxide", "kg")]),
            {("Water/m3", "m3"): "Water"},
        )

    def test_two_units_under_one_name_both_lose_the_suffix(self):
        """BAFU's `Water, process, unspecified natural origin` in kg beside the
        same name in m3 -- the pair #67 named as the thing to watch, and the
        one this rule used to decline.

        Both strip, and both rows keep their own uuid, their own unit and their
        own mapping back to the vendor.  What they no longer keep is two
        published names for a flow the list had already joined.
        """
        self.assertEqual(
            unit_suffix_rewrites([
                ("Water, process, unspecified natural origin/kg", "kg"),
                ("Water, process, unspecified natural origin/m3", "m3"),
            ]),
            {
                ("Water, process, unspecified natural origin/kg", "kg"):
                    "Water, process, unspecified natural origin",
                ("Water, process, unspecified natural origin/m3", "m3"):
                    "Water, process, unspecified natural origin",
            },
        )

    def test_a_row_is_asked_only_about_its_own_unit(self):
        """The other half of the same change: what the rest of the list holds
        cannot make a redundant suffix survive.  Written as a pair sharing a
        base name, because that is the shape that used to change the answer."""
        rewrites = unit_suffix_rewrites([
            ("Water, process, unspecified natural origin/kg", "kg"),
            ("Water, process, unspecified natural origin/m3", "m3"),
            ("Water/m3", "m3"),
        ])
        self.assertEqual(
            rewrites[("Water/m3", "m3")], "Water"
        )
        self.assertEqual(len(rewrites), 3)

    def test_a_tail_that_is_not_the_row_s_own_unit_still_survives(self):
        """The one way a suffix stays, and it is decided per row rather than
        over the list: `Nm3` is not `m3`, so the name and the unit field
        disagree about what was measured and neither this nor `load_flows`
        guesses which was meant."""
        self.assertEqual(unit_suffix_rewrites(BAFU_UNIT_DISAGREES), {})

    def test_the_same_pair_in_one_unit_comes_off(self):
        """What BAFU's standing wood is, once the manual fixes have converted
        the mass rows to cubic metres: one quantity written two ways, and
        nothing being told apart."""
        rows = [
            ("Wood, unspecified, standing/m3", "m3"),
            ("Wood, unspecified, standing/m3", "m3"),
        ]
        self.assertEqual(
            unit_suffix_rewrites(rows),
            {("Wood, unspecified, standing/m3", "m3"): "Wood, unspecified, standing"},
        )

    def test_the_units_are_compared_case_insensitively(self):
        """`kg` and `KG` are one unit, and a list that spells them both ways
        must not read that as two."""
        self.assertEqual(
            unit_suffix_rewrites([("Water, process/kg", "kg"),
                                  ("Water, process/KG", "KG")]),
            {("Water, process/kg", "kg"): "Water, process",
             ("Water, process/KG", "KG"): "Water, process"},
        )

    def test_every_name_bafu_ships_this_way_loses_its_unit(self):
        """Read off the shipped names above rather than restated.

        All ten, with nothing kept back.  The two shapes that used to survive
        this rule are both gone from it: the pair sharing a base name in two
        units is no longer declined, and the rows whose unit a manual fix
        rewrites -- standing wood at 0.00204 m3/kg, process water at 0.001 --
        are renamed by hand in that file, because after the conversion the
        suffix is no longer a copy of the row's own unit and this rule rightly
        stops recognising it.
        """
        rewrites = unit_suffix_rewrites((n, u) for n, u, _ in BAFU_UNIT_SUFFIXED)
        self.assertEqual(
            rewrites,
            {(name, unit): base for name, unit, base in BAFU_UNIT_SUFFIXED},
        )


class PreparingARowTestCase(unittest.TestCase):
    """Both splits at once, for a row that reached matching by no other route.

    A build takes the place out of a name in the adapter and the unit out of it
    in `load_flows`, and the two points are far apart for reasons the module
    docstring gives. Somebody who hands this project one row and asks where it
    goes has been through neither, so their row arrives spelled the way SimaPro
    spells it -- and `Wood, unspecified, standing/m3` reaches matching as a
    string no flow object in any list answers to, which reads as "we do not hold
    standing wood" when the truth is that the question was never asked (#328).
    """

    def test_the_unit_comes_off_the_name(self):
        prepared = prepare_row_for_matching("Wood, unspecified, standing/m3", "m3")
        self.assertEqual(prepared.name, "Wood, unspecified, standing")
        self.assertEqual(prepared.steps, ("unit-suffix",))

    def test_the_place_comes_off_the_name(self):
        prepared = prepare_row_for_matching("Water, AE", "m3")
        self.assertEqual(prepared.name, "Water")
        self.assertEqual(prepared.location, "AE")
        self.assertEqual(prepared.steps, ("geography",))

    def test_a_name_carrying_both_loses_both_in_that_order(self):
        """The order is not a preference, it is the only one that works.

        `Water, AE/m3` is a unit stuck on a regionalised name. Taking the place
        off first leaves `Water/m3`, and the geography rule would then be
        reading `m3` as a country code -- which it declines, so the place would
        survive into matching and the row would keep a name nothing answers to.
        """
        prepared = prepare_row_for_matching("Water, AE/m3", "m3")
        self.assertEqual(prepared.name, "Water")
        self.assertEqual(prepared.location, "AE")
        self.assertEqual(prepared.steps, ("unit-suffix", "geography"))

    def test_the_name_as_sent_comes_back_with_it(self):
        """Not decoration: a name a rule rewrote is still a name the row is
        known by, and `_strip_unit_suffixes` keeps the vendor's spelling as a
        synonym for exactly this reason."""
        prepared = prepare_row_for_matching("Water, AE/m3", "m3")
        self.assertEqual(prepared.shipped_name, "Water, AE/m3")

    def test_a_tail_that_is_not_this_row_s_unit_is_left_alone(self):
        """The whole safety of the unit rule, and preparation does not widen it.

        BAFU ships `Wood, unspecified, standing/m3` in m3 and `Wood,
        unspecified, standing/kg` in kg. A row whose name says one measure and
        whose field says another is a curator's question, not a pattern's.
        """
        prepared = prepare_row_for_matching("Wood, unspecified, standing/m3", "kg")
        self.assertEqual(prepared.name, "Wood, unspecified, standing/m3")
        self.assertEqual(prepared.steps, ())
        self.assertEqual(prepared.shipped_name, "")

    def test_a_name_nothing_was_taken_out_of_is_returned_unchanged(self):
        prepared = prepare_row_for_matching("Benzene", "kg")
        self.assertEqual(prepared.name, "Benzene")
        self.assertEqual(prepared.steps, ())
        self.assertEqual(prepared.location, "")

    def test_preparing_a_prepared_row_changes_nothing(self):
        """A caller may hand over rows an exporter already split, and both
        halves of a build's own list arrive here already prepared."""
        once = prepare_row_for_matching("Water, AE/m3", "m3")
        twice = prepare_row_for_matching(once.name, "m3")
        self.assertEqual(twice.name, once.name)
        self.assertEqual(twice.steps, ())

    def test_every_step_it_runs_is_one_it_names(self):
        """`PREPARATION_STEPS` is what a prepared row reports itself in terms
        of, so a step added to the function has to be added there too."""
        for name, unit in (("Water, AE/m3", "m3"), ("Water/m3", "m3"), ("Water, AE", "m3")):
            with self.subTest(name=name):
                prepared = prepare_row_for_matching(name, unit)
                self.assertTrue(set(prepared.steps) <= set(PREPARATION_STEPS))

    def test_every_regionalised_name_bafu_ships_is_prepared_the_same_way(self):
        """Against the adapter's own rule rather than a restatement of it: what
        preparation does to a name has to be what extraction did to it, or a
        caller's copy of BAFU reaches different flows than BAFU does."""
        for shipped, base, code in GeographySuffixTestCase()._shipped():
            with self.subTest(name=shipped):
                prepared = prepare_row_for_matching(shipped, "kg")
                self.assertEqual(prepared.name, base)
                self.assertEqual(prepared.location, code)
                self.assertEqual(prepared.steps, ("geography",))

    def test_every_unit_suffixed_name_bafu_ships_is_prepared_the_same_way(self):
        """The other half, against the same shipped table `load_flows` is
        checked on."""
        for shipped, unit, base in BAFU_UNIT_SUFFIXED:
            with self.subTest(name=shipped):
                prepared = prepare_row_for_matching(shipped, unit)
                self.assertEqual(prepared.name, base)
                self.assertEqual(prepared.steps, ("unit-suffix",))
