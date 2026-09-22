"""Qualifiers a rename drops, for a reader to rule on.  Never a filter.

The CC/ChEBI identity audit -- `curation.label_audit` -- asks whether the
replacement is a name the cited CAS actually has.  It is not a question about
*specificity*, so it cannot see a replacement that names something broader than
the flow is: `'Xylene (all isomers)' -> 'Xylene'` passes it, because `xylene` is
a name CAS 1330-20-7 holds and `xylene (all isomers)` is not (#224).

This module is how those renames get shortlisted for a chemist.  It compares the
two names and reports the qualifiers the current one carries that the
replacement does not:

    scope             `(all isomers)`, `, mixed`, `and isomers`
    carbon_range      `C4-6`, `C13-15`
    locant            `3-`, `1,1,1-`, `N-`
    stereo            `alpha-`, `cis-`, `sec-`
    salt_hydrate_ion  `salt`, `dihydrate`, `ion`, `hydrochloride`
    parenthetical     any bracketed group the replacement loses
    comma_clause      any `, ...` clause the replacement loses

**A pattern over chemical names must not decide anything here.**  #220 tried
exactly that -- refuse a replacement that drops a locant, a designation or a
scope qualifier -- and abandoned it after three iterations: `C4-6` was read as
an isotope, then `beta-1,2,3,4,5,6-` was read as one too, and the version that
stopped misfiring still blocked `Barbituric acid`, `Quizalofop` and
`δ-Hexachlorocyclohexane`.  Chemical nomenclature is a grammar, not a pattern,
and 79k flows will always hold a case the pattern has not met.

What changed in #224 is only the *use*.  A heuristic that decides has to be
right; a heuristic that ranks 741 pairs so a chemist reads the 200 likeliest
first only has to be better than reading them in alphabetical order.  So this
module is deliberately over-eager -- `'Pyraclostrobin (prop)' ->
'Pyraclostrobin'` is reported, and is fine -- and the output is a worklist, not
a gate.  Nothing in `pipeline`, `transformers` or `domain` imports it, and
`tests/test_architecture_structure.py` fails if that changes.

Comparison runs over `canonical_label_value` (markup stripped, whitespace
collapsed, case folded) plus the Greek-to-ASCII stereo map the rename rule
itself compares with, so `alpha-` respelt as `α-` is not a dropped qualifier.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from brightway_flows.domain.labels import canonical_label_value
from brightway_flows.transformers.consensus_match.naming import (
    GREEK_TO_ASCII,
    alpha_only,
)

#: Words that widen what a name denotes.  Kept to terms that qualify a
#: substance rather than name one: a term that is part of a substance's name in
#: some flow and a qualifier in another (`oil`, `waste`) belongs to the mixture
#: vocabulary in `consensus_match.naming`, not here.
SCOPE_PHRASES: tuple[str, ...] = (
    "all isomers",
    "and isomers",
    "isomer mixture",
    "isomeric mixture",
    "isomers",
    "isomer",
    "mixed",
    "mixtures",
    "mixture",
    "unspecified",
    "homologues",
    "homologs",
    "and salts",
    "and its salts",
    "and derivatives",
    "technical grade",
    "technical",
    "branched",
    "linear",
    "total",
    "sum",
)

#: Salt, hydrate and ion words.  `\w*hydrate` covers the series
#: (`monohydrate`, `dihydrate`, `pentahydrate`) without listing it.
SALT_HYDRATE_ION_WORDS: tuple[str, ...] = (
    "salts",
    "salt",
    "anhydrous",
    "ions",
    "ion",
    "cations",
    "cation",
    "anions",
    "anion",
    "free base",
    "free acid",
    "hydrochloride",
    "hydrobromide",
    "hydroiodide",
)

#: Stereo, conformation and chain-form prefixes written outside brackets.  The
#: bracketed ones -- `(R)-`, `(1S,2R)-`, `(+/-)-` -- are reported by the
#: parenthetical detector instead, so that a pair is not counted twice.
STEREO_WORDS: tuple[str, ...] = (
    "alpha",
    "beta",
    "gamma",
    "delta",
    "epsilon",
    "zeta",
    "eta",
    "theta",
    "cis",
    "trans",
    "syn",
    "anti",
    "ortho",
    "meta",
    "para",
    "endo",
    "exo",
    "erythro",
    "threo",
    "racemic",
)

#: Single-letter and abbreviated prefixes, which only mean anything hyphenated:
#: `n-hexane` and `tert-butyl`, not the `n` of `n,n-dimethylformamide`.
_STEREO_PREFIX_RE = re.compile(r"(?<![a-z0-9])(dl|dextro|laevo|levo|rac|sec|tert|iso|neo|d|l|r|s|e|z)-")

#: `C4-6`, `C13-15`, `C18`.  Matched before locants so that the `13-15` of
#: `C13-15` is not also read as one -- the misfire #220 hit first.
_CARBON_RANGE_RE = re.compile(r"(?<![a-z0-9])c\s?(\d+)(?:\s?[-–]\s?(\d+))?(?![a-z0-9])")

#: `3-`, `1,1,1-`, `2,4-`: digits (or an element locant) bound to the name by a
#: hyphen.  The trailing lookahead keeps `1,1,1-` apart from a bare range.
_LOCANT_RE = re.compile(r"(?<![a-z0-9])(\d+(?:,\d+)*|[nopsc])-(?=[a-z(])")

_PARENTHETICAL_RE = re.compile(r"\(([^()]*)\)")

#: A clause boundary, not the commas inside `1,1,1-`: a comma with a space
#: after it.  `Benzene, 1,2-dimethyl-` splits once, not three times.
_COMMA_CLAUSE_RE = re.compile(r",\s+")


@dataclass(frozen=True)
class QualifierLoss:
    """One detector's verdict on one pair: what the replacement no longer says.

    `tokens` is what the current name carries and the replacement does not, in
    the detector's own terms, because a chemist reading the shortlist is ruling
    on the dropped qualifier rather than on the detector's name for it.
    """

    detector: str
    tokens: tuple[str, ...]


def _comparable(name: str) -> str:
    """The form both names are read in: canonicalised, Greek stereo in ASCII."""
    return canonical_label_value(name).translate(GREEK_TO_ASCII)


def _scope(text: str) -> set[str]:
    """Scope phrases, longest first, each masking what it consumed.

    Without the mask `Xylene (all isomers)` reports both `all isomers` and
    `isomers`, and the row a chemist reads says twice what it means once.
    """
    found: set[str] = set()
    for phrase in sorted(SCOPE_PHRASES, key=len, reverse=True):
        pattern = re.compile(rf"\b{re.escape(phrase)}\b")
        if pattern.search(text):
            found.add(phrase)
            text = pattern.sub(lambda match: " " * len(match.group(0)), text)
    return found


def _carbon_ranges(text: str) -> set[str]:
    return {match.group(0).replace(" ", "") for match in _CARBON_RANGE_RE.finditer(text)}


def _locants(text: str) -> set[str]:
    """Locants, with the carbon ranges masked out first.

    `C13-15` holds a `13-` that reads as a locant to a pattern that has not
    already claimed it, which is how the abandoned heuristic came to see an
    isotope in a chain-length range.  Masking rather than ordering the regexes
    is what makes that structural instead of incidental.
    """
    masked = _CARBON_RANGE_RE.sub(lambda match: " " * len(match.group(0)), text)
    return {match.group(1) for match in _LOCANT_RE.finditer(masked)}


def _stereo(text: str) -> set[str]:
    found = {word for word in STEREO_WORDS if re.search(rf"\b{word}\b", text)}
    found.update(match.group(1) for match in _STEREO_PREFIX_RE.finditer(text))
    return found


def _salt_hydrate_ion(text: str) -> set[str]:
    found = {word for word in SALT_HYDRATE_ION_WORDS if re.search(rf"\b{re.escape(word)}\b", text)}
    found.update(match.group(0) for match in re.finditer(r"\b\w*hydrate\b", text))
    return found


def _parentheticals(text: str) -> set[str]:
    return {
        match.group(1).strip()
        for match in _PARENTHETICAL_RE.finditer(text)
        if match.group(1).strip()
    }


def _comma_clauses(text: str) -> set[str]:
    head, *clauses = _COMMA_CLAUSE_RE.split(text)
    return {clause.strip(" .") for clause in clauses if clause.strip(" .")} if head else set()


#: The detectors, in the order a row reports them.  A table rather than a chain
#: of `if`s because the shortlist names the detector that fired on every row,
#: and a chemist ruling on 200 rows needs to know which question each one is.
DETECTORS: tuple[tuple[str, Callable[[str], set[str]]], ...] = (
    ("scope", _scope),
    ("carbon_range", _carbon_ranges),
    ("locant", _locants),
    ("stereo", _stereo),
    ("salt_hydrate_ion", _salt_hydrate_ion),
    ("parenthetical", _parentheticals),
    ("comma_clause", _comma_clauses),
)


#: Detectors whose loss is a scope claim in itself.  `and its salts` and
#: `dihydrate` say what the flow covers whatever else the two names share, so
#: they shortlist a pair even when the replacement is an unrelated name.  The
#: rest are structural, and structure only means something between two names
#: that are otherwise the same one -- see :func:`is_reduction`.
SEMANTIC_DETECTORS = frozenset({"scope", "salt_hydrate_ion"})


def qualifier_losses(current: str, replacement: str) -> list[QualifierLoss]:
    """Qualifiers *current* carries that *replacement* drops.

    Empty when the replacement keeps everything the detectors can see, which is
    not the same as "the replacement is safe" -- it is "no detector has a
    reason to put this pair in front of a reader first".
    """
    before = _comparable(current)
    after = _comparable(replacement)
    losses: list[QualifierLoss] = []
    for name, detect in DETECTORS:
        lost = detect(before) - detect(after)
        if lost:
            losses.append(QualifierLoss(detector=name, tokens=tuple(sorted(lost))))
    return losses


def _skeleton(name: str) -> str:
    """The name with everything but its letters removed."""
    return alpha_only(_comparable(name))


def is_reduction(current: str, replacement: str) -> bool:
    """Whether *replacement* is *current* with something taken out of it.

    This is what separates a dropped locant that matters from one that does
    not, and without it the shortlist is nearly the whole population.  A
    systematic name giving way to a common one drops every locant it had --
    `'(+/-) 2-(2,4-dichlorophenyl)-3-(1h-1,2,4-triazole-1-yl)propyl-...' ->
    'Tetraconazole'` drops eleven -- and that is the improvement the rule exists
    to make, not a loss of scope.  `'3-Methylpentane' -> 'Methyl Pentane'` drops
    one, and the two names are otherwise the same name: what went is the only
    thing that distinguished them.

    So the test is on the letters.  `methylpentane` == `methylpentane` and
    `xylene` sits inside `xyleneallisomers`, while `tetraconazole` shares no
    such relation with the systematic name it replaced.
    """
    before = _skeleton(current)
    after = _skeleton(replacement)
    return bool(after) and after in before


@dataclass(frozen=True)
class QualifierAssessment:
    """What one pair looks like to a reader deciding where to start."""

    losses: tuple[QualifierLoss, ...]
    reduction: bool

    @property
    def shortlisted(self) -> bool:
        """Whether this pair belongs in front of a chemist first.

        Not "this rename is wrong".  Every applied pair stays in the output;
        this only says which are worth a reader's first hour.
        """
        if not self.losses:
            return False
        if self.reduction:
            return True
        return any(loss.detector in SEMANTIC_DETECTORS for loss in self.losses)


def assess(current: str, replacement: str) -> QualifierAssessment:
    """The qualifiers *replacement* drops, and whether that puts it on the list."""
    return QualifierAssessment(
        losses=tuple(qualifier_losses(current, replacement)),
        reduction=is_reduction(current, replacement),
    )
