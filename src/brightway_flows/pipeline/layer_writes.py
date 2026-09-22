"""What the passes after the layering wrote, on its way to the changelog.

`ChangeEvent` used to be constructed in exactly one place -- `apply_transformers`
-- and `pipeline_sources` written in exactly one place, the line below it. Every
write the run made *after* `resolve_flow_layers` was therefore invisible:

* `ElementPrefLabelPass` replaces a published `prefLabel` outright;
* `_link_flows_to_their_substance` overwrites `properties`, `types`,
  `origin_qualifier` and the two parent identifiers with the substance's
  answers;
* the duplicate pass sets `owl_deprecated` and the two replacement fields.

None of it appeared in `changelog`, so
:mod:`brightway_flows.pipeline.review_records` claiming the table makes
"everything that happened to this substance answerable without a join" was true
of the transformer chain and not of the run. A curator reading a flow whose name
the element pass had changed saw the change had never happened.

This is the `Change` discipline for the passes, without the proposal step.
A transformer *proposes* changes because it is shown the whole list and must not
mutate it while other transformers are still reading; a layer pass holds both
layers and writes to them directly, which is why it is not a transformer. What
it shares is that the write must be recorded where it is made.

Two differences from `Change`, both deliberate:

* **A write that changes nothing is not recorded.** `apply_transformers` logs
  every applied change, including no-ops, because a transformer proposing one is
  itself worth seeing. Here the caller is a bulk copy --
  `_link_flows_to_their_substance` assigns `properties` onto all 94k flows,
  and on the 2026-08-12 build only 815 of 7,674 objects differed from the flow
  that carried them. Logging the rest would add hundreds of thousands of rows
  saying nothing.
* **The old value is captured before the write, and the label with it.** A
  `ChangeEvent` carries `flow_name`, and the element pass changes exactly that,
  so reading the label afterwards would report every rename as being *from* its
  new name.

A pass that does not want to record -- the merge reuses several of these over a
subset of its own -- passes no log and gets one that is discarded. Nothing
branches on whether recording is on.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from brightway_flows.domain.flow import Flow
from brightway_flows.domain.labels import flow_label_value
from brightway_flows.pipeline.review_records import ChangeEvent


@dataclass(frozen=True)
class LayerWrite:
    """One field a pass wrote onto a flow after the transformer chain.

    Mirrors `ChangeEvent` rather than being one, because `change_index` and
    `flow_object_id` are filled in by the writer and a pass has no business
    guessing them. :meth:`as_change_event` does the conversion once, where the
    log is drained.
    """

    uuid: str
    field_name: str
    old_value: Any
    new_value: Any
    pass_name: str
    #: The flow's label *before* the write, so a rename reports what it renamed.
    flow_name: str = ""
    comment: str = ""

    def as_change_event(self) -> ChangeEvent:
        return ChangeEvent(
            uuid=self.uuid,
            flow_name=self.flow_name,
            field_name=self.field_name,
            old_value=self.old_value,
            new_value=self.new_value,
            transformer=self.pass_name,
            comment=self.comment,
        )


@dataclass
class LayerWriteLog:
    """Applies a pass's writes and remembers the ones that changed something.

    Always applies. Whether anything is *recorded* is a property of this object,
    not of the call site, so a pass reads the same however it is being used.
    """

    writes: list[LayerWrite] = field(default_factory=list)

    def write(
        self,
        flow: Flow,
        field_name: str,
        new_value: Any,
        *,
        pass_name: str,
        comment: str = "",
    ) -> bool:
        """Set *field_name* on *flow*, and record it if the value moved.

        *field_name* is validated against `Flow` exactly as `Change` validates
        it, so a misspelling raises here rather than creating an attribute
        nothing reads.

        Returns whether the value changed, which is what a pass counting its own
        work wants -- several of them keep a `Counter` and would otherwise have
        to compare the values a second time.
        """
        attribute = Flow.resolve_field(field_name)
        old_value = getattr(flow, attribute)
        if old_value == new_value:
            return False
        self.writes.append(LayerWrite(
            uuid=flow.uuid,
            field_name=attribute,
            old_value=old_value,
            new_value=new_value,
            pass_name=pass_name,
            flow_name=flow_label_value(flow),
            comment=comment,
        ))
        setattr(flow, attribute, new_value)
        flow.pipeline_sources[attribute] = pass_name
        return True

    def change_events(self) -> list[ChangeEvent]:
        """Everything recorded, as changelog rows, oldest first."""
        return [write.as_change_event() for write in self.writes]
