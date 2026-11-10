"""EF 3.1 as the ecoinvent Centre implements it, read from the file ecoinvent
publishes on GitHub rather than from the workbook behind its login.

The ecoinvent Association publishes the result of its LCIA mapping procedure at
https://github.com/ecoinvent/lcia: one CSV per method and release, each row an
ecoinvent elementary flow and each column after the seventeenth a category of
the method, under CC BY-NC 4.0.  For ecoinvent 3.12 that file states the same
EF v3.1 implementation as ``LCIA Implementation 3.12.xlsx`` -- the workbook
``integrations.ecoinvent_lcia`` reads, which a licence holder downloads and
nobody may redistribute -- and this adapter reads it instead, so that the 3.12
implementation this list publishes is one anybody can regenerate, and one whose
terms are the publisher's own.

**What the public file holds, measured against the 3.12 workbook this project
read first** (``EF v3.1_mapped_3.12.csv`` at commit ``1aed01c5``):

| | |
|---|---:|
| rows, one per ecoinvent 3.12 elementary flow | 9,830 |
| category columns | 25 |
| cells with a number in them | 30,627 |
| ...of which written as ``0.0`` | 3,212 |
| factors after the zeros are dropped | **27,415** |
| flows those factors name | **7,960** |
| factors the workbook's ``EF v3.1`` also states, at the same number | **27,415** |
| factors in the workbook and not here | **0** |

**The 3,212 zeros are dropped, and that is the one editorial decision here.**
The workbook states no row where the mapped file writes ``0.0``: a flow mapped
to an EF flow the method does not characterise gets a zero cell in every
category, where the workbook simply has no row.  A zero kept would be published
as a factor the ecoinvent Centre stated -- ``assessed, and zero`` -- and would
put 3,212 differences against the JRC into the difference report that the
workbook never produced.  The count of dropped cells is written into the file,
so a release in which the mapped file starts stating a real zero is a number
that moved rather than a number nobody saw.

**The file names a flow by ecoinvent's own UUID**, which is better than the
workbook's triple: ``elementary_flow_id`` is the identifier
``elementary_flow_sources`` joins on, and the name, compartment and
subcompartment columns beside it are checked against the extracted flow list
rather than used to find anything.  A UUID the extracted list does not have, or
one it names differently, is a release that has moved, and the fetch stops.

**There is no ``no LT`` file to check against.**  The repository publishes the
full method only, so the subtraction the workbook adapter verifies
(``check_long_term``) has nothing to run on here, and a manifest that asks this
adapter for one is refused rather than quietly answered with nothing.

What this writes is the workbook adapter's file format, under its
``FACTORS_SCHEMA_VERSION``, with the file's own provenance beside the counts --
repository, commit, digest and licence -- so ``lcia.sources`` reads both with
one reader and a reader of the file can see which it was.
"""

from __future__ import annotations

import csv
import math
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

import orjson
import structlog

from brightway_flows.domain.lcia.records import (
    StatedCategory,
    StatedFactor,
    stated_category,
)
from brightway_flows.downloads import PinnedFile, sha256
from brightway_flows.filesystem import ecoinvent_public_lcia_csv_path
from brightway_flows.integrations.ecoinvent_lcia import (
    FACTORS_SCHEMA_VERSION,
    FlowKey,
    check_against_crosswalk,
)

if TYPE_CHECKING:  # pragma: no cover - import cycle at runtime only
    from brightway_flows.sources import LciaSpec, SourceList

logger = structlog.get_logger(__name__)

#: Where the ecoinvent Association publishes its mapped method files.
REPOSITORY = "https://github.com/ecoinvent/lcia"
_RAW = "https://raw.githubusercontent.com/ecoinvent/lcia/"

#: The terms the repository's README states for its data.  Its
#: ``metadata.json`` says CC BY-NC 3.0; the README, which is the statement a
#: person reads, says 4.0, and the newer is recorded.  Not this project's data
#: licence, which is why it travels with the factors.
LICENCE_NAME = "CC BY-NC 4.0"
LICENCE_URL = "https://creativecommons.org/licenses/by-nc/4.0/"

#: The columns every mapped file opens with, in order, before the category
#: columns.  Stated so that a file whose columns move fails where it is read.
LEADING_COLUMNS = (
    "elementary_flow_id",
    "elementary_flow_name",
    "cas_number",
    "formula",
    "synonyms",
    "compartment",
    "subcompartment",
    "unit_name",
    "flow_status",
    "flow_used",
    "conversion_factor",
    "method_elementary_flow_id",
    "method_elementary_flow_name",
    "method_compartment",
    "method_subcompartment",
    "method_unit",
    "compartment_status",
)

#: What separates a category from its indicator in a column heading:
#: ``climate change|global warming potential (GWP100)``.
CATEGORY_SEPARATOR = "|"


class EcoinventPublicLciaError(ValueError):
    """The published file does not say what this reader requires of it."""


@dataclass(frozen=True, slots=True)
class PublishedMethodFile:
    """One method's mapped file in ecoinvent's repository, at one commit.

    Pinned to a commit rather than to a branch, so that the address always
    means the same bytes and the digest can be checked against what arrives.
    A new commit of the file is a new pin to look at, not a download to accept.
    """

    commit: str
    #: The file's path inside the repository.
    path: str
    #: Its SHA-256, as this project read it.
    sha256: str

    @property
    def url(self) -> str:
        return f"{_RAW}{self.commit}/{quote(self.path)}"

    @property
    def permalink(self) -> str:
        return f"{REPOSITORY}/blob/{self.commit}/{quote(self.path)}"

    @property
    def pinned(self) -> PinnedFile:
        return PinnedFile(urls=(self.url,), sha256=self.sha256)


#: The files this project reads, by ``(list_version, method name)``.  A release
#: or a method with no entry is one nobody has compared against the workbook
#: yet, and the fetch says so rather than reading the branch tip.
PUBLISHED_METHOD_FILES: dict[tuple[str, str], PublishedMethodFile] = {
    ("3.12", "EF v3.1"): PublishedMethodFile(
        commit="1aed01c5b6e89880f285275d00c5eafd1cd92ec5",
        path="3.12/methods_mapped/EF v3.1_mapped_3.12.csv",
        sha256="d818625e1b0bb4fd8f4ce3458bcb35659ab82616f9970ea11c5dd3bbfd01ed2f",
    ),
}


@dataclass(frozen=True, slots=True)
class MappedRow:
    """One row of a mapped file: a flow, and the numbers it carries."""

    flow_uuid: str
    key: FlowKey
    #: Category name to amount, with the zero cells already left out.
    amounts: dict[str, float]


@dataclass(frozen=True, slots=True)
class MappedFile:
    """What a mapped file says, read and checked but not yet resolved."""

    method: str
    categories: tuple[StatedCategory, ...]
    rows: tuple[MappedRow, ...]
    #: Cells written as zero and dropped (see the module docstring).
    zero_cells: int

    @property
    def factor_count(self) -> int:
        return sum(len(row.amounts) for row in self.rows)


# --------------------------------------------------------------------------
# reading the file


def _categories(header: tuple[str, ...], *, method: str) -> tuple[StatedCategory, ...]:
    """The category columns, as the records the workbook adapter also makes.

    No unit: the file states the flow's unit and the method flow's, and
    neither is the category's reference unit, so ``reference_unit`` is ``None``
    the way ``uuid`` is -- an absence, not a value.

    :raises EcoinventPublicLciaError: on a heading with no separator, an empty
        half, or a category named twice.
    """
    categories: list[StatedCategory] = []
    seen: set[str] = set()
    for heading in header[len(LEADING_COLUMNS):]:
        if heading.count(CATEGORY_SEPARATOR) != 1:
            raise EcoinventPublicLciaError(
                f"The column {heading!r} is not `category{CATEGORY_SEPARATOR}"
                f"indicator`, so it cannot be a category of {method!r}."
            )
        name, indicator = (part.strip() for part in heading.split(CATEGORY_SEPARATOR))
        if not name or not indicator:
            raise EcoinventPublicLciaError(
                f"The column {heading!r} names an empty category or indicator."
            )
        if name in seen:
            raise EcoinventPublicLciaError(
                f"The file states the category {name!r} twice, so a number "
                "under it cannot be placed."
            )
        seen.add(name)
        categories.append(
            stated_category(
                uuid=None,
                name=name,
                methodology=method,
                impact_indicator=indicator,
                reference_unit=None,
            )
        )
    if not categories:
        raise EcoinventPublicLciaError(
            f"The file has no category columns after {LEADING_COLUMNS[-1]!r}."
        )
    return tuple(categories)


def read_mapped_file(path: Path, *, method: str) -> MappedFile:
    """Every row of the mapped file at *path*, with the header checked.

    :raises EcoinventPublicLciaError: if the leading columns have moved, a row
        is the wrong width, a flow has no identifier or has two rows, or a
        cell is not a finite number.  Each is a file that has changed shape,
        and each is better as a failed fetch than as a number in the wrong
        field.
    """
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        try:
            header = tuple(cell.strip() for cell in next(reader))
        except StopIteration:
            raise EcoinventPublicLciaError(f"{path.name} is empty.") from None
        if header[: len(LEADING_COLUMNS)] != LEADING_COLUMNS:
            raise EcoinventPublicLciaError(
                f"{path.name} opens with the columns "
                f"{header[: len(LEADING_COLUMNS)]}, and this reads "
                f"{LEADING_COLUMNS}."
            )
        categories = _categories(header, method=method)
        names = [category.name or "" for category in categories]
        first_category = len(LEADING_COLUMNS)

        rows: list[MappedRow] = []
        seen: set[str] = set()
        zero_cells = 0
        for number, cells in enumerate(reader, start=2):
            if len(cells) != len(header):
                raise EcoinventPublicLciaError(
                    f"{path.name} line {number} has {len(cells)} cells and the "
                    f"header {len(header)}."
                )
            flow_uuid = cells[0].strip()
            if not flow_uuid:
                raise EcoinventPublicLciaError(
                    f"{path.name} line {number} states no elementary_flow_id."
                )
            if flow_uuid in seen:
                raise EcoinventPublicLciaError(
                    f"{path.name} states the flow {flow_uuid} twice (line "
                    f"{number}), and a file with one row per flow is the "
                    "shape this reads."
                )
            seen.add(flow_uuid)
            amounts: dict[str, float] = {}
            for name, cell in zip(names, cells[first_category:], strict=True):
                text = cell.strip()
                if not text:
                    continue
                try:
                    amount = float(text)
                except ValueError:
                    raise EcoinventPublicLciaError(
                        f"{path.name} line {number} states {text!r} under "
                        f"{name!r}, which is not a number."
                    ) from None
                if not math.isfinite(amount):
                    raise EcoinventPublicLciaError(
                        f"{path.name} line {number} states {text!r} under "
                        f"{name!r}, which is not a finite number."
                    )
                if amount == 0.0:
                    zero_cells += 1
                    continue
                amounts[name] = amount
            rows.append(
                MappedRow(
                    flow_uuid=flow_uuid,
                    key=FlowKey(
                        name=cells[1].strip(),
                        compartment=cells[5].strip(),
                        subcompartment=cells[6].strip(),
                    ),
                    amounts=amounts,
                )
            )
    if not rows:
        raise EcoinventPublicLciaError(f"{path.name} has a header and no rows.")
    return MappedFile(
        method=method,
        categories=categories,
        rows=tuple(rows),
        zero_cells=zero_cells,
    )


# --------------------------------------------------------------------------
# against the extracted flows


def flows_by_uuid(flows: Iterable[dict[str, Any]]) -> dict[str, FlowKey]:
    """Each extracted ecoinvent flow's triple, by its UUID.

    The inverse of the workbook adapter's ``flow_index``: there the triple is
    the only name a factor row has and the UUID is looked up; here the row
    states the UUID and the triple is what is checked.

    :raises EcoinventPublicLciaError: if a flow has no two-part context.  The
        file states a compartment and a subcompartment for every row, and a
        flow with neither cannot be compared with one.
    """
    index: dict[str, FlowKey] = {}
    for flow in flows:
        context = flow.get("context") or []
        if len(context) != 2:
            raise EcoinventPublicLciaError(
                f"Flow {flow.get('uuid')!r} has context {context!r}; the "
                "mapped file names every flow by a compartment and a "
                "subcompartment, so a flow with neither cannot be checked "
                "against it."
            )
        index[str(flow.get("uuid") or "")] = FlowKey(
            name=str(flow.get("name") or "").strip(),
            compartment=str(context[0]).strip(),
            subcompartment=str(context[1]).strip(),
        )
    return index


def resolve(
    *, file: MappedFile, flows: dict[str, FlowKey]
) -> tuple[list[StatedFactor], dict[str, int]]:
    """The rows that carry a number, as records against the flow each names.

    A row with no number left after the zeros is not looked at: the file lists
    every elementary flow of the release, characterised or not, and an
    uncharacterised flow the extracted list has retired is not a factor that
    reaches nothing.

    :raises EcoinventPublicLciaError: if a row with a number names a UUID the
        extracted list does not have, or names it under another name,
        compartment or subcompartment.  Neither is a matching question -- the
        UUID is ecoinvent's own identifier -- so a miss is a release that has
        moved rather than a row to drop.
    """
    characterised = [row for row in file.rows if row.amounts]
    unknown = sorted(row.flow_uuid for row in characterised if row.flow_uuid not in flows)
    if unknown:
        raise EcoinventPublicLciaError(
            f"{len(unknown)} flows carry a factor and are not in the extracted "
            f"list: {', '.join(unknown[:5])}"
        )
    misnamed = sorted(
        f"{row.flow_uuid} is {row.key} here and {flows[row.flow_uuid]} there"
        for row in characterised
        if flows[row.flow_uuid] != row.key
    )
    if misnamed:
        raise EcoinventPublicLciaError(
            f"{len(misnamed)} flows carry a factor under a name, compartment "
            f"or subcompartment the extracted list does not give them: "
            f"{'; '.join(misnamed[:5])}"
        )
    by_name = {category.name or "": category for category in file.categories}
    factors = [
        StatedFactor(category=by_name[name], flow_uuid=row.flow_uuid, amount=amount)
        for row in characterised
        for name, amount in row.amounts.items()
    ]
    per_category: Counter[str] = Counter(
        factor.category.name or "" for factor in factors
    )
    return factors, dict(per_category)


# --------------------------------------------------------------------------
# the adapter


def method_payload(
    *,
    file: MappedFile,
    published: PublishedMethodFile,
    digest: str,
    factors: list[StatedFactor],
    counts: dict[str, int],
) -> dict[str, Any]:
    """One method's block, in the workbook file's shape plus its provenance.

    ``long_term_check`` is ``None`` because there is nothing to check against,
    and it is written rather than left out so that a reader of both files sees
    the absence where the workbook's file has the record.
    """
    return {
        "method": file.method,
        "file": published.path,
        "permalink": published.permalink,
        "commit": published.commit if digest == published.sha256 else None,
        "file_sha256": digest,
        "categories": [
            {
                "category": category.name,
                "indicator": category.impact_indicator,
                "unit": category.reference_unit,
                "factor_count": counts.get(category.name or "", 0),
            }
            for category in file.categories
        ],
        "factor_count": len(factors),
        "flow_count": len({factor.flow_uuid for factor in factors}),
        "rows": len(file.rows),
        "zero_cells_dropped": file.zero_cells,
        "long_term_check": None,
        "factors": [
            {
                "flow_uuid": factor.flow_uuid,
                "category": factor.category.name,
                "amount": factor.amount,
            }
            for factor in factors
        ],
    }


def factors_payload(
    *, source: SourceList, methods: list[dict[str, Any]]
) -> dict[str, Any]:
    """The whole file: the provenance every method shares, and the blocks."""
    return {
        "schema_version": FACTORS_SCHEMA_VERSION,
        "source": source.key,
        "list_version": source.list_version,
        "repository": REPOSITORY,
        "licence": {"name": LICENCE_NAME, "url": LICENCE_URL},
        "methods": methods,
    }


def published_file_for(source: SourceList, method: str) -> PublishedMethodFile:
    """The pinned file for *method* of *source*'s release.

    :raises EcoinventPublicLciaError: if this project pins none.  The branch
        tip is not read in its place: a file nobody has compared against the
        workbook is a file nobody has checked.
    """
    published = PUBLISHED_METHOD_FILES.get((source.list_version, method))
    if published is None:
        pinned = ", ".join(
            f"{method} of {version}" for version, method in sorted(PUBLISHED_METHOD_FILES)
        )
        raise EcoinventPublicLciaError(
            f"This project pins no file in {REPOSITORY} for {method!r} of "
            f"ecoinvent {source.list_version}; it pins {pinned}. Compare the "
            "release's file against the workbook before adding it to "
            "`PUBLISHED_METHOD_FILES`, or read the workbook with "
            "`brightway_flows.integrations.ecoinvent_lcia:fetch`."
        )
    return published


def fetch(source: SourceList, *, force: bool = False) -> Path:
    """The LCIA adapter for a release whose mapped file ecoinvent publishes.

    Downloads the pinned file into the data directory unless it is already
    there (*force* downloads it again), reads it, checks it against the
    extracted flows and the crosswalk, and writes the factors file the
    manifest names.  Needs no ecoinvent credentials: that is the point of it.

    :raises EcoinventPublicLciaError: if the manifest asks for a ``no LT``
        check, pins no file, the extracted flows are missing, or the file is
        not what this reader requires of it.
    """
    if source.lcia is None:  # pragma: no cover - `fetch_source_lcia` checks first
        raise EcoinventPublicLciaError(f"{source.key} declares no lcia block.")
    spec: LciaSpec = source.lcia

    for method in spec.methods:
        if method.no_long_term:
            raise EcoinventPublicLciaError(
                f"{source.key}'s manifest asks for {method.name!r} to be checked "
                f"against {method.no_long_term!r}, and {REPOSITORY} publishes no "
                "such file. Drop `no_long_term` from the manifest, or read the "
                "workbook with `brightway_flows.integrations.ecoinvent_lcia:fetch`, "
                "which has both."
            )
    if not source.flows_path.exists():
        raise EcoinventPublicLciaError(
            f"The extracted flows for {source.key} are not at "
            f"{source.flows_path}, and a factor reaches a flow by naming it. "
            f"Run `{source.fetch_command}` first."
        )
    flows = flows_by_uuid(orjson.loads(source.flows_path.read_bytes()))

    blocks: list[dict[str, Any]] = []
    for method in spec.methods:
        published = published_file_for(source, method.name)
        csv_path = published.pinned.download(
            ecoinvent_public_lcia_csv_path(source.list_version, method.name),
            force=force,
        )
        digest = sha256(csv_path)
        if digest != published.sha256:
            # A hand-placed file is read as it is (`downloads`), and the file
            # that is written says which bytes it read and claims no commit.
            logger.warning(
                "ecoinvent_public_lcia_file_is_not_the_pinned_one",
                path=str(csv_path),
                sha256=digest,
                pinned=published.sha256,
            )
        logger.info(
            "reading ecoinvent public lcia file",
            source=source.key,
            method=method.name,
            path=str(csv_path),
        )
        file = read_mapped_file(csv_path, method=method.name)
        check_against_crosswalk(file.categories, method=method.name)
        factors, counts = resolve(file=file, flows=flows)
        blocks.append(
            method_payload(
                file=file,
                published=published,
                digest=digest,
                factors=factors,
                counts=counts,
            )
        )
        logger.info(
            "read_ecoinvent_public_lcia_file",
            method=method.name,
            rows=len(file.rows),
            factors=len(factors),
            zero_cells_dropped=file.zero_cells,
        )

    spec.factors_path.write_bytes(
        orjson.dumps(
            factors_payload(source=source, methods=blocks), option=orjson.OPT_INDENT_2
        )
    )
    logger.info(
        "saved ecoinvent public lcia factors",
        source=source.key,
        path=str(spec.factors_path),
        methods=[block["method"] for block in blocks],
        factors=sum(block["factor_count"] for block in blocks),
        licence=LICENCE_NAME,
    )
    return spec.factors_path
