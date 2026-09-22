# A flow's name and its registry number name different chemicals

*Part of [What we have found](index.md), the class where the two halves of a flow's identity — the name and the registry number — name two different chemicals, and the error travels to every list that reads either half.*

## An ozone-depleting solvent, published as a carcinogen

**The two chemicals.** 1,1,1-trichloroethane
([CAS 71-55-6](https://commonchemistry.cas.org/detail?cas_rn=71-55-6),
[CHEBI:36015](https://www.ebi.ac.uk/chebi/searchId.do?chebiId=CHEBI:36015),
[PubChem CID 6278](https://pubchem.ncbi.nlm.nih.gov/compound/6278)) is the
degreasing solvent sold as methyl chloroform, phased out under the Montreal
Protocol because it depletes stratospheric ozone. Every list read here also calls
it `HCFC-140`, which is not a name it should have — see
[the box below](#hcfc-140-is-not-this-compound-either).
1,1,2-trichloroethane
([CAS 79-00-5](https://commonchemistry.cas.org/detail?cas_rn=79-00-5),
[CHEBI:36018](https://www.ebi.ac.uk/chebi/searchId.do?chebiId=CHEBI:36018),
[PubChem CID 6574](https://pubchem.ncbi.nlm.nih.gov/compound/6574)) is a
suspected carcinogen, used mostly as an intermediate, with no ozone-depleting
potential at all.

Both are C₂H₃Cl₃. They differ in which carbon carries the third chlorine —
`CC(Cl)(Cl)Cl` against `ClCC(Cl)Cl` — so the molecular formula cannot tell them
apart, and neither can a name that has been truncated or mistyped. The structure
can, and so can the registry number that stands for it.

**What EF 3.1 ships.** Read from the parsed EF 3.1 input, 20 August 2026:

| EF 3.1 flow name | registry number | flows | compartments |
|---|---|---:|---|
| `1,1,1-trichloroethane` | **79-00-5** | 5 | the five air compartments |
| `1,1,2-trichloroethane` | 79-00-5 | 8 | indoor air, all soil, all water |
| `HCFC-140` | 71-55-6 | 13 | all thirteen |
| `Methyl chloroform` | *none* | 4 | four air compartments |

Five flows are named after the ozone-depleting solvent and carry the carcinogen's
registry number. The carcinogen's own remaining eight compartments are named
correctly and carry the same number, and the two sets do not overlap: **together
the thirteen are one substance, named after its isomer in five of them.**

Meanwhile the real 1,1,1-trichloroethane is in the list twice — as `HCFC-140` in
all thirteen compartments, and as `Methyl chloroform` in four of them — and never
under its own systematic name. (`Methyl chloroform` ships with no registry number
whatsoever; that it is 71-55-6 is a separate correction this project makes,
[#35](https://github.com/brightway-labs/brightway-flows/issues/35).)

### `HCFC-140` is not this compound either

The name the solvent *is* published under in these lists is itself chemically
wrong, and wrong in a way that matters for this particular confusion.

**There is no fluorine in it.** HCFC stands for hydrochloro*fluoro*carbon.
1,1,1-trichloroethane is C₂H₃Cl₃ — three chlorines, no fluorine — so it is a
hydrochlorocarbon, an HCC. CAS Common Chemistry lists
[`HCC 140a` and `F 140a`](https://commonchemistry.cas.org/detail?cas_rn=71-55-6)
among the synonyms of 71-55-6, and none of the registries this project reads calls
it an HCFC.

**And the number, without its suffix, is the other isomer's.** In that numbering
the trailing letter distinguishes isomers, and Common Chemistry lists
[`HCC 140`](https://commonchemistry.cas.org/detail?cas_rn=79-00-5) — no suffix —
among the synonyms of **79-00-5, the carcinogen**. So `HCFC-140` invents a
fluorine the molecule does not have and then drops the one character that
separates this solvent from the very chemical it keeps being confused with.

It is not EF's coinage alone. All four lists carry it:

| source list | how the designation appears | flows |
|---|---|---:|
| EF 3.1 | the flow name, `HCFC-140` (`hcfc-140` in indoor air) | 13 |
| ecoinvent 3.12 | a synonym on `1,1,1-Trichloroethane` | 9 |
| ecoinvent 3.8 | inside the flow name, `Ethane, 1,1,1-trichloro-, HCFC-140` | 10 |
| BAFU 2026 v1 | inside the flow name, same spelling | 4 |

Nothing about the identification turns on this: the registry number, the
structure and the factors settle which chemical the flows are, and this project
publishes the substance under its systematic name, `1,1,1-Trichloroethane`. What
it does show is that **the flow name is unreliable evidence on both sides of this
pair** — one isomer is named after the other, and the other is named with a
designation no registry issues. It is also a finding in its own right, of a kind
[covered on its own page](part-numbers.md): a code that circulates inside
inventory lists, is treated as an identifier by anyone matching on names, and
belongs to no registry. This list currently republishes it as an alternative label
(`Hcfc-140`), inherited from EF's flow name, which is worth reconsidering on the
same grounds.

**The name is the half that is wrong**, on four independent witnesses.

*The registry number*, on all five flows, and on the eight correctly named ones
beside them.

*The synonyms EF ships with those five flows*: `1,1,2-Trichloraethan`,
`1,1,2-Trichlorethane`, `Ethane, 1,1,2-trichloro-`, `Trichloroethane, 1,1,2-`,
`Vinyl trichloride`, `beta-Trichloroethane`. Every one of those is a name for
1,1,2-trichloroethane. The flow's own synonym list contradicts the flow's name.

*The characterisation factors.* Per kilogram to non-urban air or from high stacks:

| impact category | the flow named `1,1,1-trichloroethane` | `HCFC-140`, the real 1,1,1 |
|---|---:|---:|
| Climate change | *none* | 161.0 |
| Photochemical ozone formation | *none* | 0.0152 |
| Ecotoxicity, freshwater | 1.149 | 4.3159 |
| Human toxicity, cancer | 4.1845e-07 | 0.0 |
| Human toxicity, non-cancer | 1.2878e-06 | 1.4942e-08 |
| Ozone depletion | 0.14 | *none* |

A cancer factor where the real solvent has a stated zero, a non-cancer factor 86
times higher, and no climate-change factor at all although EF itself gives the
real solvent one of 161. Those are the carcinogen's numbers.

*USEtox 2.1, read directly.* EF 3.1's three toxicity categories are USEtox, so the
underlying model can be asked about each chemical by name rather than through
EF's flows. Reading the USEtox workbooks reproduces 228 of the 228 EF values this
project already records from them, with no mismatches, which is what makes the
reading trustworthy here. Asked about these two chemicals, per kilogram to urban
air close to ground:

| EF 3.1 flow | category | EF 3.1 | USEtox, for the chemical the flow's *number* names |
|---|---|---:|---:|
| the mislabelled one | Human toxicity, cancer | 1.3184e-06 | 1.31798e-06 |
| `HCFC-140` | Human toxicity, cancer | 0.0 | 0 |
| the mislabelled one | Human toxicity, non-cancer | 4.0983e-06 | 4.11587e-06 |
| `HCFC-140` | Human toxicity, non-cancer | 1.7557e-08 | 1.75022e-08 |

USEtox gives 1,1,1-trichloroethane a cancer factor of exactly zero — it is not a
carcinogen — and EF's `HCFC-140` says 0.0, while the mislabelled flow carries the
carcinogen's non-zero number to three figures. Non-cancer agrees with its own
chemical to within rounding and differs from the other isomer by two orders of
magnitude. **EF assigned these factors by registry number, and then named five of
the flows after the wrong chemical.**

**The number is what changed, and it changed between two versions of EF.** In
**EF 3.0** those same five flows — same identifiers, same name — carry
**71-55-6**, the solvent's own number, in the published ILCD flow list. EF 3.1
kept the identifiers and the name and replaced the number with its isomer's. So
this is not a flow that was always mislabelled: it is a flow whose stated identity
changed under a stable identifier, which is
[a class of its own](identifier-reuse.md).

**That is what makes the mapping wrong, and the mapping was right when it was
made.** The published ecoinvent → EF correspondence is
[GLAD's](https://github.com/One-Click-LCA/GLAD-ElementaryFlowResources/blob/master/Mapping/Output/Mapped_files/ecoinventEFv3.7-ILCD-EFv3.0.xlsx),
mapping ecoinvent 3.7 to EF 3.0, and it sends ecoinvent's
`Ethane, 1,1,1-trichloro-, HCFC-140` — registered 71-55-6 — to these five flows in
the five air compartments, **rows 1756 to 1760**, every one of them with
`MapType = CAS`. Against EF 3.0 that was a true registry-number match, 71-55-6 to
71-55-6. The same table's water rows, 1761 to 1765, go to `HCFC-140` instead,
which is why the substance splits by compartment at all. Read against EF 3.1, five
correct rows now point at the wrong isomer and five point at the right one.

Measured on the build of 20 August 2026 merging ecoinvent 3.12, ecoinvent 3.8 and
BAFU 2026 v1:

| source list | flows for this solvent | carrying the error | what the error is |
|---|---:|---:|---|
| **EF 3.1** | 17 | **5** | five flows renumbered to the carcinogen's registry number since EF 3.0, keeping the solvent's name — the origin |
| **ecoinvent 3.12** | 9 | **4** | every emission to air published as the carcinogen |
| **ecoinvent 3.8** | 10 | **5** | every emission to air published as the carcinogen |
| **BAFU 2026 v1** | 4 | 0 | all four published correctly |

So **nine of the twenty-three inventory rows for this solvent were published as a
different chemical** — and one ecoinvent substance was split by compartment across
two published substances, with its ten emissions to water correct and its nine
emissions to air not. The half that moved is the half that matters for an
ozone-depleting solvent.

BAFU escaped for a structural reason: it has no correspondence table, so its rows
are matched on what they themselves carry, and 71-55-6 reaches the substance that
number belongs to. ecoinvent's rows were sent by a table that had been settled
years earlier and never re-asked — which is the difference that matters here, not
the difference between matching on a name and matching on a number.

**The decision.** The registry number is trusted and the name is corrected, the
same way as for other mislabelled flows
([#46](https://github.com/brightway-labs/brightway-flows/issues/46)):

- EF's five misnamed flows are renamed `1,1,2-trichloroethane`, keeping 79-00-5.
  The replaced spelling is *not* kept as an alternative label — an alternative
  label asserts that the substance is also known by that name, and this substance
  is not; the name belongs to a different molecule. Three synonyms carrying the
  1,1,1 spelling are dropped with it, because a synonym is searched and matched on
  and would re-assert by name exactly the identity the registry number denies.
- The rename is conditional on the number as well as the name, so a flow that
  legitimately carries 71-55-6 under a spelled-out `1,1,1-trichloroethane` is left
  alone. That case is this error in reverse, and renaming it would create the
  thing being fixed.
- The nine ecoinvent air rows are re-pointed onto EF's `HCFC-140` in the same
  compartment. This is the half the published output turns on: correcting a name
  cannot move a row, because a row matched through a correspondence table follows
  the identifier the table states. The five source identifiers involved are stable
  across every ecoinvent release on hand and carry 71-55-6 in all of them.

After the fix, all nineteen ecoinvent rows and all four BAFU rows are published as
`1,1,1-Trichloroethane`, and the substance carries its own factors: climate change
161.0, photochemical ozone formation 0.0152, and a cancer factor of zero
([#121](https://github.com/brightway-labs/brightway-flows/issues/121)).

**What is still wrong, and is not ours to fix silently.** The ozone-depletion
factor of 0.14 sits on the flow EF misnamed, and EF gives `HCFC-140` none. Ozone
depletion is 1,1,1-trichloroethane's signature effect, and 1,1,2-trichloroethane
is controlled by nothing and has no published ozone-depletion potential — so that
one number was evidently assigned to the flow by its *name* while every other
factor on it was assigned by its *number*. The consequence of putting the rows on
the right chemical is that **an ozone-depleting solvent currently scores zero for
ozone depletion in this list.** The score it lost was the right effect reached
through the wrong chemical's flow, arriving with a cancer factor the solvent does
not have. Moving a factor onto a substance no implementation puts it on is a
larger decision than renaming a flow, and it is open as
[#126](https://github.com/brightway-labs/brightway-flows/issues/126).

## What settles it when the two halves disagree

Those five flows are one case of something no flow list is protected against.

Every flow in a modern list carries at least two independent statements of what
it is: a name, and a registry number — a CAS number, an EC number, or both. The
two are maintained by different people at different times, and nothing in a flow
list forces them to agree. When they disagree, the list is internally
inconsistent, and there is no way to tell from the flow alone which half is
wrong.

There are usually three further witnesses available, and they are what settles it:

- **the synonyms the list ships with the flow**, which are often inherited from a
  chemical database and therefore track the identifier rather than the name;
- **the characterisation factors attached to the flow**, which were computed for
  one chemical by a model that names its substances itself;
- **the registry entry**, which states a structure, and a structure is what
  distinguishes chemicals that a name or a formula cannot.

This project's rule is that a registry number outranks a name — see
[A name is not an identifier](../deciding/identity.md) —
but the rule only decides which record wins. It does not repair the name, and it
does nothing at all about the second half of the damage, which is that **the error
does not stay in the list that contains it.** Correspondence tables between
inventory lists are built on both halves — of the 5,394 rows in GLAD's published
ecoinvent-to-EF file, 2,477 are matched on the flow name and 2,280 on the registry
number — so a list whose own naming is correct can inherit another list's error
through the mapping and arrive at the wrong substance without ever having said
anything wrong itself. And a row matched on the number is not safe either, as
[the identifier that stayed while the substance changed](identifier-reuse.md)
shows: the number can change under it.

## When the name is the half that is right

The rule is not mechanical, and one case in the same class went the other way.

EF 3.1 ships thirteen flows named `vanadium (v)`, one per compartment, and gives
every one of them **15121-26-3** — which
[CAS Common Chemistry](https://commonchemistry.cas.org/detail?cas_rn=15121-26-3)
names `Vanadium(2+)`. Name and number again disagree; this time the name is
right, and three things say so.

EF names this family by oxidation state and does it consistently: `chromium (iii)`
and `chromium (vi)`, `arsenic (iii)` and `arsenic (v)`, `antimony (iii)` and
`antimony (v)`, `iron (ii)` and `iron (iii)`. Read as anything but a five,
`vanadium (v)` would be the element — and EF already publishes the element
separately as `vanadium`, 7440-62-2, in the same thirteen compartments. And
ecoinvent, independently, registers its own pentavalent vanadium flows as
**22537-31-1**, which is
[ChEBI:33003, vanadium(5+)](https://www.ebi.ac.uk/chebi/searchId.do?chebiId=CHEBI:33003).
Nothing else in the list is left needing the name.

What the wrong number cost while it stood: enrichment resolved 15121-26-3 to the
divalent ion, took its synonym, and renamed the substance `Vanadium(2+)`, so
thirteen EF flows and every characterisation factor on them were published as a
different ion. The fix keeps the name and replaces the number
([#49](https://github.com/brightway-labs/brightway-flows/issues/49)).

Two cases, one class, opposite outcomes — which is the point. *A registry number
outranks a name* decides who wins when there is nothing else to go on. Where the
list's own naming is systematic, and the substance the number names is already
published separately under its own flows, that is evidence, and it can outweigh
the number.

### Five metals, and the number is the element's

The same shape, in a second list, and this time the evidence is the vendor's
own. BAFU 2026 v1 ships five flows named for a metal in its +2 oxidation
state — one row each, all emissions to air in populated areas — and writes the
**metal's** registry number on every one:

| BAFU 2026 v1 ships | numbered | which is | the ion's own number |
|---|---|---|---|
| `Cadmium II` | 7440-43-9 | cadmium the metal | 22537-48-0 |
| `Zinc II` | 7440-66-6 | zinc the metal | 23713-49-7 |
| `Mercury II` | 7439-97-6 | mercury the metal | 14302-87-5 |
| `Lead II` | 7439-92-1 | lead the metal | 14280-50-3 |
| `Nickel II` | 7440-02-0 | nickel the metal | 14701-22-5 |

Three things say the name is the half that is right. BAFU uses the roman
numeral the way every list here does: its own `Chromium III` carries
16065-83-1, the trivalent ion's number, and lands on `Chromium(3+)` without
anybody having to read the name. **BAFU already ships a plain `Cadmium` row
under 7440-43-9 in that very compartment**, so read as the metal, `Cadmium II`
is a second name for a substance the list lists once — which no vendor does on
purpose. And ecoinvent ships the same five names, fourteen rows each, under
the ions' own numbers.

What it cost was the thing a registry number is supposed to prevent: one name
meaning two substances depending on which list wrote the row. BAFU's five
emissions were published as the elements, beside ecoinvent's seventy identical
names published as the ions, and a cadmium emission characterised as the metal
is not the one characterised as the ion. Each of the five is now given the
ion's number by a curated fix that records what BAFU wrote beside what it
should have written
([#146](https://github.com/brightway-labs/brightway-flows/issues/146)) —
a replacement rather than a fill, the same shape as the `vanadium (v)`
correction above. Reading the numeral off the name instead was considered and
rejected: it would decide identity by regex, and BAFU's own `Chromium III`
shows a correctly numbered row does not need it. See [how an arriving row is
narrowed](../deciding/registry-numbers.md#where-a-number-reaches-several-substances-how-an-arriving-row-is-narrowed).
