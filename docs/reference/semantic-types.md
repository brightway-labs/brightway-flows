# What kind of thing is this flow?

Every flow object carries `@type`: one or more ChemROF classes saying what the
substance *is*. The published export copies them onto each flow, so a consumer
can filter for "every monoatomic cation" or "every radionuclide" without
re-deriving it from formulas.

## How the class is chosen

From the chemistry — formula, charge, structure, registry identifiers, and the
contexts the substance is emitted to. Not from the label.

That distinction is the whole point. The typing this replaced ran a regex over
the preferred name and required the base element object to already exist, so
`Chloride`, `Sodium ion`, `Bromide ion`, `Fluoride Ion`, `Sulfide ion`,
`Lithium ion`, `Tin(2+)` and `Tin(IV)` went untyped — monoatomic ions by any
reading — while five objects carrying no charge at all were typed
`MonoatomicIon`.

The rules run in order, and the first match wins:

| # | If | Class |
|---|---|---|
| 0c | its name is curated as an aggregate measurement | `brightway:AggregateMeasurement` |
| 1 | it has an isotope record | `Isotope`, plus `Radionuclide` when it decays |
| 2 | it is already an element from the periodic table | `ChemicalElement`, or an ion class if charged |
| 3 | one atom, non-zero charge | `AtomCation` / `AtomAnion` |
| 4 | several SMILES components | `ChemicalSalt` if any is charged, else `MolecularComplex` |
| 5 | several atoms, non-zero charge | `MolecularCation` / `MolecularAnion` |
| 6 | one structure, no net charge | `Allotrope`, `Zwitterion` or `NeutralMolecule` |
| 7 | every context it occurs in counts something other than chemistry | *none — see below* |
| 8 | its label names a class of substance | `MoleculeGroupingClass` / `AtomGroupingClass` |
| 9 | its contexts are resource only, and it has no structure | `Material` |
| 10 | it has a CAS or EC number but no structure | `ImpreciseChemicalMixture` |

Rule 0c is numbered where it is because it has to beat the chemistry rather
than follow them; see
[a measurement is not a substance](#a-measurement-is-not-a-substance) below.

Rule 10 is the UVCB rule. ChemROF defines `ImpreciseChemicalMixture` as "a
macroscopic polyatomic entity that consists of multiple chemical entities where
the stoichiometry is not known", which is the UVCB definition. It catches the
EC-inventory names — `Alcohols, C12-15, Ethoxylated`,
`Alkenes, C6-10, Hydroformylation Products, High-boiling`.

Rule 1 keys on the isotope record and never on the label, because `HCFC-123a`
has the same shape as `Americium-241` and is a molecule.

That puts the whole weight of rule 1 on the record being right, and for a long
time it was not: 37 of the 79 published nuclides carried an *isomer's*
half-life, decay mode and specific activity under a ground state's name.
Potassium-40 — the dominant natural-radioactivity flow in most inventories —
went out with a half-life of 336 nanoseconds against 1.25 billion years. See
[how a nuclide is identified](#how-a-nuclide-is-identified) below.

### Rule 8 reads two kinds of label, and trusts them differently

A label that says `unspecified` or `compounds` is settling the question itself:
`Aldehydes, Unspecified`, `Hydrocarbons (unspecified)`,
`Volatile Organic Compound`. Those hold whatever else is known about the object
— `Tributyltin Compounds` has an EC number for the category, and an authority
registering a category does not stop it being one.

A bare plural family noun is weaker. `Salts` and `Hydrocarbons` name a class in
`Hydrocarbons, Aromatic` and part of a substance name in
`Fatty Acids, Tallow, Zinc Salts`. Matching them unconditionally moves 39
EC-registered UVCBs out of `ImpreciseChemicalMixture` and calls them classes —
measured against the full build, not guessed. What separates the two is the
registry identifier: nobody registers "aromatic hydrocarbons". So the weaker
patterns apply only where rule 10 would find nothing, which is what makes the
wider net safe.

Rule 6 checks *allotrope before zwitterion*: ozone's canonical SMILES is
`[O-][O+]=O`, separated formal charges that net to zero, so the zwitterion test
matches it — and "a zwitterion of oxygen" is not a thing.

## Only the most specific class

`MolecularCation` implies `PolyatomicIon` implies `Molecule` in ChemROF, and a
reasoner derives the chain. Writing all three would be noise that can drift out
of step with the ontology, so only the leaf is emitted.

The one exception is a charged element, which gets both `FullySpecifiedAtom` and
its ion class — neither implies the other.

Abstract ChemROF classes are never emitted. `ChemicalEntity`,
`PolyatomicEntity`, `ChemicalMixture`, `PreciseChemicalMixture`,
`MoleculeByChargeState` and `ChemicalGroupingClass` are all abstract;
instantiating one is a modelling error.

## Why elements are `ChemicalElement`

`FullySpecifiedAtom` requires atomic number, charge **and** neutron number to be
stated. This project's element objects take their neutron number from the most
abundant isotope — an approximation, not a statement — and their charge from a
default of zero. Neither is specified in the sense the class means.

`ChemicalElement` is "generic form of an atom, with unspecified neutron or
charge", which is exactly what they are. Two things follow:

- **`chemrof:neutron_number` and `chemrof:elemental_charge` are no longer
  written on an element.** Stating either contradicts the class. Both values
  survive in the untyped `properties.element` bag, which is the periodic-table
  row and where an approximation belongs.
- **A charged element is *only* an ion.** `ChemicalElement` and a charge state
  are mutually exclusive, where `FullySpecifiedAtom` and an ion class could both
  be emitted — which was only possible because the first was claiming something
  untrue.

`chemrof:symbol`, which `ChemicalElement` declares, is written now that there is
a class to hang it on.

## A grouping class is still a flow object

`Aldehydes, Unspecified` names a category of substance rather than a substance,
and `MoleculeGroupingClass` says so. That is a statement about what it is, not a
licence to model it differently.

It keeps its `flow_object_id`, its registry identifiers and its elementary
flows, and it is published as a `skos:Concept` like every other flow. The source
lists emit against these rows and LCIA methods characterise them; the harmonised
list has to carry them. Typing them is not a reason to drop them.

## A measurement is not a substance

`Chemical Oxygen Demand` is the mass of oxygen a laboratory's oxidant would
consume in breaking down everything organic in a sample. The oxygen is not in
the discharge. `Benzene (as BTEX)` is benzene, toluene, ethylbenzene and xylene
weighed together and reported as though the whole of it were benzene.
`Particles (PM2.5)` is everything below an aerodynamic diameter, of any
composition. None of them names a chemical entity, and every one arrives in a
list of substances looking like one.

They are typed **`brightway:AggregateMeasurement`** — the one class this project
mints rather than borrows.

### Why a class and not a recorded reason

Leaving them untyped was the previous answer, and it published nothing. A
consumer filtering for chemistry cannot exclude a row whose only statement is an
absence, and being excluded from a query for substances is the single thing
these rows most need said about them.

It was also not stable. Two of the six names in
[#68](https://github.com/brightway-labs/brightway-flows/issues/68) had
already been typed as substances by rules that read a registry number, on the
2026-08-13 build:

| Object | Was typed | From |
|---|---|---|
| `Acid (as H+)` | `NeutralMolecule`, with the hydron's formula, SMILES, InChI, InChIKey, two masses and an IUPAC name, over 12 elementary flows | CAS 12408-02-5 |
| `COD, Chemical Oxygen Demand` | `ImpreciseChemicalMixture` | CAS 17612-50-9, which names no compound |
| `Acidity, Unspecified` | `MoleculeGroupingClass` | the `, Unspecified` in its label |
| `Nitrogenous Matter (unspecified, As N)` | `MoleculeGroupingClass` | the same |

An outcome a rule can silently overwrite is not a decision.

### Why not `ImpreciseChemicalMixture`

It is the nearest ChemROF class and it does not fit. ChemROF defines it as *a
macroscopic polyatomic entity that consists of multiple chemical entities where
the stoichiometry is not specified* — coal, tea tree oil, toothpaste. A portion
of matter you could hold. A kilogram of chemical oxygen demand is not one, and
neither is a kilogram of acidity. Nothing in ChemROF's 137 classes describes a
quantity whose definition is the procedure that produces it, which is why this
one is minted; see [the JSON-LD reference](jsonld.md#a-class-of-our-own).

One of them genuinely *is* a mixture: BTEX is four compounds in unstated
proportions, really present in the discharge. It is still typed a measurement,
because what the row reports is a number rebased onto benzene, and calling it a
mixture would leave the label's claim to be benzene unanswered.

### Curated, never matched

Which names are such a quantity is stated in
`src/brightway_flows/data/aggregate-measurements.json`, one entry per
quantity with its definition and the reason beside it. The regex this replaced
read `oxygen demand`, `, total` and `^particles` out of labels, and a pattern of
that kind is a guess that gets more expensive with every list added:
`Alkoxylation Reaction Product of Glycerin as Starter` is a molecule and
`Occup. as Forest Land` is land use, and both would answer an `X as Y` rule.

Names match case- and whitespace-insensitively — BAFU writes `as Cl` where the
preferred label reads `As Cl` — against the preferred label first and the
alternative labels second, so a curator can write the name the source uses.
Matching is exact after normalisation and never containment: `Benzene` must not
match `Benzene (as BTEX)`. Which label matched is recorded on the object, and a
match through an alternative label is worth a look — it means the row is
published under a name the file does not list.

### The identity comes off in the same pass

A class alone would leave a row typed as a measurement while still carrying the
registry number and structure that made it look like a substance — a record
contradicting itself. So the same pass withdraws both.

The registry number is **withdrawn rather than corrected**, which is what
[#57](https://github.com/brightway-labs/brightway-flows/issues/57) decided
for organic-bound nitrogen: a registry number names one compound, this is a
quantity over many, and there is no right number to put in its place. Leaving it
is not neutral. A shared registry number is this project's proof of shared
identity, so a number on one of these rows is a merge waiting for a substance to
claim it — which is exactly what fused organic-bound nitrogen with the
nitrogen-gas rows and renamed them all `Dinitrogen`.

Every withdrawn number is **named** on the object under
`created_from.aggregate_measurement`, not merely counted: a number nobody can
see was removed is one nobody can check.

### What the number is expressed as, as a link

The relation between `Benzene (as BTEX)` and benzene is real, and the whole
problem is that matching them would state it as identity. Two minted properties
state it as a link instead:

| Predicate | Says | On AOX |
|---|---|---|
| `brightway:expressedAs` | the substance the mass is reported in terms of | `Chlorine` |
| `brightway:sumsOver` | the grouping class whose members it counts | `Adsorbable Organic Halogen Compounds` |

AOX is the case with both, and they are different objects: EF's `Adsorbable
Organic Halogen Compounds` is a class of molecules, correctly typed
`MoleculeGroupingClass`; BAFU's `AOX, Adsorbable Organic Halogen as Cl` is those
molecules weighed as chlorine, so bromine and iodine in the sample are counted
at chlorine's atomic weight. Nothing in the published list said how the two
relate.

Both are optional, and three outcomes are recorded rather than two:

- **stated and resolved** — the flow-object IRI, as a node reference.
- **`unstated`** — the file names none. Acidity is the case: its proton is not
  the element hydrogen, and naming the wrong thing is worse than naming nothing.
- **`unresolved:<label>`** — the file names one the list does not carry.
  `Nitrogen, Total (excluding N2)` is expressed as nitrogen and the list has
  `Dinitrogen` but no elemental `Nitrogen` object.

Only the third is a defect, which is why it is not collapsed into the second. A
label two flow objects share resolves to neither — eleven preferred labels are
duplicated in the current build — because a link to an arbitrary one of two
substances is worse than no link.

### Why merging BTEX into benzene is not an option

It is worth stating separately, because it is the reading a merge rule would
reach for. BAFU carries `Benzene (as BTEX)` in 8 datasets. All 8 also carry
plain `Benzene`, `Toluene`, `Benzene, ethyl-`, `Xylene`, `m-Xylene` and
`o-Xylene` — and the benzene row is in the same compartment, `emissions to water
/ unspecified`. Merging the two would sum benzene with a total that already
contains it, in one process, in one compartment.

The identity cost is the larger one. Benzene's flow object carries 71
characterisation factors, and benzene is the IARC Group 1 carcinogen of the
four where toluene and the xylenes are not; those factors would then multiply a
mass that is mostly not benzene. After the merge nothing distinguishes the rows
that were totals.

Nothing was holding the row apart: it has no CAS and its name is not `Benzene`,
so no rule reached it. That is an accident rather than a decision, and a name
mapping or a CAS in a later BAFU release would have ended it.

### Why COD, BOD5 and TOC *are* merged

The opposite case, and worth stating beside it. Three of these quantities were
published twice, once by each list:

| BAFU | EF 3.1 |
|---|---|
| `COD, Chemical Oxygen Demand` | `chemical oxygen demand` |
| `BOD5, Biological Oxygen Demand` | `biological oxygen demand` |
| `TOC, Total Organic Carbon` | `total organic carbon` |

Unlike BTEX and benzene, these pairs are one quantity. Chemical oxygen demand
is the mass of oxygen one procedure consumes; there is no sense in which
BAFU's is a different number from EF's, and the whole of the difference between
the rows is the abbreviation in front of the name.

Nothing could have brought them together on its own. Neither row carries a
registry number the other shares, and BAFU has no prepared match table, so the
merge has only the names — and two strings that differ are two substances.
`DOC, Dissolved Organic Carbon` is the proof that this was spelling and not
judgement: BAFU ships it too, it lands on EF's flow object today, and it does so
for no better reason than that EF happens to ship the prefixed spelling itself.

The fix is three entries in `bafu-2026-v1-manual-fixes.json` that add EF's
spelling to each row's **synonyms** — not a rule, and not a rename.
`bootstrap_labels` reads a row's shipped name and synonyms when it is matched
and then purges both, so the added string is read by the merge and published
nowhere: BAFU keeps its own spelling in `source_refs`, and EF's flow object
gains no alternative label from it. Renaming the rows would have put EF's
spelling into the published record as though BAFU had used it.

Two of BAFU's water subcompartments, `river` and `groundwater`, are ones EF does
not carry for these quantities. Their flows are created under the shared flow
object rather than under one of their own, which is the point of merging.

COD's CAS 17612-50-9 is deliberately left on the row. It names no compound and
is withdrawn — but on the object, in the pass above, where the withdrawal is
recorded and the number named. Removing it at the source would pre-empt that and
leave no trace of a number the list really did carry. It cannot affect the match
either way, because EF's flow object has no registry number to disagree with it.

`aggregate-measurements.json` goes on listing both spellings for each of the
three. Once the lists merge, only EF's matches anything; the other is kept
because it names what a source really ships, and a list arriving later with the
abbreviated spelling and no fix should still be typed.

## Untyped is a decision, not a silence

Every object gets an outcome. Where no class applies, the reason is recorded on
the object under `created_from.semantic_typing.reason`, and the run reports the
tally.

| Reason | What it means |
|---|---|
| `land_use_not_a_chemical_entity` | `Arable, Irrigated`, `Agriculture, Mosaic` — 226 objects that are land-use classes. |
| `inventory_indicator_not_a_chemical_entity` | `Exported Energy - Heat`, `Materials For Recycling`, `Hazardous Waste Disposed` — 15 objects. |
| `economic_not_a_chemical_entity` | `Labour Cost`, `Net Tax`, `Rent`, `Net Operating Surplus` — 5 objects. |
| `not_a_chemical_entity` | The flow occurs in two of those dimensions, so no one of them is to blame. |
| `delayed_emission_correction_not_a_substance` | EF 3.1's six `Correction flow for delayed emission of …` objects — an accounting device measured in kg·a, a mass held for a time rather than a substance ([#43](https://github.com/brightway-labs/brightway-flows/issues/43)). |
| `no_structure_and_no_registry_identifier` | The identity is too thin to classify: no formula, no structure, no CAS, no EC. 20 objects on the run of 18 August 2026, and only one of them carries a characterisation factor ([#19](https://github.com/brightway-labs/brightway-flows/issues/19)). |

The first four come from the *context dimension*, not from the label. The
dimensions where a substance is not what is being counted are named in
`_NON_CHEMICAL_DIMENSIONS`, taken from
`domain.context.Dimension` so a dimension added there has to be placed on one
side of the line or the other. Land use was the only one named until now, and
`Labour Cost` fell through to "the identity is too thin to classify" — which is
untrue of rent. We can tell exactly what it is; it is not chemistry.

There used to be a fifth reason here, `aggregate_measurement_not_a_substance`,
read off the label by a regex and assigning no class. It is gone: those
quantities have a class now, and which names are one of them is curated rather
than matched. See below.

`delayed_emission_correction_not_a_substance` runs first instead, beside the
alpha-emitter rule and for the same reason: both objects arrive holding a
substance's structure, taken through a CAS number they share with it, so every
structural rule below would place them and place them wrongly. The two part
company on what to do next. A set of isotopes is a class over atoms, which
`AtomGroupingClass` says; nothing in ChemROF says "a mass held for a time", so
the correction is typed as nothing and the properties it inherited are
withdrawn — on both layers, since the published export projects the flow rather
than the object. What stays is its CAS and its `parent_flow_object_id`, which
say which substance the correction is *about*.

The elementary-flow layer is untyped for the same reason: a flow is an
occurrence, not a substance, and there is no verified class for one.

## Two SMILES slots, because ChemROF has two

`chemrof:smiles_string` is "a string encoding of a molecular graph, **no chiral
or isotopic information**". This project stored chiral SMILES in it —
`C[C@H]1CO[C@H]2CCCC2O1` — on 1,167 flow objects.

`chemrof:isomeric_smiles_string`, declared `is_a: smiles_string`, is the slot
for those, so the correction is a move rather than a new claim:

- the original string goes to `isomeric_smiles_string`
- `smiles_string` keeps the same structure with the stereochemistry and any
  isotopic label removed, **computed by RDKit** rather than by editing the
  string, so what is published there is a graph the project can stand behind

Charge survives the flattening and should: `[O-][O+]=O` is ozone's graph, not a
claim about its stereochemistry. Two stereoisomers that flatten to the same
graph leave one entry, not two.

A structure RDKit will not parse **moves too, and no graph is written for it**.
There is no graph-only form of a string that does not resolve to a molecule, and
a hand-stripped one would be a guess — but that is a reason to publish no graph,
not a reason to publish the stereochemistry as one, which is what leaving the
string in `smiles_string` did. ChEBI writes L-tryptophan's shape as `[C@@H]` and
its indole as `Cc1cnc2ccccc12` — an aromatic nitrogen carrying no hydrogen, so
the ring will not kekulise and RDKit rejects the whole string. It sat in the
graph slot, `[C@@H]` and all — 7 substances, 91 elementary flows, on the
2026-08-12 build
([#51](https://github.com/brightway-labs/brightway-flows/issues/51)). All
7 keep a readable graph from another source once the string moves; where an
unreadable string is a record's only value, `smiles_string` is withdrawn rather
than published empty.

Provenance follows the same rule. The graph slot names as its source only the
strings a graph was actually computed from, so a value RDKit could not read is
never recorded as something this project derived a structure from.

A run reports `objects_with_stereochemistry_in_smiles`, measured off the finished
records because what makes a value wrong is the name it is published under.
**That one has to be zero.**

Beside it is `flows_with_stereochemistry_in_smiles`, which has to be zero for the
same reason rather than for a second one: **a flow's `properties` are its
substance's**, deep-copied onto it once every correction has run over the
object. Before that they were the flow's own — what its sources wrote, from
before the layering merged them — so the split reached the substance and not its
flows: 8,542 published flows stated a shape in `smiles_string` and not one of
them carried an `isomeric_smiles_string`, on the same build where the object
figure was zero
([#53](https://github.com/brightway-labs/brightway-flows/issues/53)). The
two figures are now one measurement made twice, and they part company only if a
flow stops taking its chemistry from its substance.

## One structure, one value, whoever spelled it

A record collects its structures from ChEBI, PubChem, OPSIN, RDKit and — for a
flow object — every flow the layering merged into it, and each writes the
molecule the way its own toolkit spells it. A canonical SMILES is canonical *per
toolkit*: PubChem's OEChem writes camphor `CC1(C2CCC1(C(=O)C2)C)C` where RDKit
writes `CC12CCC(CC1=O)C2(C)C`. Nothing compared those as structures, so both
were stored — 5,708 redundant strings on 5,270 flow objects, and for 3,285 of
them the record had exactly one structure once the spellings were collapsed. It
was never structurally ambiguous; it only read that way (#22).

Two things now hold:

- **RDKit does not add a spelling of a structure the record already carries.**
  It records itself as a further source on the value that is there. What the
  source wrote is not rewritten.
- **Where two spellings of one structure reach a record anyway** — two sources
  spelling it differently, or the flattened form of a stereo string landing on a
  flat one a source supplied — they collapse to one value. This runs in the
  property normalisation, over flows and flow objects alike: the published
  export projects the flow and the review apps read the object, and the two
  disagreeing is how a fix reaches one and not the other.

**The surviving spelling is RDKit's canonical form.** Usually that form is
already one of the stored values, and the collapse only removes the other. Where
neither source wrote it, one spelling has to go regardless, and writing the
canonical form rather than picking a winner keeps the published string
consistent with every other structural property in the record, all of which are
RDKit-derived. A value nothing duplicates is never rewritten.

Stereochemistry is part of the structure for this purpose, so two stereoisomers
are two values in either slot. In `smiles_string` on a flow object the question
does not arise — the split above has already taken the stereochemistry off — and
on a flow it still can be there, where flattening it would be a loss rather than
a collapse. A string RDKit will not parse is never collapsed into anything:
having no canonical form is not the same as being the molecule next to it.

Provenance is unchanged by a collapse. It is recorded per property rather than
per value, so every source that attested to the structure is still named on the
property the spellings collapsed into.

A run reports `smiles_string_duplicate_spellings_collapsed` and its isomeric
counterpart, and — measured off the records afterwards rather than asserted by
the step that collapses — `objects_with_redundant_smiles` and
`flows_with_redundant_smiles`, which are the numbers that have to be zero.

## One substance, one key, at the specificity it is known to

`inchi2d_key_string` accumulates the same way, and the redundancy it collected is
not a second spelling. An InChIKey's first block hashes connectivity alone, so
taking the stereochemistry off a key changes only the second block:
`QIVBCDIJIAJPQS-VIFPVBQESA-N` is L-tryptophan and `QIVBCDIJIAJPQS-UHFFFAOYSA-N`
is the same skeleton with the layer that says which mirror image deleted. Both
sat in one slot, with nothing marking which was the substance and which the
simplification — and the flat one is `DL-tryptophan`'s real key, so a rule
merging substances that share an InChIKey fused two substances that are not the
same (#50). 419 flow objects, 5,416 elementary flows.

- **Every stage that writes the slot refuses the flat key** where the record
  already states a specific one for that skeleton, and withdraws a flat key
  already there when the specific one arrives second. Refusing at the write
  rather than sweeping afterwards keeps the value out of the stages that read
  the slot in between.
- **The property normalisation does it again** for records assembled where no
  stage runs: `merge.creations` writes flow objects into SQLite without going
  through the transform engine.

**Nothing is lost.** The dropped string is the surviving key with its second
block replaced by `UHFFFAOYSA`, so a consumer who wants the connectivity-only
form can write it out from what is published — no chemistry toolkit, no
structure, no lookup. A consumer asking whether two records share a skeleton
should compare the first block, which is what `same_skeleton` does.

**The grouping is per skeleton, not per record.** A record can hold keys for more
than one skeleton, and the second is usually a wrong hit (#6, #38): `D-menthol`
carries its own key, that key's flat form, and `TWDOPJXHIBEHIL-UHFFFAOYSA-N`,
a different chemical altogether. The first flat key is a simplification of
something the record already states and goes; the second is the only evidence
that the wrong structure is there and stays. 47 of the 474 flat keys were the
second kind. A substance registered without stereochemistry keeps its flat key
for the same reason — it is the only key it has.

A run reports `inchikeys_redundant_flat_dropped`, and — measured off the records
afterwards — `objects_with_redundant_flat_inchikey` and
`flows_with_redundant_flat_inchikey`, which are the numbers that have to be zero.

## How a nuclide is identified

A nuclide is fixed by three values: which element, how many nucleons, and which
nuclear state. `Uranium-238` and `Uranium-238m` are different nuclides — 4.5
billion years against 280 nanoseconds — and everything about matching them turns
on that being expressible.

It was not. A nuclide row was found by looking its *name* up in a dictionary
built from every spelling the row might go by: `238U`, `U238`, `U-238`,
`Uranium-238`, `Uranium 238`, and eight more. An isomer and its ground state
differ in exactly one of those and share the rest, so `238Um` claimed
`Uranium-238` as well, the assignment overwrote, and whichever row PubChem
listed last won the ground state's name. Nothing recorded that a choice had been
made — `matched_on` said the label matched, and it had.

Matching is now on the triple. The consequences of the old form, all of them
measured on a full build:

- **37 of 79 nuclides carried an isomer's record.** Potassium-40 at 336 ns,
  Uranium-238 at 280 ns, Neptunium-237 at 710 ns, Technetium-99 at 6 hours
  against 211,000 years. `specific_activity_bq_per_g` is derived from the same
  row, and that is the number a consumer needs to convert a kBq flow to mass.
- **Four nuclide records were published twice**, once under a ground state's
  name and once under its isomer's, so `Technetium-99` and `Technetium-99m` were
  indistinguishable in the artifact.
- **Nine objects published a `chemrof:symbol` that is not an element symbol.**
  Where the symbol ended in `238Um` was guessed from the trailing letters, which
  reads `147Pm` as phosphorus, `54Mn` as an element `M`, and `122Sbp` as one
  called `Sbp`. The caller always knows the element, so the symbol is data and
  the boundary was never in question.

The element names and symbols are a literal table in `domain.nuclides`, checked
against the PubChem cache by a test. That is what makes the parsing a pure
function, and what lets a name whose first token is not an element name — a
refrigerant code, a sodium salt — be rejected for free.

### What a record has to satisfy before it is published

Rule 1 fires on the presence of an isotope record, so a record that contradicts
itself would type the object `Isotope` and hang wrong values off it. Two checks
run first, and their outcome is recorded on the object under
`properties.isotope_lookup.checks` whether they pass or fail:

| Check | Why |
|---|---|
| `ground_state_does_not_decay_by_isomeric_transition` | Isomeric transition is the fall from an excited state, so a ground state has nothing to fall from. 31 objects published it. |
| `half_life_sources_agree` | PubChem and ChemLIN answer separately for the same nuclide, within a factor of two. 14 objects disagreed by up to eight orders of magnitude while both were reported as matched. |

A record that fails is **not written**. The object stays untyped, and
`isotope_lookup.reason` names the check — which is worse for a consumer than a
right answer and much better than a wrong one.

A lookup that finds nothing is recorded the same way, and the reason
distinguishes the two cases that matter:

| Reason | What it means |
|---|---|
| `label_is_not_a_nuclide_name` | An aggregate or an element — `Radioactive Species, Alpha Emitters`, `Thorium`. The expected outcome, and not a defect. |
| `no_row_for_isomeric_state` | The mass number exists for that element in some other state. This project will not guess which. |
| `no_nuclide_at_that_mass_number` | The element name is wrong. `Palladium-234m` is protactinium-234m: palladium is atomic number 46 and stops at about mass 128, so no such nuclide exists ([#20](https://github.com/brightway-labs/brightway-flows/issues/20)). Corrected in `ef-3.1-manual-fixes.json`. |

The last one is the point of splitting them. `matched: false` was the whole
record before, and nothing read it.

## Nuclide properties

The isotope enrichment has long collected `mass_number`, `symbol`,
`decay_modes`, half-life and specific activity into an untyped bag. Three of
those have declared ChemROF slots and now use them:

- `chemrof:nucleon_number` ← `mass_number`
- `chemrof:symbol` ← `symbol`
- `chemrof:decay_mode` ← `decay_modes`

The bag stays: it still holds specific activity, discovery year and the ChemLIN
URL, none of which have a slot.

**`chemrof:half_life` is published as a float, against its declared range.**
ChemROF gives the slot the range `NumberOfYears`, defined as `xsd:int`.
Americium-241's half-life is 432.6 years and Krypton-85's is 10.7; no integer is
either value. The three options were a wrong number, no number, or a float the
range does not permit — and only the float tells the truth, so that is what is
published, with `qudt:hasUnit` naming years explicitly. Reported upstream.

A stable nuclide gets no `half_life` at all: infinity is not a number JSON
carries, and "does not decay" is better said by the absence of a value than by
one nothing can compare. The exact source string, with the uncertainty the float
drops, stays in `properties.isotope`.

## `has_element`

The link from an ion or isotope to its element was
`properties.relationships.parent_element_flow_object_id` with
`relationship_type: "ion_of"` — a home-grown pair of strings for a relation
ChemROF declares on exactly the two classes that need it. It is now
`chemrof:has_element`.

The value is a node reference over a minted flow-object IRI:

```json
"https://w3id.org/chemrof/has_element": {
  "@id": "https://vocab.brightway.dev/flow-objects/fo-0bfffb5e4dadc218"
}
```

It was the bare `flow_object_id`, which the export flattens to the string
`"fo-0bfffb5e4dadc218"` — a literal against a slot whose range is a class, and
nothing a consumer can follow. Minting the namespace was the decision
[#8](https://github.com/brightway-labs/brightway-flows/issues/8) left
open; see [the JSON-LD reference](jsonld.md) for why the target being
unpublished does not block it.

ChemROF gives `has_element` the range `ChemicalElement`, and that is now what
the element objects are, so the range holds.

A range is only satisfied if the target exists. Americium, Neptunium,
Promethium and Technetium appear in both source lists only as nuclides — there
is no `Americium` flow — so five isotope objects had nothing to point at. The
element enrichment mints those four, which makes them the first flow objects
with no elementary flows; see
[Known limitations](limitations.md#four-flow-objects-have-no-elementary-flows).
An element is minted only where the list already carries its isotopes.

Where the link still cannot be made, `relationships.unresolved_reason` says so
rather than the key being absent, and the run counts it as
`isotope_unlinked_element_count`.

The `relationships` bag is left in place; the substance page reads it.

## The type filter

`flow_objects.flow_type` in SQLite holds one value per object so `/flows` and
`/flow-objects` can group by it. It is the most specific class IRI, and the filter options are
generated from the term registry rather than written out — the hand-written list
it replaced offered five options, of which `"consensus"` matched 98.6% of
objects and named nothing.

One value in that column is not a ChemROF class, and is marked as such by not
being an IRI: `unclassified`, for an object the rules could not place.

One more is an IRI and is not ChemROF's: `brightway:AggregateMeasurement`. That
it appears in the same facet as the chemical classes is deliberate — a filter
offering only chemistry could not express "this row is not chemistry", which is
what a consumer looking at `Chemical Oxygen Demand` needs to be told.

### The origin qualifier is a second axis, not a value of this one

`OriginQualifiedSubstance` used to be a second such value, for the
biogenic/fossil/land-use-change split. It answered the type question with the
origin one, and it was answering for an object that *has* a type: 10 of the 14
qualified substances carry the same ChemROF class as the substance they were
split from.

| object | qualifier | type |
|---|---|---|
| Carbon Dioxide | — | `NeutralMolecule` |
| Carbon Dioxide (biogenic) | `biogenic` | `NeutralMolecule` |
| Carbon Dioxide (fossil) | `fossil` | `NeutralMolecule` |
| Carbon Dioxide (land Use Change) | `land_use_change` | `NeutralMolecule` |

That is not a gap in the typing. Biogenic CO₂ *is* a neutral molecule, and where
the inherited chemistry is genuinely wrong — the alpha-emitter aggregates, which
arrive carrying an element's formula and mass for a set of isotopes — rule 0
already corrects it. Origin is orthogonal: it says where the carbon came from,
not what it is.

So `flow_objects.origin_qualifier` is its own filter on `/flows` and
`/flow-objects` (`?qualifier=biogenic`), and it is shown on the flow page beside
the type. An object that no rule could type and that carries a qualifier now
reports both facts instead of one.

### Both facets are counted in flows

`filter_option_counts` carries a `type` and a `qualifier` group, counted in
elementary flows like every other option on `/flows`. Grouping `flow_objects`
directly is cheaper and answers a different question — it offered
`biogenic (4)`, the substances, above a result of 28 flows.

Counting them in flows needs the join, and `flow_type` and `origin_qualifier`
are declared after `flow_object_json`, so reading either off a row steps over a
multi-kilobyte blob. `idx_flow_objects_facets` covers both columns: the
build-time `GROUP BY` goes from 652 ms to 116 ms and the cheap
`flow_objects`-only form from 54 ms to 1.3 ms, for 0.5 MB.

A database written before either existed still works. Its facet options fall
back to substance counts and say so — `biogenic (4 substances)` — because the
webapp's connection is `mode=ro` with `PRAGMA query_only` and cannot add the
index it would need to do better. A rebuild replaces them.
