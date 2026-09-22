# How do I find out why a flow says what it says?

*Part of [How a flow is decided](index.md), and how to check any answer the rest of this section describes.*

Two independent records are kept:

- **Field-level provenance** — for a data value, which source asserted it,
  recorded as a structured PROV record rather than free text. Carried on the
  value itself, and traced across the run by `provenance_activities`.
- **Which source stands behind which value.** Where a field holds several
  values, the provenance list above covers the field as a whole and cannot say
  which source gave which value: DABCO's InChIKey field held two keys and three
  provenance entries with nothing joining them. A companion `attested_by`
  records, per value, which steps wrote or confirmed it. It is what lets the
  salt rule above withdraw the InChIKey that came from the same place as the
  formula it withdrew. A value nothing attests reads as *unknown*, never as
  unsupported, so an older record is never withdrawn for its silence.
- **The change log** — for each field the pipeline wrote, which processing step
  wrote it, the old value, the new value, and the reason. The `changelog`
  table, keyed by flow object id, with `changelog_flows` naming the elementary
  flows each edit landed on. One row per edit: the biggest fields in the log
  belong to the substance, and an edit to a substance reaches every flow that
  shares it, so a row per flow said the same thing a dozen times over.
  `/changes` shows all of it; `/flows/<uuid>/changes` shows one flow's, on
  demand.

Both are written by every run. They were optional JSON files until the review
application was consolidated onto the database, which meant the record of why a
value is what it is normally did not exist.

A value the pipeline **declined** to write is the same kind of fact. When two
flows are collapsed into one and both of them published a characterisation
factor for the same method, only one number can be published, and the other
used to disappear without trace — so nothing told a reader that the number they
were looking at had been chosen at all. The number not published is now kept on
the factor that superseded it, in `superseded_values`, with its own provenance
naming the flow that published it.

No processing step mutates a flow directly; each proposes changes that the
engine applies and logs. That is what makes the change log complete rather than
best-effort. Where several steps write the same field, the last one wins, and
the log shows the sequence.
