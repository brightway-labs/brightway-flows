# Who states a number, and whose counts?

*Part of [How a factor is decided](index.md). The first question the flowchart
asks is whether any* deciding *implementation states a number — and this page
is what "deciding" means.*

A characterisation factor is a statement by somebody. EF 3.1's number for
copper in surface water is not a property of copper; it is what a team produced
by running a model against a flow list, and a second team running the same
model against a different flow list produced a second statement. This list
keeps every statement under the name of the team that made it, and it derives
one more of its own. Which statements the derivation may read is the first
decision, and it is made once per method, in the method's own file.

Figures are from the build of 1 September 2026, run `20260901T0451332605450000`.

## Three roles

| role | who | what it means to the method |
|---|---|---|
| **reference** | the JRC for EF 3.1; 2.-0 LCA consultants for Stepwise 2006 | the method's own publisher. Exactly one per method. Always decides |
| **transcription** | the ecoinvent Centre's EF 3.1; GreenDelta's EF 3.1 | somebody else's rendering of the same method, against their own flow list |
| **consensus** | this list | ours, derived from the deciding implementations. Never decides, because it is the thing being decided |

The role is what the pipeline branches on — never the name. A factor only the
reference states is `sole` and needs no curator; a factor only a transcription
states is a question. That asymmetry is real and worth stating plainly: adopting
the method's own number for a flow is not a decision, and adopting somebody
else's number for a flow the method's publisher never characterised is.

It is also worth stating what `sole` does **not** mean. It says who spoke, not
who is right. Stepwise 2006's consensus implementation is 9,622 factors and every
one of them is `sole`, because one publisher renders that method and nobody
checks it; the consensus implementation of a single-publisher method is that
publisher's transcription under our name, and the flowchart makes no claim
beyond that.

## Being published and being evidence are two things

Every implementation in a method's file is transcribed, published, and compared
in the difference report. Only the ones marked `decides: true` are handed to the
derivation, where a number of theirs can become one of ours or reach a curator's
queue.

GreenDelta's EF 3.1 is the case that made the distinction necessary
([#157](https://github.com/brightway-labs/brightway-flows/issues/157)).
It arrives inside BAFU's openLCA distribution as *EF 3.1 Method (adapted)*: a
hand transcription of the JRC's files onto ecoinvent's flow identifiers, which
nobody can re-run. It is published — 25,258 factors over 1,507 flows — and it is
shown on every flow's page beside the other two, and a number of GreenDelta's is
never evidence for a number of ours, never a candidate in a queue, and changes no
factor this list states. What it is for is putting a third reading of EF 3.1 in
the difference report, where a disagreement is a question somebody can look at.

So for EF 3.1 the flowchart's first question is asked of two voices, the JRC's
and the ecoinvent Centre's; for Stepwise 2006, of one.

| implementation | role | decides | factors | flows reached |
|---|---|---|---:|---:|
| European Commission — JRC | reference | yes | 318,774 | 88,907 |
| ecoinvent Centre | transcription | yes | 27,290 | 7,925 |
| GreenDelta | transcription | **no** | 25,258 | 1,507 |
| brightway-flows | consensus | no | 323,874 | — |
| 2.-0 LCA consultants (Stepwise 2006) | reference | yes | 9,622 | 6,006 |
| brightway-flows (Stepwise 2006) | consensus | no | 9,622 | — |

## Where a voice's numbers come from

How an implementation's factors reach a consensus flow is also on its row, and
it is one of three routes:

- **published flows** — the implementation's own list is the base list, so its
  factors are already on consensus flows. The JRC's.
- **a source list** — the factors name somebody else's flows, and the merge says
  which consensus flow each became. The ecoinvent Centre's workbook names
  ecoinvent flows; GreenDelta's package names the ecoinvent identifiers it was
  built against, and walks whichever release has them; Stepwise's SimaPro export
  names its own rows.
- **derived** — ours, from the rest.

A factor that names a flow the merge did not place reaches nothing, and is
reported rather than guessed onto a neighbour: 222 of GreenDelta's rows and 11
of Stepwise's are in that state on this build, each a `flow-not-reached`
finding.

## The same rules for every method

Two methods share the flow list and nothing else. Stepwise 2006 also has a
category called *Acidification*, counted in a different unit from a different
model, and it is not EF's; no category, no ruling, no approval and no queue
crosses from one method to the other, and a method's contradiction model
([next page](model.md)) is that method's alone. What the two share is the
flowchart. EF 3.1 with four implementations and Stepwise 2006 with one run
through the same questions in the same order — and the convention that fills a
blank ([page 5](blanks.md)) is written once, about our contexts, for both.

## Where it is written down

- `data/lcia-impact-categories.json` and `data/stepwise-2006-impact-categories.json`
  — the `implementations` block of each, with `role`, `decides` and `factors.from`
  on every row.
- `lcia_impact_categories.implemented_by` — which implementation a published
  category belongs to; every factor joins to it.
- `/factors` in the review application — the categories, and how much each
  implementation fills.
