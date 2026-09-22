"""EF 3.1 as the ecoinvent Centre implements it, read out of its workbook.

The second implementation of a method this project has, and the first one that is
not the method's own publisher's.  ``LCIA Implementation 3.12.xlsx`` holds 484,598
characterisation factors over 633 indicators in 46 methods; two of them carry the
name EF v3.1 and one of those is ingested.

**What arrives, measured against the shipped workbook and the 9,850 ecoinvent
3.12 biosphere flows this project has already extracted:**

| | |
|---|---:|
| `EF v3.1` CF rows | 27,415 |
| distinct flow triples among them | 7,960 |
| ...that resolve to an ecoinvent flow | **7,960** |
| biosphere flows whose triple names more than one of them | **0** |
| `EF v3.1 no LT` CF rows | 27,190 |
| rows in `EF v3.1` and not in `no LT` | 225 |
| rows in `no LT` and not in `EF v3.1` | **0** |
| rows in both whose value differs | **0** |

Every one of those is asserted here rather than trusted, because each is a fact
about a release and not about the world.  A 3.13 that gives one flow two triples,
renames a category, or makes ``no LT`` more than a subtraction fails this fetch
instead of quietly writing something wrong.

**The flow is named by a triple, and that is the join.**  The workbook carries no
identifier for a flow any more than for a category: a CF row says
``(Name, Compartment, Subcompartment)``, and the first hop of getting a factor
onto a consensus flow is that triple against ``ecoinvent-biosphere-flows-*.json``.
It resolves exactly -- no case folding, no whitespace stripping, no synonym list
-- which is what makes it a join rather than a matching problem.  The second hop,
from an ecoinvent flow to a consensus flow, belongs to ``characterise``: it needs
what ``build`` wrote.

``plans/lcia-factors.md`` §2.2 through §2.4 is the design.  Nothing in a build
reads what this writes.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import orjson
import structlog

from brightway_flows.domain.lcia.crosswalk import by_stated_method_category
from brightway_flows.domain.lcia.records import (
    StatedCategory,
    StatedFactor,
    stated_category,
)

if TYPE_CHECKING:  # pragma: no cover - import cycle at runtime only
    from brightway_flows.sources import LciaMethodSpec, LciaSpec, SourceList

logger = structlog.get_logger(__name__)

#: The version of the file this writes.  Its own, per rule 13: the published
#: list's `SCHEMA_VERSION` is a different number about a different thing.
FACTORS_SCHEMA_VERSION = 1

#: What ecoinvent appends to every name in a ``no LT`` method: the method, each
#: of its categories and each of their indicators.  ``acidification`` becomes
#: ``acidification no LT``, so comparing the two methods row by row means taking
#: the suffix off first -- and a release that stops using it is one where nothing
#: here can tell which row is which, so it is asserted rather than assumed.
NO_LONG_TERM_SUFFIX = " no LT"

#: The sheet naming every method's categories, and the one holding the numbers.
INDICATORS_SHEET = "Indicators"
FACTORS_SHEET = "CFs"

#: The columns of each, in order.  Stated so that a workbook whose columns move
#: fails where it is read rather than three steps later with a number in the
#: wrong field.
INDICATOR_COLUMNS = ("Method", "Category", "Indicator", "Indicator Unit")
FACTOR_COLUMNS = (
    "Method",
    "Category",
    "Indicator",
    "Name",
    "Compartment",
    "Subcompartment",
    "CF",
)


@dataclass(frozen=True, slots=True)
class FlowKey:
    """How the workbook names a flow: the triple, and nothing else."""

    name: str
    compartment: str
    subcompartment: str

    def __str__(self) -> str:
        return f"{self.name} / {self.compartment} / {self.subcompartment}"


@dataclass(frozen=True, slots=True)
class LongTermCheck:
    """What a method's ``no LT`` sibling turned out to be.

    A subtraction, or the fetch has already failed.  Kept as a record so the
    written file can state what was checked and what it found, which is the
    difference between a rule and a claim.
    """

    method: str
    checked_against: str
    rows: int
    rows_in_sibling: int
    #: Rows the full method states and the sibling does not, by compartment.
    dropped_by_compartment: tuple[tuple[str, str, int], ...]

    @property
    def dropped(self) -> int:
        return sum(count for _c, _s, count in self.dropped_by_compartment)

    def to_dict(self) -> dict[str, Any]:
        return {
            "checked_against": self.checked_against,
            "rows": self.rows,
            "rows_in_sibling": self.rows_in_sibling,
            "rows_dropped": self.dropped,
            "dropped_by_compartment": [
                {"compartment": compartment, "subcompartment": sub, "rows": count}
                for compartment, sub, count in self.dropped_by_compartment
            ],
        }


class EcoinventLciaError(ValueError):
    """The workbook does not say what this reader requires of it."""


# --------------------------------------------------------------------------
# reading the workbook


def _rows(workbook: Any, sheet: str, columns: tuple[str, ...]) -> Iterable[tuple]:
    """Every row of *sheet* after its header, with the header checked.

    :raises EcoinventLciaError: if the sheet is absent or its columns have moved.
    """
    if sheet not in workbook.sheetnames:
        raise EcoinventLciaError(
            f"The workbook has no {sheet!r} sheet; it has "
            f"{', '.join(workbook.sheetnames)}."
        )
    rows = workbook[sheet].iter_rows(values_only=True)
    header = tuple(str(value or "").strip() for value in next(rows))
    if header[: len(columns)] != columns:
        raise EcoinventLciaError(
            f"The {sheet!r} sheet's columns are {header}, and this reads "
            f"{columns}."
        )
    return rows


def read_categories(
    workbook: Any, method: str
) -> tuple[StatedCategory, ...]:
    """The categories *method* declares, in sheet order.

    A :class:`~brightway_flows.domain.lcia.records.StatedCategory` with no
    ``uuid``: the workbook states none, and ``None`` there is that absence rather
    than a value.  The category's identity on this side is its name.
    """
    categories: list[StatedCategory] = []
    seen: set[str] = set()
    for row in _rows(workbook, INDICATORS_SHEET, INDICATOR_COLUMNS):
        if row[0] != method:
            continue
        name = str(row[1] or "").strip()
        if not name:
            raise EcoinventLciaError(
                f"{method!r} declares an indicator with no category name."
            )
        if name in seen:
            raise EcoinventLciaError(
                f"{method!r} declares the category {name!r} twice, so a factor "
                "naming it cannot be placed."
            )
        seen.add(name)
        categories.append(
            stated_category(
                uuid=None,
                name=name,
                methodology=method,
                impact_indicator=str(row[2] or "").strip() or None,
                reference_unit=str(row[3] or "").strip() or None,
            )
        )
    if not categories:
        raise EcoinventLciaError(
            f"The workbook declares no categories under {method!r}."
        )
    return tuple(categories)


def check_against_crosswalk(
    categories: tuple[StatedCategory, ...], *, method: str
) -> None:
    """That a method file and the workbook name the same categories.

    Only for a workbook method some method file pairs its categories with.  A
    method file pairs each of its categories with what ecoinvent calls it,
    because no string transform gets from ``Ecotoxicity, freshwater`` to
    ``ecotoxicity: freshwater``; a release that renames one leaves that row
    pairing a name nobody publishes, and the pair would silently stop matching.
    A workbook method no file pairs anything with is one this list does not
    publish, and it is read past rather than complained about.

    :raises EcoinventLciaError: on either difference. Both directions matter: a
        category the workbook gained is one no method file has a row for, and one
        it lost is a row that will never match again.
    """
    crosswalked = {
        category
        for (stated_method, category) in by_stated_method_category()
        if stated_method == method
    }
    if not crosswalked:
        return
    published = {category.name or "" for category in categories}
    missing = sorted(crosswalked - published)
    added = sorted(published - crosswalked)
    if missing or added:
        raise EcoinventLciaError(
            f"The crosswalk and {method!r} disagree about the categories. "
            f"The crosswalk names {len(missing)} the workbook does not "
            f"({', '.join(missing[:5])}); the workbook states {len(added)} the "
            f"crosswalk does not ({', '.join(added[:5])}). "
            "A method file is what pairs them."
        )


def read_factors(
    workbook: Any, methods: Iterable[str]
) -> dict[str, dict[tuple[FlowKey, str], float]]:
    """Every CF row of each named method, keyed by ``(flow, category)``.

    One pass over 484,598 rows for all the methods asked for, because opening
    the sheet again per method is the expensive half of this fetch.

    :raises EcoinventLciaError: if one method states two numbers for one flow and
        category. There is one factor per flow and category, and a workbook that
        breaks that is not something to reconcile here.
    """
    wanted = set(methods)
    out: dict[str, dict[tuple[FlowKey, str], float]] = {
        method: {} for method in wanted
    }
    for row in _rows(workbook, FACTORS_SHEET, FACTOR_COLUMNS):
        method = row[0]
        if method not in wanted:
            continue
        key = (
            FlowKey(
                name=str(row[3] or "").strip(),
                compartment=str(row[4] or "").strip(),
                subcompartment=str(row[5] or "").strip(),
            ),
            str(row[1] or "").strip(),
        )
        amount = row[6]
        if not isinstance(amount, (int, float)) or isinstance(amount, bool):
            raise EcoinventLciaError(
                f"{method!r} states a factor that is not a number for "
                f"{key[1]!r} and {key[0]}."
            )
        if key in out[method]:
            raise EcoinventLciaError(
                f"{method!r} states two factors for {key[1]!r} and {key[0]}."
            )
        out[method][key] = float(amount)
    for method in sorted(wanted):
        if not out[method]:
            raise EcoinventLciaError(f"The workbook has no CF rows for {method!r}.")
    return out


# --------------------------------------------------------------------------
# the two things asserted about what was read


def _without_the_suffix(
    rows: dict[tuple[FlowKey, str], float], *, method: str
) -> dict[tuple[FlowKey, str], float]:
    """A ``no LT`` method's rows under the category names its sibling uses.

    :raises EcoinventLciaError: if a category does not carry
        :data:`NO_LONG_TERM_SUFFIX`. The suffix is the only thing pairing a row
        here with a row there.
    """
    out: dict[tuple[FlowKey, str], float] = {}
    for (key, category), amount in rows.items():
        if not category.endswith(NO_LONG_TERM_SUFFIX):
            raise EcoinventLciaError(
                f"{method!r} states the category {category!r}, which does not "
                f"end in {NO_LONG_TERM_SUFFIX!r}, so nothing pairs it with a "
                f"category of the full method."
            )
        out[(key, category[: -len(NO_LONG_TERM_SUFFIX)])] = amount
    return out


def check_long_term(
    *,
    method: LciaMethodSpec,
    rows: dict[tuple[FlowKey, str], float],
    sibling_rows: dict[tuple[FlowKey, str], float],
) -> LongTermCheck:
    """That *method*'s ``no LT`` sibling is *method* minus its long-term rows.

    Four things have to hold, and each is a way the sibling could be more than a
    subtraction: every one of its categories is one of the full method's with
    ``no LT`` appended, it states no row the full method does not, it states no
    number the full method does not, and every row it drops is in a compartment
    whose name says long-term.  Where they hold, the sibling is not published
    (§2.4); where one fails, this raises and the release is somebody's to look at.
    """
    sibling_rows = _without_the_suffix(sibling_rows, method=str(method.no_long_term))
    sibling_only = sorted(
        f"{category} / {key}" for key, category in set(sibling_rows) - set(rows)
    )
    if sibling_only:
        raise EcoinventLciaError(
            f"{method.no_long_term!r} states {len(sibling_only)} rows that "
            f"{method.name!r} does not, so it is not that method minus its "
            f"long-term rows: {'; '.join(sibling_only[:5])}"
        )
    differing = [
        (key, category)
        for key, category in set(rows) & set(sibling_rows)
        if rows[(key, category)] != sibling_rows[(key, category)]
    ]
    if differing:
        key, category = differing[0]
        raise EcoinventLciaError(
            f"{method.name!r} and {method.no_long_term!r} state different "
            f"numbers for {len(differing)} rows, so the second is a second "
            f"implementation rather than a subtraction: {category!r} for "
            f"{key.name!r} in {key.compartment}/{key.subcompartment} is "
            f"{rows[(key, category)]} against "
            f"{sibling_rows[(key, category)]}."
        )
    dropped: Counter[tuple[str, str]] = Counter()
    for key, _category in set(rows) - set(sibling_rows):
        dropped[(key.compartment, key.subcompartment)] += 1
    not_long_term = sorted(
        f"{compartment}/{sub}"
        for compartment, sub in dropped
        if "long-term" not in sub.lower()
    )
    if not_long_term:
        raise EcoinventLciaError(
            f"{method.no_long_term!r} drops rows outside a long-term "
            f"compartment, so what it removes is not the long-term emissions: "
            f"{', '.join(not_long_term)}"
        )
    return LongTermCheck(
        method=method.name,
        checked_against=str(method.no_long_term),
        rows=len(rows),
        rows_in_sibling=len(sibling_rows),
        dropped_by_compartment=tuple(
            (compartment, sub, count)
            for (compartment, sub), count in sorted(
                dropped.items(), key=lambda item: (-item[1], item[0])
            )
        ),
    )


def flow_index(flows: Iterable[dict[str, Any]]) -> dict[FlowKey, str]:
    """The triple to the ecoinvent flow UUID it names.

    :raises EcoinventLciaError: if two flows share a triple. The workbook has no
        other way to name one, so a shared triple means a CF row could belong to
        either -- and it does not happen: all 9,850 flows of 3.12 have their own.
    """
    index: dict[FlowKey, str] = {}
    for flow in flows:
        context = flow.get("context") or []
        if len(context) != 2:
            raise EcoinventLciaError(
                f"Flow {flow.get('uuid')!r} has context {context!r}; the "
                "workbook names a flow by a compartment and a subcompartment, "
                "so a flow with neither cannot be reached from it."
            )
        key = FlowKey(
            name=str(flow.get("name") or "").strip(),
            compartment=str(context[0]).strip(),
            subcompartment=str(context[1]).strip(),
        )
        claimed = index.get(key)
        if claimed is not None and claimed != flow.get("uuid"):
            raise EcoinventLciaError(
                f"Flows {claimed!r} and {flow.get('uuid')!r} share the triple "
                f"{key}, which is the only name the workbook has for a flow."
            )
        index[key] = str(flow.get("uuid") or "")
    return index


def resolve(
    *,
    rows: dict[tuple[FlowKey, str], float],
    categories: dict[str, StatedCategory],
    index: dict[FlowKey, str],
) -> tuple[list[StatedFactor], dict[str, int]]:
    """The CF rows as records, against the ecoinvent flow each names.

    :raises EcoinventLciaError: if a row names a category the ``Indicators``
        sheet does not declare, or a flow the extracted list does not have.
        Neither is a matching question -- the triple is the workbook's own
        identifier and the categories are its own declarations -- so a miss is a
        release that has moved rather than a row to drop.
    """
    unknown_categories = sorted(
        {category for _key, category in rows if category not in categories}
    )
    if unknown_categories:
        raise EcoinventLciaError(
            f"{len(unknown_categories)} categories have factors and are not "
            f"declared by the Indicators sheet: {', '.join(unknown_categories[:5])}"
        )
    unresolved = sorted(
        {str(key) for key, _category in rows if key not in index}
    )
    if unresolved:
        raise EcoinventLciaError(
            f"{len(unresolved)} flow triples carry factors and name no "
            f"extracted ecoinvent flow: {'; '.join(unresolved[:5])}"
        )
    factors = [
        StatedFactor(
            category=categories[category],
            flow_uuid=index[key],
            amount=amount,
        )
        for (key, category), amount in rows.items()
    ]
    per_category: Counter[str] = Counter(
        factor.category.name or "" for factor in factors
    )
    return factors, dict(per_category)


# --------------------------------------------------------------------------
# the adapter


def _factors_payload(
    *,
    source: SourceList,
    spec: LciaSpec,
    workbook_path: Path,
    per_method: dict[str, list[StatedFactor]],
    categories: dict[str, tuple[StatedCategory, ...]],
    counts: dict[str, dict[str, int]],
    checks: list[LongTermCheck],
    flow_keys: dict[str, int],
) -> dict[str, Any]:
    """What the file holds.  The records' own shape, not a flow record's."""
    return {
        "schema_version": FACTORS_SCHEMA_VERSION,
        "source": source.key,
        "list_version": source.list_version,
        "workbook": workbook_path.name,
        "methods": [
            {
                "method": method.name,
                "categories": [
                    {
                        "category": category.name,
                        "indicator": category.impact_indicator,
                        "unit": category.reference_unit,
                        "factor_count": counts[method.name].get(category.name or "", 0),
                    }
                    for category in categories[method.name]
                ],
                "factor_count": len(per_method[method.name]),
                "flow_count": flow_keys[method.name],
                "long_term_check": next(
                    (
                        check.to_dict()
                        for check in checks
                        if check.method == method.name
                    ),
                    None,
                ),
                "factors": [
                    {
                        "flow_uuid": factor.flow_uuid,
                        "category": factor.category.name,
                        "amount": factor.amount,
                    }
                    for factor in per_method[method.name]
                ],
            }
            for method in spec.methods
        ],
    }


def fetch(source: SourceList, *, force: bool = False) -> Path:
    """The LCIA adapter for ecoinvent: the workbook's factors, as a file.

    *force* re-downloads the release rather than reading what
    ``ecoinvent_interface`` has cached.  The parse is the slow half either way --
    484,598 rows of one sheet -- so there is nothing to skip on a second run.

    :raises EcoinventLciaError: if the workbook, the extracted flows or the
        relationship between a method and its ``no LT`` sibling is not what this
        reader requires. Every one of those is a release that has changed shape,
        and each is better as a failed fetch than as a file nobody checked.
    """
    import openpyxl
    from ecoinvent_interface import EcoinventRelease, Settings
    from ecoinvent_interface.release import get_excel_lcia_file_for_version

    if source.lcia is None:  # pragma: no cover - `fetch_source_lcia` checks first
        raise EcoinventLciaError(f"{source.key} declares no lcia block.")
    spec = source.lcia

    if not source.flows_path.exists():
        raise EcoinventLciaError(
            f"The extracted flows for {source.key} are not at "
            f"{source.flows_path}, and a factor reaches a flow by naming it. "
            f"Run `{source.fetch_command}` first."
        )

    release = EcoinventRelease(Settings())
    workbook_path = get_excel_lcia_file_for_version(release, source.list_version)
    logger.info(
        "reading ecoinvent lcia workbook",
        source=source.key,
        path=str(workbook_path),
        force=force,
    )
    workbook = openpyxl.load_workbook(workbook_path, read_only=True, data_only=True)

    index = flow_index(orjson.loads(source.flows_path.read_bytes()))

    siblings = {
        method.no_long_term for method in spec.methods if method.no_long_term
    }
    rows = read_factors(
        workbook, [method.name for method in spec.methods] + sorted(siblings)
    )

    categories: dict[str, tuple[StatedCategory, ...]] = {}
    per_method: dict[str, list[StatedFactor]] = {}
    counts: dict[str, dict[str, int]] = {}
    flow_keys: dict[str, int] = {}
    checks: list[LongTermCheck] = []
    for method in spec.methods:
        categories[method.name] = read_categories(workbook, method.name)
        check_against_crosswalk(categories[method.name], method=method.name)
        by_name = {
            category.name or "": category for category in categories[method.name]
        }
        factors, counted = resolve(
            rows=rows[method.name], categories=by_name, index=index
        )
        per_method[method.name] = factors
        counts[method.name] = counted
        flow_keys[method.name] = len({key for key, _category in rows[method.name]})
        if method.no_long_term:
            checks.append(
                check_long_term(
                    method=method,
                    rows=rows[method.name],
                    sibling_rows=rows[method.no_long_term],
                )
            )

    payload = _factors_payload(
        source=source,
        spec=spec,
        workbook_path=Path(workbook_path),
        per_method=per_method,
        categories=categories,
        counts=counts,
        checks=checks,
        flow_keys=flow_keys,
    )
    spec.factors_path.write_bytes(orjson.dumps(payload, option=orjson.OPT_INDENT_2))
    for check in checks:
        logger.info(
            "checked_no_long_term_sibling",
            method=check.method,
            checked_against=check.checked_against,
            rows=check.rows,
            rows_dropped=check.dropped,
        )
    logger.info(
        "saved ecoinvent lcia factors",
        source=source.key,
        path=str(spec.factors_path),
        methods=[method.name for method in spec.methods],
        factors=sum(len(factors) for factors in per_method.values()),
    )
    return spec.factors_path


def load_factors(path: Path) -> dict[str, list[StatedFactor]]:
    """What :func:`fetch` wrote, back as records, keyed by method.

    The read side of the file, here rather than in the pass that will match these
    onto consensus flows, because the shape belongs to whoever writes it.
    """
    payload = orjson.loads(path.read_bytes())
    version = payload.get("schema_version")
    if version != FACTORS_SCHEMA_VERSION:
        raise EcoinventLciaError(
            f"{path.name} states schema_version {version!r}; this reads "
            f"{FACTORS_SCHEMA_VERSION}. Re-run the fetch."
        )
    out: dict[str, list[StatedFactor]] = defaultdict(list)
    for method in payload.get("methods") or ():
        name = str(method.get("method") or "")
        categories = {
            str(row.get("category") or ""): stated_category(
                uuid=None,
                name=str(row.get("category") or ""),
                methodology=name,
                impact_indicator=row.get("indicator"),
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
                )
            )
    return dict(out)
