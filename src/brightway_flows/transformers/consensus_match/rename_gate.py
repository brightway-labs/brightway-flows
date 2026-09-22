"""This run's rulings, and the renames still waiting for one.

The ruling itself is not here: `rule_on_replacement` in
`domain.preferred_label_decisions` is the gate, shared with the element pass in
`pipeline.element_labels`, because a ruling is keyed on the pair of names and
not on the stage that proposed the rename.  What is here is the state one run
of consensus matching carries around that decision -- the loaded rulings, and
the proposals no ruling covers -- so that the rules can ask one object rather
than thread two.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from brightway_flows.domain.preferred_label_decisions import (
    LabelDecision,
    LabelRuling,
    UndecidedLabelPair,
    UndecidedLabelReplacement,
    fold_undecided_label_pairs,
    rule_on_replacement,
)


@dataclass
class RenameGate:
    """The curated rulings, and the proposals still waiting for one."""

    #: Curated rulings on (current, replacement) preferred-label pairs.
    decisions: dict[tuple[str, str], LabelDecision] = field(default_factory=dict)
    #: Replacements a rule proposed that no curator has ruled on.  Not applied;
    #: queued for review.  See `preferred_label_decisions`.
    undecided: list[UndecidedLabelReplacement] = field(default_factory=list)
    #: Registry numbers ruled contested in `contested-cas-decisions.json`.  A
    #: name derived from one of these belongs to only one of the substances
    #: carrying it, so no rename may be derived from it (#34).
    separated_cas: frozenset[str] = frozenset()
    #: `(cas, old_name, candidate)` per rename declined for that reason, so a
    #: rename that silently did not happen is still counted.
    declined_contested: list[tuple[str, str, str]] = field(default_factory=list)

    def reset(self) -> None:
        self.undecided = []
        self.declined_contested = []

    def approves(
        self, member_uuid: str, old_name: str, candidate: str, *, rule: str, cas: str = ""
    ) -> bool:
        """Whether replacing *old_name* with *candidate* may proceed.

        Both rename rules go through this.  Each replaces the preferred label of
        every member of a flow object, and a wrong one names a different
        substance -- `Xylene (all isomers)` becoming `Xylene` -- which nothing
        downstream can detect.  So the rules propose and
        `preferred-label-decisions.json` decides.

        There were three rules until the `entropy` rule was removed in #222: a
        rule wrong about identity in 68% of its proposals is not something a
        gate can rescue, because the gate only decides what an unruled proposal
        does by default.

        All this adds to the ruling is what to do with an undecided pair: not
        applied, and recorded so that a rename which silently did not happen is
        not work forgotten.
        """
        if cas and cas in self.separated_cas:
            # A number ruled contested (#34) is one that two substances in this
            # list carry, so the name it "has" belongs to only one of them.  Both
            # rename rules derive the candidate from the number, so for the other
            # substance the candidate is a different substance's name -- which is
            # how EF's `1,1,1-trichloroethane` came to be published as
            # `1,1,2-Trichloroethane`, the name Common Chemistry gives 79-00-5.
            #
            # Gated on the ruling and not on the contest, deliberately.  Declining
            # every rename from a contested number would have refused 11 good ones
            # for every 3 bad, `Baryte` -> `Barium sulfate` and this project's own
            # `HCFC-140` -> `1,1,1-Trichloroethane` among them: whether two names
            # under one number are one substance is a chemical question, and the
            # answer is the ruling rather than anything readable off the names.
            self.declined_contested.append((cas, old_name, candidate))
            return False

        ruling = rule_on_replacement(
            self.decisions, current=old_name, replacement=candidate, rule=rule
        )
        if ruling is not LabelRuling.UNDECIDED:
            return ruling is not LabelRuling.REJECTED

        self.undecided.append(UndecidedLabelReplacement(
            uuid=member_uuid,
            rule=rule,
            current=old_name,
            replacement=candidate,
            cas=cas,
        ))
        return False

    def undecided_pairs(self) -> list[UndecidedLabelPair]:
        """This run's unruled renames, folded to one row per pair."""
        return fold_undecided_label_pairs(self.undecided)
