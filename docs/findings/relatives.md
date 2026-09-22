# A substance is given its chemical relative's common name

*Part of [What we have found](index.md), the class where the plain common name sits on the salt, the hydrate or the racemate rather than on the chemical the name belongs to.*

## Paraquat is not paraquat dichloride, and a tonne of gypsum is not a tonne of anhydrite

EF 3.1 puts the plain common name on the relative for six substances, over 66
flows:

| EF 3.1 name | registry number it carries | what that number is | flows |
|---|---|---|---:|
| `paraquat` | 1910-42-5 | paraquat **dichloride**, the salt | 13 |
| `MCPA` / `mcpa` | 3653-48-3 | **MCPA-sodium**, the sodium salt | 13 |
| `flupyrsulfuron-methyl` | 144740-54-5 | the **sodium salt** of it | 13 |
| `mecoprop-p` | 7085-19-0 | **mecoprop**, the racemic mixture | 13 |
| `gypsum` | 7778-18-9 | **anhydrite**, the water-free mineral | 1 |
| `1,3,5-triazine` | 121-82-4 | **RDX**, the explosive, a trinitro derivative of the hydrogenated ring | 13 |

Take paraquat. The chemical called paraquat is a doubly charged ion,
[4685-14-7](https://commonchemistry.cas.org/detail?cas_rn=4685-14-7). What is
sold and sprayed is its chloride salt, paraquat dichloride,
[1910-42-5](https://commonchemistry.cas.org/detail?cas_rn=1910-42-5) — **38% heavier
for the same amount of active herbicide.** EF 3.1 ships both, and puts the plain
name on the salt.

**Three witnesses, and the third is the source itself.** Every one of the thirteen
flows carries the dichloride's registry number and the dichloride's EC number,
217-615-7. Every one of the fifty-odd synonyms EF ships with them names the salt —
`Paraquat dichloride`, `1,1'-Dimethyl-4,4'-bipyridinium dichloride`,
`Methyl viologen dichloride`, and the products `Gramoxone`, `Esgram`,
`Pillarxone`; the bare word `Paraquat` appears in none of them. And EF states the
rule itself, in the general comment shipped on these flows:

> Correct mapping CAS and flow to be verified: yet unclear whether this is the
> sodium-, hydrochloride-, calcium-, potassium- or other salt or the pure
> substance that is emitted. Note that the CAS No is the relevant identifier, to
> which also the ILCD LCIA characterisation factors relate.

That is the source telling the reader to trust the number over the name.

**The substance the plain name belongs to is already in the list**, in all
thirteen compartments, under its systematic name
`1,1'-dimethyl-4,4'-bipyridinium` — and *that* flow's synonyms include `PARAQUAT`,
`Paraquat ion` and `Paraquat dication`. Nothing is lost by taking the bare name
off the salt.

**What it cost, and who caused it.** This is where the attribution has to be
careful, because the naming error and the mapping error have different authors.

**GLAD got three of the five right.** Its file maps ecoinvent's `paraquat` to EF's
`1,1'-dimethyl-4,4'-bipyridinium` — the ion, correctly — at rows 3659 and 3660;
`mcpa` to `2-methyl-4-chlorophenoxyacetic acid`, the acid, at rows 2928 to 2931;
and `mecoprop-p` to `(r)-2-(4-chloro-2-methylphenoxy)propionic acid`, the pure
enantiomer, at row 2937. Every one of those is a registry-number match onto the
right substance, and none of them uses EF's mislabelled flow. The misroutings this
project measured in its own builds — five paraquat rows onto the salt, four MCPA
rows onto the sodium salt, six mecoprop-P rows onto the racemate — come from rows
added to the table *after* GLAD, by name, in compartments GLAD never mapped. They
are this project's own and are not a finding about published data.

**Two of the five are GLAD's, and both are forced by EF.** `gypsum, in ground`
(row 2183) and `anhydrite, in ground` (row 331) are both mapped onto EF's single
`gypsum` flow — the one carrying anhydrite's registry number — because EF 3.0 has
exactly one flow for the two minerals. Both rows are marked
`FLOWNAME_MANUAL (PROXY)`; two different minerals, one target, and the target is
named after the hydrate while it is numbered as the anhydrous salt. And
`flupyrsulfuron-methyl` (row 2051) was a true number match in 3.7 and became wrong
when ecoinvent renumbered its flow, which is
[the identifier-reuse class](identifier-reuse.md).

**What the EF naming error costs regardless of any table** is the thing this
section is really about: any step that matches on a name — and every list without
a correspondence table matches on names — sends a row naming `paraquat` to a flow
that is paraquat dichloride, and a row naming `gypsum` to a flow that is anhydrite.
The name is the trap, and it is EF that set it.

**The decision.** Correct the name on EF's flow, keep the registry number, and do
not retain the replaced name as a synonym — because it is a name of a *different*
substance, and retaining it would leave every name-matching step landing exactly
where it did before. Where the correct target exists in EF, the ecoinvent rows are
re-pointed onto it; where it does not — the flupyrsulfuron parent acid, gypsum in
the compartments ecoinvent uses — the mapping is declined and the substance is
published under its own name
([#119](https://github.com/brightway-labs/brightway-flows/issues/119)).

Mecoprop needed one more thing: EF files it under **7085-19-0**, and the number in
current use is 93-65-2. Asked for the old number, CAS Common Chemistry returns a
record whose own registry number is 93-65-2 — the service resolving the superseded
entry onto the current one. ecoinvent and BAFU both already carry 93-65-2, so EF
was the only list holding the old number, and correcting it moved eight ecoinvent
rows and one BAFU row from matching on a *name* to matching on a *number*.

**What it cost, by source list:**

| source | extent |
|---|---|
| **EF 3.1** | **53 flows**, five substances named after a relative — the origin, and the whole of the finding |
| **GLAD's published mapping** | **3 rows** forced by it: `gypsum` and `anhydrite` onto one flow (rows 331, 2183), `flupyrsulfuron-methyl` onto the salt (row 2051) |
| **ecoinvent** | distinguishes all five pairs correctly, with the right number on each |
| **BAFU 2026 v1** | ships `Gypsum`, `Anhydrite`, `Paraquat`, `Mecoprop` and `Mecoprop-P` as separate rows, with the right number on each — except `Anhydrite`, which carries none at all |

## Common names, and the thing that is actually sold

What EF did with paraquat is not peculiar to EF, or to herbicides.

Pesticides, minerals and pharmaceuticals are known by a common name — *paraquat*,
*MCPA*, *gypsum* — and the thing actually sold, sprayed or mined is very often not
the chemical that name belongs to. It is a salt of it, a hydrate of it, an ester
of it, or one of its two mirror images. The relatives differ in molecular weight,
in the dose applied per hectare, and sometimes in what they do.

A flow list that puts the plain common name on the relative is not making a
spelling mistake. It is making a claim about identity that its own registry number
denies, and — because correspondence tables and name matching both work on
names — every list downstream inherits it, including lists that had the pair
right.
