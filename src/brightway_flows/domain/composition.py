"""What a compositional name states about how many atoms of each element.

`Antimony trisulfide` says three sulfur atoms, and that is a fact about the
substance stated in its own name.  Nothing read it until #129, where a
name-to-structure parser handed back a structure with one sulfur -- antimony
*mono*sulfide, a different compound -- and it was published, because the formula
and the SMILES agreed with each other and nothing else was consulted.

Only the simplest names are read: a binary compositional name, two words, each
optionally carrying a multiplicative prefix.

    antimony trisulfide          Sb?   S3
    dibismuth trisulphide        Bi2   S3
    diphosphorus pentasulphide   P2    S5

**A missing prefix states nothing, and must not be read as one.**  That is the
whole difference between a rule that catches two substances and one that
condemns eleven correct ones.  `Hydrogen sulfide` is H2S, `lanthanum oxide` is
La2O3, `arsenic trioxide` is As2O3 -- traditional names, every one correct, and
not one of them says how many atoms of the first element there are.  Read as
"one", each becomes a contradiction of its own true formula.

Anything not of this shape yields ``None``, which means *no statement*, not *no
contradiction*.  `Tetramethylthiuram monosulphide` is two words and is not one
of these: `thiuram` is not an element, and its "monosulphide" counts a bridging
atom rather than the molecule's three sulfurs.  Requiring both halves to name an
element is what keeps that name out.
"""

from __future__ import annotations

import re

from brightway_flows.domain.nuclides import element_symbol

#: The multiplicative prefixes, as far as any name in these lists goes.
_MULTIPLIERS: dict[str, int] = {
    "mono": 1,
    "di": 2,
    "tri": 3,
    "tetra": 4,
    "penta": 5,
    "hexa": 6,
    "hepta": 7,
    "octa": 8,
    "nona": 9,
    "deca": 10,
}

#: The `-ide` stems that name an element.  A stem is not the element's name with
#: a suffix -- `sulfide` and `sulphide` are both spelled in these lists, and
#: `antimonide` is not `antimony` -- so they are listed rather than derived.
_ANION_STEMS: dict[str, str] = {
    "sulfide": "S",
    "sulphide": "S",
    "oxide": "O",
    "nitride": "N",
    "phosphide": "P",
    "carbide": "C",
    "hydride": "H",
    "chloride": "Cl",
    "fluoride": "F",
    "bromide": "Br",
    "iodide": "I",
    "selenide": "Se",
    "telluride": "Te",
    "arsenide": "As",
    "antimonide": "Sb",
    "boride": "B",
    "silicide": "Si",
}

#: One element and its count in a formula: `Bi2S3`, `SSb`, `P4S10`.
_FORMULA_ATOM = re.compile(r"([A-Z][a-z]?)(\d*)")

#: A trailing charge, which says nothing about how many atoms there are.  It has
#: to come off rather than disqualify the formula: RDKit writes the structure
#: this is all about as `SSb+`, so a rule that refused to count a charged
#: formula would never fire on the case it exists for.
_TRAILING_CHARGE = re.compile(r"[+-]\d*$")

#: A formula this cannot count.  `2Cu.S` and `C39H41N3O6S2.Na` are two
#: substances written as one string, and a bracketed formula states a grouping
#: this does not parse.
_UNCOUNTABLE = re.compile(r"[.·()\[\]]")


#: `monoxide` rather than `monooxide`: the prefix and the stem share their `o`,
#: and `carbon monoxide` is a name these lists really carry.  Spelled out before
#: the prefix is taken off, so the stem table needs no entry for the elision.
_ELISIONS: dict[str, str] = {
    "monoxide": "monooxide",
    "dioxide": "dioxide",
    "pentoxide": "pentaoxide",
    "tetroxide": "tetraoxide",
    "heptoxide": "heptaoxide",
}


def _split_multiplier(word: str) -> tuple[int | None, str]:
    """The count a word's prefix states, or ``None``, and the rest of the word.

    Longest prefix first, so `hexa` is not read as `he`.  A word that is only a
    prefix keeps its whole self: there would be nothing left to name an element.
    """
    for prefix in sorted(_MULTIPLIERS, key=len, reverse=True):
        if word.startswith(prefix) and len(word) > len(prefix):
            return _MULTIPLIERS[prefix], word[len(prefix) :]
    return None, word


def stated_composition(name: str) -> dict[str, int | None] | None:
    """What the *name* says about its two elements, or ``None``.

    A value of ``None`` against an element means the name mentions it without
    saying how many: `arsenic trioxide` names arsenic and does not count it.
    The whole result is ``None`` when the name is not a binary compositional one
    or when it counts neither element -- it then says nothing, and a caller must
    not read that as agreement.
    """
    words = str(name or "").strip().lower().split()
    if len(words) != 2:
        return None
    cation_count, cation_word = _split_multiplier(words[0])
    anion_count, anion_word = _split_multiplier(
        _ELISIONS.get(words[1], words[1])
    )
    cation = element_symbol(cation_word)
    anion = _ANION_STEMS.get(anion_word)
    if cation is None or anion is None or cation == anion:
        return None
    if cation_count is None and anion_count is None:
        return None
    return {cation: cation_count, anion: anion_count}


def formula_composition(formula: str) -> dict[str, int] | None:
    """How many atoms of each element a *formula* states, or ``None``.

    ``None`` for anything this cannot count honestly -- see `_UNCOUNTABLE`.
    """
    text = _TRAILING_CHARGE.sub("", str(formula or "").strip())
    if not text or _UNCOUNTABLE.search(text):
        return None
    counts: dict[str, int] = {}
    consumed = 0
    for match in _FORMULA_ATOM.finditer(text):
        if match.start() != consumed:
            return None
        consumed = match.end()
        counts[match.group(1)] = counts.get(match.group(1), 0) + int(
            match.group(2) or "1"
        )
    if consumed != len(text) or not counts:
        return None
    return counts


def corroborates_name(formula: str, name: str) -> bool:
    """Whether the *name* independently says the same thing as the *formula*.

    Stronger than "does not contradict", and the difference is the whole point:
    a name that says nothing about composition contradicts nothing, and is not
    evidence for anything either.  This asks for a name that *states* a count
    and a formula that agrees with it -- two sources arriving at one answer.

    It is the gate on publishing a registry's composition as a substance's
    formula (#129).  Without it that rule fires on two dozen substances whose
    names corroborate nothing, and several would be wrong: `Rhenium(2+)` would
    take the neutral element's formula from the element's registry number, and
    `Uranium Alpha` -- alpha-emitting isotopes reported together as activity,
    not a substance at all (#68) -- would be published as though it were
    uranium metal.
    """
    return (
        stated_composition(name) is not None
        and formula_composition(formula) is not None
        and not contradicts_name(formula, name)
        and set(stated_composition(name) or {}) == set(
            formula_composition(formula) or {}
        )
    )


def contradicts_name(formula: str, name: str) -> bool:
    """Whether a *formula* states a composition the *name* says it is not.

    A formula agrees when it is the stated counts, or a whole multiple of them.
    The multiple matters, because a correct formula is often written as one:
    `diphosphorus pentasulphide` is published as `P4S10`, two P2S5 units, and
    `dibismuth trisulphide` carries `Bi4S6`, two Bi2S3 units.  Both keep the
    ratio their name states.  A monosulfide does not -- one sulfur is not three
    at any scale, and that is the whole of #129.

    False where either side cannot be read, and false where the formula names
    elements the name does not.  A formula about different elements is a
    question this cannot answer, rather than one it answers no to: `H3AsO3` is
    arsenous acid rather than a reading of arsenic trioxide.
    """
    stated = stated_composition(name)
    found = formula_composition(formula)
    if stated is None or found is None:
        return False
    if set(stated) != set(found):
        return False
    multiple: int | None = None
    for element, count in stated.items():
        if count is None:
            continue
        atoms = found[element]
        if atoms % count:
            return True
        if multiple is None:
            multiple = atoms // count
        elif multiple != atoms // count:
            return True
    return False
