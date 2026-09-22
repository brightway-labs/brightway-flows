# What do we do when one registry number reaches several substances?

*Part of [How a flow is decided](index.md), at the stage where the pipeline goes to ChEBI, PubChem and Common Chemistry to find out what a substance is.*

Each of these exists because a specific, reproducible failure was found in real
data. They are worth understanding because they define what "matched" means in
this project.

## The CAS cross-check: don't trust a second-hand cross-reference

ChEBI IDs for a flow are resolved two ways. **ChEBI-direct** uses ChEBI's own
CAS cross-references — the ChEBI record itself claims the CAS.
**PubChem-derived** is a second hop: PubChem says "this compound has CAS *Y* and
is also CHEBI:*Z*".

The second hop is unreliable. CAS 25013-16-5 (butylated hydroxyanisole,
C₁₁H₁₆O₂) was mapped by PubChem to CHEBI:17688, which is (S)-nicotine,
C₁₀H₁₄N₂. The two share no structural relationship, and the ChEBI record for
nicotine does not list that CAS. Unguarded, all 105 of the nicotine record's
cross-references — Beilstein IDs, PubMed articles, DrugBank, HMDB — would have
been attached to butylated hydroxyanisole.

**The rule:** a PubChem-derived ChEBI ID is kept only if the ChEBI record's own
CAS numbers overlap the CAS numbers being queried. No overlap, no match.

This guard also fixes a subtler problem. When related stereoisomers share a CAS
family, PubChem may map all of them to one ChEBI entry — and that entry may
carry stereochemistry-specific synonyms like `(+)-(1S,3S,4R)-menthol`. Without
the cross-check, that name spreads to (−)-menthol, D-menthol, and racemic
menthol, all of which are different substances.

## The formula check: ChEBI is not infallible either

ChEBI-direct matches skip the cross-check, because ChEBI is asserting the CAS
itself. But ChEBI records occasionally claim a CAS that belongs to a different
substance. CHEBI:30146 (lithium hydride, HLi) lists CAS 7439-93-2, which is the
CAS for lithium *metal* (CHEBI:30145, Li). Unguarded, lithium hydride's synonyms
("hydridolithium", "[LiH]", "hydrure de lithium") become synonyms of the lithium
element, and its formula HLi contaminates the element's properties.

**The rule:** when several ChEBI-direct records match one CAS and the flow has a
known formula, candidates are scored for formula similarity and those below a
similarity threshold are discarded. Li vs HLi scores about 0.50, below the 0.55
threshold, so lithium hydride is rejected for the lithium element. Identical
formulae (stereoisomers) score 1.0 and are always kept. A record with *no*
formula is kept — absence of data is not evidence against a match.

The flow's own formula comes from its `molecular_formula` property, and from
what its name implies. That is the whole basis: there is no separate
flow-level formula field, which is why the guard is silent for flows whose
structure has not yet been enriched.

## The primary-CAS rule: pick the compound that owns the number

A PubChem compound lists a primary CAS — the first in its own identifiers — plus
secondary cross-references. When one CAS maps to several compounds, the one
whose *primary* CAS matches is the right one.

CAS 7440-38-2 is elemental arsenic; CAS 7784-42-1 is arsine (arsane). PubChem
lists both numbers on both compounds:

| PubChem CID | Substance | Formula | Primary CAS |
|---|---|---|---|
| 23969 | arsane | AsH₃ | 7784-42-1 |
| 5359596 | arsenic | As | 7440-38-2 |

ChEBI has no CAS entry for either number, so the ChEBI cross-reference strategy
fails and selection falls through to "first compound in PubChem's listing
order" — which for 7440-38-2 is arsane. That produced a three-stage cascade:
the arsenic flow was renamed "arsane"; then, because names from *all* compounds
sharing a CAS were pooled into one candidate list, "arsenic" was available as a
name for arsine and the readability scorer preferred it over "hydrogen
arsenide", so arsine was renamed "arsenic"; then element enrichment matched
elemental arsenic to the flow now labelled "arsenic" — the arsine flow — and
enriched it with the wrong element's properties.

**The rules:** prefer the compound whose primary CAS equals the queried CAS; and
propagate a compound's names only to its primary CAS, not to its secondary
cross-references.

## The contested-CAS rule: one number claimed by two names

The mirror of the case above: not one number mapping to several registry
compounds, but one number carried by several **flow names in one source list**.
Merging flows on a shared CAS treats the number as proof of shared identity,
and in EF 3.1 that assumption fails at scale: 68 registry numbers are carried
by more than one flow name, and 53 of those groups are fused onto a single
flow object, taking 963 elementary flows and 1,908 characterisation factors
with them ([#34](https://github.com/brightway-labs/brightway-flows/issues/34)).

The tempting rule — refuse to merge on a contested number without external
corroboration — does not survive measurement, and is deliberately not the rule.
19 of the 68 groups are contested **because this project made them so**: every
CAS the [#19](https://github.com/brightway-labs/brightway-flows/issues/19)
code table and [#35](https://github.com/brightway-labs/brightway-flows/issues/35)
supplied is by construction a number two names now carry, and the merge is the
whole point of supplying it. A rule built on suspicion undoes our own
corrections.

Four signals decide instead, in order, and the first that speaks wins:

1. **A curated ruling**, from `contested-cas-decisions.json`. Final either way —
   the same contract as `preferred-label-decisions.json`.
2. **A number this project supplied by manual fix.** A `cas_numbers` fix in a
   `*-manual-fixes.json` is a curator saying, with evidence in its comment,
   that this name denotes this substance. Read from the fixes file rather than
   restated, so the two cannot drift apart.
3. **Divergent characterisation factors.** If EF gives the two names
   *different* factors for the same method in the same context, EF is saying
   they are different substances, and no external source is needed to hear it.
   Measured over the 53 fused groups this fires on 11, by 19% to twenty orders
   of magnitude — including all four fused hydrofluoroether groups, which
   Common Chemistry only partly corroborates and cannot adjudicate at all for
   `84011-06-3`, a number it has no record for.
4. **Full Common Chemistry synonymy** — every name in the group is a name the
   registry holds for the number. Merge.

Anything else is undecided: the flows **stay merged**, and the group goes to
the [`contested-cas` queue](../operating/review-app.md) as a question for a
curator. 21 groups sit there, and splitting them by rule would change 307
published flows on no evidence at all — which is the failure mode the
suspicion rule was rejected for. Structure comparison is deliberately not a
signal here while [#42](https://github.com/brightway-labs/brightway-flows/issues/42)
is repairing stereo layers that are wrong in both directions; the measurement
said it is not needed — no group's verdict depends on it.

Implemented in `flow_layers/contested_cas.py`, whose module docstring carries
the full decision record, including which flows are allowed to ask the
question at all.

## Where a number reaches several substances: how an arriving row is narrowed

The two rules above are about the list this project publishes. This one is
about a row arriving from a source list, and it is the everyday case: BAFU
ships a row called simply `Water`, carrying 7732-18-5, and **twelve substances
in this list carry that number too** — every kind of water is H₂O. The number
is not wrong and it does not identify anything on its own.

Two things are settled before the number is read at all: a curated target in a
`*-match-overrides.json`, which is a decision and not evidence to be weighed,
and a row the water or land taxonomy already names — which is why ecoinvent's
`Water, green` does not have to be told apart from eleven other waters by a
registry number every one of them shares.

Otherwise a number that reaches exactly one substance ends the question there,
and that is what happens to almost every row. Where it reaches several, the
row's own name is read — but only ever to *choose among the substances the number
already found*, never to reach one it did not. Four narrowings run in order,
and each records what it was under `basis` on the row's outcome, so a curator
reading the merge report can tell one from another:

1. **The origin qualifier in the name** (`cas+qualifier`). Fossil against
   biogenic CO₂, green against blue against grey water — the qualifier is read
   from every name the row carries, not only the one it is published under,
   because a naming step may already have normalised it away. A qualifier
   this vocabulary knows and **no substance in the list carries** is the
   opposite case: every candidate the number found has been ruled out by the
   row's own name, so the row is reported as having no candidate and mints a
   substance rather than falling through to the next narrowing. Without that,
   `Carbon dioxide, non-fossil, resource correction` reached plain
   `Carbon Dioxide` — the very substance the qualifier exists to hold it apart
   from ([#133](https://github.com/brightway-labs/brightway-flows/issues/133)).
2. **The whole name** (`cas+label`), against the candidates' own published
   names and synonyms.
3. **The industry designation the name ends in** (`cas+designation`), for a
   list carrying [SimaPro's naming
   habits](../operating/sources.md#simapro-lineage). ecoinvent 2 wrote a
   family of fluorinated ethers as structural prose with the designation
   appended — `Ether, 1,1,2,2-Tetrafluoroethyl 2,2,2-trifluoroethyl-,
   HFE-347mcc3` — and gave three members of that family one registry number,
   406-78-0, which EF 3.1 carries as well. The prose is identical on all
   three rows and is nobody's published name, so step 2 reads nothing; the
   last comma-segment is EF's own name for exactly one of the three. Read
   only against those three, so it can settle a family and never introduce a
   substance the number did not reach.
4. **Which candidate is actually called that** (`+preferred-name`), tried last
   and only on a row about to be reported as matching too much. Eleven of the
   twelve waters answer to "water" among their synonyms, correctly, so steps 2
   and 3 leave the tie standing; one of them is *called* `Water`, and that is a
   better answer than eleven that merely also go by it
   ([#86](https://github.com/brightway-labs/brightway-flows/issues/86)).
   The row's own name is asked, not any of its names, so `Water, river` is not
   sent to plain `Water`.

Still tied after all four, the row is left unmatched as
`multiple-flow-object-candidates` and named in the merge report. Nothing here
guesses, and nothing here overrules the number: a row whose name says one
substance and whose number says another lands on the number's, every time.

**Which is why a number that is simply wrong takes a curated fix, not a
narrowing.** BAFU ships one row called `Cadmium II` — the +2 ion — and gives
it 7440-43-9, which is cadmium the metal. The number reaches exactly one
substance, so no narrowing is even reached, and the row landed on the element
while ecoinvent's fourteen rows of that same name, carrying the ion's own
22537-48-0, landed on `Cadmium(2+)`: one name, two substances, decided by
which list wrote the row. The evidence that the name is the half that is right
is BAFU's own — it writes `Chromium III` with the trivalent ion's number, and
it already ships a plain `Cadmium` row under 7440-43-9 in the same
compartment, so read as the metal the row is a second name for a substance the
list lists once. The correction is a `cas_numbers` fix in
`bafu-2026-v1-manual-fixes.json` recording what the vendor wrote and what it
should have written, for each of `Cadmium II`, `Zinc II`, `Mercury II`,
`Lead II` and `Nickel II`
([#146](https://github.com/brightway-labs/brightway-flows/issues/146)) —
the same shape as the correction that gives EF's `vanadium (v)` flows
pentavalent vanadium's number instead of the divalent ion's, in [What we have
found](../findings/names-and-numbers.md#when-the-name-is-the-half-that-is-right). A rule that
read the numeral off the name instead would decide a substance's identity by
regex.

Implemented in `resolve_flow_object`, in `merge/matching.py`.

## The curated-CAS gate: a vendor catalogue is not a registry

The primary-CAS rule above decides between compounds during consensus matching.
The same question arises earlier, where structures and names are written onto a
substance, and there it used to go unasked.

CAS numbers are looked up through PubChem's `xref/RN` cross-reference index.
That index aggregates the CAS numbers of every *substance* record standardised
onto a compound — and a substance record can be a chemical vendor's catalogue
listing. A vendor that types the wrong number into its catalogue puts that
number on a compound it does not belong to.

CAS 686-31-7 is tert-amyl peroxy-2-ethylhexanoate. `xref/RN` returns three
compounds for it:

| PubChem CID | Formula | Substance |
|---|---|---|
| 102465 | C₁₃H₂₆O₃ | tert-amyl peroxy-2-ethylhexanoate |
| 121489259 | C₁₃H₂₆O₃ | the same, (2R) enantiomer |
| 106206 | C₁₈H₁₂MgN₂O₂ | **magnesium bis(quinolin-8-olate)** |

The magnesium salt is there because two vendor listings carry 686-31-7 on it.
The number appears nowhere on that compound's own page — not in its synonyms,
not in its CAS section. It exists only in the cross-reference index.

Merged unchecked, the substance published two molecular formulas, three InChI,
four SMILES and ten IUPAC names spanning two unrelated compounds. It was also
typed `ChemicalSalt`, because semantic typing reads the first SMILES of a sorted
list and the magnesium salt sorts first.

PubChem curates a **CAS** section on each compound, admitting only numbers a
registry or regulator attests, with a reference per source. For CID 102465 it
gives 686-31-7 from ten of them — AICIS, CAMEO Chemicals, CAS Common Chemistry,
ChemIDplus, EPA CDR, EPA TSCA, EPA DSSTox, ECHA, FDA GSRS, NZ EPA. For CID
106206 it gives 67952-28-7 and 14639-28-2, and not 686-31-7.

**The rule:** a compound is dropped from a CAS lookup when its own curated CAS
section does not list the number searched on. Two conditions keep this from
overreaching:

- **Something better has to exist first.** A compound is dropped only when
  another candidate for the same CAS *is* attested. Where no candidate is
  attested, all are kept and the substance stays as ambiguous as it was —
  the pipeline does not guess.
- **Silence is not denial.** Where no curated record has been fetched for a
  compound, it is kept. Only a record that was retrieved and does not list the
  number counts as evidence against.

That second condition is why the identifier cache stores an empty record for a
compound PubChem holds no registry identifiers for. "Asked, and there are none"
and "never asked" are different answers, and only the first may drop a
candidate.

Every CAS the gate narrowed is listed in the **CAS links PubChem does not
curate** queue of the [review application](../operating/review-app.md), with the
compounds kept, dropped, and not asked about.

**A semantic type can change without the substance having changed.** Type
assignment reads the *first* SMILES of a sorted list, so removing a candidate
can change which structure it reads. Over a 400-flow verification run the gate
narrowed 55 substances to a single structure, took the count carrying more than
one from 135 to 80 — and moved 15 semantic types, 10 of them on substances that
are still ambiguous and whose type was therefore already arbitrary. That
arbitrariness is
[a known limitation](../reference/limitations.md#some-flow-objects-merge-unrelated-substances),
not something this rule introduced; the gate makes it visible by changing which
arbitrary answer comes out.
