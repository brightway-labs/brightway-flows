"""A signed substance takes its donor's published number where nobody states one.

Stepwise 2006 characterises zinc emitted to water at 133.39 for non-cancer human
toxicity and names no zinc ion.  `Zinc(2+)` has a flow in the same compartment,
every ecoinvent zinc emission lands on it, and nobody states anything for it --
so the flowchart never sees the key, `derive()` publishes nothing, and no queue
asks (#197).  The adoption route in `lcia.consensus` cannot reach it either: an
adoption there answers a row a *transcription* stated, and Stepwise has one
implementation.

This pass is the other route, and it is as narrow as the first.  An entry in
the method's adoptions file with ``number_from: donor`` says the recipient takes
the donor's **published** number, context for context: zinc's water number onto
the zinc ion's water flow, zinc's air number onto its air flow.  It runs after
`derive()`, the moves and the printings -- everything that states a number for
the donor has run -- and before the context convention, so the ion's own river,
lake and forestry-soil flows then take the number the way the element's do.

What it refuses is most of it:

* **a recipient the method's own publisher characterised anywhere.**  Stepwise
  names `Chromium III` and gives it no ecotoxicity number while giving the metal
  one; that is the publisher's decision about chromium, and an entry for the
  trivalent ion is refused whatever it says, counted under
  ``recipient_stated_by_a_publisher``;
* **a triple already published**, however it got there -- it never overwrites;
* **a donor factor that is itself carried or adopted**, so no chain walks a
  number two substances or two contexts away from anything a publisher stated;
* **a pair whose units differ** -- the ion flows are in kilograms of the
  element, as the element's are, and the check says so rather than assumes it;
* **a category the entry does not name**, and a donor row somebody other than
  the entry's implementations stated.

It writes ``derivation: adopted``, the same word the first route writes,
because the reason is the same signed entry; ``source_flow_uuid`` names the
donor's flow, so a reader asking where 133.39 on the zinc ion came from is sent
to zinc's flow in the same compartment.  A decline publishes nothing and is
counted.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping
from dataclasses import replace
from typing import Any

import structlog

from brightway_flows.lcia.adoptions import FactorAdoption, NumberFrom
from brightway_flows.lcia.adoptions import Verdict as AdoptionVerdict
from brightway_flows.lcia.consensus import Derivation

logger = structlog.get_logger(__name__)

#: What an adopted factor's `derivation` says.
ADOPTED = str(Derivation.ADOPTED)

#: Derivations a donor row may carry: somebody's statement for the donor's flow,
#: or a curated correction of one.  Never `carried` and never `adopted`, so no
#: number reaches a recipient by a chain of two crossings.
DONOR_DERIVATIONS = frozenset(
    str(derivation)
    for derivation in Derivation
    if derivation not in (Derivation.CARRIED, Derivation.ADOPTED)
)


def adopt_donor_numbers(
    published: list[Any],
    *,
    adoptions: Mapping[str, FactorAdoption],
    slug_of: Any,
    flows: Mapping[str, Mapping[str, Any]],
    stated: Mapping[Any, Mapping[tuple[str, str, str], Any]],
) -> tuple[list[Any], dict[str, int]]:
    """*published*, plus the donor's number on every signed recipient flow.

    *published* is the consensus implementation's factors as `derive()`, the
    moves and the printings left them; *adoptions* is the method's adoptions
    file, of which only the ``number_from: donor`` entries are read here;
    *slug_of* reads a row's category slug; *flows* is
    :func:`~brightway_flows.lcia.sources.flow_descriptions`; *stated* is
    every **deciding** implementation's factors keyed on (flow, category slug,
    geography), which says both who stated the donor's row and whether the
    publisher ever characterised the recipient.

    The new rows are appended; nothing already published is touched.  The
    counts say what happened: ``adopted``, ``recipient_stated_by_a_publisher``,
    ``already_published``, ``unit_differs``, ``declined``.
    """
    counts: Counter[str] = Counter()
    entries = [
        adoption
        for adoption in adoptions.values()
        if adoption.number_from is NumberFrom.DONOR
    ]
    if not entries:
        return published, dict(counts)

    #: Which implementations state each (flow, slug, geography), by name.
    speakers: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    substances_spoken_for: set[str] = set()
    for implementation, factors in stated.items():
        for key in factors:
            speakers[(str(key[0]), str(key[1]), str(key[2] or ""))].add(implementation.name)
            substances_spoken_for.add(str(flows.get(str(key[0]), {}).get("flow_object_id") or ""))

    #: substance → context IRI → live flows there.
    live: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for uuid, flow in flows.items():
        if flow.get("deprecated"):
            continue
        substance = str(flow.get("flow_object_id") or "")
        context = str(flow.get("context_iri") or "")
        if substance and context:
            live[substance][context].append(str(uuid))

    #: (substance, context IRI, slug, geography) → the published row.
    filled: dict[tuple[str, str, str, str], Any] = {}
    for row in published:
        flow = flows.get(row.elementary_flow_uuid)
        if flow is None or flow.get("deprecated"):
            continue
        key = (
            str(flow.get("flow_object_id") or ""),
            str(flow.get("context_iri") or ""),
            slug_of(row),
            row.factor.geography or "",
        )
        filled.setdefault(key, row)

    adopted: list[Any] = []
    for adoption in entries:
        if adoption.verdict is AdoptionVerdict.DECLINE:
            counts["declined"] += 1
            continue
        recipient = adoption.flow_object_id
        donor = adoption.donor.flow_object_id if adoption.donor else ""
        if recipient in substances_spoken_for:
            counts["recipient_stated_by_a_publisher"] += 1
            continue
        for (substance, context, slug, geography), source in list(filled.items()):
            if substance != donor or source.derivation not in DONOR_DERIVATIONS:
                continue
            speaking = speakers.get((source.elementary_flow_uuid, slug, geography), set())
            if not adoption.takes_donor_number(category_slug=slug, speaking=speaking):
                continue
            if (recipient, context, slug, geography) in filled:
                counts["already_published"] += 1
                continue
            donor_unit = str(flows[source.elementary_flow_uuid].get("unit") or "")
            for uuid in live.get(recipient, {}).get(context, ()):
                if str(flows[uuid].get("unit") or "") != donor_unit:
                    counts["unit_differs"] += 1
                    continue
                new = replace(
                    source,
                    elementary_flow_uuid=uuid,
                    derivation=ADOPTED,
                    # The donor's flow, so a reader can find the number's owner;
                    # the entry that signed for it is keyed on the recipient.
                    # `also_stated` was said about the donor, not here.
                    source_flow_uuid=source.elementary_flow_uuid,
                    also_stated=None,
                )
                adopted.append(new)
                filled.setdefault((recipient, context, slug, geography), new)
                counts["adopted"] += 1
                counts[f"adopted_{adoption.relationship}"] += 1
    if adopted:
        logger.info(
            "adopted_donor_numbers",
            factors=len(adopted),
            entries=len(entries),
            refused_recipients=counts.get("recipient_stated_by_a_publisher", 0),
        )
    return published + adopted, dict(counts)
