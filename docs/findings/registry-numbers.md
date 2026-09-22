# A registry number that is not this substance's

*Part of [What we have found](index.md), the class where the number on the flow is real, and belongs to something else.*

## Natural gas's number appears once in EF 3.1, on a flow that is not natural gas

EF 3.1 ships `Gas, mine, off-gas, process, coal mining` carrying
[8006-14-2](https://commonchemistry.cas.org/detail?cas_rn=8006-14-2), which is
natural gas's registry number. Gas that seeps out of a coal seam while the coal is
being mined is not natural gas — different impurities, different heating value —
and **EF says so itself**, on the neighbouring `Pit Methane` flow: *"Pit methane is
a different substance than natural gas (impurities, heating value etc.)"*.

EF keeps the two substances apart three ways — by name, by category (one is a
*material* resource from ground, the other an *energy* resource) and by unit (m³
against MJ). The registry number is the single thing they share, and it is the only
one of the four that decides identity downstream.

Meanwhile **EF gives natural gas itself no identifier at all.** 8006-14-2 appears
exactly once in the whole of EF 3.1, and it is on the wrong flow.

What that cost was measured, and it was not nothing: enrichment looked the number
up and wrote natural gas's names onto coal-mine gas, so `Natural gas`,
`Gas, natural` and `Sweet natural gas` named two substances at once — and BAFU's
two natural gas rows could then be placed on neither. ecoinvent shipped the same
error and has already fixed it: 3.8 and 3.9.1 carry 8006-14-2 on this flow, and
3.10.1 onwards leave it off, under the same identifier
([#80](https://github.com/brightway-labs/brightway-flows/issues/80)).

## What the number can belong to instead

This is the plainest of the identity classes: the flow carries a registry
number, and the number belongs to something else — a superseded entry for the same
substance, or a neighbouring substance entirely — or it carries none at all and the
substance cannot be reached.

## The same class, four more shapes

**Superseded.** EF files borax under 12447-40-4. That number is genuinely borax's,
but it has been superseded, and the number in current use is 1303-96-4 — which is
how ChEBI files the mineral, twice, and what ecoinvent carries. Nobody disagrees
about the substance; the two halves of the list simply never meet. Mecoprop is the
same shape, EF holding 7085-19-0 where the rest of the world uses 93-65-2
([#110](https://github.com/brightway-labs/brightway-flows/issues/110)).

**Borrowed from a neighbour.** EF puts borax's number on six `Borate` rows as well
as on its one `borax` row. Borate is the ion; borax is one particular salt of
it — sodium tetraborate decahydrate, **about a fifth boron by mass** — so the two
are not interchangeable in an inventory, and sharing a number fused them into one
substance carrying borax's structure and trade names. ecoinvent tells them apart:
its `Borate` rows carry 11129-12-7, the ion's own number.

**Borrowed again, in the other list.** ecoinvent gives `Alpha-lindane`,
`Beta-lindane` and `Delta-lindane` all the *gamma* isomer's number, 58-89-9 — 21
flows across seven compartments each. The isomers have their own numbers
(319-84-6, 319-85-7, 319-86-8) and different toxicity.

**A number for something that is not a compound.** All three lists put dinitrogen's
number, 7727-37-9, on `Nitrogen, organic bound` — EF on five rows, ecoinvent on
five, BAFU on four. Organic-bound nitrogen is not a compound at all: it is the
nitrogen locked inside the organic matter of a discharge, reported as a mass of
nitrogen, and no registry number can name it because a number names one compound
and this is a measurement over many. The number is removed rather than corrected,
because there is nothing to correct it to
([#57](https://github.com/brightway-labs/brightway-flows/issues/57)).

**Absent.** Fifty of EF's part-numbered flows ship with no identifier of any kind,
as do EF's own natural gas rows and BAFU's `Anhydrite`. A flow with no number is
not wrong, but it is unreachable: nothing can look it up, and it will mint a
substance of its own beside the one it should have joined. ecoinvent 3.8's
`Fosetyl-aluminium` is what that costs. The row carries no number, 3.9.1 onwards
call the same uuid `Fosetyl-Al` and register it 39148-24-8 — EF 3.1's
`fosetyl-aluminum`, the fungicide sold as Aliette, which the JRC characterises
in that very compartment — and the retired British spelling reaches EF's flow
only as one of its synonyms, which is not enough to place a row against a
substance that states a registry number the row does not. So the emission minted
a substance of its own, and **every 3.8 inventory's application of the fungicide
scored zero** while 3.12's and BAFU's identical rows scored. One curated match
override answers it, guarded by the retired spelling so the releases that state
their own number keep matching on it
([#144](https://github.com/brightway-labs/brightway-flows/issues/144)).
