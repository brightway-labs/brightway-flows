# A class of substances is published as one of its members

*Part of [What we have found](index.md), the class where the source row names a family of chemicals and the published flow is one particular member of it.*

## Amine oxides are not lauramine oxide

ecoinvent 3.8 ships this row:

| | |
|---|---|
| name | `Amine oxide` |
| identifier | `b157329c-4179-5491-97c4-649900954ffa` |
| compartment | air / unspecified |
| unit | kg |
| registry number | **1643-20-5** |

[1643-20-5](https://commonchemistry.cas.org/detail?cas_rn=1643-20-5) is
dodecyldimethylamine oxide — lauramine oxide, the twelve-carbon surfactant in
washing-up liquid. An amine oxide is any amine carrying an oxygen on its nitrogen,
and a detergent formulation may use several. The flow is the class; the number is
one member of it.

**ecoinvent says so itself, one release later.** Under the same identifier, 3.9.1
renames the flow `Amine oxides` — plural — and ships it with **no registry number
at all**, and 3.10.1, 3.11 and 3.12 keep it that way. Nothing else about the row
changed. So this is not a reading of an ambiguous name: the list that published
the number withdrew it, and left the plural behind to say what the flow had always
meant.

**The mapping was faithful and the result is still wrong.** GLAD's row 312 sends
this flow to EF's `dodecyl(dimethyl)amine oxide` with `MapType = CAS` — a true
registry-number match against the number ecoinvent then carried, made before the
withdrawal. Read against 3.12, where the flow means the class and carries no
number, that row publishes a family as one surfactant. It is the same shape as
[the identifier that stayed while the substance
changed](identifier-reuse.md), one step removed: here
the identifier stayed and the *number was taken away*, and the table went on
quoting it.

**What it cost.** On the build of 21 August 2026 at `f27d89b`, ecoinvent's
`Amine oxides` was published as `Dodecyl(dimethyl)amine Oxide`, in EF's air flow
for that surfactant, which carries four characterisation factors. Whatever the
underlying datasets released as amine oxides was scored as lauramine oxide, and
the substance answered to `Amine Oxides` as one of its names.

**The decision.** The mapping row is declined and the class is published as itself,
minting the flow it needs — and, because declining the row hands the flow back to
name and number matching, 3.8's registry number is corrected in the same change,
or it would send the flow straight back to the member. The rule that correction is
written under is worth stating, because it decides a class of cases and may want
revisiting: **where one flow identifier carries different fields in different
releases, the latest release is canonical.** ecoinvent means one flow by one
identifier, so a later release restating it is a correction of what it said before
([#123](https://github.com/brightway-labs/brightway-flows/issues/123)).

## The catch-all class, running the other way

This is [the catch-all class](catch-alls.md) inverted, and it is quieter
because it moves the same identity in the opposite direction. There, a source row
names one chemical and the table sends it to a bucket, so different chemicals
become one. Here the source row names the **class** — `Amine oxides`,
`Diphenylether compounds` — and it is published as one particular member of that
class. Everything a dataset reported under the class is then stated to be that one
chemical, scored with that one chemical's factors, and the class's name is added to
the member's list of names, so a search for either returns the other.

Both start from the same place: EF has no flow for the thing the source row names,
and the table reaches for the nearest thing it has.

## The same shape, twice more

**Diphenyl ether is not the diphenylethers.** ecoinvent 3.8's
`Diphenylether-compound` (water, unspecified, `1d8560a8-…`) carries
[101-84-8](https://commonchemistry.cas.org/detail?cas_rn=101-84-8), which is
diphenyl ether itself — the parent compound rather than the family named after it,
whose best-known members are the brominated flame retardants. From 3.9.1 the same
identifier is `Diphenylether compounds` with no number, exactly as with the amine
oxides. GLAD's row 1672 matched the number, and the family was published as the
parent ether, which EF characterises with four factors.

**Stibnite is not the ion.** Different cause, same consequence, and it reaches a
second list. ecoinvent's `Stibnite` is the antimony ore, Sb₂S₃, taken out of the
ground and weighed in kilograms; GLAD's **row 4458** sends it to EF's `antimonite`
under `MapType = FLOWNAME_MANUAL (PROXY)` — matched on the resemblance of the two
names, because EF has no flow for the mineral. Antimonite is the dissolved
oxyanion, `O3Sb-3`. A mineral in the ground and an ion in solution are not one
substance, and the mineral handed the ion its name.

That is what damaged BAFU. BAFU ships its own `Stibnite` row in `resources / in
ground`, registered
[1317-86-8](https://commonchemistry.cas.org/detail?cas_rn=1317-86-8) — the
mineral's own number, which is right — and it has no correspondence table
anywhere near it. EF carries no flow for 1317-86-8, so the number reached nothing
and the name reached the ion: the merge recorded `basis: label`,
`basis_value: Stibnite`. **A list that was correct about stibnite, and said so with
a registry number, was pulled onto a dissolved ion by a table that never read it.**

**What it cost, per source list**, on the build of 21 August 2026 at `f27d89b`:

| source list | flows | what the error is |
|---|---:|---|
| **ecoinvent 3.8** | 3 | two class-named flows carrying one member's registry number — `Amine oxide` and `Diphenylether-compound`, both withdrawn from 3.9.1 under the same identifiers — and `Stibnite, in ground` |
| **ecoinvent 3.12** | 3 | the two classes published as one member each, and `Stibnite` published as the dissolved ion |
| **BAFU 2026 v1** | 1 | its own correct `Stibnite` row pulled onto the ion by the name the ion had absorbed |
| **EF 3.1** | 0 | no flow for any of the three classes — the coverage gap the proxies fill; its member flows are its own, correctly named |
| **GLAD's mapping** | 3 rows | 312 and 1672 by CAS, faithful to the number ecoinvent then carried; 4458 a name proxy, flagged as one |

**The decision**, in all three cases: the row is declined, the class or the mineral
is published as itself, and the specific member keeps its own flows and its own
factors. Stibnite's registry number is corrected as well — ecoinvent registers the
ore as the manufactured compound, 1345-04-6, where IARC separates the two and gives
the mineral 1317-86-8, which is the number BAFU had reached independently.
