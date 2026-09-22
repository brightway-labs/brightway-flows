"""The score artifact: what a vendor's own tooling says its unit processes are worth.

The hand analysis scored one activity two ways -- through brightway with
ecoinvent's own factors, and through this list with ours -- and found the
inventory identical while three categories were off by 434x, 28x and 2.3x.
This is the record of the first of those two routes, for a few hundred unit
processes rather than one, so the second can be re-run against it here and
the gap attributed flow by flow.

It is an *input*.  Nothing in this package can compute it: the life cycle
inventory of a unit process needs the whole technosphere solved, which is
brightway's job, and brightway is not a dependency of this list and will not
be.  `tools/export_unit_process_scores.py` writes it under a brightway Python;
this module reads it, and says what a valid one is.

Three things the file carries, and why each is there:

- **The inventory** of each unit process -- the vendor's own elementary flows,
  by the vendor's own identifier, with the cumulative amount per unit of
  reference product.  The vendor's identifier and not ours, because the whole
  question is what became of each vendor flow on its way to a consensus flow.
- **The factors** the vendor's tooling applied, once per (category, flow) and
  not once per unit process: the same number 500 times over would be most of
  the file.  Carried at all so that a difference in score can be split into
  "the flow did not map", "we have no factor" and "our factor differs", which
  the score alone cannot say.
- **The scores**, which the factors and the inventory reproduce.  The loader
  checks that they do (:func:`recompute`), so an artifact whose factors are not
  the ones its scores used is refused rather than compared.

The records are dataclasses and the JSON Schema is generated from them
(`domain.schema.unit_process_scores_schema`), so the exporter can validate
what it wrote against the checked-in schema without importing this package.
"""

from __future__ import annotations

import gzip
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import orjson
from jsonschema import Draft202012Validator
from pydantic import TypeAdapter, ValidationError

#: The artifact's own version, module-local (rule 13): a flow-list bump has
#: nothing to say about a brightway export, and the LCIA tables' version has
#: nothing to say about it either.
ARTIFACT_SCHEMA_VERSION = 1

#: The tolerance :func:`recompute` allows between a stated score and the sum of
#: its contributions, relative to the score.  Loose enough for summation order
#: -- brightway sums a sparse product, this sums a list -- and tight enough
#: that a factor the score did not use fails it.
RECOMPUTE_TOLERANCE = 1e-6


class ScoreArtifactError(ValueError):
    """An artifact that does not say what it claims to."""


@dataclass(frozen=True, slots=True)
class ArtifactRelease:
    """Which release was scored, by what, and how the sample was drawn."""

    list_name: str
    list_version: str
    system_model: str
    brightway_project: str
    brightway_database: str
    #: The vendor's method as brightway namespaces it -- ``EF v3.0`` for 3.8,
    #: ``EF v3.1`` for 3.12 -- and whatever the release ships, not what we
    #: would have preferred it to.
    method_family: str
    #: Package versions of the tooling that wrote the file, ``{"bw2data":
    #: "4.5", ...}``: a difference between two exports of one release is a
    #: difference in one of these before it is anything else.
    generator: dict[str, str]
    created_at: str
    sample_size: int
    sample_seed: int

    @property
    def key(self) -> str:
        """``ecoinvent-3.8-apos``, matching `AssessedRelease.key`."""
        return f"{self.list_name}-{self.list_version}-{self.system_model}"


@dataclass(frozen=True, slots=True)
class ArtifactCategory:
    """One of the vendor's impact categories, in the vendor's words.

    ``key`` is the brightway method tuple after its namespace, joined with
    ``|``: ``EF v3.0|climate change|global warming potential (GWP100)``.  A
    string rather than the tuple because it is a JSON object key in
    `UnitProcess.scores`, and the vendor's spelling rather than ours because
    the crosswalk to our categories is a decision this file does not take.
    """

    key: str
    method_family: str
    category: str
    indicator: str
    unit: str


@dataclass(frozen=True, slots=True)
class ArtifactFlow:
    """A vendor elementary flow as the vendor's tooling holds it.

    Carried beside the uuid so that a flow the merge never saw -- one the
    vendor added after the list was extracted, or one brightway spells
    differently -- can be named in a report rather than reported as a uuid.
    """

    source_flow_uuid: str
    name: str
    unit: str
    context: list[str]
    cas_number: str | None = None


@dataclass(frozen=True, slots=True)
class ArtifactFactor:
    """The factor the vendor's tooling applied to one flow under one category."""

    category_key: str
    source_flow_uuid: str
    amount: float


@dataclass(frozen=True, slots=True)
class InventoryLine:
    """One flow of a unit process's cumulative inventory, per unit of product."""

    source_flow_uuid: str
    amount: float


@dataclass(frozen=True, slots=True)
class UnitProcess:
    """One dataset: what it makes, where, and what it emits and takes to do so.

    ``activity_code`` is brightway's identifier and ``activity_uuid`` the
    vendor's; the first is what the exporter selected by and the second is
    what a reader with the vendor's data recognises.  ``scores`` is keyed by
    `ArtifactCategory.key` and holds what brightway computed -- the number
    the comparison is against.
    """

    activity_code: str
    activity_uuid: str
    name: str
    reference_product: str
    product_amount: float
    product_unit: str
    geography: str
    classifications: dict[str, str]
    inventory: list[InventoryLine]
    scores: dict[str, float]


@dataclass(frozen=True, slots=True)
class ScoreArtifact:
    """Root of one artifact file.

    The lists are lists and not dicts keyed by identifier so that a duplicate
    is a thing the loader finds rather than a thing JSON parsing silently
    collapses; the indexes a reader wants are the methods below.
    """

    schema_version: int
    release: ArtifactRelease
    categories: list[ArtifactCategory]
    flows: list[ArtifactFlow]
    factors: list[ArtifactFactor]
    unit_processes: list[UnitProcess] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ScoreArtifact:
        """Build the records from a payload whose shape has been checked.

        Types are checked here as pydantic checks them in lax mode -- a word
        where a number should be raises, a numeric string does not -- which is
        why :func:`load_score_artifact` validates against the JSON Schema
        first, where ``"0.0059"`` is a string and not a number.  The
        cross-references between the lists are :func:`validate`.
        """
        try:
            return _ADAPTER.validate_python(payload)
        except ValidationError as exc:
            first = exc.errors()[0]
            where = ".".join(str(part) for part in first["loc"]) or "document"
            raise ScoreArtifactError(f"{where}: {first['msg']}") from exc

    def category_index(self) -> dict[str, ArtifactCategory]:
        return {category.key: category for category in self.categories}

    def flow_index(self) -> dict[str, ArtifactFlow]:
        return {flow.source_flow_uuid: flow for flow in self.flows}

    def factor_index(self) -> dict[tuple[str, str], float]:
        """``(category_key, source_flow_uuid) -> amount``."""
        return {
            (factor.category_key, factor.source_flow_uuid): factor.amount
            for factor in self.factors
        }

    def factors_by_category(self) -> dict[str, dict[str, float]]:
        """``category_key -> {source_flow_uuid: amount}``."""
        out: dict[str, dict[str, float]] = {c.key: {} for c in self.categories}
        for factor in self.factors:
            out.setdefault(factor.category_key, {})[factor.source_flow_uuid] = factor.amount
        return out


_ADAPTER: TypeAdapter[ScoreArtifact] = TypeAdapter(ScoreArtifact)


def _finite(value: float, *, where: str) -> None:
    if not math.isfinite(value):
        raise ScoreArtifactError(f"{where}: {value!r} is not a finite number")


def _duplicates(values: list[str]) -> list[str]:
    seen: set[str] = set()
    repeated: list[str] = []
    for value in values:
        if value in seen and value not in repeated:
            repeated.append(value)
        seen.add(value)
    return repeated


def validate(artifact: ScoreArtifact) -> None:
    """The cross-references between the lists, and that the scores recompute.

    Every check names the key it failed on, because an artifact is a few
    hundred thousand lines and "invalid" is not a place to look.

    :raises ScoreArtifactError: on the first thing wrong.
    """
    if artifact.schema_version != ARTIFACT_SCHEMA_VERSION:
        raise ScoreArtifactError(
            f"schema_version {artifact.schema_version!r} is not "
            f"{ARTIFACT_SCHEMA_VERSION}"
        )
    for name, values in (
        ("categories", [c.key for c in artifact.categories]),
        ("flows", [f.source_flow_uuid for f in artifact.flows]),
        ("unit_processes", [u.activity_code for u in artifact.unit_processes]),
        ("factors", [f"{f.category_key}/{f.source_flow_uuid}" for f in artifact.factors]),
    ):
        if repeated := _duplicates(values):
            raise ScoreArtifactError(f"{name}: repeated {repeated[0]!r}")
    if not artifact.categories:
        raise ScoreArtifactError("categories: empty; nothing was scored")

    categories = artifact.category_index()
    flows = artifact.flow_index()
    for factor in artifact.factors:
        where = f"factors[{factor.category_key}/{factor.source_flow_uuid}]"
        if factor.category_key not in categories:
            raise ScoreArtifactError(f"{where}: names a category not in categories")
        if factor.source_flow_uuid not in flows:
            raise ScoreArtifactError(f"{where}: names a flow not in flows")
        _finite(factor.amount, where=where)

    by_category = artifact.factors_by_category()
    for process in artifact.unit_processes:
        where = f"unit_processes[{process.activity_code}]"
        # An empty inventory is not refused: ecoinvent 3.8 APOS has by-product
        # and waste-treatment entries -- `hard coal ash` from concrete
        # production, production amount -1 -- whose every burden is allocated
        # elsewhere, and 5 of a 500-dataset sample were.  Their scores are 0
        # and the recompute below agrees.
        _finite(process.product_amount, where=f"{where}.product_amount")
        if process.product_amount == 0:
            raise ScoreArtifactError(f"{where}.product_amount: zero")
        if repeated := _duplicates([line.source_flow_uuid for line in process.inventory]):
            raise ScoreArtifactError(f"{where}.inventory: repeated {repeated[0]!r}")
        for line in process.inventory:
            if line.source_flow_uuid not in flows:
                raise ScoreArtifactError(
                    f"{where}.inventory[{line.source_flow_uuid}]: names a flow "
                    "not in flows"
                )
            _finite(line.amount, where=f"{where}.inventory[{line.source_flow_uuid}]")
        if set(process.scores) != set(categories):
            missing = sorted(set(categories) - set(process.scores))
            extra = sorted(set(process.scores) - set(categories))
            raise ScoreArtifactError(
                f"{where}.scores: "
                + (f"missing {missing[0]!r}" if missing else f"unknown {extra[0]!r}")
            )
        for key, stated in process.scores.items():
            _finite(stated, where=f"{where}.scores[{key}]")
            recompute(process, key, by_category[key], stated=stated)


def recompute(
    process: UnitProcess,
    category_key: str,
    factors: dict[str, float],
    *,
    stated: float,
) -> float:
    """The score from the inventory and the factors, checked against *stated*.

    This is what makes the factors trustworthy: an exporter that wrote the
    scores from one method and the factors from another would pass every
    other check, and the comparison would then attribute the difference to
    the wrong numbers.

    :returns: the recomputed score.
    :raises ScoreArtifactError: if it is not *stated* within
        `RECOMPUTE_TOLERANCE`, relative to the larger of the score and the
        contributions -- a score near zero with contributions that cancel is
        held to the size of what cancelled, not to zero.
    """
    computed = 0.0
    scale = 0.0
    for line in process.inventory:
        factor = factors.get(line.source_flow_uuid)
        if factor is None:
            continue
        contribution = line.amount * factor
        computed += contribution
        scale = max(scale, abs(contribution))
    tolerance = RECOMPUTE_TOLERANCE * max(abs(stated), scale)
    if abs(computed - stated) > tolerance:
        raise ScoreArtifactError(
            f"unit_processes[{process.activity_code}].scores[{category_key}]: "
            f"stated {stated!r} but the inventory and factors give {computed!r}"
        )
    return computed


def load_score_artifact(path: Path, *, schema: dict[str, Any] | None = None) -> ScoreArtifact:
    """Read one artifact file, refusing anything that is not one.

    Three gates, in order of how cheaply they fail: the version, then the shape
    against the generated JSON Schema (which is what the exporter validated
    against, so a disagreement here is a schema drift and not a data error),
    then the cross-references and the recompute in :func:`validate`.  On the
    500-dataset 3.8 APOS export, 122 MB, the three together take about ten
    seconds, most of it the schema.

    *schema* defaults to the generated one; a test hands in a variant.

    :raises FileNotFoundError: naming the exporter, because the file is
        produced by a different Python and "missing" usually means "not yet".
    :raises ScoreArtifactError: for everything else.
    """
    if not path.exists():
        raise FileNotFoundError(
            f"{path}: no score artifact. Write one with "
            "tools/export_unit_process_scores.py under a brightway Python."
        )
    try:
        payload = orjson.loads(_read(path))
    except orjson.JSONDecodeError as exc:
        raise ScoreArtifactError(f"{path.name}: not JSON ({exc})") from exc

    from brightway_flows.domain.schema import (
        SchemaVersionError,
        check_schema_version,
        unit_process_scores_schema,
    )

    try:
        check_schema_version(payload, artifact=path.name, expected=ARTIFACT_SCHEMA_VERSION)
    except SchemaVersionError as exc:
        raise ScoreArtifactError(str(exc)) from exc

    validator = Draft202012Validator(schema or unit_process_scores_schema())
    for error in sorted(validator.iter_errors(payload), key=lambda e: list(e.absolute_path)):
        where = "/".join(str(part) for part in error.absolute_path) or "document"
        raise ScoreArtifactError(f"{path.name}: {where}: {error.message}")

    artifact = ScoreArtifact.from_dict(payload)
    try:
        validate(artifact)
    except ScoreArtifactError as exc:
        raise ScoreArtifactError(f"{path.name}: {exc}") from exc
    return artifact


def _read(path: Path) -> bytes:
    """The file's bytes, through gzip when it is a ``.gz``.

    The exporter writes plain JSON, 122 MB for 500 unit processes of 3.8
    APOS; the committed fixture -- three of them, one of which is the wind
    activity with its 2,144-line inventory -- is a sixth of that gzipped, and
    a test fixture is read far more often than it is diffed.
    """
    if path.suffix == ".gz":
        with gzip.open(path, "rb") as handle:
            return handle.read()
    return path.read_bytes()


def write_score_artifact(artifact: ScoreArtifact, path: Path) -> Path:
    """Write an artifact, validated first, indented so that it diffs.

    Here for the tests and for anything in this package that assembles one --
    a fixture cut from a real export, say.  The exporter does not use it: it
    runs under a Python this package is not installed in, and writes the same
    shape with the stdlib.  Gzipped when *path* ends in ``.gz``.
    """
    validate(artifact)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = orjson.dumps(artifact.to_dict(), option=orjson.OPT_INDENT_2) + b"\n"
    if path.suffix == ".gz":
        with gzip.open(path, "wb") as handle:
            handle.write(payload)
    else:
        path.write_bytes(payload)
    return path
