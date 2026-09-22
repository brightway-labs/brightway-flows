"""One entry in a flow's ``source_refs``: which list a flow came from.

There were three models of this and the thing actually stored was none of them
(#92):

* ``domain.models.SourceRef`` -- a Pydantic model, reached only as the declared
  element type of ``HarmonisedFlow.source_refs``, so it validated an input
  file's references and was never constructed anywhere;
* ``flow_layers.layering.FlowSourceRef`` -- a dataclass with the identical five
  fields, constructed and then ``asdict()``-ed on the next line, so it existed
  for the duration of one expression;
* ``webapps.app.queries.flows.SourceReference`` -- the read side.

``Flow.source_refs`` and ``ElementaryFlow.source_refs`` are declared
``list[dict[str, Any]]``, and every reader does ``ref.get("list_name")``.
``docs/reference/architecture.md`` names the rule this broke: *avoid parallel
models for the same concept*.

This is that concept, once. It is a ``SerialisableRecord`` like the three flow
records, so it converts at an I/O boundary and is read by attribute everywhere
else.

**It is still the boundary contract.** ``HarmonisedFlow.source_refs`` is
declared ``list[SourceRef]`` against this class, and Pydantic validates a
stdlib dataclass exactly as it validated the model it replaces -- a reference
missing ``source_flow_uuid`` raises at the file boundary as before. That is why
one class can serve both roles here where ``HarmonisedFlow`` and ``Flow`` need
two: ``Flow`` is separate because ``validate_assignment=True`` would re-run
validation on every attribute write in a hot loop over 94k records, and nothing
writes to a source reference in a loop.

The webapp's ``SourceReference`` stays separate on purpose, and says so in its
own docstring: it is built from four columns of ``elementary_flow_sources`` and
has no ``source_metadata`` to carry, so sharing this record would put a field on
it that is structurally always empty.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from brightway_flows.domain.records import SerialisableRecord


@dataclass
class SourceRef(SerialisableRecord):
    """A flow in a source list, named as that list named it.

    ``(list_name, list_version)`` is the identity of the list -- the same pair
    `SourceList` carries and the `elementary_flow_sources` table stores. It is
    *given* to the code that builds one of these, never re-derived from
    ``flow.source``, which is a display string (#13).

    ``source_metadata`` is an open bag and stays one: it holds whatever a
    particular list needs to say about the row it shipped -- the base list puts
    the vendor's own compartment strings there, a merge puts the source unit.
    Declaring its keys would mean declaring them for every list.

    Field order is the order the keys were written under ``asdict()``, and the
    published shape must not move: these reach ``elementary_flow_sources``,
    which is the only copy of them anything keeps (#30).
    """

    list_name: str
    #: ``kw_only`` so it keeps its place in the serialised order while carrying
    #: the default the Pydantic model gave it -- an input file may name a list
    #: without pinning a release. The same trick, for the same reason, as
    #: ``ElementaryFlow.source_refs``.
    list_version: str = field(default="", kw_only=True)
    source_flow_uuid: str
    source_flow_name: str
    source_metadata: dict[str, Any] = field(default_factory=dict)
