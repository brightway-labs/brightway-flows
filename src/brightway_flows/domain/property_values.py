"""Semantic property values, typed the way the ontology says they are typed.

Every ChemROF slot this project emits declares a range, and until now every one
of them was written as a string: ``molecular_mass`` as ``"398.54"``,
``elemental_charge`` as ``"0"``.  Expanded as JSON-LD that is a plain literal
where the ontology promised ``xsd:double`` and ``xsd:integer``, so a consumer
cannot sort by mass or filter by charge without re-parsing every value.

Three corrections live here, because each is "what a property value should look
like on the way out" and each has to happen everywhere a property is written:

**Datatypes.** :func:`coerce_property_datatypes` reads
:data:`~brightway_flows.domain.vocabulary.TERM_DATATYPE` and turns the
string into a number.  A value that will not parse is *kept as it is* and
counted, never dropped -- the source lists contain ranges, approximations and
unit-suffixed masses, and losing them silently would be worse than publishing
them untyped.

**One structure, one value.**  :func:`collapse_smiles_spellings` reduces two
spellings of the same molecule to one.  Two toolkits spell a canonical SMILES
differently, and comparing the strings said they were two structures (#22).
:func:`drop_redundant_flat_inchikeys` does the matching job for the key slot,
where the second value is not another spelling but the same substance with its
stereochemistry taken off -- and is some other substance's real key (#50).

**Whole-entity charge.** ChemROF scopes ``formal_charge`` to ``AtomOccurrence``:
"the charge remaining on an atom when all ligands are removed homolytically".
It is a property of one atom inside a molecule, not of the molecule.  The net
charge of a chemical entity is ``elemental_charge``, whose declared domain is
``ChemicalEntity`` and whose definition is "number of protons minus number of
electrons".  :func:`migrate_entity_charge` moves the value across and records
that it did.

All three are idempotent, so it is safe to run them again on their own output --
which the export does, because the merge writes flows into SQLite by a path that
does not go through the transform engine.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from brightway_flows.chem import collapse_duplicate_smiles
from brightway_flows.domain.common import Provenance
from brightway_flows.domain.inchikey import without_redundant_flat_keys
from brightway_flows.domain.vocabulary import (
    CHEMROF_ELEMENTAL_CHARGE,
    CHEMROF_FORMAL_CHARGE,
    CHEMROF_INCHI2D_KEY_STRING,
    CHEMROF_ISOMERIC_SMILES_STRING,
    CHEMROF_SMILES_STRING,
    PROV_HAD_PRIMARY_SOURCE_CURIE,
    PROV_WAS_DERIVED_FROM_CURIE,
    RDFS_LABEL_CURIE,
    Datatype,
    TERM_DATATYPE,
    term_for_iri,
)

#: Written into the provenance of a value this module moved or retyped.
MIGRATION_ACTIVITY = "property_values.charge_predicate_migration"

_ATTRIBUTED_TO = "brightway-flows"


def _coerce_scalar(value: Any, datatype: Datatype) -> tuple[Any, bool]:
    """Return (*coerced*, *changed*) for one scalar.

    A value that does not parse comes back unchanged.  ``bool`` is excluded
    deliberately: it is an ``int`` subclass in Python but not an XSD integer,
    and silently publishing ``true`` as ``1`` would be a lie about the source.
    """
    if isinstance(value, bool):
        return value, False
    if datatype is Datatype.INTEGER and isinstance(value, int):
        return value, False
    if datatype is Datatype.DOUBLE and isinstance(value, float):
        return value, False
    if isinstance(value, (int, float)):
        # An integer arriving for a double slot, or the reverse.
        return (float(value), True) if datatype is Datatype.DOUBLE else (int(value), True)
    if not isinstance(value, str):
        return value, False
    text = value.strip()
    if not text:
        return value, False
    try:
        if datatype is Datatype.DOUBLE:
            return float(text), True
        number = float(text)
    except ValueError:
        return value, False
    # "2.0" for an integer slot is the same integer; "2.5" is not, and keeping
    # it as a string is more honest than rounding a charge.
    if number.is_integer():
        return int(number), True
    return value, False


def coerce_property_datatypes(properties: Any) -> tuple[dict[str, Any], Counter]:
    """Retype the values of every numeric semantic property in *properties*.

    Returns the properties (a new dict when anything changed, the original
    otherwise) and a counter of ``coerced`` / ``unparseable`` values.
    """
    counts: Counter = Counter()
    if not isinstance(properties, dict):
        return {}, counts
    out = dict(properties)
    for key, entry in properties.items():
        term = term_for_iri(str(key))
        datatype = TERM_DATATYPE.get(term) if term is not None else None
        if datatype is None or not isinstance(entry, dict):
            continue
        raw = entry.get("@value")
        values = raw if isinstance(raw, list) else [raw]
        coerced: list[Any] = []
        changed = False
        for value in values:
            new_value, was_changed = _coerce_scalar(value, datatype)
            coerced.append(new_value)
            if was_changed:
                changed = True
                counts["coerced"] += 1
            elif isinstance(value, str) and value.strip():
                counts["unparseable"] += 1
        if not changed:
            continue
        updated = dict(entry)
        updated["@value"] = coerced if isinstance(raw, list) else coerced[0]
        out[key] = updated
    return out, counts


def _merged_charge_provenance(entry: dict[str, Any]) -> dict[str, Any]:
    """Provenance for a charge value that has moved predicate.

    The original provenance is kept as the primary source, so the value's
    lineage back to PubChem or ChEBI survives the move; this module's own step
    is recorded as what derived it.
    """
    existing = entry.get("provenance")
    primary: list[str] = []
    if isinstance(existing, dict):
        source = existing.get(PROV_HAD_PRIMARY_SOURCE_CURIE)
        if isinstance(source, list):
            primary = [str(x) for x in source]
        elif isinstance(source, str):
            primary = [source]
        derived = existing.get(PROV_WAS_DERIVED_FROM_CURIE)
    else:
        derived = None
    return Provenance(
        was_generated_by=MIGRATION_ACTIVITY,
        was_attributed_to=_ATTRIBUTED_TO,
        had_primary_source=primary,
        was_derived_from=str(derived) if derived else CHEMROF_FORMAL_CHARGE,
    ).to_dict()


def migrate_entity_charge(properties: Any) -> tuple[dict[str, Any], bool]:
    """Move a whole-entity charge off ``formal_charge``.

    ``formal_charge`` is an ``AtomOccurrence`` property in ChemROF; the net
    charge of a chemical entity is ``elemental_charge``.  Returns the properties
    and whether anything moved.

    An entity that already carries ``elemental_charge`` keeps it: the
    element-and-ion enrichment in ``flow_layers`` writes that predicate directly
    from the periodic table and from the parsed ion label, and it is the better
    source.  The ``formal_charge`` entry is dropped in that case rather than
    left behind, so one entity never states its charge twice.
    """
    if not isinstance(properties, dict) or CHEMROF_FORMAL_CHARGE not in properties:
        return properties if isinstance(properties, dict) else {}, False
    out = dict(properties)
    entry = out.pop(CHEMROF_FORMAL_CHARGE)
    if CHEMROF_ELEMENTAL_CHARGE in out:
        return out, True
    if not isinstance(entry, dict):
        return out, True
    moved = dict(entry)
    moved[RDFS_LABEL_CURIE] = "elemental charge"
    moved["provenance"] = _merged_charge_provenance(entry)
    out[CHEMROF_ELEMENTAL_CHARGE] = moved
    return out, True


def _is_smiles_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def collapse_smiles_spellings(properties: Any) -> tuple[dict[str, Any], Counter]:
    """Reduce two spellings of one structure, in either SMILES slot, to one value.

    A record collects its structures from ChEBI, PubChem, OPSIN, RDKit and --
    for a flow object -- every flow the layering merged into it.  Each writes
    the molecule the way its own toolkit spells it, and a canonical SMILES is
    canonical only per toolkit: PubChem's OEChem writes camphor
    `CC1(C2CCC1(C(=O)C2)C)C` where RDKit writes `CC12CCC(CC1=O)C2(C)C`.  Nothing
    compared those as structures, so both were stored and the record read as a
    substance with two candidate structures when it had one (#22).

    The RDKit stages no longer add a spelling of a structure the record already
    carries, which is where most of these came from.  This is for the rest: two
    sources spelling it differently, and -- on a flow object -- the flattened
    form of a stereo string landing on a flat one a source supplied.

    Which spelling survives is `chem.collapse_duplicate_smiles`, along with what
    happens to a string RDKit will not parse.  Provenance is untouched: it is
    recorded per property rather than per value, so every source that attested
    to the structure is still named on the property the spellings collapsed
    into.
    """
    counts: Counter = Counter()
    if not isinstance(properties, dict):
        return {}, counts
    out = dict(properties)
    for iri in (CHEMROF_SMILES_STRING, CHEMROF_ISOMERIC_SMILES_STRING):
        entry = out.get(iri)
        if not isinstance(entry, dict):
            continue
        raw = entry.get("@value")
        values = raw if isinstance(raw, list) else [raw]
        # A slot holding anything but strings is not one to rewrite: whatever
        # put a non-string there meant something this does not understand, and
        # dropping it while collapsing duplicates would lose it silently.
        if len(values) < 2 or not all(_is_smiles_text(v) for v in values):
            continue
        survivors, dropped = collapse_duplicate_smiles(list(values))
        if not dropped:
            continue
        updated = dict(entry)
        updated["@value"] = survivors if isinstance(raw, list) else survivors[0]
        out[iri] = updated
        counts[f"{iri.rsplit('/', 1)[-1]}_duplicate_spellings_collapsed"] += dropped
    return out, counts


def drop_redundant_flat_inchikeys(properties: Any) -> tuple[dict[str, Any], Counter]:
    """Drop each stereochemistry-free key the record's own specific key covers.

    The stages that write this slot refuse the value at their own write, which
    is where the fix belongs: a flat key sitting in the record is read by
    everything downstream of the stage that added it, and #50's whole point is
    that a reader cannot tell it from a second candidate identity.  This is for
    the path that has no stage -- `merge.creations` writes flow objects into
    SQLite without going through the transform engine, so a record assembled
    there has had no writer to refuse anything.

    Which values survive, and why the grouping is per skeleton rather than per
    record, is `domain.inchikey.without_redundant_flat_keys`.  Provenance is
    untouched, for the reason `collapse_smiles_spellings` leaves it alone: it is
    recorded per property, so every source that attested to the structure is
    still named on the slot the flat key left.
    """
    counts: Counter = Counter()
    if not isinstance(properties, dict):
        return {}, counts
    entry = properties.get(CHEMROF_INCHI2D_KEY_STRING)
    if not isinstance(entry, dict):
        return dict(properties), counts
    raw = entry.get("@value")
    if not isinstance(raw, list) or len(raw) < 2:
        return dict(properties), counts
    # A slot holding anything but strings is not one to rewrite, the same guard
    # and the same reason as the SMILES collapse.
    if not all(isinstance(v, str) and v.strip() for v in raw):
        return dict(properties), counts
    kept = without_redundant_flat_keys(raw)
    if len(kept) == len(raw):
        return dict(properties), counts
    out = dict(properties)
    updated = dict(entry)
    updated["@value"] = kept
    out[CHEMROF_INCHI2D_KEY_STRING] = updated
    counts["inchikeys_redundant_flat_dropped"] += len(raw) - len(kept)
    return out, counts


def redundant_flat_inchikey_slots(properties: Any) -> int:
    """Whether the key slot still states one substance's structure twice.

    The acceptance measure for #50, read off the record after every writer has
    had its turn -- 419 flow objects and 5,416 elementary flows on the
    2026-08-12 build, and a run that reports anything other than zero has a
    writer this does not know about.
    """
    if not isinstance(properties, dict):
        return 0
    _, counts = drop_redundant_flat_inchikeys(properties)
    return 1 if counts else 0


def redundant_smiles_slots(properties: Any) -> int:
    """How many SMILES slots still carry two spellings of one structure.

    The acceptance measure for #22, read off the record after everything has
    written to it rather than asserted by the step that collapses -- so a run
    reports whether what it publishes is free of the redundancy, and says so
    again if some later step reintroduces it.
    """
    if not isinstance(properties, dict):
        return 0
    redundant = 0
    for iri in (CHEMROF_SMILES_STRING, CHEMROF_ISOMERIC_SMILES_STRING):
        entry = properties.get(iri)
        if not isinstance(entry, dict):
            continue
        raw = entry.get("@value")
        values = raw if isinstance(raw, list) else [raw]
        # The same guard the collapse applies, so this measures what that
        # promises rather than reporting a slot it has decided not to touch.
        if len(values) < 2 or not all(_is_smiles_text(v) for v in values):
            continue
        _, dropped = collapse_duplicate_smiles(list(values))
        if dropped:
            redundant += 1
    return redundant


def normalise_semantic_properties(properties: Any) -> tuple[dict[str, Any], Counter]:
    """Apply the corrections, in the order they depend on each other.

    The charge moves first so the datatype pass sees it under the predicate it
    will be published as, and types it from that predicate's declared range.
    The two structure corrections are independent of both and run last.
    """
    moved_properties, moved = migrate_entity_charge(properties)
    out, counts = coerce_property_datatypes(moved_properties)
    if moved:
        counts["charge_migrated"] += 1
    out, collapse_counts = collapse_smiles_spellings(out)
    counts.update(collapse_counts)
    out, flat_key_counts = drop_redundant_flat_inchikeys(out)
    counts.update(flat_key_counts)
    return out, counts


def normalise_records(records: Any) -> Counter:
    """Normalise ``properties`` in place across any records that carry it.

    Records are read and written by attribute -- see ``AGENTS.md`` -- so this
    takes the records themselves rather than their dicts, and is what the
    transform engine calls for both ``Flow`` and ``FlowObject``.
    """
    counts: Counter = Counter()
    for record in records:
        properties = record.properties
        if not isinstance(properties, dict) or not properties:
            continue
        updated, record_counts = normalise_semantic_properties(properties)
        record.properties = updated
        counts.update(record_counts)
    return counts
