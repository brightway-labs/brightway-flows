"""A registry number claimed by two names in one source list, and what decides it.

`resolve_flow_layers` treats a shared CAS as proof of shared identity.  Usually
it is.  In EF 3.1 it is not: 68 registry numbers are carried by more than one
flow name, and 53 of those groups are fused onto a single flow object, taking
963 elementary flows and 1,908 characterisation factors with them (#34).

The tempting rule -- do not merge on a contested number without external
corroboration -- does not survive measurement, and this module is deliberately
not that rule.  **19 of the 68 groups are contested because this project made
them so**: every CAS the #19 code table and #35 supplied is by construction a
number that two names now carry, and the merge is the whole point of supplying
it.  A rule built on suspicion undoes our own corrections.

What separates the two populations is the source list's own characterisation
factors.  If EF gives two names *different* factors for the same method in the
same context, EF is saying they are different substances, and no external source
is needed to hear it.  Measured over the 53 fused groups, that fires on 11, by
19% to twenty orders of magnitude -- including all four fused hydrofluoroether
groups, which Common Chemistry only partly corroborates and cannot adjudicate at
all for `84011-06-3`, a number it has no record for.

So four signals, in order, and the first that speaks decides:

1. **A curated ruling**, from `data/contested-cas-decisions.json`.  Final either
   way, the same contract as `preferred-label-decisions.json`.
2. **A number this project supplied by manual fix.**  A `cas_numbers` fix in a
   `*-manual-fixes.json` is a curator saying, with evidence in its comment, that
   this name denotes this substance.  Derived from the fixes file rather than
   restated in the decisions file, so the two cannot drift apart.
3. **Divergent factors**, above `FACTOR_TOLERANCE`.  Separate.
4. **Full Common Chemistry synonymy** -- every name in the group is a name the
   registry number holds.  Merge.

Anything else is `UNDECIDED`, which keeps today's behaviour and produces a
review item.  21 groups land there, and splitting them would change 307
published flows on no evidence at all -- which is the failure mode of the rule
this module does not implement.

Nothing here reads an InChIKey.  That is deliberate: #42 is repairing stereo
layers that are currently wrong in both directions, so a structure comparison is
the one signal that cannot be trusted yet, and the measurement said it is not
needed -- no group's verdict depends on it.

**The caller passes the flows that resolve *by CAS*.**  A flow the qualifier,
material or nuclide axis claims takes an exclusive branch in
`resolve_flow_layers` and never asks this question, so including it here would
manufacture a contest that cannot happen: EF's fourteen waters and its methane
qualifier family both disagree on factors -- 0.221 against 100 for `Water use` --
and both are already separated, so a `separate` verdict on them would move the
one member that *does* resolve by CAS off its published `cas:` identifier and
change nothing else.  Contested means "two names the CAS branch would otherwise
fuse", and the caller is what knows that.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Any

import orjson
import structlog

from brightway_flows.domain.context import Context
from brightway_flows.domain.context_registry import context_to_dict
from brightway_flows.domain.flow import Flow
from brightway_flows.domain.labels import flow_label_value
from brightway_flows.filesystem import COMMONCHEMISTRY_CACHE_FILEPATH
from brightway_flows.flow_layers.labels import _canonical_name, _norm_text
from brightway_flows.filesystem import PACKAGE_DATA_DIR

logger = structlog.get_logger(__name__)

#: Curated rulings.  Beside the other decision files rather than in this module,
#: because a ruling is data a curator edits and a rule is code we test.
DECISIONS_FILEPATH = (
    PACKAGE_DATA_DIR / "contested-cas-decisions.json"
)

#: How far two characterisation factors may differ before the disagreement is
#: about the substance rather than about arithmetic.
#:
#: Two names for one substance routinely publish the same factor to different
#: precision -- EF has `5.5192e-08` under `dichloromethane` and `5.52e-08` under
#: `Methylene chloride` -- and comparing exact values calls that a conflict.
#: Three significant figures bounds that error at 0.5%.
#:
#: The value is otherwise unconstrained by the data: over the 53 fused groups
#: nothing lands between 2% and 19%, so this could move a long way without
#: changing an outcome.  It is a threshold on rounding, not a judgement about
#: how different two substances have to be.
FACTOR_TOLERANCE = 0.02


class Verdict(StrEnum):
    """What to do with a registry number two names claim."""

    #: The names denote one substance; key on CAS as usual.
    MERGE = "merge"
    #: They do not; key on the name so each keeps its own flow object.
    SEPARATE = "separate"
    #: Nothing decides.  Today's behaviour, and a review item.
    UNDECIDED = "undecided"


@dataclass(frozen=True)
class ContestedCas:
    """One registry number, the names claiming it, and the verdict on them."""

    cas: str
    names: tuple[str, ...]
    verdict: Verdict
    #: Which of the four signals spoke.  Carried because a verdict without its
    #: reason cannot be reviewed, and because the review queue renders it.
    decided_by: str
    evidence: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ContestedCasRuling:
    """A curator's answer for one registry number, and what it was given on.

    *names* is what the curator was looking at when they answered.  It does not
    select -- the ruling is keyed on the number and applies whatever names carry
    it today -- but a changed set means the ruling was written about different
    data, which :func:`contested_cas_index` says out loud rather than obeying in
    silence.
    """

    cas: str
    verdict: Verdict
    names: tuple[str, ...]
    comment: str


def load_decisions(path: Path | None = None) -> dict[str, ContestedCasRuling]:
    """Curated rulings, keyed by CAS.

    A missing file is not an error: no ruling is the normal state before a
    curator has looked, and every signal below it still works.
    """
    path = path or DECISIONS_FILEPATH
    if not path.exists():
        logger.debug("no_contested_cas_decisions", path=str(path))
        return {}
    payload = orjson.loads(path.read_bytes())
    decisions: dict[str, ContestedCasRuling] = {}
    for row in payload.get("decisions", []):
        if not isinstance(row, dict):
            continue
        cas = str(row.get("cas") or "").strip()
        verdict = str(row.get("decision") or "").strip().lower()
        if not cas or verdict not in (Verdict.MERGE, Verdict.SEPARATE):
            # Dropped rather than guessed: a typo in the decision would
            # otherwise read as whichever branch the comparison fell through to.
            logger.warning("contested_cas_decision_unusable", cas=cas, decision=verdict)
            continue
        if not str(row.get("comment") or "").strip():
            raise ValueError(f"contested-cas ruling for {cas} has no comment.")
        decisions[cas] = ContestedCasRuling(
            cas=cas,
            verdict=Verdict(verdict),
            names=tuple(sorted(str(n) for n in row.get("names") or ())),
            comment=row["comment"],
        )
    return decisions


@lru_cache(maxsize=1)
def commonchemistry_details() -> Mapping[str, Any]:
    """The Common Chemistry answers already on disk, keyed by registry number.

    Signal 4's input.  Read from the cache the enrichment fills rather than
    fetched: this runs inside the layering, which must not depend on the network,
    and a number nothing has looked up yet simply corroborates nothing.

    Memoised because the file is tens of megabytes and the merge resolves layers
    once per source list.  It is a cache of answers, not state, so a process that
    reads it twice in one run would get the same thing anyway.
    """
    if not COMMONCHEMISTRY_CACHE_FILEPATH.exists():
        logger.debug("no_commonchemistry_cache", path=str(COMMONCHEMISTRY_CACHE_FILEPATH))
        return {}
    payload = orjson.loads(COMMONCHEMISTRY_CACHE_FILEPATH.read_bytes())
    details = payload.get("detail_by_cas")
    return details if isinstance(details, dict) else {}


def cas_supplied_by_manual_fixes(path: Path | None) -> frozenset[str]:
    """Registry numbers a `*-manual-fixes.json` writes onto a flow.

    Signal 2.  Read from the fixes file itself rather than copied into the
    rulings file: the fix *is* the ruling, it already carries the evidence in
    its comment, and a second copy is how the two come to disagree about what
    was decided.
    """
    if path is None or not path.exists():
        return frozenset()
    payload = orjson.loads(path.read_bytes())
    supplied: set[str] = set()
    for fix in payload.get("fixes", []):
        if not isinstance(fix, dict) or fix.get("field") not in ("cas_number", "cas_numbers"):
            continue
        value = fix.get("new_value")
        if isinstance(value, str):
            supplied.add(value.strip())
        elif isinstance(value, list):
            supplied.update(str(v).strip() for v in value if str(v).strip())
    return frozenset(supplied)


# ---------------------------------------------------------------------------
# Signal 3: the source list's own characterisation factors
# ---------------------------------------------------------------------------

def _context_key(context: Context | None) -> str:
    """A hashable context.

    The on-disk dict rather than the record: `orjson` writes a dataclass field
    by field, so a `Context` would key on eight entries including the five it
    does not set -- and this string is published, in the `where` of a
    disagreement report.
    """
    return orjson.dumps(
        context_to_dict(context) if context is not None else None,
        option=orjson.OPT_SORT_KEYS,
    ).decode("utf-8")


def factor_rows(flow: Any) -> Iterable[tuple[str, float]]:
    """Every `(method name, factor)` a record publishes.

    Typed loosely because `pipeline/collisions.py` asks the same question of an
    `ElementaryFlow`, which carries the identical `lcia_methods` list.  Only the
    list is read, so both records answer.

    A factor with no method name is skipped, because the name is the only thing
    making two flows' factors comparable and there is nothing to compare an
    unnamed one against.  It used to be four ways of not finding a key -- two
    spellings of the amount, a `.get()` for the name, and a shape check for the
    entry -- on a list this pass reads to decide which CAS number a substance
    keeps, where not finding a key is a decision made on no evidence.
    """
    for factor in flow.lcia_methods or ():
        name = str(factor.category.name or "").strip()
        if name:
            yield name, factor.amount


def worst_disagreement(
    rows: Iterable[tuple[Any, str, float]],
) -> tuple[float, tuple[Any, float, float] | None, int]:
    """The largest relative disagreement between two sides on one comparable key.

    *rows* are `(key, side, factor)`: the *key* is what makes two factors
    comparable at all -- a method, or a method in a context -- and the *side* is
    who published it.  Returns `(worst, where, comparable)`, `where` being
    `(key, low, high)` for the worst key, so a caller can label it its own way.

    `comparable` counts the keys where two sides both publish a usable value,
    and is what separates "these agree" from "there was nothing to compare" --
    21 of the 53 fused CAS groups have no comparable pair at all, and reading
    that as agreement would be an evidence-free merge dressed up as an
    evidenced one.

    Zero and negative factors are skipped rather than special-cased: a relative
    difference is not defined across zero, and an uptake credit compared against
    an emission is a question about sign conventions, not about identity.

    Both callers ask this of two flows that may be one substance -- two names
    claiming a registry number, or two flows one field away from collapsing --
    so the rule and the tolerance it is read against are stated once (#58).
    """
    per_key: dict[Any, dict[str, set[float]]] = {}
    for key, side, factor in rows:
        per_key.setdefault(key, {}).setdefault(side, set()).add(factor)

    worst = 0.0
    where: tuple[Any, float, float] | None = None
    comparable = 0
    for key, by_side in per_key.items():
        if len(by_side) < 2:
            continue
        values = [v for values in by_side.values() for v in values if v > 0]
        if len(values) < 2:
            continue
        comparable += 1
        low, high = min(values), max(values)
        relative = high / low - 1
        if relative > worst:
            worst = relative
            where = (key, low, high)
    return worst, where, comparable


def significant_digits(value: float) -> int:
    """How many digits a published number states.

    Read off the shortest decimal that round-trips the float, which is what the
    source list wrote: `0.000118` states three and `0.00011755` states five.
    Trailing zeros do not count -- `100.0` states one -- because a source list
    writing `100` is not claiming to have measured three digits.
    """
    number = Decimal(repr(abs(float(value)))).normalize()
    return len(number.as_tuple().digits)


def to_significant_digits(value: float, digits: int) -> Decimal:
    """*value* written to *digits* significant figures.

    Half away from zero, which is how a published table is rounded and not what
    Python's own formatting does: `%.3g` gives `7.13e-09` for `7.135e-09`,
    where EF publishes `7.14e-09`.  Rounding the shorter way would read that
    pair as two numbers.
    """
    number = Decimal(repr(float(value)))
    if not number:
        return number
    quantum = Decimal(1).scaleb(number.adjusted() - digits + 1)
    return number.quantize(quantum, rounding=ROUND_HALF_UP)


def more_precise_value(
    left: float, right: float, *, tolerance: float = FACTOR_TOLERANCE
) -> float | None:
    """Which of two published numbers is the other one written to more digits.

    `None` when they are two numbers rather than one number written twice, and
    that is the whole question: EF publishes `0.00011755` for a refrigerant
    under its chemical name and `0.000118` for the same refrigerant under its
    industry designation, which is one number, while `1.62e-08` against
    `1.63e-08` is two.  A caller keeping only one of the two has something to
    prefer in the first case and nothing to prefer in the second.

    Both tests have to pass.  The numbers must agree within *tolerance*, the
    same threshold that decides whether two names are one substance -- so `5`
    against `5.4`, which *is* a rounding at one significant figure, is still
    read as two numbers, 8% apart.  And the shorter number must be what the
    longer one becomes at the shorter one's precision, which is a stronger
    statement than "these are close": `0.000119` is within tolerance of
    `0.00011755` and is not a rounding of it, so neither is preferred.

    Zero is not a rounding of anything and a relative difference is not defined
    across it, so a pair touching or straddling zero is two numbers (#47's
    stated zeros are the case that reaches this).

    Nothing here decides a contest; it is not a fifth signal.  It sits beside
    `FACTOR_TOLERANCE` because it is read against it, and what asks the question
    is `pipeline/collision_decisions.py`, where a merge keeps one of the two
    numbers and until #63 kept whichever one the survivor happened to hold.
    """
    left, right = float(left), float(right)
    if left == right or left == 0 or right == 0 or (left > 0) != (right > 0):
        return None
    low, high = sorted((abs(left), abs(right)))
    if high / low - 1 > tolerance:
        return None
    left_digits, right_digits = significant_digits(left), significant_digits(right)
    if left_digits == right_digits:
        return None
    fine, coarse = (left, right) if left_digits > right_digits else (right, left)
    if to_significant_digits(fine, min(left_digits, right_digits)) != Decimal(
        repr(coarse)
    ):
        return None
    return fine


def factor_disagreement(
    flows: Iterable[Flow],
    *,
    name_of: Mapping[str, str],
) -> tuple[float, dict[str, Any] | None, int]:
    """The largest relative disagreement between two names on one factor.

    Signal 3's reading of `worst_disagreement`: two factors are comparable when
    they are the same method in the same context, and the sides are the names
    claiming the registry number.
    """
    rows: list[tuple[Any, str, float]] = []
    for flow in flows:
        name = name_of.get(flow.uuid, "")
        if not name:
            continue
        context = _context_key(flow.context)
        for method, factor in factor_rows(flow):
            rows.append(((method, context), name, factor))

    worst, at, comparable = worst_disagreement(rows)
    where: dict[str, Any] | None = None
    if at is not None:
        (method, context), low, high = at
        where = {"method": method, "context": context, "low": low, "high": high}
    return worst, where, comparable


# ---------------------------------------------------------------------------
# Signal 4: Common Chemistry synonymy
# ---------------------------------------------------------------------------

def _record_names(record: Any) -> set[str]:
    """Every name Common Chemistry publishes for one registry number.

    An empty record is not an answer.  `_lookup_commonchemistry_detail_cached`
    writes `{}` both for a 404 and for a request that failed after its retries,
    which is the distinction #267 was corrected for -- so an empty record must
    corroborate nothing rather than refute everything.
    """
    if not isinstance(record, dict) or not record:
        return set()
    names = {str(record.get("name") or "")}
    names.update(str(s) for s in record.get("synonyms") or ())
    return {_canonical_name(_strip_markup(n)) for n in names if n.strip()}


def _strip_markup(value: str) -> str:
    """Common Chemistry marks up its names -- `<em>N</em>,<em>N</em>'-...`."""
    out, depth = [], 0
    for char in value:
        if char == "<":
            depth += 1
        elif char == ">":
            depth = max(0, depth - 1)
        elif depth == 0:
            out.append(char)
    return "".join(out)


def _folded(name: str) -> set[str]:
    """A name and the orthographic variants that are never another substance."""
    canonical = _canonical_name(name)
    return {canonical, canonical.replace("sulph", "sulf"), canonical.replace("sulf", "sulph")}


def corroborated_by_synonyms(names: Iterable[str], record: Any) -> bool:
    """Is every name one that Common Chemistry gives this registry number?"""
    published = _record_names(record)
    if not published:
        return False
    return all(_folded(name) & published for name in names)


# ---------------------------------------------------------------------------
# The index
# ---------------------------------------------------------------------------

def names_claiming(flow: Flow, *, list_name: str = "", list_version: str = "") -> set[str]:
    """Every name this source list has given *flow*: its label, and what it arrived as.

    Both, because a rename can erase the contest before anything looks for it.
    `consensus_match` renames a flow to the name Common Chemistry gives its CAS,
    which is the right move for a synonym and the wrong one when the number is
    wrong for the flow -- EF's `1,1,1-trichloroethane` carries `79-00-5`, whose
    name is `1,1,2-Trichloroethane`, so the rename lands the two substances on
    one name and this question then finds nothing to ask about (#34).  Reading
    the name the flow *arrived* under is what keeps the evidence.

    Only the named list's references count, and *no* reference is read unless a
    list is named.  A contested number is one substance's name colliding with
    another's *within* one list; the same number on an EF flow and an ecoinvent
    flow is the merge doing its job, and counting a foreign list's name here
    would report every such meeting as a contest.
    """
    names: set[str] = set()
    label = _norm_text(flow_label_value(flow).strip())
    if label:
        names.add(label)
    if not list_name:
        return names
    for ref in flow.source_refs or ():
        if not isinstance(ref, dict):
            continue
        if str(ref.get("list_name") or "") != list_name:
            continue
        if list_version and str(ref.get("list_version") or "") != list_version:
            continue
        arrived = _norm_text(str(ref.get("source_flow_name") or "").strip())
        if arrived:
            names.add(arrived)
    return names


def contested_cas_index(
    flows: Iterable[Flow],
    *,
    decisions: Mapping[str, ContestedCasRuling] | None = None,
    supplied_by_us: frozenset[str] = frozenset(),
    commonchemistry: Mapping[str, Any] | None = None,
    tolerance: float = FACTOR_TOLERANCE,
    list_name: str = "",
    list_version: str = "",
) -> dict[str, ContestedCas]:
    """Every registry number *flows* claim under more than one name, and its verdict.

    Names are normalised the way the layering normalises them, so `HCFC-140` and
    `hcfc-140` are one name here as they are there.  On raw source strings EF 3.1
    has 339 such numbers and almost all of it is case.

    *list_name* and *list_version* identify the list being asked about, so that
    `names_claiming` can read what each flow arrived as.  Omitting them asks only
    about current labels, which is what a caller with no source references has.
    """
    flows = list(flows)
    decisions = decisions or {}

    name_of: dict[str, str] = {}
    names_by_cas: dict[str, set[str]] = {}
    flows_by_cas: dict[str, list[Flow]] = {}
    for flow in flows:
        names = names_claiming(flow, list_name=list_name, list_version=list_version)
        if not names:
            continue
        # The label is what a factor disagreement is reported against, because it
        # is what the flow is published as.  `names` is what decides the contest.
        name_of[flow.uuid] = _norm_text(flow_label_value(flow).strip()) or sorted(names)[0]
        for cas in flow.cas_numbers or ():
            cas = str(cas).strip()
            if not cas:
                continue
            names_by_cas.setdefault(cas, set()).update(names)
            flows_by_cas.setdefault(cas, []).append(flow)

    index: dict[str, ContestedCas] = {}
    for cas, names in names_by_cas.items():
        if len(names) < 2:
            continue
        ordered = tuple(sorted(names))

        ruling = decisions.get(cas)
        if ruling is not None:
            if ruling.names and ruling.names != ordered:
                # The ruling still applies -- it is keyed on the number -- but a
                # changed name set means it was written about different data,
                # and silence here is how a stale ruling goes on being obeyed.
                logger.warning(
                    "contested_cas_ruling_names_moved",
                    cas=cas, ruled_on=list(ruling.names), now=list(ordered),
                )
            index[cas] = ContestedCas(
                cas=cas, names=ordered, verdict=ruling.verdict,
                decided_by="curated ruling", evidence={"comment": ruling.comment},
            )
            continue

        if cas in supplied_by_us:
            index[cas] = ContestedCas(
                cas=cas, names=ordered, verdict=Verdict.MERGE,
                decided_by="a manual fix supplied this number",
            )
            continue

        worst, where, comparable = factor_disagreement(flows_by_cas[cas], name_of=name_of)
        if comparable and worst > tolerance:
            index[cas] = ContestedCas(
                cas=cas, names=ordered, verdict=Verdict.SEPARATE,
                decided_by="the source list characterises these names differently",
                evidence={"divergence": worst, "worst_at": where, "comparable": comparable},
            )
            continue

        if corroborated_by_synonyms(ordered, (commonchemistry or {}).get(cas)):
            index[cas] = ContestedCas(
                cas=cas, names=ordered, verdict=Verdict.MERGE,
                decided_by="every name is one Common Chemistry gives this number",
            )
            continue

        index[cas] = ContestedCas(
            cas=cas, names=ordered, verdict=Verdict.UNDECIDED,
            decided_by="no signal decides",
            evidence={"comparable": comparable, "divergence": worst},
        )
    return index
