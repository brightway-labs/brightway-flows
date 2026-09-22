"""Remove catalogue codes and trade names from alternative labels.

Common Chemistry and ChEBI publish, beside the systematic name, every string
anyone has filed against the CAS number: supplier grade designations (`S 100`,
`A 1`, `F 1000`), brand names with a product number (`Prifrac 2981`, `Garlon
480`, `Dowicil 100`), and database accessions (`NSC 147337`, `AKOS000118800`,
`C.I. 77120`).  The enrichment adds all of them, because nothing in either
payload distinguishes a name from a catalogue entry -- 368,720 of 2,012,182
published alternative labels are one of these three shapes.

They are not synonyms of the substance.  `S 100` does not name zinc
distearate; it names a product someone sells that contains it.  Nor are they
inert: a grade code is shared between unrelated products, and a merge once
resolved Propylene Carbonate to **Talc** because both carried a `K 3`
alternative label (see `tests/test_label_matching.py`).

Why shape and not agreement
---------------------------
The obvious alternative is to publish only names two sources agree on.  That
was measured against a full build and rejected: Common Chemistry and ChEBI
agree on 5.8% of published strings, because they use different naming
conventions rather than because the other 94% are wrong.  Requiring a second
vote removes 92% of the corpus -- taking `oxidane`, `trans-2,4-hexadienal` and
Common Chemistry's own primary name for a substance along with the grade codes
-- and 31,002 flows lose every alternative label they have.  Filtering by shape
removes 18.3% and leaves 104 flows with none.  Agreement measures vocabulary
overlap between registries; it does not measure whether a string is a name.

When the shape test is wrong
----------------------------
It is a heuristic, so it will be, and there are two ways to overrule it:

* A whole convention belongs in the patterns below.  Refrigerant, halocarbon
  and halon numbering is already exempt (`HFC-134a`, `Halon 1211`,
  `Fluorocarbon 113`, `R-600a`) -- EF 3.1 identifies 55 flows by designation
  alone and nothing else can place them (#19), so removing those would be a
  data loss rather than a cleanup.  Congener numbering (`PCB 118`) is exempt
  for the same reason, pre-emptively.  Colour Index generic names (`Acid Red
  27`, `Pigment Blue 15:3`) are exempt because a generic name identifies the
  colorant, not a product someone sells -- 480 build labels have that shape.
* A single string belongs in `data/altlabel-keep-list.json`, which a curator
  can add to without touching code, and which that file documents.
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
)
from brightway_flows.pipeline import Change, Transformer
from brightway_flows.filesystem import PACKAGE_DATA_DIR

logger = structlog.get_logger(__name__)

KEEP_LIST_FILEPATH = (
    PACKAGE_DATA_DIR / "altlabel-keep-list.json"
)

#: Database accessions and registry identifiers.  Each alternative is anchored
#: on a known prefix rather than on a general "letters then digits" shape, so
#: adding one is a deliberate act and a name that merely resembles an accession
#: is not caught.
REGISTRY_CODE = re.compile(
    r"""^(?:
        NSC[ -]?\d+ | CCRIS[ -]?\d+ | HSDB[ -]?\d+ | BRN[ -]?\d+ | MFCD\d+
        | UNII[ :-]?[0-9A-Z]{6,} | DTXSID\d+ | DTXCID\d+ | SCHEMBL\d+ | CHEMBL\d+
        | ZINC\d+ | NCGC\d+[-0-9]* | AKOS\d+ | AC1[A-Z0-9]{4,} | CID[ ]?\d+
        | EINECS[ ]?[\d-]+ | RTECS[ ]?[A-Z]{2}\d+ | C\.?I\.?[ ]?\d{4,6}
        | Epitope[ ]ID:?\d+ | Caswell[ ]No\.?[ ]?\d+ | UN[ ]?\d{4}
        | NCI-C\d+ | USAF[ ][A-Z]{1,3}-?\d+ | WLN:.* | InChI=.*
        | EPA[ ]Pesticide[ ]Chemical[ ]Code[ ]?\d+ | Pesticide[ ]Code:?[ ]?\d+
        | CAS[ -]?\d{2,7}-\d{2}-\d
    )$""",
    re.VERBOSE | re.IGNORECASE,
)

#: Supplier grade designations: up to four letters, a separator, a number.  The
#: separator is required.  Without it the pattern also matches `H2O` and every
#: other formula-shaped label, which are names.
GRADE_CODE = re.compile(r"^[A-Za-z]{1,4}[ -]\d{1,5}[A-Za-z]?$")

#: Brand name and product number: `Garlon 480`, `Polytal 4641`, `Penta 811K`.
#: Three digits are required.  Two-digit trailing numbers are how several real
#: names end -- `Tween 80`, `Vitamin B12`, `Pigment Yellow 74` -- and telling
#: those from a product number is not something this test can do.
TRADE_NAME = re.compile(r"^[A-Z][a-z]{2,}(?: [A-Z][a-z]+)? [A-Z]?\d{3,6}[A-Za-z]?$")

#: Industry designations for refrigerants, blowing agents, halons and
#: fluorocarbons.  `R` is admitted only with a hyphen: `R-600a` is isobutane as
#: a refrigerant, while `R 300` is a grade of stearic acid.
DESIGNATION = re.compile(
    r"""^(?:
        (?:HFC|HCFC|CFC|HFO|HCFO|HFE|PFC|FC|R)-\d{1,4}[a-z]{0,3}\d?
        | (?:Halon|Freon|Genetron|Forane|Suva|Arcton)[ -]?\d{3,4}[a-zA-Z]{0,2}
        | (?:Per)?[Ff]luorocarbon[ -]?\d{2,4}[a-zA-Z]{0,2}
    )$""",
    re.VERBOSE | re.IGNORECASE,
)

#: Congener numbering, which is an identity and not a product code.
CONGENER = re.compile(r"^(?:PCB|PBB|PBDE|BDE|PCDD|PCDF|PCN)[ -]?\d{1,3}$", re.IGNORECASE)

#: Colour Index generic names: an application class, a hue, and a serial number
#: (`Acid Red 27`, `Pigment Blue 15:3`, `C.I. Basic Violet 3`).  This is a
#: closed naming convention published by Colour Index International, and a
#: generic name identifies a colorant rather than a supplier's product -- the
#: same standing as refrigerant numbering above.  480 build labels have this
#: shape.  Without the exemption `GRADE_CODE` leaves them alone but
#: `strip_product_families` would take them, because `Red 27` is exactly the
#: free-standing designation that rule looks for.
COLOUR_INDEX_CLASS = (
    r"Acid|Basic|Direct|Disperse|Mordant|Pigment|Reactive|Sulphur|Sulfur|Vat|Food|Natural"
    r"|Developer|Ingrain|Solvent|Oxidation[ ]Base|Fluorescent[ ]Brightener|Azoic"
)
COLOUR_INDEX_HUE = (
    r"Yellow|Orange|Red|Violet|Blue|Green|Brown|Black|White|Grey|Gray|Pink|Purple"
)
COLOUR_INDEX = re.compile(
    r"^(?:C\.?\s?I\.?\s*)?(?:%s)\s+(?:%s)\s+\d{1,3}(?::\d{1,2})?$"
    % (COLOUR_INDEX_CLASS, COLOUR_INDEX_HUE),
    re.IGNORECASE,
)

#: A trailing parenthetical naming the substance class: `S 10 (silica)`, `R 203
#: (pigment)`, `A 1 (talc)`.  Common Chemistry appends these to disambiguate a
#: grade code that several substances share, which is a courtesy that made the
#: shape tests miss the code entirely -- 2,519 published labels are one of the
#: shapes below wearing this suffix.  The qualifier is evidence the string is a
#: grade, so it is stripped before the tests rather than after.
QUALIFIER_SUFFIX = re.compile(r"^(.*?)\s*\(([^()]{1,30})\)$")


def _shape_of(text: str) -> str | None:
    """The catalogue shape of an already-trimmed, already-unqualified string."""
    if DESIGNATION.match(text) or CONGENER.match(text) or COLOUR_INDEX.match(text):
        return None
    if REGISTRY_CODE.match(text):
        return "registry code"
    if GRADE_CODE.match(text):
        return "grade code"
    if TRADE_NAME.match(text):
        return "trade name"
    return None


def catalogue_code_kind(value: str) -> str | None:
    """Which catalogue shape *value* has, or None if it reads as a name.

    Knows nothing about the keep list: this answers what the string looks like,
    and whether to act on the answer is the transformer's decision.  Separated
    so the shape rules can be read, tested and argued about on their own.

    A string wearing a trailing class qualifier is tested twice: once whole, and
    once with the qualifier removed.  `S 10 (silica)` is a grade code and the
    parenthetical is what says so, but it also has to be tried whole first, or a
    genuine name that merely ends in a bracket would be judged on its stem.
    """
    text = value.strip()
    if not text:
        return None
    kind = _shape_of(text)
    if kind is not None:
        return kind
    qualified = QUALIFIER_SUFFIX.match(text)
    if qualified:
        stem = qualified.group(1).strip()
        if stem:
            return _shape_of(stem)
    return None


def load_keep_list(path: Path | None = None) -> set[str]:
    """Labels a curator has ruled are names, as canonical comparison keys.

    An entry without a `comment` is dropped and logged.  The file says the
    comment is mandatory, and a rule enforced nowhere is a rule that is not
    enforced -- an unexplained exemption would otherwise sit in the data
    forever with nobody able to say what it was for.
    """
    filepath = path or KEEP_LIST_FILEPATH
    if not filepath.exists():
        return set()

    payload = orjson.loads(filepath.read_bytes())
    keep: set[str] = set()
    for entry in payload.get("keep", []):
        if not isinstance(entry, dict):
            continue
        value = entry.get("value")
        comment = entry.get("comment")
        if not isinstance(value, str) or not value.strip():
            continue
        if not isinstance(comment, str) or not comment.strip():
            logger.warning(
                "altlabel keep-list entry ignored: no comment",
                value=value,
                filepath=str(filepath),
            )
            continue
        key = canonical_label_value(value)
        if key:
            keep.add(key)
    return keep


class StripCatalogueAltLabelsTransformer(Transformer):
    """Remove catalogue codes and trade names from `altLabel`."""

    name = "strip_catalogue_altlabels"
    answers_per_flow = True

    def __init__(self, keep_list_path: Path | None = None) -> None:
        # Injectable so a test can state its own exemptions, and so a caller
        # with a curated list elsewhere is not forced to edit the package.
        self._keep_list_path = keep_list_path
        self._keep: set[str] = set()

    def setup(self) -> None:
        self._keep = load_keep_list(self._keep_list_path)

    def transform(self, flows: list[Flow]) -> list[Change]:
        changes: list[Change] = []

        for flow in flows:
            uuid = flow.uuid or ""
            if not uuid:
                continue

            existing_alt = coerce_alt_labels(flow.altLabel)
            if not existing_alt:
                continue

            kept = []
            removed: list[tuple[str, str]] = []
            for label in existing_alt:
                kind = catalogue_code_kind(label.value)
                if kind is None or canonical_label_value(label.value) in self._keep:
                    kept.append(label)
                else:
                    removed.append((label.value, kind))

            if not removed:
                continue

            new_alt = dedupe_alt_labels_against_pref(
                alt_labels=kept,
                pref_label=coerce_pref_label(flow.prefLabel),
            )
            # The values are named, not counted: a curator reading the change
            # log has to be able to see what left without opening the source,
            # and this is the log they would consult before writing a keep-list
            # entry to put one back.
            listed = ", ".join(
                f"{value!r} ({kind})" for value, kind in sorted(removed)[:20]
            )
            if len(removed) > 20:
                listed += f", and {len(removed) - 20} more"
            changes.append(Change(
                uuid,
                "altLabel",
                [x.to_dict() for x in new_alt],
                comment=f"Removed {len(removed)} catalogue altLabel value(s): {listed}",
            ))

        return changes
