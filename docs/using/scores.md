# Scoring a dataset two ways

Take one ecoinvent dataset — `electricity production, wind, >3MW turbine,
onshore` in Sweden, one kilowatt-hour — and ask what it is worth under EF.
There are two ways to answer.

The first is the vendor's own: brightway, with ecoinvent's own elementary
flows and the factors ecoinvent ships in its LCIA implementation file. For
ecoinvent 3.8 that file carries EF v3.0, because that is the method 3.8
shipped with; for 3.12 it carries EF v3.1.

The second is this list's: the same inventory — the same flows, the same
amounts — but every ecoinvent flow first mapped onto its consensus flow, and
the factor applied being the one this list publishes under its own name.

For that wind activity the two answers agreed on the inventory exactly and
disagreed on three categories: water use 434 times too high, fossil resource
use 28 times too low, freshwater ecotoxicity 2.3 times too high. Finding out
why took a contribution analysis run by hand on each side, which is what named
the flows — four fossil fuels whose factor had been imported as 1.0, uranium
with no factor at all, and water counted twice, once as withdrawal less return
and once as vapour.

The score comparison does that for five hundred datasets at once, and then
ranks the flows by how much score they move.

## What is compared

The vendor's side is a file written by brightway — see
[running the exporter](../operating/running.md#scoring-a-releases-unit-processes-with-brightway).
It holds a seeded sample of a release's datasets; for each one its cumulative
inventory per unit of reference product, by the vendor's own flow identifiers;
the factors the vendor's tooling applied, once per category and flow; and the
scores. The list refuses a file whose scores are not exactly its inventory
times its factors, so the factors in the file are provably the ones the scores
used.

`compare-scores` then re-scores every dataset our way. A flow of the inventory
is looked up in the merge's record of where that vendor's rows went; if the
consensus flow it reached is measured in another unit, the conversion the merge
recorded is applied to the amount; and this list's own factor for that flow
under that category is multiplied in.

## Why two numbers differ

Because the inventory is the same on both sides, a difference for one dataset
under one category is the sum of differences for single flows, and each of
those is one of six things:

| Reason | What happened to the flow |
|---|---|
| agree | It mapped, both sides have a factor, and the two contributions agree within 2% |
| factor differs | Both sides have a factor and they do not agree |
| no consensus factor | It mapped, the vendor has a factor, this list does not |
| unmapped flow | The vendor's flow reached no consensus flow at all |
| unit crossing unconverted | It mapped onto a flow in another unit and the merge recorded no conversion |
| only consensus factor | This list has a factor and the vendor does not |

That list is closed, and it is the report. `Scores` in the review application
shows, per release, a row per category with how many datasets agree, how many
are within 2×, and the median of ours over theirs; behind each category the
vendor's flows ranked by how much of that category's total they move, with the
reason; and behind any dataset, every category both ways and every flow under
one of them.

## Reading a release scored with an earlier method

ecoinvent 3.8 is scored with EF v3.0, the method it ships. This list's factors
are EF 3.1, so part of every gap on that release is the revision between the
two rather than a defect of either side — biogenic climate change moved by a
fifth between 3.0 and 3.1, and the three `metals` toxicity categories 3.0
scored separately were folded into `inorganics` in 3.1, which is why those
three appear on the table as categories with no row of ours. A release scored
with the same method version on both sides, as 3.12 is, has no such excuse: on
it every gap is the flow mapping's or the factor's.

That makes the two releases read together. 3.8 says where the two sides differ;
3.12 says whether the difference is the method's revision or ours. A flow that
disagrees on 3.8 and agrees on 3.12 is the JRC changing its mind between
versions. A flow that disagrees on both is this list's to answer.

## What the 3.8 comparison says

Three categories on that release are worth reading in full, because between
them they show every shape a difference can take: a difference of vintage that
belongs to neither side's method, a mapping this list stands behind, a gap in
the method's own flow list, and a genuine revision.

### Non-renewable energy resources

501 datasets, 247 of them agreeing within 2%, 252 in the 2× band and two a
hundredfold out. Three flows account for every one of those gaps and no others.

| Flow | ecoinvent (EF v3.0) | This list | Share of the category |
|---|---|---|---|
| Oil, crude, in ground | 42.3 MJ/kg | 43.4 | 1.01% |
| Gas, natural, in ground | 34.5 MJ/m³ | 36.0 | 0.65% |
| Peat, horticulture | 9.76 MJ/kg | none | 0.02% |

A fourth, `Gas, mine, off-gas, process, coal mining`, was on that list until
[#161](https://github.com/brightway-labs/brightway-flows/issues/161) gave it
a factor; the same section explains why, and why it is not the same question as
peat.

The first two are not a difference of method at all, and it is worth being
precise about whose number is whose. The JRC's factor for a fossil energy
carrier is 1.0 MJ per MJ under EF v3.0 and EF 3.1 alike — EUR 29600 §4.10 states
it and the EF 3.1 data says the same — so the per-kilogram number is nobody's
characterisation factor. It is the implementer's heating value, and ecoinvent
revised theirs at database release 3.9 following Meili et al. (2021): crude oil
42.3 → 43.4 MJ/kg, natural gas 34.5 → 36 MJ/m³.

**The table above measures a build that predates
[#162](https://github.com/brightway-labs/brightway-flows/issues/162).** At
the time this list recorded one heating value per substance and applied it to
every release it merged (#141), and it was the newer one — so on 3.8 it
converted with 3.9-era values while ecoinvent had scored with the values 3.8
shipped, and the 2× band on 3.8 was entirely oil and gas chains, at +2.6% and
+4.3%. A conversion factor now carries the releases it was checked against, and
3.8 converts with 3.8's own numbers, so a rerun should put oil and gas in the
agreeing band on both releases. The table stays as measured until somebody
reruns the comparison and can state what it found.

Hard coal (18.01), brown coal (9.41) and uranium (560,000) were not revised, and
agreed bit for bit on both releases before the change as after it.

The other two — mine off-gas and horticultural peat — are flows the ecoinvent
Centre characterises and the JRC does not, and both numbers come from one rule
of ecoinvent's rather than from two judgements. Their LCIA implementation report (v3.12, §6.5.1) lists both flows in
Table 5 as non-renewable **fossil** energy carriers, gives their lower heating
values in Table 6 — 36 MJ/Sm³ for mine off-gas, the same as natural gas, and
9.76 MJ/kg for peat — and says lower heating values "are implemented in methods
assessing energy resources if no other CFs are given". So where EF is silent,
ecoinvent fills in the calorific value.

The JRC is silent for a reason that is about its flow list rather than about
either substance. EUR 29600 §4.10 states the rule as a rule about a bucket:
following van Oers et al. (2002), "a separate impact category for fossil fuels
is defined, based on their similar function as energy carriers. CFs for fossil
fuels are expressed as MJ/MJ, i.e. the CF is equal to 1 for all fossil
resources." The bucket is EF's `Non-renewable energy resources from ground`,
whose flows are all in megajoules, and the six characterised flows are exactly
its members. Neither of these two is in it: EF files mine off-gas as a
non-renewable **material** resource from ground, in standard cubic metres, and
horticultural peat as a **renewable material** resource from the biosphere, in
kilograms.

That silence means opposite things for the two, and both have now been answered
in opposite directions. Mine off-gas is coal-seam methane and a fossil resource
by any reading of the model; it falls between EF's two resource buckets — the
energy rule wants megajoules and it is in standard cubic metres, and
`Resource use, minerals and metals` prices crustal elements in kg Sb-eq and has
nothing to price a methane flow from — so EF lists it and characterises it
nowhere. That is a gap rather than a decision, and 36 MJ/Sm³ is the JRC's own
rule arithmetic: 1.0 MJ per MJ, times the flow's heating value. A `publish`
ruling adopts it
([#161](https://github.com/brightway-labs/brightway-flows/issues/161)).
Horticultural peat is 0.02% of the category and 98% of two datasets —
`market for peat` and `market for peat moss` are the two hundredfold outliers —
and it has been answered: EF ships a separate fuel peat, from the ground, in
megajoules, at 1.0, and this flow is the other one. A `decline` in
`data/lcia-factor-rulings.json` says so on the record
([#160](https://github.com/brightway-labs/brightway-flows/issues/160)). What
that costs is peat burned for electricity: ecoinvent ships one peat flow and
uses it for both, so Irish peat-fired power scores 0.91× theirs here, and the
answer to that is a fuel-peat row in the inventory rather than a fuel's factor
on a growing medium.

One number in this section is worth reading twice. Giving mine off-gas its
factor *lowered* how many 3.8 datasets agree within 2%, from 291 to 247, and
that is not a regression. The mine-gas deficit ran the opposite way to the oil
and gas heating-value surplus and was quietly cancelling part of it, so removing
one error exposed the other; the mean ratio moved from 1.013 to 1.017, which is
the oil-and-gas offset with nothing left masking it. The release where the
vintage difference does not exist says what actually happened: on 3.12, scored
with the same method and the same heating values on both sides, the category
went from 495 of 500 datasets agreeing within 2% to **499 of 500**, and its mean
ratio from 0.9963 to 0.9999. Two releases are worth having for exactly this
reason.

### Marine eutrophication

428 datasets within 2%, 73 in the 2× band, and this list's score never above
ecoinvent's — the lowest ratio is 0.752, and the difference is pure
subtraction. One substance does all of it: ecoinvent's `Nitrogen` emitted to
water, in four contexts, which EF v3.0 characterises at 1.0 kg N-eq/kg and this
list does not characterise at all.

It is not characterised because ecoinvent labels that flow CAS 7727-37-9, which
is dinitrogen, and N₂ dissolved in water does not eutrophy anything. The list
does publish `Nitrogen, Total (excluding N2)` at 1.0 in all four of the same
water contexts, which is what a total-nitrogen row should reach. The tell that
this reading is the right one is that ecoinvent stopped: their EF 3.1
implementation gives the same four flows nothing, and on 3.12 the category has
no disagreeing flow whatsoever. The datasets it moves on 3.8 are exactly the
nitrogen chemistry — urea formaldehyde resin at 0.752, the NPK and ammonium
nitrate markets, ammonia production — where wastewater denitrification puts N₂
in the water.

### Human toxicity and ecotoxicity

Start with the control. On 3.12, with EF 3.1 on both sides, all nine toxicity
categories agree on essentially every dataset: 500 of 500 identical for five of
them, 496 or 497 for the rest. So everything below is the revision between EF
v3.0 and EF 3.1, and none of it is the mapping.

EF v3.0 scores twelve toxicity categories and EF 3.1 scores nine, and the three
that vanished are the `metals` ones. That has two consequences on the table,
and only the first is obvious. The three `metals` rows have no counterpart and
report nothing. The three surviving `inorganics` rows pair up by name and are
**not** comparable either, because EF v3.0's `inorganics` excludes the metals
and EF 3.1's includes them: nearly every flow moving `ecotoxicity: freshwater,
inorganics` is reported as `only consensus factor`, and every one of them is a
metal — strontium, chromium(VI), iron, aluminium, cadmium, barium, silver. The
`organics` rows are the half of the split that survived unchanged, and they
agree: `human toxicity: carcinogenic, organics` is identical on all 501
datasets, and `ecotoxicity: freshwater, organics` is within 2% on 390 of them.

So the aggregates are the only honest reading of toxicity on 3.8, and each is
dominated by a handful of numbers the JRC revised:

- **`ecotoxicity: freshwater`** — 336 of 501 datasets in the 10× band, ratios
  from 0.012 to 9.4. Aluminium(3+) is four-fifths of it on its own: 188,000
  CTUe/kg to air under EF v3.0 against 2,002.7 under EF 3.1, a ninety-fourfold
  cut, repeated across seven compartments. Copper falls the same way (36,500 to
  17.0); iron (134 to 2,109) and chromium(VI) (1,040 to 12,274) rise, which is
  what puts a few datasets above 1 rather than below it.
- **`human toxicity: carcinogenic`** — two-fifths of the movement is
  chromium(III), which EF v3.0 gives 7.6e-05 CTUh/kg to air and EF 3.1 gives
  **zero**. EF 3.1 charges hexavalent chromium and not trivalent.
- **`human toxicity: non-carcinogenic`** — a fifth of it is carbon monoxide,
  1.08e-06 CTUh/kg under EF v3.0 and zero under EF 3.1, across three air
  compartments; chloride and chlorine are zeroed the same way.

What is left on 3.12, once the revision is out of the picture, is a handful of
pesticides — fenpropimorph, mecoprop, lambda-cyhalothrin — where ecoinvent
characterises a release to agricultural soil and this list has no factor, plus
kresoxim-methyl, where a ruling takes the JRC's 134.73 over ecoinvent's 53,540
(EF publishes that substance twice under two EC numbers). Each is under a
thousandth of its category.

## What the first run said

On the build of 25 August 2026, over 500 datasets of ecoinvent 3.12 cutoff
scored with EF 3.1 on both sides, 22 of 25 categories agreed within 2% on
almost every dataset. Water use was twice ecoinvent's on nearly all of them —
a median ratio of 2.00 over 462 datasets — and the two flows that moved it were
`Water, turbine use` withdrawn and `Water` returned to water, at +2.4e11 and
−2.4e11 over the sample: a withdrawal and its return, netting to almost
nothing, that this list characterises and ecoinvent's own implementation leaves
at zero. What was doubling the score was the flow both sides agreed on. Water
to air carries 42.95 on both, and that is ecoinvent's way of counting
consumption — what evaporates — while the withdrawals and returns are the
JRC's way — what was taken and not given back. On a water-balanced dataset the
two are the same cubic metres, and publishing both factors counted them twice.
The ecoinvent number had reached this list as `restated`, because 42.95 stands
bit for bit on every withdrawal of the category and that is what the identity
twin looks for. A `decline` in `data/lcia-factor-rulings.json` now withholds it,
and the median ratio is 1.00. That is the wind activity's water finding, for 460
datasets rather than one, and it is
[#150](https://github.com/brightway-labs/brightway-flows/issues/150).

What is left on water use after the ruling is not systematic: irrigation,
where the JRC's convention counts the withdrawal as consumed and ecoinvent's
counts nothing because none of it leaves as vapour; wastewater treatment, where
more is returned than withdrawn; and run-of-river hydro, whose return exceeds
its turbine withdrawal by a little. Those are the two conventions differing on
an unbalanced inventory, and the comparison names each one.

## What it does not do

It does not apply a regional factor. An aggregate inventory has no place to
apply one to, so only the factors stated for no particular place are used.
And it does not make brightway a dependency of this list: the exporter runs
under a brightway Python and the two share nothing but the file and the schema
that describes it.
