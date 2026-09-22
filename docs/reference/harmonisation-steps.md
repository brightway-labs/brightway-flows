# Harmonisation steps

A transform runs twenty-seven processing steps ("transformers") over the flows, in
a fixed order, and then fourteen further passes over the two layers those steps
produce. This page says what each one does and why it sits where it does.

For the reasoning behind the rules — why PubChem is distrusted, what the guards
protect against — read [How a flow is decided](../deciding/index.md) first.
This page is the ordered inventory.

## How a step works

No step edits a flow. Each reads the flows it is shown and hands back a list of
*proposals* — this flow, this field, this new value, and a sentence saying why.
The run applies them and records every one it applied.

Three consequences matter when you are reading the output.

- **The change log is complete.** Nothing reaches a published flow without a row
  in the `changelog` table naming the step that wrote it and the reason. That
  is what `/changes`, and the history on a flow's own page, are showing you.
- **A later step overrules an earlier one.** Proposals are applied in step order,
  and for the same field on the same flow the last one wins. `Carbon Dioxide`
  is title-cased at step 5 and may be replaced outright at step 14; the
  published label is step 14's, and step 5's attempt is still in the log.
- **Each flow goes through the chain once.** The order assumes raw input — step
  5 would re-title-case what step 14 wrote — so a flow is marked finished when
  the chain has been through it, and nothing may write to it again. This is
  what lets a later source list be enriched alongside the settled consensus
  without disturbing it.

## What each step is shown

Twenty-two of the twenty-seven steps ask a question about one flow: what this
registry number resolves to, what this structure implies, how this flow's own
names should be spelled. Those are shown only the flows the run can still write
to.

Five ask a question about the *set*, and are shown every flow, finished ones
included:

| Step | The question it asks about the set |
|---|---|
| 7 Registry number from the name | Does another row of this list give this name a number? |
| 13 Strip cross-object synonyms | Is this synonym some other substance's name? |
| 14 Strip element-symbol synonyms | Which substance *is* the element for this symbol? |
| 15 Consensus matching | Do the source lists agree about this substance? |
| 17 RDKit (authoritative) | Is this structure unique across the whole build? |

The distinction is why bringing in a small list is now quick. Building the base
list shows every step every flow, because nothing is finished yet. Bringing in a
source list afterwards is different: the consensus is already settled, so a step
that answers per flow sees only the arriving rows. Before that was true, adding
ecoinvent 3.8's 4,892 flows cost as much as building the 94,000-flow base list,
because every step re-derived an answer for the whole consensus and the run
discarded it — about 210,000 discarded answers per merged list. Merging one list
went from 189 seconds to 60
([#88](https://github.com/brightway-labs/brightway-flows/issues/88)).

A step that does not say which kind of question it asks is shown everything.
That costs time and cannot cost correctness.

## The order

| # | Step | Does |
|---|---|---|
| 1 | Bootstrap labels | Build structured `prefLabel`/`altLabel` from legacy name and synonym fields |
| 2 | Default context mapping | Resolve source compartments to consensus contexts |
| 3 | Unit normalisation | Map unit strings onto the canonical unit vocabulary |
| 4 | Strip names | Remove leading and trailing whitespace |
| 5 | Normalise name case | Conservative title-casing |
| 6 | Common Chemistry CAS review | Early CAS reconciliation against Common Chemistry and ChEBI |
| 7 | Registry number from the name | Fill in a missing CAS from what the flow's own name unambiguously means |
| 8 | Check digits | Validate CAS and EC check digits; propose corrections |
| 9 | EC cross-check | Test CAS ↔ EC pairs against the ECHA inventory |
| 10 | Enrich references | Add ChEBI/PubChem properties and external references |
| 11 | RDKit (pre-consensus) | Compute structural properties from existing structures |
| 12 | ChEBI synonyms | Import ChEBI synonyms as `altLabel` |
| 13 | Strip cross-object synonyms | Remove synonyms that are another substance's preferred name |
| 14 | Strip element-symbol synonyms | Remove element symbols from non-element flows |
| 15 | **Consensus matching** | Decide preferred names and identifiers from weighed evidence |
| 16 | OPSIN | Parse IUPAC names; set authoritative name and structure |
| 17 | RDKit (authoritative) | Replace structural properties for unambiguous flows |
| 18 | RDKit (post-consensus) | Compute structural properties for the rest |
| 19 | Supply registered composition | Publish the registry's composition where the pipeline derived none and the name agrees |
| 20 | Supply registered structure | Publish the registry's structure where the pipeline derived none and the registry knows the substance by this name |
| 21 | Withhold contradicted composition | Withdraw a structure the registry's own composition contradicts |
| 22 | Apply structure corrections | Publish the structure a curator states, for a substance the pipeline cannot work out |
| 23 | Withhold ambiguous mass | Publish a mass only for a flow whose structure is settled |
| 24 | Strip qualifier synonyms | Remove non-qualifier-specific synonyms from qualified flows |
| 25 | Strip catalogue synonyms | Remove supplier grades, trade names and database accessions |
| 26 | Strip product families | Remove repeated supplier product families from crowded objects |
| 27 | Dedupe synonyms | Remove duplicate `altLabel` values, preserving order |

A `PubChemTransformer` exists that proposes name updates from PubChem compound
data. It is **not** in the default chain — PubChem names are not trusted as a
primary naming source.

A `PubChem readable name` step used to run just before the dedupe, promoting a
PubChem record title over the current label. It was removed in
[#21](https://github.com/brightway-labs/brightway-flows/issues/21): it
rewrote 17,942 published labels a run from a single source with no agreement
requirement and no curator ruling, and being last in line its label was the one
that shipped. `Nivalenol` was published as `Epitope ID:2151205`.

## Phase by phase

### Steps 1–5: make the data comparable

Nothing here makes a judgement. Labels move into the structured SKOS form,
compartments resolve to consensus contexts, units resolve to the canonical
vocabulary, whitespace and casing are normalised.

These run first because every later step compares flows to each other, and
comparison is only meaningful once representation is uniform. Unit
normalisation in particular has to happen before matching, since a unit that
does not resolve fails the run at export.

Context resolution is where the `context_iri` is set. From this point on the
IRI, not the display strings, is the authoritative form of the context.

### Steps 6–9: fix the identifiers

Registry numbers are checked before anything is enriched from them.

- **Common Chemistry CAS review** reconciles CAS numbers against the highest-quality
  source available, and records disagreements for review rather than silently
  overwriting.
- **Registry number from the name** fills in a number where the row has none and
  its own name says which it is. BAFU ships four rows called `Silver-110`; two
  of them carry 14391-76-5 and two carry nothing at all, and the two without it
  ended up published as a second silver-110 with no half-life, no decay mode and
  no characterisation. A row takes the number the *same list* gives that name on
  another row, and only where the list is silent does it take the one ChEBI and
  PubChem publish — which is what keeps BAFU's `Barite` on the number BAFU gave
  it, 13462-86-7, rather than on barium sulfate. Nothing is written where a name
  reaches more than one number: `Borax` is the decahydrate and the anhydrous
  salt, and a name that means two substances has identified neither.
- **Check digits** catch transcription errors — CAS and EC numbers both carry a
  check digit — and propose corrections where the intended number is
  unambiguous. Strings nothing valid can be recovered from go to the
  `ec-malformed` review queue.

    An EC number's last digit is a sum of the six before it, taken modulo 11,
    which leaves eleven possible answers and only ten digits to write them in.
    Where the sum lands on the eleventh, the substances registered before 1981
    simply skipped the number — so one that turns up is a typing error. The
    substances notified as new afterwards, whose numbers begin with 4, did not
    skip it: they were issued with a 1. `423-740-1` is the fragrance ingredient
    Peonile, `435-790-1` is the heat-transfer fluid HFE-7500, and both are
    numbers ECHA publishes an infocard for. 181 of the 106,213 substances in
    the inventory are of this kind, ten of them reach EF 3.1, and until #120
    all ten were filed as errors nobody could fix.
- **EC cross-check** tests each CAS ↔ EC pairing against the official ECHA
  inventory. Contradictions go to the `ec-cross-check` review queue.

Order matters: enrichment steps look substances up *by* their identifiers, so a
wrong identifier here becomes wrong chemistry later.

### Steps 10–14: enrich, then clean up

**Enrich references** and **ChEBI synonyms** pull properties, cross-references
and synonyms from ChEBI and PubChem. Both apply the CAS cross-check and formula
guards described in [How a flow is decided](../deciding/index.md) — this is
where a mis-linked ChEBI record would do the most damage.

Enrichment resolves a CAS to PubChem compounds in three narrowing passes, in
this order:

1. **The curated-CAS gate.** A compound whose own curated CAS section does not
   list the number searched on is dropped, provided another candidate is
   attested. This runs first because it is the only one that consults PubChem's
   own judgement rather than inferring one, and the only one that works on a
   flow carrying neither a formula nor a ChEBI id — which is most of them at
   this point in the chain.
2. **Formula similarity**, where the flow already has a molecular formula.
3. **ChEBI alignment**, where the flow already has a ChEBI id. If the CAS was
   ambiguous and no candidate carries a matching ChEBI cross-reference, all of
   them are rejected rather than one being picked.

Passes 2 and 3 ask whether the CAS *was* ambiguous, not whether it still is —
so the gate in pass 1 cannot make an ambiguous CAS look settled and let a
candidate through that pass 3 would have rejected.

**RDKit (pre-consensus)** computes structural properties from whatever
structures are now available, so consensus matching has them to weigh.

Then two cleanup passes remove synonyms that would mislead the matching step:

- synonyms identical to a *different* flow object's preferred name;
- element symbols (`Rn`, `[Rn]`) on anything that is not the pure element.

Both deliberately run **before** consensus matching, so the scoring step never
sees a contaminated label set.

### Step 15: consensus matching

The main naming and identity decision. It evaluates candidate preferred and
alternative names across ChEBI, the EC inventory, PubChem and Common Chemistry;
classifies how identifiers and names relate; and applies an update only when
explicit confidence rules are met — typically several independent sources
agreeing.

Where a CAS is unique within its context, name selection uses readability and
complexity scoring with a margin requirement, so a marginally-better candidate
does not displace an established name.

When the evidence does not meet the bar it does not guess. The case goes to the
`consensus-match` review queue, at `/queue/consensus-match`. Changes it does
apply are in the `changelog` table, under `transformer = 'consensus_match'`.

### Steps 16–18: derive structure authoritatively

Once identity is settled, structural data can be recomputed rather than
inherited.

**OPSIN** parses IUPAC names into structures. A flow qualifies when exactly one
unique label across its preferred and alternative names parses — compared
case-insensitively. For those flows the IUPAC name property is set to that
label, and SMILES and InChI are replaced with values derived from the parse.
All labels for the run are batched into a single OPSIN call, so the JVM starts
once.

**RDKit (authoritative)** then replaces every structural property — SMILES,
InChI, InChIKey, formula, masses — but only where identity is unambiguous:

1. exactly one IUPAC name value, set by OPSIN in this run or seeded from
   PubChem in an earlier one;
2. an InChI resolving to a standard-layer InChIKey that is globally unique
   across all flows.

OPSIN deliberately leaves InChIKey, formula and masses to this step, so they are
all derived from one authoritative InChI rather than from a mixture of sources.

**RDKit (post-consensus)** fills in structural properties for the flows that did
not qualify, without overriding what is already there.

Both RDKit stages ask whether the flow already carries the *structure*, not
whether it carries the string. InChI, InChIKey, formula and masses are canonical
across toolkits, so those match on the string as they always did; a canonical
SMILES is canonical only per toolkit, so those are compared after
canonicalisation. Where the structure is already there, RDKit is recorded as a
further source on it rather than adding a second spelling — see [one structure,
one value](semantic-types.md#one-structure-one-value-whoever-spelled-it).

Neither stage adds an InChIKey with no stereochemistry to a flow that already
carries a stereochemistry-bearing key for the same skeleton, and a key that does
carry it withdraws a flat one already there. The flat key is the same substance
with a layer deleted, and it is another substance's real key — the two side by
side in one slot are indistinguishable from two candidate identities. It is
still computed and still published for a flow that has no more specific key for
that skeleton. See [Known limitations](limitations.md#some-flow-objects-merge-unrelated-substances).

!!! warning "Qualified flows are not excluded here, though they were meant to be"

    All three of these stages were written to skip flows carrying an origin
    qualifier — biogenic and fossil CO₂, green/blue/grey water — and to leave
    them out of the InChIKey uniqueness index.

    The guards read `origin_qualifier` off the flow. It is a **flow object**
    field; `Flow` does not have it, and it appears in no input. The guards
    therefore never fired, and this was invisible until the record classes
    stopped tolerating a missing attribute. The dead conditions have been
    removed rather than repaired, because restoring the intent would change
    which flows get enriched — that is a data decision, not a refactor.

    Two consequences today: qualified flows receive RDKit structural enrichment
    that was intended to be withheld, and they count towards InChIKey
    uniqueness — so a substance whose only "duplicate" is its own biogenic
    variant is not treated as unique. See
    [Known limitations](limitations.md).

### Steps 19–27: final polish

- **Supply registered composition** publishes what the registry says a substance
  is made of, where the steps above worked out nothing. Some numbers carry a
  formula and no structure — CAS knows Sb₂S₃'s composition and publishes no
  connection table for it — and until #129 that answer was only ever used to
  *judge* a derived formula, never to supply one. Antimony trisulfide ended with
  no composition at all once its wrong one was withdrawn, which the next step's
  own rule calls worse than a disputed one.

    Only the composition is written: no SMILES, no InChI, no mass. Those are
    statements about connectivity, the registry makes none, and inventing one
    from a composition is the mistake #129 is about. And a registry number alone
    is not enough — **the substance's own name has to state a count that
    agrees**. Without that gate the step fires on two dozen substances and
    several would be wrong: `Rhenium(2+)` would take neutral rhenium's formula
    from the element's registry number, and `Uranium Alpha` — alpha-emitting
    isotopes reported together as activity, not a substance — would be published
    as uranium metal.
- **Supply registered structure** is the same question about the same numbers,
  asked the other way: not what the substance is made of, but what it *is*. Some
  registry numbers carry a full structure, and a substance whose own chemistry
  the steps above could not work out was published with a name and a number and
  nothing else even so. Disodium phosphonate is a plain salt of two sodiums and
  one phosphonate; CAS has held its structure all along, and this list published
  none, because the composition step refuses a formula written in more than one
  piece — a sensible guard against reading a mixture's ingredient list as a
  molecule, and a salt is exactly what that shape looks like when it is not one.

    The evidence that the number really is *this* substance is the load-bearing
    part, and it cannot be the composition step's, which asks the name to state
    a count: hardly any of these names count anything. It is instead that **CAS
    knows the substance by the name this list gives it** — `disodium
    phosphonate` is one of the names CAS records for that number. Two sources
    naming one substance, which is the same test in the form these names can
    meet, and it refuses every case the composition step warns about: the six
    correction flows for delayed emissions would otherwise take carbon dioxide's
    and methane's structures, and `Uranium Alpha` uranium metal's.

    Three more groups pass that gate and are still refused. **Isotopes**,
    because CAS registers uranium-238's number as plain `Uranium`, and
    publishing it would make uranium-238 and uranium metal the same substance to
    anyone joining on structure. **Mixtures CAS names as such** — "reaction
    products with", "reaction mass of" — whose structures are the recipe the
    name lists rather than a compound. And **minerals whose formula is a ratio**,
    like talc at three-quarters of a magnesium, where the registered formula and
    the registered structure are not describing the same thing.

    The structure, its key and the composition are published, all credited to
    the registry. No mass and no SMILES: those would have to be computed from
    the structure, and the steps that compute such things have already run by
    this point — which is where this step has to be if it is only ever to fill a
    gap and never to overrule a derivation.
- **Withhold contradicted composition** withdraws a structure whose composition
  the registry's own formula contradicts. A registry writes a salt as its acid
  and a ratio of metal — nickel acetate is `C2H4O2 · 1/2 Ni`, two acetic acids
  to one nickel — and neither SMILES nor InChI can hold half an atom, so the
  structure derived from that formula loses the ratio and describes one acetic
  acid beside one nickel. Both end up published. This step multiplies the ratio
  out, ignores hydrogen (a salt is its acid with the acidic hydrogens gone) and
  compares what is left against each published formula.

    It withdraws only where the registry backs at least one of the substance's
    own formulas: where it agrees with none of them the disagreement is real and
    the row stays open for a curator, and a substance publishing a single
    formula is never touched. The same test cuts both ways — it keeps the
    name-derived answer for nickel acetate and withdraws it for
    `1,4-diazabicyclooctane`, whose incomplete name parses to a different
    molecule. See [Salts: the formula and the structure do not say the same
    thing](../deciding/salts.md).
- **Apply structure corrections** publishes the structure a curator states in
  `structure-corrections.json`, for a substance whose structure nothing in this
  pipeline can work out. One today: antimony trisulfide, where the name reader
  returns a monosulfide, the registry has a composition and no structure, and
  EF's own name describes a four-antimony cage the substance is not. It runs
  after both steps above rather than before them because it is not evidence
  to be weighed — it is a decision, and a decision a later derivation could
  reverse would not be one. The published class is stated in the same entry.
- **Withhold ambiguous mass** publishes `molecular_mass` only where one
  structure is settled — a mass is a property of a structure, so a flow carrying
  several candidates has none to report.
- **Strip qualifier synonyms** removes synonyms from a qualified flow that are
  not specific to its qualifier — so the biogenic CO₂ flow does not accumulate
  names that describe fossil CO₂.
- **Strip catalogue synonyms** removes the strings that are catalogue entries
  rather than names: supplier grades (`S 100`, `A 1`), trade names with a
  product number (`Garlon 480`, `Prifrac 2981`) and database accessions (`NSC
  147337`, `C.I. 77120`). It runs here because both writers of an alternative
  label have finished by now — ChEBI at step 11 and Common Chemistry at step
  14 — and before the dedupe, so the deduplicated list is the published one.

    It matches on the shape of the string, so it can be wrong; when it is,
    [`altlabel-keep-list.json`](https://github.com/brightway-labs/brightway-flows/blob/main/src/brightway_flows/data/altlabel-keep-list.json)
    overrules it for a named label without a code change, and the step's
    change-log comment names every value it removed. See [A product code is not
    a
    name](../deciding/synonyms.md#the-catalogue-strip-a-product-code-is-not-a-name).
- **Strip product families** removes what the shapes above cannot see, because
  the evidence is not in any single label. `Silicon Dioxide` published 4,003
  synonyms, 173 of them beginning `Snowtex` and 126 `Aerosil`
  ([#27](https://github.com/brightway-labs/brightway-flows/issues/27)); a
  brand token matches no anchored prefix list and there is an open-ended supply
  of them. Repetition within one object is the signal instead: several labels
  sharing a leading token and ending in a free-standing designation are a
  supplier catalogue, not a naming history.

    It runs only on objects carrying at least 100 alternative labels. That is a
    scope gate rather than a quality signal — the median object has 9 synonyms
    and the 96 above 100 hold 23.9% of every synonym in the list, so the rule is
    confined to where a repeated token has no innocent reading. It takes 8,643
    labels from 69 objects, 6.6% of the published total.

    Names that are shaped like product codes are settled by a register rather
    than a pattern, because `Ponceau 4R` and `Acetoquinone Blue R` do not
    differ as strings: ChEBI is consulted at run time and the public part of the
    Colour Index ships in
    [`colour-index-names.json`](https://github.com/brightway-labs/brightway-flows/blob/main/src/brightway_flows/data/colour-index-names.json).
    Corroboration may only keep a label, never publish one. `Methyl Violet 10B`
    is in no open register and is the documented gap; the keep list covers that
    case.
- **Dedupe synonyms** removes duplicates, keeping the first occurrence so
  provenance ordering survives.

## After the steps: the layering, and the passes that follow it

When every step has run, the flows are split into the two published layers, and
fourteen further passes run over the result. Much of what you will notice about
the published list is decided here rather than in the chain above: what kind of
thing each substance is, which occurrences are duplicates of one another, and
which source-list flow each one answers to.

Each pass counts its own work into `run_stats`, under the stage name below, so a
number that moves between builds can be read against the pass that moved it.
Figures quoted in this section are from the 2026-08-14 build unless another is
named.

| | Pass | Decides | `run_stats` stage |
|---|---|---|---|
| 1 | Split the layers | which flows are one substance, and which occurrences are one flow | `resolve_flow_layers` |
| 2 | Split by origin qualifier | that biogenic and fossil CO₂ are two substances | `resolve_flow_layers` |
| 3 | Ask about contested registry numbers | which shared CAS numbers nobody has ruled on | `resolve_flow_layers`, and the `contested-cas` queue |
| 4 | Collapse and report duplicate occurrences | which duplicates go, on whose terms, and which pairs are still a question | `apply_collision_rulings`, `deprecate_duplicate_elementary_flows`, `elementary_flow_collisions` |
| 5 | Attach concept associations | which source-list flow each occurrence answers to | *counted at export, as `build_correspondences`* |
| 6 | Resolve match strengths | how strong each of those links may claim to be | `resolve_match_strengths` |
| 7 | Carry associations onto flows | that a flow-shaped consumer can see them | `carry_associations_onto_flows` |
| 8 | Recognise flows that are not substances | which flows are land classes, corrections or aggregates | `attach_non_material_families` |
| 9 | Type each substance | what kind of thing it is, from its chemistry | `assign_semantic_types` |
| 10 | Normalise property values | one structure, one value, on the predicate that means it | `normalise_property_values` |
| 11 | Send the substance's chemistry to its flows | that both layers publish the same chemistry | `layer_writes` |
| 12 | Withdraw chemistry from flows that are not one substance | which flows may state no formula at all | `withdraw_single_substance_properties` |
| 13 | Send an element's name to its flows | that `nitrogen` publishes as `Nitrogen` | `element_pref_labels` |
| 14 | Send the substance's name to its flows | that a flow is called what its substance is called | `substance_label_v1`, and the `substance-label-conflict` queue |

A pass that writes to a flow writes through the same change log the steps do.
So a change in a flow's history with no step behind it is one of these, and
`run_stats` files them together under `layer_writes`, by pass. Before that was
true, a published label being replaced outright — or a flow being deprecated —
happened with nothing in the log to show for it.

1. **Flow objects and elementary flows are separated.** Substances are grouped
   by identity; occurrences are grouped by `(flow_object_id, context_iri)`.
   Identity is the CAS number, falling back to the normalised name — except for
   a flow whose name is exactly a nuclide, which is grouped by that nuclide.
   Both source lists put the *element's* registry number on some nuclide rows,
   and grouping on it merged uranium ore with a single nuclide (#17).
2. **Origin qualifiers split flow objects.** Flows named as biogenic, fossil,
   land-use-change, or as green/blue/grey water get their own flow object
   linked to the base substance. Detection reads the flow's current display
   name first and falls back to the original names in `source_refs` — necessary
   because a naming step may already have normalised the qualifier out of the
   preferred name. Where the qualifier has to be recovered that way, the
   original qualified name is restored as the preferred label. Among names
   sharing a qualifier and CAS, the shorter wins.
3. **A registry number that two flow names share is a question, not a merge.**
   The layering groups on the CAS number, so two names in one source list
   carrying the same number become one substance — which is right for a synonym
   and wrong for two substances the list happened to register alike. The
   2026-08-14 build weighed 794 such numbers. Eleven carry a curated ruling that
   they name two substances, which keeps 318 flows off the object their shared
   number would otherwise have put them on; 370 have no ruling, stay merged, and
   go to the `contested-cas` queue with the names that share them. Staying
   merged is the conservative answer: splitting a substance nobody asked to
   split would strand every characterisation factor pointing at it.
4. **Duplicates are deprecated, not deleted.** Elementary flows with the same
   substance-and-context signature keep one active row; the others are marked
   `owl:deprecated` with a `dcterms:isReplacedBy` pointer.

    A name is not part of that signature, so two flows of one substance in one
    context and unit differing *only* in their name are collapsed here — which
    is #31. What holds a pair apart is a field the signature reads, and it is
    almost always the free-text note: of the 116 pairs standing in the
    2026-08-12 build, 114 differed only in `general_comment` and the other two
    only in which source named their CAS. On 90 of those the note was
    `01.00.000`, a version string EF writes into a description field, which is
    not a description and is no longer read as one — collapsing 77 of the 116
    (#62) and leaving 39, of which 37 are held apart by a note that really is
    prose. Those are the pairs the `elementary-flow-collision` queue asks about,
    and each item names the differing fields so a curator can see what is doing
    the holding.

    Where a curator has answered — the ruling is in
    [`elementary-flow-collision-decisions.json`](https://github.com/brightway-labs/brightway-flows/blob/main/src/brightway_flows/data/elementary-flow-collision-decisions.json),
    keyed on the collision so it survives a rebuild — the collapse happens just
    before this step, on the curator's terms rather than the sort's: the ruling
    names which flow survives, the other flow's characterisation factors and
    source references are carried onto it, and a source list that mapped onto
    the collapsed identifier reaches the survivor through the replacement.

    The characterisation factors are not part of the signature either, so two
    rows being collapsed can publish the same factor and give it different
    numbers — usually because one of them is the other rounded. Whichever
    collapse it is, the number is now settled rather than inherited from
    whichever row the sort reached: where the two are one number written to
    different precision, the more precise one is published, and the number not
    published is recorded on the factor that superseded it, under
    `superseded_values`, naming the flow that published it. Where the gap is
    too wide to be rounding — 66 of the 68 doubly-published factors on the
    2026-08-12 build, by up to 400 times — the number is still settled the same
    way, and the run logs `merged_factor_values_conflict` and counts
    `duplicate_factor_values_conflict`, because discarding a number that far
    from the one kept is a decision about which source to believe rather than a
    duplicate publishing itself twice.

    The queue is asked again by the merge, of the flows it is about to write,
    and its answer replaces this one — because a merge *adds* flows, and while
    only this step asked, the queue described 116 groups of a published 145
    ([#60](https://github.com/brightway-labs/brightway-flows/issues/60)).
    Each item says which stage produced it, and a group holding flows the merge
    minted is `review` rather than `info`. The two stages' counts are filed
    separately in `run_stats`, under `elementary_flow_collisions` and
    `merge_elementary_flow_collisions`, so a number that moves can be read
    against the stage that moved it. This step and the ruling above both run
    before the merge, so a group the merge produced is one neither has seen —
    and a ruling written against one is counted absent rather than applied. The
    factor settling above never reaches those flows either.

    The merge asks the other half of the same question as well, which nothing
    used to ask: whether one *substance* is published in two **places**
    ([#87](https://github.com/brightway-labs/brightway-flows/issues/87)).
    Where a substance is released is a fact about the process, so releases are
    left out of it — a metal emitted to air and to a river is two ordinary
    flows. Where it is taken from is a fact about the substance, so two intake
    contexts that are two different places rather than one described at two
    levels of detail are two answers to a question that has one, and the flow
    the merge wrote into the second of them is what nothing watched. Those
    reach the `substance-in-two-places` queue, counted in `run_stats` under
    `merge_substance_places`. Unlike a collision, there is nothing here one
    field away from collapsing: the two halves are separate identifiers that
    can never meet, so an inventory using one and a method characterising the
    other do not connect.

    **The rule the queue exists to enforce: a substance is taken from one
    place.** The check reports; it cannot fix, because which of the two places
    is right is a question about the substance and the pipeline has no way to
    answer it. The answer is written down instead, one row at a time, in
    `flow_specific_context_mappings` — the same instrument
    [#83](https://github.com/brightway-labs/brightway-flows/issues/83)
    used for BAFU's land compartment and
    [#117](https://github.com/brightway-labs/brightway-flows/issues/117)
    for its cooling water. A row names the source flow by uuid, records the
    compartment the vendor ships it in, gives the context it belongs in, and
    says why.
    [#89](https://github.com/brightway-labs/brightway-flows/issues/89)
    closed the last nine that way, and
    `stats.merge_substance_places.substances_in_two_places` is 0.

    Two kinds of row, and they are not the same claim:

    - **A filing slip**, where one list contradicts itself. The vendor writes
      one name into two compartments, usually in the same dataset, and the
      majority filing is the substance's real home — basalt is in the ground in
      102 datasets and biotic and in-air in one each, all three in one dataset.
      Nothing is being decided here; the vendor's own data settles it.
    - **A disagreement between two lists**, where both readings have something
      behind them and the project has to pick. Green water is rainfall held in
      soil: EF 3.1 files it as taken from air because that is how it arrives,
      ecoinvent as taken from the ground because that is where roots reach it.
      Neither is wrong, neither flow carries a factor, and the list takes EF's.
      **These are choices, and the rule's comment has to say so** — a reader who
      cannot tell a correction from a decision cannot re-check either.
    - **Two substances wearing one name**, which is neither of the above, and
      which the check cannot tell from them. Peat is the worked example: EF 3.1
      ships peat as a non-renewable *energy* resource in megajoules, carrying
      the fossil-resource factor, **and** as a renewable *material* resource in
      kilograms, carrying nothing. Fuel peat and horticultural peat are not one
      substance in two places, and a context rule that moved one onto the other
      would merge two substances and cross a unit at the same time. What the
      answer needs is a **rename**, in the manual-fixes file of every release
      that ships the flow, so the two are told apart by name; each is then in
      one place already, because both source lists file each of them
      consistently.

      **Before reaching for a context rule, check the units.** Two intake
      contexts measured in different units are the shape this case makes, and
      the rule that would "fix" it destroys evidence: it merges the substances
      and hides the unit crossing inside a match. It is also worth checking
      whether the compartments disagree at all — ecoinvent's material peat and
      EF's are both filed as biotic, so once the names agreed nothing had to
      move, and an earlier attempt that moved them all to the ground collapsed a
      distinction the sources were drawing.

    All three are held by `expectations/0450-one-place-per-substance.json`,
    which states the surviving place for each substance *and* names the row that
    used to go elsewhere. Two claims rather than one, because a fix that moved a
    row somewhere new again would satisfy neither, and a fix that moved the row
    correctly while leaving the minted twin standing would satisfy only the
    second. Where the answer was a rename, the unit is claimed too — that is
    what says the two substances are still two.

    **A rule may have to move the base list's own flow.** Where the rows are
    sent somewhere the base list's flow is not, the two cannot meet: the merge
    refuses to put a row on a flow whose medium contradicts its own, and mints a
    second flow instead — the defect the check reports, reintroduced by the fix
    for it. So the rule goes on EF's flow as well, which is what
    [#114](https://github.com/brightway-labs/brightway-flows/issues/114) did
    when EF filed helium as a resource taken from air: helium comes out of
    natural gas, ecoinvent said so, and it was EF's flow that moved.
5. **Concept associations are attached**, linking each occurrence back to the
   source-list flows it corresponds to. Which lists those are is a property of
   the run: the base list, plus every list named by `--source` whose manifest
   declares a `concept_associations` block.
6. **Each of those links is told how strong a claim it may make.** An
   `exactMatch` says that one source flow and one consensus flow mean the same
   thing. That is only true where the source list did not put several of its own
   flows onto the same consensus flow — where it did, the consensus flow is
   *broader* than any one of them, and each link is weakened to a `broadMatch`.
   The count is over the whole source list, so the answer is not knowable until
   every one of its flows is placed. On the 2026-08-14 build 93,799 links kept
   `exactMatch` and 50 were weakened, all of them EF 3.1's. Before this pass
   existed, 28 EF 3.1 flows each claimed two exact matches, one of them a
   retired duplicate's
   ([#76](https://github.com/brightway-labs/brightway-flows/issues/76)).
7. **Those links are copied onto the flow.** The published export and the flow's
   own record are flow-shaped, so a link resolved on the occurrence layer has to
   travel or no consumer sees it. A link a merge wrote directly is kept rather
   than replaced; the two are told apart by the activity named in the link's own
   provenance.
8. **Flows that are not substances are recognised, and grouped into families.**
   A land-use class, a delayed-emission correction and an alpha-emitter
   aggregate are all things an inventory measures without their being a
   substance, and where several of them are the same kind of thing a parent
   object is minted for the family. The number to watch is
   `non_material_unfamilied`: it counts the candidates no family claimed, it is
   zero today, and a run where it is not is a run that met a kind of
   non-material flow nothing has been told about.
9. **Each substance is typed** — what kind of thing it is, derived from its
   chemistry rather than from its name. `Nickel(2+)` becomes a
   [MonoatomicIon](https://chemkg.github.io/chemrof/MonoatomicIon/) whose
   [Atom](https://chemkg.github.io/chemrof/Atom/) is nickel; `Alcohols, C12-15,
   ethoxylated` becomes an
   [ImpreciseChemicalMixture](https://chemkg.github.io/chemrof/ImpreciseChemicalMixture/),
   which is what a UVCB is. Deriving it from the formula, charge, structure,
   registry numbers and emission contexts rather than from a pattern over the
   label is what catches `Chloride` and `Sodium ion`, which a pattern missed.
   The 2026-08-14 build typed 5,409 neutral molecules, 91 elements, 81 isotope
   records, 36 monoatomic ions, 24 polyatomic ions and 7 zwitterions, and left
   32 objects untyped for having neither a structure nor a registry number.
   See [Semantic types](semantic-types.md).
10. **Property values are normalised.** A semantic property leaves here typed
    the way the ontology types it, a whole-entity charge leaves on the predicate
    that means whole-entity charge, and one structure leaves as one value
    however its sources spelled it — 30,940 duplicate SMILES spellings and 226
    duplicate isomeric ones were collapsed on that build. Four counters here
    have to read zero, and do: a flow or an object publishing a stereochemistry
    in the field defined as carrying none, and a flat InChIKey left beside a
    more specific one for the same skeleton.
11. **The substance's chemistry travels to its flows.** Formula, masses,
    structures, registry strings, charge and the RDF classes are held once, on
    the substance, and the flow shows what is in it. That is a derivation rather
    than a copy, so a later correction to the substance cannot reach one layer
    and not the other. It used to be a copy, and the two drifted: on the
    2026-08-12 build 815 of 7,674 substances differed from their own flows, and
    8,542 published flows stated a molecular shape in the field defined as
    carrying none
    ([#53](https://github.com/brightway-labs/brightway-flows/issues/53)).
12. **A flow that is not one substance may not state a chemistry.** An
    alpha-emitter aggregate or a delayed-emission correction has no molecular
    formula to report, and 216 flows are in that position. `properties_withdrawn`
    reads zero, because step 12 above no longer gives them one — and it is still
    counted, because a non-zero reading means a flow the typing missed is
    publishing a molecular formula for a quantity measured in kg·a.
13. **An element's name reaches its flows**, titlecased — so a source list
    saying `nitrogen` publishes as `Nitrogen`. Only where that is a change of
    casing, or where a curator has approved the rename: a flow whose own name is
    more specific than its substance's — an allotrope, an isotope, a phase —
    keeps it, and the proposal goes to the `undecided-label-replacement` queue.
    That was 856 titlecasings and 2 undecided renames on the 2026-08-14 build.
    The rulings are in
    [`preferred-label-decisions.json`](https://github.com/brightway-labs/brightway-flows/blob/main/src/brightway_flows/data/preferred-label-decisions.json),
    the same file that gates consensus matching's renames.
14. **The substance's name reaches its flows** — the general rule the element
    pass is a special case of, and the last writer of a published name. The
    name of a substance is written twice, once on the substance and once on
    each of its flows, and until this pass a correction to the first copy
    stopped there: the 2026-08-19 build published 886 flows under a name their
    own substance had superseded, and 149 substances appeared in the export
    under two different names at once
    ([#7](https://github.com/brightway-labs/brightway-flows/issues/7)).
    Each flow now takes its substance's name, and the name it had stays
    findable as a synonym of the flow. The exception is deliberate: a flow
    whose own name answers for a *different* substance is an identification
    bug — either two substance records are one substance, or the flow sits on
    the wrong one
    ([#116](https://github.com/brightway-labs/brightway-flows/issues/116))
    — and renaming it would delete the only visible symptom. Such a flow keeps
    its name and the pair goes to the `substance-label-conflict` queue,
    unless a ruling in the same decisions file has answered it: `approve`
    renames and withholds the colliding synonym (a name that answers for two
    substances is published for neither, #113), `reject` lets the flow's name
    stand. The merge applies the same rule to the whole database after its own
    label writes, under the `merge_substance_labels` stage, because a merge
    moves substance names on flows it never otherwise rewrites. `assess`
    checks the result from the published payloads, as
    `flows.label_disagrees_with_substance`.

Element and isotope enrichment is **seeded from the base list only**. A
substance that arrives solely through a merged list gets no element or isotope
facts: the periodic table is matched by label against the one list whose labels
are curated for it, and a merged list's row reaches the enrichment only once it
has been matched onto a consensus flow the base list already named. This was an
undeclared consequence of an `if row.source == "EF 3.1"` comparison until #14;
it is now a stated policy, at the guard and in the module's docstring.

See [Flow objects and elementary flows](../concepts/two-layers.md).

## What a run writes

Every run writes:

- `harmonised-flows-simple.json.gz` — the published export, the one artifact
  with a downstream consumer
- `consensus-flows.sqlite3` — both layers, the change log, the PROV-O activity
  trail, every review queue, what each stage counted, and the merge outcome

Nothing is optional any more. `elementary-flows.json`, `flow-objects.json` and
`harmonised-flows.json` are no longer written; the records they held are JSON
columns in the database. The review files that used to be written on request —
`transform-log.json`, `provenance.json`, `consensus-match-review.json` — and
the four written unconditionally are tables in it.

See [Which output do I need?](../using/outputs.md).
