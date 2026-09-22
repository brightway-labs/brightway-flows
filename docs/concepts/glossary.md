# Glossary

Terms as this project uses them. Where a term is common in LCA but used here
more narrowly, the narrower sense is given.

### altLabel

A synonym. From SKOS, where `skos:altLabel` is the alternative to
`skos:prefLabel`. Stored per language.

Supplier grades, trade names and database accessions are not synonyms and are
removed; see [A product code is not a
name](../deciding/synonyms.md#the-catalogue-strip-a-product-code-is-not-a-name).

### CAS number

CAS Registry Number. Widely used but **not** a unique key for substance
identity in this project's sense: one CAS may be listed by several database
records, and database records occasionally claim a CAS belonging to a different
substance. See [How a flow is decided](../deciding/index.md).

### ChEBI

Chemical Entities of Biological Interest, the EBI's chemical ontology. The
primary source of synonyms and cross-references here.

### ChemROF

The [chemical representation ontology](https://chemkg.github.io/chemrof/) whose
IRIs are used as property keys — molecular formula, molecular mass, elemental
charge, atomic number, SMILES, InChI, InChIKey, IUPAC name — and as semantic
types such as `FullySpecifiedAtom` and `MonoatomicIon`.

### Concept association

A recorded correspondence between a consensus flow and a flow in a source list,
expressed as an `xkos:ConceptAssociation` carrying a SKOS mapping property. This
is what makes the output usable as a translation table.

Which property is a statement about the pair, not about the source list.
`skos:exactMatch` is symmetric and transitive, so it is used only where the
pairing is one-to-one on both sides; `skos:broadMatch` where one consensus flow
groups several source flows, `skos:narrowMatch` where one source flow spans
several consensus flows, and `skos:relatedMatch` where both are true.

That is counted after the merge has seen the whole source list, never while a
row is being merged: which property a pairing supports depends on how many other
rows of the same list land on the same consensus flow, and the row being merged
cannot see them. A `skos:closeMatch` — written where a row was matched by
identifier or label rather than asserted equivalent by a curator — is left as it
is either way. It claims nothing that chains, and promoting it to a hierarchy
would state more than the match knows.

### Consensus matching

The step that decides a flow's preferred name and identifiers by weighing
several independent sources against each other, acting only when confidence
rules are met. Not to be confused with the project name.

### Context

The compartment an elementary flow belongs to, expressed in this project's
controlled vocabulary: a `dimension`, usually a `media`, and optionally one
sub-attribute. There are 60 allowed contexts. See
[Flow contexts](contexts.md).

### Context IRI

The canonical identifier for a context, e.g.
`https://vocab.brightway.one/flow-contexts/envi-air-grle-ur10pesq`. **This, not
the display strings, is the authoritative form.** Contexts should always be
resolved from the IRI; reconstructing one by parsing display strings loses
information, because `Unknown` values are omitted from the display form.

### Dimension

The top level of the context taxonomy: `Environmental`, `Resource`,
`Land Use`, `Economic`, `Social`, or `Inventory Indicator`. Added on top of the
Edelen taxonomy so that flows without a direct environmental effect can still be
characterised.

### Elementary flow

Here specifically: **one substance in one context**, identified by
`elementary_flow_id`. Carries context, unit, LCIA methods, and source
references. See [Flow objects and elementary flows](two-layers.md).

### EF 3.1

The European Commission's Environmental Footprint reference flow list, version
3.1, distributed in ILCD format. The base input for this project.

### Flow object

The canonical identity of a substance, identified by `flow_object_id` (format
`fo-` followed by 16 hex characters). Carries names, synonyms, registry numbers,
and chemical properties. Shared across all contexts in which the substance
appears.

### GLAD

The [Global LCA Data Access network](https://www.globallcadataaccess.org/).
Its ILCD-to-SimaPro substance mapping workbook is used to generate concept
associations to SimaPro flows, by a build that merges a list whose flows
originate in SimaPro. Each row pairs an EF 3.1 flow with a SimaPro one; the
SimaPro concept is identified by substance *and* compartment, because the
workbook's `TargetFlowUUID` names only the substance.

### Harmonised flow

An intermediate record: one input flow after all processing steps have run, but
before the split into flow objects and elementary flows. Stored in
`elementary_flows.flow_json`; it was written to `harmonised-flows.json` until
the pipeline stopped producing that file.

### ILCD

International Reference Life Cycle Data System, the XML format EF 3.1 ships in.

### InChI / InChIKey

IUPAC structure identifiers. The InChIKey is a fixed-length hash of the InChI;
its first block (the "skeleton") encodes connectivity, so two records with
different skeletons are structurally unrelated substances.

### Layering

The step that takes processed flows and resolves them into the two output
layers — flow objects and elementary flows. Also available on its own via the
`build` command.

### Merge

Folding an additional source list (currently ecoinvent) into an existing
consensus list, adding source references to matching flows and creating new
flows where nothing matches. Distinct from the transform, which builds the list
in the first place.

### Origin qualifier

A tag marking a flow that must not share a flow object with the base substance
despite sharing its CAS number: `biogenic`, `fossil`, `land_use_change`,
`biogenic_resource_correction`, `biogenic_100yr`, `green_water`,
`blue_water`, `grey_water`,
`alpha_emitters`, `delayed_emission_correction`,
`biogenic_delayed_emission_correction`, `fossil_delayed_emission_correction`.

### prefLabel

The preferred name, one per language. From SKOS.

### Provenance

A structured record of where a data value came from, following
[PROV-O](https://www.w3.org/TR/prov-o/) — not free text. Distinct from the
change log, which records which processing step wrote a field.

### Resource (dimension)

In this project, `Resource` is reserved for accounting concepts such as "mass
fraction of zinc" or "energy, geothermal, converted". A named mineral such as
sphalerite is a tangible substance and gets `Environmental` with a media
instead. This differs from most source lists and is a deliberate choice — see
[Flow contexts](contexts.md).

### SKOS

Simple Knowledge Organization System. Supplies `prefLabel`, `altLabel`,
`definition`, and the mapping properties (`exactMatch`, `closeMatch`,
`broadMatch`, `narrowMatch`, `relatedMatch`) used in concept associations.

### Source ref

An entry in an elementary flow's `source_refs` recording one contributing source
flow: its list name and version, original UUID, original name, and original
compartment strings. Never discarded, so a merge remains auditable.

### Transform

The main pipeline run: load inputs, apply every processing step in order, then
layer and export. Invoked as `brightway-flows build`.

### Transformer

One processing step in the transform. Twenty run by default, in a fixed order.
Each proposes changes rather than editing flows directly, which is what makes
the change log complete. See
[Harmonisation steps](../reference/harmonisation-steps.md).

### XKOS

An extension of SKOS for statistical classifications, used here for
`xkos:ConceptAssociation`. Note that XKOS defines **no** property for the type
of a mapping, so the match kind is expressed with the SKOS mapping property
itself rather than with any `mapType` property.
