# Flow objects and elementary flows

The consensus list is built from two linked layers. Almost every question about
the data resolves to "which layer does this belong to?", so it is worth getting
straight before anything else.

| | **Flow object** | **Elementary flow** |
|---|---|---|
| Answers | *What is this substance?* | *Where and how does it appear in inventories?* |
| Identifier | `flow_object_id`, e.g. `fo-a1b2c3d4e5f60718` | `elementary_flow_id` (a UUID) |
| Carries | names, synonyms, CAS/EC, formula, mass, structure, definition, typing | context, unit, LCIA methods, source references |
| One per | substance | substance **×** context |
| Table | `flow_objects` | `elementary_flows` |

The relationship is **many elementary flows to one flow object**. Every
elementary flow points at exactly one flow object; a flow object may have any
number of elementary flows hanging off it — including none.

Four do. Americium, Neptunium, Promethium and Technetium appear in both source
lists only as nuclides, and `chemrof:has_element` needs an object for the
element to point at, so those four are minted with no flows of their own. That
is the split doing its job rather than a gap in it: the list has americium as a
substance without having an occurrence of americium, and both layers publish as
`skos:Concept`. Code that joins the two layers should use an outer join.

## Why split them

Consider lead. It appears in inventories as an emission to urban air, an
emission to surface water, and an extraction from ground — in EF 3.1, in
ecoinvent, and in SimaPro, each with slightly different names and compartment
strings.

The chemistry of lead does not change across those rows. Its CAS number
(7439-92-1), atomic number (82), and molecular mass are properties of the
element, not of the emission event. If those facts were stored per row, then:

- correcting one of them would mean correcting it in a dozen places, and the
  copies would drift;
- there would be no way to state that all twelve rows are the same substance,
  which is exactly the statement a harmonised list exists to make.

Storing identity once and referencing it from each occurrence makes the
statement explicit and keeps it consistent by construction.

```
                    flow object  fo-…  "Lead"
                    CAS 7439-92-1 · Pb · Z=82 · 207.2 g/mol
                          ▲       ▲        ▲        ▲
              ┌───────────┘       │        │        └───────────┐
     elementary flow      elementary flow  elementary flow   elementary flow
     Air / ground level   Water / surface  Air / ground lvl   Resource / ground
     / urban             water            / rural
     unit: kg            unit: kg         unit: kg           unit: kg
     src: EF 3.1         src: EF 3.1      src: ecoinvent     src: ecoinvent
```

## What lives on a flow object

Everything that is true of the substance regardless of where it was emitted:

- `prefLabel` — the preferred name, one per language
- `altLabel` — synonyms
- `properties` — molecular formula, mass, charge, atomic number, SMILES, InChI,
  InChIKey, IUPAC name
- `references` — links to ChEBI, PubChem, Wikidata, and other databases
- `classifications` — CAS, EC, KEGG, Gmelin registry numbers
- `skos:definition` — a prose definition
- `@type` — semantic typing: `chemrof:NeutralMolecule`, `chemrof:AtomCation`,
  `chemrof:Radionuclide`, `chemrof:ImpreciseChemicalMixture` for a UVCB, and so
  on, derived from the chemistry rather than from the name. See
  [What kind of thing is this flow?](../reference/semantic-types.md)
- `created_from` — how this object was assembled

## What lives on an elementary flow

Everything that depends on the occurrence:

- `context` and `context_iri` — the compartment, in the consensus vocabulary
- `unit` and `unit_iri`
- `lcia_methods` — characterisation factors carried from the source list, each with the place it applies to where the source names one
- `source_refs` — one entry per source flow that contributed to this row
- `concept_associations` — links to the equivalent flow in EF 3.1, SimaPro, etc.
- `general_comment` — free text from the source list
- deprecation status, if this row has been superseded

!!! note "The published flow also carries its substance's chemistry"

    `harmonised-flows-simple.json.gz` publishes flows and only flows — there are
    no substance records in it and no `flow_object_id` on a flow to look one up
    with — so the substance's `properties`, labels, references and classes have
    to travel with the flow or a consumer of that file cannot reach them at all.
    They are **derived from the flow object**, deep-copied onto each of its flows
    after every correction has run over the substance, so the two layers cannot
    state different chemistry for one substance. Until #53 the flow answered for
    itself, with the properties its sources wrote before the layering: 8,542
    published flows stated a stereochemistry in `smiles_string`, which is defined
    as carrying none, while their substances stated it correctly.

    In the database this copy is stored once per substance, in
    `flow_object_payloads`, and folded back into each flow on the way out — see
    [File schemas](../reference/schemas.md).

!!! note "`source_refs` is not in any JSON"

    Elementary flows carry it in memory, but the writers of
    the published export strips it, and no stored payload
    keeps it either — not `flow_json`, since the merge appends a matched flow's
    new reference to the table and to nothing else (#30). To read source
    references, use the `elementary_flow_sources` table in
    `consensus-flows.sqlite3`, or the merge report for merged flows. See
    [Known limitations](../reference/limitations.md).

**The core invariant:** `(flow_object_id, context_iri)` is unique across all
non-deprecated elementary flows. There is exactly one row for "lead to urban
ground-level air", no matter how many source lists supplied one.

## When two similar substances stay apart

Some substances share a CAS number but must not share a flow object, because
downstream methods treat them differently. The pipeline detects these from the
flow name and splits them into separate flow objects, each tagged with an
`origin_qualifier` and pointing back to the undifferentiated base substance via
`parent_flow_object_id`. Both halves reach the published export, as
`brightway:originQualifier` and `brightway:baseSubstance` — see
[JSON-LD](../reference/jsonld.md).

| `origin_qualifier` | Triggered by | Why it must stay separate |
|---|---|---|
| `biogenic_delayed_emission_correction` | "delayed emission" + "biogenic" | An accounting flow in kg·a, not the substance |
| `fossil_delayed_emission_correction` | "delayed emission" + "fossil" | An accounting flow in kg·a, not the substance |
| `delayed_emission_correction` | "delayed emission" | An accounting flow in kg·a, not the substance |
| `land_use_change` | "land use", "land-use" | Different carbon accounting |
| `biogenic_resource_correction` | "resource correction" | Distinct from ordinary biogenic CO₂ |
| `biogenic_100yr` | "biogenic-100yr" | Uptake credited under a 100-year horizon — an accounting variant, not ordinary uptake |
| `biogenic` | "biogenic", "non-fossil", "non fossil" | Contemporary vs. geological carbon |
| `fossil` | "fossil", not preceded by "non" | Contemporary vs. geological carbon |
| `grey_water` | "grey water" / "gray water" | Water-footprint methods |
| `blue_water` | "blue water" | Water-footprint methods |
| `green_water` | "green water" | Water-footprint methods |
| `alpha_emitters` | a trailing "alpha" (`Plutonium-alpha`) | A set of isotopes reported as activity, not the element |

The table is in precedence order: a name matching more than one qualifier takes
the first match. `non-fossil` is treated as a synonym for `biogenic` — both mean
carbon from the contemporary biosphere — unless "resource correction" also
appears, which is more specific and wins. The delayed-emission checks come
first for the same reason: "Correction flow for delayed emission of fossil
methane" is also a `fossil` match, and reading that word first put the
correction flow on the `Methane (fossil)` object rather than on its own.

The three delayed-emission qualifiers are one qualifier per carbon origin
because the corrections share their base substance's CAS: the fossil and the
biogenic correction for carbon dioxide are both 124-38-9, so a single qualifier
would group them by `(qualifier, CAS)` back onto one object.

Qualified flows are grouped by `(qualifier, CAS numbers)` rather than by CAS
alone, so `Carbon dioxide, fossil` and `Carbon dioxide, biogenic` get distinct
flow objects despite sharing CAS 124-38-9.

### A flow that is not a substance at all

Six BAFU flows count traffic noise: sound from an aircraft, a lorry, a passenger
car, a freight train and a passenger train, filed under a compartment BAFU calls
`non material emissions` and measured per person-kilometre or per
tonne-kilometre. Noise is a real environmental burden and methods characterise
it, but it has no formula, no mass and no registry number, because it is not
matter.

Each of the six keeps its own flow object — they differ in unit and in
characterisation factors — and all six point at a seventh, `Noise`, which no
source list carries and this project mints. The link is
`brightway:baseIntervention` rather than `baseSubstance`: a noise flow has no
base substance, and saying it did would publish exactly the claim these flows
cannot support.

Which flows are candidates is decided by the context, not by the name: every
flow whose contexts *all* count something other than a substance, which today
means `Environmental → Other`. Which family a candidate joins is declared in
`data/non-material-interventions.json`. A candidate no family claims is counted
by the run and left alone, so a second kind of non-material flow arriving is a
decision someone makes rather than a default it inherits.

### A nuclide is grouped by its nuclide

A flow whose name is exactly a nuclide — `Uranium-238`, `Technetium-99m` — is
grouped by that nuclide rather than by its CAS number, for the same reason the
qualifiers exist: the CAS is not wrong, it is simply not this flow's identity.

A CAS registry number identifies a *substance*, and the source lists do not
agree on what that means for a nuclide. Technetium-99 and Technetium-99m have
their own numbers and separated cleanly. But EF 3.1 and ecoinvent both ship
`uranium-238`, `thorium-232` and `Praseodym-147` carrying the **element's**
number — `7440-61-1` is uranium; U-238's own is `24678-82-8` — so the CAS merged
each of them into the element. One flow object then stood for two substances:
uranium ore, measured in kg and MJ, resolved to an object labelled
`Uranium-238`, typed `chemrof:Isotope`, carrying a nucleon number, a half-life
and a decay mode. Elemental uranium had no flow object at all, so the three
uranium isotopes had no element to link to, and the alpha-emitter aggregate was
recorded as a child of U-238 rather than of uranium
([#17](https://github.com/brightway-labs/brightway-flows/issues/17)).

The key is the triple that actually distinguishes nuclides: element, nucleon
count, and nuclear state. It is derived from the published label and from
nothing else, so this pass and the isotope enrichment cannot disagree about
which flows are nuclides.

Deliberately narrow. `Thorium` and `Plutonium` are element names, not nuclide
names, and keep their CAS key — which is what separates an element from its own
isotopes rather than what merges them. A name that merely has the shape,
`HCFC-123a`, is not a nuclide either: the first token has to be an element name,
and that is a closed set.

The CAS stays on the object, where a consumer can still read it. It stops
deciding what the object is.

The reverse case also matters. `carbon dioxide (biogenic-100yr)` and `Correction
flow for delayed emission of biogenic carbon dioxide (within first 100 years)`
share both CAS and qualifier, so they collapse into one biogenic flow object and
the longer name becomes a synonym — the shorter preferred name wins.

## When a row is deprecated instead of deleted

If two elementary flows end up with the same `(flow_object_id, context_iri)`
signature — usually because two source lists supplied the same thing — one is
kept active and the other is marked deprecated with a pointer to its
replacement:

- `owl:deprecated: true`
- `dcterms:isReplacedBy` — the IRI of the surviving row

Nothing is deleted. The deprecated row keeps its own source references, so a
consumer holding the old identifier can still resolve it, and a reviewer can
still see what was merged into what. Deprecated flows are excluded from the
simplified published export but present on the `ElementaryFlow` record in
`elementary_flows.elementary_flow_json`.

## Reading both layers when debugging

Data problems almost always present at one layer and originate at the other. A
practical order:

1. **Look at the flow object first.** Wrong synonyms, a wrong formula, or a
   suspicious mixture of unrelated names mean an identity-resolution problem —
   see [what a name that belongs to something else does](../deciding/synonyms.md).
2. **Then look at the linked elementary flows.** A missing row, a wrong context,
   or an unexpected deprecation is a context-mapping or merge problem.
3. **Then read the source references** for that flow — from the
   `elementary_flow_sources` SQLite table, not the JSON — to see which source
   rows were folded together, under their original names and compartments.

Both layers are browsable: `/flow-objects` and `/flows` in
[the review application](../operating/review-app.md), which cross-links them —
every flow names its substance, and every substance lists the flows that
resolve to it.
