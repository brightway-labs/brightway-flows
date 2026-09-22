# What happens when the evidence is not good enough?

*Part of [How a flow is decided](index.md). Declining to answer is one of the outcomes at every stage of it.*

The consensus matching step applies updates only under explicit confidence
rules — typically several independent sources agreeing. When they do not agree,
it does not guess. Instead the case goes into a queue in `review_queue`, and
`/queue/<name>` is where a human decides it:

| Situation | Queue |
|---|---|
| Common Chemistry disagrees with the flow's name for a CAS | `commonchem-cas-name-differences` |
| Common Chemistry gives a different CAS for the flow's name | `commonchem-name-cas` |
| A CAS resolves to several ChEBI records ambiguously | `cas-ambiguous` |
| No EC number can be recovered from the string at all | `ec-malformed` |
| CAS ↔ EC pairing contradicts the ECHA inventory | `ec-cross-check` |
| Consensus matching found no confident answer | `consensus-match` |
| A preferred-label rename is awaiting a ruling | `undecided-label-replacement` |
| A land-class substance has a flow published outside Land Use | `land-class-out-of-place` |
| Two live flows share a substance, a context and a unit, and a comment is all that separates them | `elementary-flow-collision` |
| A ChEBI record's formula diverges from the flow's | `formula_mismatches` table |
| An element has no flow object | `element_coverage` table |
| An ecoinvent flow matched no consensus flow object | `merge_outcomes` table |

Declining to act is a normal outcome, not a failure. See
[The review application](../operating/review-app.md) for how to work through
these queues.
