# What do we do when the model underneath says something else?

*Part of [How a factor is decided](index.md). This is the check that runs
before two voices are compared, because it is the one case where their agreeing
proves nothing.*

Biphenyl is an ordinary industrial chemical: a solvent carrier, a dye
intermediate, a preservative on citrus crates. EF 3.1 gives it 0.19957 CTUh per
kilogram for non-cancer human toxicity from urban air. That number puts it
**third** of the 3,380 substances EF characterises in that compartment, above
almost every pesticide in the list, and the ecoinvent Centre's implementation
states exactly the same number — because both are transcribing the same file.

EF 3.1's toxicity categories are derived from USEtox 2.1, and USEtox's own
number for biphenyl is about 1,400,000 times smaller
([#107](https://github.com/brightway-labs/brightway-flows/issues/107)).
Something went wrong between the model and the method, and two teams copying the
method faithfully copied the fault.

## Agreement between two copies is not evidence about the original

The flowchart's second question exists for this. Where the model a method is
derived from states something more than a hundredfold away from the method, for
a substance, in **every** compartment where both can be compared, the consensus
implementation publishes nothing for that substance and category — even where
the two transcriptions agree, and even where only one of them speaks. Asking
"which of these two readings is right?" would be asking the smaller question
first: a curator who settles it has published a number the model says is wrong
by five orders of magnitude.

The hundredfold line is deliberately crude. EF's toxicity factors are not
USEtox's factors — the JRC adjusts, aggregates and re-scopes them, and
differences of two- or ten-fold between the two are ordinary and are not a
question. A hundredfold in every compartment is not an adjustment.

## What is compared, and what is not

USEtox states one quantity per substance and compartment, and EF's six toxicity
categories are three pairs of an organic and an inorganic half plus their sums.
Only the categories whose quantity is the same one USEtox states are compared:
non-cancer human toxicity and its organics half. The rest — cancer, freshwater
ecotoxicity — are recorded in the evidence file and asked nothing about, because
a ratio between two different quantities is a fact about the two models rather
than about the substance.

On the build of 1 September 2026, run `20260901T0451332605450000`: 38 rows of
evidence, 34 of them not comparable for that reason, and **8 questions over 4
substances** — biphenyl, o‑phenylphenol, benfluralin and the 2,4/2,6‑toluene
diisocyanate mixture — holding 110 factors unpublished. None has been ruled.

## What a ruling can and cannot do here

A `contradicted-factor` question takes the same two verdicts as any other.
`publish` names the implementation whose number this list takes **in spite of**
the model — a curator who has read the JRC's report and decided the adjustment
was deliberate says so, and the factor comes back as `ruled` with the reasoning.
`decline` withholds it on the record.

What no verdict can do is publish USEtox's number. USEtox is not an
implementation of EF 3.1; it is what EF 3.1 says it is derived from, and a
factor of the consensus implementation must be a number one of the method's own
implementations stated.

## This is per method

The evidence file names the method it is about. Stepwise 2006 has no
contradiction model on file, and so no `contradicted-factor` questions; a
second method built on USEtox would need its own evidence rows rather than
inheriting EF's, because which categories are comparable is a fact about that
method's categories.

## Where it is written down

- `data/lcia-underlying-model-factors.json` — USEtox 2.1's numbers for the
  substances checked, keyed on registry number, with the divisor each was read
  with.
- the `contradicted-factor` queue — one row per substance and category, with
  what each implementation stated and the model's number and ratio.
- `data/lcia-factor-rulings.json` — where a curator answers one.
