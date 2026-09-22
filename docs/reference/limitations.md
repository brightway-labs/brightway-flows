# Known limitations

Things that are currently wrong, incomplete, or misleading. Read this before
depending on the output for anything consequential.

## Open questions, by source list and by topic

Everything below is a snapshot; the live record is the issue tracker. Each
open issue is labelled with the source list it is about and the kind of
question it asks, so a reader who only cares about one list can filter to it.
These links show every open issue carrying that label:

**By source list**

- [EF 3.1](https://github.com/brightway-labs/brightway-flows/issues?q=is%3Aissue+is%3Aopen+label%3Aef-3.1)
  — the European Commission's Environmental Footprint flow list and method
- [ecoinvent](https://github.com/brightway-labs/brightway-flows/issues?q=is%3Aissue+is%3Aopen+label%3Aecoinvent)
  — releases 3.8 to 3.12, and ecoinvent's own implementation of EF 3.1
- [BAFU 2026 v1](https://github.com/brightway-labs/brightway-flows/issues?q=is%3Aissue+is%3Aopen+label%3Abafu)
  — the Swiss federal flow list
- [GreenDelta](https://github.com/brightway-labs/brightway-flows/issues?q=is%3Aissue+is%3Aopen+label%3Agreendelta)
  — the EF 3.1 implementation for openLCA shipped with BAFU
- [Stepwise 2006](https://github.com/brightway-labs/brightway-flows/issues?q=is%3Aissue+is%3Aopen+label%3Astepwise)
- [EXIOBASE](https://github.com/brightway-labs/brightway-flows/issues?q=is%3Aissue+is%3Aopen+label%3Aexiobase)
- [ChEBI](https://github.com/brightway-labs/brightway-flows/issues?q=is%3Aissue+is%3Aopen+label%3Achebi),
  [PubChem](https://github.com/brightway-labs/brightway-flows/issues?q=is%3Aissue+is%3Aopen+label%3Apubchem)
  and [CAS Common Chemistry](https://github.com/brightway-labs/brightway-flows/issues?q=is%3Aissue+is%3Aopen+label%3Acommon-chemistry)
  — the registries the chemistry is enriched from

**By topic**

- [matching](https://github.com/brightway-labs/brightway-flows/issues?q=is%3Aissue+is%3Aopen+label%3Amatching)
  — a source row reaches the wrong substance, several, or none
- [chemistry](https://github.com/brightway-labs/brightway-flows/issues?q=is%3Aissue+is%3Aopen+label%3Achemistry)
  — formulas, structures, charges and registry numbers
- [names](https://github.com/brightway-labs/brightway-flows/issues?q=is%3Aissue+is%3Aopen+label%3Anames)
  — preferred and alternative names
- [lcia-factors](https://github.com/brightway-labs/brightway-flows/issues?q=is%3Aissue+is%3Aopen+label%3Alcia-factors)
  — which characterisation factor is published and why
- [compartments](https://github.com/brightway-labs/brightway-flows/issues?q=is%3Aissue+is%3Aopen+label%3Acompartments)
  — which compartment a flow sits in, and which factors reach it
- [land-use](https://github.com/brightway-labs/brightway-flows/issues?q=is%3Aissue+is%3Aopen+label%3Aland-use)
  and [water](https://github.com/brightway-labs/brightway-flows/issues?q=is%3Aissue+is%3Aopen+label%3Awater)
- [publishing](https://github.com/brightway-labs/brightway-flows/issues?q=is%3Aissue+is%3Aopen+label%3Apublishing)
  — the export files, JSON-LD and licence
- [review-app](https://github.com/brightway-labs/brightway-flows/issues?q=is%3Aissue+is%3Aopen+label%3Areview-app)
- [pipeline-rule](https://github.com/brightway-labs/brightway-flows/issues?q=is%3Aissue+is%3Aopen+label%3Apipeline-rule)
  — a rule the build applies to every source list, rather than one list's data

**By who has to answer**

- [needs-chemist](https://github.com/brightway-labs/brightway-flows/issues?q=is%3Aissue+is%3Aopen+label%3Aneeds-chemist)
  — rows waiting for someone to read them with chemistry knowledge
- [needs-policy-decision](https://github.com/brightway-labs/brightway-flows/issues?q=is%3Aissue+is%3Aopen+label%3Aneeds-policy-decision)
  — waiting on a project-level decision rather than on data
- [upstream-question](https://github.com/brightway-labs/brightway-flows/issues?q=is%3Aissue+is%3Aopen+label%3Aupstream-question)
  — only the publisher of a source list can answer

Most issues carry a table of the affected rows and a link to a CSV with every
row and its data, so the question can be worked on without a build.

## Some flow objects merge unrelated substances

**This is the most consequential one.** A flow object is supposed to be one
substance. In the current output, many are not.

Of 7,727 flow objects, **2,806 carry more than one InChIKey, and 2,252 carry two
or more distinct InChIKey skeletons.** The skeleton block of an InChIKey encodes
molecular connectivity — different skeletons mean structurally unrelated
substances. Those objects have merged things that are not the same. Those
figures are from a run made before the curated-CAS gate described below; they
have not yet been re-measured.

The cause is that chemical properties are accumulated rather than resolved.
When several sources supply a molecular formula or an InChIKey, all the values
are kept side by side in a bag, with no step that decides which is correct and
no link between a particular value and the provenance record that justifies it.
Fixing it in general requires agreeing source-precedence rules first, which has
not happened yet.

One cause of it has been removed. PubChem's CAS cross-reference index carries
vendor catalogue entries, so a vendor with the wrong CAS in its catalogue
attached an unrelated compound to a substance — magnesium bis(quinolin-8-olate)
onto a peroxyester, in the case that prompted the fix. Those links are now
dropped where PubChem's own curated CAS section contradicts them; see
[the curated-CAS gate](../concepts/../deciding/registry-numbers.md#the-curated-cas-gate-a-vendor-catalogue-is-not-a-registry).
It does not touch candidates that disagree for any other reason, and a CAS whose
candidates are all unattested is left exactly as ambiguous as it was.

A second cause has been removed. A registry number that names a UVCB, an
unspecified isomer or a commercial mixture denotes no single structure, but
PubChem answers it with one anyway — `1300-21-6`, dichloroethane with no isomer
stated, returns 1,1-dichloroethane, and gum turpentine returns triethyl citrate.
Where CAS Common Chemistry answers for a number and gives it no molecular
formula, no structure is now looked up through it; where it gives a formula and
no structure, a curated ruling decides, because ozone's record and
dichloroethane's are identical. See
[the structure gate](../concepts/../deciding/structures.md#the-structure-gate-a-registry-number-need-not-denote-a-structure).
On the 2026-08-07 build that withholds a structure from 181 flow objects and
dissolves 49 of the 105 InChIKey collisions. It is deliberately silent when the
Common Chemistry cache has no answer for a number, and when it has one the
pipeline cannot interpret.

A third cause has been removed, and it is the one that made the InChIKey signal
untrustworthy. A registry number is often registered with its stereochemistry
unstated — `4170-30-3` is crotonaldehyde with the *trans* isomer registered
separately as `123-73-9` — but PubChem and ChEBI both answer such a number with a
stereo-specific compound, because that is the kind of record they hold. The flow
object then carried a stereochemistry the substance does not have, and collided
under InChIKey with the isomer it had borrowed it from. Where Common Chemistry
publishes a flat structure for a number, a stereoisomer of it is no longer
attached from any source, and the structure CAS does publish is used instead.
See
[the stereochemistry gate](../concepts/../deciding/structures.md#the-stereochemistry-gate-a-flat-registration-is-a-statement).
That acts on 90 registry numbers across 100 flow objects, taking the "stereo
invented" band to nought while leaving every one of them with a structure.

A fourth cause has been removed. An InChIKey with the stereochemistry taken off
is the same substance as the key it was taken from — `QIVBCDIJIAJPQS-UHFFFAOYSA-N`
is `QIVBCDIJIAJPQS-VIFPVBQESA-N` without the layer that says which mirror image —
and it is also `DL-tryptophan`'s real key, so `L-tryptophan` publishing both read
as a substance with two candidate identities and matched a substance it is not.
The stages that write the slot now refuse a flat key for a skeleton the record
already states specifically, and withdraw it if the specific key arrives second.
On the 2026-08-12 build that is 427 values across 419 flow objects and 5,416
elementary flows; objects carrying more than one InChIKey fall from 679 to 306,
and the 46 shared flat keys that had a specific-key holder among them fall to
none. Nothing is lost: block 1 of an InChIKey hashes connectivity alone, so the
dropped string is the surviving one with block 2 replaced by `UHFFFAOYSA`, and a
consumer who wants it can write it out without a chemistry toolkit. A record
whose *only* key for a skeleton is flat keeps it — that is a substance registered
without stereochemistry, or the wrong-hit structure of
[#38](https://github.com/brightway-labs/brightway-flows/issues/38), and 47
of the 474 flat keys were that. See
[#50](https://github.com/brightway-labs/brightway-flows/issues/50).

What is left of the stereochemistry defect is smaller than it was first
reported. 91 flow objects held an InChIKey whose skeleton matched Common
Chemistry and whose stereo layer did not; 45 of those were never disagreements
at all, because CAS published a non-standard key for the number and no standard
key can equal one. Measured on the 2026-08-12 build, after the gate:

| | flow objects | what it is |
|---|---:|---|
| stereo **invented** | 0 | was 33; fixed by the gate above |
| stereo **conflict** | 5 | measures at 20 without the split below; both records standard and specific, and each states an arrangement the other contradicts — open, and a curation question. Was 8; three of those differed in charge rather than in shape, and are the band below |
| stereo **lost** | 0 | was 7; the structure CAS publishes is now read and published in place of the flat key. See below |
| **cas-undetermined** | 7 | not a disagreement: the registry's record leaves an arrangement blank that ours states, and the two agree everywhere both speak. Ours stands |
| **ours-undetermined** | 1 | our record has the blank instead. Five more were repaired from the registry; this one could not be. See below |
| **charge** | 6 | not a shape question at all: the object publishes CAS's substance with hydrogen ions added or taken away. 4 are settled from the registry's own answer, 2 stay open. See below |
| **incomparable** | 33 | not a disagreement: CAS's structure has no comparable standard form, so the two were never comparable. Was 36 — three were single atoms whose keys agreed with ours exactly |

A flat key *beside* a specific one is not a loss — the flat key states nothing
the specific one contradicts. It is no longer published either: see the fourth
cause above. Only an object with no specific key at all counts as a loss, and
that is what the table counts.

A fifth cause has been removed, and it is the "lost" band above. Where a number
states a stereochemistry that no source we look a structure up in can supply, the
structure CAS publishes is read, re-expressed as a standard key and published in
place of the flat one. That fires on **7 flow objects and 91 elementary flows**
on the 2026-08-12 build, and dissolves two InChIKey collisions that
[#50](https://github.com/brightway-labs/brightway-flows/issues/50)
explicitly left alone —
`Trans-4-tert-butylcyclohexanol` against `4-tert-butylcyclohexanol`, and
`4-tert-butylcyclohexyl Acetate, Cis` against `4-(tert-butyl)cyclohexyl Acetate`.
It is the only place the pipeline adds a structural claim rather than refusing
one, so the conditions on it are strict and are set out in
[restoring a stereochemistry no source holds](../concepts/../deciding/structures.md#restoring-a-stereochemistry-no-source-holds).
Each repair is reported in the same queue as a `restored` row at `info`.

A sixth cause has been removed, and it is the last one a rule can reach. A flow
object could hold **two** stereochemistry-bearing keys for one skeleton, one from
each lookup path, with nothing reconciling them — `Pyrethrin I` published both
`ROVGZAWFACYCSP-VUMXUWRFSA-N` and `ROVGZAWFACYCSP-NEWSRXKRSA-N`. Where one of
them is the structure CAS registers for the number, the others are withdrawn:
**8 flow objects, 106 elementary flows**, six of them pyrethrin esters where the
withdrawn key is the surviving one with the double-bond geometry left out. Where
*no* key matches the registry nothing is touched, because that is a conflict and
not a tie. See
[when the registry breaks a tie](../concepts/../deciding/structures.md#when-the-registry-breaks-a-tie-between-two-sources).
Each withdrawal is reported at `review`, naming the key that went and the one
that stayed.

A seventh cause has been removed, and it is a reading fault rather than a data
fault. "Both records specific and different" was one label over three findings,
because an InChIKey hashes every stereo layer at once: a record leaving one
corner of thirty blank gets a fingerprint as different from the complete
record's as inverting all thirty would give. Twelve of the twenty numbers turned
out to be one record simply not stating something the other did, agreeing
everywhere both spoke. Seven have the blank on the registry's side and need
nothing done; five had it on ours and are repaired from the registry, **5 flow
objects and 65 elementary flows**. `β-Endosulfan` and `Trans-nonachlor` are
among them, and they are why it matters: their published keys named a broader
substance than the registry number does, and for the endosulfans the corners
left blank are exactly what tells the two regulated isomers apart.
`α-Endosulfan` has a gap *and* a real conflict, so nothing is repaired there and
it carries both rows. See
[a gap is not a contradiction](../concepts/../deciding/structures.md#a-gap-is-not-a-contradiction).

An eighth cause has been removed, and it was never a stereochemistry defect at
all. An InChIKey's last block says how many hydrogen ions the substance carries,
and an object could publish the registry's own substance twice over — once
neutral and once ionised, an acid beside its ion, in the field that says what the
substance is. `(2R,3R)-2,3-dihydroxybutanedioic acid` published both
`FEWJPZIEWOKRBE-JCYAYHJZSA-N` and `FEWJPZIEWOKRBE-JCYAYHJZSA-L`, tartaric acid
and tartrate, whose shape hashes are identical. Charge is now tested before
shape, so these are a band of their own rather than a shape disagreement, and
where the registry's own answer is among the object's keys the other is
withdrawn: **4 flow objects, 52 elementary flows**. One of the four,
`Aminocaproic Acid`, was reported nowhere before — CAS registers the number
without a stereochemistry, and the gate that owns those has nothing to say about
charge.

The other 11 objects publishing a charge clash are mostly salts the registry
answers with a different skeleton altogether, so nothing is reproduced and
nothing is touched. Two objects are reported as open `protonation` rows at
`blocking` — `Cupferron` and the ammonium salt of `34274-28-7`, where the
registry does hold the number's structure and what the object publishes for it is
ionised. The rest clash without the registry saying anything either way. Finding
those needs no registry lookup, since two keys on one object differing only in
the last character is always this situation, and that check is still open. See
[an acid and its ion](../concepts/../deciding/structures.md#an-acid-and-its-ion-are-two-substances-not-two-shapes)
and [#54](https://github.com/brightway-labs/brightway-flows/issues/54).

The one open band cannot be settled by a rule, so it is reported rather than
acted on: it is the `stereo-disagreement` queue of the
[review application](../operating/review-app.md), at `blocking`, alongside the
bands that only look like a disagreement. The five rows still wearing the
`conflict` label are `Carbetamide` and its mirror image, `Nivalenol` with one
corner of eight inverted, `465-73-6`, `Ryanodine`, and `α-Endosulfan`, which
publishes three fingerprints at once and so carries an `ours-undetermined` row
as well.

Three rows that looked like the same sort of mislabelling have gone.
`Zinc-65`, `Radium-226` and `Radon-222` were reported as comparisons that could
not be made, against keys identical to their own, under an explanation naming a
cause that did not apply. Agreement is now tested against the key CAS published
before any conversion is attempted, and where a conversion does refuse it says
which of its three reasons applied. See
[#55](https://github.com/brightway-labs/brightway-flows/issues/55).

The same issue asked whether an isotopic label can be lost anywhere else, and
the answer is: not this way, and once. `Radon-222` publishes the fingerprint
`SYUHGPGVQRZVTB-IGMARMGPSA-N` beside the structure `InChI=1S/Rn` — radon-222's
fingerprint beside plain radon's structure. It is the only object in the list
where a specific key sits beside a bare, unlabelled element structure, and no
round trip dropped the label: that structure was derived from the alternative
label `radon(0)`, which the object carries because ChEBI's record for plain
radon is attached to it alongside radon-222's. A source record for a
neighbouring substance is
[#38](https://github.com/brightway-labs/brightway-flows/issues/38) and
[#6](https://github.com/brightway-labs/brightway-flows/issues/6), where
`Radium-226`'s `[RaH2]` belongs too.

One rule that reads a fingerprint as a shape does now ask the structure first.
`_drop_superseded_stereo_inchikeys` withdraws a key when another on the same
skeleton is the one the registry reproduces, on the reasoning that the two were
one substance under two identities. Two nuclides of one element present to it
identically — `HCWPIIXVSYCSAN-IGMARMGPSA-N` and `HCWPIIXVSYCSAN-YPZZEJLDSA-N`
are radium-226 and radium-224 — and withdrawing one of those would delete a
substance. It withdraws nothing today that it did before: each of the 37 flow
objects carrying a number CAS registers as an isotope holds a single key for the
skeleton.

**One known gap in that queue.** It classifies structures as they arrive through
the ChEBI and PubChem CAS lookups, so a structure that reaches a flow object
another way — a source list's own SMILES, or RDKit deriving a key from it — is
never offered to it. On this build that hides exactly one row, `α-Cypermethrin`
(67375-30-8), whose key RDKit derived from the source structure. Closing it
means classifying the *published* structure after the properties are resolved,
which is a different stage from the one that looks up candidates.

See [#42](https://github.com/brightway-labs/brightway-flows/issues/42).

**What to do about it:** if you rely on flow object identity, check whether the
object carries more than one InChIKey skeleton and treat those cases as
unresolved. `/checks/shared-labels` and
`/checks/formula-mismatches` surface related symptoms.

## Some nuclides still publish the element's registry number

Nuclides are grouped by nuclide rather than by CAS, so `Uranium-238` no longer
shares a flow object with elemental uranium and `Thorium-232` no longer sits
inside the thorium element object. That fixes the grouping. It does not fix
every published identifier.

`uranium-238` had the element's CAS corrected to `24678-82-8` in every source
list's manual fixes — EF 3.1's and all five registered ecoinvent versions' —
because that number is known. Two objects still carry an element's number as
their own:

| Flow object | CAS it publishes | Whose it is |
|---|---|---|
| `Thorium-232` | 7440-29-1 | thorium, the element |
| `Praseodymium-147` | 7440-10-0 | praseodymium, the element |

No nuclide-specific number is cited for either, and inventing one would be worse
than publishing the vendor's. Both source lists ship these values; nothing in
this pipeline put them there.

**What to do about it:** a nuclide's identity in this list is its flow object,
not its CAS. If you join on CAS you will re-merge these two with their elements —
which is precisely what the layering was changed to stop
([#17](https://github.com/brightway-labs/brightway-flows/issues/17)).

## Four flow objects have no elementary flows

`chemrof:has_element` links an isotope to the flow object for its element, and
its declared range is `ChemicalElement`, so that object has to exist for the
triple to say anything. Americium, Neptunium, Promethium and Technetium appear
in both source lists **only as nuclides** — there is no `Americium` flow — so
five isotope objects had nothing to point at.

Those four elements are now minted by the element enrichment, and they are the
first flow objects in the list with no elementary flows.

That is what they are, rather than a defect: a flow object is a substance and an
elementary flow is an occurrence, and this list has americium as a substance
without having an occurrence of americium. Both layers publish as
`skos:Concept`, so a concept with no occurrences is a vocabulary entry.

**What to do about it:** do not assume a flow object has at least one
elementary flow. `/flow-objects` counts them with a subquery and shows nought;
code that joins the two layers should use an outer join. The minted objects
are identifiable by `created_from.resolver` —
`element_enrichment_minted_element_v1` — and counted by the run as
`element_flow_object_count_added`, with their names in
`element_flow_object_names_added`.

An element is minted only when the list already carries its isotopes, so this
completes a substance the list is already publishing rather than importing the
periodic table. If a source list ever does carry an `Americium` flow, that flow
becomes the element's object and nothing is minted — but the identifier changes
on that day, because `element:Am` is not the CAS a source flow would bring.

## Origin-qualified flows get structural enrichment intended to be withheld

The three structure-deriving stages — OPSIN, RDKit pre-consensus and RDKit
authoritative — were written to skip flows carrying an origin qualifier, and to
exclude them from the InChIKey uniqueness index. They never did.

Each guard tested `origin_qualifier` on the flow. That field lives on the
**flow object**, not the flow, and appears in no input, so the condition was
always false. Nothing surfaced it: the record shim returned `None` for an
unknown field rather than raising. Removing the shim made all three guards
visibly dead, and they were deleted rather than repaired — restoring the
intended behaviour changes which flows get enriched, which is a decision about
the data rather than a refactor.

Two effects on the current output:

- Biogenic, fossil, and green/blue/grey water variants receive RDKit-computed
  structural properties that were meant to be left alone.
- Those variants count towards InChIKey uniqueness. A substance whose only
  structural twin is its own qualified variant is therefore not treated as
  unique, and misses the authoritative-replacement path.

**What to do about it:** if you are comparing structural properties across
qualified and unqualified variants of the same substance, do not assume the
qualified ones were left in their source state. Nothing here is *wrong* per
flow — the computed values are correct for the structure — but the intended
separation is not in force.

## A published label can name something broader than the flow

Preferred labels are replaced by a rule that takes the name Common Chemistry and
ChEBI both give a flow's CAS. It applies without a curator ruling on it, and the
evidence for that is an audit of **identity** — is the replacement a name the
cited CAS actually has? Over one full run it found 0 of 724 pairs asserting an
identity neither source supports, against 80 of 114 for a PubChem-backed rule
that was removed for it.

That question cannot see **specificity**. `Xylene (all isomers)` → `Xylene`
passes it, because `xylene` is a name CAS 1330-20-7 holds and
`xylene (all isomers)` is not — so a rename that drops a scope qualifier scores
in the same bucket as `Tetraconazole` replacing its systematic name.

In the 2026-08-06 run the rule applied 741 distinct renames over 9,530 flows.
None asserted an unsupported identity. 71 of them drop a qualifier the current
name carries — a scope word, a locant, an oxidation state, a salt or hydrate
word — and no chemist has read those yet.

**What to do about it:** if you key anything on `prefLabel`, keep the flow uuid
as the identity and treat the label as a display name. The rule adds the
original name to the flow's `altLabel` list when it renames, so the narrower
name is generally still on the record. To see the renames for yourself:

```bash
tools/build_scope_narrowing_shortlist.py
```

It writes `docs/reference/scope-narrowing-shortlist.json`: every applied rename,
audited for identity, with the qualifier-loss shortlist ordered first. A row can
be ruled on by moving it into `preferred-label-decisions.json` with
`"decision": "reject"`, which overrides the rule on the next run.

## A name can reach one substance and still name a second one

The merge places a source row on a flow object by whatever evidence it has: a
published correspondence table, a registry number, a curated override. None of
those leaves the row's **name** on the object it lands on. So a name can be the
whole of what one list calls a substance and be reachable nowhere — and the next
list that ships that string finds nothing, mints the substance again, and the
same quantity is published twice under two ids.

Nothing about the first list's run shows this. It surfaces only when a second
list happens to carry the same name, which is how #74 found it: ecoinvent's
`Energy, gross calorific value, in biomass` reaches EF 3.1's flow through a
correspondence table, EF publishes it as `Biomass`, and BAFU's identical string
became a second substance carrying 394 datasets' worth of wood.

Measured on the 2026-08-13 build, **129 names** over **467 source rows** are in
that state — unreachable where they were placed, and already the published name
of some other flow object. 74 of them are land occupation and transformation
classes, which are being reworked separately (#66); the other 55 carry 319 rows
and include `Heat, Waste` against `Waste Heat`, `Benzo(k)fluoranthene` against
`Benzo[k]fluoranthene`, and the whole `Particulates, < 2.5 um` family against
`Particles (PM2.5)`.

Not all 129 are one substance twice. `Penoxsulam` reaching `Granite` is a trade
name matching the wrong thing, and a few are genuinely two substances that carry
no evidence saying so.

**What to do about it:** if you are totalling a quantity across source lists,
check that the flows you are adding are the same flow object and not two objects
with the same name. To see the list for yourself:

```bash
tools/build_unreachable_name_shortlist.py
```

It writes `docs/reference/unreachable-name-shortlist.json`: every name that has
already split a substance, with the object it reaches, what that object publishes
instead, the object it names, and what decided each placement. It shortlists
rather than rules — pairs the list already tells apart by a registry number or an
origin qualifier are dropped, and the rest want a reader. A row is fixed by
giving the name somewhere to land, which for a list with no correspondence table
is a synonym in its manual fixes, as `COD, Chemical Oxygen Demand` and
`Energy, gross calorific value, in biomass` have.

## The published JSON is not valid JSON-LD

The outputs use JSON-LD vocabulary — `@value`, `@id`, `@type`, IRI keys — and
look like linked data, but they do not currently expand correctly. Verified with
`pyld`:

- A representative flow object expands to `[]`, because the terms are undefined.
  The generated `@context` addresses part of this.
- `{"@value": [list]}` is a hard JSON-LD syntax error; the accumulator bags
  described above produce exactly that shape.
- A `@value` with a sibling `provenance` key is also a syntax error. Per-value
  provenance cannot sit next to `@value` — it needs a separate reified graph.

**What to do about it:** treat the files as ordinary JSON with IRI-shaped keys.
Do not feed them to a JSON-LD processor and expect the triples you want.

## Provenance dominates the payload

Per-value provenance is roughly **70% of the flow-object record** — measured at
117 MB with it and about 36 MB without, when that layer was still written to a
file. It is now a JSON column in `consensus-flows.sqlite3` and the ratio is
unchanged. If you only need the substance data, the smaller
`harmonised-flows-simple.json.gz` carries none of it. The provenance is not
redundant, but it is not free either, and moving it to a sidecar graph is
blocked on the JSON-LD fix above.

## `source_refs` is missing from the published files

Elementary flows carry a `source_refs` list naming every source flow that
contributed to them. It is the project's audit trail, and the record classes
require it — but the published export strips it before writing.

**What to do about it:** for source traceability, read the
`elementary_flow_sources` table in `consensus-flows.sqlite3`, or open the flow
in the review application, where the same rows are the **Source lists** section
of its detail page. The data exists; it is just not in the published file. This
is a known gap between the classes and the export rather than a missing
feature.

The table is also the *only* place it exists. `elementary_flows.flow_json`
carried a second copy until
[#30](https://github.com/brightway-labs/brightway-flows/issues/30), and
that copy was the build-time answer: the merge appends to the table and to no
payload, so on the 2026-08-07 build 7,794 of 94,433 stored copies were short —
the payload named the base list's single source where the table named two to 38.
The field is no longer stored, which leaves one answer rather than a complete one
and a silently partial one.

**In artifacts built before 2026-08-07, every base-list reference in that table
appears twice** — see *A source reference is stored once*, below.

## Artifacts in the data directory may be stale

The layered artifacts in a typical data directory have often been overwritten by
bounded test runs, and a fresh `build` is generally needed to
regenerate the real merge outputs. Files are whatever the last run left there.

Check the `stats` block and the modification time before trusting an artifact.
A `flow_object_count` in the hundreds is a test run.

## Context resolution is fixed, but old artifacts may not be

An earlier version of the merge rebuilt structured contexts by zipping display
strings positionally against a fixed key tuple. Because the display form orders
fields for reading and drops `"Unknown"` values, this silently mis-assigned
fields — water bodies landed in vertical strata, and the `"Indoor"` marker was
written as a stratum. It was wrong for **37 of 49** registered contexts and
corrupted 231 elementary flows.

The producer is fixed, and a validation gate now rejects contexts that
contradict their own `context_iri`, so a fresh run is correct. But artifacts
generated before the fix still contain the corrupted contexts.

**What to do about it:** always resolve a context from `context_iri`. Never
reconstruct one by parsing display strings — that is precisely the operation
that caused this.

## The context taxonomy will change

60 contexts is a deliberate minimum: an attribute is only included when
characterisation factors actually differ across its values. As LCIA methods
develop, that judgement changes. `Space` as a vertical stratum is an open
question. Context IRIs are stable identifiers, but the *set* is not frozen.

## Some integrations are incomplete

Adding a list is a manifest in `data/sources/`
([#2](https://github.com/brightway-labs/brightway-flows/issues/2)) rather
than a Python change
([#12](https://github.com/brightway-labs/brightway-flows/issues/12)). What
a new list still has to be given by hand is its context mapping: a row whose
compartment maps to no consensus IRI stops a merge rather than being guessed at.

Stepwise 2006 was the outstanding case on this page and is no longer one. It is
registered as a source list
([#164](https://github.com/brightway-labs/brightway-flows/issues/164)) and
merged in the base build's default source set
([#169](https://github.com/brightway-labs/brightway-flows/issues/169)), last
at `merge_priority` 300 because its rows are the weakest identified of any
registered list — a SimaPro `{methods}` CSV ships no flow identifiers, so each
one is derived from the name, the compartment and the unit. On the four-list
build of 2026-08-29 6,058 of its rows merged: 5,915 onto flows that already
existed, 141 minting new ones, and 2 matching nothing.

BAFU 2026 v1 is registered ([#4](https://github.com/brightway-labs/brightway-flows/issues/4)),
and what remains is matching rather than reachability. It carries no flow
identifier of its own, so a row is matched on a registry number where it ships
one and on its name where it does not. It puts the geography in the flow
name (`Water, RER`, `Nitrogen dioxide, RAF`), where this list does not model it
at all; the adapter now takes the place out of the name and into a field of its
own ([#65](https://github.com/brightway-labs/brightway-flows/issues/65)),
so each of those 181 names asks the same question its unregionalised sibling
asks, and a row that cannot answer it creates one flow between them rather than
a water per country. For most of them the question is still unanswered:
`water` is the alternative label of ten substances, and `water, river` is the
preferred label of none, because this list holds one water and puts the river
in the context. Its rows that read as bookkeeping were three families, and
[#69](https://github.com/brightway-labs/brightway-flows/issues/69) decided
two of them. The `Energy, from X` carriers are not bookkeeping at all: they are
flows this list already publishes, because EF 3.1 accounts fossil energy
carriers by energy content rather than by mass, and they are collapsed onto
them. The eleven `resource correction` rows are bookkeeping, and are still not
flows of their own: each is a negative amount of the resource it corrects — BAFU
writes that resource's own registry number on nine of them — so each lands on
the resource's flow, which is what makes a correction and the extraction it
corrects add up. The aggregate indicators are the family still open: `COD`,
`BOD5` and `TOC` reach EF's own aggregate flows under BAFU's longer spellings,
but `AOX, Adsorbable Organic Halogen as Cl` reaches nothing and creates a
substance of its own.

See [Choosing sources](../operating/sources.md).

## The review app counts both SMILES slots as candidates

`/flow-objects/<id>` warns that a substance "carries N candidate structures" when
it holds more than one SMILES, and it counts `isomeric_smiles_string` and
`smiles_string` together. A substance with one structure whose stereochemistry
is known holds two strings by design — the stereo form in one slot, the graph in
the other — so the note fires on it.

Collapsing duplicate spellings took the objects showing that note from 5,762 to
3,007, and **698 of the remainder carry at most one structure**: the note is
counting the split, not ambiguity. The substances that are genuinely ambiguous
are the rest, and are
[#6](https://github.com/brightway-labs/brightway-flows/issues/6).

## The coarse particulate band carries PM10's number by this list's own convention

EF 3.1 characterises `Particles (PM2.5)`, `Particles (PM10)` and the two windows
finer than PM2.5, and states nothing for `Particles (PM2.5 - PM10)`, the coarse
band, in any compartment. Every list here ships a coarse-band row — ecoinvent's
`Particulates, > 2.5 um, and < 10um`, renamed `Particulate Matter, > 2.5 um and
< 10um` at 3.9.1, BAFU's and AGRIBALYSE's under the 3.8 spelling — and until
2 September 2026 those rows scored either zero or PM10's number depending on
which list they came from.

Zero was the faithful mapping. PM10's number was
[#37](https://github.com/brightway-labs/brightway-flows/issues/37): five
curated rows sent ecoinvent's coarse fraction to EF's `particles (PM10)` so that
a score computed from this list would reproduce what brightway2 and other tools
report — ecoinvent 3.8 apos characterised faithfully came out 14.3 % below the
same inventory in brightway2 with EF 3.0 (2.58004e-09 against 3.01204e-09
disease incidence per kWh), and that one flow was the whole gap
([#32](https://github.com/brightway-labs/brightway-flows/issues/32)). The
cost was a published `skos:exactMatch` saying that ecoinvent's 2.5–10 µm
fraction *is* PM10, which it is not, and a second vendor briefly inheriting the
trade by spelling ([#153](https://github.com/brightway-labs/brightway-flows/issues/153)).

Both are gone. The five rows are retired, ecoinvent's coarse rows land on
`Particles (PM2.5 - PM10)` like everyone else's, and the band carries PM10's
number under EF 3.1 in each air compartment by the size-window convention in
`data/particle-size-carry-rules.json` — `derivation: carried`, from the PM10
flow of the same compartment
([how a factor is decided](../deciding-factors/blanks.md)). The score does not
move; the assertion does. The same convention is what gives the band Stepwise
2006's PM10 number, and what leaves particles above ten micrometres blank under
EF, where nothing above them is characterised.

**The concern that remains, on the record.** EF 3.1's PM10 factor is exactly
**0.23 ×** its PM2.5 factor in every compartment, and PM0.2, PM0.2 – PM2.5 and
PM2.5 all carry the *same* factor within a compartment. That reads as "the fine
fraction gets the full effect factor, and 0.23 is a fixed assumed fine share for
a flow reported as bulk PM10" — not as a modelled coarse-fraction effect factor.
On that reading, giving the number to a flow defined as 2.5–10 µm credits fine
particulate that ecoinvent already reports separately as `Particulates, < 2.5
um`, and a score built this way double-counts a slice of the fine fraction.
Against it, the ecoinvent Centre and GreenDelta both give the coarse band that
number in their own EF 3.1 implementations. The project owner ruled for the
convention on 2 September 2026 with this concern recorded beside it.

**What to do about it:** if you share the concern, or you care about the coarse
fraction as a physical quantity rather than as an input to this one indicator,
drop the factors whose `derivation` is `carried` on `Particles (PM2.5 - PM10)`
under EF's particulate matter category. Nothing on the mapping needs re-mapping
any more: every list's coarse rows are on the band they name.

## ecoinvent's trivalent chromium is characterised as trivalent, unlike elsewhere

ecoinvent's `Chromium III` — `Chromium` in 3.8, same uuids — is mapped to EF 3.1's
`chromium (iii)` in all nine of its air and soil contexts. Every published
correspondence table sends those nine to EF's unspeciated `chromium` instead,
while sending the same substance in water to `chromium (iii)`, and other EF
implementations follow them. This one does not
([#45](https://github.com/brightway-labs/brightway-flows/issues/45)).

The reason to diverge: EF 3.1 gives unspeciated `chromium` exactly the factors it
gives `chromium (vi)` — identical values in all eleven contexts and all six
toxicity methods. Following the published tables therefore scores trivalent
chromium as hexavalent. In air, unspecified, that is Human toxicity, cancer
7.8078e-05 where `chromium (iii)` has no factor at all, Human toxicity,
non-cancer 4.1364e-06 against 1.7697e-09, and Ecotoxicity, freshwater 4288.0
against 333.4.

**What to expect:** an inventory reporting chromium to air or soil scores lower
here than in a tool that follows the published tables, and its contribution to
Human toxicity, cancer from that flow goes to zero. Chromium VI is unaffected —
ecoinvent reports it as its own flow, mapped to `chromium (vi)` by everyone
including this list. The divergence is confined to the trivalent flow.

This reaches ecoinvent 3.8 too, where those uuids are named `Chromium` with CAS
7440-47-3 rather than `Chromium III` with CAS 16065-83-1. The reading is that
3.9.1's rename clarified rather than changed: 3.8 already shipped a separate
`Chromium VI` flow in the same nine contexts, so its unspeciated flow was in
practice everything-but-hexavalent. If you disagree with that reading, the nine
rows are in `src/brightway_flows/data/ecoinvent-match-overrides.json` and
deleting them restores the published tables' target.

## One air compartment names two situations, and neither is what gets published

Every source list splits outdoor air differently, and one compartment names two
situations at once. It reaches this list under three spellings — EF 3.1's
`Emissions to non-urban air or from high stacks` (7,308 flows), ecoinvent's
`air / non-urban air or from high stacks` (390 flows in 3.8, rising to 1,237 in
3.12) and BAFU's `emissions to air / low. pop.` (256 flows, SimaPro's spelling
of ecoinvent v2's `low population density`).

The compartment means *an emission in the countryside, **or** an emission from a
tall stack anywhere*, and nothing in a flow says which. Both literal readings
are expressible and both are wrong most of the time: `High stack, >150 meters`
says a dairy barn's ammonia left a 150-metre chimney, and `Ground level → Rural`
says a power-station plume was released at head height. All three lists are now
published as

```
Environmental → Air → Medium stack, <150 meters → Rural (<1000 people/square mile)
```

which is neither reading, and is chosen because it is what EF's own numbers say
the compartment behaves like. In all 40 (flow, method) pairs where this
compartment and one of EF's narrow non-urban compartments are both characterised,
EF gives this one exactly the factor it gives `Emissions to non-urban air high
stack`. For `particles (PM2.5)` under EF-particulate Matter:

| EF 3.1 compartment | Factor | Published here as |
|---|---|---|
| `non-urban air close to ground` | 1.13763e-05 | Ground level → Rural |
| `non-urban air low stack` | 3.92285e-06 | Low stack, <25 m → Rural |
| **`non-urban air or from high stacks`** | **3.01757e-06** | **Medium stack, <150 m → Rural** |
| `non-urban air high stack` | 3.01757e-06 | Medium stack, <150 m → Rural |
| `non-urban air very high stack` | 1.62949e-06 | High stack, >150 m → Rural |

**What this costs.** An emission that really did leave a >150-metre stack is
published as a sub-150-metre one — a factor of 1.85 in EF's own particulate
numbers, against the factor of 3.8 the other way for reading it as ground level.
The rural qualifier is safe, since the compartment asserts non-urban in every
spelling, but the stack height is inferred from characterisation rather than
stated by any source. **Do not read `Medium stack, <150 meters` on one of these
flows as a statement about a physical stack.** It says the source list put this
release in a compartment EF characterises as a sub-150-metre rural release.

The decision is taken once for all three lists, which is what
[#79](https://github.com/brightway-labs/brightway-flows/issues/79) asked
for: moving one alone would split three spellings of one compartment into two
consensus contexts. The rules are the `non-urban air or from high stacks` and
`low. pop.` rows in
`src/brightway_flows/data/context-manual-mapping.json`, each carrying this
reasoning.

**Two consequences worth knowing.** EF alone also ships the narrow
`Emissions to non-urban air high stack` (16 flows), which maps to the same
context, so those 16 collapse onto their twins in the union compartment. Fifteen
of the pairs agree on name, unit, CAS and every characterisation factor; the
sixteenth, `sulfur trioxide`, has 5 factors on the union row against 2 on the
narrow one, a strict subset, and the rulings union factors onto the survivor. No
factor is lost either way.

**And the phrase misleads a curator too.** Seven decisions in
`elementary-flow-collision-decisions.json` — each one saying that two rows in
this compartment are one flow — were written against
`Air → High stack, >150 meters` rather than against the compartment above,
because that is the half of EF's name a reader remembers. A decision is stored
under the compartment it names, so all seven were filed against a compartment
those flows are not in and quietly did nothing: three substances a curator had
already decided about went on being published twice for four months, and the
build reported the seven the same way it reports a decision about a substance
this run did not load. They are corrected, and the build now says when a
decision names a compartment its own flows are not in
([#106](https://github.com/brightway-labs/brightway-flows/issues/106)).
When writing one, take the compartment from the review queue's own row rather
than from the source list's words for it.

And `Air → High stack, >150 meters → Unknown` is now a context no source list
names. So is `Air → Ground level → Unknown`, for a different reason: ecoinvent's
`air / unspecified` used to be published there, asserting a stratum the
compartment does not name and splitting it from EF's `Emissions to air,
unspecified` and BAFU's `emissions to air / unspecified`, which both sit on
`Air → Unknown`. It split ecoinvent from itself as well — the rows the
correspondence tables match onto EF's flow were already in `Air → Unknown`, and
only the rows that found no EF partner stayed behind, which on the 2026-08-13
build was all **54** flows there, every one an ecoinvent creation, none of them
characterised, in a context no other list could reach. All three lists now agree
there too.

## A forestry or industrial soil emission is characterised by one implementation of EF 3.1 and not the other

Both source lists that ship a forestry soil compartment point it at the same
consensus context, and both that ship an industrial soil compartment point it at
the same one. ecoinvent's `soil / forestry` and BAFU's
`emissions to soil / forestry` map to

```
Environmental → Ground → Silvicultural
```

and ecoinvent's `soil / industrial` and BAFU's `emissions to soil / industrial`
map to `Environmental → Ground → Industrial`. On the 2026-08-15 build all 144
rows of the two industrial compartments are published there, and 994 of the 995
rows of the two forestry ones — the exception being one row coarsened onto soil,
unspecified, which is covered below.

**Who characterises the flows they land on depends on which implementation of EF
3.1 you ask**, and until `characterise` there was only one to ask. This entry
used to say "nothing characterises them", and that was true of the only
implementation this list published:

| Ask | And the answer is |
|---|---|
| **EF 3.1 as the JRC published it** | Nothing. EF's flow list has no forestry or industrial soil compartment, and the JRC characterises the flows it ships. |
| **EF 3.1 as the ecoinvent Centre implemented it** | It characterises them. Its own flow list *has* `soil / forestry`, so it had to say something about it — atrazine there carries 6 factors. |
| **This list** | It publishes ecoinvent's number where that number is demonstrably not ecoinvent's own science — the same substance already carries it in a neighbouring compartment within tolerance, or another flow of the category publishes it bit for bit — marked `restated` so a reader can find the twin. Atrazine's six forestry-soil factors are published that way. What that rule cannot reach is a number of ecoinvent's own, and adopting one of those for a flow the method's own publisher never characterised is a decision, so it goes to the `proposed-factor` queue and waits for a curator. |

`elementary_flows.lcia_factor_count` is the JRC's count and keeps that meaning,
so a flow here still reads as uncharacterised in that column. The flow's page in
the review application shows all three, and `lcia-factors.json.gz` publishes all
three. See [Characterisation factors](../concepts/factors.md).

That is what a decision taken in
[#84](https://github.com/brightway-labs/brightway-flows/issues/84) cost,
and it is worth reading what it bought.

**What used to happen.** A compartment rule decides where a row goes only when
the row creates a new flow. A row that matched an existing flow took that flow's
context instead, and for forestry and industrial soil most rows match — through
the correspondence tables, onto EF. EF's Ground flows sit in exactly four
places — `Agricultural` (7,176), `Unknown` (7,155), `Non-agricultural` (7,154)
and `Industrial` (4) — so the tables route both compartments onto
`Emissions to non-agricultural soil`. On the 2026-08-15 build (run
`2b3cb84e8019`, merging ecoinvent 3.8, ecoinvent 3.12 and BAFU 2026-v1):

| Source rows | Published as non-agricultural | Published on the compartment they named |
|---|---:|---:|
| ecoinvent `soil / forestry` (993) | 916 | 72 |
| ecoinvent `soil / industrial` (96) | 92 | 4 |
| BAFU `emissions to soil / forestry` (2) | 0 | 2 |
| BAFU `emissions to soil / industrial` (48) | 0 | 48 |

So **whether a forestry emission was published as silvicultural or as
non-agricultural was decided by whether EF happens to ship the substance**, which
is not a fact about the emission. Atrazine and pyrethrins are both sprayed on
forest and both filed by ecoinvent in `soil / forestry`; atrazine came out
non-agricultural because EF ships an atrazine flow there and the table matched
ecoinvent's row onto it, and pyrethrins came out silvicultural because no partner
existed. Industrial soil showed the same thing between the lists rather than
inside one: both lists say industrial, and 92 of ecoinvent's rows were pulled off
the compartment all 48 of BAFU's stayed on.

**What happens now.** A correspondence table names the substance; the compartment
stays the row's own. The table is not wrong to point at non-agricultural soil —
EF has no forestry soil, so naming the nearest flow EF has is the only thing a
correspondence table can do here — so the pair stays in
`correspondence-context-routing.json` as a permitted coarsening, marked
`"publishable": false`. That flag is the whole of the change: the guard over the
tables goes on permitting the pair, and the merge stops publishing a row on it.

**What it cost.** On that build the flows ecoinvent's 993 forestry rows reached
carried **3,084** characterisation factors between them, and the flows its 96
industrial rows reached carried **292**. Every one of those rows now lands on a
flow with none, and the list holds **865** flows it did not hold before — 821 in
`Silvicultural`, 44 in `Industrial` — every one of them uncharacterised. Nothing
was deleted: EF's own non-agricultural flows keep their factors, and not one
published flow changed its factor count, its context or its deprecation. But the
list no longer hands a consumer a factor for an emission it has filed as
silvicultural.

**The factor it was handing over was a specific number, not a neutral one.** EF
characterises 6,578 substances in both agricultural and non-agricultural soil,
and **4,746** of them carry a different factor in the two. Atrazine is one:
under `Human toxicity, non-cancer` it is 3.70e-07 in agricultural soil and
2.86e-08 in non-agricultural, a factor of 13. So publishing a forest pesticide as
a non-agricultural emission was not a coarsening that dropped detail and asserted
nothing; it picked one of EF's two soil numbers and applied it.

**What a consumer should do about it.** There are now two defensible answers and
the list publishes the evidence for both. Read the factor from the same
substance's non-agricultural flow, deliberately, and record that as an assumption
of the assessment — or read the ecoinvent Centre's factor for the silvicultural
flow itself, which is a number somebody stated about exactly this compartment.
Either way it is a modelling judgement, which is why the decision went this way:
an emission a source says happened on forest soil is published as one, and
choosing the factor to read for it belongs to whoever is doing the modelling.

**How much of the list this applies to, measured.** 4,626 (flow, category) pairs
carry no factor of any implementation while a *broader* context of the same
substance does — 1,252 flows over 978 substances, and 4,253 of them in exactly
three compartments: 3,045 in `Ground → Silvicultural`, 1,039 in
`Water → Unconfined aquifer`, 169 in `Ground → Industrial`. Publishing them by a
declared fallback rule was designed and then set aside for the reason above: it
would pick the broader number on the consumer's behalf and label it as this
list's decision. The join that does it deliberately is one line, and
`plans/lcia-factors.md` §4.3 records the decision not to take it for you.

**A row can still be coarsened onto `Ground → Unknown`, and one is.** ecoinvent
3.12's `Thifensulfuron` in `soil / forestry` is published as an emission to soil,
unspecified, because the substance has a flow there, none in silvicultural, and
`Unknown` on the geography axis is the absence of a claim rather than a competing
one. That coarsening is allowed on purpose, by the same rule that lets a lake
release be published as a release to water. It is why the expectations for #84
name substances rather than claiming the whole compartment.

**Neither `Forest` nor `Silvicultural` is reachable from EF 3.1.** EF's only
forest vocabulary is 22 land occupation and transformation flows, which are in
the `Land Use` dimension, not `Ground`. `Ground → Forest` is a context no list
names at all — `forestry` names a management practice and `Forest` is a land
cover, and [#77](https://github.com/brightway-labs/brightway-flows/issues/77)
moved BAFU off it — and it stays in the vocabulary for a source that means the
cover.

## The ecoinvent Centre's implementation of EF 3.1 states no number where the JRC does

Measured on the full build of 2026-08-17, over the two implementations
`characterise` publishes. Restricted to flows ecoinvent's *own* list reaches —
9,407 of them — because an implementation cannot drop a factor for a flow it has
never had. That larger asymmetry is the coverage report's subject rather than
this entry's; see [Characterisation factors](../concepts/factors.md).

**161 factors, over 60 flows and 12 impact categories.** The JRC states a
non-zero number, ecoinvent's list has the flow, and its workbook says nothing
about it. The largest populations are `Ecotoxicity, freshwater` (39 with its
organics twin), `Human toxicity, non-cancer` (26 with its twin) and `Water use`
(8); the flows are mostly pesticides and industrial intermediates —
1,1,2-trichloroethane loses 6, glufosinate ammonium salt, oxathiapiprolin and
fenpyroximate 4 each. A further 3,167 are ones where the JRC states a **zero**,
which is a weaker claim to lose: "assessed, and zero" is worth publishing
([#47](https://github.com/brightway-labs/brightway-flows/issues/47)) but
its absence changes no result.

**A much larger number is structural rather than a drop.** EF states a geography
on 42,871 of its factors and ecoinvent's workbook states none at all, so on the
raw count 33,565 more "disappear" — every located EF factor has no ecoinvent
counterpart by construction. Those are not a gap in ecoinvent's implementation;
they are two file formats, one of which can say `ES-CA` and one of which cannot.
A comparison that lumped them in with the 161 would report 33,726 and mean
almost nothing by it.

**Neither number is an error, and this list does not resolve them.** Where only
one implementation speaks, this list publishes that number as `sole` and says
who said it. What a consumer needs to know is that "the ecoinvent Centre's EF
3.1" is not a superset or a subset of "the JRC's EF 3.1" in either direction:
4,372 factors go the other way, ecoinvent characterising flows the JRC does not.
Both directions are in `lcia-differences.json` and under
[`/factors`](../operating/review-app.md) in the review application.

## Four substances have no human-toxicity factor in this list's implementation of EF 3.1

EF 3.1's toxicity categories are USEtox 2.1, by the JRC's own account. For the two
human-health ones the LC-Impact result workbook runs the same model and publishes
the answer as damage rather than as a midpoint — cases of disease, stated as the
years of healthy life they cost — and over the substances where the two agree the
ratio between them is exactly 11.5 and 2.7, the model's own severity constants. So
the two are the same numbers in different units, and a substance where they are not
is a disagreement about the substance.

**Four substances disagree by more than a hundredfold in every compartment:**
biphenyl, o-phenylphenol, benfluralin and the 2,4/2,6-toluenediisocyanate mixture,
all in non-cancer human toxicity. The worked example is biphenyl, an ordinary
industrial chemical: EF 3.1 characterises a kilogram emitted to urban air at
0.19957 CTUh — two hundred cases of disease per tonne, and third of the 3,380
substances EF characterises for non-cancer human toxicity there, above mercury —
where USEtox 2.1 gives 0.00000014. The narrowest of the four is benfluralin at
133× and the widest biphenyl at 1,381,461×.

| Ask | And the answer is |
|---|---|
| **EF 3.1 as the JRC published it** | 0.19957. Unchanged, in the same table and the same file as before: this list publishes what the JRC published. |
| **EF 3.1 as the ecoinvent Centre implemented it** | The same number, where its flow list reaches the flow. It transcribed the same file. |
| **This list** | Nothing, for all 110 factors of those four substances — every context, not only the six the models were compared in. The question is in the `contradicted-factor` queue as 8 items, one per substance and category spelling, each carrying both numbers and the file the model's came from. |

**Freshwater ecotoxicity is not compared, and 34 further pairs are therefore not
here.** They were measured — the widest is dodecyl methacrylate, where EF gives
110,460 CTUe to a kilogram in fresh water and the workbook 0.53 — and this list
publishes EF's number for every one of them. The reason is that the two
publications are not counting the same thing in that category. The workbook's
ecotoxicity sheet is LC-Impact's ecosystem-quality result, a potentially
*disappeared* fraction of species, published beside marine and terrestrial numbers
EF does not characterise at all; EF's CTUe is a potentially *affected* fraction.
The constant between them, 0.0175906, is fitted across two models rather than
converting within one, and the fit is loose where the human-health ones are exact:
over the substances not in dispute, 55.3% of the cancer factors and 32.5% of the
non-cancer ones land within 1% of the model, against 20.0% of the ecotoxicity
ones, whose middle half runs from 0.45× to 1.06× where cancer's runs from 0.9996×
to 1.043× (measured 2026-08-21 over 14,921 ecotoxicity and 6,312 human-toxicity
comparisons). A gap measured across that, however wide, does not say EF's number
is wrong — so withdrawing a factor on it would be a decision taken on a scale
mismatch. The measurements stay in
`data/lcia-underlying-model-factors.json`; nothing is asked about them.

**What a consumer should do about it.** A toxicity result computed from this
list's implementation will be missing these four substances, and one computed from
either published implementation will include EF's number. Which is right is
exactly what nobody has established: the JRC may have adjusted these deliberately,
as it did the 27 metals — where the report tabulates each change and this list
therefore treats the difference as a decision rather than a defect — and the
report does not mention these four. Until somebody rules, an assessment that needs
a number for one of them should take EF's, deliberately and on the record, the same
way [#84](https://github.com/brightway-labs/brightway-flows/issues/84)'s
entry says to take a broader context's factor.

**This is not a claim that USEtox is right and EF is wrong.** It is a claim that
two numbers a hundredfold to ten-millionfold apart cannot both be published as
though nobody disputed them, which is what `derivation: sole` and `agreed` say.
[#107](https://github.com/brightway-labs/brightway-flows/issues/107) is the
finding, and a bug report to the JRC is what it should end in.

## A row is no longer published in a place it denies

The algorithmic matcher refuses to cross a dimension or media boundary, then
scores the survivors, preferring a candidate whose context is a *generalisation*
of the source's. When no such candidate existed it fell back to scoring every
survivor, including siblings — so a `Silvicultural` row could win on an
`Agricultural` flow of the same substance, since they overlap on
`Environmental → Ground` and differ by one token. On the 2026-08-13 build this
put **110** rows in a context that contradicts the one they named: 13 ecoinvent
forestry rows published as farm soil, 27 ecoinvent air rows that named no
population density and were published in a specific one, and the rest ones and
twos across air strata and water bodies — including BAFU's lake and river
releases of lead-210, polonium-210 and radium-226, published as releases to
groundwater.

The selector now refuses a flow whose context contradicts the row's own
([#85](https://github.com/brightway-labs/brightway-flows/issues/85)). Two
contexts contradict when one names a different value from the other on an axis
they both fill in; a target that leaves the axis out, or sets it to `Unknown`, is
a coarsening and is allowed, as are the pairs written down in
`correspondence-context-routing.json` and marked publishable — the same file, and
the same decisions, the correspondence-table guard reads. A refused row is
re-decided among the flows that do not contradict it, and where there are none it
gets a flow in the context it named. Replayed over the 2026-08-13 traces that is
12 rows coarsened and 98 given a flow of their own, and no change to the other
2,163 the selector scored.

**It deliberately does not touch the ties that send a row to a flow of its own.**
Filtering the candidates before scoring rather than after would turn 113 of those
into coarsenings. That is a separate question, and for the forestry soil that
made up most of the 113 it has since been answered the other way: the row keeps
its own compartment (#84, the section above). The rest are still ties, and still
get a flow each.

And of the 12 rows it coarsens, all 12 land on a flow whose unit differs from
theirs, because the flow that agreed on the unit was the contradicting one; those
are recorded as unit disagreements in the ordinary way.

**The same guard now covers the curated route as well**, which is what #84's fix
came to. A row a correspondence table covered never reached the selector, so it
was published wherever the table's target sat, guard or no guard. On the
2026-08-15 pair of builds that moved **1,190** rows, and forestry and industrial
soil are 1,012 of them. The other 178 are the same defect in other compartments:

| Rows | Source compartment | Was published as | Now published as |
|---:|---|---|---|
| 104 | ecoinvent `water / ground-` | `Water → Long-term` | `Water → Unconfined aquifer` |
| 10 | ecoinvent `air / unspecified` | `Air → Medium stack → Rural` | `Air → Unknown` |
| 8 | ecoinvent `water / ground-, long-term` | `Water → Surface water` | `Water → Long-term` |
| 6 | ecoinvent `water / unspecified` | `Water → Ocean` or `→ Surface water` | `Water → Unknown` |
| 5 | ecoinvent `natural resource / in ground` | `Resource → Air`, `Resource → Water` | `Resource → Ground` |
| 4 | ecoinvent `air / low population density, long-term` | `Air → Medium stack → Rural` | `Air → Long-term` |
| 2 | ecoinvent `air / lower stratosphere…` | `Air → Medium stack → Rural` | `Air → Aircraft cruise height` |
| 1 | ecoinvent `air / urban air close to ground` | `Air → Ground level → Urban` | `Air → Unknown` |
| 1 | BAFU `resources / in water` | `Resource → Water → Ocean` | `Resource → Water → Unknown` |
| 37 | BAFU, five compartments | the same context, a flow BAFU minted | the same context, a flow ecoinvent minted |

The 104 are the rows
[#48](https://github.com/brightway-labs/brightway-flows/issues/48) is about
— ordinary groundwater pointed at EF's long-term water flow, which EF
characterises as zero for all four USEtox categories. They now land on the
compartment ecoinvent named. The table still says what it said, so #48's entry
in `known_violations` stands; what changed is that the merge no longer publishes
a row on it.

Two rows in that table are worth reading twice. The single
`urban air close to ground` row **lost** its compartment rather than gaining it:
by the time it was scored, this same build had minted an `Air → Unknown` flow of
the substance from a sibling row, and the selector coarsened onto it. Coarsening
onto a flow the list minted moments earlier is a different defect —
[#89](https://github.com/brightway-labs/brightway-flows/issues/89) — and
this change makes one more row show it. And the 37 BAFU rows did not move at all:
they are in the compartment they always were, on a flow that now carries an
identifier derived from an ecoinvent row, because ecoinvent reaches the
compartment first and mints it
([#102](https://github.com/brightway-labs/brightway-flows/issues/102)).
Nothing is published twice and no substance moves.


## A groundwater release is published as a groundwater release

The same act, on the compartment that had been left out of it. EF 3.1 has no
groundwater emission compartment, so the Randonneur correspondence points
ecoinvent's `water / ground-` rows at EF's fresh water flow — the nearest flow
EF has, and the right thing for a table to say. Reading the compartment off it
as well was allowed here when the two soil entries were refused, on the grounds
that ecoinvent's own `EF v3.1` implementation characterises these rows with the
freshwater factor, so fresh water was where the release was *treated* as
happening rather than merely the nearest name EF had.

That is a fact about characterisation, not about where the release went, and it
was doing the deciding. Both lists that ship a groundwater compartment map it to
`Water → Unconfined aquifer` and agreed all along; the table pulled ecoinvent's
rows off it and BAFU, having no table, stayed. On the 2026-08-15 pair of builds
**576** of ecoinvent's 695 `water / ground-` rows were published on
`Water → Surface water` while all 63 of BAFU's placed groundwater rows sat on
`Water → Unconfined aquifer`, and **32 substances were published twice**, once
per list — Chromium(6+), Ammonium and Phosphorus among them, with neither list
having said anything wrong. So the entry is `publishable: false` like the two
soil ones: the table names the substance, the compartment stays the row's own
([#77](https://github.com/brightway-labs/brightway-flows/issues/77)).

636 rows moved, all of them in water:

| Rows | Source compartment | Was published as | Now published as |
|---:|---|---|---|
| 576 | ecoinvent `water / ground-` | `Water → Surface water` | `Water → Unconfined aquifer` |
| 50 | BAFU `emissions to water / groundwater`, ecoinvent `water / ground-` | the same context, a flow BAFU minted | the same context, a flow ecoinvent minted |
| 5 | BAFU `emissions to water / lake`, `/ river` | `Water → Unknown` | `Water → Lake`, `→ River` |
| 5 | BAFU `emissions to water / lake`, `/ river` | the same context, a different identifier | the same context, a different identifier |

Of the 32 substances published twice, **27 now reach one shared flow**: every
Chromium(6+) row, ecoinvent 3.8, ecoinvent 3.12 and BAFU alike, reaches the same
aquifer flow. The two that still differ are not this shape — `Water` is
coarsened onto `Water → Unknown` by ecoinvent, and `Carbon` reaches the aquifer
from both lists but resolves to `Elemental Carbon` on one side, which is
[#89](https://github.com/brightway-labs/brightway-flows/issues/89)'s
question rather than this one. The 55 rows that changed identifier without
changing compartment are
[#102](https://github.com/brightway-labs/brightway-flows/issues/102) again:
ecoinvent now reaches the compartment first and mints it.

**What it cost is the characterisation, and it is the larger number here.**
No flow changed its factor count and none changed its deprecation — the count of
characterised flows is identical on both sides — but **405 of the 636 rows now
reach a flow carrying no factors**, where before they reached one carrying
between one and six: 206 rows lost four factors, 79 lost six, 69 lost two, 47
lost one and 4 lost five. `on_characterised_flow` falls by 201 for ecoinvent
3.12 and 203 for 3.8. No method characterises a compartment EF cannot express,
so this is the forestry-soil trade again
([#84](https://github.com/brightway-labs/brightway-flows/issues/84)),
decided the same way: what the source said about where the release went is the
stronger claim, and reading a freshwater factor for a groundwater release is a
judgement for whoever consumes this list rather than one this list makes
silently.

What it bought, besides the two lists meeting, is that the merge stops
contradicting itself: `context_inconsistent` falls from **299 to 14** on
ecoinvent 3.12 and from **306 to 15** on 3.8. Those rows were being flagged as
published in a context their own compartment denied for as long as the
coarsening was published.

**A note on measuring this one.** The before side was the stored build of the
branch's merge base, which `refresh_base_build.py` correctly reported as
answering for this branch. It reused the shared directory's `ef-31-flows.json`,
written three days earlier by older extraction code, while the after side
re-extracted it — a 2.5 KB difference in a 207 MB file. That pair reported 64
halocarbon flows changing deprecation, none of which any groundwater row
touches, and `flows.deprecated` moving 169 → 233. Two further builds settled it:
one of the same commit into a second data directory, which came out byte
identical and so ruled out nondeterminism, and one of the *base* commit against
the after side's own inputs, which reports **0** flows changing factor count or
deprecation. Every deprecation belonged to the input difference. `--source` and
the commit are not the whole of "the same inputs"; the extracted base list is
part of it too.


## Water vapour to unspecified air took two fixes, and now lands

BAFU reports water vapour to the air, compartment `unspecified`. The list holds
water vapour in exactly that compartment — air, height unstated — measured in
kilograms, which is the flow the row means. It also holds water vapour in air at
aircraft cruise height and in air long-term, both in kilograms. All three scored
3, so the merge reported a tie and placed the row nowhere. On a build of EF 3.1
with ecoinvent 3.8, 3.12 and BAFU that was **50** of the **70** rows reported as
`tied-elementary-candidates`, every one of them BAFU's water vapour.

The score counted words, and a compartment that leaves a question open still
prints an answer to it. Air of unstated height is written
`Environmental → Air → Unknown`; the row that names that compartment arrives as
`Environmental → Air`, because the words the row is compared against are the
ones the context *states*, and "unstated" is not one. So the flow the row meant
shared two words with it and differed by one — exactly like air at cruise
height and air long-term, which differ from it by a real one. Water in the air
over an airport at cruising altitude is not water in the air generally, and
neither is water released more than a hundred years from now.

There is a rule that takes a flow sitting in the row's own compartment and stops
before scoring anything, and it declined here because it requires that exactly
one flow sit there and three do: the kilogram flow and two more in cubic metres,
the doubling recorded as an open item in `water-taxonomy-overview.md` §8.

The score now asks whether a candidate **is** the compartment the row named,
which the context IRI answers and the words only describe
([#90](https://github.com/brightway-labs/brightway-flows/issues/90)). It is
worth one point, deliberately less than the unit's two, so the row measured in
kilograms still reaches the kilogram flow of the two in its own compartment
rather than either cubic-metre one. Replayed over the water vapour flows the
2026-08-15 build holds, the kilogram flow scores 4 and the two neighbours 3.

**What it does not do.** A row whose compartment the list does not hold gives the
point to nobody, so the search for the nearest flow above it is unchanged, and so
are the ties that send a row to a flow of its own: 420 rows on that build,
341 of them BAFU releases to a named water body and 25 ecoinvent forestry soil,
all still placed as they were. That question is
[#77](https://github.com/brightway-labs/brightway-flows/issues/77)'s. For
the 25 forestry rows
[#84](https://github.com/brightway-labs/brightway-flows/issues/84) has
since answered it, and answered it the same way: a forestry emission keeps the
compartment its list named, and a flow of its own is where it belongs.

**The scoring change alone moved nothing**, and it took a second fix to matter.
The fifty rows were stopping one stage earlier, at
`multiple-flow-object-candidates`: twelve substances answer to water's CAS
number, and until BAFU's water rows were given a material
([#86](https://github.com/brightway-labs/brightway-flows/issues/86))
nothing said which of them a row of water vapour was. With both in, all fifty
reach `Water vapour` in `Environmental → Air → Unknown`, in kilograms — the flow
they always meant. Both claims in
`expectations/0455-exact-compartment.json` are met on the 2026-08-15 build, on
which BAFU's unmatched total falls from 267 rows to 10.

It is worth saying which fix did what, because neither is visible on its own. The
scoring change decides *which flow of a substance*, and could not run while the
substance was unknown; the material assignment decides *which substance*, and
would have handed all fifty to a tie one step later. A reviewer measuring either
against `main` alone sees no published flow move.

## Two ether rows waited on a curator, not on a rule

Stepwise 2006 reports `Ether, 1,1,1-trifluoromethyl methyl-, HFE-143a` to
unspecified air, CAS 421-14-7. The merge finds the substance without trouble and
then finds **two** live EF 3.1 flows of it in that compartment, in kilograms:
EF's `Methyl trifluoromethyl ether`, carrying the number, ten synonyms and no
factor, and EF's `HFE-143a`, carrying the number and Climate change 616.0. One
substance, published twice — under a chemical name and under a refrigerant
designation. Nothing separates the two, so the selector refused
(`tied-elementary-candidates`) and the row was published nowhere, taking
Stepwise's own climate-change factor with it. `Ether, nonafluorobutane ethyl-,
HFE569sf2 (HFE-7200)` is the same story on 163702-05-4, tied between EF's
`n-HFE-7200` and EF's `HFE-569sf2`.

On the shared five-list build of 3 September 2026 these were **the only two
unmatched rows in 28,490**, across every merged list.

**Nothing in the merge could have fixed them.** A duplicated flow that is still
standing is exactly what a source row cannot be placed onto: the pipeline
reports the pair on `queue/elementary-flow-collision` and stops, because deciding
that two rows of one substance are one flow is a curator's decision and not a
score. Until it is taken, every list's row for that substance in that compartment
fails the same way — the two Stepwise rows are simply the first rows any merged
list has had for these two ethers.

The eight rulings (two pairs, four air compartments each) are in
`elementary-flow-collision-decisions.json`
([#185](https://github.com/brightway-labs/brightway-flows/issues/185)), and
they are decided by two different reasons, which is worth reading before writing
a ninth:

- **Trifluoromethoxymethane** is the ordinary case, and the survivor is
  `HFE-143a` because it holds the factor. Retiring the named row loses nothing:
  the ten synonyms and EF's ILCD note belong to the flow object the two share,
  and the substance is published as `Methyl Trifluoromethyl Ether` either way.
- **The nonafluorobutyl ethyl ether** cannot be decided that way — both rows
  carry 60.7 — so it is the carbon tetrachloride case
  ([#105](https://github.com/brightway-labs/brightway-flows/issues/105)):
  deduplication's sort would fall through to the identifier and decide nothing
  about the chemistry. `HFE-569sf2` survives because of what it carries — twelve
  synonyms, EF's note, and eleven contexts across air, soil and water against a
  bare row with four air contexts — and because one of those synonyms, `Ether,
  nonafluorobutane ethyl-`, is the head of the Stepwise row's own name.

No ruling loses a factor: the sets are nested in the first pair and equal in the
second.

## Two BAFU rows may count different things and share one flow

A list SimaPro shaped writes the unit into the flow's name, because SimaPro
keys its flows on names alone. This list carries the unit as its own field, so
the copy is redundant and is taken back out
([#67](https://github.com/brightway-labs/brightway-flows/issues/67)) —
`Water/m3` is published as `Water`. All ten of BAFU's such names are rewritten
that way, and `expectations/0384-unit-inside-the-flow-name.json` is what says so
on every build. One pair is worth knowing about anyway.

```
Water, process, unspecified natural origin/kg   unit=kg
Water, process, unspecified natural origin/m3   unit=m3
```

**They share a flow, and the names never had anything to do with it.** A flow's
identity is its substance and its compartment — the unit is not in it, and
`(flow_object_id, context_iri)` is unique across live flows — so in each of the
two compartments they share, both rows reach one flow: `Water` in
`Resource → Water → Unknown`. For a while the rule that strips the unit declined
this pair, on the ground that the suffix was the only thing holding two rows
apart. It was not holding them apart; it was holding two *names* apart above a
single flow, and costing both rows their match, since no flow object answers to
a name with a unit stuck on the end. The rule no longer makes that exception,
and since [#78](https://github.com/brightway-labs/brightway-flows/issues/78)
the mass rows are carried in cubic metres at 1000 kg/m³ with the density stated
on their mappings, so there is one unit as well as one name. Each row keeps its
own identifier, its own source reference and its own mapping back to BAFU.

**What is left is a question about the vendor's data, not about names.** If the
two rows count different things, a consumer who holds both in a dataset and maps
both through this list adds them together. The archive is only half decisive:

| Compartment | Datasets using `/kg` | using `/m3` | using both | mass ÷ (volume × 1000 kg/m³) |
|---|---|---|---|---|
| `resources / land` | 64 | 64 | 63 | 6.58 × 10⁻⁵ – 6.65 × 10⁻⁵ |
| `resources / unspecified` | 64 | 64 | 57 | 1.6 × 10⁻⁵ – 3.89 |

In `land` the ratio is fixed to five significant figures across all 63 datasets.
Two numbers that tight are generated from one, not measured twice, and reading
them as one flow moves a consumer's total by 66 parts per million. In
`unspecified` it scatters over five orders of magnitude, and in at least one
dataset the mass row is 3.9 × the volume row — there the two are independent
numbers and the sum is a real change. Settling it needs to know what BAFU means
by writing both, which is a question for that list; BAFU's standing wood was the
same shape and was settled by measurement, in `bafu-2026-v1-manual-fixes.json`.
It stays open on #67, as a question about `resources / unspecified`.

One further consequence, in the same family. `Water/m3` is one exchange in one
dataset, and taking the suffix off puts an m³ row into `emissions to air /
low. pop.`, where BAFU's other water rows are kilograms — 131 exchanges of
them. That row is placed rather than refused: giving BAFU's water rows a
material (#86) reads water in an air compartment as vapour, and the two
kilogram rows in `low. pop.` and the one m³ row both reach `Water vapour` there —
each on the flow stating its own unit, because the list already publishes that
compartment twice, once in kilograms and once in cubic metres. So no unit is
guessed there either. The air rows are deliberately left in kilograms by #78's
conversions: EF 3.1 states water vapour in air by mass, and it is liquid water
this list publishes by volume.

## 190 published flows sit beside a characterised one and carry no factors

A curated grouping says "this ecoinvent herbicide belongs with the herbicide
class". When this population was measured (the 2026-08-12 build) the merge
answered it in one of two ways: where the substance was in the prepared
correspondence table — `Flurenol`, `Mecoprop`, `Saflufenacil` and ten more —
the row became a *source reference* on the class flow already there, and that
flow's factors answered for it; where it was not, the row fell through to a
manual addition, and a manual addition **mints a flow** on the named object in
the row's own context. The tables have since been retired
([#141](https://github.com/brightway-labs/brightway-flows/issues/141)), so
the first way now runs on this project's own curated rows rather than the
vendor's — the split itself, and the population below, still stand and have
not been re-measured since the retirement.

On the 2026-08-12 build that is 190 flows, across the four pesticide classes,
sharing a substance, a context, a unit **and a name** with a flow that holds the
characterisation. Every one of the 190 carries no factors at all, and 12 of the
29 groups they form hold no base-list flow either — nothing in the group has a
number on it. Nothing published distinguishes them from the flow that does.

Whether minting is right is a curator's question, and this list does not answer
it. What it does now is ask it
([#60](https://github.com/brightway-labs/brightway-flows/issues/60)): the
collision check runs again after the merge, so the groups reach the
`elementary-flow-collision` queue as `review` items naming the flows the merge
minted, and the counts are published in `run_stats` under
`merge_elementary_flow_collisions`. While the check ran only in the transform,
the queue held 116 groups and the database held 145.

These 29 groups are not collapses waiting to happen, which is what a
transform-side collision is. Deduplication runs in the transform and so does the
pass that applies the collision rulings, so nothing inspects a flow the merge
minted — not in this build, and not in the next, whose transform starts from the
base list again. A ruling written against one of these groups is counted
`collision_rulings_absent` and applied to nothing. The answer is a curation
decision about the grouping: a curated correspondence row in the list's
match-overrides file, or a manual addition that attaches rather than mints.

**What to expect:** selecting flows of one of the pesticide classes in one
context returns up to twenty rows, of which at most one carries factors.
Consumers reading characterisation should read it from the flow that has it —
the group's members are listed in the queue item's payload — rather than
assuming a name and a context identify one row.

## Forty-eight refrigerants are still published under a part number

The list prefers the chemistry to the trade's numbering: the gas EF 3.1 calls
`HFC-134a` is published as `1,1,1,2-Tetrafluoroethane`, with `HFC-134a` kept
beside it as an alternative label so an inventory written against EF 3.1 still
finds it. On the 2026-08-17 build that is done for 70 of the 118 substances EF
names this way. The other 48 keep the part number, and it is worth knowing why,
because "this one still says `CFC-113`" is not an oversight
([#104](https://github.com/brightway-labs/brightway-flows/issues/104)).

**Twenty-six have no chemical name available at all.** For 14, neither Common
Chemistry nor ChEBI names the registry number; the other 12 carry no single
registry number to ask about. For those the part number is the only name there
is.

**The other 22 have a name, and it is not an improvement:**

- **The name says less than the number does.** `CFC-113` carries registry
  number 26523-64-8, which is trichlorotrifluoroethane with no isomer stated,
  and that is Common Chemistry's name for it too. C₂Cl₃F₃ has two isomers and
  the part number says which one; the name does not. Four are held back for
  this, and two more because the name names one isomer of something the part
  number names as a mixture — `HFE-7200` is sold as a mixture of the normal and
  iso ethers and Common Chemistry's name is the iso one alone.
- **The name is another part number.** Common Chemistry's name for 76-14-2 is
  `CFC 114`. Two substances.
- **The name is the registry's index form.** `Ethane, 1-bromo-2-fluoro-` is a
  catalogue heading with the substituents sorted after the parent, and reading
  it aloud is harder than reading `FC-151B1`. Three substances.
- **Several substances share one registry number.** Four isomeric ethers —
  `HFE-356mec3`, `HFE-356pcc3`, `HFE-356pcf2` and `HFE-356pcf3` — all carry
  382-34-3, and there is one name for that number. Renaming would publish four
  substances under one name, which is worse than four part numbers. Ten
  substances across four registry numbers, and the shared number is itself
  something to fix rather than something a rename should hide.
- **Both names on offer are worse.** `HFE-356mff2` is `flurotyl` to ChEBI,
  which is its name as an inhaled convulsant drug, and
  `1,1′-Oxybis[2,2,2-trifluoroethane]` to Common Chemistry, which is the index
  form. One substance.

**What to expect:** a flow named `HFC-…`, `CFC-…`, `HFE-…`, `FC-…` or `Halon-…`
is a substance in one of those positions. Searching the list by a part number
finds the substance either way, because the renamed 70 keep theirs as an
alternative label.

## The `Borate` flows carry no registry number

EF 3.1 gives its six rows named `Borate` the registry number 12447-40-4, which
is borax — sodium tetraborate decahydrate, the mineral. Borate is the ion; borax
is one particular salt of it, and a kilogram of borax is about a fifth boron by
mass, so the two are not interchangeable in an inventory. Sharing the number put
all six on borax's substance record, where they were published under the ion's
name, typed as a salt, and carrying borax's structure and 24 of its trade names
([#106](https://github.com/brightway-labs/brightway-flows/issues/106)).

The number is removed from the six rather than replaced, which is the repair
[#57](https://github.com/brightway-labs/brightway-flows/issues/57) made
when both lists gave organic-bound nitrogen the registry number of nitrogen gas.
Replacing it would assert an identity EF never stated. ecoinvent does state one
— it reaches these rows as `Borate` under 11129-12-7, the borate ion, and the
borax rows as `Borax` under 1303-96-4 — and nothing is lost by the separation,
because both sides arrive through the correspondence table on identifier rather
than on the number.

**What to expect:** `Borate` is a substance with no registry number, no
structure and no synonyms, and `Borax` is a separate one carrying all three.
Both flows carry a comment saying what the difference is. A consumer matching on
registry number will not reach the borate flows; matching on the identifier, or
on ecoinvent's own correspondence, will.

## One substance, one place it is taken from

Two source lists agree about what a substance is and disagree about where it
comes from. Because the identity is agreed they share one substance record;
because the place is not, they become two flows that can never meet. An
inventory using one and a method characterising the other do not connect, and
until now nothing reported it
([#87](https://github.com/brightway-labs/brightway-flows/issues/87)).

Where a substance is *released* is a fact about the process, so a metal emitted
to air and to a river is two ordinary flows and no list contradicts another by
shipping one of them. Where it is *taken from* is a fact about the substance:
peat comes out of the ground, wood off a living tree, and no process chooses. So
the check compares the contexts that are not releases, and reports a substance
holding a context that is a different place from every other one it has — not
one of them described at another level of detail — where the merge is what wrote
the flow there. Those reach the `substance-in-two-places` queue, counted under
`merge_substance_places` in `run_stats`.

The rule is not "two places no single source list holds at once", which is how
the issue puts it: read literally that asks whether some list files the
substance in both places itself, and on the 2026-08-14 build it reports 8
substances and misses both of the two the issue is about — BAFU ships each of
them in two compartments, so the pair excuses itself. A list filing one name in
two compartments is the defect seen from closer up.

Fifteen substances on the 2026-08-14 build, those 8 among them. Two are fixed in
the change that added the check — BAFU's geothermal energy, which is a ground
resource and not a biotic one, and BAFU's kilogram of peat, which now goes to the
same substance ecoinvent's kilogram goes to — leaving thirteen.

Giving BAFU's water rows a material (#86) then changed which thirteen. `Water,
Well` left the list, because those rows now join `Groundwater` rather than
minting a substance of their own; and three kinds of water joined it, because
rows that used to be refused now land, and BAFU files some of them in a
compartment that reads as ground. Fifteen again on the 2026-08-15 build, and a
different fifteen.

Four of those fifteen have since been settled. The `Volume occupied` rows — a
repository cavern, an underground deposit and a reservoir — were split because EF
3.1 filed them as a use of land while ecoinvent and BAFU filed them as resources,
and [#72](https://github.com/brightway-labs/brightway-flows/issues/72)
decided that the lists which wrote them are right: they measure a volume, and a
land occupation is a surface held for a time. EF's four now resolve to the
compartment the other three lists already use, so each is one flow rather than
two. Eleven on the 2026-08-16 build, and **nine on the build of 25 August 2026**
— `Carbon Dioxide, In Air` was fixed by
[#135](https://github.com/brightway-labs/brightway-flows/issues/135),
`Helium` was split out as
[#114](https://github.com/brightway-labs/brightway-flows/issues/114) and
`Cooling water` by
[#117](https://github.com/brightway-labs/brightway-flows/issues/117), while
`Peat` returned from a different row.

[#89](https://github.com/brightway-labs/brightway-flows/issues/89)
answered all nine. **A substance is taken from one place, and the rule is now
written down** — rows in `flow_specific_context_mappings`, one per source row
that put a substance somewhere it could not also be, and for peat a rename as
well, because there the two places turned out to be two substances:

| Substance | Published in | The row that moved, and where it was |
|---|---|---|
| `Groundwater` | `Resource → Water → Unconfined aquifer`, **209 factors** | BAFU's well water in `resources / in ground` and `resources / unspecified`, and its process water in `resources / in ground` |
| `Water` | `Resource → Water → Unknown`, **209 factors** | BAFU's five `Water, embodied in product` rows in `economic issues` |
| `Peat, horticulture` | `Resource → Biotic`, kilograms | nothing moved: ecoinvent's `Peat` is *renamed* so that it reaches EF 3.1's own flow for the same substance, which is already in the same compartment |
| `Platinum` | `Resource → Ground`, **1 factor** | BAFU's `Platinum` in `resources / biotic` |
| `Basalt` | `Resource → Ground` | BAFU's `Basalt` in `resources / biotic` and `resources / in air` |
| `Biomass` | `Resource → Biotic` | BAFU's biomass energy in `resources / in air` and `resources / unspecified` |
| `Green water` | `Resource → Air` | ecoinvent's `Water, green` in `natural resource / in ground` |
| `Organic Carbon, Placed In Landfill` | `Inventory Indicator` | BAFU's row in `resources / in ground` |
| `Waste Mass, Total, Placed In Landfill` | `Inventory Indicator` | BAFU's row in `resources / in ground` |

**Seven were one list disagreeing with itself**, which is the same defect seen
from closer up: BAFU files a name in two of its own compartments and the
compartment rule believes both. The minority compartment is the slip — basalt is
in the ground in 102 datasets and biotic and in-air in one each, all three in the
*same* dataset — so the remedy is the one
[#83](https://github.com/brightway-labs/brightway-flows/issues/83) and
[#87](https://github.com/brightway-labs/brightway-flows/issues/87) already
used, and [#117](https://github.com/brightway-labs/brightway-flows/issues/117)
used for the cooling-water row sitting beside the well water. For the waters the
second compartment is `resources / unspecified` or `resources / in ground` — the
first names 42 things and means none of them, and the list reads both as ground,
which is right for platinum and wrong for a withdrawal of drinking water.

Two of the nine were **not slips but genuine disagreements**, and those are
decisions this project made rather than corrections it applied. They are
recorded here because a reader is entitled to know which is which.

- **`Green water`** is rainfall held in soil. EF 3.1 files it as a resource
  taken from air, because precipitation is how it arrives; ecoinvent 3.12 files
  it in the ground, because that is where a plant's roots reach it. Neither is
  wrong and neither flow carries a factor. The list takes EF's reading: EF 3.1
  is the base list, and its flow is the one a method would characterise without
  this project minting a target for it.
- **`Peat, horticulture`** turned out not to be a place question at all — see
  *Two peats, not one peat in two places* below. Peat was in the list above as
  one substance in two contexts, and it is two substances, each of which the
  source lists already file consistently. The answer was a **rename**, not a
  context rule, and nothing moved.

### Two peats, not one peat in two places

Peat was in the list above as a substance in two places, and it turned out to be
**two substances**. EF 3.1 ships both and tells them apart by compartment and by
unit:

| EF 3.1 flow | Compartment | Unit | Factor |
|---|---|---|---|
| `peat` | Resources from ground → *Non-renewable energy* | MJ | `Resource use, fossils`, 1.0 |
| `Peat, horticulture` (EF ships it as `Peat, in ground`) | Resources from biosphere → *Renewable material* | kg | none |

The first is peat burned as a fuel, counted by its energy content. The second is
peat dug and sold as a growing medium, counted by its mass. A megajoule of fuel
peat and a kilogram of horticultural peat are not one substance measured two
ways, and a rule that merged them would be crossing a unit as well as a
substance.

ecoinvent ships one peat flow — kilograms, `natural resource / biotic` — and it
is the horticultural one. What made this look like a single substance in two
places is a **vendor rename**: ecoinvent 3.8 spells that flow `Peat, in ground`
and reaches EF's material peat, while 3.9.1 through 3.12 spell it `Peat` and did
not, so one vendor flow was published as two substances depending on which
release a build merged. Every release is renamed to `Peat, horticulture`, on the
same uuid, and EF's own flow is renamed with them — a correction applied to one
release and not another leaves the merge two lists that disagree about what a
substance is
([#26](https://github.com/brightway-labs/brightway-flows/issues/26)). Each
vendor spelling is kept as an alternative label, because an inventory written
against one of these lists holds no other string for it.

**The compartments already separate them, so nothing is moved.** EF files the
material peat under `Resources from biosphere` and ecoinvent files its own row
under `natural resource / biotic`; both map to `Resource → Biotic`, and the fuel
peat sits in `Resource → Ground` on both sides. The renamed rows therefore meet
on EF's flow with no context rule at all — the two peats stay told apart by
compartment, by unit *and* by name, which is three independent ways rather than
one. An earlier revision of this work sent every peat row to `Resource → Ground`
on the reasoning that peat is dug out of a bog. That is true, and it was the
wrong thing to act on: it collapsed a distinction the source lists draw, and
left the name carrying the whole difference.

The one row that does move is BAFU's, below, and it moves because BAFU's peat is
the *fuel* while the compartment it is filed in says biotic — a row whose
compartment and substance disagree, which is the ordinary case this section is
about.

**What the merged reading would have cost.** Sending ecoinvent's kilogram row to
EF's megajoule flow crosses a unit, and it drops a published number: the
ecoinvent Centre's implementation states `Resource use, fossils` at **9.76 per
kilogram** for that flow, which is peat's calorific value, and 9.76 per kilogram
is wrong by an order of magnitude against a flow measured in megajoules. Kept
apart, the factor stays where it belongs and the JRC's 1.0 per megajoule stays on
the fuel peat.

**BAFU's peat is the fuel, and its kilograms are converted to megajoules.**
BAFU ships three peat rows — a kilogram under `resources / biotic` in 134 of the
release's 11,947 datasets, a kilogram under `resources / in ground` in one, and
`Energy, from peat` in megajoules in one — and all three are the energy carrier.
The archive says so rather than the name: the biotic row is the extraction input
to `Peat, at mine`, one kilogram per kilogram, and that dataset is filed under
`fuels / peat` and its output feeds `Peat, burned in power plant` and
`Electricity, peat, at power plant`. The 133 other datasets carrying the row are
ordinary products — glass, acetone, gypsum, polyols — at 1e-4 to 1e-8 kg, which
is peat-fired electricity reaching them through the background; `Electricity
imports` alone carries `Electricity, peat, at power plant` 211 times. Nothing in
the release uses peat as a growing medium.

**Why the kilograms are converted.** EF 3.1 accounts fossil and nuclear energy
carriers by energy content rather than by mass, deliberately: the target carries
`Resource use, fossils`, and that factor is *defined per megajoule*. BAFU records
the same extraction as a mass. The substance is the same and only the quantity
basis differs, which is why the crossing is accepted rather than refused — an
unconverted kilogram landing on a per-megajoule factor would be scored as though
one kilogram were one megajoule, understating peat by about a factor of ten. The
conversion is **9.76 MJ/kg**, the IPCC 2006 Guidelines Vol. 2 Table 1.2 default
for peat, whose 95% confidence interval is 7.80 to 12.5 MJ/kg; the value is
stated with its source rather than derived, because energy content varies that
widely with moisture. It is written once in
`bafu-2026-v1-match-overrides.json`, carried by the merge as
`qudt:conversionMultiplier`, and the same number is used for both kilogram rows —
one target takes one conversion whichever compartment the kilogram came from.
The same treatment BAFU's coal, crude oil, natural gas and uranium rows already
get, and the crossing is recorded in `unit-change-allowlist.json` so the guard
does not report it again ([#78](https://github.com/brightway-labs/brightway-flows/issues/78)).

**This corrects [#87](https://github.com/brightway-labs/brightway-flows/issues/87).**
It routed BAFU's biotic kilogram to the *material* peat, on the reading that a
mass of peat is the material and a megajoule of peat is the carrier, and on the
observation that BAFU's row has the same name, the same `biotic` compartment and
the same kilogram as ecoinvent 3.12's. Same name and same compartment, different
substance: BAFU's flows came out of ecoinvent 2, where peat was a fuel, and
ecoinvent 3 restructured. Under #87's routing the units happened to agree — both
sides kilograms — and that agreement was the reason the row was left alone. It
agreed with the wrong substance. Renaming the material peat is what made the
error visible.

**Two published numbers change**, both in the direction of a withdrawal being
scored where it previously was not. `Groundwater` and `Water` each carry EF
3.1's 209 water-use factors on the flow EF ships, and the rows BAFU filed in the
ground or under `economic issues` reached a minted flow carrying none — so a
BAFU inventory drawing well water or process water scored zero against every
water-use method, and now scores what its siblings score. The embodied-water
rows are the one place where that is a judgement rather than a repair:
`economic issues` is BAFU being honest that the quantity is an accounting entry,
and an accounting entry that lands on a characterised flow is scored like a
withdrawal. Whether such entries belong in this list at all is
[#69](https://github.com/brightway-labs/brightway-flows/issues/69), and
this change asks that question more sharply rather than answering it.

**What to expect:** a substance is published in one intake context, and
`stats.merge_substance_places.substances_in_two_places` is 0. Two expectation
files hold it there — `0450-one-place-per-substance.json` states the claim for
each of the nine and names the row behind it, and
`0450-withdrawal-water-bodies.json` covers the withdrawal-body half — so a tenth
substance arriving fails the build's assessment rather than joining a queue
nobody reads. The queue itself stays, because the check is what would find the
tenth.

## What a redirect's reason does and does not promise

`harmonised-flows-simple.json.gz` publishes a `redirects` entry for every
identifier this list deprecated, so a consumer holding one is no longer told
nothing ([#39](https://github.com/brightway-labs/brightway-flows/issues/39)).
Each entry says where the identifier now resolves and, in `deprecationReason`,
whether the merge behind it crossed a source-context distinction. Reading that
field is still the point — but it answers a narrower question than earlier
versions of this page implied.

On the 2026-08-12 build there are **130 redirects, and all 130 are
`identity-merge`**: for every one, the source list both flows came from put them
in the same context. Earlier versions of this page reported 14,438 of 14,602
redirects as `context-collapse`, and two separate things have changed since.
Most of those deprecations no longer happen at all — the soil pair in
[#40](https://github.com/brightway-labs/brightway-flows/issues/40) and the
water pair in
[#41](https://github.com/brightway-labs/brightway-flows/issues/41)
separated the contexts that were producing them. The 46 that did survive into
the 2026-08-12 build were mislabelled: the reason was decided by pooling every
source list into one set of contexts per flow, so a survivor a second list also
attests to had a context its deprecated flow did not, and being better attested
read as an identity that had moved
([#59](https://github.com/brightway-labs/brightway-flows/issues/59)).
Comparing within each list both flows carry makes all 46 identity merges.

A context collapse is still a real thing and still the case to refuse: two
distinct source contexts that map onto one consensus context give two flows that
compare equal and whose factors legitimately disagree
([#1](https://github.com/brightway-labs/brightway-flows/issues/1),
[#36](https://github.com/brightway-labs/brightway-flows/issues/36)). That
no redirect in this build is one is a fact about which deprecations survive
today, not a guarantee about the next build.

### The fourth reason, which is not a merge

`identifier-scheme-change` says no flow moved: this list renamed a flow it had
minted, and the two sides of the redirect are the same substance in the same
compartment. It is always safe to follow.

There are 2,561 of them and they are all from one renaming. A flow the merge
mints used to be named after whichever source row reached its compartment
first — which is not a property of the flow, and moved when a vendor added a row
that sorted earlier, when a curated fix let an existing row through, and when
the lists were merged in a different order. Water in a river was renamed by
[#78](https://github.com/brightway-labs/brightway-flows/issues/78)
converting one BAFU row to cubic metres, with nothing about the water changed,
and the name it lost simply vanished from the next build
([#102](https://github.com/brightway-labs/brightway-flows/issues/102)). A
minted flow is now named after its substance and its compartment, and every name
the change retired is recorded so that it still resolves.

What that does **not** cover is a name from a build merging some other set of
source lists. Those builds minted their flows from their own rows, and those
identifiers cannot be worked out from here; the recorded file says which build
it came from.

**An identity merge is not a promise that the two flows' factors agreed.**
Comparing every characterisation factor a deprecated flow carries with what its
survivor carries for the same method — 183 factors across the 52 of 130
deprecated flows that carry any:

| | count |
|---|---:|
| survivor has no factor for that method — genuinely recoverable | 22 |
| survivor has the same value — following the redirect is a no-op | 93 |
| survivor has a **different** value — conflict | **68** |

14 of the conflicts differ by more than 10×, the widest by 397×: Kresoxim-methyl
(CAS 143390-89-0) reaches EF 3.1 twice under `Emissions to non-agricultural
soil`, and the two UUIDs carry 53,540 and 134.73 for freshwater ecotoxicity.
Nothing was fused there — it is one list disagreeing with itself about one
place, which is [#1](https://github.com/brightway-labs/brightway-flows/issues/1),
and deduplication picks a winner by "most CFs, then UUID sort".

**What to do about it:** read `deprecationReason` before following a redirect —
`context-collapse` and `unclassified` are the cases to detect and refuse, and
the map is what lets you tell them apart rather than a licence to resolve them.
Do not read `identity-merge` as licence to overwrite a factor you already hold:
the merge chose between two numbers one source list published for one place, and
following the redirect adopts that choice.

### The fifth reason, which resolves to nothing

`source-row-withdrawn` is the one redirect you cannot follow, because there is
nowhere to follow it to. Its record carries no `dcterms:isReplacedBy` at all —
the only kind that does not — and that absence is the statement rather than a
gap in the data. The flow was minted from a source row this list has since
decided not to map, so the substance did not move: it was never a substance of
ours. **Drop the exchange.** Do not fall back to matching the flow by name.

There are three, all from
[#115](https://github.com/brightway-labs/brightway-flows/issues/115), and
they are described in the next section.

Schema version 7 is where `dcterms:isReplacedBy` and `replaced_by_identifier`
became optional on a redirect. A reader written against version 6 may
dereference either without checking, which is why the change is a version bump
and not an addition.

## What a migration between two releases does not promise

`release-migrations` writes, for a consumer who loaded one release, the
randonneur files that move their database to the next (see [Which output do
I need?](../using/outputs.md#releasesmigrationsfrom__to-moving-a-database-from-one-release-to-the-next)).
Four things it deliberately leaves to a person.

**A split is not answered.** A flow whose source rows now land on several
flows — the eleven ecoinvent `Water` rows that became water vapour in air and
water in water are the shape of it — is written to `unresolved.json` and to
none of the migrations. randonneur has a verb for it, `disaggregate`, which
splits a consumer's amount across the targets by an allocation; it is never
written, because an even split is almost never what the chemistry says and an
uneven one is a ruling. The consumer's database keeps the old identifier until
`release-migration-rulings.json` says which flow it is.

**A unit change is not converted.** A flow that resolves to exactly one
successor published in another unit is unresolved too. The merge knew the
conversion when it made the flow; the snapshot does not carry it, and writing
`conversion_factor: 1.0` against a change from kilograms to cubic metres would
be a wrong number that reads as a right one.

**A refused redirect stays refused.** The export tells a consumer not to
follow a `context-collapse` or `unclassified` redirect, and the migration does
not follow it for them: the survivor is named as the candidate and nothing is
written.

**A development build is not a release.** A snapshot of a build whose commit
no tag names is written as `brightway-flows-<git describe>-dev`. It is
reproducible — the commit is named — but a migration from or to one describes
the state of a branch on a day, and nothing downstream should pin it.

Two smaller ones. The two releases must have merged the same source lists,
because a list only one side merged would read as a thousand deletions;
`--allow-different-sources` makes those rows unresolved instead. And the
factor file is stated against the later release's flow identifiers, so it is
right only after the flow file has been applied.

## Source flows this list deliberately does not map

A source flow with no entry in its list's `xkos:Correspondence` used to be
ambiguous: it read the same whether the flow had been examined and refused or
never looked at. That ambiguity is what
[#115](https://github.com/brightway-labs/brightway-flows/issues/115) cost —
a consumer counted ecoinvent 3.8's elementary exchanges against the
associations, found three fewer, and filed a regression against a decision.

Each `xkos:Correspondence` now carries a second list beside `xkos:madeOf`:

```json
"brightway:excludedSourceConcept": [{
  "@id": "https://vocab.brightway.one/ecoinvent/3.8/flow/22cbd60c-8017-49c4-ae6f-7f0c1c6ebf0b",
  "skos:prefLabel": "venting of argon, crude, liquid",
  "context": "social / unspecified",
  "qudt:hasUnit": {"@id": "https://vocab.brightway.one/units/unit/KiloGM"},
  "brightway:exclusionReason": "A product, not an elementary flow. …"
}]
```

The label and compartment are the **vendor's** spelling, not this list's:
nothing was harmonised, so there is no consensus spelling to give, and you are
holding the vendor's file. A list that refuses nothing publishes no key at all,
so the presence of the key is the finding.

### The three ecoinvent 3.8 rows

ecoinvent publishes one `ElementaryExchanges.xml` per system model, and 3.8's
`apos` and `consequential` releases each carry three exchanges its `cutoff`
export does not, all in a `social / unspecified` compartment ecoinvent uses
nowhere else. They were added as flows by
[#25](https://github.com/brightway-labs/brightway-flows/issues/25) and
each minted a consensus flow.

All three are **products**. Each duplicates an intermediate exchange, and those
products are carried under one stable uuid by every release from 3.8 to 3.12 in
every system model:

| elementary uuid (3.8 apos only) | name | the product it duplicates |
|---|---|---|
| `22cbd60c-8017-49c4-ae6f-7f0c1c6ebf0b` | venting of argon, crude, liquid | `ccde15d5-179a-4bf2-a323-17fb1e056261` |
| `2d8d9c78-e7da-4b71-8c5e-8d1de08696c0` | venting of nitrogen, liquid | `1adfc43f-187a-4153-996c-aced5301536a` |
| `c7075d71-2cfb-42ac-bd96-4661486e1ff7` | residual wood, dry | `019600be-f3ce-4399-9e31-19cdc087ed5f` |

The asymmetry is the whole argument. Each elementary uuid occurs in exactly one
file in any ecoinvent release — 3.8 apos's elementary list — while the product
beside it is carried forward release after release, and is still there in 3.12
under the same uuid after being renamed to `residual wood, dry, measured as dry
volume`. No dataset in the 3.8 apos release references any of the three
elementary uuids. 3.9.1 removed all three, and the `social` compartment with
them.

So they are refused, the three consensus flows they minted
(`3b5f85d9601a67605e692bb34b268dd3e2b6e41c`,
`e3378e2056920fcd33aaa3650e0c8ae90e47468d`,
`a2b1125471a3d31a3094deb35114e6e62d809d73`) are withdrawn, and nothing is
published in the `soci` context.

**One consequence for the lookup.** Recognising ecoinvent's `social /
unspecified` compartment was a rule written for these three rows, and it went
with them. Recognised compartment names drop from 90 to 89, and a caller who
sends that compartment to `FlowMatcher` now gets `context_resolution:
unresolved` rather than a context with no flow behind it.

### The six Stepwise 2006 gamma-chlordane rows

Stepwise 2006 characterises chlordane under four names, and one of them is
`Chlordane, gamma-`, CAS 5566-34-7, over six compartments. All six are refused
([#167](https://github.com/brightway-labs/brightway-flows/issues/167)).

Gamma-chlordane is not a substance anybody inventories. In the environmental
literature the name means *trans*-chlordane, which Stepwise ships as its own row
under 5103-74-2 — and the number on the gamma row is not a chlordane at all: it
belongs to 2,2,4,5,6,7,8,8-octachloro-2,3,3a,4,7,7a-hexahydro-4,7-methano-1H-indene,
EC 226-938-2, two chlorines on one carbon where chlordane has one each on two.

Nothing is lost by refusing it, and that is measured rather than assumed. The
method export holds 84 chlordane factor rows: four names across 21 (category,
compartment) groups in 4 of its 19 impact categories, the amounts byte-identical
in every group, and no group carrying gamma without trans. Every number the
refused rows state is already published against `Chlordane, trans-`. Mapping
them onto that substance instead would state the same number twice in one
compartment; publishing them under their own registry number minted
`fo-2247a69a283f2f72`, `Chlordane, Gamma-`, six flows and no characterisation
factors at all.

No consensus identifier is withdrawn beside these, unlike the ecoinvent three:
Stepwise was registered and the rows refused in the same release, so they minted
nothing a consumer could be holding.

**This is the other shape of refusal.** ecoinvent's three rows live in a system
model the adapter never opens, so removing them from the fetch is a no-op that
would only fire if the adapter changed. Stepwise is a single method export —
every flow it has is in the file the adapter reads — so these six are found and
dropped on every build, which is the refusal working rather than news about it.
A file says which case it is with `excluded_rows_are_in_the_fetch`, and that is
the whole of the difference: the record still carries the vendor's identity for
the row, still states a reason a consumer can read, and is still published on
the correspondence.

## Recently fixed

Listed because earlier artifacts and earlier versions of this page said
otherwise.

- **Five pesticides and a mineral are published as the chemical they are, not as
  a relative of it.** A pesticide's common name belongs to one specific
  chemical. Applying it to a related one — the sodium salt instead of the acid,
  the chloride salt instead of the ion, the fifty-fifty mixture instead of the
  pure active half — names a different substance, with a different mass and
  different toxicity. EF 3.1 does that six times, keeping the registry number
  of the relative it really shipped, and every list that maps onto EF 3.1 maps
  by name, so ecoinvent's rows for the real substance followed it there.

  | EF 3.1 called it | the number says | which is |
  |---|---|---|
  | `paraquat` | 1910-42-5 | paraquat dichloride, 38% heavier per unit of herbicide |
  | `MCPA` | 3653-48-3 | MCPA-sodium |
  | `mecoprop-p` | 7085-19-0 | mecoprop, the racemic mixture |
  | `flupyrsulfuron-methyl` | 144740-54-5 | the sodium salt |
  | `gypsum` | 7778-18-9 | anhydrite, gypsum with the water driven off |
  | `1,3,5-triazine` | 121-82-4 | RDX, the explosive; the EC number, the synonyms and the USEtox factors on the row are all RDX's ([#199](https://github.com/brightway-labs/brightway-flows/issues/199)) |

  EF says which half is right on two of the five, in a note it ships on the rows
  itself: *"Note that the CAS No is the relevant identifier, to which also the
  ILCD LCIA characterisation factors relate."* So the numbers are kept and the
  names corrected, and the correspondence table's targets are corrected to
  match. For paraquat, MCPA and mecoprop-P the substance the name belongs to is
  in EF 3.1 in all thirteen compartments, and the table already reached it in
  the compartments where somebody had checked the number — agricultural soil for
  all three — so what changed is that the other compartments now agree with
  them. Flupyrsulfuron-methyl's parent and gypsum are on no EF 3.1 flow at all,
  so their published mappings are declined and the merge mints a consensus flow.

  Mecoprop needed its number corrected as well as its name. EF 3.1 files it
  under 7085-19-0, and the number in current use is 93-65-2 — Common Chemistry,
  asked for the old one, answers with a record whose own number is the new one,
  and ChEBI, ecoinvent and BAFU all use the new one too. The EC number moves
  with it, 230-386-8 to 202-264-4, because ECHA carries the molecule under two
  entries and pairs each with one registry number. Renaming alone would have
  merged ecoinvent's and BAFU's mecoprop rows onto the flow on a *name* match,
  across a registry-number disagreement; with the number corrected the two
  lists agree on the number, and the rows arrive on it.

  Anhydrite needed something different again, and it is the only correction
  here that is not about EF. BAFU ships its `Anhydrite` row with no registry
  number of any kind, so it had nothing to match on and minted a substance of
  its own while ecoinvent's anhydrite sat on EF's flow. It is given 7778-18-9
  and joins. **Gypsum is deliberately left as its own substance**: it is the
  dihydrate, 13397-24-5, 172.172 g/mol against anhydrite's 136.141, quarried
  and traded separately. Collapsing the two would take a conversion factor of
  0.7907 — which the overrides file can express, and which the titanium rows
  use for that exact shape — and it is not used, because the target flow
  carries no characterisation factor and the conversion would restate a
  reported gypsum tonnage as a smaller anhydrite one for nothing in return.

  **What moved**, measured on a full build of 20 August 2026 at commit 7044326
  against one of 6079386, both merging ecoinvent 3.12, ecoinvent 3.8 and BAFU
  2026-v1: 38 source rows, and no published flow changed its characterisation
  factor count or its deprecation. Two published substances called `Paraquat`
  became one. Seven consensus flows stopped carrying ecoinvent's
  flupyrsulfuron-methyl and its sodium salt at once. Gypsum and anhydrite are
  each one substance that all three source rows reach on the registry number,
  where before each was split across two. And **21 of the 34 factor collisions
  are resolved** — two ecoinvent flows arriving on one consensus flow with
  different values, so that neither was published — which is what lets MCPA's
  ecotoxicity factor be published at its own 6,268.4 CTUe rather than the
  sodium salt's 310.83.

  One correction was needed before another could work, and the build is what
  said so: ecoinvent ships the words of `Calcium sulfate dihydrate` as separate
  synonyms, so a declined gypsum row reached the `Sulfate` substance on a label
  match until the fragments were taken off
  ([#119](https://github.com/brightway-labs/brightway-flows/issues/119)).

- **Carbon tetrachloride is published once per compartment, not twice.** EF 3.1
  ships it twice in each of five air compartments — once as `CFC-10`, carrying
  registry number 56-23-5 and EC 200-262-8, and once as `Carbon tetrachloride`,
  carrying no identifier of any kind. Both copies were live, both were
  characterised under the same nine methods, and both sat in the same
  compartment, so an inventory could count the substance twice. Where the two
  disagreed they disagreed only in rounding: the cancer toxicity figure is
  0.000041784 on one and 0.0000418 on the other, about half a percent apart and
  the same number written to five digits and to three.

  The copy carrying the registry number is the one kept, and the other now
  points at it, so anyone holding the retired identifier is told where it went.
  That is the opposite of what the automatic rule would have done — the two
  hold the same number of characterisation factors, so the tiebreak falls to
  the identifier, and it picks the copy with no registry number in all five
  compartments. It is also the copy nothing maps onto: ecoinvent 3.8 and 3.12
  both reach the `CFC-10` rows, in every one of the five. **No characterisation
  factor was deleted.** Thirty-nine factor entries stopped being published
  twice, and where the two copies gave one number to different precisions the
  more precise is kept and the other recorded beside it.

  Fifteen more pairs of this shape are still live, over nine other substances,
  and they do not all want the same answer — two of them are probably two
  substances rather than one. That is
  [#106](https://github.com/brightway-labs/brightway-flows/issues/106).

- **A substance published as `Fluorescein` says it is the sodium salt, which is
  what it is.** Thirteen flows carried the name of the free acid — CAS
  2321-07-5, 332 g/mol, barely soluble in water — for a substance that is its
  disodium salt: CAS 518-47-8, 378 g/mol, and freely soluble, which is the whole
  reason the salt exists and why it is what shows up in an emission to water.

  EF 3.1 said so itself three times over and only the name disagreed. All
  thirteen rows carry the salt's registry number, all thirteen carry the salt's
  EC number, 208-253-0, and all thirteen carry the note *"Flow name and second
  synonym interchanged with each other"* — EF saying that the string in the name
  field is a synonym that was swapped in. So the correction is to the name, and
  it is made where the name is wrong: the rows are read as `Fluorescein sodium`,
  which is what Common Chemistry calls 518-47-8 and what the pharmacopoeias use.

  The old name is deliberately not kept as an alternative label. Every
  fluorescein name the registry holds for this number qualifies the word —
  `Fluorescein sodium`, `Disodium fluorescein`, `Soluble fluorescein` — and the
  bare word belongs to the acid, so publishing it would republish the confusion.
  It was doing real damage: the name was being looked up in Common Chemistry
  every build and returning **2321-07-5**, the acid's number, for twelve of the
  thirteen rows. Those twelve questions are gone, and 518-47-8 is no longer
  contested between two names.

- **BAFU's liquid water is published in cubic metres, whoever measured it.**
  Every liquid-water flow in this list is in m³ — all eleven carrying EF 3.1's
  `Water use` factors, and every water resource ecoinvent ships — and BAFU
  measured sixteen of its water rows by mass. Nine rows then landed on a flow
  stating the other unit: four kilogram rows on cubic-metre flows, and five
  cubic-metre rows on kilogram flows that BAFU's *own* kilogram rows had minted.
  The density is stated once, 1000 kg/m³, in `bafu-2026-v1-manual-fixes.json`,
  and the sixteen are carried in cubic metres; **no water row crosses a unit any
  more**, where nine did. The vendor's kilograms are not rescaled anywhere —
  each mapping states `kg` with the factor beside it as
  `qudt:conversionMultiplier`, so a consumer holding a BAFU inventory has the
  number rather than having to invent one.

  Two things are deliberately not converted. BAFU's 54 `Water` rows to air are
  water vapour, and EF 3.1 states water vapour in air by mass, so they stay in
  kilograms. And `Water, salt, ocean` runs the other way — BAFU states the
  volume, EF 3.1 states the mass — so it is accepted in
  `unit-change-allowlist.json` at 1025 kg/m³, which is the factor and the
  reasoning ecoinvent's identical row has carried since the taxonomy was built;
  two lists shipping one vendor row should not be accepted from one and reported
  from the other. BAFU's unit disagreements fall from **179 to 170**, and the
  170 left are radionuclides in becquerels against kilobecquerels, which is
  [#78](https://github.com/brightway-labs/brightway-flows/issues/78)'s
  other half. **No characterisation factor moves**, and one minted flow changes
  identifier, which is
  [#102](https://github.com/brightway-labs/brightway-flows/issues/102).

- **BAFU's water says which kind of water it is, and where it was drawn from.**
  Every water flow in every list is H₂O and registry number 7732-18-5, so the
  number cannot separate lake water from sea water. What separates them is the
  *material* — one curated line per source flow naming which of the seventeen
  kinds of water it is. EF 3.1 and all five ecoinvent releases were assigned when
  the scheme was built; BAFU was not, so its 290 water rows arrived at a merge
  that could only see one number twelve substances share. 253 were reported
  `multiple-flow-object-candidates` and placed nowhere — 9.6% of that list, and
  the single largest matching failure in the run; 30 more minted a substance of
  their own beside one the list already held, and `Water, lake` and `Water,
  river` matched plain `Water` and inherited its 209 `Water use` factors, which
  is the collapse the material axis exists to stop.

  A withdrawal's material also says which body it came from, because water taken
  from a lake was taken from a lake, so BAFU's `Water, lake`, `Water, river`,
  `Water, well` and `Water, salt, ocean` now reach EF 3.1's own lake, river,
  aquifer and ocean withdrawals rather than a second flow beside them. The rule
  refines a body the source left unstated and never overrides one it stated: the
  53 releases BAFU files to a river stay in the river, because a discharge does
  not become river water on arrival.

  On a build of EF 3.1 with ecoinvent 3.8, 3.12 and BAFU, that list's unplaced
  rows fall from **267 to 10**, and the 10 are ties between the flows of one
  substance, which belong to #76 and #84. Nine substances spelled the way BAFU
  spells them disappear, and three the taxonomy had carried without a flow since
  it was built — contaminated water, waste water and surface water, each cited in
  `environmental-materials.json` as existing *because BAFU ships a flow for it* —
  publish for the first time. **No characterisation factor moves**: no flow's
  factor count and no flow's deprecation changes, on either side
  ([#86](https://github.com/brightway-labs/brightway-flows/issues/86),
  [#83](https://github.com/brightway-labs/brightway-flows/issues/83),
  [#89](https://github.com/brightway-labs/brightway-flows/issues/89)).
  **Artifacts built before this leave 253 BAFU water rows unplaced and publish
  nine water substances under BAFU's own spelling.**

- **Hardwood and unspecified wood are flows of their own, not primary-forest
  wood.** ecoinvent ships four kinds of standing wood and EF 3.1 ships two, so
  every published correspondence table put `Wood, hard, standing` and
  `Wood, unspecified, standing` onto `Wood, primary forest, standing` — the one
  target left over once soft wood and primary forest had taken theirs. Primary
  forest is forest that has never been logged, and wood taken from it is the
  category behind deforestation and old-growth loss; ecoinvent's hardwood is
  largely managed European forest, and its unspecified wood is a statement about
  nothing at all. The GLAD ILCD→SimaPro workbook pairs the same two flows from
  the other direction, which is the same gap in EF seen from the SimaPro side.
  Both rows are now declined in `ecoinvent-match-overrides.json`, so each mints
  a consensus flow of its own — `Wood, Hard, Standing` and
  `Wood, Unspecified, Standing`, in `Resource → Biotic`, in m3. BAFU's hardwood
  and unspecified rows, which already minted flows of their own because the base
  list held nothing for them to match, now land on those two, so one resource is
  one flow whichever list a row came from. Nothing characterised changes: EF 3.1
  publishes no characterisation factor on either of its standing-wood flows.
  **Artifacts built before this publish ecoinvent's hardwood and unspecified
  wood as primary-forest wood**
  ([#81](https://github.com/brightway-labs/brightway-flows/issues/81)).

- **A renewable energy resource is published once, not twice.** EF 3.1 ships two
  names for each of four of them — `Energy, geothermal, converted` and `primary
  energy from geothermics`, and the same again for solar, wind and hydro — in
  the same category, in the same unit, with no CAS, no synonym, no comment and
  no characterisation factor on either row to tell them apart. Both survived the
  merge, so anyone adding up renewable energy resources counted each of the four
  twice, and anyone mapping their own flows in had two equally plausible targets.
  The `converted` name is the one ecoinvent 3.8, ecoinvent 3.12 and BAFU also
  publish and the one their correspondence tables point at; the second name
  comes from the legacy ILCD/ELCD block that also produced EF's `peat` and
  `uranium` rows. The four legacy rows are now deprecated onto their partner,
  which the `redirects` entry resolves, and the name they were published under
  stays on the flow object as an alternative label
  ([#73](https://github.com/brightway-labs/brightway-flows/issues/73)).
  **What that assumes:** that EF meant one quantity by both names. Nothing EF
  publishes says otherwise — neither row is characterised by any of its methods,
  so no factor prefers one — but if "primary" was ever meant as a gross figure
  and "converted" as what a plant got out of it, the redirect equates two
  numbers that differ by a conversion efficiency. `primary energy from waves` is
  untouched: it is the only wave energy entry any list here has, so it duplicates
  nothing, and a rule written to drop the `primary energy from …` family would
  have deleted it. **Artifacts built before this publish four resources twice.**

- **The shape-free SMILES slot no longer holds shapes.** `smiles_string` is "a
  molecular graph, no chiral or isotopic information", and for **7 substances,
  91 elementary flows** it held a structure that still carried the shape — the
  project's own check for stereochemistry returned true for the string sitting
  in the field defined by its absence. All 7 came from ChEBI SMILES RDKit cannot
  read — L-tryptophan's is written with the indole nitrogen missing its
  hydrogen, so the ring will not kekulise; the split moved every stereo string
  it could flatten and left the unreadable ones where they were, since it had no
  graph to put in their place. Being unable to compute a graph now means
  publishing none: the string moves to `isomeric_smiles_string` regardless, and
  all 7 keep a readable graph another source supplied
  ([#51](https://github.com/brightway-labs/brightway-flows/issues/51)).
  **Artifacts built before this publish a stereochemical structure under a field
  name that denies it.**
- **A deprecated identifier is no longer silent.** The published export carries
  only non-deprecated flows, so a consumer holding an identifier this list had
  deprecated saw exactly what one holding an identifier that was never
  harmonised saw: a lookup miss, with no way to tell the two apart. That
  ambiguity turned one import defect into five separate investigations, and
  downstream it dropped 20,569 of 225,014 EF 3.1 characterisation factors —
  9.1%, every one of them a flow this list had merged into another. Schema
  version 5 adds a `redirects` entry per deprecated flow, resolving to the
  *terminal* survivor, with the reason beside it
  ([#39](https://github.com/brightway-labs/brightway-flows/issues/39)).
  Read [the section above](#what-a-redirects-reason-does-and-does-not-promise)
  before acting on one.

- **Every registered ecoinvent version can now be merged.** 3.9.1, 3.10.1 and
  3.11 were registered with no context mapping checked in, so `--source
  ecoinvent-3.11` was refused at resolution — earlier still, it resolved,
  downloaded, ran the whole transform, and only then failed every row. All
  three ship exactly the 25 compartment pairs 3.12 ships, so the rules were
  3.8's minus the two it alone has, and no new decision was involved.
- **Every version carries the same substance-level corrections.** Uranium-238's
  CAS, `Silver-110`'s label, the three lindane isomers' CAS and
  Mefentrifluconazole's missing CAS were stated in 3.12's fixes file and in EF
  3.1's, and nowhere else; every other registered ecoinvent version shipped the
  same rows, under the same UUIDs, uncorrected. A build merging two of them was
  handed two lists disagreeing about what a nuclide's CAS is, which is the
  situation those fixes exist to prevent. Each version now has a fixes file
  stating every correction its own rows can carry — 3.8 and 3.9.1 correct ten
  Uranium-238 and ten `Silver-110` rows rather than nine, because they still
  have `air / lower stratosphere + upper troposphere`, which 3.10.1 drops
  ([#26](https://github.com/brightway-labs/brightway-flows/issues/26)).
- **`Silver-110` is the isomer.** Both source lists write the bare name, and
  neither carries a `Silver-110m` row, so the list published the 24.56-second
  ground state for a flow that reports the 249.863-day isomer. The half-life
  cannot settle which one a source means — 49 of the 81 matched isotope objects
  are shorter-lived than a year and most legitimately so — but EF's own
  characterisation factor can: `Ionising radiation, human health` gives these
  flows 0.0236 kBq U235-eq per kBq, between Antimony-124 and Manganese-54, and
  none of the 21 nuclides with a water factor under that method is short-lived.
  The label is corrected in both lists' manual fixes. A bare `m` in a label now
  resolves to the longest-lived excited state rather than to the state PubChem
  spells `m` — those are different nuclides here, 249.863 days against 660
  nanoseconds — which changes nothing for the seven isomers already published.
  **Artifacts built before this publish a ground state's half-life, decay mode
  and specific activity under this flow**, and the flow object's identifier
  changes with the name
  ([#24](https://github.com/brightway-labs/brightway-flows/issues/24)).
- **One structure is one value, however it is spelled.** A canonical SMILES is
  canonical only per toolkit, and both RDKit stages decided "is this value new?"
  by comparing strings — so RDKit's spelling of a molecule PubChem had already
  supplied was never equal to PubChem's and was appended as a second candidate.
  **5,708 of 17,170 stored SMILES were a duplicate spelling of a structure the
  same flow object already carried, on 5,270 flow objects**; for 3,285 of them
  the record had exactly one structure once the spellings were collapsed, so the
  published list asserted several structures where the data named one. Camphor
  arrived as both `CC1(C2CCC1(C(=O)C2)C)C` and `CC12CCC(CC1=O)C2(C)C`. The flow
  layer had it worse — 61,128 redundant strings on 57,534 flows. RDKit no longer
  adds a spelling of a structure that is already there, and spellings that reach
  a record anyway are collapsed to RDKit's canonical form on both layers; 482
  duplicates in `isomeric_smiles_string` went with them. `inchi2d_string` and
  `inchi2d_key_string` were never affected — InChI is canonical across toolkits.
  **Artifacts built before this overstate how many structures a substance has**
  ([#22](https://github.com/brightway-labs/brightway-flows/issues/22)).
- **A source reference is stored once.** `elementary_flow_sources` held 197,836
  rows for 103,843 links: **every base-list flow's reference was written twice**,
  every merged row's once. The table had no constraint on the link it records,
  so the merge's `INSERT OR IGNORE` had no conflict to detect and wrote a second
  copy of what the transform had already written; and the merge re-synced every
  pre-existing flow rather than the 7,441 it had matched. The link is now the
  table's key. **Artifacts built before this double-count the base list** — if
  you have counted contributions per flow or per list from that table, the EF
  figures are 2x and the merged ones are not
  ([#23](https://github.com/brightway-labs/brightway-flows/issues/23)).
- **Nuclides are identified by nuclide.** A nuclide row used to be found by
  looking its name up in a table of every spelling it might go by. An isomer
  and its ground state share most of those spellings, so one overwrote the
  other and PubChem's row order decided which: **37 of 79 published nuclides
  carried an isomer's half-life, decay mode and specific activity under a
  ground state's name.** Potassium-40 shipped at 336 nanoseconds against 1.25
  billion years, Uranium-238 at 280 nanoseconds against 4.5 billion, and four
  records were published twice — once as the ground state and once as its
  isomer — so `Technetium-99` and `Technetium-99m` were indistinguishable.
  Matching is now on the element/nucleon-count/nuclear-state triple, which the
  two rows differ in, and two checks refuse a record that contradicts itself.
  Artifacts built before this carry the wrong values
  ([#18](https://github.com/brightway-labs/brightway-flows/issues/18)).
- **PubChem's decay table is read in register.** The table arrives as parallel
  columns and is zipped back into rows by position. Blank cells were skipped
  before the zip, so a missing value pulled every later value in that column up
  one row: **18 of 118 elements published a decay mode belonging to a different
  nuclide**, and 138 ground states came out decaying by isomeric transition,
  which a ground state cannot do. Curium, lanthanum, neptunium and lead are
  among the affected elements and all four are carried by this list. Blanks are
  kept as blanks now, and a column that still does not line up is refused
  rather than zipped short. This is the same defect as the positional context
  reconstruction below, one layer down.
- **Long half-lives are published at all.** `4.463 Gy`, `211.1 ky`, `16.14 My`
  — PubChem writes the long ones with an SI prefix on the year, and the unit
  table had none of them, so every nuclide an inventory is most likely to carry
  parsed to nothing while the nanosecond isomer records that had displaced them
  parsed perfectly. ChemLIN's `7.04(1) &times; 10<sup>8</sup> a` lost its
  exponent to a scrape that stopped at the first tag, which cost six more.
- **A PubChem record title is no longer published as a preferred label.** The
  `pubchem_readable_name` step took one whenever a flow's CAS mapped to a single
  PubChem compound, and it ran last of the stages that write a label, so its
  name was the one that shipped: **17,942 labels over 1,397 distinct pairs in
  the 2026-08-06 run**, none of them ruled on by anyone. Audited against Common
  Chemistry and ChEBI, 424 of those pairs assert an identity neither source
  supports and 134 narrow the flow's scope. 43 flows published a database
  accession as their name — `CID 5359965`, `Epitope ID:2151205`. The step is
  gone. **Artifacts built before this carry those labels**; the original name
  is on the flow's `altLabel` list in them, because the step kept it there.
- **`schema_version` is now enforced.** It used to be a literal that nothing
  validated. JSON Schemas are now generated from the record classes, checked in
  under `src/brightway_flows/data/schemas/`, guarded by a test that fails on
  drift, and `check_schema_version` raises on an unsupported version rather than
  reading the file anyway. See [File schemas](schemas.md).
- **Record shapes are now uniform.** Flows added by the merge used to be built
  as raw dicts and omitted fields that transform-created flows carried — only 9
  of 19 fields appeared on every record in `harmonised-flows.json`. Merge-created
  flows now go through the record classes, so one schema covers both paths.
  Artifacts written before that change still have the divergence.
- **A wrong field name now raises.** Records used to carry a `get()` shim that
  returned `None` for anything it did not recognise, so a typo or a field read
  off the wrong record type failed silently. It is gone; the pipeline reads by
  attribute. Removing it exposed three dead branches — including the
  origin-qualifier guards above — and a broken applied-changes log in consensus
  matching, which had been building its entries under a condition that could no
  longer be true and would have lost every flow name and old value.

## Ongoing internal work

Not user-visible, but it explains churn in the codebase: the ETL has been moved
off untyped dictionaries onto explicit record types. Loading, the processing
steps, layering and the merge all read records by attribute now. The SQLite
writer, the JSON exports and the Flask apps still work in dictionaries — they
serialise whole records, and the apps read rows back from SQLite and JSON.

Reference data from external APIs — ChEBI records, PubChem compounds, GLAD rows
— stays dictionary-shaped on purpose. Their shape is set by a foreign API and
changes outside this project.

The merge row loop has finished being decomposed and the transitional record
shim is gone. What remains on the tracking issue is the property resolution
problem above, and provenance reification — which is what gates a genuinely
valid JSON-LD export.

See [Architecture](architecture.md) and [Data model](data-model.md).
