"""EF 3.1 as GreenDelta implements it, read from an openLCA JSON-LD package.

The third transcription, and the first that arrives as neither a method file nor
a workbook.  GreenDelta publishes the LCIA methods it implements for openLCA as
one archive, ``openLCA LCIA Methods 2.8.2``: 45 methods, their categories, the
61,211 elementary flows they characterise and the locations their regionalised
factors name.  This reads one method out of it, ``EF 3.1 Method (adapted)``.

**Read from the archive the `openlca` list is read from.**  It used to be the
copy inside BAFU's openLCA distribution -- 2.8.0, trimmed to this one method and
the 1,781 flows it characterised there, 26,179 factors.  The full package states
the same method over 33,045 flows, 183,654 factors: 26,175 of the 2.8.0 rows are
still there, nine with another number (eight in water use) and four gone.  The
implementation hangs off BAFU's manifest still, because BAFU's distribution is
where it first came from; the package is GreenDelta's, and so is the credit.

**Its flows are ecoinvent's where it was built against ecoinvent, and its own
otherwise.**  The manifest walks ecoinvent 3.12, 3.8 and EF 3.1 first, which is
what reached 1,222 of the 2.8.0 copy's 1,781 flows, and GreenDelta's own list
last, so a flow that route reached keeps its target and GreenDelta's own flows
are reached through the list they belong to.

Four things the archive is checked to be, because the reader downstream assumes
all four and a package that broke one would publish nonsense quietly:

* every category's ``@id`` is the JRC's own ILCD method-file UUID, which is what
  files a factor of theirs under one of our 25 (`domain.lcia.crosswalk`) -- less
  :data:`IGNORED_CATEGORIES`, GreenDelta's own 26th;
* no ``(category, flow, location)`` is stated twice with two numbers -- 1,897
  water-use rows are repeated verbatim, and are read once;
* every factor's unit is its flow's own reference unit, so nothing here needs a
  unit conversion the merge did not already record;
* every location the factors name has a code, which is what
  :attr:`~brightway_flows.domain.lcia.records.StatedFactor.geography` holds
  and what makes 91,304 regionalised rows comparable with the JRC's.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator
from zipfile import ZipFile

import orjson
import structlog

from brightway_flows.domain.lcia.crosswalk import ef_method
from brightway_flows.domain.lcia.records import StatedFactor, stated_category
from brightway_flows.filesystem import openlca_lcia_zip_path
from brightway_flows.sources import LciaSpec, SourceList, registered_source_list

logger = structlog.get_logger(__name__)

#: The shape :func:`fetch` writes and :func:`load_factors` reads.  A sibling of
#: ecoinvent's file rather than the same one: this states a geography on every
#: row, which the workbook's format has nowhere to put.
FACTORS_SCHEMA_VERSION = 1

#: The source list whose archive holds the package.  GreenDelta's EF 3.1 used to
#: be read from the copy inside BAFU's openLCA distribution -- 2.8.0, trimmed to
#: the one method and the 1,781 flows it characterised there.  The full package
#: is registered as a flow list of its own, so the method is read out of the
#: same archive that list is extracted from, and the two cannot drift apart.
PACKAGE_LIST = "openlca-2.8.2"

#: Categories of the method that are deliberately not read, by ``@id``, with
#: the reason.  2.8.2 states a 26th category beside EF 3.1's 25 -- a second
#: rendering of water use with GreenDelta's own spatialisation -- which is not a
#: category of the method the JRC publishes, so nothing here can file it.
IGNORED_CATEGORIES: dict[str, str] = {
    "1c11bfb6-3f1c-4e2b-a278-313d215e585f": (
        "Water use (adapted spatialization): GreenDelta's own variant of EF "
        "3.1's water use, not a category of the method."
    ),
}

_FLOWS = "flows/"
_CATEGORIES = "lcia_categories/"
_METHODS = "lcia_methods/"
_LOCATIONS = "locations/"


class GreenDeltaLciaError(RuntimeError):
    """The archive is not the package this reads."""


@dataclass(frozen=True, slots=True)
class Package:
    """What one openLCA method package holds, as this reader needs it."""

    #: The method's own record: name, version, description.
    method: dict[str, Any]
    #: The 25 categories, each with its factors inline.
    categories: tuple[dict[str, Any], ...]
    #: Every flow the package ships, by its openLCA UUID.
    flows: dict[str, dict[str, Any]]
    #: Location code by location UUID -- ``CH``, ``ES-CA``.
    locations: dict[str, str]

    @property
    def method_name(self) -> str:
        return str(self.method.get("name") or "")


def _documents(archive: ZipFile, prefix: str) -> Iterator[dict[str, Any]]:
    """Every JSON document under one folder of the package."""
    for name in archive.namelist():
        if name.startswith(prefix) and name.endswith(".json"):
            yield orjson.loads(archive.read(name))


def read_package(path: Path, *, method_name: str) -> Package:
    """The method named *method_name* out of the archive, parsed.

    The package holds 45 methods, and a category document says nothing about
    which method it belongs to: the method's own ``impactCategories`` is what
    does, so only the categories it lists are read, less
    :data:`IGNORED_CATEGORIES`.

    :raises GreenDeltaLciaError: if no method, or more than one, is called
        *method_name*. Picking one of two would publish an implementation under
        the other's name.
    """
    with ZipFile(path) as archive:
        methods = [
            method
            for method in _documents(archive, _METHODS)
            if str(method.get("name") or "") == method_name
        ]
        if len(methods) != 1:
            raise GreenDeltaLciaError(
                f"{path.name} holds {len(methods)} LCIA methods called "
                f"{method_name!r}; this reads exactly one."
            )
        listed = {
            str(entry.get("@id") or "")
            for entry in methods[0].get("impactCategories") or ()
        }
        categories = tuple(
            category
            for category in _documents(archive, _CATEGORIES)
            if str(category.get("@id") or "") in listed - IGNORED_CATEGORIES.keys()
        )
        flows = {
            str(flow["@id"]): flow for flow in _documents(archive, _FLOWS)
        }
        locations = {
            str(location["@id"]): str(location.get("code") or "")
            for location in _documents(archive, _LOCATIONS)
        }
    ignored = sorted(listed & IGNORED_CATEGORIES.keys())
    if ignored:
        logger.info(
            "greendelta_categories_ignored",
            categories=[IGNORED_CATEGORIES[uuid] for uuid in ignored],
        )
    return Package(
        method=methods[0],
        categories=categories,
        flows=flows,
        locations=locations,
    )


def _check_categories(package: Package, *, path: Path) -> None:
    """Every category is one of ours, addressed by the identifier they kept.

    :raises GreenDeltaLciaError: if a category names a UUID the method file does
        not pair with an EF 3.1 category. Filing its factors under a guess at
        the name would put numbers in a category nobody chose.
    """
    # Their own index and not the JRC's, even though the two hold the same
    # UUIDs: the method file says GreenDelta's identifiers are the JRC's
    # (`identifiers_from`) and checks it, so reading their row is reading what
    # this package is held to rather than what the JRC happens to state.
    known = ef_method().by_stated_identifier("greendelta")
    unknown = [
        (str(category.get("name") or ""), str(category.get("@id") or ""))
        for category in package.categories
        if str(category.get("@id") or "") not in known
    ]
    if unknown:
        raise GreenDeltaLciaError(
            f"{path.name} states categories whose identifiers "
            f"data/lcia-impact-categories.json does not pair with an EF 3.1 "
            f"category: {unknown}. Their package carried the JRC's own "
            f"method-file UUIDs; one that does not needs the method file's "
            f"`greendelta` rows written before it can be read."
        )


#: The categories EF 3.1 states as a **pair**, where which half a factor is
#: comes from the direction of the flow it characterises rather than from
#: anything on the factor itself.
#:
#: One slug, and why there is one rather than several is worth writing down.
#: `Water use` is a pair because water taken out of a catchment and water put
#: back are the same substance moving two ways: +6.98 for a cubic metre
#: withdrawn in France and -6.98 for one returned, so a process that withdraws
#: and returns the same water scores about nothing.  `Land use` looks like a
#: pair and is not: `Transformation, from forest` and `Transformation, to
#: forest` are two *flows*, both of them resources, so the minus sign is on the
#: flow rather than on its direction -- which is why GreenDelta's 5,733 negative
#: land-use factors are right as they stand and nothing here touches them.
#: Every other EF 3.1 category characterises emissions alone, where positive is
#: the only sign there is.
PAIRED_BY_DIRECTION = frozenset({"water-use"})

#: How openLCA says a flow is water going back into water.
#:
#: The whole prefix and not `Emission` alone.  Water evaporated to air is a
#: *loss* from the catchment and counts positively -- the ecoinvent Centre
#: states +42.95 for `Water vapour` in every air compartment -- so an emission
#: is the returning half of the pair only where it is an emission to water.
RETURNED_TO_WATER = "elementary flows/emission to water"


def with_the_pairs_sign(
    amount: float, *, category_slug: str, flow_category: str
) -> float:
    """*amount* with the sign the flow's direction gives it.

    Which half of a pair a factor is, is not stated on the factor: it is the
    direction of the flow it characterises, and openLCA states that in the
    flow's own category path -- `Elementary flows/Resource/...` for a
    withdrawal, `Elementary flows/Emission to water/...` for a return.

    GreenDelta's package states every water-use factor positive: their 1,438
    withdrawals, which is right, and all 416 of their returns, which is not.
    Where this list can compare a withdrawal of theirs with the JRC's -- 1,046
    of them, on groundwater, lake water, river water, turbine water and cooling
    water -- every one agrees to the digit, so the magnitudes are the JRC's and
    what is missing is the sign.  Left as shipped, returning water to the
    environment would *add* to a water-use score under their implementation, and
    a process that took a cubic metre and gave it back would score twice the
    withdrawal instead of nothing (#172).

    The magnitude is never touched and a stated zero stays zero, which is a
    statement rather than a value with a sign.  A factor that already carries
    the sign its direction gives it comes back unchanged: this states the
    convention, it does not negate a number for having disagreed.
    """
    if category_slug not in PAIRED_BY_DIRECTION:
        return amount
    if not flow_category.strip().lower().startswith(RETURNED_TO_WATER):
        return amount
    return -abs(amount) if amount else amount


def _factors(
    package: Package, *, path: Path
) -> tuple[list[StatedFactor], dict[str, dict[str, str]]]:
    """The package's factors, as records, and what each names its flow.

    The descriptions come back from here rather than from ``package.flows``
    because the two are not the same statement: a flow document carries its unit
    inside a flow property, while the stub beside a factor states the unit that
    factor is *per*.  Reading the stub is reading what the row says.

    A ``(category, flow, location)`` stated more than once with the same number
    is one statement repeated, and is read once: 2.8.2's water use repeats 357
    of its regionalised rows up to six times, every repeat identical.

    :raises GreenDeltaLciaError: if a factor is stated in a unit that is not its
        flow's own, if a location has no code, or if one
        ``(category, flow, location)`` is stated twice with different numbers --
        the three things the module docstring says the archive is, each of
        which would otherwise become a wrong number rather than a stopped run.
    """
    factors: list[StatedFactor] = []
    described: dict[str, dict[str, str]] = {}
    seen: dict[tuple[str, str, str], float] = {}
    repeated = 0
    # Their own index, as `_check_categories` uses: what a category is, to this
    # project, is what the method file pairs their identifier with, and the
    # slug is how the sign rule names the one category EF states as a pair.
    definitions = ef_method().by_stated_identifier("greendelta")
    signed = 0
    for entry in sorted(
        package.categories, key=lambda category: str(category.get("name") or "")
    ):
        # `.get`, and the fallback is a slug no rule names: refusing a category
        # this project cannot place is `_check_categories`'s job and it has run
        # by the time a fetch gets here, so raising a second time from inside
        # the sign rule would move the error message somewhere worse.
        definition = definitions.get(str(entry.get("@id") or ""))
        category_slug = definition.slug if definition is not None else ""
        category = stated_category(
            uuid=str(entry.get("@id") or ""),
            name=str(entry.get("name") or ""),
            methodology=package.method_name,
            reference_unit=str(entry.get("refUnit") or ""),
            general_comment=str(entry.get("description") or "") or None,
        )
        for row in entry.get("impactFactors") or ():
            flow = row.get("flow") or {}
            flow_uuid = str(flow.get("@id") or "")
            stated_unit = str((row.get("unit") or {}).get("name") or "")
            flow_unit = str(flow.get("refUnit") or "")
            if stated_unit != flow_unit:
                raise GreenDeltaLciaError(
                    f"{path.name}: {entry.get('name')!r} states a factor for "
                    f"{flow.get('name')!r} per {stated_unit!r}, but the flow is "
                    f"measured in {flow_unit!r}. Every row read so far is per "
                    f"the flow's own unit, and a row that is not needs a "
                    f"conversion this does not do."
                )
            geography = ""
            if location := row.get("location"):
                geography = package.locations.get(str(location.get("@id") or ""), "")
                if not geography:
                    raise GreenDeltaLciaError(
                        f"{path.name}: a factor for {flow.get('name')!r} names "
                        f"the location {location.get('name')!r}, which the "
                        f"package's own locations give no code for. A "
                        f"regionalised factor with no place is not comparable "
                        f"with anybody's."
                    )
            key = (str(entry.get("@id") or ""), flow_uuid, geography)
            stated = float(row.get("value") or 0.0)
            if key in seen:
                if seen[key] != stated:
                    raise GreenDeltaLciaError(
                        f"{path.name}: {entry.get('name')!r} states two factors "
                        f"for {flow.get('name')!r} in {geography or 'no place'}, "
                        f"{seen[key]} and {stated}, so one of them would "
                        f"silently win."
                    )
                repeated += 1
                continue
            seen[key] = stated
            described.setdefault(
                flow_uuid,
                {
                    "name": str(flow.get("name") or ""),
                    "category": str(flow.get("category") or ""),
                    "unit": flow_unit,
                    "cas": str(
                        (package.flows.get(flow_uuid) or {}).get("cas") or ""
                    ),
                },
            )
            amount = with_the_pairs_sign(
                stated,
                category_slug=category_slug,
                flow_category=str(flow.get("category") or ""),
            )
            signed += amount != stated
            factors.append(
                StatedFactor(
                    category=category,
                    flow_uuid=flow_uuid,
                    amount=amount,
                    geography=geography or None,
                )
            )
    if signed:
        logger.info("greendelta_pair_sign_applied", factors=signed)
    if repeated:
        logger.info("greendelta_identical_repeats_read_once", rows=repeated)
    return factors, described


def _digest(path: Path) -> str:
    """The archive's SHA-256, so a run can say which bytes it read."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _payload(
    *,
    source: SourceList,
    spec: LciaSpec,
    package: Package,
    archive: Path,
    factors: list[StatedFactor],
    described: dict[str, dict[str, str]],
) -> dict[str, Any]:
    """What the file holds: the records' own shape, and where they came from."""
    per_category: dict[str, int] = defaultdict(int)
    for factor in factors:
        per_category[factor.category.name or ""] += 1
    return {
        "schema_version": FACTORS_SCHEMA_VERSION,
        "source": source.key,
        "list_version": source.list_version,
        "archive": archive.name,
        "archive_sha256": _digest(archive),
        "package": str(package.method.get("category") or ""),
        "package_version": str(package.method.get("version") or ""),
        "methods": [
            {
                "method": package.method_name,
                "categories": [
                    {
                        "category": str(entry.get("name") or ""),
                        "category_uuid": str(entry.get("@id") or ""),
                        "unit": str(entry.get("refUnit") or ""),
                        "factor_count": per_category[str(entry.get("name") or "")],
                    }
                    for entry in sorted(
                        package.categories,
                        key=lambda category: str(category.get("name") or ""),
                    )
                ],
                "factor_count": len(factors),
                "flow_count": len({factor.flow_uuid for factor in factors}),
                "factors": [
                    {
                        "flow_uuid": factor.flow_uuid,
                        "category": factor.category.name,
                        "category_uuid": factor.category.uuid,
                        "amount": factor.amount,
                        "geography": factor.geography,
                    }
                    for factor in factors
                ],
                # What the publisher calls each flow it characterises. Written
                # beside the factors because a flow of theirs that reaches no
                # consensus flow is reported by name, and `82c27b2a-…` is not a
                # substance anybody can act on.
                "flows": [
                    {"uuid": uuid, **description}
                    for uuid, description in sorted(described.items())
                ],
            }
        ],
    }


def fetch(source: SourceList, *, force: bool = False) -> Path:
    """The LCIA adapter for GreenDelta's package: its factors, as a file.

    *force* is accepted because the protocol has it, and changes nothing: the
    archive is placed by hand (see :func:`~brightway_flows.filesystem.
    openlca_lcia_zip_path`) and re-read every time.

    :raises FileNotFoundError: if the archive is not in the data directory.
    :raises GreenDeltaLciaError: if the manifest does not declare exactly one
        method, since one package method is read per fetch.
    """
    if source.lcia is None:  # pragma: no cover - the manifest declares one
        raise ValueError(f"{source.key} declares no lcia block.")
    spec = source.lcia
    if len(spec.methods) != 1:
        raise GreenDeltaLciaError(
            f"{source.key}'s manifest declares {len(spec.methods)} methods for "
            f"GreenDelta's package; this reads one."
        )
    archive = openlca_lcia_zip_path(registered_source_list(PACKAGE_LIST).list_version)
    package = read_package(archive, method_name=spec.methods[0].name)
    _check_categories(package, path=archive)
    factors, described = _factors(package, path=archive)
    payload = _payload(
        source=source,
        spec=spec,
        package=package,
        archive=archive,
        factors=factors,
        described=described,
    )
    spec.factors_path.write_bytes(orjson.dumps(payload, option=orjson.OPT_INDENT_2))
    logger.info(
        "saved greendelta lcia factors",
        source=source.key,
        path=str(spec.factors_path),
        method=package.method_name,
        categories=len(package.categories),
        factors=len(factors),
        flows=len({factor.flow_uuid for factor in factors}),
        regionalised=sum(1 for factor in factors if factor.geography),
    )
    return spec.factors_path


def load_factors(path: Path) -> dict[str, list[StatedFactor]]:
    """What :func:`fetch` wrote, back as records, keyed by method.

    The read side of the file, here rather than in the pass that matches these
    onto consensus flows, because the shape belongs to whoever writes it.
    """
    payload = orjson.loads(path.read_bytes())
    version = payload.get("schema_version")
    if version != FACTORS_SCHEMA_VERSION:
        raise GreenDeltaLciaError(
            f"{path.name} states schema_version {version!r}; this reads "
            f"{FACTORS_SCHEMA_VERSION}. Re-run the fetch."
        )
    out: dict[str, list[StatedFactor]] = defaultdict(list)
    for method in payload.get("methods") or ():
        name = str(method.get("method") or "")
        categories = {
            str(row.get("category") or ""): stated_category(
                uuid=str(row.get("category_uuid") or "") or None,
                name=str(row.get("category") or ""),
                methodology=name,
                reference_unit=row.get("unit"),
            )
            for row in method.get("categories") or ()
        }
        for row in method.get("factors") or ():
            out[name].append(
                StatedFactor(
                    category=categories[str(row["category"])],
                    flow_uuid=str(row["flow_uuid"]),
                    amount=float(row["amount"]),
                    geography=row.get("geography") or None,
                )
            )
    return dict(out)


def flow_descriptions(path: Path) -> dict[str, dict[str, str]]:
    """What GreenDelta calls each flow it states a factor for.

    The same mapping :func:`brightway_flows.lcia.sources.source_flow_descriptions`
    builds from a source list's extracted flows, for an implementation whose
    flows are not a source list of this project at all.
    """
    payload = orjson.loads(path.read_bytes())
    described: dict[str, dict[str, str]] = {}
    for method in payload.get("methods") or ():
        for flow in method.get("flows") or ():
            described[str(flow.get("uuid") or "")] = {
                "name": str(flow.get("name") or ""),
                "context": str(flow.get("category") or ""),
                "unit": str(flow.get("unit") or ""),
                # Their registry number as they write it, zero-padded and all.
                # Normalising belongs to whoever compares it with ours
                # (`lcia.substance_matching`), so this stays what the file says.
                "cas": str(flow.get("cas") or ""),
            }
    return described
