"""The preferred label of a flow whose substance is a chemical element.

A flow object typed `chemrof:ChemicalElement` carries the element's name, and
this pass writes that name -- titlecased -- onto every flow that resolves to it,
so that the published list says `Nitrogen` wherever a source list said
`nitrogen`, `NITROGEN` or `Nitrogen `.

Casing is all it was ever meant to do, but until #16 it wrote whatever the
element name said, unconditionally: a flow whose own name was *more specific*
than its object's -- an allotrope, an isotope, a phase -- lost that specificity
at publication, and no ruling could stop it, because this was the one writer of
a published `prefLabel` that `preferred-label-decisions.json` did not gate.  The
`Plutonium-alpha` -> `Plutonium` rejection recorded in that file sat inert for
exactly this reason, and `Plutonium` went on being published across the runs of
#220 and #221.  That particular pair no longer reaches here: #238 found that
`Plutonium-alpha` is the radiological aggregate rather than a phase, and gave it
its own flow object, so the object this pass reads is no longer an element's.

So the pass proposes now rather than asserting.  A titlecase of the name the
flow already has is not a rename and still happens outright; anything else is a
rename, is ruled on by the same file and the same function as `consensus_match`,
and where no ruling covers it the flow keeps its own label and a curator is
asked.  Refusing by default is the right direction to fail in: an unapplied
titlecase leaves a label that is merely ugly, while an applied flattening
publishes a label naming a broader substance than the flow is.

Deliberately not a `Transformer`: it needs the flow objects and their semantic
types, which are resolved after every transformer has run.
"""

from __future__ import annotations

import structlog

from brightway_flows.domain.common import Provenance
from brightway_flows.domain.flow import Flow
from brightway_flows.domain.flow_object import FlowObject
from brightway_flows.pipeline.layer_writes import LayerWriteLog
from brightway_flows.domain.labels import flow_label_value
from brightway_flows.domain.preferred_label_decisions import (
    LabelDecision,
    LabelRuling,
    UndecidedLabelPair,
    UndecidedLabelReplacement,
    fold_undecided_label_pairs,
    load_preferred_label_decisions,
    rule_on_replacement,
    undecided_label_item_key,
)
from brightway_flows.domain.vocabulary import (
    CHEMROF_CHEMICAL_ELEMENT,
    CHEMROF_ELEMENTAL_CHARGE,
)
from brightway_flows.flow_layers.labels import _set_pref_label
from brightway_flows.flow_layers.provenance import ELEMENT_ENRICHMENT_GENERATED_BY
from brightway_flows.pipeline.review_records import (
    ReviewQueue,
    ReviewQueueItem,
    Severity,
)
from brightway_flows.sources import base_source_label

logger = structlog.get_logger(__name__)


def _element_titles_by_object_id(flow_objects: list[FlowObject]) -> dict[str, str]:
    """The titlecased element name of every flow object typed as an element."""
    titles: dict[str, str] = {}
    for obj in flow_objects:
        object_id = obj.flow_object_id.strip()
        if not object_id:
            continue
        raw_types = obj.types
        if isinstance(raw_types, str):
            object_types = [raw_types]
        elif isinstance(raw_types, list):
            object_types = [str(x) for x in raw_types if isinstance(x, str) and x.strip()]
        else:
            object_types = []
        if CHEMROF_CHEMICAL_ELEMENT not in object_types:
            continue
        title_name = flow_label_value(obj).strip().title()
        if title_name:
            titles[object_id] = title_name
    return titles


class ElementPrefLabelPass:
    """Applies the element name to its flows, subject to the label rulings.

    A `ReviewQueueProvider` rather than a function, so that the renames it did
    not take reach `review_queue` the way every other stage's do:
    `collect_review_queue_items` asks whatever it is handed, so this is handed
    to it alongside the transformers.
    """

    #: What `prov:wasGeneratedBy` says on the labels this writes, and the rule
    #: name a ruling in `preferred-label-decisions.json` is recorded against.
    #: Not in `DEFAULT_APPROVED_RULES`: an unruled proposal from here defers.
    name = ELEMENT_ENRICHMENT_GENERATED_BY

    def __init__(
        self,
        decisions: dict[tuple[str, str], LabelDecision] | None = None,
        *,
        writes: LayerWriteLog | None = None,
    ):
        self._decisions = (
            load_preferred_label_decisions() if decisions is None else decisions
        )
        self.undecided_label_replacements: list[UndecidedLabelReplacement] = []
        #: Where the labels this pass replaces are recorded.  A caller that
        #: wants them in the changelog passes its own log and drains it; one
        #: that does not gets this and discards it, so `_write` reads the same
        #: either way.  Until #92 this pass rewrote a *published* prefLabel
        #: and left no trace of having done so.
        self.writes = LayerWriteLog() if writes is None else writes

    def apply(self, flows: list[Flow], flow_objects: list[FlowObject]) -> dict[str, int]:
        """Write the element name onto the flows the rulings allow it on."""
        titles = _element_titles_by_object_id(flow_objects)
        stats = {
            "element_objects": len(titles),
            "labelled": 0,
            "titlecased": 0,
            "renamed": 0,
            "rejected": 0,
            "undecided": 0,
        }

        for flow in flows:
            title_name = titles.get(flow.flow_object_id.strip(), "")
            if not title_name:
                continue
            current = flow_label_value(flow).strip()
            if not current:
                # Nothing to replace, so nothing to rule on -- the reason
                # `bootstrap_labels` is not gated either.  A flow published
                # with no label at all is worse than one published with its
                # element's name.
                stats["labelled"] += 1
                self._write(flow, title_name)
                continue
            ruling = rule_on_replacement(
                self._decisions,
                current=current,
                replacement=title_name,
                rule=self.name,
            )
            if ruling is LabelRuling.REJECTED:
                stats["rejected"] += 1
                continue
            if ruling is LabelRuling.UNDECIDED:
                stats["undecided"] += 1
                self.undecided_label_replacements.append(UndecidedLabelReplacement(
                    uuid=flow.uuid,
                    rule=self.name,
                    current=current,
                    replacement=title_name,
                    cas=flow.cas_numbers[0] if flow.cas_numbers else "",
                ))
                continue

            stats["titlecased" if ruling is LabelRuling.SAME_NAME else "renamed"] += 1
            self._write(flow, title_name)

        logger.info("element_pref_labels", **stats)
        return stats

    def _write(self, flow: Flow, title_name: str) -> None:
        """Replace *flow*'s preferred label with the element's name."""
        self.writes.write(
            flow,
            "prefLabel",
            [
                {
                    "@value": title_name,
                    "@language": "en",
                    "@lang": "en",
                    "source": Provenance(
                        was_generated_by=self.name,
                        was_attributed_to="brightway-flows",
                        had_primary_source=[base_source_label(), "PubChem"],
                        was_derived_from="flow_object.prefLabel.titlecase",
                    ).to_dict(),
                }
            ],
            pass_name=self.name,
            comment=f"element name from the flow object: {title_name}",
        )

    def undecided_label_pairs(self) -> list[UndecidedLabelPair]:
        """This run's unruled element renames, folded to one row per pair."""
        return fold_undecided_label_pairs(self.undecided_label_replacements)

    def review_queue_items(self) -> list[ReviewQueueItem]:
        """Every element rename this pass refused for want of a ruling.

        The same queue `consensus_match` fills, because it is the same question
        and the same file answers it -- the rule name in the row is what says
        which stage asked.
        """
        return [
            ReviewQueueItem(
                queue_name=ReviewQueue.UNDECIDED_LABEL_REPLACEMENT,
                item_key=undecided_label_item_key(
                    pair.rule, pair.current, pair.replacement
                ),
                title=f"{pair.current} → {pair.replacement}",
                severity=Severity.BLOCKING,
                uuid=pair.example_uuid,
                cas=pair.cas_numbers[0] if pair.cas_numbers else "",
                payload=pair.to_dict(),
            )
            for pair in self.undecided_label_pairs()
        ]


#: The fallback name `flow_layers.ions` gives an ion whose charge it could not
#: work out: `Iron, ion`, `Tin, ion`.  Matched case-insensitively, because it is
#: written before the label is titlecased and read after.
_UNSPECIFIED_CHARGE_SUFFIX = ", ion"


def _stated_charge(obj: FlowObject) -> int | None:
    """The one charge *obj* states, or ``None`` where it states none or several.

    Several is not an error and is why this returns ``None`` rather than the
    first: a salt states formulas at more than one charge, and `+1` and `-1` on
    one object is two readings of a substance rather than a charge it has.
    """
    properties = obj.properties
    if not isinstance(properties, dict):
        return None
    entry = properties.get(CHEMROF_ELEMENTAL_CHARGE)
    if not isinstance(entry, dict):
        return None
    values = entry.get("@value")
    if not isinstance(values, list):
        values = [values]
    charges = {int(v) for v in values if isinstance(v, (int, float))}
    if len(charges) != 1:
        return None
    charge = charges.pop()
    return charge if charge else None


def _ion_title_for(base: str, charge: int) -> str:
    """`Tin` and 4 as `Tin(4+)`, which is how every named ion here is spelled."""
    return f"{base}({abs(charge)}{'+' if charge >= 0 else '-'})"


class IonPrefLabelPass:
    """Name an ion for the charge it carries, once the charge is known.

    `flow_layers.ions` names an ion from its **label**: where the label has a
    numeral in it -- EF's `arsenic (v)`, ecoinvent's `Potassium(1+)` -- the name
    comes out as `Arsenic(5+)` and `Potassium(1+)`, and where it does not the
    module falls back to `X, ion`, meaning "I could not work out the charge".

    The charge then arrives anyway.  `transformers.enrich_references` reads it
    off PubChem against the registry number -- 17341-25-2 is sodium(1+),
    22537-50-4 is tin(4+) -- and transformers run **after** the flow layers, so
    by the time the charge is known the name is already written and nothing
    revisits it.  The result is that this list publishes `Tin(2+)` and
    `Tin, ion` side by side, which are stannous and stannic tin, and says which
    one it means only once (#128).

    So this pass runs late, where the charge is, and renames the objects whose
    fallback name has stopped being true.  It leaves alone the ones the fallback
    was written for: BAFU's `Iron, ion` and `Arsenic, Ion` carry no charge, no
    formula and no registry number, because iron II and iron III are different
    substances and the row does not say which is meant.  `X, ion` is the right
    name for those, and the whole point of asking for a *stated* charge is that
    they keep it.

    **Gated by `preferred-label-decisions.json`, like every other published
    rename**, which is #16's lesson and the reason this pass proposes rather
    than asserts.  An unruled rename leaves the object named as it was and asks
    a curator, so a spelling nobody has seen before is a question rather than a
    silent change.

    Renames the **flow object**.  The flows that resolve to it are renamed after,
    by `SubstancePrefLabelPass`, which is the one writer that gives a flow its
    substance's name (#7) -- so this has to run before that one, and does.
    """

    #: Its own rule name, so a ruling can approve an ion rename without
    #: approving the element renames `ElementPrefLabelPass` proposes.
    name = "ion_pref_label_from_stated_charge"

    def __init__(
        self,
        decisions: dict[tuple[str, str], LabelDecision] | None = None,
    ):
        self._decisions = (
            load_preferred_label_decisions() if decisions is None else decisions
        )
        self.undecided_label_replacements: list[UndecidedLabelReplacement] = []
        #: What this pass renamed, as `(flow_object_id, from, to)`.  Kept here
        #: rather than in a `LayerWriteLog`, which records a write to a *flow*
        #: and has no shape for a write to a flow object; the published trace is
        #: the provenance `_set_pref_label` stamps onto the label itself, the
        #: same way `flow_layers.ions` records the name it wrote in the first
        #: place.
        self.renames: list[tuple[str, str, str]] = []

    def apply(self, flow_objects: list[FlowObject]) -> dict[str, int]:
        stats = {
            "unspecified_charge_names": 0,
            "renamed": 0,
            "no_stated_charge": 0,
            "rejected": 0,
            "undecided": 0,
        }
        for obj in flow_objects:
            current = flow_label_value(obj).strip()
            if not current.lower().endswith(_UNSPECIFIED_CHARGE_SUFFIX):
                continue
            stats["unspecified_charge_names"] += 1
            charge = _stated_charge(obj)
            if charge is None:
                # The case the fallback name exists for.  Counted rather than
                # skipped silently: this number going to nought would mean the
                # ambiguity had been settled somewhere, which is worth seeing.
                stats["no_stated_charge"] += 1
                continue
            base = current[: -len(_UNSPECIFIED_CHARGE_SUFFIX)].strip()
            if not base:
                continue
            replacement = _ion_title_for(base, charge)
            ruling = rule_on_replacement(
                self._decisions,
                current=current,
                replacement=replacement,
                rule=self.name,
            )
            if ruling is LabelRuling.REJECTED:
                stats["rejected"] += 1
                continue
            if ruling is LabelRuling.UNDECIDED:
                stats["undecided"] += 1
                self.undecided_label_replacements.append(UndecidedLabelReplacement(
                    uuid=obj.flow_object_id,
                    rule=self.name,
                    current=current,
                    replacement=replacement,
                    cas="",
                ))
                continue
            stats["renamed"] += 1
            self._write(obj, replacement, charge=charge)

        logger.info("ion_pref_labels", **stats)
        return stats

    def _write(self, obj: FlowObject, replacement: str, *, charge: int) -> None:
        """Rename *obj*, leaving the reason on the label it writes."""
        current = flow_label_value(obj).strip()
        _set_pref_label(
            obj=obj,
            value=replacement,
            resolver_name=self.name,
            seed_source=base_source_label(),
            was_derived_from="ion.prefLabel.from_stated_elemental_charge",
            extra_primary_sources=["PubChem"],
        )
        self.renames.append((obj.flow_object_id, current, replacement))
        logger.debug(
            "ion_pref_label_renamed",
            flow_object_id=obj.flow_object_id,
            was=current,
            now=replacement,
            elemental_charge=charge,
        )

    def undecided_label_pairs(self) -> list[UndecidedLabelPair]:
        return fold_undecided_label_pairs(self.undecided_label_replacements)

    def review_queue_items(self) -> list[ReviewQueueItem]:
        return [
            ReviewQueueItem(
                queue_name=ReviewQueue.UNDECIDED_LABEL_REPLACEMENT,
                item_key=undecided_label_item_key(
                    pair.rule, pair.current, pair.replacement
                ),
                title=f"{pair.current} → {pair.replacement}",
                severity=Severity.BLOCKING,
                uuid=pair.example_uuid,
                cas="",
                payload=pair.to_dict(),
            )
            for pair in self.undecided_label_pairs()
        ]
