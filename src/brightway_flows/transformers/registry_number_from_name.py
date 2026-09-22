"""Give a flow the registry number its own source list gives that name.

BAFU ships four rows called `Silver-110`. Two of them carry 14391-76-5 and land
on the silver-110 the list already holds; two carry no number at all, so the
matcher had only a name, and they became a second substance also called
`Silver-110` -- one vendor name, one build, two substances, and only one of them
carrying any characterisation (#26). The same shape produces a duplicate
`Ethane, Pentafluoro-, HFC-125` for the one BAFU row of five that omits
354-33-6, and duplicates of trifluoromethane, of Halon 1301 and of CFC-114.

The number is not missing from the list. It is missing from *this row* of it,
and the vendor has written it down on another row under the same name. Nothing
else in the pipeline reads across a source list's own rows to notice that: the
merge decides one row at a time, and a row with no number falls through to the
name lookup, which is the weakest evidence there is (#71).

## Detection strategy

A flow is a candidate when it has **no registry number of its own** and has a
preferred label. It takes the number when **another flow from the same source,
with the same name, carries exactly one, and that source gives that number to no
other name** -- the vendor has then said what the substance is, on a different
row, in its own words, and has used the name and the number to mean each other.

`source` is used as an opaque key for "which list did this row come from", never
parsed. Rows of a *different* list are not evidence: two lists using one word
for different substances is the ordinary case, and reconciling them is the
merge's job, done downstream with the whole list in view and a curator's
decisions to hand.

Nothing is written when:

- the flow already carries a number. A name is weaker evidence than a registry
  number and never overrules one;
- the source list gives the name several numbers, **or gives that number to
  several names**. Both halves say the same thing -- the list is not using this
  pairing as an identity -- and both have to refuse. BAFU gives 7440-61-1,
  uranium the element, to fourteen of its fifteen `Uranium-238` rows and to its
  `Uranium` rows as well; the fifteenth carries nothing and was matching the
  uranium-238 isotope on its name, correctly. Taking BAFU's number would have
  made that row consistent with its siblings by moving it off the isotope onto
  the element, turning a vendor's data defect from fourteen rows into fifteen.
  The check is per list: ecoinvent giving 14391-76-5 to `Silver-110m` while
  BAFU gives it to `Silver-110` is two lists spelling one substance two ways,
  which is the merge's ordinary work.

Only the **preferred label** is looked up, never the alternative labels. By the
time the chain has run, `chebi_altlabels` and `consensus_match` have attached
every synonym they could find, and a rule reading those would be asking whether
*some name this substance is also known by* means a number. That is how a trade
name reaches the wrong chemical, and this project has the case on file:
`_narrow_label_candidates` in the merge exists because "Granite" reaches
Penoxsulam and "Propylene Carbonate" reaches Talc.

## What this deliberately does not do

An earlier version also consulted ChEBI and PubChem -- given a name, the number
those two publish it under -- which reached 21 more substances, including
`Chrysotile`, `Cyclaniliprole` and `N-octane`, none of which any other part of
the build can identify. A full build showed why it cannot be done that way.
Their name indexes contain trade names, so `Granite` resolved to 219714-96-2 and
BAFU's granite matched **Penoxsulam** -- the very pairing
`_narrow_label_candidates` was written to prevent, arrived at by a road that
rule does not watch. `Air` took 25635-88-5 the same way. Nuclides failed
differently and just as badly: those databases index `krypton-85m` under
13983-27-2, which is krypton-85, and `uranium-238` under 7440-61-1, which is
uranium the element, while this list uses the specialised numbers ecoinvent
ships -- so 13 rows that had been matching correctly on their own names were
split away from the substance the rest of their rows reach.

Two wrong matches and thirteen split nuclides against twenty-one substances
enriched is not a trade a rule can make silently. Restricting the lookup to the
primary name of a ChEBI or PubChem record, rather than to any synonym, is the
shape that might work, and it needs a measurement of its own.
"""

from __future__ import annotations

from collections import defaultdict

import structlog

from brightway_flows.domain.common import Provenance
from brightway_flows.domain.flow import Flow
from brightway_flows.domain.labels import flow_label_value
from brightway_flows.pipeline import (
    Change,
    Transformer,
    normalize,
    writable_flows,
)

logger = structlog.get_logger(__name__)

#: How the number reached the flow, recorded on the change and in the provenance.
FROM_THE_SOURCE_LIST = "another row of this source list gives this name"


class RegistryNumberFromNameTransformer(Transformer):
    """Fill in a missing registry number from what the row's own list says."""

    name = "registry_number_from_name"
    # The question is about the set: which numbers do the *other* rows of this
    # source list give this name.  No flow can be asked it on its own.
    answers_per_flow = False

    def transform(self, flows: list[Flow]) -> list[Change]:
        # Phase 1, over every flow: which numbers each source list gives each
        # name.
        numbers_by_name: dict[tuple[str, str], set[str]] = defaultdict(set)
        # And the same pairs read the other way, which is the second half of
        # the identity test below.
        names_by_number: dict[tuple[str, str], set[str]] = defaultdict(set)
        for flow in flows:
            label = normalize(flow_label_value(flow))
            if not label:
                continue
            source = str(flow.source or "")
            for number in flow.cas_numbers or []:
                if isinstance(number, str) and number.strip():
                    numbers_by_name[(source, label)].add(number.strip())
                    names_by_number[(source, number.strip())].add(label)

        # Phase 2, over the flows a change can still reach.
        changes: list[Change] = []
        filled = 0
        refused = 0
        for flow in writable_flows(flows):
            if any(
                isinstance(number, str) and number.strip()
                for number in flow.cas_numbers or []
            ):
                continue
            label = normalize(flow_label_value(flow))
            if not label:
                continue

            own = numbers_by_name.get((str(flow.source or ""), label), set())
            if len(own) > 1:
                refused += 1
                continue
            if len(own) != 1:
                continue
            number = next(iter(own))
            if len(names_by_number.get((str(flow.source or ""), number), set())) > 1:
                refused += 1
                continue
            filled += 1

            changes.append(Change(
                flow.uuid,
                "cas_numbers",
                [number],
                comment=(
                    f"Registry number from the flow's own name: {FROM_THE_SOURCE_LIST}"
                ),
            ))
            existing = flow.cas_number_sources
            sources = dict(existing) if isinstance(existing, dict) else {}
            sources[number] = Provenance(
                was_generated_by=self.name,
                was_attributed_to="brightway-flows",
                had_primary_source=[str(flow.source or "")],
                was_derived_from=FROM_THE_SOURCE_LIST,
            ).to_dict()
            changes.append(Change(
                flow.uuid,
                "cas_number_sources",
                sources,
                comment="Attach provenance for the registry number its name gave it",
            ))

        logger.info(
            "registry_number_from_name",
            flow_count=len(flows),
            filled_in=filled,
            # A source list whose name and number do not identify each other,
            # in either direction.  A defect in the list rather than in this
            # step, and a number to watch: it going up means a vendor has
            # started spelling two substances one way, or numbering one
            # substance two ways.
            refused_the_list_disagrees=refused,
        )
        return changes
