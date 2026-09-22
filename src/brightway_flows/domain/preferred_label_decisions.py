"""Curated decisions on replacing a flow's preferred label.

Two stages replace a label that is already published, and this file gates both.
`consensus_match` derives a better name for a substance from Common Chemistry
and ChEBI and replaces the preferred label of every member of a flow object with
it.  The element pass in `pipeline.element_labels` replaces the label of every
flow whose substance is a chemical element with that element's name, titlecased.
Those rules are usually right.  They are not right often enough to publish
unreviewed: a wrong preferred label names a *different substance*, and nothing
downstream can tell -- an inventory keyed on the label just silently means
something else.

`bootstrap_labels` is the third writer of a preferred label and is deliberately
not gated: it writes the EF 3.1 name to a flow that has *no* label, so there is
no replacement to rule on and nothing to lose.  A raw source name is a poor
published label, but the answer to that is a rule that proposes a better one --
which arrives here -- not a ruling on the bootstrap.

Observed in one full run (#219): `Systhane` -> `Myclobutanil` and
`Acryolonitrile` -> `Acrylonitrile` alongside `Xylene (all isomers)` ->
`Xylene`, which names something broader than the flow is.

Two of the pairs #219 read off the run-to-run diff were not renames at all.
`3-Methylpentane` -> `Methyl Pentane` and `1,1,1-Trichloroethane` -> `HCFC-140`
run *backwards*: the left-hand side was this rule's own output in the previous
run, and the right-hand side is the raw EF 3.1 name resurfacing after the guard
at the `cc_chebi_agreement` call site stopped the rename from happening.  A
published diff shows which labels moved, not which rule moved them; the applied
changes are the record of that.

The two sets are not separable by *pattern*.  A heuristic was tried -- refuse a
replacement that drops a locant, a designation or a scope qualifier -- and it
took three iterations to stop misfiring on real names (`C4-6` read as an isotope,
`beta-1,2,3,4,5,6-` as one too) and still blocked good renames.  Chemical
nomenclature is a grammar, not a pattern, and 79k flows will always hold a case
the pattern has not met.  They are largely separable by *rule*, which is what
the audit below measures.

So the rules propose and a curator decides.

**Which way an undecided pair falls depends on the rule that proposed it**, and
that split is measured rather than assumed.  Auditing the 838 distinct pairs of
one full run against the sources -- is each name a name the cited CAS actually
has, per Common Chemistry and ChEBI? -- separates the two rules cleanly:

    rule                  pairs   flows   pairs asserting an identity
                                          neither source supports
    cc_chebi_agreement      724   9,375                            0
    entropy (PubChem)       114   1,431                           80

The CC/ChEBI rule is bilateral agreement between two curated sources on the
primary name for one CAS, and it does not appear to get identity wrong; its
output is synonym swaps and systematic-to-common improvements (`Tetraconazole`,
`Valsartan`, `Deoxynivalenol`).  The PubChem rule picks a name for a CAS from a
single source with no agreement requirement, and 70% of its pairs name a
different substance outright:

    '2-aminotoluene Hydrochloride'  ->  'methanol'
    'Calcium Ethynediide'           ->  'piperidin-2-one'
    'Sodium Chloride'               ->  'sea water'

**That audit is about identity, not specificity** (#224).  It asks whether the
replacement is a name the CAS has, so it cannot see a replacement that names
something *broader* than the flow is: `Xylene (all isomers)` -> `Xylene` scores
in its benign bucket, because `xylene` is a name CAS 1330-20-7 holds and
`xylene (all isomers)` is not.  That is the archetypal specificity loss, and it
is the case that motivated this file.

So the number above says what it says -- 0 pairs asserting an unsupported
identity -- and nothing about scope.  `tools/build_scope_narrowing_shortlist.py`
asks the second question over the renames this rule *applied*, which reach no
queue precisely because the rule is trusted by default: of the 741 pairs and
9,530 flows in the 2026-08-06 run, 71 pairs drop a qualifier the current name
carries.  A chemist has not read them yet.  If that shortlist turns out to hold
real narrowings at any rate worth acting on, what changes is the scope of this
constant: the `synonym_swap` half of the rule keeps the default and the
`systematic_to_common` half joins the queue.

**The PubChem rule no longer renames** (#222).  Gating it only decided what an
unruled proposal did by default, which left 117 pairs waiting on a curator to
salvage the 38 of them that were right.  A rule that names a different substance
two times in three is not a rule with a curation backlog, it is a rule that does
not work, and its corroborated proposals were already arriving as altLabels by
another path.  `consensus_match` documents the removal at the site.

What `DEFAULT_APPROVED_RULES` still decides is the fallback for
`multi_source_consensus`, the vote a CAS falls back to when Common Chemistry and
ChEBI do not both name it.  A rule outside the set refuses an undecided pair and
queues it, because for such a rule the failure modes are not symmetric: an
unapplied rename leaves a label that is merely worse, and a wrongly applied one
publishes a label that is untrue.  For a rule inside it the asymmetry runs the
other way -- refusing by default discards thousands of correct names to catch
errors that rule does not make.

**The vote stays out, and that is now measured too** (#245).  It could not be
until this year: the rule compared its candidate against the flow *object's*
label while renaming that object's *members*, so it proposed nothing at all --
0 pairs and 0 renames in the 2026-08-06 run.  With the comparison made per
member, the same inputs produce 26 pairs over 279 flows, and neither number is
the deciding one:

    pairs asserting an identity CC and ChEBI do not support          0 of 26
    pairs naming something broader than the flow is                  3 of 26

The identity audit flags two, and both are the current name respelt --
`'2,3,4,5-tetrachlorobenzoyl Chloride'` losing a space, and a Greek alpha the
name caser had capitalised to `Α`.  Neither names another substance; they are
flagged because the audit compares names without folding whitespace out.

The three that matter are the other question, the one that audit cannot ask:
`'Carbon, Organic, In Soil Or Biomass Stock' -> 'Carbon'`,
`'Iodine, 0.03% In Water' -> 'Iodine'` and `'Nitrogen, Organic Bound' ->
'dinitrogen'`.  Each is the `Xylene (all isomers)` error, at roughly one pair in
nine.  Against that, default-approving the rule would spare a curator 279 flows
-- 3% of what the CC/ChEBI rule carries, which is what makes refusing by default
cheap here and expensive there.  So the rule proposes and a curator rules, and
`tools/build_label_worklist.py` is what puts its 26 pairs in front of one.

**A curator has now read them** (#313).  The 2026-08-16 queue held 27 distinct
pairs over 293 flows -- 25 from `multi_source_consensus` and 2 proposed by both
it and the element pass -- and they came out 23 approved, 3 refused and 1 left
undecided on purpose.  The split is roughly what the audits predicted and is
worth recording, because it is the only evidence about this rule that comes from
reading rather than from counting:

- **Nineteen were typography**, and four of those were this build's own doing
  rather than the source's.  `Copper (i) Chloride`, `Copper (ii) Sulfate` and
  `O,o,o-triethylphosphorothioate` are the name caser title-casing an oxidation
  state and a set of element-symbol locants -- neither is a word -- and
  `Poly[oxy(methyl-1,2-ethanediyl)], Α-butyl-ω-hydroxy-` is it capitalising a
  Greek alpha into a letter that is not a locant at all.  Of the remaining
  fifteen, most were a space the source list had lost -- `Dihexylphthalate`,
  `Terephthaloyldichloride`, `Potassiumtetrafluoroaluminate` -- and five were
  the bicarbonates and hydrogen phosphates plus the bicarbonate ion itself,
  where Common Chemistry writes `hydrogen carbonate` and ChEBI
  `hydrogencarbonate`, and the list had the words split and then both
  capitalised.  Those five are ruled together so that the ion and its salts
  stay spelt the same way.
- **Three were about more than spelling, and two of those were refused.**  The
  rejections are `Carbon, Organic, In Soil Or Biomass Stock` -> `Carbon`, a
  scope loss whose object already carries five flows called `Carbon` for carbon
  emitted to ground, and `Glycerol Octanoate Decanoate` -> the fourteen-word
  systematic name, which is a readability choice rather than a scope one --
  both names are Common Chemistry's for 65381-09-1, so nothing about identity
  was at stake.  `Iodine, 0.03% In Water` -> `Iodine` was
  approved, because ecoinvent 3.12 names that flow `Iodine` itself and the
  `Resource -> Water` context carries what the qualifier said; no contributing
  list calls the soil-carbon stock `Carbon`.  So the shape of a pair does not
  decide it and the other lists' names are evidence -- which is the part the
  `Xylene (all isomers)` rule of thumb misses.
- **One ran backwards.**  `HC Blue No. 1` -> `HC Blue No.1` deletes a space from
  the name Common Chemistry holds, and the identity audit scores it
  `synonym_swap` because it compares names with whitespace folded.  A verdict of
  `synonym_swap` means the pair is safe on identity, not that the replacement is
  the better name.
- **One was left undecided** (#312): the substance is fluorescein's disodium
  salt named `Fluorescein`, so approving publishes an unreadable systematic name
  and rejecting records that `Fluorescein` is correct for a salt.  Neither is
  true, so neither is written down.

  **It has since been answered, and not here** (#312).  A ruling could only ever
  choose between the two names it was shown, and the name the substance should
  carry was neither of them: EF 3.1 ships all thirteen rows with the salt's
  registry number, the salt's EC number and a comment saying the name and a
  synonym were interchanged, so the wrong field was the source's name rather
  than the label rule's proposal.  `ef-3.1-manual-fixes.json` corrects it to
  `Fluorescein sodium`, and what reaches this file afterwards is
  `Fluorescein sodium` -> the systematic name, which is a readability choice
  between two names of one substance and is refused as such.  That is the
  general shape of an undecided pair worth looking at: where neither answer is
  true, the question is usually being asked about the wrong field.

The rule stays out of `DEFAULT_APPROVED_RULES` regardless.  Having read one
run's proposals says nothing about the next run's, and two of the twenty-seven
would have published something worse had nobody looked.

A `reject` ruling always wins, whichever rule proposed the pair.

**A ruling is keyed on the pair, not on the stage that proposed it** (#16).
The question a curator answers is "is the replacement a name this substance
actually has", and that is a fact about the two names; the same pair proposed by
a different stage has the same answer.  The stage matters only for what happens
when nobody has answered, which is what `DEFAULT_APPROVED_RULES` says and why the
rule name travels with the proposal into the review queue.

This module sits in `domain` rather than next to `consensus_match` for that
reason: the gate is not one transformer's private business, and the element pass
that also needs it runs in `pipeline`, after every transformer has finished.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

import orjson
import structlog

from brightway_flows.domain.labels import canonical_label_value
from brightway_flows.domain.records import SerialisableRecord
from brightway_flows.filesystem import PACKAGE_DATA_DIR

logger = structlog.get_logger(__name__)

DECISIONS_FILEPATH = (
    PACKAGE_DATA_DIR / "preferred-label-decisions.json"
)

APPROVE = "approve"
REJECT = "reject"
VALID_DECISIONS = frozenset({APPROVE, REJECT})

#: Rules whose undecided pairs are applied rather than deferred.  See the module
#: docstring for the audit this comes from: over one full run, `cc_chebi_agreement`
#: proposed 724 pairs and none of them asserted an identity that Common Chemistry
#: and ChEBI do not both support, while the PubChem-backed `entropy` rule got 80
#: of 114 wrong and was removed for it.  Adding a rule here is a claim about that
#: rule's error rate, and wants the same measurement behind it -- and the claim
#: is only as wide as the measurement: that audit covers identity and not scope,
#: which is what `tools/build_scope_narrowing_shortlist.py` exists to put in
#: front of a reader (#224).  `multi_source_consensus` has been measured on both
#: questions and is deliberately absent: 0 of its 26 pairs get identity wrong and
#: 3 of them narrow scope, over 279 flows it would not be worth publishing
#: unread (#245).
DEFAULT_APPROVED_RULES = frozenset({"cc_chebi_agreement"})


@dataclass(frozen=True)
class LabelDecision:
    """One curated ruling on one (current, replacement) pair."""

    current: str
    replacement: str
    decision: str
    notes: str = ""

    @property
    def approved(self) -> bool:
        return self.decision == APPROVE


def decision_key(current: str, replacement: str) -> tuple[str, str]:
    """The key a decision is stored and looked up under.

    `canonical_label_value` folds case, whitespace and markup, so one entry
    covers every spelling of the same ruling -- which is what lets a single row
    decide both `HCFC-140` and `Hcfc-140`, the pair that made #219's
    "same input, different output" look like non-determinism.
    """
    return (canonical_label_value(current), canonical_label_value(replacement))


def load_preferred_label_decisions(
    path: Path | None = None,
) -> dict[tuple[str, str], LabelDecision]:
    """Read the curated decisions, keyed by `decision_key`.

    A malformed or absent file yields an empty index, which -- given the
    default-refuse rule above -- means no preferred label is replaced at all.
    That is the safe direction to fail in.
    """
    source = path or DECISIONS_FILEPATH
    if not source.exists():
        logger.warning("preferred_label_decisions_missing", path=str(source))
        return {}

    payload: Any = orjson.loads(source.read_bytes())
    if not isinstance(payload, dict) or not isinstance(payload.get("decisions"), list):
        logger.warning("preferred_label_decisions_malformed", path=str(source))
        return {}

    index: dict[tuple[str, str], LabelDecision] = {}
    for row in payload["decisions"]:
        if not isinstance(row, dict):
            continue
        current = str(row.get("current") or "").strip()
        replacement = str(row.get("replacement") or "").strip()
        decision = str(row.get("decision") or "").strip().lower()
        if not current or not replacement:
            continue
        if decision not in VALID_DECISIONS:
            # A typo here would otherwise read as "not decided", which silently
            # turns an approval into a refusal.
            logger.warning(
                "preferred_label_decision_invalid",
                current=current,
                replacement=replacement,
                decision=decision,
            )
            continue
        index[decision_key(current, replacement)] = LabelDecision(
            current=current,
            replacement=replacement,
            decision=decision,
            notes=str(row.get("notes") or ""),
        )

    logger.info(
        "loaded_preferred_label_decisions",
        path=str(source),
        approved=sum(1 for d in index.values() if d.approved),
        rejected=sum(1 for d in index.values() if not d.approved),
    )
    return index


class LabelRuling(StrEnum):
    """What the curation says about one proposed replacement.

    Four outcomes, not a boolean, because the caller has to tell "nobody has
    ruled on this" from "somebody said no": the first is work for a curator and
    belongs in the review queue, the second is already answered.
    """

    #: The two names are the same modulo case, spacing and markup.  Not a
    #: substance change, so it needs no ruling.
    SAME_NAME = "same_name"
    #: Ruled `approve`, or proposed by a rule trusted to be right by default.
    APPROVED = "approved"
    #: Ruled `reject`.  Final, whichever rule proposed it.
    REJECTED = "rejected"
    #: No ruling covers this pair, and the proposing rule does not carry the
    #: benefit of the doubt.  The current label stands and a curator is asked.
    UNDECIDED = "undecided"


def rule_on_replacement(
    decisions: dict[tuple[str, str], LabelDecision],
    *,
    current: str,
    replacement: str,
    rule: str,
) -> LabelRuling:
    """How *current* -> *replacement*, proposed by *rule*, is ruled on.

    The whole of the gate, so that both stages that replace a published label
    are held to the same decision file.  It used to be a private method on
    `consensus_match`, which is why the element pass -- the other writer of a
    published `prefLabel` -- was not gated at all, and why the
    `Plutonium-alpha` -> `Plutonium` rejection then recorded in the decisions
    file sat inert across two full runs while that pass went on publishing
    `Plutonium` (#16).  That row is gone: #238 gave the aggregate its own flow
    object, so the pass no longer proposes the rename at all.
    """
    key = decision_key(current, replacement)
    if key[0] == key[1]:
        return LabelRuling.SAME_NAME

    decision = decisions.get(key)
    if decision is not None:
        return LabelRuling.APPROVED if decision.approved else LabelRuling.REJECTED

    if rule in DEFAULT_APPROVED_RULES:
        return LabelRuling.APPROVED

    return LabelRuling.UNDECIDED


@dataclass
class UndecidedLabelReplacement(SerialisableRecord):
    """A preferred-label rename a rule proposed and no curator has ruled on.

    Not applied: the current label stands until `preferred-label-decisions.json`
    says otherwise, so an unruled row publishes nothing wrong.  It is queued
    because a rename that silently did not happen is work forgotten.

    `cas` is the number the rule keyed the replacement on.  A ruling answers
    "is the replacement a name this substance actually has", and that is not
    answerable without it -- without it the row describes a decision and
    withholds the evidence for it.
    """

    uuid: str
    rule: str
    current: str
    replacement: str
    cas: str = ""
    decision: str = "undecided"
    hint: str = (
        "Add an entry to preferred-label-decisions.json to approve or reject "
        "this replacement; until then the current label stands."
    )


@dataclass
class UndecidedLabelPair(SerialisableRecord):
    """A rename pair awaiting a ruling, with every occurrence folded into it.

    A rule renames a whole flow object at once -- 176 flows carried only 18
    distinct pairs in the run that prompted this -- so a curator rules on the
    pair, not on each occurrence.

    `cas_numbers` accumulates rather than taking the first, unlike
    `example_uuid`: a ruling is keyed on the pair and so binds every CAS that
    produced it, and showing one while the ruling binds several would hide
    exactly the case where the pair means different things for different
    substances.
    """

    rule: str
    current: str
    replacement: str
    flow_count: int = 0
    example_uuid: str = ""
    cas_numbers: list[str] = field(default_factory=list)
    decision: str = "undecided"
    hint: str = ""


def fold_undecided_label_pairs(
    replacements: list[UndecidedLabelReplacement],
) -> list[UndecidedLabelPair]:
    """Undecided renames folded to one row per pair, most-affecting first.

    A rule renames a whole flow object at once -- 176 flows carried only 18
    distinct pairs in the run that prompted this -- so a curator rules on the
    pair and the occurrences are counted rather than listed.
    """
    pairs: dict[tuple[str, str], UndecidedLabelPair] = {}
    for item in replacements:
        key = decision_key(item.current, item.replacement)
        pair = pairs.get(key)
        if pair is None:
            pair = UndecidedLabelPair(
                rule=item.rule,
                current=item.current,
                replacement=item.replacement,
                example_uuid=item.uuid,
                decision=item.decision,
                hint=item.hint,
            )
            pairs[key] = pair
        pair.flow_count += 1
        if item.cas and item.cas not in pair.cas_numbers:
            pair.cas_numbers.append(item.cas)

    for pair in pairs.values():
        pair.cas_numbers.sort()
    return sorted(pairs.values(), key=lambda pair: (-pair.flow_count, pair.current))


def undecided_label_item_key(rule: str, current: str, replacement: str) -> str:
    """The review-queue key for one unruled pair.

    Carries the rule as well as the pair because the queue table is keyed on
    `(queue_name, item_key)` and two stages can now propose the same rename --
    the ruling binds both, but they are two rows of work, and a shared key would
    make the second one a primary-key collision rather than a queue entry.
    """
    return ":".join((rule, *decision_key(current, replacement)))
