# What do we do when no existing flow fits the row?

*Part of [How a flow is decided](index.md), and the second half of bringing in
another list. [The first half](merging.md) found the substance; this page is
about which of that substance's flows the row is really about — and what
happens when none of them is.*

A substance is published once. It occurs many times: in air and in water, at
ground level and at stack height, in kilograms and in cubic metres. Those
occurrences are the elementary flows, and a source row names one of them by its
compartment and its unit.

Figures are from the same build as the previous page: 25 August 2026, run
`20260825T1354430622920000`, revision `1c1385b`. Of the 15,609 rows the
algorithm placed, 13,790 were settled by the row's compartment alone, 1,756
ended in a new flow being created, and **63 were decided by scoring** — which
is worth knowing before reading the scoring rules below, because they are the
part of this that almost never has to run.

## A row is never crossed into another medium

Before anything is compared, every flow of the substance in a different
*dimension* or a different *medium* from the row is dropped. An emission to
water is never answered by a flow in air, however well the rest of it matches.

ecoinvent's `Benzoylprop-ethyl` in forestry soil is a plain example: the
substance has thirteen flows, ten of them are in air or elsewhere, and only
three survive to be considered at all.

## If the row's compartment is one this list holds, the row goes there

13,790 rows — 88% of everything the algorithm placed — are decided by this one
sentence. The row named a compartment, exactly one flow of the substance is in
it, and there is nothing to weigh.

The short-circuit declines when **two** flows share that compartment, because
then the compartment has not identified anything. That is not hypothetical: EF
3.1 holds water vapour in rural medium-stack air twice, once in kilograms and
once in cubic metres.

## Otherwise the candidates are scored

Four terms, and their relative sizes are the argument:

| Term | Worth |
|---|---:|
| the row's unit and the flow's unit are the same | **2** |
| each word the two compartments share | +1 |
| each word the flow's compartment has that the row did not say | −1 |
| the flow's compartment is exactly the one the row named | +1 |

**The unit is worth more than the compartment**, and the water vapour case is
why. ecoinvent reports `Water` to rural medium-stack air in cubic metres. Both
EF flows are in exactly that compartment, so the compartment term is a tie at
+1 and cannot separate them; the unit does, and the cubic-metre flow wins with a
score of 7 — two for the unit, four shared words, no words unaccounted for, and
one for the compartment being exactly right.

The word counting is the reason the compartment term exists at all. Counting
shared words measures how *deep* two compartments agree, not whether they are
the same one: `Air / Unknown` and `Air / Long-term` and `Air / Aircraft cruise
height` all share two words with a row that said `Air` and differ by one. Only
the compartment's identity can say which of those *is* the place the row named.

## Coarsening is honest; contradicting is not

Publishing a release to a lake as a release to water, unspecified, loses detail
and says nothing false. It is the right answer when the list has no lake.

Publishing it as a release to **groundwater** is a different act. Groundwater is
not a vaguer way of saying lake, and the score cannot tell the two apart, since
all it counts is shared words — for BAFU's lead-210, the groundwater flow
outscored every honest alternative on the strength of "an environmental release
to water" plus a matching unit
([#85](https://github.com/brightway-labs/brightway-flows/issues/85)).

So a winner that contradicts the row is thrown out and the choice is made again
among the candidates that do not. This fired on 89 rows.

## A row's answer must not depend on when it was asked

Coarsening onto the nearest compartment that exists has a second problem: the
set of flows to be nearest to *grows as the merge runs*.

ecoinvent's `Aerosols, radioactive, unspecified` is the demonstration. The
identical row, in `air / urban air close to ground` in both releases, landed on
`Air → Unknown` during the 3.12 pass, where that flow won 3 to 2. By the 3.8
pass a third flow of the substance existed, two candidates tied at 3, and the
tie put the row in its own compartment. One intervention, two consensus flows,
and the only difference was the order
([#112](https://github.com/brightway-labs/brightway-flows/issues/112)).

So a row whose compartment this list holds gets a flow in **that** compartment,
whenever no candidate is already there. Twelve rows on this build. A row whose
compartment the list does not hold is left alone, because there is no
compartment to create it in.

## Four situations create a flow, and one deliberately does not

1,756 rows ended with a new elementary flow rather than an existing one:

| Why | Rows |
|---|---:|
| two candidates tied on the top score | 1,602 |
| every candidate that fitted contradicted the row's compartment | 89 |
| the substance had no flow in that medium at all | 53 |
| nothing was in the compartment the row named | 12 |

`Benzoylprop-ethyl` is the first row of that table. Its substance is in
agricultural ground, non-agricultural ground and unspecified ground; the row is
in forestry soil, which resolves to silvicultural ground; two of the three tie,
and the row gets a silvicultural flow of its own.

What does **not** create a flow is the case one layer up — a row whose
*substance* could be several. Those two look alike and are opposites. Several
candidates mean the row matched too much, and creating something would be
choosing by another name. A row that matched too little has a gap in front of
it, and the gap is what gets filled.

## Where it is written down

`merge_outcomes.detail_json`, per row. It records the compartment the row named
and what it resolved to, how many flows of the substance there were, how many
survived the medium filter, and — for every candidate that was scored — its
score with each of the four terms separately. A vetoed winner is named too,
under `rejected_contradicting_context_iri`, so a report shows what the decision
chose between rather than what it first considered.

That is enough to re-run a matching decision offline, against a build that has
already happened, without rebuilding anything.
