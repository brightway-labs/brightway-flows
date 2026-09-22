# Why this exists

## The problem

An elementary flow is an exchange between the technosphere and the environment:
a kilogram of carbon dioxide to air, a cubic metre of water from a river, a
square-metre-year of forest occupied. Every LCI database maintains its own list
of them, and every LCIA method attaches characterisation factors to *some* list.

The lists disagree in four independent ways, and each one breaks a different
thing.

### 1. Names disagree

The same substance appears as `Carbon dioxide, fossil`, `Carbon dioxide (fossil)`,
`CO2, fossil`, and `carbon dioxide, from fossil fuels`. String matching gets most
of these and silently misses the rest.

Worse, names are not merely inconsistent — they are sometimes *wrong*. Source
lists contain genuine substance confusions, and so do the reference databases
used to fix them. A real case from this project: PubChem associates CAS
7440-38-2 (elemental arsenic) with the record for arsane, AsH₃. Follow that link
naively and the arsenic flow gets renamed "arsane" — and then, because names are
how downstream steps recognise things, the *arsine* flow gets renamed "arsenic".
Two substances swap identities, and no string comparison anywhere in the chain
notices.

### 2. Identifiers disagree, and are not unique

CAS numbers look authoritative but are not a primary key for this purpose. One
CAS can be listed by several PubChem compounds. ChEBI records occasionally claim
a CAS that belongs to a different substance — CHEBI:30146 (lithium hydride,
HLi) lists 7439-93-2, which is the CAS for lithium *metal*. Merge on CAS alone
and lithium hydride's synonyms and molecular formula contaminate the lithium
element.

### 3. Compartments disagree

`Emissions to air, urban air close to ground`, `air/urban air close to ground`,
and `Emissions/Emissions to air/Emissions to air, urban air close to ground`
denote the same thing. Meanwhile `low population density` in one list and
`Rural (<1000 people/square mile)` in another are *nearly* the same thing but
not defined identically, and `water` with no further qualification may or may
not include groundwater depending on who wrote it.

### 4. Distinctions collapse or multiply

Biogenic and fossil CO₂ share a CAS number and differ only by a word in the
name — but they must never be merged, because their carbon-cycle accounting
differs. Green, blue, and grey water all share CAS 7732-18-5 and must stay
apart for water-footprint methods. Conversely, `carbon dioxide (biogenic-100yr)`
and `Correction flow for delayed emission of biogenic carbon dioxide (within
first 100 years)` *are* the same thing under different names.

There is no rule of the form "same CAS ⇒ same flow" or "different name ⇒
different flow" that survives contact with the data.

## The approach

Four commitments follow from the above.

### Separate identity from occurrence

A substance's identity ("what is carbon dioxide") does not depend on which
compartment it was emitted to or which database recorded it. Contexts, units,
and source references do. The project therefore keeps two layers — **flow
objects** for substance identity and **elementary flows** for
substance-in-a-context — and links them.

See [Flow objects and elementary flows](two-layers.md).

### Build one context vocabulary, deliberately small

Rather than mapping every source compartment to every other, all lists map onto
a single controlled vocabulary of 60 contexts. A context attribute is only
included when characterisation factors actually differ across its values —
otherwise it is complexity without information.

See [Flow contexts](contexts.md).

### Decide from evidence, and record the evidence

Every value in the output is traceable to the source that asserted it and to the
processing step that wrote it. Where automated identity resolution is not
confident, it declines to act rather than guessing, and the case is written to a
review file for a human.

The guards described above (arsenic/arsane, lithium hydride) are not incidental
bug fixes; they are the mechanism. Each is a rule that says *do not accept this
inference unless a second, independent source agrees*.

See [How a flow is decided](../deciding/index.md).

### Never discard the source record

Every consensus flow keeps a `source_refs` list naming each source flow that
contributed to it — the original UUID, the original name, the original
compartment strings, and the file it was read from. Deduplication happens
downstream of loading, never during it, so the evidence for a merge decision
survives the merge.

(These references are currently stripped from the published JSON files and have
to be read from the SQLite database instead — the commitment holds, the delivery
is incomplete. See [Known limitations](../reference/limitations.md).)

This is what makes the output usable as a *translation table* and not only as a
substance list.

## What this is not

- **Not a characterisation factor database.** The project carries LCIA method
  references from EF 3.1 through the pipeline, but it does not compute, correct,
  or reconcile factors.
- **Not an inventory database.** There are no processes and no exchanges, only
  the elementary flows themselves.
- **Not a finished standard.** The context taxonomy is explicitly expected to
  change as LCIA methods develop. See [Known limitations](../reference/limitations.md).
