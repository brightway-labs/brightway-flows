"""Remove supplier product families from the alternative labels of one object.

`Silicon Dioxide` carries 4,003 alternative labels, 3.1% of every synonym in
the list on one object, and they are almost entirely commercial (#27).  173
begin `Snowtex`, 126 `Aerosil`, 75 `Nipsil`.  `strip_catalogue_altlabels`
removes 38% of what Common Chemistry supplied for this substance and leaves the
rest, because its shapes are per-label and these are not per-label problems:
`Snowtex 30` is four characters short of `S 100`, and `Aerosil R 300` is a
brand token followed by a grade that no anchored prefix list will ever contain.
There is an open-ended supply of brand tokens and enumerating them is not a
strategy.

What separates them is not the token but its *repetition*: 173 labels on one
object beginning with the same word is a supplier catalogue, not a naming
history.  A chemical vocabulary does not behave that way.

Why not a chemical-word gate
----------------------------
The obvious formulation -- strip a repeated leading token unless the token is a
chemical word -- was measured against the build and does not hold.  Token
identity is the wrong axis in both directions: `Methyl Violet 10B` and `Pigment
Blue 15:3` lead with chemical words and are product designations, while
`Nissan` leads 56 different objects because a supplier's catalogue crosses
substances.  Cross-object spread fails for the same reason, and additionally
spares `R` (103 objects), `S` (74) and `A` (73), which are grade prefixes
rather than vocabulary.

The axis that does separate them is what the number is doing.  In a name the
digits are bound into the chemistry by hyphens and commas -- `Sodium
2-mercaptopyridine 1-oxide`, `Disodium 1-hydroxyethane-1-diphosphonate`.  In a
product code they dangle -- `Snowtex 30`, `Nissan Nonion NS 202`, `Admafine SC
1500SMJ`.  So the test is: a free-standing designation at the end, no locants
anywhere, and enough siblings on the same object to establish a family.

Why the size gate
-----------------
`Tween 80` and `Vitamin B12` end in free-standing designations and are names.
The distribution is what makes them separable: the median object carries 9
alternative labels and the mean 17, while the 96 objects above 100 hold 23.9%
of every synonym in the list.  Running only above `MIN_OBJECT_LABELS` confines
the rule to the head of the distribution -- cheap bulk industrial solids with
large supplier catalogues behind one CAS number -- where a repeated leading
token has no innocent reading.  It is a scope gate, not a quality signal, and
it is the reason this is a second transformer rather than more patterns in the
first.

Where shape genuinely cannot decide
----------------------------------
Some names are the same shape as a product code and no rule will separate them.
Dyes are the clear case: `Ponceau 4R` is a name and `Acetoquinone Blue R` is a
product, and the strings do not differ.  Surfactant series are another --
`Tween 20`, `Polysorbate 20`, `Laureth 9`.  For these a register is consulted
rather than a pattern: ChEBI at run time, and the public part of the Colour
Index in `data/colour-index-names.json`.  Corroboration is only ever allowed to
keep a label, never to publish one, which is what makes it safe here and unsafe
as the primary filter (`strip_catalogue_altlabels` records that measurement).
It rescues 13 labels from the current build, all of them names.

Two effects are known and deliberate.  Single-token designations that lead with
digits (`03CAL`, `165MPJ`, `1085G`) are untouched: they have no family and no
tail to read.  And `Methyl Violet 10B` is in no open register -- not ChEBI, not
Wikidata -- so it survives on the size gate alone, crystal violet carrying 96
labels against a threshold of 100.  A string in that position belongs in
`altlabel-keep-list.json`.
"""

from __future__ import annotations

import re
from pathlib import Path

import orjson
import structlog

from brightway_flows.domain.flow import Flow
from brightway_flows.domain.labels import (
    canonical_label_value,
    coerce_alt_labels,
    coerce_pref_label,
    dedupe_alt_labels_against_pref,
    flow_label_value,
)
from brightway_flows.pipeline import Change, Transformer
from brightway_flows.transformers.strip_catalogue_altlabels import (
    COLOUR_INDEX,
    CONGENER,
    DESIGNATION,
    load_keep_list,
)
from brightway_flows.filesystem import PACKAGE_DATA_DIR

logger = structlog.get_logger(__name__)

COLOUR_INDEX_NAMES_FILEPATH = (
    PACKAGE_DATA_DIR / "colour-index-names.json"
)

#: Only objects at or above this many alternative labels are considered.  100 is
#: the knee of the distribution measured in #27: 96 objects, 23.9% of all
#: synonyms.  Below it a repeated leading token is as likely to be a naming
#: convention as a catalogue.
MIN_OBJECT_LABELS = 100

#: How many labels must share a leading token before the group reads as a
#: supplier family.  Five is deliberately conservative -- at this setting the
#: rule takes 7,838 labels across 66 objects, and no name corroborated by ChEBI
#: or Wikidata is among them.
MIN_FAMILY_SIZE = 5

#: A trailing token that is a free-standing designation: an optional short
#: letter prefix, then a digit, then anything short and alphanumeric.  `30`,
#: `R 300`, `1500SMJ`, `1-50`, `18-8749.01`.
DESIGNATION_TOKEN = re.compile(r"^[A-Za-z]{0,4}-?\d[\dA-Za-z]*(?:[.\-:/][\dA-Za-z]+)*$")

#: Digits bound into a chemical morpheme -- a locant, a stereo descriptor, a
#: ring position.  One anywhere in the label means the digits are doing
#: chemistry and the label is a name.
#:
#: What binds them is adjacency to *lower-case* chemistry (`2-mercaptopyridine`,
#: `pyridine-1-oxide`) or a comma between bare digits (`1,1-`, `2,4,6-`).  The
#: case matters: a hyphen between digits is a product range (`Cataloid S 1-50`,
#: `Grace Davison SP 18-8749.01`) and an upper-case suffix is a grade
#: (`Ludox HS-40`, `Snowtex 1PA-ST`), so neither may count as a locant.
LOCANT = re.compile(r"\d,\d|\d-[a-z]|[a-z]-\d|\d['’]|[αβγδ]")

#: Longer than any grade designation and into the territory of formulae and
#: registry strings, which other rules own.
MAX_DESIGNATION_LENGTH = 14


def load_colour_index_names(path: Path | None = None) -> set[str]:
    """Colorant names carrying a Colour Index identifier, as comparison keys.

    A dye common name and a dye trade name have the same shape -- a colour word
    and a short strength code -- so no shape test separates `Ponceau 4R` from
    `Acetoquinone Blue R`, and a register has to.  See the file's `description`
    for what it covers and what it is known to miss.
    """
    filepath = path or COLOUR_INDEX_NAMES_FILEPATH
    if not filepath.exists():
        return set()
    payload = orjson.loads(filepath.read_bytes())
    keys: set[str] = set()
    for value in payload.get("names", []):
        if isinstance(value, str) and value.strip():
            key = canonical_label_value(value)
            if key:
                keys.add(key)
    return keys


def load_chebi_names() -> set[str]:
    """Every ChEBI label and synonym, as comparison keys.

    Corroboration is only ever allowed to *keep* a label here, which is why
    consulting ChEBI is safe in a way that the rejected "publish only what two
    sources agree on" rule was not (see `strip_catalogue_altlabels`).  That rule
    used agreement to decide what may be published and lost 92% of the corpus;
    this uses it to overrule a heuristic, and the 13 labels it rescues from the
    current build -- `Ponceau 4R`, `Tween 20`, `Tween 60`, `Polysorbate 20`,
    `Laureth 4`, `Laureth 9` among them -- are all names.

    A missing ChEBI download is a degraded run, not a failed one: the family
    rule still works without it and the keep list still overrules it, so this
    warns rather than raising.
    """
    try:
        from brightway_flows.integrations.chebi import load_chebi_index

        index = load_chebi_index()
    except FileNotFoundError:
        logger.warning(
            "strip_product_families: ChEBI unavailable, corroboration disabled"
        )
        return set()

    keys: set[str] = set()
    for record in index.get("records", {}).values():
        label = record.get("label")
        if isinstance(label, str) and label.strip():
            key = canonical_label_value(label)
            if key:
                keys.add(key)
        for synonym in record.get("synonyms", []):
            if isinstance(synonym, str) and synonym.strip():
                key = canonical_label_value(synonym)
                if key:
                    keys.add(key)
    return keys


def is_product_designation(value: str) -> bool:
    """Whether *value* ends in a free-standing designation and carries no chemistry.

    Two tokens minimum: a bare designation on its own is `strip_catalogue_altlabels`'
    business, and this rule needs something for the designation to hang off.
    """
    text = value.strip()
    if not text or LOCANT.search(text):
        return False
    tokens = text.split()
    if len(tokens) < 2:
        return False
    last = tokens[-1].strip(",;.")
    if len(last) > MAX_DESIGNATION_LENGTH or not any(c.isdigit() for c in last):
        return False
    return bool(DESIGNATION_TOKEN.match(last))


def family_token(value: str) -> str:
    """The leading token a family is grouped on, case- and punctuation-folded."""
    tokens = value.strip().split()
    return tokens[0].strip(",;:.()[]").lower() if tokens else ""


def is_exempt_convention(value: str) -> bool:
    """Whether *value* belongs to a published designation convention."""
    text = value.strip()
    return bool(
        DESIGNATION.match(text) or CONGENER.match(text) or COLOUR_INDEX.match(text)
    )


class StripProductFamiliesTransformer(Transformer):
    """Remove repeated supplier product families from `altLabel`."""

    name = "strip_product_families"
    answers_per_flow = True

    def __init__(
        self,
        *,
        keep_list_path: Path | None = None,
        colour_index_path: Path | None = None,
        use_chebi: bool = True,
        min_object_labels: int = MIN_OBJECT_LABELS,
        min_family_size: int = MIN_FAMILY_SIZE,
    ) -> None:
        # Thresholds are injectable so a test can state a two-label family
        # without inventing a hundred-label fixture, and so the gate can be
        # lowered in a trial run without editing the package.  `use_chebi` is
        # off in tests that have no business loading a 49 MB ontology to decide
        # whether `Snowtex 30` is a brand.
        self._keep_list_path = keep_list_path
        self._colour_index_path = colour_index_path
        self._use_chebi = use_chebi
        self._min_object_labels = min_object_labels
        self._min_family_size = min_family_size
        self._keep: set[str] = set()
        self._corroborated: set[str] = set()

    def setup(self) -> None:
        self._keep = load_keep_list(self._keep_list_path)
        self._corroborated = load_colour_index_names(self._colour_index_path)
        if self._use_chebi:
            self._corroborated |= load_chebi_names()

    def _protected(self, value: str) -> bool:
        key = canonical_label_value(value)
        return key in self._keep or key in self._corroborated

    def transform(self, flows: list[Flow]) -> list[Change]:
        changes: list[Change] = []

        for flow in flows:
            uuid = flow.uuid or ""
            if not uuid:
                continue

            existing_alt = coerce_alt_labels(flow.altLabel)
            if len(existing_alt) < self._min_object_labels:
                continue

            # The object's own name is not a brand.  Without this, `Silicon` on
            # `Silicon Dioxide` would be read as a supplier token the moment
            # five `Silicon <number>` labels turned up.
            own_words = {
                word.strip("(),").lower()
                for word in flow_label_value(flow).split()
                if word.strip("(),")
            }

            families: dict[str, list[int]] = {}
            for position, label in enumerate(existing_alt):
                value = label.value
                if is_exempt_convention(value) or self._protected(value):
                    continue
                if not is_product_designation(value):
                    continue
                token = family_token(value)
                if not token or token in own_words:
                    continue
                families.setdefault(token, []).append(position)

            doomed: set[int] = set()
            removed_by_family: dict[str, list[str]] = {}
            for token, positions in families.items():
                if len(positions) < self._min_family_size:
                    continue
                doomed.update(positions)
                removed_by_family[token] = [existing_alt[p].value for p in positions]

            if not doomed:
                continue

            kept = [
                label for position, label in enumerate(existing_alt)
                if position not in doomed
            ]
            new_alt = dedupe_alt_labels_against_pref(
                alt_labels=kept,
                pref_label=coerce_pref_label(flow.prefLabel),
            )
            # Families are named with their size and one example rather than
            # every value: at 173 members a full list is unreadable, and the
            # curator deciding whether `Snowtex` was a mistake needs the shape
            # of the group, not its enumeration.
            summary = ", ".join(
                f"{token!r} ({len(values)}, e.g. {sorted(values)[0]!r})"
                for token, values in sorted(removed_by_family.items())
            )
            changes.append(Change(
                uuid,
                "altLabel",
                [x.to_dict() for x in new_alt],
                comment=(
                    f"Removed {len(doomed)} product-family altLabel value(s) "
                    f"from {len(removed_by_family)} famil(y/ies): {summary}"
                ),
            ))

        return changes
