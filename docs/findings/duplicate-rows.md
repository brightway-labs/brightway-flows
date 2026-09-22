# Two rows, one name, one compartment — and it means one of two opposite things

*Part of [What we have found](index.md), the class where one name in one compartment holds two rows — which is either a substance published twice or two substances sharing a name.*

## One substance twice: carbon tetrachloride

EF 3.1 publishes carbon tetrachloride twice in each of five air compartments. One
row is `CFC-10`, carrying
[CAS 56-23-5](https://commonchemistry.cas.org/detail?cas_rn=56-23-5), EC
200-262-8, a general comment and some fifty synonyms. The other is
`Carbon tetrachloride`, carrying **no registry number, no EC number, no synonyms
and no comment at all**.

Both rows hold the same characterisation under the same nine method identifiers.
Six of the nine agree exactly. The rest differ only in how many digits were
kept — human toxicity, cancer is 0.000040473 on one row and 0.0000405 on the
other: the same number to five figures and to three.

Which row survives is not a detail. Sorting by "most factors, then by identifier"
ties on the factor count and then picks the *bare* row — the one with no
identifier of any kind, and the one no other list maps onto. ecoinvent's
correspondence lands on the identified row, reaching it from 3.8 as
`Methane, Tetrachloro-, R-10` and from 3.12 as `Carbon Tetrachloride`. Keeping the
anonymous row would have stranded every one of those mappings, so this pair — and
46 others — carries an explicit written ruling naming the survivor rather than
being settled by a sort
([#105](https://github.com/brightway-labs/brightway-flows/issues/105),
[#106](https://github.com/brightway-labs/brightway-flows/issues/106)).

Two rows of the same substance are often a chemical name beside an industry
designation — `Methyl chloroform` beside `HCFC-140`, `perfluorohexane` beside
`PFC-51-14`, `Carbon tetrachloride` beside `CFC-10` — which is
[the codes-as-names problem](names-and-numbers.md#hcfc-140-is-not-this-compound-either) showing up as
duplication. The rest are plainer: the same name written twice in one compartment,
28 substances' worth, with `kresoxim methyl` and one oxazolidinyl carbamate
duplicated in all thirteen compartments each, `methylene chloride` in nine and
`diethyl ether` in five.

## The two kinds, and how many of each

Carbon tetrachloride is the first of the two kinds, and the two need opposite
treatment.

A flow list is supposed to have one row per substance per compartment. When it has
two, the two rows are either the same substance written down twice, or two
different substances that happen to share a name. From the outside they look
identical, and they need opposite treatment: the first pair has to be merged, and
the second must never be.

Measured over EF 3.1's 94,062 flows, and excluding pairs that this project's own
renames created, **171 (name, compartment) pairs hold two rows.** They split
almost evenly, and the split is on whether the registry numbers agree:

| | groups | distinct names |
|---|---:|---:|
| one substance, published twice | 67 | 28 |
| two different substances, one name | 104 | 9 |

## Two substances once: nine names doing double duty

The other 104 groups are the dangerous ones, because merging them would be wrong.
Nine names in EF 3.1 each cover two different chemicals in the same compartment,
and in every case the pair is a substance and a close relative of it:

| the shared EF 3.1 name | one row is | the other row is |
|---|---|---|
| `1,3-benzenediamine` | m-phenylenediamine, 108-45-2 | its **dihydrochloride**, 541-69-5 |
| `calcium dihydrogen phosphate` | calcium **hydrogen** phosphate, CaHPO₄ | calcium **dihydrogen** phosphate, Ca(H₂PO₄)₂ |
| `bis(2-ethylhexyl) but-2-enedioate` | the **fumarate**, 141-02-6 | the **maleate**, 142-16-5 |
| `methyl 2-hydroxypropanoate` | (+)-methyl lactate | (−)-methyl lactate |
| `3,6-dimethyl-1,4-dioxane-2,5-dione` | **L**-lactide, 4511-42-6 | racemic lactide, 95-96-5 |
| `2,4-dihydroxy-N-(3-hydroxypropyl)-3,3-dimethylbutanamide` | **DL**-panthenol | (+)-panthenol |
| `1-pentene` | 1-pentene, 109-67-1 | mixed pentenes, 25377-72-4 |
| `tridemorph` | 2,6-dimethyl-4-tridecylmorpholine | the technical mixture, 81412-43-3 |
| `butene` | mixed butenes, 25167-67-3 | **polybutylene**, the polymer, 9003-29-6 |

Fumarate and maleate are the trans and cis forms of the same acid ester and behave
differently; CaHPO₄ and Ca(H₂PO₄)₂ carry different amounts of phosphorus per
kilogram; L-lactide and the racemate polymerise to different plastics. Nothing in
the flow name distinguishes any of them.

**The decision.** Identity is keyed on the registry number, so these pairs stay
apart on their own: each row keeps its number, its structure and its factors, and
they are published as two substances rather than fused.

**What is still wrong.** Keeping them apart is not the same as telling them apart
on sight. Six of the nine pairs are *published under one and the same preferred
label* today — both `1,3-benzenediamine` records are called `1,3-benzenediamine`,
both esters `Bis(2-ethylhexyl) But-2-enedioate`, both lactates
`Methyl 2-hydroxypropanoate`. The records are distinct and correct; the names on
them do not say so. Three of the nine were separated by a better name arriving from
the registries (`Calcium hydrogen phosphate`, `Lactide`, `Tridemorph`), which is
what the other six still need. See
[Known limitations](../reference/limitations.md) for how this reads in the published
output.

**What it cost, by source list:**

| source list | (name, compartment) pairs holding two rows |
|---|---:|
| **EF 3.1** | **171** — 67 duplicates, 104 name collisions |
| **ecoinvent 3.12** | 0 |
| **ecoinvent 3.8** | 0 |
| **BAFU 2026 v1** | 0 |

ecoinvent has none: one flow per substance per compartment, throughout. BAFU has
none either, though it looks otherwise at first — its repeated names are regional
variants of one flow (`Water, FR`, `Water, DE`, …) and pairs measured in becquerels
and kilobecquerels, which is [a units finding](units.md)
rather than a duplication.
