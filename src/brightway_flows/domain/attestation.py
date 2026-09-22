"""Which stage stands behind each value of a property.

A property that carries several values carries one `provenance` list covering
all of them, and that list cannot say which source gave which value.  DABCO's
InChIKey field is the example: two values and three provenance entries, with
nothing joining them::

    inchi2d_key_string
      @value        IMNIMPAHZVJRPE-UHFFFAOYSA-N, KKCOQCVPBASEDD-UHFFFAOYSA-N
      provenance    chebi_semantic, pubchem_semantic, rdkit_post_consensus

A rule that withdraws one of two contradicting values has to withdraw the
InChIKey that came from the same place as the formula it withdrew, and the
provenance list cannot be asked that question.

So this adds **one** key beside it, `attested_by`, mapping each value to the
stages that wrote or confirmed it::

    attested_by
      IMNIMPAHZVJRPE-UHFFFAOYSA-N   enrich_references.chebi_semantic,
                                    enrich_references.pubchem_semantic
      KKCOQCVPBASEDD-UHFFFAOYSA-N   opsin_iupac, rdkit_post_consensus

`provenance` is untouched and stays the full record: what ran, what the primary
source was, what the value was derived from.  This answers the one question a
withdrawal needs and nothing else.

**Keyed on the value, not on its position.**  A positional list beside `@value`
would have to be kept in step by every stage that sorts, filters or collapses
that list -- `_merge_semantic_property` sorts, three gates in `enrich_references`
filter, `collapse_smiles_spellings` collapses -- and none of them would fail
visibly when they forgot.  A mapping survives all of those untouched; a filtered
value leaves an entry behind, which `prune` clears at the end.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

#: The key this module owns on a property entry.  A plain string rather than an
#: IRI: it describes the record's own bookkeeping rather than a claim about the
#: substance, so it is not a CHEMROF predicate and must not be given one (#310).
ATTESTED_BY = "attested_by"


def attest(entry: dict[str, Any], values: Iterable[str], generator: str) -> None:
    """Record that *generator* stands behind each of *values* on *entry*.

    Called by every stage that writes a structural value, including one writing
    a value the record already had -- agreement between two sources is the
    thing the withdrawal rule reads, so a confirmation counts as an attestation
    exactly as a first write does.
    """
    if not generator:
        return
    existing = entry.get(ATTESTED_BY)
    table: dict[str, list[str]] = {}
    if isinstance(existing, dict):
        for value, sources in existing.items():
            if isinstance(sources, list):
                table[str(value)] = [str(s) for s in sources]
            elif isinstance(sources, str):
                table[str(value)] = [sources]
    for value in values:
        text = str(value).strip()
        if not text:
            continue
        sources = table.setdefault(text, [])
        if generator not in sources:
            sources.append(generator)
            sources.sort()
    if table:
        entry[ATTESTED_BY] = table


def attested_by(entry: Any, value: str) -> tuple[str, ...]:
    """The stages standing behind *value*, or an empty tuple if none is recorded.

    Empty is not the same as "nobody": a record written before this existed, or
    by a stage that does not attest, says nothing here.  A rule reading this
    has to treat silence as "unknown" and leave the value alone, never as
    "unattested, therefore withdrawable".
    """
    if not isinstance(entry, dict):
        return ()
    table = entry.get(ATTESTED_BY)
    if not isinstance(table, dict):
        return ()
    sources = table.get(str(value).strip())
    if isinstance(sources, str):
        return (sources,)
    if isinstance(sources, list):
        return tuple(str(s) for s in sources)
    return ()


def prune(entry: Any) -> None:
    """Drop attestations for values *entry* no longer publishes.

    The gates that withdraw a value rewrite `@value` in place and know nothing
    about this key, which is the point of keying on the value -- but a stale
    entry should not reach the published record, so the last stage to touch a
    property calls this.
    """
    if not isinstance(entry, dict):
        return
    table = entry.get(ATTESTED_BY)
    if not isinstance(table, dict):
        return
    raw = entry.get("@value")
    published = {
        str(v).strip()
        for v in (raw if isinstance(raw, list) else [raw] if raw else [])
        if str(v).strip()
    }
    kept = {value: sources for value, sources in table.items() if value in published}
    if kept:
        entry[ATTESTED_BY] = kept
    else:
        entry.pop(ATTESTED_BY, None)
