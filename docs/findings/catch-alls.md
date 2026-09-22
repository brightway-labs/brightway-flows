# A named substance is mapped onto a catch-all, and different chemicals become one

*Part of [What we have found](index.md), the class where a correspondence table sends a row that names its chemical to a flow that names none.*

## Kaolin is not alanycarb

The published ecoinvent → EF mapping is
[GLAD's ecoinvent 3.7 → ILCD EF 3.0 file](https://github.com/One-Click-LCA/GLAD-ElementaryFlowResources/blob/master/Mapping/Output/Mapped_files/ecoinventEFv3.7-ILCD-EFv3.0.xlsx),
5,394 rows. **Thirty-five of them name a specific pesticide and target a
catch-all**, covering 34 substances:

| catch-all target in EF 3.0 | rows | named substances |
|---|---:|---:|
| `insecticides, unspecified` | 13 | 13 |
| `fungicides, unspecified` | 10 | 9 |
| `herbicides, unspecified` | 8 | 8 |
| `pesticides, unspecified` | 4 | 4 |

Among the thirteen routed to `insecticides, unspecified` are `alanycarb`
([row 260](https://github.com/One-Click-LCA/GLAD-ElementaryFlowResources/blob/master/Mapping/Output/Mapped_files/ecoinventEFv3.7-ILCD-EFv3.0.xlsx),
83130-01-2, a carbamate), `hexaflumuron` (row 2251, 86479-06-3, a benzoylurea),
`thiacloprid` (row 4724, 111988-49-9, a neonicotinoid), `novaluron` (row 3480) —
and `kaolin` (**row 2639**,
[CAS 1332-58-7](https://commonchemistry.cas.org/detail?cas_rn=1332-58-7)), which
is a clay. It is sprayed as a particle film rather than as a poison, and whatever
one thinks of its being classed as an insecticide, it is not alanycarb.

**GLAD says these are approximations, and says so in the file.** Every one of the
35 rows carries `MapType = FLOWNAME_MANUAL_PROXY`: a manual match on the flow
name, flagged as a proxy. The 19 further rows that reach the same buckets are the
buckets mapping to themselves — `fungicides, unspecified` to
`fungicides, unspecified`, rows 2103 to 2108 and their neighbours — which is
exactly right.

So the finding here is not that GLAD claimed something false. It is that **a
proxy is the only thing the table can offer**, because for 34 named pesticides EF
3.0 has no flow at all, and that a proxy stops looking like one as soon as the
qualifier is dropped downstream. This project's own export dropped it: it
published these as *exact* matches, which chains — if thirteen flows are exact
matches for one bucket they are exact matches for each other, and the export said
that alanycarb is kaolin. That was ours to fix, and it is fixed
([#76](https://github.com/brightway-labs/brightway-flows/issues/76));
GLAD's file never said it.

**The characterisation follows the bucket.** EF's three insecticide, herbicide and
fungicide catch-alls carry four factors each — freshwater ecotoxicity and human
toxicity, non-cancer — computed for an unspecified product of that class. A row
sent there is scored as the generic bucket, not as the chemical the source named,
in either direction and by an unknown amount.

**The decision.** Every one of these rows is declined: the prepared target is
refused, and the substance is published under its own name, minting the flows it
needs. Kaolin is the case that shows why declining is not the same as ignoring —
EF *does* carry `kaolin`, but only as a resource extracted from the ground, so
there was no emission flow to redirect to and the bucket was the table's only
option. What a pesticide *is for* is not thrown away with the bucket: the class is
published as a role on the substance — this substance has the role of an
insecticide — rather than as the name of a different flow.

**What it cost, and whose rows they are.** GLAD maps one compartment per
substance — 33 of the 35 rows are `soil/agricultural`, the compartment a pesticide
application is actually reported in, plus two water rows for `trifloxystrobin`.
The table this project reads is not GLAD's file directly: it is GLAD's mapping
carried forward to ecoinvent 3.11 and EF 3.1 and extended with further matches,
and in it the same 34 substances reach a bucket in **all seven** of their
compartments — 307 rows. **Only the 35 are GLAD's**; the other 272 rows are the
extension, which is this project's own work and not a finding about anybody's
published data.

| source | rows sending a named pesticide to a bucket | substances |
|---|---:|---:|
| **GLAD ecoinvent 3.7 → EF 3.0**, as published | **35** (all marked proxy) | 34 |
| the table this project reads, after extension | 307 | 49 |
| **BAFU 2026 v1** | 0 — it has no correspondence table | — |

BAFU is the control, for a structural reason: with no table, its rows are matched
on what they carry and reach their own substances. Nine of these pesticides are in
BAFU — `Boscalid`, `Thiacloprid`, `Trifloxystrobin` and six others — and every one
lands on itself. **The gap is in EF 3.0's coverage, and the table could only paper
over it.**

Those 35 are the pesticide buckets alone, which is where the class was first
looked for. [Seven further rows](#the-buckets-are-not-only-the-pesticide-ones)
send a named chemical to a *hydrocarbon* bucket, so GLAD's file holds 42 such rows
over 38 substances, and the summary table on [the overview](index.md) counts all of
them.

## What the catch-alls are for

The bucket itself is not the error, and a table that reaches for one is not
inventing anything.

Every inventory list carries catch-all flows — `Insecticides, unspecified`,
`Pesticides, unspecified` — and they exist for a real situation: a field
application where the record does not say which product was used. They are a
statement of ignorance, and a correct one.

The published correspondence table routes rows onto them that are *not* ignorant.
The source row names the pesticide, gives its registry number, and the table sends
it to the bucket anyway. What the source knew is discarded at the point of
translation, and — because everything in the bucket becomes the same published
flow — chemicals that have nothing to do with each other become one substance.

## The buckets are not only the pesticide ones

The pesticide catch-alls were found first because a curator was reading
pesticides. The same thing happens at the **hydrocarbon** buckets, seven rows of
it, and it is the same table doing it:

| GLAD row | source flow | registry number | target bucket |
|---:|---|---|---|
| 2131 | `glucose` | 50-99-7 | `hydrocarbons, aliphatic, unsaturated` |
| 3541 | `octaethylene glycol monododecyl ether` | 3055-98-9 | `hydrocarbons, aliphatic, alkanes, unspecified` |
| 1631 | `dimethyl hexynediol` | 142-30-3 | `hydrocarbons (unspecified)` |
| 1771–1773, 1775 | `ethane, 1,1,2-trichloro-` | 79-00-5 | `hydrocarbons, chlorinated` |

All seven carry `MapType = FLOWNAME_MANUAL_PROXY`, so GLAD again flags them as
approximations. What is new here is that **for three of the four substances the
bucket is not even the right kind of thing.** A hydrocarbon is a molecule of
carbon and hydrogen and nothing else. Glucose is a sugar, C₆H₁₂O₆; octaethylene
glycol monododecyl ether is a non-ionic surfactant, C₂₈H₅₈O₉; dimethyl hexynediol
is a diol, C₈H₁₄O₂. Every one of them has oxygen in it, and the third is sent to
an *unspecified* bucket while carrying a perfectly good registry number. So this
is not a specific chemical made less specific: it is a sugar published as an
unsaturated hydrocarbon.

EF 3.1 ships no flow for any of those three — checked by registry number across
all 94,062 of them — so the coverage gap is the same one the pesticides ran into.
The fourth is different, and worse: EF ships `1,1,2-trichloroethane` in thirteen
compartments, and the same table reaches it in one of the five, which is the next
section.

**What it cost.** On the build of 20 August 2026 at `8be2336`, before the
corrections, thirteen ecoinvent rows across 3.12 and 3.8 were published as a
hydrocarbon bucket: seven for 1,1,2-trichloroethane and two each for the other
three. Seven of the thirteen are GLAD's rows; the rest are the extension carrying
them into compartments GLAD never mapped, and are this project's own. The
characterisation follows the bucket in both directions: the diol was scored with
the four factors `Hydrocarbons (unspecified)` carries in water, and the seven
trichloroethane rows were scored with nothing at all, because
`Hydrocarbons, Chlorinated` carries no factor in any of the air compartments they
reach while the substance's own flow carries seven in the same place. Every row is declined, the same as the
pesticide rows, and each substance is published under its own name
([#123](https://github.com/brightway-labs/brightway-flows/issues/123),
[#124](https://github.com/brightway-labs/brightway-flows/issues/124)).

## The table sometimes already names the right target

Nothing requires a correspondence table to give the same answer twice for one
substance, and where it does not, one of the two answers is usually already right.
Read on its own, GLAD's file has five source flows that reach more than one EF
substance:

| source flow | the two targets | how it splits |
|---|---|---|
| `ethane, 1,1,2-trichloro-` | `hydrocarbons, chlorinated` / `1,1,2-trichloroethane` | four air rows to the bucket; the fifth, **row 1774**, to the substance itself, matched on its registry number |
| `trifloxystrobin` | `trifloxystrobin` / `fungicides, unspecified` | air and soil to itself by CAS, both water rows to the bucket |
| `nitrogen` | `dinitrogen` / `nitrogen, total (excluding n2)` | three air and resource rows to `dinitrogen`, matched on **7727-37-9**; nine soil and water rows to a nutrient-load measure whose own name excludes the substance being sent to it |
| `ethane, 1,1,1-trichloro-, hcfc-140` | `1,1,1-trichloroethane` / `hcfc-140` | five air rows to one, five water rows to the other, every row by CAS — [two EF flows for one chemical](names-and-numbers.md#an-ozone-depleting-solvent-published-as-a-carcinogen) |
| `water, unspecified natural origin` | `water` / `ground water` | taken from a fossil well or from the ground to one, taken from water to the other — decided by compartment on purpose |

The first four are the finding. In each, **the table names the
registry-number-matched substance in at least one compartment and something else
in the rest**, so no chemistry judgement is needed to see that it disagrees with
itself: the better answer is in the file already. A consumer adding up
1,1,2-trichloroethane gets one air compartment of five, and the four it loses were
folded in with every other chlorinated solvent nobody named. Nitrogen is the
starkest, because the target's own name rules the source out: `nitrogen, total
(excluding N2)` is the sum of nitrogen in its reactive forms, and what the table
sends it, in nine compartments, is N₂
([#125](https://github.com/brightway-labs/brightway-flows/issues/125)).

Row 1774 is worth its own sentence, because it is the row that got the substance
right: it sends an emission to **unspecified** air into EF's **indoor** air flow.
Indoor air is not a subdivision of the outdoor atmosphere and carries its own
factors, so the one row that identified the chemical correctly still lands
somewhere the source row was not.

The last row of the table is why a check for this cannot key on the split alone:
water against ground water is deliberate, and in the extended table carbon
dioxide's biogenic and land-use-change variants are too. This project now checks
the narrower question, recomputing it from the shipped tables rather than from a
list somebody typed: where one source flow reaches more than one substance and one
of those targets matches the flow's registry number, the others are reported
([#122](https://github.com/brightway-labs/brightway-flows/issues/122)).
