"""How this list names a monatomic ion, and the synonyms every one carries.

One standard, written down once, for every name of the shape: lead with two
positive charges is published as `Lead(2+)`, chloride as `Chloride(1-)`, and
copper whose charge nobody stated as `Copper, ion`.  The charged forms are the
IUPAC charge-number notation (the Red Book's `iron(2+)`, `chloride(1-)`),
with the element named in its IUPAC spelling -- `Caesium(1+)`, `Aluminium(3+)`.
IUPAC has no name for an ion of unstated charge, so `X, ion` is this list's own
spelling of it, the one `flow_layers.ions` already wrote.

The synonyms are the spellings inventories actually use for the same thing, and
are published whatever else the substance's sources happened to say:

- a cation also answers to its Stock numeral, with and without parentheses:
  `Lead(II)`, `Lead II`;
- an anion also answers to its bare name and to its signed numeral:
  `Chloride`, `Chloride(-I)`, `Chloride -I`;
- an ion of unstated charge also answers to `Copper, Ion` and `Copper Ion`;
- where the American spelling of the element differs from IUPAC's, every form
  above is repeated in it: `Cesium(1+)`, `Cesium(I)`, `Cesium I`.

A numeral states an oxidation number, which is the charge only for a single
atom.  That is why the standard is about monatomic ions: `Methylmercury(1+)` is
not mercury(I).  The generic `X, ion` spelling is the one exception, and covers a
polyatomic ion too (`Thiocyanate, ion`), because it says nothing about charge.

Pure functions of a name and a charge.  `pipeline.ion_names` applies them to the
built substances; `flow_layers.ions` and `merge.species` spell new names with
them.
"""

from __future__ import annotations

#: The `prov:wasGeneratedBy` on every label this standard writes.  Read by
#: `flow_layers.synonyms.carry_member_names`, which does not withdraw a synonym
#: carrying it: the standard promises the name, as the size-class scheme
#: promises its spellings.
ION_NAMING_STANDARD = "ion_naming_standard"

#: IUPAC spelling to American, where the two differ.  Sulfur is one spelling in
#: both; `sulphur` is British, and not asked for.
AMERICAN_SPELLINGS = {"Aluminium": "Aluminum", "Caesium": "Cesium"}

_IUPAC_SPELLINGS = {american: iupac for iupac, american in AMERICAN_SPELLINGS.items()}

#: An element's name as a monatomic anion.  Only these are recognised as
#: anion names; an element outside the table is left as it is named.
ANION_NAMES = {
    "Arsenic": "Arsenide",
    "Bromine": "Bromide",
    "Carbon": "Carbide",
    "Chlorine": "Chloride",
    "Fluorine": "Fluoride",
    "Hydrogen": "Hydride",
    "Iodine": "Iodide",
    "Nitrogen": "Nitride",
    "Oxygen": "Oxide",
    "Phosphorus": "Phosphide",
    "Selenium": "Selenide",
    "Sulfur": "Sulfide",
    "Tellurium": "Telluride",
}

_ANION_NAME_SET = frozenset(ANION_NAMES.values())

_ROMAN = (
    (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"),
)


def roman_numeral(number: int) -> str:
    """*number* (positive) in Roman numerals: 2 as ``II``, 6 as ``VI``."""
    if number < 1:
        raise ValueError(f"no Roman numeral for {number}")
    out = []
    for value, numeral in _ROMAN:
        while number >= value:
            out.append(numeral)
            number -= value
    return "".join(out)


def iupac_base(base: str) -> str:
    """*base* capitalised and in its IUPAC spelling: ``cesium`` as ``Caesium``.

    An anion's base is its anion name, so an element written where the anion
    is meant -- `Chlorine` with a negative charge -- is the caller's to turn
    into `Chloride` with `anion_base`.
    """
    text = " ".join(base.split())
    if not text:
        return ""
    text = text[0].upper() + text[1:]
    return _IUPAC_SPELLINGS.get(text, text)


def anion_base(base: str) -> str:
    """The anion name for *base*: ``Chlorine`` and ``Chloride`` both as ``Chloride``."""
    text = iupac_base(base)
    return ANION_NAMES.get(text, text)


def is_anion_name(base: str) -> bool:
    """Whether *base* is a monatomic anion's own name, `Chloride` or `Sulfide`."""
    return iupac_base(base) in _ANION_NAME_SET


def standard_ion_label(base: str, charge: int | None) -> str:
    """The published name of the ion of *base* with *charge*.

    ``None`` is a charge nobody stated: ``Copper, ion``.  A negative charge
    names the anion: ``Chlorine`` or ``Chloride`` with -1 is ``Chloride(1-)``.
    """
    if charge is None:
        return f"{iupac_base(base)}, ion"
    if charge < 0:
        return f"{anion_base(base)}({-charge}-)"
    return f"{iupac_base(base)}({charge}+)"


def standard_ion_synonyms(base: str, charge: int | None) -> list[str]:
    """The synonyms the ion of *base* with *charge* always carries, in order.

    Never the label itself.  See the module docstring for which forms these
    are and why.
    """
    if charge is not None and charge < 0:
        name = anion_base(base)
        numeral = roman_numeral(-charge)
        return [name, f"{name}(-{numeral})", f"{name} -{numeral}"]

    name = iupac_base(base)
    american = AMERICAN_SPELLINGS.get(name)
    spellings = [name] if american is None else [name, american]
    out: list[str] = []
    if charge is None:
        if american is not None:
            out.append(f"{american}, ion")
        for spelling in spellings:
            out.extend([f"{spelling}, Ion", f"{spelling} Ion"])
        return out
    numeral = roman_numeral(charge)
    if american is not None:
        out.append(f"{american}({charge}+)")
    for spelling in spellings:
        out.extend([f"{spelling}({numeral})", f"{spelling} {numeral}"])
    return out


__all__ = [
    "AMERICAN_SPELLINGS",
    "ANION_NAMES",
    "ION_NAMING_STANDARD",
    "anion_base",
    "iupac_base",
    "is_anion_name",
    "roman_numeral",
    "standard_ion_label",
    "standard_ion_synonyms",
]
