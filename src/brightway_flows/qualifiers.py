"""Flow qualifier detection for names that require separate flow objects.

Flows explicitly labelled with a qualifier require separate flow objects even
when they share a CAS number or other identifiers with the base substance.

Carbon-origin qualifiers
------------------------
"non-fossil" is treated as a synonym for "biogenic": both terms indicate that
the carbon in the flow originates from the contemporary biosphere rather than
geological reserves.

"biogenic_resource_correction" identifies flows like "Carbon dioxide,
non-fossil, resource correction" which must be kept as a distinct flow object
separate from ordinary biogenic CO2.  The match is on "resource correction"
(more specific than "non-fossil") so it takes precedence over "biogenic".

Water-type qualifiers
---------------------
Green, blue, and grey water describe distinct water categories used in water
footprint methodology (ISO 14046, Hoekstra et al.) and must not be merged with
one another or with unqualified water even when they share CAS 7732-18-5:

  * green_water  – rainwater stored in the soil and used by plants
  * blue_water   – surface water and groundwater
  * grey_water   – polluted/contaminated water (both "grey" and "gray" spellings)

Delayed-emission correction qualifiers
--------------------------------------
EF 3.1 ships six "Correction flow for delayed emission of X (within first 100
years)" flows.  These are accounting devices, not inventory flows: they carry
their own characterisation factor and are measured in kg*a, not kg.  Each one
arrives with the base substance's CAS number, so without a qualifier the CAS
merges it into the substance -- and because the correction flow's name is the
longest in the group, the merged object then publishes under *its* name.  That
is what removed nitrous oxide from the list: all fourteen `nitrous oxide` flows
and the correction flow shared one object, named for the correction (#268).

Three qualifiers rather than one, because two of the corrections are about
biogenic carbon and two about fossil carbon, and both pairs share their base
substance's CAS (124-38-9 for CO2, 74-82-8 for methane).  One qualifier would
group by `(qualifier, CAS)` and put the fossil and the biogenic correction of
the same substance back on one object.

Radiological-aggregate qualifiers
--------------------------------
"alpha_emitters" identifies flows like ``Plutonium-alpha``, ``Uranium alpha``
and ``Curium Alpha``.  These are not allotropes or phases: they are the
alpha-emitting isotopes of one element, reported together as activity, which is
why their unit is kBq and why a beta emitter of the same element (Pu-241) is
carried separately alongside them.  Every one of them arrives carrying the
*element's* CAS number, so without this qualifier the CAS merges the aggregate
into the element -- and one flow object then stands for two substances, with the
element's structural properties asserted over a set of isotopes (#238).

The match is on a trailing "alpha" token only.  "alpha" is also the commonest
stereo and positional descriptor in the list -- ``alpha-cypermethrin``,
``16alpha-hydroxyprednisolone``, ``alpha-BHC``, ``(s)-.alpha.-cyano-...`` -- and
in every one of those it is a prefix or an infix naming a position within one
molecule.  Anchoring at the end is what separates the two readings: across both
source lists the only names ending in "alpha" are the three aggregates.

Each qualified flow object links to the unqualified flow object via
``parent_flow_object_id`` when one is available.

Precedence
----------
Checks run in order; the first match wins:
  biogenic_delayed_emission_correction > fossil_delayed_emission_correction >
  delayed_emission_correction > land_use_change >
  biogenic_resource_correction > biogenic_100yr > biogenic/non-fossil >
  fossil > grey_water > blue_water > green_water > alpha_emitters

The delayed-emission checks come first because their names contain the words a
later check reads: "of biogenic carbon dioxide" is a `biogenic` match and "of
fossil methane" a `fossil` one, and either would send the correction flow to
the qualified substance's object instead of to its own.

`alpha_emitters` is last, because it is the narrowest: it can only fire on a
name no other check matched, and no name in either source list satisfies two of
these.
"""

from __future__ import annotations

import re

# ── patterns ──────────────────────────────────────────────────────────────────

#: "delayed emission" is the whole test: it appears in six names in either
#: source list and in nothing else.  The biogenic and fossil variants are the
#: same test with the carbon-origin word, in either order -- `A.*B|B.*A`, as the
#: water qualifiers below are written, because a name is as free to say
#: "biogenic carbon dioxide, correction flow for delayed emission" as EF's own
#: does the reverse, and falling through to the bare qualifier would merge the
#: biogenic and the fossil correction of one substance back onto one object.
#: Biogenic is checked before fossil because `\bfossil\b` also matches inside
#: "non-fossil".
_DELAYED_EMISSION = re.compile(r"\bdelayed[\s-]emission\b", re.IGNORECASE)
_BIOGENIC_DELAYED_EMISSION = re.compile(
    r"\bdelayed[\s-]emission\b.*\b(?:biogenic|non[\s-]fossil)\b"
    r"|\b(?:biogenic|non[\s-]fossil)\b.*\bdelayed[\s-]emission\b",
    re.IGNORECASE,
)
_FOSSIL_DELAYED_EMISSION = re.compile(
    r"\bdelayed[\s-]emission\b.*\bfossil\b"
    r"|\bfossil\b.*\bdelayed[\s-]emission\b",
    re.IGNORECASE,
)
#: `land transformation` is BAFU's spelling of the same carbon EF calls `land use
#: change` and ecoinvent books as `from soil or biomass stock`: the one-off release
#: when a use changes.  Reading it is a rule rather than two curated rows because
#: the phrase says what the carbon is, and a curated target would say only where
#: this list happens to send it.
#:
#: Measured before adding: across EF 3.1, five ecoinvent releases and BAFU, the
#: phrase occurs in **one** flow name -- `Carbon dioxide, land transformation`.
#: The land flows that might have collided do not: ecoinvent and BAFU both write
#: `Transformation, from forest`, never `land transformation`.
_LAND_USE_CHANGE = re.compile(
    r"\bland[\s-]use\b|\bland[\s-]transformation\b", re.IGNORECASE
)
#: AGRIBALYSE's spelling of the same carbon.  Draining a peatland and letting the
#: peat oxidise is a change of land use, and AGRIBALYSE books it as one: its own
#: `Peat degradation emissions on grassland, per kg CO2 {GLO}` ships the release
#: as `Carbon dioxide, land transformation`, and its soil carbon datasets say
#: their land-transformation row is "excluding peat degradation" -- the same
#: accounting, split out, not a different kind of carbon.  So the phrase says
#: what the carbon is, which is what earns a rule here rather than a curated
#: target per row, and it answers the methane row as well as the carbon dioxide
#: one (#194).
#:
#: Measured before adding: across EF 3.1, all five ecoinvent releases, BAFU
#: 2026-v1, Stepwise 2006 and AGRIBALYSE 3.2, `peat oxidation` occurs in
#: **three** flow names, one row each, all AGRIBALYSE's and all in unspecified
#: air -- `Carbon dioxide, peat oxidation`, `Methane, peat oxidation` and
#: `Dinitrogen monoxide, peat oxidation`.  Nothing else in any list matches.
#:
#: **The third needs a curated target, and finding that out took a full build.**
#: EF ships no nitrous oxide of land-use-change origin, so nothing carries the
#: qualifier and nothing narrows -- which was expected to leave the row where it
#: already was, on EF's `Nitrous Oxide` in unspecified air.  It does not.
#: 10024-97-2 reaches two objects, the substance and its delayed-emission
#: correction flow, and what separated them was the row's own shipped name
#: sitting on `Nitrous Oxide` as an altLabel, carried there by
#: `carry_member_names` from this row.  Give the name a qualifier and the row
#: layers elsewhere, the altLabel is not carried, and the row is refused as
#: `multiple-flow-object-candidates`.  So `agribalyse-3.2-match-overrides.json`
#: states where it goes.  A rule that reads a phrase reads it on every name that
#: carries it; where the vocabulary has no flow to move a row to, the row is
#: stated rather than derived.
_PEAT_OXIDATION = re.compile(r"\bpeat[\s-]oxidation\b", re.IGNORECASE)
_RESOURCE_CORRECTION = re.compile(r"\bresource[\s-]correction\b", re.IGNORECASE)
#: ecoinvent's `Carbon dioxide, to soil or biomass stock`: carbon entering a
#: long-lived land carbon pool.  Not land *use change* -- 102 of the 269
#: ecoinvent 3.12 datasets that emit it are `land already in use`, where no
#: conversion happens at all -- and not biogenic either, because the fast cycle
#: EF calls neutral is the one whose other half falls inside the study.  The GHG
#: Protocol's word for it is a land management removal, and its definition is the
#: whole of the concept: "the transfer of a GHG from the atmosphere to storage
#: within a non-atmospheric pool".
#:
#: **`to` and not `from`, deliberately.** The release side, `Carbon dioxide, from
#: soil or biomass stock`, reaches EF's own `carbon dioxide (land use change)` in
#: air, where both implementations state +1 and the list publishes `agreed` --
#: there is a flow there that means what it means, and moving it would turn two
#: publishers concurring into one asserting.  There is no such flow for the
#: capture.  So the direction is load-bearing here, and it is the only thing in
#: the vendor's name that carries it.
#:
#: Narrow on purpose, and measured: across EF 3.1, BAFU 2026-v1 and all five
#: ecoinvent releases read here, `to soil or biomass stock` occurs in exactly one
#: flow name -- `Carbon dioxide, to soil or biomass stock`, four contexts in each
#: ecoinvent release, twenty rows in all.  Nothing else in any list matches.  The
#: three sibling phrases stay out: `from soil or biomass stock` is the release
#: side and names carbon dioxide, carbon monoxide and methane; `in soil or
#: biomass stock` and its `increase`/`decrease` spellings are the organic carbon
#: balancing flows.  None of those is a transfer out of the atmosphere.
_TO_SOIL_OR_BIOMASS_STOCK = re.compile(
    r"\bto soil or biomass stock\b", re.IGNORECASE
)
#: EF 3.1's `carbon dioxide (biogenic-100yr)`: biogenic CO2 uptake credited
#: under a 100-year time horizon.  An accounting variant, like the delayed-
#: emission corrections above and unlike plain biogenic uptake -- and until
#: this pattern existed the bare `biogenic` word inside it matched below, so
#: the accounting flow sat on the ordinary biogenic substance and ecoinvent's
#: plain uptake row, prepared-matched onto it, acquired 100-year semantics
#: nothing in ecoinvent's own data states (#116).  Tolerant of a space or
#: hyphen before `100` and an optional one before `yr`, and nothing wider: a
#: `100yr` with no `biogenic` beside it is a time horizon in a method name,
#: not a carbon origin.
_BIOGENIC_100YR = re.compile(r"\bbiogenic[\s-]100[\s-]?yr\b", re.IGNORECASE)
_BIOGENIC = re.compile(r"\bbiogenic\b", re.IGNORECASE)
_NON_FOSSIL = re.compile(r"\bnon[\s-]fossil\b", re.IGNORECASE)
_FOSSIL = re.compile(r"\bfossil\b", re.IGNORECASE)
_GREY_WATER = re.compile(r"\bgr[ae]y\b.*\bwater\b|\bwater\b.*\bgr[ae]y\b", re.IGNORECASE)
_BLUE_WATER = re.compile(r"\bblue\b.*\bwater\b|\bwater\b.*\bblue\b", re.IGNORECASE)
_GREEN_WATER = re.compile(r"\bgreen\b.*\bwater\b|\bwater\b.*\bgreen\b", re.IGNORECASE)
#: A trailing "alpha", separated from the substance it qualifies by a space, a
#: hyphen or a comma.  `\b` alone would match `16alpha` and `.alpha.`, and the
#: separator has to be *present* rather than optional: a name that is only the
#: word "alpha" qualifies nothing and is not one of these flows.
_ALPHA_EMITTERS = re.compile(r"\S[\s,-]+alpha\s*$", re.IGNORECASE)

# ── qualifier names ───────────────────────────────────────────────────────────

#: Named, because two modules outside this one branch on it: `semantic_typing`
#: types these objects and withdraws the structural properties they inherited,
#: and neither should be matching a string literal against this table.
ALPHA_EMITTERS = "alpha_emitters"

#: The three a delayed-emission correction flow can take.  Named because the
#: layering has to ask whether a qualifier is one of these -- a correction flow
#: renamed to "Methane (fossil)" still detects `fossil`, and taking that answer
#: puts it back on the substance object the split exists to keep it off.
DELAYED_EMISSION_CORRECTIONS: frozenset[str] = frozenset({
    "biogenic_delayed_emission_correction",
    "fossil_delayed_emission_correction",
    "delayed_emission_correction",
})


def is_delayed_emission_correction(qualifier: str | None) -> bool:
    """Whether *qualifier* is one of the delayed-emission correction values."""
    return qualifier in DELAYED_EMISSION_CORRECTIONS

# ── ordered qualifier table ───────────────────────────────────────────────────

# Each entry: (qualifier_name, [patterns_any_of_which_triggers_a_match]).
# Order matters: first match wins.  More specific patterns must come before
# more general ones (e.g. biogenic_resource_correction before biogenic).
QUALIFIER_CHECKS: list[tuple[str, list[re.Pattern[str]]]] = [
    ("biogenic_delayed_emission_correction", [_BIOGENIC_DELAYED_EMISSION]),
    ("fossil_delayed_emission_correction",   [_FOSSIL_DELAYED_EMISSION]),
    ("delayed_emission_correction", [_DELAYED_EMISSION]),
    # Before `land_use_change`.  Not because the two patterns overlap -- they do
    # not -- but because a reader comparing the entries should meet the narrower
    # land concept first, and because a future `land use` spelling of a stock
    # flow must not silently become a land-use-change row.
    ("sequestration_from_land_management", [_TO_SOIL_OR_BIOMASS_STOCK]),
    ("land_use_change",             [_LAND_USE_CHANGE, _PEAT_OXIDATION]),
    ("biogenic_resource_correction",[_RESOURCE_CORRECTION]),
    # Before the bare word, which also matches inside it.
    ("biogenic_100yr",              [_BIOGENIC_100YR]),
    ("biogenic",                    [_BIOGENIC, _NON_FOSSIL]),
    ("fossil",                      [_FOSSIL]),
    ("grey_water",                  [_GREY_WATER]),
    ("blue_water",                  [_BLUE_WATER]),
    ("green_water",                 [_GREEN_WATER]),
    (ALPHA_EMITTERS,                [_ALPHA_EMITTERS]),
]

ORIGIN_QUALIFIERS: tuple[str, ...] = tuple(q for q, _ in QUALIFIER_CHECKS)


def detect_origin_qualifier(name: str) -> str | None:
    """Return the qualifier embedded in *name*, or ``None``.

    Returns one of the values in ``ORIGIN_QUALIFIERS``, or ``None``.

    A "delayed emission" correction flow maps to one of the three
    ``*_delayed_emission_correction`` values before any carbon-origin word in
    the same name is read.  ``"non-fossil"`` maps to ``"biogenic"`` unless
    "resource correction" also appears, in which case it maps to
    ``"biogenic_resource_correction"``.
    Both ``"grey"`` and ``"gray"`` map to ``"grey_water"``.  A *trailing*
    ``"alpha"`` maps to ``"alpha_emitters"``; an ``"alpha"`` anywhere else in
    the name is a position within a molecule and maps to nothing.
    """
    if not name:
        return None
    for qualifier, patterns in QUALIFIER_CHECKS:
        if any(p.search(name) for p in patterns):
            return qualifier
    return None
