"""What a nuclide *is*, and how long it lasts.

Two things live here.

**The identity.**  A nuclide is fixed by three values -- which element, how many
nucleons, and which nuclear state -- and :class:`Nuclide` is that triple.  Both
the flow labels (``Uranium-238``, ``Technetium-99m``) and the nuclear-data
sources (``238U``, ``99Tcm``) write the same triple in their own notation, and
:func:`parse_nuclide_label` and :func:`parse_nuclide` read each of them into it.
Comparing and indexing happens on the triple, never on either spelling.

This is not how it worked.  ``flow_layers`` built a dictionary from every name a
nuclide row might go by and looked labels up in it, which fails in two ways that
this shape cannot: an isomer and its ground state generate the same aliases, so
one silently overwrote the other and whichever PubChem listed last won
(`#18 <https://github.com/brightway-labs/brightway-flows/issues/18>`_);
and where the element symbol ends in ``238Um`` was guessed from the trailing
letters, which reads ``147Pm`` as phosphorus and ``54Mn`` as an unnamed element
``M``.  Neither guess is necessary.  The set of element symbols is closed and it
is right here, so the symbol is *data* and the boundary is not in question.

**The half-life.**  ChemLIN and PubChem write it as a quantity with a unit and
often an uncertainty in brackets -- ``432.6(2) a``, ``10.739 yr``, ``5.7 ms``,
``stable``.  Two callers want it as a number: ``flow_layers`` ranks isomeric
candidates by it in days, and ``pipeline.semantic_typing`` publishes it in years.

Lives in ``domain`` rather than in ``flow_layers`` for the reason
``domain.units`` does: ``flow_layers`` pulls in settings, the filesystem and the
integrations, and a pipeline module that wants only the parser should not have
to import all of that to get it.  The periodic table is a constant rather than
reference data for the same reason -- it is what makes the parsing a pure
function, and a test checks it against the PubChem cache so the two cannot
drift.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass

import pint

UREG = pint.UnitRegistry()

# ── the periodic table ────────────────────────────────────────────────────────

#: ``(atomic number, symbol, name)``, PubChem's spelling of the name.  Checked
#: against ``pubchem-elements-isotopes.json`` by ``tests/test_nuclides.py``, so
#: this being a literal is a pin rather than a second source of truth.
ELEMENTS: tuple[tuple[int, str, str], ...] = (
    (1, "H", "Hydrogen"), (2, "He", "Helium"), (3, "Li", "Lithium"),
    (4, "Be", "Beryllium"), (5, "B", "Boron"), (6, "C", "Carbon"),
    (7, "N", "Nitrogen"), (8, "O", "Oxygen"), (9, "F", "Fluorine"),
    (10, "Ne", "Neon"), (11, "Na", "Sodium"), (12, "Mg", "Magnesium"),
    (13, "Al", "Aluminum"), (14, "Si", "Silicon"), (15, "P", "Phosphorus"),
    (16, "S", "Sulfur"), (17, "Cl", "Chlorine"), (18, "Ar", "Argon"),
    (19, "K", "Potassium"), (20, "Ca", "Calcium"), (21, "Sc", "Scandium"),
    (22, "Ti", "Titanium"), (23, "V", "Vanadium"), (24, "Cr", "Chromium"),
    (25, "Mn", "Manganese"), (26, "Fe", "Iron"), (27, "Co", "Cobalt"),
    (28, "Ni", "Nickel"), (29, "Cu", "Copper"), (30, "Zn", "Zinc"),
    (31, "Ga", "Gallium"), (32, "Ge", "Germanium"), (33, "As", "Arsenic"),
    (34, "Se", "Selenium"), (35, "Br", "Bromine"), (36, "Kr", "Krypton"),
    (37, "Rb", "Rubidium"), (38, "Sr", "Strontium"), (39, "Y", "Yttrium"),
    (40, "Zr", "Zirconium"), (41, "Nb", "Niobium"), (42, "Mo", "Molybdenum"),
    (43, "Tc", "Technetium"), (44, "Ru", "Ruthenium"), (45, "Rh", "Rhodium"),
    (46, "Pd", "Palladium"), (47, "Ag", "Silver"), (48, "Cd", "Cadmium"),
    (49, "In", "Indium"), (50, "Sn", "Tin"), (51, "Sb", "Antimony"),
    (52, "Te", "Tellurium"), (53, "I", "Iodine"), (54, "Xe", "Xenon"),
    (55, "Cs", "Cesium"), (56, "Ba", "Barium"), (57, "La", "Lanthanum"),
    (58, "Ce", "Cerium"), (59, "Pr", "Praseodymium"), (60, "Nd", "Neodymium"),
    (61, "Pm", "Promethium"), (62, "Sm", "Samarium"), (63, "Eu", "Europium"),
    (64, "Gd", "Gadolinium"), (65, "Tb", "Terbium"), (66, "Dy", "Dysprosium"),
    (67, "Ho", "Holmium"), (68, "Er", "Erbium"), (69, "Tm", "Thulium"),
    (70, "Yb", "Ytterbium"), (71, "Lu", "Lutetium"), (72, "Hf", "Hafnium"),
    (73, "Ta", "Tantalum"), (74, "W", "Tungsten"), (75, "Re", "Rhenium"),
    (76, "Os", "Osmium"), (77, "Ir", "Iridium"), (78, "Pt", "Platinum"),
    (79, "Au", "Gold"), (80, "Hg", "Mercury"), (81, "Tl", "Thallium"),
    (82, "Pb", "Lead"), (83, "Bi", "Bismuth"), (84, "Po", "Polonium"),
    (85, "At", "Astatine"), (86, "Rn", "Radon"), (87, "Fr", "Francium"),
    (88, "Ra", "Radium"), (89, "Ac", "Actinium"), (90, "Th", "Thorium"),
    (91, "Pa", "Protactinium"), (92, "U", "Uranium"), (93, "Np", "Neptunium"),
    (94, "Pu", "Plutonium"), (95, "Am", "Americium"), (96, "Cm", "Curium"),
    (97, "Bk", "Berkelium"), (98, "Cf", "Californium"),
    (99, "Es", "Einsteinium"), (100, "Fm", "Fermium"),
    (101, "Md", "Mendelevium"), (102, "No", "Nobelium"),
    (103, "Lr", "Lawrencium"), (104, "Rf", "Rutherfordium"),
    (105, "Db", "Dubnium"), (106, "Sg", "Seaborgium"), (107, "Bh", "Bohrium"),
    (108, "Hs", "Hassium"), (109, "Mt", "Meitnerium"),
    (110, "Ds", "Darmstadtium"), (111, "Rg", "Roentgenium"),
    (112, "Cn", "Copernicium"), (113, "Nh", "Nihonium"),
    (114, "Fl", "Flerovium"), (115, "Mc", "Moscovium"),
    (116, "Lv", "Livermorium"), (117, "Ts", "Tennessine"),
    (118, "Og", "Oganesson"),
)

ATOMIC_NUMBER_BY_SYMBOL: dict[str, int] = {s: z for z, s, _ in ELEMENTS}

#: The spellings a source list uses that PubChem does not.  IUPAC and American
#: usage differ on four names, and both appear across EF 3.1 and ecoinvent.
#: Nothing here is a truncation or an abbreviation: a label that shortens an
#: element name is a defect in that label and is corrected in the manual fixes,
#: not absorbed here, because absorbing it would hide the next one.
_ELEMENT_NAME_ALIASES = {
    "aluminium": "Al",
    "caesium": "Cs",
    "sulphur": "S",
    "cesium": "Cs",
}

_SYMBOL_BY_ELEMENT_NAME: dict[str, str] = {
    **{name.lower(): symbol for _, symbol, name in ELEMENTS},
    **_ELEMENT_NAME_ALIASES,
}


def element_symbol(name: str) -> str | None:
    """The symbol for an element *name*, or ``None`` when it is not one."""
    return _SYMBOL_BY_ELEMENT_NAME.get(str(name or "").strip().lower())


# ── the identity ──────────────────────────────────────────────────────────────

#: An isomeric state as the sources spell it.  PubChem runs ``m n p q r x``
#: through successive excited states of one nuclide -- all six occur in the
#: cached tables, ``o`` does not, and the run refuses a letter outside the set
#: rather than reading it as a state; ChemLIN numbers the same states ``m1``,
#: ``m2``, ``m3``.  The empty string is the ground state, and it is a distinct
#: value rather than a missing one -- that is the whole point.
_STATE = re.compile(r"^(?:[mnpqrx]\d?|)$")

#: ``Uranium-238``, ``Uranium 238``, ``Technetium-99m``, ``Praseodymium-141``.
#: Anchored at both ends: a nuclide name is the whole label or it is not a
#: nuclide name.  ``Lead 2,4,6-trinitro-m-phenylene dioxide`` starts with an
#: element name and a number and is a molecule.
_LABEL = re.compile(r"^([A-Za-z]+)[\s-]?(\d{1,3})\s*([a-z]\d?)?$")

#: ``238U``, ``238Um``, ``99Tcm`` -- mass number first, then the symbol, then
#: the state.  Where the symbol ends is *not* read from this: the caller passes
#: the element, and :func:`parse_nuclide` splits on it.
_NUCLIDE = re.compile(r"^(\d{1,3})([A-Za-z]+)$")


@dataclass(frozen=True, order=True)
class Nuclide:
    """One nuclide: an element, a nucleon count, and a nuclear state.

    Frozen and ordered so it can key a dictionary and sort a report.  Equality
    is the identity: ``238U`` and ``238Um`` are different nuclides, which is
    exactly what the alias index could not express.
    """

    symbol: str
    mass_number: int
    state: str = ""

    @property
    def atomic_number(self) -> int:
        return ATOMIC_NUMBER_BY_SYMBOL[self.symbol]

    @property
    def is_ground_state(self) -> bool:
        return not self.state

    @property
    def key(self) -> str:
        """``U-238``, ``U-238m``.  Stable, and short enough to read in an id."""
        return f"{self.symbol}-{self.mass_number}{self.state}"

    def ground_state(self) -> Nuclide:
        """The same nuclide in its ground state."""
        return Nuclide(self.symbol, self.mass_number)

    def __str__(self) -> str:
        return self.key


def parse_nuclide(text: str, *, symbol: str) -> Nuclide | None:
    """Read a nuclear-data source's ``238Um`` into a :class:`Nuclide`.

    *symbol* is the element the row belongs to, which the caller always knows --
    PubChem's isotope tables are nested one level below the element.  Whatever
    follows the symbol is the state, whichever letter it is.  Guessing the
    boundary instead is what published ``chemrof:symbol`` of ``P`` for
    promethium and ``M`` for manganese, and read ``122Sbp`` as an element
    ``Sbp``: the letters that end a symbol and the letters that name a state
    overlap, so nothing about the string settles it.
    """
    match = _NUCLIDE.match(str(text or "").strip().replace(" ", ""))
    if not match or not symbol:
        return None
    mass_number, letters = int(match.group(1)), match.group(2)
    if not letters.startswith(symbol):
        return None
    state = letters[len(symbol):].lower()
    if not _STATE.match(state):
        return None
    return Nuclide(symbol, mass_number, state)


def parse_nuclide_label(label: str) -> Nuclide | None:
    """Read a flow's ``Uranium-238`` into a :class:`Nuclide`.

    ``None`` for anything whose first token is not an element name, which is
    what keeps ``HCFC-123a`` -- same shape, and a molecule -- out.  The check is
    the closed set of element names rather than a pattern, so it costs nothing
    to be strict.

    This says only what the *label* claims.  Whether a nuclide of that mass
    number exists is a question for the nuclear data, and ``flow_layers`` asks
    it there: ``Palladium-234m`` parses cleanly here and has no answer there,
    which is how that defect is caught rather than published
    (`#20 <https://github.com/brightway-labs/brightway-flows/issues/20>`_).
    """
    match = _LABEL.match(str(label or "").strip())
    if not match:
        return None
    symbol = element_symbol(match.group(1))
    if not symbol:
        return None
    state = (match.group(3) or "").lower()
    if not _STATE.match(state):
        return None
    return Nuclide(symbol, int(match.group(2)), state)


#: How a source spells a unit of time, mapped to what `pint` calls it.  `a` is
#: *annum*, which is how the nuclear-data sources write years and which pint
#: would otherwise read as `are`.
_UNIT_ALIASES = {
    "ns": "nanosecond",
    "us": "microsecond",
    "ms": "millisecond",
    "s": "second",
    "sec": "second",
    "secs": "second",
    "m": "minute",
    "min": "minute",
    "mins": "minute",
    "h": "hour",
    "hr": "hour",
    "hrs": "hour",
    "d": "day",
    "day": "day",
    "days": "day",
    "wk": "week",
    "wks": "week",
    "week": "week",
    "weeks": "week",
    "mo": "month",
    "mos": "month",
    "y": "year",
    "yr": "year",
    "yrs": "year",
    "year": "year",
    "years": "year",
    "a": "year",
    # PubChem writes the long half-lives with an SI prefix on the year, and
    # without these they parse to nothing: uranium-238 is `4.463 Gy`,
    # potassium-40 `1.248 Gy`, carbon-14 `5.70 ky`, iodine-129 `16.14 My`.
    # Those are the nuclides an inventory is most likely to carry and the ones
    # whose half-life a consumer is most likely to want, and every one of them
    # published without a `chemrof:half_life` while the isomer records that
    # displaced them -- nanoseconds and microseconds -- parsed perfectly.
    #
    # Matched case-insensitively like every other alias, which is safe *here*
    # and would not be in general: `Gy` is the gray, a unit of absorbed dose.
    # These strings are half-lives, so a duration is the only reading.
    "ky": "kiloyear",
    "my": "megayear",
    "gy": "gigayear",
    "ty": "terayear",
    "py": "petayear",
}

#: A magnitude, an optional bracketed uncertainty, an optional power of ten, and
#: a unit.  The exponent sits *after* the uncertainty in the form ChemLIN uses --
#: ``7.04(1) &times; 10<sup>8</sup> a``, folded to ``7.04(1)e8 a`` before it gets
#: here -- so it cannot simply be part of the magnitude.
_QUANTITY = re.compile(
    r"(\d+(?:\.\d+)?)(?:\([^)]*\))?\s*(?:[eE]([+-]?\d+))?\s*([a-zA-Zµμ]+)"
)


def half_life(value: str, *, unit: str) -> float | None:
    """The half-life in *unit*, or ``None`` when the text does not yield one.

    ``"stable"`` returns infinity, which is what the sources mean by it and what
    the ranking in ``flow_layers`` relies on to prefer a stable nuclide.
    """
    text = html.unescape(str(value or "").strip())
    if not text:
        return None
    if "stable" in text.lower():
        return float("inf")
    match = _QUANTITY.search(text)
    if not match:
        return None
    normalised = (
        match.group(3).lower().replace("µ", "u").replace("μ", "u").rstrip(".")
    )
    source_unit = _UNIT_ALIASES.get(normalised)
    if not source_unit:
        return None
    try:
        magnitude = float(match.group(1)) * 10 ** int(match.group(2) or 0)
        return float((magnitude * UREG(source_unit)).to(unit).magnitude)
    except Exception:
        return None


def half_life_days(value: str) -> float | None:
    """The half-life in days.  Used to rank metastable candidates."""
    return half_life(value, unit="day")


def half_life_years(value: str) -> float | None:
    """The half-life in years, for ``chemrof:half_life``.

    ``None`` for a stable nuclide as well as for an unparseable one: infinity is
    not a number a JSON document can carry, and "does not decay" is better said
    by the absence of a half-life than by a value no consumer can compare.
    """
    years = half_life(value, unit="year")
    if years is None or years == float("inf"):
        return None
    return years
