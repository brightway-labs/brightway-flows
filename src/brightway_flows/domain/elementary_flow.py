"""The `ElementaryFlow` record: one substance in one context.

Sibling of `Flow` and `FlowObject`, and the third of the record types
`domain.records` describes.  It lived in `flow_layers` because that is where it
is created, which put `domain.schema` -- which needs it to generate the
published schema -- on an import edge back out of `domain`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha1
from typing import Any, ClassVar

from brightway_flows.domain.context import Context
from brightway_flows.domain.context_registry import (
    context_field_from_serialised,
    context_field_to_serialised,
)
from brightway_flows.domain.lcia.records import (
    FLOW_ENTRIES_SCHEMA,
    StatedFactor,
    flow_entries,
    stated_factors,
)
from brightway_flows.domain.records import SerialisableRecord
from brightway_flows.domain.vocabulary import (
    DCTERMS_IS_REPLACED_BY,
    OWL_DEPRECATED,
)

#: What a minted identifier is a hash *of*, so that a hash of the same substance
#: and compartment computed anywhere else is the same string.  Namespaced, like
#: the basis :func:`~brightway_flows.domain.flow_object.stable_flow_object_id`
#: takes, so that a flow identifier and a flow-object identifier can never
#: collide even where the two are given the same pair of arguments.
MINTED_FLOW_ID_BASIS_PREFIX = "consensus-minted-flow"


def minted_elementary_flow_id(flow_object_id: str, context_iri: str) -> str:
    """The identifier for a flow this project mints, from what makes it that flow.

    A flow is one substance in one context, and those two are what the merge
    already treats as its identity: every path that adds a flow asks
    ``flows_for_object_in_context`` first and joins the flow that is there
    rather than minting a second one.  So the pair is the identity, and the
    identifier is a function of it and of nothing else.

    **Not the source row that reached the compartment first.**  Until #102 the
    basis carried that row's uuid as well, and the row is not a property of the
    flow: on the build of 805e72f, 188 of the 2,561 minted flows were reached by
    more than one source row, so which of them named the flow was whichever the
    merge happened to see first.  It moved when a vendor added a row that sorted
    earlier, when a curated fix let an existing row through -- BAFU's river water
    was renamed by #78 doing exactly that, with nothing about the water changed
    -- when the lists were merged in a different order, and when a row was
    removed and promoted whichever row had been second.  Nothing deprecated the
    old identifier in any of those cases: it was simply absent from the next
    build, which is a silent miss for whoever had pinned it.

    **Not the unit either**, although a substance can be published in more than
    one.  The merge cannot mint two flows for one substance in one context
    whatever their units, so a unit in the basis could never separate two flows
    -- it could only rename the one, on the day a unit is corrected, which is
    again a change to how the quantity is written and not to which flow it is.

    The identifiers this returns are 40-character sha1 hex, distinguishable from
    the base list's own uuids, which the merge does not mint and must not move.
    """
    basis = f"{MINTED_FLOW_ID_BASIS_PREFIX}:{flow_object_id}:{context_iri}"
    return sha1(basis.encode("utf-8")).hexdigest()


@dataclass
class ElementaryFlow(SerialisableRecord):
    """One substance in one context.

    ``(flow_object_id, context_iri)`` must be unique across non-deprecated flows.
    """

    elementary_flow_id: str
    flow_object_id: str
    source: str
    #: Absent on a flow no source list has been merged onto -- which is most of
    #: them: 400 of the 596 in a bounded run are EF 3.1 flows with no source
    #: reference at all.  Declared required, this record could not represent
    #: them, and `from_dict` raised on two thirds of the file it names.
    #:
    #: `kw_only` rather than reordering: a default may not precede a
    #: non-defaulted field, and moving the declaration would move the key in
    #: `to_dict()` output and so in the published artifact.
    source_refs: list[dict[str, Any]] | None = field(default=None, kw_only=True)
    #: Required, and a `Context` rather than `Any`: an elementary flow *is* a
    #: substance in a context, so a record without one is not one of these.
    #: Nothing constructs it without a context either -- the layering is reached
    #: only after `validate_flow_contexts` has refused any flow the mapping
    #: could not place (#97).
    context: Context
    context_iri: str
    unit: str | None
    unit_iri: str | None
    #: The source list's characterisation factors, as records; see `Flow`, which
    #: is also where the note about reading a factor from here lives.
    lcia_methods: list[StatedFactor]
    general_comment: str | None
    # Defaulted so a merge-created flow can be built without one; every record
    # then carries the key, rather than only transform-created ones.
    cas_match_labels: dict[str, str] = field(default_factory=dict)
    # Attached after layering by _attach_concept_associations.
    concept_associations: list[dict[str, Any]] | None = None
    # Set by the duplicate-deprecation pass; absent on active flows.
    owl_deprecated: bool | None = None
    dcterms_is_replaced_by: str | None = None
    is_replaced_by_uuid: str | None = None
    # Source-specific keys, e.g. the label and property fields the merge
    # pipeline inherits onto its added flows.
    extra: dict[str, Any] = field(default_factory=dict)

    _ALIASES: ClassVar[dict[str, str]] = {
        "owl_deprecated": OWL_DEPRECATED,
        "dcterms_is_replaced_by": DCTERMS_IS_REPLACED_BY,
    }
    _OMIT_IF_NONE: ClassVar[frozenset[str]] = frozenset({
        "source_refs", "concept_associations", "owl_deprecated",
        "dcterms_is_replaced_by", "is_replaced_by_uuid",
    })
    _EXTRA_FIELD: ClassVar[str | None] = "extra"
    _CODECS: ClassVar[dict[str, tuple[Any, Any]]] = {
        "context": (context_field_to_serialised, context_field_from_serialised),
        "lcia_methods": (flow_entries, stated_factors),
    }
    _SERIALISED_SCHEMAS: ClassVar[dict[str, Any]] = {
        "lcia_methods": FLOW_ENTRIES_SCHEMA,
    }
