"""Reading a molecular formula, including the ratios a registry writes into one.

A registry writes a salt as its acid and a ratio of metal, because that is what
the substance is made of and the acid is the part with a name::

    373-02-4    Nickel acetate      C2H4O2 . 1/2 Ni     mass 178.80
    553-72-0    Zinc benzoate       C7H6O2 . 1/2 Zn
    7758-16-9   Disodium pyrophosphate   H4O7P2 . 2 Na
    14807-96-6  Talc                H2O3Si . 3/4 Mg

Two acetic acids to one nickel, said the other way round.  Neither SMILES nor
InChI can hold half an atom, so a structure derived from that formula silently
loses the ratio and becomes one-to-one -- which is how nickel acetate comes to
publish `C2H4NiO2` beside its real `C4H6NiO4` (#310).

`registered_composition` multiplies the ratio out, so `C2H4O2 . 1/2 Ni` reads as
the four carbons, eight hydrogens, four oxygens and one nickel it means.

`heavy_atom_composition` then drops hydrogen, because **a salt is its acid with
the acidic hydrogens gone** and the registry names the acid.  Nickel acetate as
the registry states it is `C4H8NiO4`; as the salt it is `C4H6NiO4`.  Ignore
hydrogen and both are four carbons, four oxygens and one nickel -- one
substance, described from two ends.

What it costs to ignore hydrogen is that two substances differing *only* by
hydrogen are read as one: ethane and ethene are both two carbons.  That is
acceptable here and nowhere else, because the caller is not identifying a
substance -- it is asking whether a value already on the record contradicts what
the registry registered, and it asks only of a record that already carries two
answers.  Do not reach for this as a way of saying two substances are the same.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from fractions import Fraction

#: One element symbol and its optional count: `C4`, `H`, `Ni`, `Zr`.
_ATOM = re.compile(r"([A-Z][a-z]?)(\d*)")

#: A component's leading multiplier, either a fraction (`1/2Ni`) or a whole
#: number (`2Na`).  Anything else is a component with an implied multiplier of 1.
_FRACTION = re.compile(r"^(\d+)/(\d+)(.*)$")
_MULTIPLE = re.compile(r"^(\d+)(.*)$")

#: A composition as this module hands it out: element and count, element order
#: fixed so two are comparable with `==`.
Composition = tuple[tuple[str, int], ...]


def parse_formula(text: str) -> Counter[str] | None:
    """*text* as element counts, or `None` if it is not a plain formula.

    `None` rather than a partial answer: a formula this cannot read in full --
    a charge suffix, a wildcard, an isotope in brackets -- says nothing, and a
    caller comparing a half-read formula would be comparing a different
    substance.
    """
    text = str(text or "").strip()
    if not text:
        return None
    counts: Counter[str] = Counter()
    position = 0
    while position < len(text):
        match = _ATOM.match(text, position)
        if match is None or not match.group(1):
            return None
        counts[match.group(1)] += int(match.group(2) or 1)
        position = match.end()
    return counts or None


def registered_composition(text: str) -> Counter[str] | None:
    """*text* as element counts with its component ratios multiplied out.

    `C2H4O2.1/2Ni` is two acetic acids to one nickel, so it reads as
    `C4H8NiO4`.  `H4O7P2.2Na` is one pyrophosphate to two sodium.  A formula
    with no components and no multipliers reads as itself.

    `None` where any component is unreadable, and for CAS's own
    `Unspecified` -- the registry stating that the number has no definite
    composition at all, which is a statement about the substance and not a
    failure to parse.  Both cases mean *no opinion*, and a caller must not read
    either as disagreement.
    """
    plain = str(text or "").strip()
    if not plain or plain == "Unspecified":
        return None
    components: list[tuple[Fraction, Counter[str]]] = []
    for part in (p.strip() for p in plain.split(".")):
        if not part:
            continue
        fraction = _FRACTION.match(part)
        if fraction is not None:
            denominator = int(fraction.group(2))
            if denominator == 0:
                return None
            multiplier = Fraction(int(fraction.group(1)), denominator)
            rest = fraction.group(3)
        else:
            whole = _MULTIPLE.match(part)
            if whole is not None:
                multiplier, rest = Fraction(int(whole.group(1))), whole.group(2)
            else:
                multiplier, rest = Fraction(1), part
        counts = parse_formula(rest)
        if counts is None:
            return None
        components.append((multiplier, counts))
    if not components:
        return None
    # Scale every component by the smallest factor that makes each multiplier a
    # whole number: `1/2 Ni` alongside one acetic acid is one nickel alongside
    # two, not half a nickel rounded to none.
    scale = 1
    for multiplier, _ in components:
        scale = scale * multiplier.denominator // math.gcd(scale, multiplier.denominator)
    total: Counter[str] = Counter()
    for multiplier, counts in components:
        factor = multiplier * scale
        if factor.denominator != 1:  # pragma: no cover - scale is their common multiple
            return None
        for element, count in counts.items():
            total[element] += count * int(factor)
    return total or None


def heavy_atom_composition(counts: Counter[str] | None) -> Composition | None:
    """*counts* without hydrogen, as a comparable tuple, or `None` if empty.

    See the module docstring for why hydrogen goes and what that costs.  A
    formula of nothing but hydrogen -- `H2`, and the registry's own `H2O` minus
    its oxygen never happens -- returns `None` rather than an empty tuple, so a
    caller cannot compare two substances by finding that neither has any heavy
    atoms.
    """
    if not counts:
        return None
    heavy = [
        (element, count)
        for element, count in counts.items()
        if element != "H" and count > 0
    ]
    if not heavy:
        return None
    return tuple(sorted(heavy))


def published_heavy_atoms(text: str) -> Composition | None:
    """The heavy-atom composition of a formula as a source published it.

    Reads component ratios the same way `registered_composition` does, because
    a source may spell a salt the registry's way too -- the build carries
    `H4B4O9.2Na` for disodium tetraborate.
    """
    return heavy_atom_composition(registered_composition(text))
