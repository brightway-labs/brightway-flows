# Data model

!!! note "For developers"

    This page describes the Python classes that hold flow data **in memory**. It
    is for people writing or modifying processing steps. For the shape of the
    files on disk, see [File schemas](schemas.md).

This is also the reference for the ongoing move away from passing untyped
dictionaries through the ETL.

## Why classes at all

The pipeline used to move `dict[str, Any]` from loading through to export. Three
costs came with that:

- **Typos were silent.** `flow["prefLable"] = …` created a new key that nothing
  read. There was no point at which the mistake surfaced.
- **Every reader re-validated.** Because any key could hold anything, code was
  full of `isinstance(x, dict)` guards — several hundred of them.
- **The shape was undocumented.** The only way to learn a flow's fields was to
  read every writer.

The classes below fix the first two by construction and the third by existing.

## Layering

The project separates the *file contract* from the *working record*, following
the rule in [Architecture](architecture.md): validate external payloads at the
boundary with Pydantic, then operate on dataclasses inside the pipeline.

```
input JSON ──► HarmonisedFlow ──► Flow ──► transformers ──► Flow
               (Pydantic,         (dataclass, mutated in place)
                validates)                     │
                                               ▼
                              resolve_flow_layers(list[Flow])
                                               │
                                               ▼
                              list[FlowObject] + list[ElementaryFlow]
                                               │  ← one conversion, records → dicts
                                               ▼
                                  SimpleFlow / JSON / SQLite
```

Every record stays typed until the write boundary. `Flow`, `FlowObject` and
`ElementaryFlow` are each serialised exactly once, immediately before the SQLite
writer and the JSON exports.

## The classes

### `domain.models.HarmonisedFlow` — the input file contract

**Pydantic.** Validates a raw record read from disk, and nothing else. It is the
only place that decides whether an input file is acceptable.

- Declares Python-valid field names with aliases for serialised keys that are
  not valid identifiers: `owl_deprecated` ↔ `http://www.w3.org/2002/07/owl#deprecated`,
  `skos_definition` ↔ the SKOS definition IRI, `pipeline_sources` ↔ `_sources`.
- `from_dict()` routes unrecognised keys into `additional_properties` rather
  than dropping them; `to_dict()` inlines them again.
- Reads `context` as what an input file actually carries: the compartment path
  the source list ships, a list of strings. The consensus context is not an
  input, so this model has no opinion about it; see `Flow.context` below.

**Used by:** `pipeline._load_transform_inputs`, once per input record.

### `domain.flow.Flow` — the working record

**Dataclass.** What transformers read and write. One instance per flow for the
life of a transform run.

It is a dataclass rather than the Pydantic model for two reasons. Transformers
mutate flows in a hot loop over ~94k records and `HarmonisedFlow` sets
`validate_assignment=True`, so every write would re-run full validation. And
`dataclasses.fields()` is what lets `Change` reject an unknown field name.

Key members:

| Member | Purpose |
|---|---|
| `uuid`, `identifier`, `name`, `source` | Identity |
| `cas_numbers`, `ec_numbers`, `synonyms` | Chemical identifiers |
| `context`, `context_iri`, `unit`, `unit_iri` | Context and unit |
| `prefLabel`, `altLabel` | Lang-tagged labels; see `domain/labels.py` |
| `properties`, `references`, `concept_associations`, `skos_definition` | Enrichment |
| `flow_object_id`, `source_refs`, `input_datasets` | Layering and source tracking |
| `owl_deprecated`, `dcterms_is_replaced_by`, `is_replaced_by_uuid` | Deprecation |
| `general_comment`, `cas_match_labels`, `cas_number_sources` | Carried from the source list or set by a transformer |
| `pipeline_sources` | Field name → last transformer that wrote it |
| `extra` | Source-specific keys not declared here, round-tripped verbatim |

Three behaviours are worth knowing:

- **`context` is the consensus context, and only that.** It is a
  `domain.context.Context` — `None` until `DefaultContextMappingTransformer`,
  the second transformer of the chain, decides which one the flow is in. The
  compartment path the source list shipped is a different fact and lives in
  `provided.context`, permanently: it is what the mapping keys on, what the
  merge matches on, and what every artifact reports as `original_context`.

  It used to be one field holding both, typed `list[Any] | dict[str, Any]`, and
  a reader could not tell from the type which one they had. The measurement
  that settled it: the mapping places all 93,993 flows of a full EF 3.1 run, so
  the list form was alive for one transformer's worth of the run, and all
  95,193 published elementary flows carry the structured form (#97). Nothing
  may reach an artifact without a consensus context —
  `context_registry.validate_flow_contexts` stops the run — which is what lets
  `ElementaryFlow.context` be a required `Context` rather than `Any`. See
  [Flow contexts](../concepts/contexts.md).
- **`to_dict()` is not `dataclasses.asdict()`.** It restores aliased keys, omits
  optional fields that are `None` so absent keys stay absent, and inlines
  `extra`. The leading fields mirror `HarmonisedFlow`'s declaration order, and
  fields that model does not declare come last — `tests/test_flow_model.py`
  asserts both. Promoting a key out of `extra` into a declared field therefore
  moves it later in the serialised record; the keys and values are unchanged,
  only their order, which JSON does not treat as meaningful.
- **There is no `get()`.** Records are read by attribute. A wrong field name
  raises where it is written rather than returning `None` — which is how three
  dead branches survived in the transformers, including two guards on
  `origin_qualifier`, a field `Flow` does not have. Source-specific keys are read
  from `extra` explicitly.

### `pipeline.engine.Change` — a proposed field update

A transformer does not mutate flows directly. It returns `Change` objects and
the engine applies them, producing a list of
`pipeline.review_records.ChangeEvent` — the change log that fills the
`changelog` and `provenance_activities` tables.

Three names, one pipe, and they stay distinct because a request is not a
receipt: `Change` is proposed, `ChangeEvent` is what the engine applied, and
`webapps.app.queries.changes.ChangeRow` is that row read back for a review page
a build later. The last of those was also called `Change` until #98.

```python
Change(flow.uuid, "prefLabel", new_labels, comment="why this changed")
```

`field` is validated against `Flow` at construction. A misspelled name raises
`UnknownFlowFieldError` at the call site instead of silently creating a key.
Both attribute names and serialised keys are accepted; the attribute name is
stored.

Changes are applied last-writer-wins, in transformer order, and each application
records the transformer in `flow.pipeline_sources`.

### `domain.records.SerialisableRecord` — shared dict conversion

A mixin, not a record. `Flow`, `FlowObject` and `ElementaryFlow` all need the
same two things: serialised keys that are not valid Python identifiers (`@type`,
`_sources`, IRI-keyed fields), and optional fields that must stay *absent* from
the output rather than serialise as null. `dataclasses.asdict()` does neither, so
each record declares `_ALIASES`, `_OMIT_IF_NONE` and optionally `_EXTRA_FIELD`,
and inherits `from_dict` / `to_dict` / `resolve_field` / `get`.

Two further declarations cover fields that are not plain values. `_NESTED` names
a field holding another record, converted by its own `from_dict` / `to_dict`.
`_CODECS` names a field whose serialised form needs a pair of functions instead:
`Flow.context` and `ElementaryFlow.context`, whose `Context` deliberately leaves
its on-disk shape to this project rather than to the shared context contract, and
`lcia_methods`, which holds `StatedFactor` records and publishes the rows a
source list stated — five keys of the publisher's plus the amount, in the
publisher's own order.

A codec'd field can therefore publish a shape its annotation does not describe,
and the generated JSON Schema is about the published shape. `_SERIALISED_SCHEMAS`
is where a record says what that shape is; `lcia_methods` declares the list of
objects the artifacts have always held, so converting the field left every
checked-in schema byte-identical.

It is deliberately field-free so it composes with `@dataclass` subclasses without
disturbing their field order — which is what keeps serialised key order stable.

### `domain.flow_object.FlowObject` — canonical substance identity

**Dataclass.** One per distinct substance, shared across contexts. Carries
`prefLabel`, `altLabel`, `properties`, `references`, `classifications`, the
`origin_qualifier` / `parent_flow_object_id` pair used for biogenic/fossil
splits, `skos_definition`, and `types` (serialised as `@type`, e.g.
`chemrof:FullySpecifiedAtom`). See
[Flow objects and elementary flows](../concepts/two-layers.md).

### `domain.elementary_flow.ElementaryFlow` — a substance in a context

**Dataclass.** The `(flow_object_id, context_iri)` pairing, plus unit, LCIA
methods and source references. That pair must be unique across non-deprecated
flows.

`context` is a required `Context` — an elementary flow *is* a substance in a
context, so a record without one is not one of these. It can be required because
the layering runs after the gate that refuses any flow the mapping did not
place.

Also carries `concept_associations`, attached after layering, and the
deprecation cluster (`owl_deprecated`, `dcterms_is_replaced_by`,
`is_replaced_by_uuid`) set by the duplicate-deprecation pass. Those are omitted
from the output when unset, so active flows do not gain null keys. An `extra`
bag holds the label and property fields the merge pipeline inherits onto flows
it adds.

`minted_elementary_flow_id` lives here too: a flow this project mints — one the
merge added rather than one EF 3.1 shipped — is named by a hash of that same
pair, so the identifier says what the uniqueness rule says. It used to carry the
uuid of whichever source row reached the compartment first, which renamed flows
that had not changed
([#102](https://github.com/brightway-labs/brightway-flows/issues/102)).

### `domain.context.Context` — a validated context

**Dataclass of enums,** with eight `check_*` invariants that reject impossible
combinations (water emissions with no water body, vertical strata on a
non-air medium, and so on). This is a shared definition used across Brightway
tooling — keep the enums, the validators and `to_list`/`from_list` in step.

Resolve a context from its IRI with `domain.context_registry`; never rebuild one
by parsing `to_list()` output, which drops `"Unknown"` values and orders fields
for reading rather than for round-tripping.

`context_for_iri` returns one shared instance per IRI, and the flows that land
on the same context share it. That is what makes a `Context` on 94k records
cheaper than the dict it replaced, and it holds because nothing mutates a
context: a flow moves by being given a different one.

### `domain.vocabulary` — the term registry

Not a flow class, but the single definition point for every vocabulary IRI, plus
short names (`Term.MOLECULAR_FORMULA`) and a generated `JSONLD_CONTEXT`. Import
IRIs from here; a test fails if a module re-declares one.

### `domain.simple_flow.SimpleFlow` — the published export

**Dataclass.** The stripped-down record in `harmonised-flows-simple.json.gz`,
which is what downstream consumers read. Deliberately narrower than `Flow`.

### The characterisation records

**Dataclasses, in two halves.** `domain/lcia/records.py` holds both, and the
difference between them is whose words they are in. A publisher states a factor
against its own flow identifier and its own name for the category; what this list
publishes is joined by our identifiers, and the method's own file is what gets
from one to the other.

| Class | Module | Role |
|---|---|---|
| `StatedCategory` | `domain/lcia/records.py` | An impact category as its own publisher names it. Frozen, and shared by every factor that names it |
| `StatedFactor` | `domain/lcia/records.py` | That a publisher stated this amount for this flow in this category. What `lcia_methods` on `Flow` and `ElementaryFlow` holds |
| `SupersededValue` | `domain/lcia/records.py` | A number a collapse declined, and the flow that published it |
| `LCIAMethod` | `domain/lcia/records.py` | A method, one row for every version and implementation of it |
| `ImpactCategory` | `domain/lcia/records.py` | One category as one implementer renders it. `implemented_by` is the field the section turns on |
| `CharacterizationFactor` | `domain/lcia/records.py` | What one unit of a consensus flow is worth under one category |
| `ImpactCategoryDefinition` | `domain/lcia/crosswalk.py` | One category of one method: every implementation's name for it, and the unit and area of protection it is published with |
| `LCIAMethodDefinition` | `domain/lcia/crosswalk.py` | One method: its version, its implementations and its categories. One file per method, and nothing outside it is about one method in particular |
| `MethodImplementation` | `domain/lcia/crosswalk.py` | Who rendered a method. `role` is what the pipeline branches on — `reference`, `transcription`, `consensus` — and `factors` says where its numbers are read from |
| `StatedCategoryName` | `domain/lcia/crosswalk.py` | What one implementation calls one category, and the identifier its own factor rows carry |

A `StatedFactor` becomes a `CharacterizationFactor` when the method file has said
which impact category the publisher's words name and the matching has said which
consensus flow its identifier names — identifiers on both sides, because by then
both are ours. The lookup is always inside one method: a category slug is unique
within a method and not across methods, so a `Difference`, a `CoverageGap` and a
factor queue's `item_key` all carry the method as well.

**The score artifact** is a third half, in `domain/lcia/unit_process_scores.py`,
and entirely in the vendor's words: what brightway says a sample of a release's
unit processes are worth, with the vendor's own flows, factors and scores.
`ScoreArtifact` holds an `ArtifactRelease`, the `ArtifactCategory`,
`ArtifactFlow` and `ArtifactFactor` lists, and one `UnitProcess` per dataset
with its `InventoryLine`s and scores. It is the one record family this project
reads rather than writes — `tools/export_unit_process_scores.py` produces it
under a brightway Python — so `load_score_artifact` is where the boundary is
defended: the generated schema first, then that every factor and inventory line
names a flow the file describes, then that the inventory and the factors
reproduce every score. Which releases are read, and from where, is
`settings.ScoreComparisonSettings`.

### The release records

**Dataclasses, all `SerialisableRecord`s,** in `releases/`. A release is a
build somebody tagged, and a migration is what a consumer of one release
applies to hold the next; these are the records between the two.

| Class | Module | Role |
|---|---|---|
| `ReleaseStamp` | `releases/snapshot.py` | Which build a snapshot came from and what it is called: the run, the commit, the merged lists, the tag or the `git describe` of a development build |
| `SnapshotFlowObject` | `releases/snapshot.py` | A substance as the `flow_objects` table publishes it. Registry numbers are inside `classifications`, so a corrected CAS is one change |
| `SnapshotElementaryFlow` | `releases/snapshot.py` | A `SimpleFlow` plus what the export leaves out: its substance, and whether it is deprecated and where its redirect points |
| `SnapshotRedirect` | `releases/snapshot.py` | One published redirect with its reason as a slug, because the alignment branches on it |
| `SnapshotFactor` | `releases/snapshot.py` | A factor by the triple that identifies it; the method and category names ride along for comments only |
| `SnapshotSourceRow` | `releases/snapshot.py` | `(list, version, source uuid)` and the flow it reached: the key one build's identifiers are matched to another's by |
| `ReleaseSnapshot` | `releases/snapshot.py` | The root of `releases/<version>.json.gz`: the stamp and the five lists, with the indexes the alignment reads |
| `IdentifierFate` | `releases/alignment.py` | What became of one identifier the later release does not publish: replaced, deleted or unresolved, and how that was decided |
| `Delta` | `releases/diff.py` | One change to one substance, flow or factor, with `DeltaKind` (`created`, `updated`, `replaced`, `deleted`, `unresolved`). `Delta`, not `Change`: `pipeline.Change` is a transformer's proposal and the webapp's `ChangeRow` is a changelog row read back |
| `MigrationRuling` | `releases/rulings.py` | A curator's answer for one unresolved identifier between one pair of releases |

### Supporting value objects

| Class | Module | Role |
|---|---|---|
| `Label` | `domain/labels.py` | One lang-tagged label with provenance |
| `Provenance` | `domain/common.py` | Structured PROV record; use instead of free text |
| `Classification` | `domain/flow_object.py` | A classification with resource URLs and per-value provenance |

## Writing a transformer

```python
from brightway_flows.domain.flow import Flow
from brightway_flows.pipeline import Change, Transformer

class MyTransformer(Transformer):
    name = "my_transformer"

    def setup(self) -> None:
        """Load supplementary data once, before any flow is seen."""

    def transform(self, flows: list[Flow]) -> list[Change]:
        changes = []
        for flow in flows:
            if not flow.cas_numbers:
                continue
            changes.append(Change(
                flow.uuid, "altLabel", enrich(flow.altLabel),
                comment="added synonyms from <source>",
            ))
        return changes
```

Points to observe:

- `transform` receives **all** flows, so logic that groups or compares them is
  possible.
- Return changes; do not mutate flows. Mutating bypasses the change log, and
  `AGENTS.md` requires that data changes carry structured provenance.
- Always set `comment`. It is what a reviewer sees in the webapp.
- Register the class in `transformers/__init__.py`; order matters and is
  documented in [Harmonisation steps](harmonisation-steps.md).
- **Read by attribute, never `.get()`.** Records have no `get()`, so
  `flow.cas_numbrs` raises immediately instead of quietly evaluating to `None`.
  Source-specific keys live in `extra` and are read from it by name:
  `flow.extra["elementary_flow_categorization"]`.
- **Check which record type owns a field before guarding on it.**
  `origin_qualifier` is on `FlowObject`, not `Flow`. Three transformer guards
  tested it on the flow and silently never fired — see
  [Known limitations](limitations.md).
- Dictionaries belong at I/O boundaries only. External payloads — ChEBI,
  PubChem, GLAD, SQLite rows — stay dicts by design and are parsed where they
  are read.

## Current state of the migration

Typed today, and read by attribute throughout:

- Input loading through to the end of the transformer loop.
- `Change` field names.
- `resolve_flow_layers`, end to end: it takes `list[Flow]` and returns
  `list[FlowObject]` and `list[ElementaryFlow]`.
- The duplicate-deprecation pass, the context gate and the concept-association
  back-propagation.
- Contexts, flow objects, labels, provenance, the simple export.
- The merge's working set, both layers, end to end: `_load_working_set` builds
  `FlowObject` and `ElementaryFlow` records at the read boundary. The flow
  object round trip is byte-exact over all 8,021 objects of the 2026-08-14
  build. The elementary round trip returns the same keys with the same values
  over all 95,190 rows of that build, in a different order on 93,993 of them —
  see below.
- The flows the merge creates, and the report rows it writes about them.
- The characterisation factors a flow carries. `lcia_methods` was a list of
  dicts, six keys read with `.get()` in four modules — including
  `flow_layers.contested_cas`, which compares two flows' factors to decide which
  CAS number a substance keeps. It holds `StatedFactor` records now, and
  `deduplication.settle_factor_values` writes the number it settles by
  attribute.
- Every write made after the layering: a pass records it through
  `LayerWriteLog`, which validates the field name against `Flow` exactly as
  `Change` does, and the record reaches `changelog`.
- One source reference. `domain.source_ref.SourceRef` is both the working record
  and — validated by Pydantic as a stdlib dataclass — the boundary contract for
  `HarmonisedFlow.source_refs`.

Typed at the door and dict-shaped behind it: the SQLite writer.
`_write_consensus_sqlite` takes `list[Flow]`, `list[ChangeEvent]`,
`list[FlowObject]` and `list[ElementaryFlow]`, and converts the three record
lists with `to_dict()` before it opens the database. It serialises whole
records — into columns, into `flow_json`, into the search text — so the
conversion is its own work rather than three parallel lists of dictionaries the
caller builds only to hand over (#96). `changelog` is never converted: the
only thing the database keeps of the log is a per-flow count of it.

Still dict-based, deliberately:

- the JSON exports, which serialise whole records at the boundary;
- the Flask apps, which read rows back from SQLite and JSON.

The merge's elementary-flow working list was the last of these, and #93 is what
it took to convert it. `ElementaryFlow`'s declaration order differs from the
order `elementary_flow_record` projects, which appends the three keys it
defaults, so the conversion reorders 93,993 of the build's 95,190 rows. No
published byte moves with it: the working list is never serialised in the order
it is held. A flow the merge creates reaches `elementary_flows.flow_json`
through `_as_harmonised`, which rebuilds it as a `Flow` and so writes that column
in `Flow`'s order, and the selector traces in `merge_outcomes.detail_json` are
assembled key by key from the fields they name.

The substance keys a merge-created flow carries — `name`, `prefLabel`,
`altLabel`, `properties`, `references`, `cas_numbers`, `ec_numbers`,
`skos:definition` — are not declared on `ElementaryFlow` and live in its `extra`
bag, read from there by name. `elementary_flow_json` has two shapes: 93,993
base-list rows carry the occurrence keys alone and the 1,197 the merge created
carry these as well. Which shape is right is a question about what a record of a
flow should say, not a question this conversion answers.

`flow_label_value` and `validate_flow_contexts` accept either a record or a
mapping, explicitly, because they are called from both sides of that boundary.

External payloads — ChEBI records, PubChem compounds, GLAD rows — stay
dictionaries on purpose. Their shape is set by a foreign API and changes outside
this project; they are parsed at the boundary where they are read.

The transitional `get()` shim is gone. It let dict-shaped reading code survive
while the records were introduced, at the cost of turning a wrong field name
into a silent `None` — which is how three dead branches and a broken
applied-changes log went unnoticed. Its call sites were found by instrumenting
`get()` to log its caller during a bounded run, rather than by grepping, since
most `.get()` calls in these modules are on external payloads and had to stay.

The serialised shape of these records is now a checked contract.
`domain/schema.py` derives a JSON Schema per artifact from the record classes —
handling `_ALIASES`, `_OMIT_IF_NONE` and `_EXTRA_FIELD`, none of which a plain
`TypeAdapter(cls).json_schema()` would get right — and `tests/test_schemas.py`
fails if the checked-in copies under `data/schemas/` drift from the classes, or
if a real artifact does not validate. Changing a field on a record means
regenerating those schemas.

One known gap remains here rather than in the type work: `properties` are
accumulator bags with no resolution step and no value-to-provenance linkage. See
[Known limitations](limitations.md).
