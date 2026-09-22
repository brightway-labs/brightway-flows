"""Utilities for JSON-LD style SKOS labels."""

from __future__ import annotations

import re

from dataclasses import dataclass
from functools import lru_cache
from html import unescape
from typing import Any

#: How many distinct strings the label-normalisation caches below remember.
#:
#: A build calls `strip_markup` 36 million times and `canonical_label_value` 26
#: million, over a vocabulary of a few hundred thousand distinct strings: the
#: same synonym is normalised again for every flow that carries it, for every
#: transformer that reads it, and once more per merged source list.  Both are
#: pure functions of one string, so the repeat calls can be answered from a
#: table rather than recomputed.
#:
#: Bounded rather than unbounded because the input is source data and a cache
#: that can only grow is a leak waiting for a list with a million synonyms.  The
#: limit is set well above the vocabulary a build actually has, so in practice
#: nothing is evicted; if a future list exceeds it the caches degrade to doing
#: the work again, which is what they did before.
_LABEL_CACHE_SIZE = 1 << 20


@dataclass(frozen=True)
class Label:
    value: str
    language: str = "en"
    source: Any = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "@value": self.value,
            "@language": self.language,
        }
        if self.source not in (None, "", [], {}):
            payload["source"] = self.source
        return payload


#: Source names carry presentation markup -- `<span class="text-smallcaps">D</span>`
#: from CAS Common Chemistry, `<i>`/`<sub>`/`<sup>` from ChEBI and PubChem.  It is
#: formatting, not part of the name, and it must not reach a stored or published
#: label: downstream consumers read `prefLabel` and `altLabel` as text.
#:
#: Matching is deliberately *tag-shaped* -- `<` then a name character -- rather
#: than "anything between angle brackets".  `<[^>]+>` also matched `<->`, which
#: in a carbohydrate name is a glycosidic linkage:
#: `beta-D-Fruf-(2<->1)-alpha-D-Glcp` is sucrose, and stripping turned it into
#: `beta-D-Fruf-(21)-alpha-D-Glcp`.  Eleven published alt labels were affected.
_MARKUP_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_MARKUP_TAG = re.compile(
    r"""
    </?[A-Za-z][^<>]*>   # an element: <i>, </span>, <span class="...">, <br/>
    |
    <[!?][^>]*>          # a declaration or processing instruction: <?xml ...?>
    """,
    re.VERBOSE,
)


@lru_cache(maxsize=_LABEL_CACHE_SIZE)
def strip_markup(text: str) -> str:
    """Remove XML/HTML markup and resolve character references.

    Tags are dropped rather than escaped: the letter inside a smallcaps span is
    the meaningful part of a name like `D-Glucitol`.

    References are resolved after tags are removed, not before, so an escaped
    `&lt;i&gt;` stays the literal text it was written as instead of becoming a
    tag and then vanishing.  Resolving them at all is the difference between
    publishing `N&#39;-nitrosomethylharnstoff` and `N'-nitrosomethylharnstoff`.
    """
    without_comments = _MARKUP_COMMENT.sub("", text)
    return unescape(_MARKUP_TAG.sub("", without_comments))


@lru_cache(maxsize=_LABEL_CACHE_SIZE)
def canonical_label_value(text: str) -> str:
    """Case/whitespace-insensitive key used for label equality."""
    return " ".join(strip_markup(text).split()).lower()


def coerce_label(value: Any, *, default_source: str) -> Label | None:
    """Convert legacy/raw label payloads to Label."""
    if isinstance(value, str):
        text = strip_markup(value).strip()
        if not text:
            return None
        return Label(value=text, source=default_source)

    if isinstance(value, dict):
        text = value.get("@value")
        if text is None:
            text = value.get("value")
        if not isinstance(text, str) or not text.strip():
            return None
        source = value.get("source")
        language = value.get("@language")
        if language is None:
            language = value.get("@lang")
        if language is None:
            language = value.get("lang_code")
        return Label(
            value=strip_markup(text).strip(),
            language=language.strip() if isinstance(language, str) and language.strip() else "en",
            source=(
                source
                if source not in (None, "", [], {})
                else default_source
            ),
        )

    return None


def coerce_pref_labels(value: Any) -> list[Label]:
    if isinstance(value, list):
        labels: list[Label] = []
        for item in value:
            parsed = coerce_label(item, default_source="legacy_prefLabel")
            if parsed is not None:
                labels.append(parsed)
        return dedupe_labels(labels)

    parsed = coerce_label(value, default_source="legacy_prefLabel")
    if parsed is None:
        return []
    return [parsed]


def coerce_pref_label(value: Any) -> Label | None:
    labels = coerce_pref_labels(value)
    return labels[0] if labels else None


def coerce_alt_labels(value: Any) -> list[Label]:
    if isinstance(value, list):
        labels: list[Label] = []
        for item in value:
            parsed = coerce_label(item, default_source="legacy_altLabel")
            if parsed is not None:
                labels.append(parsed)
        return dedupe_labels(labels)

    parsed = coerce_label(value, default_source="legacy_altLabel")
    if parsed is None:
        return []
    return [parsed]


def dedupe_labels(labels: list[Label]) -> list[Label]:
    """Deduplicate by (value, language), preserving first occurrence."""
    out: list[Label] = []
    seen: set[tuple[str, str]] = set()
    for label in labels:
        text_key = canonical_label_value(label.value)
        lang_key = label.language.strip().lower()
        key = (text_key, lang_key)
        if not text_key or key in seen:
            continue
        seen.add(key)
        out.append(label)
    return out


def dedupe_alt_labels_against_pref(
    *,
    alt_labels: list[Label],
    pref_label: Label | None,
) -> list[Label]:
    """Deduplicate alt labels and drop values matching prefLabel."""
    deduped = dedupe_labels(alt_labels)
    if pref_label is None or not pref_label.value.strip():
        return deduped
    pref_key = canonical_label_value(pref_label.value)
    if not pref_key:
        return deduped
    return [
        label
        for label in deduped
        if canonical_label_value(label.value) != pref_key
    ]


def flow_label_value(flow: Any) -> str:
    """Canonical display label for a flow or flow object, from prefLabel only.

    Accepts a record or a plain mapping: the webapps read rows back from SQLite
    and JSON, where they are dicts, while the ETL passes record objects.
    """
    raw = (
        flow.get("prefLabel")
        if isinstance(flow, dict)
        else getattr(flow, "prefLabel", None)
    )
    labels = coerce_pref_labels(raw)
    if labels:
        for label in labels:
            if label.language.lower().startswith("en"):
                return label.value
        return labels[0].value
    return ""
