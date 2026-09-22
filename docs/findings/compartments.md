# The compartment names two situations at once

*Part of [What we have found](index.md), the class where the place half of a flow holds two situations, and a characterisation factor can only have been computed for one of them.*

## "Non-urban air or from high stacks"

Every list has this compartment, under three spellings — EF 3.1's
`Emissions to non-urban air or from high stacks`, ecoinvent's
`air / non-urban air or from high stacks`, BAFU's `emissions to air / low. pop.`.
It holds **7,308 EF flows, 1,237 ecoinvent 3.12 flows, 390 ecoinvent 3.8 flows and
256 BAFU flows**, which makes it one of the most used compartments in life cycle
inventory.

The name is a disjunction: *a release in the countryside*, **or** *a release from a
tall stack anywhere*. Those are different situations with different fates — ammonia
leaving a dairy barn at head height in open country, and a power-station plume
leaving a 150-metre chimney over a city. No single context can hold both, and
nothing in a flow says which one a given number was.

**EF's own factors settle it, and they pick neither reading.** EF also ships a
*narrow* set of air compartments — `non-urban air close to ground`,
`non-urban air low stack`, `non-urban air high stack`,
`non-urban air very high stack` — with 16 to 18 flows each, against 7,308 in the
ambiguous one. In all 40 (flow, method) pairs where the ambiguous compartment and
one of the narrow ones are both characterised, EF gives the ambiguous compartment
**exactly the factor it gives `Emissions to non-urban air high stack`**. For
particles (PM2.5):

| compartment | factor |
|---|---:|
| non-urban air close to ground | 1.13763e-05 |
| **non-urban air or from high stacks** | **3.01757e-06** |
| non-urban air high stack | 3.01757e-06 |
| non-urban air very high stack | 1.62949e-06 |

So the numbers attached to this compartment were computed for a stack between 15
and 150 metres, in the countryside — not for the barn, and not for the very tall
chimney.

**The decision.** The compartment is mapped to rural air, medium stack under 150
metres: it keeps the rural qualifier the name does assert, and takes the stack
height EF's numbers assert rather than the one the name suggests. **What is given
up, stated plainly:** a release that really did leave a chimney above 150 metres is
published as a sub-150-metre one, which EF's own factors say is the smaller of the
two errors. The decision is made once for all three lists, because moving one
alone would split them apart
([#79](https://github.com/brightway-labs/brightway-flows/issues/79)).

## A compartment is supposed to be one situation

That compartment is the most used of the ones that do this, and it is not the
only one.

A flow is a substance *and* a place. The place is supposed to be one situation, so
that a characterisation factor computed for it means something. Several
compartments in wide use name two.

## Occupation and transformation in one compartment

ecoinvent files land occupation and land transformation in a single compartment,
`natural resource / land` — **182 flows, 60 occupation and 122 transformation**,
identically in 3.8 and 3.12.

These are not a coarse and a fine version of one thing. Occupation is land held in
a use for a time, measured in m²·a; transformation is land changing from one state
to another, measured in m². They are siblings, and a compartment rule cannot be
right about both: filing everything in that compartment as occupation put all 122
transformation flows in the wrong place. The only thing that distinguishes them is
the flow's own name, which begins `Occupation, ` or `Transformation, `
([#52](https://github.com/brightway-labs/brightway-flows/issues/52)).
