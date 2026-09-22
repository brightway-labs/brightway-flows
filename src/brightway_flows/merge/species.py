"""The element/ion rule: a vendor's newest name for a flow is the canonical one.

`plans/retire-prepared-correspondence.md` §3a is the design and the measurement;
this is the machinery. ecoinvent renamed its dissolved-metal flows wholesale
between 3.8 and 3.9.1 -- `Selenium` (7782-49-2) became `Selenium IV`
(22541-55-5), `Copper` became `Copper ion` with the number deleted, and 3.8's
separate elemental-`Zinc` and `Zinc, ion` flows both became `Zinc II` -- the
same uuids throughout. The newest release's identity is the vendor's current
opinion, earlier ones are treated as mistaken, and one uuid is one substance in
every release. Two pieces make that real:

* **The canonical identities**, one file, derived mechanically from the release
  extractions by ``tools/derive_ecoinvent_canonical_identities.py`` and checked
  in, so the substitutions a build makes are a reviewable diff rather than a
  function of which extractions happened to be on disk. An entry exists only
  where a release on disk disagrees with the newest one; a uuid every release
  names alike needs no entry and gets none.
* **Charge normalisation**: `Nickel II`, `Nickel(2+)` and this list's
  `Nickel(2+)` label are one identity, and a generic `Copper ion` is its own --
  the vendor deleted the number deliberately, and picking a charge for it would
  be the reinterpretation the rule refuses. :func:`species_object_label` turns a
  parsed name into the label this list spells that identity with, and matching
  looks the label up like any other.

Neither piece rewrites what a vendor shipped. The substitution happens to the
*matching evidence* of a row -- the name and number the lookup consults -- and
the row's provenance keeps the release's own words. And it happens only for a
list with no prepared correspondence table: while a table decides where rows
land (every ecoinvent version, until the plan's PR F), this module changes
nothing, which is what makes its introduction hash-identical by construction.

Bare element names are deliberately not parsed as ions anywhere here. EF 3.1
itself ships 40 bare-element names in emission-to-water contexts beside their
speciated siblings, so a bare name is a legitimate identity of the reference
list, not an unfinished one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Mapping

import orjson

from brightway_flows.filesystem import PACKAGE_DATA_DIR

if TYPE_CHECKING:
    from brightway_flows.merge.state import SourceRow
    from brightway_flows.sources import SourceList

#: The derived file. One constant per data file (rule 5).
CANONICAL_IDENTITIES_FILEPATH = PACKAGE_DATA_DIR / "ecoinvent-canonical-identities.json"

#: Bumped when the file's shape changes; module-local (rule 13).
CANONICAL_IDENTITIES_SCHEMA_VERSION = 1

#: The elements the rule can be about. Full names, both spellings where two
#: exist. A polyatomic ion (`Thiocyanate`) is deliberately absent: it has no
#: elemental form, so a bare/charged pair of its name is a twin of one
#: substance (#130), never the element/ion family.
#: Rhodium and palladium joined on #198: ecoinvent 3.12 ships `Rhodium III`
#: and `Palladium II`, and a name outside this table is not the family's
#: business, so those two were never looked up as `Rhodium(3+)` and fell to
#: the vendor's bare synonym. A census of every charge-stated name on the
#: build of 2 September 2026 found exactly these two missing.
ELEMENTS = frozenset(
    """aluminium aluminum antimony arsenic barium beryllium boron bromine
    cadmium caesium calcium cesium chlorine chromium cobalt copper fluorine
    gold iodine iron lead lithium magnesium manganese mercury molybdenum
    nickel palladium phosphorus potassium rhodium scandium selenium silicon
    silver sodium strontium sulfur sulphur thallium tin titanium tungsten
    vanadium zinc""".split()
)

#: Spellings folded to the one this list's labels use.
_SPELLINGS = {"aluminum": "aluminium", "caesium": "cesium", "sulphur": "sulfur"}

_ROMAN = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6}
_NUMERIC = re.compile(r"^([a-z]+)\s*\((\d)\+\)$")
_ROMAN_RE = re.compile(r"^([a-z]+)\s+\(?(i{1,3}v?|vi?)\)?$")
_ION_RE = re.compile(r"^([a-z]+),?\s+ions?$")


class CanonicalIdentityError(ValueError):
    """A canonical-identity file that cannot be read as one.

    Raised rather than skipped (rule 14): a malformed entry silently ignored is
    a substitution that looks applied and is not.
    """


@dataclass(frozen=True)
class SpeciesName:
    """One name of the element/ion family, parsed."""

    #: The element, in this list's spelling, capitalised: ``Nickel``.
    element: str
    #: ``charge`` (a stated oxidation state, roman or numeric), ``ion`` (the
    #: generic marker, charge deliberately unstated), or ``bare``.
    kind: str
    #: The stated charge, for ``kind == "charge"`` only.
    charge: int | None = None


def parse_species(name: str) -> SpeciesName | None:
    """*name* as a member of the element/ion family, or ``None``.

    ``Nickel II``, ``Nickel (II)`` and ``Nickel(2+)`` parse to one record;
    ``Nickel ion`` and ``Nickel, Ion`` to the generic record; ``Nickel`` to the
    bare one. Anything whose root is not an element -- ``Thiocyanate, Ion``,
    ``Fungicides, unspecified`` -- is not the family's business and returns
    ``None``.
    """
    text = " ".join((name or "").split()).lower()
    if not text:
        return None
    if text in ELEMENTS:
        return SpeciesName(element=_canonical_element(text), kind="bare")
    for pattern, kind in ((_NUMERIC, "numeric"), (_ROMAN_RE, "roman"), (_ION_RE, "ion")):
        matched = pattern.match(text)
        if matched and matched.group(1) in ELEMENTS:
            element = _canonical_element(matched.group(1))
            if kind == "ion":
                return SpeciesName(element=element, kind="ion")
            charge = (
                int(matched.group(2)) if kind == "numeric" else _ROMAN[matched.group(2)]
            )
            return SpeciesName(element=element, kind="charge", charge=charge)
    return None


def _canonical_element(word: str) -> str:
    return _SPELLINGS.get(word, word).capitalize()


def species_object_label(species: SpeciesName) -> str:
    """The label this list spells *species* with.

    ``Nickel(2+)`` for a stated charge, ``Nickel, Ion`` for the generic marker
    -- the spelling `Arsenic, Ion` already publishes -- and the element itself
    for a bare name.
    """
    if species.kind == "charge":
        return f"{species.element}({species.charge}+)"
    if species.kind == "ion":
        return f"{species.element}, Ion"
    return species.element


@dataclass(frozen=True)
class CanonicalIdentity:
    """What the newest release says one uuid is."""

    uuid: str
    #: The newest release's name, verbatim.
    name: str
    #: The newest release's registry number, or ``""`` where it ships none --
    #: which is itself the vendor's statement, and replaces a stale number.
    cas_number: str
    #: The release the identity was read from.
    decided_by: str
    #: The earlier statements this replaces, as ``(version, name, cas)`` rows,
    #: so the file is reviewable without the extractions beside it.
    replaces: tuple[tuple[str, str, str], ...]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise CanonicalIdentityError(message)


def load_canonical_identities(
    path: Path | None = None,
) -> dict[str, CanonicalIdentity]:
    """The canonical identities, by uuid.

    Not cached: the path is injectable, and a test's file must not be answered
    with the derived one (rule 13).
    """
    filepath = path or CANONICAL_IDENTITIES_FILEPATH
    if not filepath.exists():
        return {}
    payload = orjson.loads(filepath.read_bytes())
    _require(isinstance(payload, dict), f"{filepath.name} is not an object")
    version = payload.get("schema_version")
    _require(
        version == CANONICAL_IDENTITIES_SCHEMA_VERSION,
        f"{filepath.name} is schema version {version!r}; this reads "
        f"{CANONICAL_IDENTITIES_SCHEMA_VERSION}",
    )
    rows = payload.get("identities")
    _require(isinstance(rows, list), f"{filepath.name} carries no identities list")

    index: dict[str, CanonicalIdentity] = {}
    for position, row in enumerate(rows):
        _require(isinstance(row, dict), f"identity {position} is not an object")
        uuid = str(row.get("uuid") or "").strip()
        _require(bool(uuid), f"identity {position} names no uuid")
        _require(uuid not in index, f"identity {position} is the second for {uuid}")
        name = str(row.get("name") or "").strip()
        _require(bool(name), f"identity {position} ({uuid}) names no name")
        _require(
            parse_species(name) is not None,
            f"identity {position} ({uuid}) is not the element/ion family: {name!r}. "
            f"The rule in plans/retire-prepared-correspondence.md §3a covers that "
            f"family and nothing else; a wider canonicalisation is a different "
            f"decision and must not arrive through this file.",
        )
        replaces = row.get("replaces")
        _require(
            isinstance(replaces, list) and bool(replaces),
            f"identity {position} ({uuid}) replaces nothing; an entry for a uuid "
            f"every release names alike decides nothing and must not exist",
        )
        rows_out = []
        for earlier in replaces:
            _require(
                isinstance(earlier, dict)
                and bool(str(earlier.get("version") or "").strip()),
                f"identity {position} ({uuid}) has a malformed `replaces` row",
            )
            rows_out.append((
                str(earlier["version"]),
                str(earlier.get("name") or ""),
                str(earlier.get("cas_number") or ""),
            ))
        index[uuid] = CanonicalIdentity(
            uuid=uuid,
            name=name,
            cas_number=str(row.get("cas_number") or "").strip(),
            decided_by=str(row.get("decided_by") or "").strip(),
            replaces=tuple(rows_out),
        )
    return index


def rule_governs(source: "SourceList") -> bool:
    """Whether the element/ion rule decides rows of *source*.

    Two conditions, and both are the point.  The canonical-identities file is
    derived from ecoinvent's releases and says nothing about anybody else's
    uuids.  And while a prepared correspondence table decides where a list's
    rows land, this rule deciding the same rows differently would be two
    authorities for one row -- so the rule waits for the table to be retired
    (plans/retire-prepared-correspondence.md, PR F), which is what makes its
    machinery hash-identical to introduce.
    """
    return source.list_name == "ecoinvent" and source.prepared_match_table is None


def canonicalized_for_matching(
    row: "SourceRow", identities: Mapping[str, CanonicalIdentity]
) -> "SourceRow":
    """*row* with the vendor's newest identity as its matching evidence.

    Two substitutions, both confined to what the lookup consults -- the flow's
    provenance keeps the release's own words:

    * A uuid the canonical-identities file names takes the newest release's
      name and number, *including* an empty number: 3.8's `Zinc` (7440-66-6)
      matches as `Zinc II` (23713-49-7), and 3.8's `Copper` matches as
      `Copper ion` with no number at all, because deleting the number is the
      newest release's statement too.
    * A name of the element/ion family with a stated charge or a generic ion
      marker leads its labels with the spelling this list publishes that
      identity under -- `Nickel II` looks up `Nickel(2+)`, `Copper ion` looks
      up `Copper, Ion` -- so the ordinary label branch matches it with no
      species-specific branch of its own.

    The stale labels are dropped rather than appended for a substituted row:
    the earlier release's name is exactly the evidence the rule overrides, and
    leaving `Zinc` in the lookup set would let the label narrowing resurrect
    the identity the vendor withdrew.  A bare canonical name is left entirely
    alone -- EF 3.1 ships bare elements in every compartment, and a bare name
    is an identity, not an omission.
    """
    identity = identities.get(row.uuid)
    name = row.name
    if identity is not None and (identity.name, identity.cas_number) != (row.name, row.cas):
        name = identity.name
        # The EC number goes with the labels: it is the *earlier* registration's
        # companion evidence, and leaving it made nine of 3.8's `Arsenic ion`
        # rows land on elemental arsenic through the element's EC while their
        # 3.12 siblings minted the ion -- one uuid, two substances, which is the
        # split this substitution exists to prevent.
        row = replace(row, name=name, cas=identity.cas_number, ec="", labels=[name])
    species = parse_species(name)
    if species is None or species.kind == "bare":
        return row
    label = species_object_label(species)
    # The label is lookup evidence only; the row's *name* stays what enrichment
    # settled on.  A version that also renamed the row was tried and reverted:
    # minted substances take their labels from the flow record inside
    # `resolve_flow_layers`, not from this row, so renaming here made
    # `merge_outcomes` disagree with the objects the same rows minted.
    # Harmonising the minted generic-ion spellings (`Arsenic Ion` beside the
    # EF-shipped `Titanium, ion`) is the label machinery's job, tracked on
    # #141.
    if label in row.labels:
        return row
    return replace(row, labels=[label, *row.labels])
