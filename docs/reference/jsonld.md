# The published export as JSON-LD

`harmonised-flows-simple.json.gz` is a JSON-LD document. It carries an
`@context`, every flow carries an `@id`, and the numeric properties are numbers.
Expanding it with any conformant processor yields triples.

```python
import gzip, json
from pyld import jsonld

document = json.loads(gzip.decompress(open("harmonised-flows-simple.json.gz", "rb").read()))
triples = jsonld.expand(document)
```

Nothing is fetched over the network: the context is inline.

## What the context does

It is generated from the term registry in
`brightway_flows/domain/vocabulary.py`, never hand-maintained, so a term
cannot be published without being declared. Three kinds of entry:

| Kind | Example | Why |
|---|---|---|
| Namespace prefix | `"chemrof": "https://w3id.org/chemrof/"` | Expands the CURIEs already used inside `concept_associations` and `provenance` |
| Term | `"smiles_string": "https://w3id.org/chemrof/smiles_string"` | The short name used in code |
| Typed term | `"molecular_mass": {"@id": …, "@type": "xsd:double"}` | ChemROF declares the slot's range; the context repeats it |

Two entries carry the shape of the file rather than a predicate:

- **`"flows": "@graph"`** — the export is a list of nodes, which is what a graph
  container is. Aliasing avoids minting a predicate for it.
- **`"properties": "@nest"`** — the nesting is a convenience of the file format,
  not a claim about the substance. `molecular_formula` is a property *of the
  flow*, not of some intermediate "properties" resource, and `@nest` says
  exactly that. It requires `"@version": 1.1`, which the context declares.

## Datatypes

Every ChemROF slot declares a range. Until schema version 3 all of them were
published as strings — `"398.54"`, `"0"` — so a consumer could not sort by mass
or filter by charge without re-parsing. They are now JSON numbers.

A value that will not parse is **kept as it is**, not dropped. The source lists
contain ranges and approximations (`"approx. 400"`), and publishing them
untyped is more honest than publishing nothing. The run logs how many of each it
saw under `normalised_semantic_properties`.

## Charge

ChemROF scopes `formal_charge` to `AtomOccurrence` — "the charge remaining on an
atom when all ligands are removed homolytically". It is one atom's charge inside
a molecule, not the molecule's.

The net charge of a chemical entity is **`elemental_charge`**, whose declared
domain is `ChemicalEntity`. Everything that used to be published as
`chemrof:formal_charge` is now `chemrof:elemental_charge`. A moved value keeps
its original `prov:hadPrimarySource` and `prov:wasDerivedFrom`, so its lineage
back to PubChem or ChEBI survives the move.

## Six predicates this project defines

Everything else in the context is borrowed. These six are ours, under
`https://vocab.brightway.one/terms/`:

| Term | On | Points at |
|---|---|---|
| `brightway:flowContext` | an elementary flow | a flow-context IRI |
| `brightway:originQualifier` | an elementary flow | an origin-qualifier IRI |
| `brightway:baseSubstance` | an origin-qualified flow | a flow-object IRI |
| `brightway:baseIntervention` | a non-material flow | a flow-object IRI |
| `brightway:expressedAs` | an aggregate measurement | a flow-object IRI |
| `brightway:sumsOver` | an aggregate measurement | a flow-object IRI |

They were minted because nothing published provides them and the cost of doing
without had become concrete. `context_iri` — the compartment, the field an LCA
practitioner filters on first — was the one thing in the export contributing no
triples at all. `origin_qualifier` is the biogenic/fossil/land-use-change split:
an LCA distinction with no equivalent in any chemical ontology, because it is
about where a substance came from rather than what it is, and the only published
trace of it was the preferred label.

The qualifier's *values* are minted too, under
`https://vocab.brightway.one/origin-qualifiers/`, so a qualifier is a concept
rather than a bare string. The local names are the entries of
`qualifiers.ORIGIN_QUALIFIERS`.

### `baseSubstance` is the other half of `originQualifier`

The qualifier says *why* a substance is held apart. It does not say what from.
`Carbon Dioxide (biogenic)` was published as a `NeutralMolecule` with
`originQualifier: biogenic` and nothing at all identifying the CO₂ it is
biogenic relative to — so a consumer's only route back to the base substance was
a CAS lookup, which returns the fossil and land-use-change siblings as well.
`baseSubstance` carries the `parent_flow_object_id` the pipeline has always
derived beside the qualifier:

```json
"https://vocab.brightway.one/terms/originQualifier": {
  "@id": "https://vocab.brightway.one/origin-qualifiers/biogenic"
},
"https://vocab.brightway.one/terms/baseSubstance": {
  "@id": "https://vocab.brightway.dev/flow-objects/fo-82a29244dccbaefc"
}
```

Minted rather than borrowed, after checking the alternatives. ChemROF's
`alternate_form_of` is the right shape but is declared `abstract: true`, so it
cannot be instantiated, and every concrete child of it (`isotope_of`,
`has_element`, `conjugate_base_of`) is a *chemical* relation — biogenic CO₂ is
the same molecule as fossil CO₂, which is exactly the point. `subtype_of` is
class-level (`domain: OwlClass`, `range: OwlClass`) and these are instances.
`skos:broader` has `skos:Concept` for both domain and range, and would assert
that a flow object is a concept; the *flows* are published as concepts, the
substances are not.

It is absent wherever `originQualifier` is, and on the one qualified substance
whose flow object carries no CAS number for the parent resolution to run
through (`Oils, Non-fossil`).

### `baseIntervention` is `baseSubstance` for what is not a substance

Some flows count a burden that is not a release of matter. BAFU ships six of
them: traffic noise from an aircraft, a lorry, a passenger car, a freight train
and a passenger train, filed under a compartment it calls `non material
emissions` and measured per person-kilometre or per tonne-kilometre. They are
six measurements of one thing, and the thing has no flow in any source list, so
this project mints a flow object for it and the six point at it:

```json
"https://vocab.brightway.one/terms/baseIntervention": {
  "@id": "https://vocab.brightway.dev/flow-objects/fo-3cddb1c75a28db1c"
}
```

A second term rather than a wider reading of `baseSubstance`, because that term
says "substance" and means it: a noise flow has no base substance, which is the
same reason the semantic typing can give it no chemical class. The alternatives
`baseSubstance` ruled out rule this one out for the same reasons.

Each member keeps its own flow object. The six differ in unit and in
characterisation factors, and one flow object carrying six flows in one context
is what the review application's duplicate check exists to find. Membership is
decided by the context — every flow whose contexts all count something other
than a substance — and the family by name, in
`data/non-material-interventions.json`. A candidate no family claims is reported
by the run rather than swept into the nearest one.

### `expressedAs` and `sumsOver` say what a measurement relates to

An aggregate measurement — `Chemical Oxygen Demand`, `Benzene (as BTEX)`,
`AOX, Adsorbable Organic Halogen as Cl` — is a quantity rather than a substance,
and it still relates to substances. The relation is the dangerous part: reading
`Benzene (as BTEX)` as benzene attributes toluene's and xylene's mass to a
Group 1 carcinogen. These two predicates state the relation as a link so that
nothing has to state it as identity:

```json
"https://vocab.brightway.one/terms/expressedAs": {
  "@id": "https://vocab.brightway.dev/flow-objects/fo-ca47b8a9e172dd57"
},
"https://vocab.brightway.one/terms/sumsOver": {
  "@id": "https://vocab.brightway.dev/flow-objects/fo-b9081903fbd8d902"
}
```

`expressedAs` is the substance the mass is reported in terms of — chlorine for
AOX, benzene for BTEX, oxygen for COD. `sumsOver` is the grouping class whose
members the number counts. AOX has both, and they are deliberately different
objects: the second is EF's `Adsorbable Organic Halogen Compounds`, a class of
molecules; the first is the element those molecules are weighed as.

**`expressedAs` is not `baseSubstance`.** That predicate means the
undifferentiated substance a qualified one was *split from*, and it is published
only beside `originQualifier`. Nothing split BTEX off benzene, and COD's oxygen
is not in the discharge at all — it is what a laboratory's oxidant would
consume. Reusing the term would have made one published definition mean two
things, one of them false.

Both are absent where the curated file states none, and where it states one the
list does not carry: `Nitrogen, Total (excluding N2)` is expressed as nitrogen
and there is no elemental `Nitrogen` flow object, only `Dinitrogen`. Which of
the two it was is recorded on the flow object under
`created_from.aggregate_measurement` rather than being flattened into a missing
key.

## A class of our own

`brightway:AggregateMeasurement` is the only **class** this project mints, and
it is the only `@type` in the export that is not from ChemROF, ENVO or AGROVOC.

A quantity defined by the procedure that produces it is not a chemical entity,
and ChemROF has no term for one. The nearest is `ImpreciseChemicalMixture`,
defined as "a macroscopic polyatomic entity" — a portion of matter, which a
kilogram of chemical oxygen demand is not. Minting was avoided for as long as
the cost was only that these rows stayed untyped; it stopped being acceptable
when two of them were typed as substances by accident, `Acid (as H+)` published
as a `NeutralMolecule` carrying the hydron's structure and `COD, Chemical Oxygen
Demand` as a mixture, both off a registry number
([#68](https://github.com/brightway-labs/brightway-flows/issues/68)).

It is deliberately **outside** the ChemROF hierarchy rather than beneath
`ChemicalEntity`. Being outside it is the statement: a consumer filtering for
chemistry excludes these rows without having to know what COD is.

What has to be published at its IRI is a label, a definition, and the assertion
that it is disjoint with `chemrof:ChemicalEntity` — see the warning below, which
covers it along with everything else minted here.

## What a substance is used for

A flow object says what a substance *is*. What it is *for* — herbicide,
fertilizer, environmental contaminant — is published as
**`RO:0000087 has role`**, on both the flow object and the flow:

```json
"http://purl.obolibrary.org/obo/RO_0000087": [
  {"@id": "http://purl.obolibrary.org/obo/CHEBI_24527", "rdfs:label": "herbicide"},
  {"@id": "http://purl.obolibrary.org/obo/CHEBI_25944", "rdfs:label": "pesticide"}
]
```

Borrowed, not minted, and that is the point: it is the relation ChEBI's own
distribution uses, so the assertions this project publishes and the assertions it
reads are one relation. The values are ChEBI role classes and the hierarchy
between them is ChEBI's — `herbicide ⊑ pesticide` is true because ChEBI says so,
and a consumer that wants the tree resolves the IRIs. Nothing here restates it.

The rows are **nodes, not literals**, so the term is declared
`{"@container": "@set"}` and deliberately not `@type: @id`, which would coerce a
plain string. Each row's own `@id` is the reference; `rdfs:label` beside it is
what stops a reader having to resolve `CHEBI_24527` to learn the flow is a
herbicide, on the same reasoning as `unit` beside `unit_iri`.

It is a **list** because a role is many-valued — sulfluramid is an insecticide
and an acaricide — which is also why it is not modelled as `baseSubstance`-style
parenthood: `parent_flow_object_id` is single, and means something else.

Not every ChEBI role is published. The roles are allow-listed to fourteen
classes in `data/chebi-roles.json`, because ChEBI's role tree is largely
biomedical — `metabolite`, `inhibitor`, `mouse metabolite` — and none of that
groups anything an LCA asks about. `greenhouse gas` is deliberately excluded even
though it sounds useful: ChEBI gives it to carbon dioxide, methane and sulfur
hexafluoride and to no HFC or PFC in this list, so grouping on it would produce a
set missing the entire fluorinated basket.

The flow-object layer carries each assertion's definition and provenance; the
simplified export keeps the IRI and the label only, the same way it publishes
`altLabel` as strings rather than as label records.

**Not every role comes from ChEBI, and the provenance says which do.** ChEBI has
no `has role` edge for about half the pesticides the source lists ship — nothing
for cyhalofop-butyl, for spinetoram, for sodium fluorosilicate, and nothing for
kaolin, which is a clay used as an insecticide because it coats the leaf and
insects will not settle on it. Those roles are asserted by a curator from a
published source, one row per substance in `data/curated-chebi-roles.json`, and
they use the same predicate and the same fourteen classes: a consumer reads them
the same way and does not have to know where a row came from.

Where it matters is revision. A role generated from ChEBI says
`prov:wasGeneratedBy: chebi_roles` and can be recomputed from a newer ChEBI
release; a curated one says `curated_roles`, names the record it was read from
under `prov:hadPrimarySource`, and cannot. Both are published on the same
substance where both apply — laminarin is an `agrochemical` because ChEBI says
so and a `fungicide` because its EU approval does, and dropping either would be
a smaller answer than the one the sources support.

## The substance layer has identifiers now

`chemrof:has_element` links an ion or an isotope to its element, and its value
used to be a bare `flow_object_id`. The export flattens a property entry to its
value, so what was published was the literal string `"fo-0bfffb5e4dadc218"` —
against a slot whose declared range is `ChemicalElement`, a class. Nothing could
follow it and no reasoner could use it.

Flow objects are therefore identified under
`https://vocab.brightway.dev/flow-objects/`, the same authority that already
names the flows that occur of them, and the link is a node reference:

```json
"https://w3id.org/chemrof/has_element": {
  "@id": "https://vocab.brightway.dev/flow-objects/fo-0bfffb5e4dadc218"
}
```

The target is not a node in this document: the flow-object layer is not
published, so the link refers to a substance the export does not describe. That
is a link waiting for its object rather than a literal that can never become
one, and the identifier is the same string either way — so publishing the layer
later adds the description without changing any identifier already emitted.

`brightway:baseSubstance` is the second link over this namespace, on the same
terms.

!!! warning "These have to resolve"

    A minted IRI is a promise: it keeps meaning the same thing, and something
    answers when you dereference it. Serving `vocab.brightway.one/terms/`,
    `vocab.brightway.one/origin-qualifiers/`,
    `vocab.brightway.one/environmental-materials` and
    `vocab.brightway.dev/flow-objects/` is a deployment task, not a code one,
    and it is not done yet. What has to be published at each is a short RDF
    description: a label, a definition, for the five predicates a domain and
    range, and for `brightway:AggregateMeasurement` its disjointness with
    `chemrof:ChemicalEntity`.

    The material scheme is the one entry there that is an IRI rather than a
    namespace: `environmental-materials` is the `skos:ConceptScheme` its
    concepts are `skos:inScheme`, and `environmental-materials/sea-water` is one
    of them — a water flow's `@type` carries the concept, and the scheme has to
    answer for itself as well as for what it prefixes.

## What does not expand

Three keys produce no triples, and are dropped on expansion. They stay in the
JSON, so a plain-JSON reader is unaffected.

| Key | Why it produces nothing |
|---|---|
| `unit` | Undeclared. The IRI form, `unit_iri`, expands as `qudt:hasUnit`; the string beside it is a convenience duplicate. |
| `schema_version` | Undeclared. Metadata about the file, not about the flows. |
| `replaced_by_identifier` | Declared as `null`, which is how JSON-LD says a key asserts nothing. On a redirect record, `dcterms:isReplacedBy` already names the survivor as an IRI; this is the same survivor as a bare UUID, for a consumer doing UUID lookups. A predicate for it would be a second, weaker name for the link that is already there. |

The last one is the distinction worth noting: `unit` and `schema_version` are
undeclared, so nothing in the document says whether that was decided or
overlooked. `replaced_by_identifier` is declared *and* dropped, which says it
was decided.

## Deprecated flows are nodes, and only nodes

A deprecated flow is not in `flows` — the export publishes the live list — but
its identifier is in `redirects` as a node of its own, carrying three
statements and no others:

```
<consensus flow IRI>  owl:deprecated             true
                      dcterms:isReplacedBy       <the surviving flow's IRI>
                      brightway:deprecationReason <a deprecation-reason IRI>
```

The target is the **end** of the replacement chain, not the next hop, so a
consumer never chases one — and never has to write the cycle guard that would
need.

What is deliberately absent is as much of the design as what is there. A
redirect record carries no `@type` and no `skos:inScheme`: a deprecated flow is
not a member of the published scheme, and saying it were would contradict its
absence from `flows`. The record states what is true of the *identifier*, not of
a concept in the list.

`brightway:deprecationReason` is minted, like `originQualifier` and
`baseSubstance` before it, because neither OWL nor DCTERMS has a property for
it. Its values are IRIs under
`https://vocab.brightway.one/deprecation-reasons/` rather than bare strings, for
the same reason origin qualifiers are: a term a consumer is expected to branch
on should not have a second spelling. There are four —
`identity-merge`, `context-collapse`, `unclassified` and
`identifier-scheme-change` — and
[known limitations](limitations.md#what-a-redirects-reason-does-and-does-not-promise)
says why the difference between them is not cosmetic.

The fourth is not a merge at all. It says this list renamed a flow it had
minted, and both sides of the redirect are the same substance in the same
compartment. That happened once, to all 2,561 minted flows at the same time:
they used to be named after whichever source row reached the compartment first,
and are now named after the substance and the compartment.

## The mappings, and where they went

A flow no longer carries `concept_associations`. The mappings to EF 3.1,
SimaPro and ecoinvent are nodes of their own, collected by an
`xkos:Correspondence` — one per source list:

```
Correspondence                        one per source list
  ├── xkos:compares  → the two ConceptSchemes it relates
  └── xkos:madeOf    → ConceptAssociation    (its own @id, a real node)
                         ├── xkos:sourceConcept → the source list's flow
                         └── xkos:targetConcept → the consensus flow
```

This is the shape
[py-semantic-taxonomy](https://github.com/cauldron/py-semantic-taxonomy) uses,
and it is why `xkos:madeOf` is back: #9 removed it because its domain is
`xkos:Correspondence` and there was no such resource to put on its left. There
is now.

**To find the mappings for a flow**, look for associations whose
`xkos:targetConcept` is that flow. They used to be reachable as
`flow["concept_associations"]`; that key is gone, and schema version 4 is the
signal.

**The match quality is a statement about the concepts, not about the
association.** XKOS defines no property for the type or strength of a mapping —
the specification says so — so `skos:exactMatch`, `skos:broadMatch` and
`skos:closeMatch` sit on the source concept. In the file they are written inside
the `xkos:sourceConcept` node object, which in RDF is exactly a statement about
that concept.

**Association IRIs are derived from the two flows they relate**, so the same
mapping gets the same IRI on every run and a rebuild does not rename the graph.

## Every triple is in the default graph

`flows`, `redirects`, `concept_schemes` and `correspondences` are all
`@included`. None is `@graph`, and that is deliberate.

`flows` *was* `@graph`, and while it was the only key in the document producing
triples that was harmless: a node object carrying nothing but `@graph` is a
plain graph container, so its contents land in the default graph. Add a second
top-level key and the document object becomes a named node — its `@graph`
becomes a *named* graph, and the flows move into a blank-node-named one while
the correspondences stay in the default graph. A consumer querying the default
graph would then get the correspondences and none of the flows.

`@included` keeps every node in the default graph whatever else is added. Only
`to_rdf` shows this; `expand` reports the same nodes either way, which is why
`tests/test_jsonld_export.py` checks the N-Quads.

One consequence for readers: with `@included`, `jsonld.expand()` returns the one
wrapping node rather than a flat list. Use `jsonld.flatten()` or `jsonld.to_rdf()`.

## Schemes and status

The consensus list is a `skos:ConceptScheme`, every published flow is a
`skos:Concept` `skos:inScheme` it, and each source list is a scheme of its own.
That answers what the flow layer *is* — a question left open in #8, where the
answer had been "there is no verified class for an occurrence rather than a
substance".

Schemes and correspondences carry `bibo:status`. SKOS and XKOS define no
construct for publication status; BIBO's is what py-semantic-taxonomy settled
on. Everything published is `accepted` — a flow a curator has not settled is not
in the export at all.

`dcterms:created` and `dcterms:creator` are emitted, as PyST requires — but not
on every scheme. The consensus scheme and every correspondence carry both; a
source list's scheme carries neither. This project created the consensus list
and asserts each correspondence, so those are its claims to make. It did not
create EF 3.1 or ecoinvent, and naming itself their creator would be false. A
source scheme appears in the document only so a correspondence has something
well-formed to `xkos:compares`.

`creator` is the literal `brightway-flows <version>`. `dcterms:creator`
ranges over `dcterms:Agent` and software is one, but this project publishes no
IRI for itself and minting one to name the generator would be a publishing
commitment for no gain over the string.

`created` is a wall-clock `xsd:dateTime`, and so the one value in the export
that differs between two runs over identical inputs. `tools/verify_run.py`
treats it as volatile — as it already did `generated_at` and `run_id` — so a
comparison still reports real differences and not the clock.

## Language tags

PyST rejects an untagged string literal. `prefLabel`, `altLabel` and
`definition` are published as bare strings, so the tag is declared on the
**term** in `@context` rather than written into the document:

```json
"definition": {
  "@id": "http://www.w3.org/2004/02/skos/core#definition",
  "@language": "en"
}
```

The literals expand tagged, and a consumer reading `definition[0]` as a string
still gets a string — no shape change and no schema bump, which writing
`{"@value": ..., "@language": "en"}` into the export would have needed.

This is a claim about the export rather than about the pipeline. Labels are
resolved to one language before export, English preferred but falling back to
whatever a source list supplies, so a definition that exists only in another
language is tagged `en` wrongly. That is the assumption the resolution already
made; it is now stated in the output. Carrying the real tag through means
publishing these as language-tagged objects.

## Units

`qudt:hasUnit` with an IRI, everywhere. The source-concept nodes used
`qudt:unit` with a bare string — `"qudt:unit": "kg"` — which is wrong twice
over: QUDT deprecates `qudt:unit` in favour of `qudt:hasUnit`, and both range
over `qudt:Unit`, which a string is not. The unit string is resolved through
`units.json` by `brightway_flows.domain.units.unit_iri_for`; a unit that
file does not know is left out rather than stated wrongly.

## Guarantees the test suite enforces

`tests/test_jsonld_export.py` builds an export from fixtures, expands it with
the JSON-LD reference implementation, and asserts the triples. It fails if:

- the export loses its `@context`, or a flow loses its `@id`
- a published field is added without being declared or knowingly exempted
- `properties` stops nesting, or leaves an intermediate node behind
- a mass or charge regresses to a string
- an unparseable value is silently dropped
- `formal_charge` reappears in the published output
- a flow asserts `xkos:madeOf`, which would make it a correspondence
- any triple lands in a graph other than the default one
- a mapping loses its own IRI, or that IRI stops being derived from the two
  flows it relates
- the match quality moves off the source concept and onto the association
- the compartment or the origin qualifier stops expanding, or either is
  published as a string rather than a reference
