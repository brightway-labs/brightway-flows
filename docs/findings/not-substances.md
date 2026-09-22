# Flows that are not substances at all

*Part of [What we have found](index.md), the class where the row has no substance identity to get wrong: a laboratory measurement, a burden that is not matter, a place in a state.*

## Measurements over many molecules

Fourteen kinds of flow in these lists are laboratory quantities rather than
substances — **180 flows in EF 3.1, 40 in ecoinvent 3.12, 45 in 3.8 and 41 in
BAFU**. Chemical oxygen demand is the mass of oxygen a chemical
oxidant consumes in breaking down everything oxidisable in a sample — **the oxygen
is not in the discharge at all**; it is what the laboratory's reagent gave up.
Biochemical oxygen demand is the same quantity measured by letting bacteria do the
oxidising over five days, and BOD5 and BOD20 are different numbers, so the five
days are part of the definition. Total organic carbon is one element counted across
an unstated set of molecules. `Nitrogen, organic bound` — [which all three lists
give dinitrogen's registry number](registry-numbers.md) —
is the same kind of thing.

## Rows with no substance identity to get wrong

Chemical oxygen demand is the plainest member of a class that runs through every
list here. These rows are not errors in a substance's identity; they are
flows that have no substance identity to get wrong, sitting in a list built to hold
substances. Read as chemistry, they produce nonsense — and every automated step
that enriches a flow from its registry number will try.

## Burdens that are not matter

BAFU carries six noise rows — aircraft, lorry,
passenger car, freight and passenger rail — counted per person-kilometre for
passengers and per tonne-kilometre for freight. What is counted is not how much
noise there is but how much transport it accompanied. Noise has no formula, no
mass and no registry number, and no chemical ontology has a class for it
([#70](https://github.com/brightway-labs/brightway-flows/issues/70)).

## Land classes

ecoinvent ships 182 land flows, BAFU 152 and Stepwise 2006
41, named `Occupation, arable, conservation tillage` or `Transformation, from
forest, primary`. These are not substances but *places in a state*, measured in
m² and m²·a; they need fields a substance record has no room for — what the land
is, what it was, and what it became — which is why they are given their own kind
of record rather than a chemical one
([#66](https://github.com/brightway-labs/brightway-flows/issues/66)).

What the land **was** is the field the record still does not have. Thirteen of
Stepwise's 41 rows are about it: `Occupation, sealed, on grassland` is a paved
square metre that used to be grassland, and Stepwise charges 0.7 for it where
the same paving on arable land costs 0.2 — so the previous state is what the
number turns on, and every axis this project has describes the land as it is.
Those thirteen are published under Stepwise's own names, and listed as
unreadable in `tests/data/observed-land-classes.json` rather than left silent
([#174](https://github.com/brightway-labs/brightway-flows/issues/174)).
Whether the axes should gain a previous state is
[#176](https://github.com/brightway-labs/brightway-flows/issues/176).

## One quantity in two directions

Waste heat is shipped as an emission by every
list — EF 12 flows, ecoinvent 13, BAFU 14 — and BAFU *also* ships
`Energy, waste heat, air` as a **resource taken from the air**. The same physical
quantity is both a release and an intake depending on which row you read
([#75](https://github.com/brightway-labs/brightway-flows/issues/75)).

## The decision, in every case

These rows are kept and published, with a record
type that fits what they are, and they are kept *out* of the chemical enrichment
that would otherwise attach a structure, a formula and a set of trade names to a
laboratory procedure. The registry number is removed where a list supplied one,
because there is nothing to correct it to.
