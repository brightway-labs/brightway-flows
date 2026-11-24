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
| **transcription** | the ecoinvent Centre's EF 3.1, from its 3.12 release and again from its 3.13 one; GreenDelta's EF 3.1 | somebody else's rendering of the same method, against their own flow list |
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

## Two releases, one voice

The ecoinvent Centre's EF 3.1 is read twice, from its 3.12 release and from its
3.13 one ([#459](https://github.com/brightway-labs/brightway-flows/issues/459)),
and both decide. Two releases are two statements. Where a number changed
between them — α‑endosulfan's freshwater ecotoxicity went from endosulfan's
11,499 to the isomer's own 42,351 — a curator should look at the change rather
than have the newer release settle it by being newer.

They are still one publisher, and the method file says so: both rows carry
`publisher: ecoinvent Centre`. Agreement needs two publishers. Where the JRC is
silent and the two releases state the same number, that is the ecoinvent Centre
speaking alone, and it is a proposal, as any one transcription's number would be
([page 4](one-voice.md)). Where the JRC speaks and one release agrees with it
while the other does not, that is a disagreement between publishers, and it is
contested.

## Being evidence and being published are two things too

A third flag, `open`, says whether an implementation's numbers may leave the
build at all. The 3.13 release is closed. Its workbook sits behind ecoinvent's
login, ecoinvent has not published a 3.13 file, and the workbook's terms let it
inform this list's numbers but not be republished. So it decides, and nothing of
its own is written anywhere: none of its categories, factors, differences or
findings is in the database or either factor file. A factor this list publishes
because the JRC and 3.13 agree shows the JRC's number beside it, never 3.13's.
When ecoinvent publishes a 3.13 file, the release will be read from that file
and opened.

The 3.12 release is open, because it is read from the file ecoinvent publishes
at [github.com/ecoinvent/lcia](https://github.com/ecoinvent/lcia),
`EF v3.1_mapped_3.12.csv`. That file states the 3.12 workbook's 27,415 EF v3.1
factors at the same numbers and 3,212 cells of `0.0` where the workbook has no
row, which are dropped on the way in. Anyone can regenerate the implementation
with `fetch-lcia ecoinvent-3.12`, and its terms are the publisher's, CC BY-NC
4.0, not this list's ODbL: the implementation's row states the licence, and
every category of `ecoinvent Centre (3.12)` carries it as `meta.licence` so a
reader of the published rows sees it where the numbers are.

Each release is its own implementation, and the name says which. The 3.12
release keeps the identifier segment `ecoinvent-centre`: release 1.1.0
published its 25 categories under it, a category's identifier is a hash of
that segment, and a method linked to those identifiers keeps working. Every
later release carries its version in the segment and in the name,
`ecoinvent-centre-3-13` and `ecoinvent Centre (3.13)`, so a reader holding a
factor row can tell which release stated it without opening this page.

So for EF 3.1 the flowchart's first question is asked of two voices, the JRC's
and the ecoinvent Centre's, the second speaking through two releases; for
Stepwise 2006, of one.

Figures from the six-list build of `1e67f3c` on 23 November 2026 (run `20261123T2334105411510000`). The 3.13 release's count is what
was read and kept back rather than published:

| implementation | role | decides | factors | flows reached |
|---|---|---:|---:|---:|
| European Commission — JRC | reference | yes | 318,766 | 88,903 |
| ecoinvent Centre (3.12) | transcription | yes | 27,346 | 7,939 |
| ecoinvent Centre (3.13) | transcription | yes, not published | 27,342 | 7,965 |
| GreenDelta | transcription | **no** | 25,261 | 1,510 |
| brightway-flows | consensus | no | 327,173 | — |
| 2.-0 LCA consultants (Stepwise 2006) | reference | yes | 9,623 | 6,007 |
| brightway-flows (Stepwise 2006) | consensus | no | 18,947 | — |

## Where a voice's numbers come from

How an implementation's factors reach a consensus flow is also on its row, and
it is one of three routes:

- **published flows** — the implementation's own list is the base list, so its
  factors are already on consensus flows. The JRC's.
- **a source list** — the factors name somebody else's flows, and the merge says
  which consensus flow each became. The ecoinvent Centre's workbook and its
  public mapped file both name ecoinvent flows, the workbook by name and
  compartment and the file by UUID; GreenDelta's package names the ecoinvent identifiers it was
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
flowchart. EF 3.1 with five implementations and Stepwise 2006 with one run
through the same questions in the same order — and the convention that fills a
blank ([page 5](blanks.md)) is written once, about our contexts, for both.

## Where it is written down

- `data/lcia-impact-categories.json` and `data/stepwise-2006-impact-categories.json`
  — the `implementations` block of each, with `role`, `decides`, `open` and
  `factors.from` on every row, and `publisher` where two rows are one
  publisher's releases.
- `lcia_impact_categories.implemented_by` — which implementation a published
  category belongs to; every factor joins to it.
- `/factors` in the review application — the categories, and how much each
  implementation fills.
