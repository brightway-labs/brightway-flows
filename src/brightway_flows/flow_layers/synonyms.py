"""A name a source list published stays a name the list answers to.

EF 3.1 calls a refrigerant `HFE-143a`.  It also publishes the same substance,
in the same eleven compartments, as `Methyl trifluoromethyl ether`.  Once the
layering works out that the two are one substance -- they share CAS 421-14-7 --
one of those names becomes the substance's name and, until this pass existed,
the other went nowhere.  Somebody holding an inventory written against EF 3.1
searched the published list for `HFE-143a` and found nothing (#113).

Nothing was lost from the *mapping*: `elementary_flow_sources` still records
which source flow reached which substance, and under what name.  What was lost
is the ability to find the substance by a name a vendor actually publishes.

**The retention already existed one branch away.**  `flow-object-overrides.json`
says it in as many words -- where a merge group states its object's label,
"every member name that is not the stated label becomes an alternative label on
the object, so a source's own spelling stays searchable".  That branch runs only
for a grouping somebody wrote down by hand.  Substances joined because they
share a registry number -- which is most of them, and needs no curator -- state
no label, so the demoted name had nowhere to go, and which name won was decided
by length: the longest member name becomes the substance's name.

## One name, one substance

The property this pass establishes is that **a published name names exactly one
substance**, and it has to hold in both directions:

* a name this pass carries must not already name another substance, and must not
  be claimed by two substances at once;
* a name already published as a synonym must not name two substances either.

The second half is not this pass's doing and is fixed here anyway, because the
property is worth having whole rather than in the part this pass touches.  On
the 2026-08-18 build 888 synonyms named more than one substance and 49 were a
synonym of one and the name of another, so a reader searching for `camphor` got
two answers and had no way to tell which was meant.

The comparison is `_canonical_name` -- letters and digits, folded to lower case
-- and not the looser `canonical_label_value` the transform's own guard uses.
`Arsenic Ion` and `Arsenic, Ion` are one name for this purpose and the looser
key reads them as two, which is exactly how one of them survived on `Arsenic`
while the other survived on `Arsenic(5+)`.

## Which names are worth keeping

Four tests, and the first is the one that does the correctness work.

**A name two substances claim is not carried.**  `Arsenic Ion` reaches both
`Arsenic` and `Arsenic(5+)`; `Methane` reaches both `Methane (fossil)` and
`Methane (land use change)`.  In every one of those cases the pass cannot know
which substance the vendor meant, and a synonym nobody can resolve is worse than
no synonym.  This is the uniqueness rule doing the filtering, not a heuristic.

**A name that describes a place is not carried.**  `Hafnium, In Ground` is not
another name for hafnium; it is hafnium in a particular compartment, which the
flow's context already says.  The vocabulary is curated, in
`source-name-places.json`, because every entry is a reading of what a vendor
meant by a word.

**A name stating a concentration is not carried.**  `Aluminium, 24% In Bauxite,
11% In Crude Ore, In Ground` states an ore grade, which is a property of the
deposit rather than a name of the metal.  A per-cent sign in a comma-separated
segment is the test, and it is here rather than in the curated file because it
is not a membership question -- no list of grades could be written down.

**A name that names a family of chemicals is not carried.**  EF 3.1's
`polyhaloalkene` is the refrigerant HFO-1234yf -- the vendor ships the same
substance under both spellings -- and the class word is a name for every
polyhalogenated alkene at once, so it is a name for none of them (#116).
Curated in the same file as the places, and for the same reason: every entry
is a reading of what a vendor meant by a word.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import orjson
import structlog

from brightway_flows.domain.elementary_flow import ElementaryFlow
from brightway_flows.domain.flow_object import FlowObject
from brightway_flows.domain.particulate_size import (
    class_by_flow_object,
    particulate_class_by_source_flow,
)
from brightway_flows.domain.vocabulary import PROV_WAS_GENERATED_BY_CURIE
from brightway_flows.filesystem import PACKAGE_DATA_DIR
from brightway_flows.flow_layers.labels import _canonical_name, _label_entry

logger = structlog.get_logger(__name__)

PLACES_FILEPATH = PACKAGE_DATA_DIR / "source-name-places.json"

#: What this pass calls itself in the provenance of a label it writes.
PASS_NAME = "carry_member_names"

#: The stage the merge files this pass's counters under, beside the two other
#: whole-list questions it asks after its writes.
MERGE_SYNONYM_STAGE = "merge_member_name_synonyms"


@dataclass(frozen=True, slots=True)
class PlaceVocabulary:
    """The membership tests `source-name-places.json` states.

    A record rather than the raw payload, for the reason `domain/rulings.py`
    gives: a misspelled key in a bag answers `None` and the ruling silently
    stops applying.

    `chemical_classes` joined the two place tests for the same reason they
    exist: a source name that names a *family* of chemicals is not a name of
    the member the flow turned out to be, any more than `Hafnium, In Ground`
    is a name of hafnium.  EF 3.1's `polyhaloalkene` is HFO-1234yf, CAS
    754-12-1 -- EF ships the substance under both spellings -- and once the
    flow is renamed for the member (#116), carrying the class word back as a
    synonym would assert that a search for it should land on this one member
    rather than on any other polyhalogenated alkene in the list.
    """

    land_flow_prefixes: frozenset[str]
    places: frozenset[str]
    chemical_classes: frozenset[str]


def _values(payload: dict[str, Any], key: str, path: Path) -> frozenset[str]:
    block = payload.get(key)
    if not isinstance(block, dict):
        raise ValueError(f"{path}: {key!r} is missing or is not an object")
    values = block.get("values")
    if not isinstance(values, list) or not values:
        raise ValueError(f"{path}: {key!r} states no values")
    out = set()
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{path}: {key!r} holds a value that is not a name")
        out.add(" ".join(value.strip().lower().split()))
    return frozenset(out)


def load_place_vocabulary(path: Path | None = None) -> PlaceVocabulary:
    """The curated vocabulary, or a raise if the file cannot be read.

    Path-injectable and therefore not cached, which is the rule in
    `domain/rulings.py`; :func:`place_vocabulary` is the cached no-argument
    form the pass actually calls.
    """
    resolved = PLACES_FILEPATH if path is None else path
    payload = orjson.loads(resolved.read_bytes())
    return PlaceVocabulary(
        land_flow_prefixes=_values(payload, "land_flow_prefixes", resolved),
        places=_values(payload, "places", resolved),
        chemical_classes=_values(payload, "chemical_classes", resolved),
    )


@lru_cache(maxsize=1)
def place_vocabulary() -> PlaceVocabulary:
    return load_place_vocabulary()


def _segments(name: str) -> list[str]:
    return [" ".join(part.strip().lower().split()) for part in name.split(",")]


def names_a_place(name: str, vocabulary: PlaceVocabulary | None = None) -> bool:
    """Whether *name* says where the flow is rather than what the substance is.

    Public because it is the whole of the second and third tests, and a test
    that reads the curated file should be able to ask it directly rather than
    through a pass that needs two layers of records to answer.
    """
    vocab = place_vocabulary() if vocabulary is None else vocabulary
    parts = _segments(name)
    if not parts:
        return False
    if parts[0] in vocab.land_flow_prefixes:
        return True
    for part in parts[1:]:
        if "%" in part:
            return True
        if part.startswith("in ") and part[3:].strip() in vocab.places:
            return True
    return False


def names_a_class(name: str, vocabulary: PlaceVocabulary | None = None) -> bool:
    """Whether *name* names a family of chemicals rather than this member.

    The whole name, folded the way the vocabulary's values are, against the
    curated list -- not a substring test, because `polyhaloalkene resin` would
    be some vendor's name for a particular product and this test has no
    business reading it.  Public for the reason `names_a_place` is.
    """
    vocab = place_vocabulary() if vocabulary is None else vocabulary
    return " ".join(name.strip().lower().split()) in vocab.chemical_classes


@lru_cache(maxsize=1)
def _size_windows_by_name() -> dict[str, frozenset[str]]:
    """Every curated source name, folded, to the size windows it names.

    Built from `particulate-flow-classes.json`, so what counts as "the name of a
    2.5-10 um row" is the same curated statement the merge matches on.  A set
    rather than one id because a spelling can be shared: ecoinvent 3.8 and BAFU
    both write `Particulates, > 2.5 um, and < 10um`, and both mean the same
    window -- but nothing here needs them to.
    """
    windows: dict[str, set[str]] = defaultdict(set)
    for row in particulate_class_by_source_flow().values():
        key = _canonical_name(row.source_name)
        if key:
            windows[key].add(row.size_class.id)
    return {key: frozenset(value) for key, value in windows.items()}


def names_another_size_window(name: str, flow_object_id: str) -> bool:
    """Whether *name* is a particle size band this substance is not.

    The rule #153 needed and nothing could express before the window was a
    field.  `Particles (PM10)` published two alternative labels on the build of
    25 August 2026 -- `Particulate Matter, > 2.5 um and < 10um` and
    `Particulates, > 2.5 um, and < 10um` -- and both name the *coarse fraction*.
    They arrived honestly: #37 deliberately maps ecoinvent's 2.5-10 um rows
    onto PM10 to reproduce the scores existing tools report, so those rows are
    members of PM10's merge group, and this pass keeps a member's name.

    The trade is a decision about ecoinvent's rows.  Publishing the coarse
    fraction's name as a name for PM10 turns it into a decision about every
    later list that spells its coarse fraction the ecoinvent way -- which is how
    four BAFU rows took it, on a label, with nothing recorded anywhere.

    So the name is not carried.  The mapping is untouched; what stops is the
    published claim that PM10 answers to the coarse band's name.  A substance
    that is not a size window is not asked about, and neither is a name no
    curated row uses.
    """
    windows = _size_windows_by_name().get(_canonical_name(name))
    if not windows:
        return False
    here = class_by_flow_object().get(flow_object_id)
    if here is None:
        return False
    return here.id not in windows


def _label_values(rows: Any) -> list[str]:
    out: list[str] = []
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict):
                value = row.get("@value")
            else:
                value = row
            if isinstance(value, str) and value.strip():
                out.append(value.strip())
    return out


def carry_member_names(
    flow_objects: list[FlowObject],
    elementary_flows: list[ElementaryFlow],
    *,
    vocabulary: PlaceVocabulary | None = None,
    changed: set[str] | None = None,
) -> Counter[str]:
    """Keep every member name that names this substance and no other.

    Runs after the layering because it is a question about the whole set: which
    substance a name belongs to cannot be answered while the substances are
    still being built, and neither can whether two of them claim it.  For the
    same reason the merge runs it over its whole working set rather than over
    the batch it minted: a name the merge gives a new substance may be one an
    older substance already answers to.

    *changed* collects the identifier of every substance whose synonyms moved,
    which is what the merge needs to know: it writes the objects it minted and
    would otherwise leave a withdrawal on a pre-existing one in memory only.
    """
    vocab = place_vocabulary() if vocabulary is None else vocabulary
    # Every key the pass can report, seeded at zero.  A `Counter` omits a key it
    # never incremented, and `assess` reads a missing measure as a subject that
    # is not in this build rather than as a zero -- so the invariant below would
    # report `unresolved` on exactly the builds where it holds.
    stats: Counter[str] = Counter({
        key: 0 for key in (
            "names_carried",
            "names_shared_by_two_substances",
            "preferred_labels_demoted",
            "substances_with_a_second_preferred_label",
            "names_the_list_would_not_answer_to",
            "rejected_already_names_a_substance",
            "rejected_names_a_class",
            "rejected_names_a_place",
            "rejected_names_another_size_window",
            "rejected_two_substances_claim_it",
            "substances_given_a_name",
            "substances_with_a_synonym_withdrawn",
            "synonyms_naming_two_substances",
            "synonyms_withdrawn",
        )
    })
    stats["substances"] = len(flow_objects)

    object_by_id = {obj.flow_object_id: obj for obj in flow_objects}

    # First, because everything below reads the labels it moves.  A substance
    # has one preferred label, and where two member names were the same length
    # the layering kept both as preferred-label rows rather than choosing --
    # `HFE-569sf2` and `n-HFE-7200`, `HG-02` and the IUPAC name beside it, 19
    # substances in all.  The second row is published in `pref_label_json` and
    # nowhere a reader looks: `pref_label_value` is the first row and so is the
    # `flow_objects_fts` column a name search reads, so the name is in the file
    # and cannot be found.  Demoted rather than deleted, and the first row is
    # kept, which is the row `coerce_pref_label` already returns -- so the
    # published name of every substance is unchanged and only the rows that
    # were invisible move.
    for obj in flow_objects:
        rows = list(obj.prefLabel or [])
        if len(rows) < 2:
            continue
        obj.prefLabel = rows[:1]
        obj.altLabel = list(obj.altLabel or []) + rows[1:]
        stats["preferred_labels_demoted"] += len(rows) - 1
        stats["substances_with_a_second_preferred_label"] += 1
        if changed is not None:
            changed.add(obj.flow_object_id)

    # Who claims what, before anything is written.  A preferred label and a
    # synonym are one kind of claim here: the question is which substance a
    # reader searching for the string would be taken to.
    claimed_by: dict[str, set[str]] = defaultdict(set)
    named_by: dict[str, set[str]] = defaultdict(set)
    for obj in flow_objects:
        for value in _label_values(obj.prefLabel):
            key = _canonical_name(value)
            if key:
                claimed_by[key].add(obj.flow_object_id)
                named_by[key].add(obj.flow_object_id)
        for value in _label_values(obj.altLabel):
            key = _canonical_name(value)
            if key:
                claimed_by[key].add(obj.flow_object_id)

    # Half one: a synonym that names more than one substance, or that is
    # another substance's name, stops being published.  A preferred label is
    # never removed -- a substance has to be called something -- so where the
    # two collide it is the synonym that goes.
    removed_objects = 0
    for obj in flow_objects:
        keep, dropped = [], []
        for row in obj.altLabel or []:
            values = _label_values([row])
            key = _canonical_name(values[0]) if values else ""
            if not key or _promised_by_the_scheme(row):
                # A window's promised spelling is never withdrawn here.  The
                # claim key strips punctuation, so `Particulates, < 10 um` and
                # `Particulates, > 10 um` are one key claimed by two windows,
                # and on the first build of stage 1 (#196) this loop took
                # both off.  The scheme checks those spellings exact, and the
                # promise pass below writes one only where no other substance
                # publishes that exact text.
                keep.append(row)
                continue
            owners = claimed_by.get(key, set())
            others_naming = named_by.get(key, set()) - {obj.flow_object_id}
            if len(owners) > 1 or others_naming:
                dropped.append(values[0])
                continue
            keep.append(row)
        if dropped:
            removed_objects += 1
            stats["synonyms_withdrawn"] += len(dropped)
            obj.altLabel = keep
            if changed is not None:
                changed.add(obj.flow_object_id)
    stats["substances_with_a_synonym_withdrawn"] = removed_objects

    # Half two: the member names that lost the contest for the substance's own
    # name, offered back as synonyms.
    candidates: dict[str, set[str]] = defaultdict(set)
    for flow in elementary_flows:
        object_id = flow.flow_object_id or ""
        if not object_id or object_id not in object_by_id:
            continue
        for ref in flow.source_refs or []:
            if not isinstance(ref, dict):
                continue
            name = str(ref.get("source_flow_name") or "").strip()
            if name:
                candidates[object_id].add(name)

    # Names the substance already publishes are not candidates at all, and are
    # dropped before the counting so that the figures below are about names the
    # list would otherwise not answer to.
    proposed: dict[str, set[str]] = defaultdict(set)
    for object_id, names in candidates.items():
        obj = object_by_id[object_id]
        known = {
            _canonical_name(value)
            for value in _label_values(obj.prefLabel) + _label_values(obj.altLabel)
        }
        for name in names:
            key = _canonical_name(name)
            if not key or key in known:
                continue
            if names_another_size_window(name, object_id):
                # Rejected *here*, before `wanted_by` below counts claimants,
                # and not in the carrying loop with the other three tests.
                #
                # The difference is what the test is about.  `names_a_place` and
                # `names_a_class` disqualify a name for every substance alike --
                # `Hafnium, In Ground` is a place whoever wants it -- so where
                # they run cannot change who else may have the name.  This one is
                # about the *pair*: `Particulates, > 2.5 um, and < 10um` is wrong
                # for `Particles (PM10)` and right for `Particles (PM2.5 -
                # PM10)`, and both want it, because #37 maps ecoinvent's coarse
                # rows onto PM10 while BAFU's reach the coarse flow.
                #
                # Left in the carrying loop it would reject the name from PM10
                # and still leave PM10 counted as a claimant, so the two-claimant
                # rule below would then take it off the coarse flow as well --
                # and the flow whose name it actually is would be the one that
                # lost it.
                stats["rejected_names_another_size_window"] += 1
                continue
            proposed[object_id].add(name)

    stats["names_the_list_would_not_answer_to"] = len(
        {_canonical_name(n) for names in proposed.values() for n in names}
    )

    wanted_by: dict[str, set[str]] = defaultdict(set)
    for object_id, names in proposed.items():
        for name in names:
            wanted_by[_canonical_name(name)].add(object_id)

    carried_objects = 0
    for object_id, names in sorted(proposed.items()):
        obj = object_by_id[object_id]
        rows = []
        for name in sorted(names):
            key = _canonical_name(name)
            if names_a_place(name, vocab):
                stats["rejected_names_a_place"] += 1
                continue
            if names_a_class(name, vocab):
                stats["rejected_names_a_class"] += 1
                continue
            if len(wanted_by[key]) > 1:
                stats["rejected_two_substances_claim_it"] += 1
                continue
            if claimed_by.get(key):
                stats["rejected_already_names_a_substance"] += 1
                continue
            rows.append(
                _label_entry(
                    value=name,
                    language="en",
                    resolver_name=PASS_NAME,
                    seed_source="",
                    was_derived_from="source_flow_name",
                )
            )
            # Claimed as it is written, so two substances cannot both take it
            # and a later candidate sees it gone.
            claimed_by[key].add(object_id)
            stats["names_carried"] += 1
        if rows:
            carried_objects += 1
            obj.altLabel = list(obj.altLabel or []) + rows
            if changed is not None:
                changed.add(object_id)
    stats["substances_given_a_name"] = carried_objects

    stats["size_class_labels_promised"] = promise_size_class_labels(
        flow_objects, claimed_by=claimed_by, changed=changed
    )
    stats.update(_names_answering_twice(flow_objects))
    logger.info("carried_member_names", **dict(stats))
    return stats


#: What a window's promised alternative labels say wrote them, and from where.
SIZE_CLASS_PASS_NAME = "particulate_size_class"
SIZE_CLASS_LABEL_SOURCE = "particulate-size-classes.json"


def promise_size_class_labels(
    flow_objects: list[FlowObject],
    *,
    claimed_by: dict[str, set[str]] | None = None,
    changed: set[str] | None = None,
) -> int:
    """Every particle size window publishes the `Particulates` spellings the
    scheme promises for it, whatever else happened to its labels.

    A pass over the whole set rather than a line in the layering, because the
    layering is not the only thing that builds a window's object: the merge
    rebuilds an object when it mints a new flow on it, and the flow it mints
    carries no source row the size table can be looked up by, so the rebuilt
    object knows no window.  On the first build of stage 1 that left PM10 and
    the above-ten fraction -- the two windows AGRIBALYSE minted an aquifer flow
    on -- with every promised spelling missing while the other five had
    theirs.  The object's identifier is the window's, by construction, so the
    promise is kept here by identifier and cannot be lost that way (#196).

    A spelling already published on the object, under any provenance, is left
    as it is.  A spelling another substance already publishes, *as that exact
    text*, is not written and is logged instead.  Exact text rather than the
    claim key the rest of this module uses, because that key strips
    punctuation and reads `Particulates, < 10 um` and `Particulates, > 10 um`
    as one name -- which is how the first build of stage 1 lost both.  The
    scheme guarantees the exact spellings are distinct (`check_labels`), so
    exact is the right question here.  *claimed_by* is told what was written.
    Returns how many labels were written.
    """
    windows = class_by_flow_object()
    exact_owner: dict[str, set[str]] = defaultdict(set)
    for obj in flow_objects:
        for value in _label_values(obj.prefLabel) + _label_values(obj.altLabel):
            exact_owner[_exact(value)].add(obj.flow_object_id)
    written = 0
    for obj in flow_objects:
        window = windows.get(obj.flow_object_id)
        if window is None:
            continue
        rows = []
        for spelling in window.alt_labels:
            exact = _exact(spelling)
            if not exact or obj.flow_object_id in exact_owner.get(exact, set()):
                continue
            others = exact_owner.get(exact, set())
            if others:
                logger.warning(
                    "size_class_label_published_elsewhere",
                    window=window.id,
                    label=spelling,
                    published_by=sorted(others),
                )
                continue
            rows.append(
                _label_entry(
                    value=spelling,
                    language="en",
                    resolver_name=SIZE_CLASS_PASS_NAME,
                    seed_source=SIZE_CLASS_LABEL_SOURCE,
                    was_derived_from="particulate-size-classes.json alt_labels",
                )
            )
            exact_owner[exact].add(obj.flow_object_id)
            if claimed_by is not None:
                claimed_by.setdefault(_canonical_name(spelling), set()).add(obj.flow_object_id)
        if rows:
            obj.altLabel = list(obj.altLabel or []) + rows
            written += len(rows)
            if changed is not None:
                changed.add(obj.flow_object_id)
    return written


def _exact(value: str) -> str:
    """A label's text, case- and whitespace-folded and nothing else."""
    return " ".join(value.strip().lower().split())


def _promised_by_the_scheme(row: Any) -> bool:
    """Whether this label row is a window's promised spelling."""
    if not isinstance(row, dict):
        return False
    provenance = row.get("provenance")
    entries = provenance if isinstance(provenance, list) else [provenance]
    return any(
        isinstance(entry, dict) and entry.get(PROV_WAS_GENERATED_BY_CURIE) == SIZE_CLASS_PASS_NAME
        for entry in entries
    )


def _names_answering_twice(flow_objects: list[FlowObject]) -> Counter[str]:
    """How many published names still answer for more than one substance.

    Read off the records after the pass has finished rather than tracked while
    it runs, so the numbers describe what will be published.

    Two numbers, because the pass can only answer for one of them.
    ``synonyms_naming_two_substances`` counts a name where at least one of the
    substances holds it as a *synonym*, which is the whole of what this pass
    withdraws, and it has to be zero.  ``names_shared_by_two_substances``
    counts the rest: two substances whose *preferred* labels canonicalise to one
    name.  That is wider than an identical string, because the comparison is
    `_canonical_name` -- `Particles (> PM10)` and `Particles (PM10)` differ only
    by a `>` and a space, neither of which is a letter or a digit, and they are
    two different size windows.  A substance has to be called something, so
    neither name can be withdrawn and this pass leaves both alone -- 18 of them
    on the build of 29 August 2026, among them `Fenoxycarb` and `Metaldehyde`,
    each published twice under two registry numbers.  Reporting them apart is
    what stops the pass claiming to have fixed a defect it cannot see the answer
    to.

    This comment named `Camphor` and `Chlordane` until #167, off the 2026-08-18
    build.  Measured again on 29 August, neither is: camphor is in the population
    but under the systematic spellings `Bornan-2-one` and `(+)-bornan-2-one`, and
    chlordane is not in it at all -- nor was it on the 28 August build, before
    #167 renamed anything.  Why they left is not recorded here, and the count
    stayed in the same range throughout, which is how two examples went stale
    without any number moving.
    """
    named_by: dict[str, set[str]] = defaultdict(set)
    synonym_of: dict[str, set[str]] = defaultdict(set)
    for obj in flow_objects:
        for value in _label_values(obj.prefLabel):
            key = _canonical_name(value)
            if key:
                named_by[key].add(obj.flow_object_id)
        for value in _label_values(obj.altLabel):
            key = _canonical_name(value)
            if key:
                synonym_of[key].add(obj.flow_object_id)

    stats: Counter[str] = Counter()
    for key in set(named_by) | set(synonym_of):
        owners = named_by[key] | synonym_of[key]
        if len(owners) < 2:
            continue
        if synonym_of[key]:
            stats["synonyms_naming_two_substances"] += 1
        else:
            stats["names_shared_by_two_substances"] += 1
    return stats


__all__ = [
    "MERGE_SYNONYM_STAGE",
    "PASS_NAME",
    "PLACES_FILEPATH",
    "PlaceVocabulary",
    "carry_member_names",
    "load_place_vocabulary",
    "names_a_class",
    "names_a_place",
    "place_vocabulary",
]
