"""How the review app says a machine key or a resolved URL out loud.

Three jobs of the same shape.  The pipeline stores identity -- a ChemROF IRI, a
cross-reference URL expanded from a ChEBI xref, an ENVO accession -- and a page
has to name it in words.  Every reader below works off a registry that already
exists, `domain.vocabulary` for the terms, `integrations.chebi.XREF_URL_PREFIXES`
for the URLs and the two anchor snapshots for the classes ENVO, GET and AGROVOC
publish, rather than carrying a second copy of it: a term, a prefix or an anchor
added there is named here without anybody remembering this module.

Nothing here decides anything.  A key the registries do not know is still
printed, split into words or reduced to its host, because "the app has no name
for this" and "there is nothing here" are different claims and only one of them
is true.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any
from urllib.parse import urlparse

from brightway_flows.domain import vocabulary
from brightway_flows.integrations.chebi import XREF_URL_PREFIXES


def local_name(key: Any) -> str:
    """The last segment of a CURIE or an IRI: `xkos:sourceConcept` is `sourceConcept`.

    Every reader here and in `filters` asks for a term by its local name rather
    than by one of its two spellings.  `concept_associations` is keyed with
    CURIEs, and a database built before that change carries expanded IRIs; the
    app reads whichever database is in the data directory.
    """
    return str(key).rsplit("#", 1)[-1].rsplit("/", 1)[-1].rsplit(":", 1)[-1]


#: Words that are not capitalised, they are spelled.  Applied per word, so
#: `ISOMERIC_SMILES_STRING` reads "Isomeric SMILES string" and the CHEMINF
#: accession behind `CAS_REGISTRY_NUMBER` reads "CAS registry number" -- which
#: is the whole reason this goes through the term registry rather than through
#: the IRI's last segment, `CHEMINF_000446`.
_SPELLED: dict[str, str] = {
    "cas": "CAS",
    "ec": "EC",
    "id": "ID",
    "inchi": "InChI",
    "inchi2d": "InChI2D",
    "iri": "IRI",
    "iupac": "IUPAC",
    "smiles": "SMILES",
    "uuid": "UUID",
}


def _words(text: str) -> list[str]:
    """The words in `isomeric_smiles_string`, `isomericSmilesString`, `half-life`.

    The camel-case split is skipped for a name that is already all upper case,
    which is what a `Term` member's name is.  Run over `INCHI2D_KEY_STRING` it
    finds a boundary between the digit and the `D` and yields "Inchi2 d key
    string" -- a word break inside an acronym, which is the one thing this is
    supposed to get right.
    """
    spaced = (
        re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text)
        if any(character.islower() for character in text)
        else text
    )
    return [word for word in re.split(r"[\s_-]+", spaced) if word]


def _humanise(text: str) -> str:
    """A sentence-cased phrase: one capital at the front, acronyms spelled."""
    words = _words(text)
    if not words:
        return ""
    written = [
        _SPELLED.get(word.lower())
        or (word.lower().capitalize() if index == 0 else word.lower())
        for index, word in enumerate(words)
    ]
    return " ".join(written)


@lru_cache(maxsize=1)
def _term_by_key() -> dict[str, vocabulary.Term]:
    """Every declared term, under both spellings a stored key can use.

    Keyed by the full IRI and by the CURIE, and deliberately not by the local
    name: two namespaces may declare the same local name, and a lookup that
    guessed between them would rename a property rather than fail to name it.
    """
    keys: dict[str, vocabulary.Term] = {}
    for term in vocabulary.Term:
        keys[vocabulary.iri(term)] = term
        keys[vocabulary.curie(term)] = term
    return keys


def predicate_label(key: Any) -> str:
    """A properties-table predicate as a person reads it.

    `http://w3id.org/chemrof/molecular_formula` is "Molecular formula" and
    `http://semanticscience.org/resource/CHEMINF_000446` is "CAS registry
    number" -- the second only because the term registry knows what that
    accession is.  A key nothing declares (`isotope_lookup`, written by the
    element enrichment as a working record rather than as a published term) is
    split into its words and left otherwise alone.
    """
    text = str(key or "").strip()
    if not text:
        return ""
    term = _term_by_key().get(text)
    return _humanise(term.name if term is not None else local_name(text))


def predicate_term(key: Any) -> str:
    """The same predicate as the vocabulary writes it: `chemrof:molecular_formula`.

    Shown beside the label rather than instead of it.  The label is for
    reading; this is what a curator quotes in an issue and what the published
    document actually carries, and a page that dropped it would be asking them
    to reconstruct the IRI from an English phrase.
    """
    text = str(key or "").strip()
    term = _term_by_key().get(text)
    return vocabulary.curie(term) if term is not None else text


#: What to call the site behind a cross-reference URL.  Keyed by the same
#: prefixes `integrations.chebi` expands an xref with, so the two cannot drift;
#: `tests/test_flow_object_page.py` fails if a prefix is added there without a
#: name here.
#:
#: The three below are minted outside that table -- by `enrich_references` for
#: a PubChem compound and for the registries PubChem cross-references, among
#: them Wikidata, and by the isotope enrichment for ChemLin -- and are listed
#: with it because a reader does not care which pass recorded a link.
_RESOURCE_NAMES: dict[str, str] = {
    "chebi": "ChEBI",
    "cas": "CAS Common Chemistry",
    "kegg.compound": "KEGG",
    "kegg.drug": "KEGG",
    "hmdb": "HMDB",
    "drugbank": "DrugBank",
    "chemspider": "ChemSpider",
    "lipidmaps": "LIPID MAPS",
    "metacyc.compound": "MetaCyc",
    "pubmed": "PubMed",
    "wikipedia.en": "Wikipedia",
}

_EXTRA_PREFIXES: tuple[tuple[str, str], ...] = (
    ("https://pubchem.ncbi.nlm.nih.gov/", "PubChem"),
    ("https://www.chemlin.org", "ChemLin"),
    ("https://www.wikidata.org/wiki/", "Wikidata"),
)


@lru_cache(maxsize=1)
def _resource_prefixes() -> tuple[tuple[str, str], ...]:
    """(URL prefix, resource name), longest prefix first.

    Longest first because two prefixes can nest: ChEBI's own search URL and the
    EBI host it sits on would both match, and the specific one is the answer.
    """
    pairs = [
        (prefix, _RESOURCE_NAMES[key])
        for key, prefix in XREF_URL_PREFIXES.items()
        if key in _RESOURCE_NAMES
    ]
    pairs.extend(_EXTRA_PREFIXES)
    return tuple(sorted(pairs, key=lambda pair: len(pair[0]), reverse=True))


def resource_name(url: Any) -> str:
    """Which resource a known URL points at: "ChEBI", "PubChem", "Wikipedia".

    Matched on the prefix the pipeline built the URL from, so the answer is the
    database that was actually cross-referenced rather than whichever host
    happens to serve it.  Anything unmatched falls back to the host, which for
    the URLs PubChem supplies for its own external identifiers is the only name
    there is.  Something that is not a URL at all -- a ChEBI xref whose prefix
    has no expansion, recorded as `Beilstein:1234` -- keeps its prefix.
    """
    text = str(url or "").strip()
    if not text:
        return ""
    for prefix, name in _resource_prefixes():
        if text.startswith(prefix):
            return name
    host = urlparse(text).netloc
    if host:
        return host.removeprefix("www.")
    return text.split(":", 1)[0] if ":" in text else ""


#: The three vocabularies whose classes are cited by accession rather than by
#: name.  `ENVO_01000892` is an identifier, not a word, and the two snapshots
#: below are where this project already keeps what each one is called.
_ANCHOR_GROUPS = ("envo", "get", "agrovoc")


@lru_cache(maxsize=1)
def _anchor_labels() -> dict[str, str]:
    """Every ENVO, GET and AGROVOC class this project cites, IRI to label.

    Read from the two anchor snapshots rather than from a table of our own:
    those files exist because an accession is eight digits and a typo still
    resolves, so they already hold the label the authority publishes for every
    class the land and water taxonomies name.  A third copy of it would be a
    third thing to keep right.

    A missing snapshot is an empty mapping rather than an error.  Both files are
    package data and ship with the wheel, but a page that cannot name a class is
    a page showing an accession, and a page that raises is no page at all.
    """
    from brightway_flows.domain import land_use_anchors, materials

    found: dict[str, str] = {}
    for snapshot in (land_use_anchors.anchor_snapshot, materials.anchor_snapshot):
        try:
            payload = snapshot()
        except FileNotFoundError:
            continue
        for group in _ANCHOR_GROUPS:
            entries = payload.get(group)
            if not isinstance(entries, dict):
                continue
            for entry in entries.values():
                if not isinstance(entry, dict):
                    continue
                iri, label = entry.get("iri"), entry.get("label")
                if isinstance(iri, str) and isinstance(label, str) and label.strip():
                    found[iri] = label.strip()
    return found


def type_label(iri: Any) -> str:
    """What a flow object's `@type` is called, in words.

    Three registries in turn, because the types come from three places and only
    one of them spells its classes out.  A ChemROF or Brightway class is named
    by `predicate_label` from its own term registry -- `NeutralMolecule` reads
    "Neutral molecule".  An ENVO, GET or AGROVOC class is named by the
    authority, through the anchor snapshots: `ENVO_01000892` is "anthropised
    terrestrial biome", and the accession is not something a reader can be
    expected to hold in their head.  Anything else keeps its own text.
    """
    text = str(iri or "").strip()
    if not text:
        return ""
    return _anchor_labels().get(text) or predicate_label(text)
