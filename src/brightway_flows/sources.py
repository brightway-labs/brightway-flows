"""What an input flow list is, and which ones this build knows about.

The merge was written for a single input list and keyed everything on an
ecoinvent version string, so ``version`` came to mean two things at once: *which
list* and *which release of it*.  That conflation is why nothing else could be
merged -- seven separate inputs were derived from that one string, and a second
list had no way to name itself.

The identity of an input list is ``(list_name, list_version)``.  That pair is
not new: it is what the published ``source_refs`` records carry and what the
``elementary_flow_sources`` table stores.  The merge was the only layer not
using it.

A :class:`SourceList` is that identity together with the location of every input
keyed to it.  The registry of them **is data**: one manifest per list in
``data/sources/``, read here (#12).  It used to be a comprehension over
``ECOINVENT_VERSIONS``, which made the architecture doc's claim -- *adding a
list is a registry entry* -- true about the shape of this dataclass and false
about the code: adding BAFU meant editing Python.

This module is not under ``merge/`` because a source list is not a merge
concept.  The base list is a source list too (#14), and it is the *transform's*
input; ``merge/sources.py`` importing ``pipeline.loading`` while
``pipeline.loading`` needed the base list would have been a cycle.

Two roles, and a list has exactly one:

``base``
    The fixed list every other list is merged into.  It is the transform's
    input, never a ``--source``, and its ``source_label`` is published in
    ``flow.source``.
``source``
    A list the merge consumes.  These are what ``--source`` names.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Protocol

import orjson
import randonneur_data as rd
import structlog

from brightway_flows.domain.flow import Flow
from brightway_flows.domain.vocabulary import source_scheme
from brightway_flows.filesystem import DATA_DIR
from brightway_flows.additional_flows import (
    ExcludedSourceFlow,
    apply_additional_flows,
    load_excluded_source_flows,
)
from brightway_flows.manual_fixes import apply_manual_fixes
from brightway_flows.match_overrides import apply_match_overrides
from brightway_flows.simapro_names import (
    canonical_geography_code,
    split_geography_suffix,
    unit_suffix_rewrites,
)
from brightway_flows.filesystem import (
    PACKAGE_DATA_DIR,
    SIMAPRO_LINEAGE_FIXES_FILEPATH,
    SOURCE_MANIFEST_DIR,
)

logger = structlog.get_logger(__name__)

# `PACKAGE_DATA_DIR` and `SOURCE_MANIFEST_DIR` were declared here, and exactly
# one module in the tree imported the first of them -- the other 23 spelled the
# path themselves, because reading a bundled data file should not mean importing
# the source-list registry.  Both live in `filesystem` now and are re-exported
# here for the tests that say `sources.PACKAGE_DATA_DIR` (#92).  No module in
# `src/` does: `flow_layers.roles` was the last, until #306.
__all__ = ["PACKAGE_DATA_DIR", "SOURCE_MANIFEST_DIR"]

BASE_ROLE = "base"
SOURCE_ROLE = "source"
_ROLES = (BASE_ROLE, SOURCE_ROLE)

#: Curated inputs a manifest may name, and where each is looked up.  ``flows``
#: is deliberately absent: it is the one *derived* input, it lives in the data
#: directory, and it is produced by a fetch rather than authored.
_CURATED_INPUTS = (
    "manual_fixes", "manual_additions", "additional_flows", "match_overrides",
)

#: Where a list's mappings back to the consensus flows come from.  The manifest
#: vocabulary; :mod:`brightway_flows.pipeline.concept_associations` holds
#: one implementation per name, and `tests/test_concept_associations.py` pins
#: the two sets equal so a name can only be added in both places.
#:
#: ``source_refs``
#:     From the flow's own ``source_refs``: this list was merged into the
#:     consensus flows, so each one records which of its flows it came from.
#: ``glad``
#:     From the GLAD ILCD-to-SimaPro correspondence table, which pairs EF 3.1
#:     flows with SimaPro 10.2 ones.  For a list whose flows *originate* in
#:     SimaPro: the consensus list never merged SimaPro directly, so there are
#:     no ``source_refs`` to read and the pairing has to come from the table.
PAIR_SOURCES = ("source_refs", "glad")


class SourceAdapter(Protocol):
    """Turns a vendor's distribution into the record shape, on disk.

    `docs/operating/sources.md` step 1 has always said "write an adapter"; until
    #15 there was nowhere for one to live and no protocol for it to satisfy, so
    each list needed a module, a dedicated CLI command and a `filesystem.py` path
    function.  A manifest now names one by dotted path and `fetch-source <key>`
    runs it, whichever list it is.

    The adapter takes the :class:`SourceList` rather than nothing.  Five
    ecoinvent manifests share one adapter and differ only in `list_version`, so
    a no-argument `fetch()` would need five near-identical functions -- and the
    adapter needs `flows_path` regardless, because where a list's flows go is
    the manifest's answer and not the adapter's to invent.

    Returns the path it wrote, which must be ``source.flows_path``: a fetch that
    writes anywhere else has produced a file nothing will open.
    """

    def __call__(self, source: SourceList, *, force: bool = False) -> Path: ...


@dataclass(frozen=True)
class ConceptAssociationSpec:
    """How one list's mappings back to the consensus flows are built.

    A concept-association builder used to be a class per list, which meant a
    third list's mappings cost a fourth class rather than a manifest key (#244).
    The classes differed in exactly what is declared here: which scheme's IRIs
    to mint, where the pairs come from, and what to cite as the primary source.
    """

    #: Slug of the :class:`~brightway_flows.domain.vocabulary.SourceScheme`
    #: the mappings point at.  Not necessarily this list's own scheme: a list
    #: whose flows originate in SimaPro publishes mappings to *SimaPro*.
    scheme: str
    #: One of :data:`PAIR_SOURCES`.
    pairs_from: str
    #: `prov:hadPrimarySource` for the mappings: the artifact they were read
    #: from, which for ``glad`` is the correspondence table rather than a list.
    primary_source: str = ""

    @classmethod
    def from_manifest(cls, payload: Any, *, path: Path) -> ConceptAssociationSpec:
        """Parse the optional ``concept_associations`` block of a manifest."""
        if not isinstance(payload, dict):
            raise ValueError(
                f"{path.name}: concept_associations must be an object or absent."
            )
        for required in ("scheme", "pairs_from"):
            value = payload.get(required)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(
                    f"{path.name}: concept_associations.{required} must be a "
                    "non-empty string."
                )
        pairs_from = payload["pairs_from"].strip()
        if pairs_from not in PAIR_SOURCES:
            allowed = ", ".join(PAIR_SOURCES)
            raise ValueError(
                f"{path.name}: concept_associations.pairs_from must be one of "
                f"{allowed}, not {pairs_from!r}."
            )
        # Raises if the slug is not registered.  Checked here so a typo fails
        # when the manifest is read, not silently after a build: an association
        # whose source belongs to no scheme is dropped by the export.
        source_scheme(payload["scheme"].strip())
        return cls(
            scheme=payload["scheme"].strip(),
            pairs_from=pairs_from,
            primary_source=str(payload.get("primary_source") or "").strip(),
        )


@dataclass(frozen=True)
class LciaMethodSpec:
    """One LCIA method a source list publishes, and the sibling it is checked
    against.

    ecoinvent ships every method twice, once whole and once with the long-term
    compartments removed and ``no LT`` appended to every name.  The second states
    no number the first does not -- measured over all 54,605 rows of the two EF
    3.1 methods: 0 rows differ in value, 0 rows are ``no LT``-only, and 225 rows
    are dropped, 201 in ``air / low population density, long-term`` and 24 in
    ``water / ground-, long-term``.

    So the ``no LT`` method is read and not published (``plans/lcia-factors.md``
    §2.4), and naming it here is what keeps that a checked fact rather than one
    measured once in 3.12: a release where it is more than a subtraction fails
    the fetch instead of being dropped unread.
    """

    #: The method as the workbook's ``Method`` column spells it: ``EF v3.1``.
    name: str
    #: The sibling that must be *name* minus its long-term rows, or ``None`` for
    #: a method that ships without one.
    no_long_term: str | None = None

    @classmethod
    def from_manifest(cls, payload: Any, *, path: Path) -> LciaMethodSpec:
        if not isinstance(payload, dict):
            raise ValueError(f"{path.name}: each lcia.methods entry must be an object.")
        name = payload.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"{path.name}: lcia.methods[].name must be a string.")
        sibling = payload.get("no_long_term")
        if sibling is not None and (
            not isinstance(sibling, str) or not sibling.strip()
        ):
            raise ValueError(
                f"{path.name}: lcia.methods[].no_long_term must be a method name "
                "or null."
            )
        return cls(
            name=name.strip(),
            no_long_term=sibling.strip() if isinstance(sibling, str) else None,
        )


@dataclass(frozen=True)
class LciaSpec:
    """Where a source list's characterisation factors come from.

    A second thing to fetch for a list, on the same terms as its flows: an
    adapter named by dotted path, and a path in the data directory for what it
    writes.  Separate from ``inputs`` because a build reads none of it -- the
    factors are matched onto the consensus flows by ``characterise``, which runs
    after ``build`` and reads what it wrote.
    """

    #: Dotted path to the adapter, as ``module:attr``.
    adapter: str
    #: Where the adapter writes, in the data directory.
    factors_path: Path
    #: The methods to ingest, and what each is checked against.
    methods: tuple[LciaMethodSpec, ...]
    #: Who rendered the method, as
    #: :class:`~brightway_flows.lcia.categories.Implementation` spells it.
    #: Stated rather than taken from the list, because the two are not the same
    #: fact: BAFU's distribution ships GreenDelta's package, and an
    #: implementation attributed to whichever list it arrived with would credit
    #: the wrong people and publish the wrong ``implemented_by``.
    implemented_by: str = ""
    #: The lists whose merged flows this implementation's factors are looked up
    #: in, in the order they are tried.  Empty means the list's own, which is
    #: ecoinvent's case: the workbook names ecoinvent's flows.  GreenDelta's
    #: package names *ecoinvent's* -- it is built against ecoinvent 3.6 to 3.11
    #: and ships no list of its own -- so it declares the chain that reaches
    #: them, newest release first.
    resolve_through: tuple[str, ...] = ()

    @classmethod
    def from_manifest(cls, payload: Any, *, path: Path) -> LciaSpec:
        """Parse the optional ``lcia`` block of a manifest."""
        if not isinstance(payload, dict):
            raise ValueError(f"{path.name}: lcia must be an object or absent.")
        adapter = payload.get("adapter")
        if not isinstance(adapter, str) or ":" not in adapter:
            raise ValueError(
                f"{path.name}: lcia.adapter must be a dotted path as "
                "'module:attr'."
            )
        factors = payload.get("factors")
        if not isinstance(factors, str) or not factors.strip():
            raise ValueError(f"{path.name}: lcia.factors must name a file.")
        methods = payload.get("methods")
        if not isinstance(methods, list) or not methods:
            raise ValueError(
                f"{path.name}: lcia.methods must be a non-empty list. A list "
                "that publishes no method does not need an lcia block."
            )
        parsed = tuple(
            LciaMethodSpec.from_manifest(entry, path=path) for entry in methods
        )
        names = [method.name for method in parsed]
        if len(set(names)) != len(names):
            raise ValueError(f"{path.name}: lcia.methods names a method twice.")
        implemented_by = payload.get("implemented_by")
        if implemented_by is not None and (
            not isinstance(implemented_by, str) or not implemented_by.strip()
        ):
            raise ValueError(
                f"{path.name}: lcia.implemented_by must name who rendered the "
                "method, or be absent."
            )
        through = payload.get("resolve_through") or []
        if not isinstance(through, list) or not all(
            isinstance(key, str) and key.strip() for key in through
        ):
            raise ValueError(
                f"{path.name}: lcia.resolve_through must be a list of source "
                "list keys, or absent."
            )
        return cls(
            adapter=adapter.strip(),
            factors_path=DATA_DIR / factors.strip(),
            methods=parsed,
            implemented_by=(implemented_by or "").strip(),
            resolve_through=tuple(key.strip() for key in through),
        )


@dataclass(frozen=True)
class SourceList:
    """One flow list, and where its inputs live.

    Every curated input is optional: a list with no manual fixes or manual
    additions is merged without them, which is the normal state of a list on the
    day it is first added.  Only ``flows_path`` must exist, and that is checked
    when the flows are loaded rather than here, so that constructing the registry
    never depends on a download having happened.

    Context rules are not among them.  They live in one file keyed by ``source``
    rather than one file per list (#11), so "which contexts does this list
    map onto" is a question for :mod:`brightway_flows.context_mapping`, not
    a path stored here.  It used to be a path, naming a *generated* projection
    of that file which ``build`` never regenerated.
    """

    list_name: str
    list_version: str

    #: The source flows themselves, in the data directory: the one derived input.
    flows_path: Path
    #: Hand-authored field corrections applied before matching.
    manual_fixes_path: Path | None = None
    #: Curated groupings that become new elementary flows.
    manual_additions_path: Path | None = None
    #: Whole source flows the vendor ships where the fetch does not look,
    #: appended to the fetched rows before anything reads them (#25).  Not a
    #: correction: a fix names a field on a row that exists, and these rows do
    #: not exist until this file puts them there.
    additional_flows_path: Path | None = None
    #: A randonneur correspondence table of decisions made previously, or None
    #: for a list nobody has mapped yet.
    prepared_match_table: str | None = None
    #: Curated targets that win over whatever :attr:`prepared_match_table`
    #: says, applied by :func:`load_prepared_match_table`.  Not a manual fix: a
    #: fix names a field on a source flow, and a target uuid is not one.
    match_overrides_path: Path | None = None
    #: Minted IRI prefix for this list's flows.  Load-bearing: it is the
    #: `xkos:sourceConcept` `@id` in `concept_associations`, which is published
    #: and read downstream, so a list's prefix cannot change once it has shipped.
    flow_iri_prefix: str = ""
    #: How this list's mappings back to the consensus flows are built, or
    #: ``None`` for a list that publishes none.  ``None`` is not "no mappings
    #: exist" -- the merge writes ecoinvent's directly onto the flows -- it is
    #: "nothing is built for this list at transform time".
    #:
    #: Load-bearing for *when*, not only how: the builders for a run are the
    #: base list's plus those of the lists named by ``--source``, so a
    #: correspondence table is read only on a build that has something to use it
    #: for.  GLAD used to be downloaded and parsed by every `extract` to feed a
    #: builder no run registered (#244).
    concept_associations: ConceptAssociationSpec | None = None
    #: ``base`` or ``source``; see the module docstring.
    role: str = SOURCE_ROLE
    #: Dotted path to this list's :class:`SourceAdapter`, as ``module:attr``, or
    #: ``""`` for a list whose flows arrive by some other route.  Read through
    #: :func:`load_adapter`, which is where a bad path fails.
    adapter: str = ""
    #: Set only where the published ``flow.source`` string is not the key: the
    #: base list's flows say ``EF 3.1``, with a space.  Read through
    #: :attr:`source_label`, never directly.
    declared_source_label: str = ""
    #: Where this list belongs in the merge order; lower merges earlier.
    #:
    #: The order was whatever the `--source` flags were typed in.  That is not a
    #: preference: **the first list to reach a substance mints its flow object**,
    #: and everything merged after it matches against what that list created --
    #: which is why five manual-fixes files argue about ecoinvent's brine
    #: arriving before EF's.  A list whose rows carry registry numbers should
    #: reach a substance before one whose rows carry only a name, or the
    #: better-identified list ends up matching against objects the weaker one
    #: invented.
    #:
    #: Declared here rather than defended by whoever types the command, so that
    #: a run cannot get it wrong and a new list states where it belongs.
    #: Required for a ``source``; meaningless for the ``base``, which is what
    #: the sources are merged *into* and so is always first.
    #:
    #: It does not have to separate versions of one list.  Five ecoinvent
    #: releases share 100 and :func:`merge_order` puts the newest of them first,
    #: which is a fact about ecoinvent releases rather than five hand-picked
    #: numbers a sixth release would have to be squeezed between.
    merge_priority: int = 0
    #: Where this list's characterisation factors come from, or ``None`` for a
    #: list that publishes none -- which is every list but ecoinvent, whose
    #: workbook is the only second implementation of a method this project has.
    #: Read by ``fetch-lcia`` and by ``characterise``, never by a build.
    lcia: LciaSpec | None = None
    #: Whether this list's flows came, at some remove, out of SimaPro.
    #:
    #: Not a statement about the vendor -- BAFU is a Swiss federal agency and
    #: has nothing to do with SimaPro the company -- but about **where the flow
    #: names were shaped**.  A list built in or exported through SimaPro
    #: inherits a set of naming habits that nothing else has: the geography
    #: written into the name (``Water, RER``), the unit written into it
    #: (``Gas, natural/m3``), chemicals in CAS-index order (``Benzene,
    #: chloro-``), and the land-use class carried in the name rather than the
    #: compartment (``Occupation, annual crop``).
    #:
    #: Those are the patterns name matching has to undo, and they are wrong to
    #: apply anywhere else: de-inverting ``Benzene, chloro-`` is right for a
    #: SimaPro-lineage list and a licence to invent structures for a list that
    #: happens to have a comma in a name.  This is what lets a strategy say
    #: which lists it is entitled to run on.
    #:
    #: Optional, defaulting to false, unlike :attr:`merge_priority`.  The
    #: failure modes are not alike: a missing merge priority silently produces
    #: the wrong output, while a missing flag here declines an opportunity --
    #: the extra strategies do not run and the rows stay unmatched, which is
    #: visible in the merge report.  Safe by default is the correct bias for a
    #: flag that unlocks aggressive name rewriting.
    simapro_origin: bool = False

    #: Which stage of a build reads the place out of a flow name -- ``Water,
    #: AE`` is water in the Emirates, and the lineage writes the place into
    #: the name (#65).  From the manifest's ``simapro.geography_split``:
    #:
    #: - ``"extraction"``: the list's adapter splits while extracting, and the
    #:   place is part of the identity the uuids are derived from.  BAFU's
    #:   answer, permanently: its published uuids bake the split in, so moving
    #:   it would be a uuid migration (#192, plans/simapro-row-preparation.md).
    #: - ``"load"``: :meth:`load_flows` splits after the manual fixes, the way
    #:   the unit split runs -- the extraction file and the uuids untouched,
    #:   only the name the pipeline sees.
    #: - ``""`` (absent, or ``"off"`` in the manifest): no build stage splits.
    #:   The lookup's `prepare_row_for_matching` splits regardless, which is
    #:   how the gap this field closes stayed invisible (#192).
    #:
    #: Only meaningful beside :attr:`simapro_origin`; the manifest parser
    #: refuses the block on a list the lineage did not shape.
    geography_split: str = ""

    @property
    def key(self) -> str:
        """Stable identifier used on the command line and as a report key."""
        return f"{self.list_name}-{self.list_version}"

    @property
    def version_sort_key(self) -> tuple[int, ...]:
        """:attr:`list_version` as numbers, so 3.10.1 sorts after 3.9.1.

        Compared with :func:`merge_order` only, and only against other versions
        of the same list, which is what lets this be as simple as it is: every
        run of digits in the string, in order.  ``3.9.1`` is ``(3, 9, 1)`` and
        ``3.10.1`` is ``(3, 10, 1)``, where sorting the strings would put 3.10.1
        first -- the whole reason this is not `list_version` itself.  BAFU's
        ``2026-v1`` becomes ``(2026, 1)``, which orders BAFU releases sensibly
        and is never compared against an ecoinvent one.

        A version with no digits at all sorts first, which is the safe end: it
        would be merged last, matching against what the numbered releases built
        rather than the other way round.
        """
        digits: list[int] = []
        current = ""
        for character in self.list_version:
            if character.isdigit():
                current += character
            elif current:
                digits.append(int(current))
                current = ""
        if current:
            digits.append(int(current))
        return tuple(digits)

    @property
    def source_label(self) -> str:
        """What this list's flow records carry in ``Flow.source``.

        The key for every list that has one, which is every list whose flows
        this project fetches itself.  The base list arrives from a vendor
        already saying ``EF 3.1``, and that string is published, so it is
        declared rather than derived.
        """
        return self.declared_source_label or self.key

    @property
    def fetch_command(self) -> str:
        """What to run to produce :attr:`flows_path`, named in errors.

        Derived, not declared.  It was a manifest string per list until #15 --
        ``download-ecoinvent-flows --version 3.12``, ``extract`` -- which meant a
        new list had to invent a command *and* write the code behind it, and a
        renamed command left five manifests telling readers to run something that
        no longer existed.  One command fetches any list, so the string follows
        from the key.

        Empty for a list with no adapter: there is nothing to tell a reader to
        run, and a hint naming a command that would fail is worse than none.
        """
        return f"fetch-source {self.key}" if self.adapter else ""

    @property
    def merge_activity(self) -> str:
        """`prov:wasGeneratedBy` for values this merge writes."""
        return f"merge_{self.list_name}"

    @property
    def algorithm_addition_source(self) -> str:
        """`source` given to flows this list caused the merge to create.

        Derived rather than stored: it appears in the published artifact, so the
        value must stay exactly what it was, and deriving it means a new list
        cannot forget to set it.
        """
        return f"{self.list_name} algorithm addition"

    @property
    def manual_addition_source(self) -> str:
        """`source` given to flows created from this list's curated groupings."""
        return f"{self.list_name} manual addition"

    @property
    def addition_sources(self) -> frozenset[str]:
        """Both of the above; the merge asks "did this run create that flow?"."""
        return frozenset({self.algorithm_addition_source, self.manual_addition_source})

    def __str__(self) -> str:
        return self.key

    @classmethod
    def from_manifest(cls, payload: dict[str, Any], *, path: Path) -> SourceList:
        """Build a source list from one ``data/sources/*.json`` manifest.

        *path* is named only in errors: a manifest that does not describe a list
        has to say which file to open.
        """
        inputs = payload.get("inputs")
        if not isinstance(inputs, dict):
            raise ValueError(f"{path.name}: 'inputs' must be an object.")

        def curated(name: str) -> Path | None:
            value = inputs.get(name)
            if value is None:
                return None
            if not isinstance(value, str) or not value.strip():
                raise ValueError(
                    f"{path.name}: inputs.{name} must be a filename or null."
                )
            return PACKAGE_DATA_DIR / value.strip()

        flows = inputs.get("flows")
        if not isinstance(flows, str) or not flows.strip():
            raise ValueError(f"{path.name}: inputs.flows must name a file.")

        role = payload.get("role")
        if role not in _ROLES:
            raise ValueError(
                f"{path.name}: role must be one of {', '.join(_ROLES)}, not {role!r}."
            )

        for required in ("list_name", "list_version", "flow_iri_prefix"):
            value = payload.get(required)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{path.name}: {required} must be a non-empty string.")

        table = payload.get("prepared_match_table")
        if table is not None and (not isinstance(table, str) or not table.strip()):
            raise ValueError(
                f"{path.name}: prepared_match_table must be a name, a filename, or null."
            )

        priority = payload.get("merge_priority")
        if role == SOURCE_ROLE and not isinstance(priority, int):
            raise ValueError(
                f"{path.name}: merge_priority must be an integer. It is where this "
                "list belongs in the merge order, and the first list to reach a "
                "substance mints its flow object -- so a list that does not say "
                "would be placed by whatever order the --source flags happen to "
                "be typed in."
            )
        if isinstance(priority, bool):  # `bool` is an `int`, and not one here.
            raise ValueError(f"{path.name}: merge_priority must be an integer.")

        simapro = payload.get("simapro_origin", False)
        if not isinstance(simapro, bool):
            raise ValueError(
                f"{path.name}: simapro_origin must be true or false, not "
                f"{simapro!r}. It says whether this list's flow names were "
                "shaped by SimaPro, which is what entitles a name-matching "
                "strategy to run on them."
            )

        simapro_block = payload.get("simapro")
        geography_split = ""
        if simapro_block is not None:
            if not simapro:
                raise ValueError(
                    f"{path.name}: a `simapro` block on a list whose "
                    "simapro_origin is false configures habits the list does "
                    "not have. Set simapro_origin, or drop the block."
                )
            if not isinstance(simapro_block, dict):
                raise ValueError(
                    f"{path.name}: `simapro` must be an object, not "
                    f"{simapro_block!r}."
                )
            unknown = sorted(set(simapro_block) - {"geography_split"})
            if unknown:
                raise ValueError(
                    f"{path.name}: unknown `simapro` key(s) {unknown}; "
                    "only `geography_split` is understood. A misspelled key "
                    "would read as the default and look configured."
                )
            stage = str(simapro_block.get("geography_split") or "off").strip()
            if stage not in ("extraction", "load", "off"):
                raise ValueError(
                    f"{path.name}: simapro.geography_split must be "
                    f"'extraction', 'load' or 'off', not {stage!r}."
                )
            geography_split = "" if stage == "off" else stage

        associations = payload.get("concept_associations")
        spec = (
            None
            if associations is None
            else ConceptAssociationSpec.from_manifest(associations, path=path)
        )

        lcia = payload.get("lcia")
        lcia_spec = None if lcia is None else LciaSpec.from_manifest(lcia, path=path)

        return cls(
            list_name=payload["list_name"].strip(),
            list_version=payload["list_version"].strip(),
            flows_path=DATA_DIR / flows.strip(),
            manual_fixes_path=curated("manual_fixes"),
            manual_additions_path=curated("manual_additions"),
            additional_flows_path=curated("additional_flows"),
            match_overrides_path=curated("match_overrides"),
            prepared_match_table=table,
            flow_iri_prefix=payload["flow_iri_prefix"].strip(),
            concept_associations=spec,
            lcia=lcia_spec,
            role=role,
            adapter=str(payload.get("adapter") or "").strip(),
            declared_source_label=str(payload.get("source_label") or "").strip(),
            merge_priority=priority if isinstance(priority, int) else 0,
            simapro_origin=simapro,
            geography_split=geography_split,
        )

    def missing_curated_inputs(self) -> list[tuple[str, Path]]:
        """Declared curated inputs that are not on disk.

        ``flows_path`` is not checked: it is fetched rather than authored, its
        absence is reported by :meth:`load_flows` with the command that produces
        it, and checking it here would make a `--dry-run` build -- which never
        reaches the merge -- fail on a list it was not going to read.
        """
        missing: list[tuple[str, Path]] = []
        for name in _CURATED_INPUTS:
            path = getattr(self, f"{name}_path")
            if path is not None and not path.exists():
                missing.append((name, path))
        # A prepared match table is either a `randonneur_data` registry name --
        # not ours to check -- or a file checked in beside the manifests.
        if (table := self.prepared_match_table) and table.endswith(".json"):
            local = Path(table)
            if not local.is_absolute():
                local = PACKAGE_DATA_DIR / local
            if not local.exists():
                missing.append(("prepared_match_table", local))
        return missing

    def load_flows(self) -> list[Flow]:
        """This list's flows, as records, with its manual fixes applied.

        The merge read and repaired its own input inline, which meant a source
        list knew where its flows were but not how to produce them, and the
        result was dicts -- the last dict-shaped input in the pipeline.

        Records, and through the same normaliser the transform stage uses, so
        that a source list's flows arrive in one shape however they are reached.
        That is what lets a list be enriched before it is matched (#210)
        instead of being matched raw and enriched on a second build.

        Additional flows and manual fixes are applied to the raw rows *before*
        normalisation, because both name the source list's own field names --
        ``cas_number``, not ``cas_numbers``.

        :raises FileNotFoundError: if the list's flows have not been fetched.
        :raises ValueError: if the file is not a JSON list.
        """
        # Imported here, not at module scope: `pipeline.loading` reads the base
        # list from this module, and importing a `pipeline` submodule runs
        # `pipeline/__init__`, so the pair would be a cycle.
        from brightway_flows.pipeline.loading import _normalize_input_flow_record

        if not self.flows_path.exists():
            hint = f" Run `brightway-flows {self.fetch_command}` first." if self.fetch_command else ""
            raise FileNotFoundError(
                f"Source flows for {self.key} not found at {self.flows_path}.{hint}"
            )

        payload = orjson.loads(self.flows_path.read_bytes())
        if not isinstance(payload, list):
            raise ValueError(f"Expected list payload in {self.flows_path}")
        rows = [row for row in payload if isinstance(row, dict)]

        # Before the fixes, so that a fix can name an added row: both files are
        # curated, and which of them a given flow arrived by is not something a
        # correction should have to know.
        if self.additional_flows_path is not None:
            apply_additional_flows(
                rows,
                self.additional_flows_path,
                source=self.source_label,
                label=self.key,
            )

        if self.manual_fixes_path is not None:
            apply_manual_fixes(rows, self.manual_fixes_path, label=self.key)

        # After the list's own fixes, which speak about the vendor's file as
        # shipped, and before the unit split below, which reads the names these
        # leave.  Corrections for habits of the lineage rather than of one
        # list: every list whose names SimaPro shaped writes the element's
        # number on its isotope rows and a resource's energy content into its
        # name, and correcting that list by list is how BAFU's fourteen
        # `Uranium-238` rows were published as the element while Stepwise's
        # sat in a queue (#147).
        if self.simapro_origin:
            apply_manual_fixes(rows, SIMAPRO_LINEAGE_FIXES_FILEPATH, label=self.key)

        # After the fixes, for the same reason the unit split below runs after
        # them, and before it, in the order `prepare_row_for_matching` already
        # uses: a place in a name is a place whatever else is wrong with the
        # row.  Behind the manifest's word rather than `simapro_origin`,
        # because one list (BAFU) splits at extraction instead -- the place is
        # part of the identity its uuids derive from -- and running the split
        # twice for it would be work done to find nothing (#192).
        if self.geography_split == "load":
            self._split_geography_suffixes(rows)

        # After the fixes, so that a fix still names the flow the way the vendor
        # shipped it: a correction is written by reading the vendor's file, and
        # a curator should not have to predict what this leaves behind.  It is
        # also how a row this declines gets corrected at all -- BAFU's `Nm3` gas
        # rows say one measure in the name and another in the field, and a fix
        # rewrites the name before this sees it.
        if self.simapro_origin:
            self._strip_unit_suffixes(rows)

        flows: list[Flow] = []
        skipped = 0
        for row in rows:
            normalised = _normalize_input_flow_record(row, source_hint=self.key)
            if normalised is None:
                # No uuid and no identifier: nothing downstream could key on it.
                skipped += 1
                continue
            flows.append(Flow.from_dict(normalised))
        if skipped:
            logger.warning(
                "source_flows_without_identifier",
                source=self.key,
                path=str(self.flows_path),
                skipped=skipped,
            )
        logger.info("loaded_source_flows", source=self.key, count=len(flows))
        return flows

    def _strip_unit_suffixes(self, rows: list[dict[str, Any]]) -> None:
        """Take the unit back out of the names of *rows*, in place (#67).

        Only for a list ``simapro_origin`` is true of, like everything in
        :mod:`brightway_flows.simapro_names`, and gated by the caller
        rather than here so that reading `load_flows` shows what the flag buys.

        A row is asked about its own name and its own unit, and nothing else:
        a suffix comes off wherever it is a copy of the unit field.  The rule
        used to consult the whole list first, to decline a suffix that was the
        only thing telling two rows apart; it no longer does, because the two
        rows reached one flow either way and the suffix only cost them their
        match.  :func:`~brightway_flows.simapro_names.unit_suffix_rewrites`
        carries the reasoning.

        The vendor's spelling is added as a synonym, and it is worth being
        exact about what that buys, because it is not what it looks like.  The
        merge reads a row's synonyms when it matches it, so the spelling helps
        the row find its flow.  It is not published: `bootstrap_labels` moves
        the name into ``prefLabel`` and purges both fields, so no consensus flow
        carries ``Water/m3`` as an alternative label and a consumer holding a
        BAFU inventory finds their row through the correspondence written for
        its uuid, not by searching for the name their file uses.
        """
        rewrites = unit_suffix_rewrites(
            (str(row.get("name") or ""), str(row.get("unit") or "")) for row in rows
        )
        renamed = 0
        for row in rows:
            name, unit = str(row.get("name") or ""), str(row.get("unit") or "")
            stripped = rewrites.get((name, unit))
            if stripped is None:
                continue
            row["name"] = stripped
            synonyms = row.get("synonyms")
            if not isinstance(synonyms, list):
                synonyms = []
            if name not in synonyms:
                synonyms = [*synonyms, name]
            row["synonyms"] = synonyms
            renamed += 1
        if renamed:
            logger.info(
                "stripped_unit_suffix_from_names", source=self.key, count=renamed
            )

    def _split_geography_suffixes(self, rows: list[dict[str, Any]]) -> None:
        """Take the place back out of the names of *rows*, in place (#65, #192).

        The load-stage twin of what BAFU's extractor does: ``Water, AE``
        becomes ``Water`` in ``AE``.  Identity is deliberately untouched --
        the uuid stays whatever the extraction derived from the shipped
        fields -- which is what makes this safe for every curated table keyed
        on it, and is the whole reason the split runs here rather than in the
        adapter (`plans/simapro-row-preparation.md`).

        What each split row gains:

        - ``location``: the canonical code, so a withdrawn ``CS`` is reported
          as Serbia while the row's identity keeps the vendor's spelling;
        - ``original_name``: the name as shipped, for the record;
        - the shipped spelling as a **synonym**, because a third party
          matching their own list against ours will write ``Phosphorus, CN``
          and the row has to go on answering to it.  The merge reads
          synonyms; what the published flow object carries is the member-name
          pass's business.

        Both whitelists gate it, exactly as everywhere else: an unknown code
        is not a place, and a base label nobody vetted is not a name this is
        allowed to shorten -- ``Particulates, SPM`` is code-shaped and is
        suspended particulate matter.
        """
        renamed = 0
        for row in rows:
            name = str(row.get("name") or "")
            split = split_geography_suffix(name)
            if split is None:
                continue
            base, code = split
            row["name"] = base
            row["location"] = canonical_geography_code(code)
            row["original_name"] = name
            synonyms = row.get("synonyms")
            if not isinstance(synonyms, list):
                synonyms = []
            if name not in synonyms:
                synonyms = [*synonyms, name]
            row["synonyms"] = synonyms
            renamed += 1
        if renamed:
            logger.info(
                "split_geography_from_names", source=self.key, count=renamed
            )


@lru_cache(maxsize=None)
def _manifest_payloads() -> tuple[tuple[Path, dict[str, Any]], ...]:
    """Every manifest in `data/sources/`, parsed and structurally checked.

    Cached because the manifests are package data: they cannot change during a
    run, and the hot paths ask for the base list's `source_label` per flow.  The
    :class:`SourceList` objects themselves are rebuilt per call -- see
    :func:`known_source_lists`.
    """
    if not SOURCE_MANIFEST_DIR.is_dir():
        raise FileNotFoundError(
            f"No source list manifests found at {SOURCE_MANIFEST_DIR}. "
            "Each flow list this build knows about is one JSON file there."
        )

    payloads: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(SOURCE_MANIFEST_DIR.glob("*.json")):
        payload = orjson.loads(path.read_bytes())
        if not isinstance(payload, dict):
            raise ValueError(f"{path.name}: a manifest describes one list, as an object.")
        payloads.append((path, payload))

    if not payloads:
        raise FileNotFoundError(f"No source list manifests in {SOURCE_MANIFEST_DIR}.")
    return tuple(payloads)


def _registry() -> dict[str, SourceList]:
    """Every manifest as a :class:`SourceList`, keyed by `key`, both roles.

    Rebuilt per call.  A module-level dict would freeze the data directory at
    import time, which the verification harness overrides per run.
    """
    registry: dict[str, SourceList] = {}
    bases: list[str] = []
    for path, payload in _manifest_payloads():
        source = SourceList.from_manifest(payload, path=path)
        if source.key in registry:
            raise ValueError(
                f"{path.name}: {source.key} is already registered. A list's "
                "(list_name, list_version) is its identity, so two manifests "
                "cannot claim the same one."
            )
        if source.role == BASE_ROLE:
            bases.append(source.key)
        registry[source.key] = source

    if len(bases) != 1:
        raise ValueError(
            "Exactly one manifest must have role 'base' -- it is the list every "
            f"other list is merged into. Found: {', '.join(bases) or 'none'}."
        )
    return registry


def merge_order(sources: Iterable[SourceList]) -> list[SourceList]:
    """*sources* in the order the merge has to consume them.

    The first list to reach a substance mints its flow object, and every list
    merged after it matches against what that list created.  So the order is a
    property of the lists rather than of the invocation, and this is where that
    is decided.

    Two rules, and the second is why this is a function rather than a `sorted`
    call on :attr:`SourceList.merge_priority`:

    1. **Lowest `merge_priority` first.**  A better-identified list has to reach
       a substance before a weaker one -- ecoinvent at 100 carries vendor uuids,
       CAS and EC numbers; BAFU at 200 carries a name and, on fewer than half of
       its rows, a registry number.

    2. **Within one list, newest version first.**  Five ecoinvent releases share
       a priority, and a plain sort left the tie to the order the `--source`
       flags happened to be typed: `-s ecoinvent-3.8 -s ecoinvent-3.12` anchored
       the whole family to 2021 spellings, and reversing the two flags produced a
       different build from the same data (#100).  3.12 has better names and more
       registry numbers than 3.8, which is the same argument that puts ecoinvent
       ahead of BAFU, applied inside a list instead of between two.

    Sorted in two passes because the version half is descending and the rest
    ascending, and Python's sort is stable: the version pass survives the
    priority pass intact.  Lists of different names at one priority are grouped
    by name, so nothing here is left to the invocation.
    """
    by_version = sorted(sources, key=lambda s: s.version_sort_key, reverse=True)
    return sorted(by_version, key=lambda s: (s.merge_priority, s.list_name))


def known_source_lists() -> dict[str, SourceList]:
    """The lists the merge can consume, keyed by `SourceList.key`.

    The base list is deliberately absent: it is the thing being merged *into*,
    so naming it as a `--source` is not a build anyone means to run.
    """
    return {
        key: source
        for key, source in _registry().items()
        if source.role == SOURCE_ROLE
    }


def base_source_list() -> SourceList:
    """The fixed list every other list is merged into.

    A registry entry with `role: "base"` rather than the string ``"EF 3.1"``
    repeated across eight modules (#14).  Which list is the base is now the
    `role` in one manifest.
    """
    return next(
        source for source in _registry().values() if source.role == BASE_ROLE
    )


@lru_cache(maxsize=None)
def excluded_source_flows() -> dict[str, tuple[ExcludedSourceFlow, ...]]:
    """Every source row a list refuses, keyed by its concept scheme's slug.

    Keyed by the *scheme* slug rather than by :attr:`SourceList.key`, because
    the export hangs these off an `xkos:Correspondence`, and which scheme a
    correspondence belongs to is recovered from a flow IRI (see
    :func:`~brightway_flows.domain.vocabulary.scheme_for_flow_iri`).  The
    two strings are equal for every list registered today; deriving it means
    they cannot silently stop being.

    Every registered list is read, not only those a build merges.  What a list
    refuses is a property of the curated file, and the export drops the entry
    for any scheme this build publishes no correspondence for.

    Cached: the files are small, they cannot change within a run, and the export
    asks once per document.
    """
    from brightway_flows.domain.vocabulary import scheme_for_flow_iri

    out: dict[str, tuple[ExcludedSourceFlow, ...]] = {}
    for key, source in known_source_lists().items():
        if source.additional_flows_path is None:
            continue
        records = load_excluded_source_flows(
            source.additional_flows_path, source=source.source_label
        )
        if not records:
            continue
        scheme = scheme_for_flow_iri(source.flow_iri_prefix)
        if scheme is None:
            # A list whose prefix no scheme claims publishes no correspondence
            # either, so there is nowhere to hang the exclusions and no consumer
            # to read them.  Refused rather than dropped: the manifest and the
            # scheme registry disagreeing is a bug in one of them, and a silent
            # skip here would surface as three flows missing from an export.
            raise ValueError(
                f"{key} excludes {len(records)} source flow(s), but its flow IRI "
                f"prefix {source.flow_iri_prefix!r} belongs to no registered "
                f"concept scheme, so the exclusions have nowhere to be published."
            )
        out[scheme.slug] = records
    return out


@lru_cache(maxsize=None)
def base_source_label() -> str:
    """The `source` string the base list's flows carry, e.g. ``"EF 3.1"``.

    Cached: several per-flow loops compare against it, and the answer cannot
    change within a run.
    """
    return base_source_list().source_label


@lru_cache(maxsize=None)
def simapro_origin_source_labels() -> frozenset[str]:
    """The ``source`` strings of every list whose names SimaPro shaped.

    One place for a name-matching strategy to ask "am I allowed to run on this
    row?", rather than each of them growing its own list of keys -- which is
    the shape that made `known_source_lists` a comprehension over ecoinvent
    versions and left a second list unreachable (#12).

    Labels rather than keys because a strategy holds a flow, and what a flow
    carries is :attr:`SourceList.source_label`.

    Cached: the manifests are package data and cannot change within a run.
    """
    return frozenset(
        source.source_label
        for source in (base_source_list(), *known_source_lists().values())
        if source.simapro_origin
    )


def registered_source_list(key: str) -> SourceList:
    """Look up *key* in the registry, in either role.

    Distinct from :func:`resolve_source_list`, which answers "can this list be
    merged" -- it excludes the base list and demands context rules.  Fetching
    asks something weaker and earlier: "is this a list at all".  The base list is
    fetched like any other, and a list is fetched *before* anyone maps its
    compartments, so requiring context rules here would make the first step of
    adding a list depend on the second.

    :raises ValueError: if `key` names no list.
    """
    registry = _registry()
    try:
        return registry[key]
    except KeyError:
        allowed = ", ".join(sorted(registry))
        raise ValueError(
            f"Unknown source list {key!r}. Known source lists: {allowed}"
        ) from None


def source_flows_path(key: str) -> Path:
    """Where *key*'s flows are written by its fetch and read by the merge.

    One line of one manifest, resolved against the data directory.  It used to
    be `filesystem.ecoinvent_flows_filepath(version)`, and the fetch built the
    same name a second time from the same convention -- so a list whose flows
    file was named anything else could be downloaded to a path nothing read.

    :raises ValueError: if `key` names no list.  Fetching a list with no
        manifest writes a file nothing will ever open.
    """
    return registered_source_list(key).flows_path


def load_adapter(
    source: SourceList, *, dotted_path: str | None = None
) -> SourceAdapter:
    """Import the :class:`SourceAdapter` *source*'s manifest names.

    ``module:attr``, imported here rather than at registry-build time: an
    adapter pulls in whatever its vendor needs -- `ecoinvent_interface`, an XML
    parser, an HTTP client -- and reading the registry happens on every build,
    including builds that fetch nothing.

    *dotted_path* names a second adapter the same list declares, which today is
    ``lcia.adapter``: fetching ecoinvent's characterisation factors is the same
    job as fetching its flows, against a different file, and both are reported
    against the list rather than as an `ImportError` from somewhere the reader
    has never heard of.

    :raises ValueError: if the list declares no adapter, or if the dotted path
        does not name a callable.  Both are manifest mistakes.
    """
    declared = dotted_path if dotted_path is not None else source.adapter
    if not declared:
        raise ValueError(
            f"Source list {source.key!r} declares no adapter, so there is "
            "nothing to fetch it with. Add `\"adapter\": \"package.module:fetch\"` "
            "to its manifest in data/sources/."
        )
    module_name, _, attribute = declared.partition(":")
    if not module_name or not attribute:
        raise ValueError(
            f"Source list {source.key!r} declares adapter {declared!r}, "
            "which is not a 'module:attribute' path."
        )
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise ValueError(
            f"Source list {source.key!r} names adapter {declared!r}, "
            f"whose module could not be imported: {exc}"
        ) from exc
    adapter = getattr(module, attribute, None)
    if not callable(adapter):
        raise ValueError(
            f"Source list {source.key!r} names adapter {declared!r}, "
            f"but {module_name} has no callable {attribute!r}."
        )
    return adapter


def fetch_source_flows(source: SourceList, *, force: bool = False) -> Path:
    """Run *source*'s adapter and return the path it wrote.

    The one place a list's flows are produced, for every list.  It also holds the
    adapter contract to its word: an adapter that writes somewhere other than the
    manifest's `inputs.flows` has produced a file the merge will never open, and
    the run that discovers that is the one an hour later reporting the flows
    missing.
    """
    adapter = load_adapter(source)
    written = Path(adapter(source, force=force))
    if written != source.flows_path:
        raise ValueError(
            f"Adapter {source.adapter!r} for {source.key} wrote {written}, but "
            f"its manifest says its flows live at {source.flows_path}. Nothing "
            "reads the path it wrote."
        )
    logger.info("fetched_source_flows", source=source.key, path=str(written))
    return written


def fetch_source_lcia(source: SourceList, *, force: bool = False) -> Path:
    """Run *source*'s LCIA adapter and return the path it wrote.

    The same contract as :func:`fetch_source_flows`, for the other thing a list
    can be asked for: an adapter that writes somewhere other than the manifest's
    ``lcia.factors`` has produced a file nothing will open.

    :raises ValueError: if the list declares no ``lcia`` block, or its adapter
        writes to the wrong path.
    """
    if source.lcia is None:
        raise ValueError(
            f"{source.key} declares no lcia block, so there is nothing to "
            f"fetch. Only a list that publishes an implementation of an LCIA "
            f"method has one."
        )
    adapter = load_adapter(source, dotted_path=source.lcia.adapter)
    written = Path(adapter(source, force=force))
    if written != source.lcia.factors_path:
        raise ValueError(
            f"LCIA adapter {source.lcia.adapter!r} for {source.key} wrote "
            f"{written}, but its manifest says its factors live at "
            f"{source.lcia.factors_path}. Nothing reads the path it wrote."
        )
    logger.info("fetched_source_lcia", source=source.key, path=str(written))
    return written


def resolve_source_list(key: str) -> SourceList:
    """Look up a source list by `key`, e.g. ``ecoinvent-3.12``.

    Also asserts that the list can actually be merged: that the inputs its
    manifest declares are on disk, and that the context mapping has rules for
    it.  The registry used to over-promise: five ecoinvent versions resolved,
    but only two had context rules, so ``--source ecoinvent-3.11`` resolved,
    downloaded, ran the whole transform, and then failed every row's context.
    `build` resolves every `--source` before doing any work precisely so that a
    bad one fails immediately, and "nothing has mapped this list's contexts" is
    the same class of mistake as "no such list".

    :raises ValueError: if `key` names no list, names one whose declared
        curated inputs are not present, or names one the context mapping has no
        rules for.
    """
    registry = known_source_lists()
    try:
        source = registry[key]
    except KeyError:
        allowed = ", ".join(sorted(registry))
        raise ValueError(
            f"Unknown source list {key!r}. Known source lists: {allowed}"
        ) from None

    if missing := source.missing_curated_inputs():
        detail = "; ".join(f"{name} at {path}" for name, path in missing)
        raise ValueError(
            f"Source list {key!r} declares inputs that do not exist: {detail}."
        )

    # Imported here rather than at module scope: `context_mapping` is read by
    # the transform as well, and this is the only place the registry needs it.
    from brightway_flows.context_mapping import (
        MANUAL_MAPPING_FILEPATH,
        context_iri_by_source_context,
    )

    if not context_iri_by_source_context(source.source_label):
        raise ValueError(
            f"Source list {key!r} has no context mapping rules: no row in "
            f"{MANUAL_MAPPING_FILEPATH.name} has source {source.source_label!r}. "
            "The merge would place none of its rows."
        )
    return source


#: Randonneur verbs that pair a source flow with a target one.  `replace` is
#: what the published ecoinvent-to-EF tables use; `update` is what the
#: transitive tables use, and both carry `source` and `target` objects.
#: `delete` is deliberately absent: it names a source with no target, which is
#: the absence of a decision rather than one the merge can follow.
_MATCH_VERBS = ("replace", "update")


# ecoinvent 3.8's composed correspondence table used to live beside the
# manifests; #141 retired every prepared table, and the composed file, its
# composing tool and the fixtures that read it as history are all in git
# history now. What a source loads is its override rows, onto the empty
# table every manifest declares.
def load_prepared_match_table(
    source: SourceList,
    *,
    registered_as: Mapping[str, Sequence[str]] | None = None,
) -> list[dict]:
    """The correspondence table of decisions already made about *source*.

    *registered_as* is what this release registers each of its flows as, by
    uuid, and the merge passes the flows it has already loaded.  It is what
    lets an override that records a renumbering check be re-asked against a
    release nobody has checked it against; see
    :mod:`brightway_flows.match_overrides`.  Omitted, the question is not
    asked, which is right for a caller holding no flows -- a test reading the
    table's shape has none, and neither has the 3.8 composition.

    :attr:`SourceList.match_overrides_path` is applied on top of it, which is
    the one hook a curated target has for a list whose table this project does
    not write.  ecoinvent 3.9.1 onwards read theirs from `randonneur_data`
    verbatim, so a decision like mapping ecoinvent's coarse particulate fraction
    onto EF 3.1's `particles (PM10)` (#37) could be stated for 3.8, whose table
    is composed here, and nowhere else.  Overriding what the table loads covers
    every version by one route.

    Empty for a list with no table, which is what a newly added list looks like:
    every row then goes through algorithmic matching and lands in the report for
    a curator to decide.

    `prepared_match_table` is either a `randonneur_data` registry name or a path
    to a local file.  A local path is how a table composed for this project is
    consumed before it has been contributed upstream: `randonneur_data` publishes
    no ecoinvent 3.8 to EF 3.1 correspondence, so that table is generated here,
    reviewed, and checked in.

    Which verb the rows are under is read from the table rather than assumed.
    This used to be `data["replace"]` unconditionally, which raised `KeyError`
    on any table using `update`.

    Note the merge keys prepared rows on ``source["uuid"]``, and `update`-verb
    tables spell that field ``identifier``.  Reading the verb is therefore
    necessary but not sufficient to consume a transitive table directly; the
    composed tables this project checks in use `replace` and `uuid`.
    """
    return apply_match_overrides(
        _declared_match_table(source),
        source.match_overrides_path,
        label=source.key,
        release=source.list_version,
        registered_as=registered_as,
    )


def _declared_match_table(source: SourceList) -> list[dict]:
    """The rows of the table *source*'s manifest names, before any override."""
    if not source.prepared_match_table:
        return []

    local = Path(source.prepared_match_table)
    if local.suffix == ".json":
        if not local.is_absolute():
            local = PACKAGE_DATA_DIR / local
        if not local.exists():
            raise FileNotFoundError(
                f"Prepared match table for {source.key} not found at {local}."
            )
        data = orjson.loads(local.read_bytes())
    else:
        data = rd.Registry().get_file(source.prepared_match_table)

    for verb in _MATCH_VERBS:
        rows = data.get(verb)
        if isinstance(rows, list) and rows:
            return rows
    return []
