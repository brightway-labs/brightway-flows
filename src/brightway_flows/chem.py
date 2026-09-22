"""RDKit-based chemical property helpers."""

import logging
import re
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Iterator, Optional

from rdkit import Chem, rdBase
from rdkit.Chem import Descriptors, rdMolDescriptors
from rdkit.Chem.Draw import rdMolDraw2D
from rdkit.Chem.inchi import InchiToInchiKey, MolFromInchi, MolToInchi

RDKIT_PYTHON_LOGGER_NAME = "rdkit"

#: How many distinct structure strings the caches in this module remember.
#:
#: Reading a structure is the most expensive thing a build does -- 484,000
#: `MolToInchi` calls and 125,000 `MolFromInchi` calls on a three-source run,
#: 105 of the 431 seconds the transformer chain spends -- and almost all of it
#: is the same handful of strings read again.  A substance's SMILES is parsed
#: once per flow that carries it, once more by each of the three RDKit
#: transformers, and again for every source list the merge enriches.  Parsing a
#: string is a pure function of that string, so the repeats are answerable from
#: a table.
#:
#: Bounded, like the label caches, because the keys come from source data: a
#: cache that can only grow is a leak waiting for a larger list.  The limit sits
#: far above the number of distinct structures a build has (a few tens of
#: thousands), so nothing is evicted in practice.
_STRUCTURE_CACHE_SIZE = 1 << 18

# RDKit prefixes every message with its own local-time stamp; we add a UTC one.
_RDKIT_TIMESTAMP_PREFIX = re.compile(r"^\[\d{2}:\d{2}:\d{2}\]\s*")

_rdkit_log_path: Optional[Path] = None
_flow_label: ContextVar[str] = ContextVar("rdkit_flow_label", default="")


class _RDKitLogFileHandler(logging.Handler):
    """Append RDKit messages to the configured log file, or drop them.

    Each line is prefixed with a timestamp and the flow label set by the
    enclosing :func:`capture_rdkit_logs` block, for easy scanning.
    """

    def emit(self, record: logging.LogRecord) -> None:
        if _rdkit_log_path is None:
            return
        message = _RDKIT_TIMESTAMP_PREFIX.sub("", record.getMessage()).strip()
        if not message:
            return
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            with open(_rdkit_log_path, "a", encoding="utf-8") as fh:
                fh.write(f"{ts}\t{_flow_label.get()}\t{message}\n")
        except Exception:
            self.handleError(record)


def _redirect_rdkit_logging() -> None:
    """Route every RDKit message into a handler we own, and never to stderr.

    RDKit writes to C++ streams by default, and ``rdBase.CaptureErrorLog``
    intercepts only the *error* stream — warnings such as ``Proton(s)
    added/removed`` (from ``MolToInchi``) and ``Problems encountered parsing
    Mol data`` still reached stderr.  ``LogToPythonLogger`` sends all levels to
    the ``rdkit`` logger instead, whose default stderr handler ``rdkit``
    installs on import we remove here.  Levels must stay *enabled* for messages
    to reach that logger at all, so disabling them is no longer how we go quiet.
    """
    logger = logging.getLogger(RDKIT_PYTHON_LOGGER_NAME)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
    logger.addHandler(_RDKitLogFileHandler())
    logger.setLevel(logging.WARNING)
    logger.propagate = False

    rdBase.LogToPythonLogger()
    rdBase.EnableLog("rdApp.error")
    rdBase.EnableLog("rdApp.warning")
    rdBase.DisableLog("rdApp.info")
    rdBase.DisableLog("rdApp.debug")


_redirect_rdkit_logging()


def configure_rdkit_logging(log_path: Path) -> None:
    """Set the file that RDKit messages are written to, clearing it first.

    Call this once per pipeline run (from a transformer's ``setup()``).  Both
    the pre- and post-consensus transformers call it, but since all ``setup()``
    calls complete before any ``transform()`` call, the double-clear is safe.
    Until this is called, RDKit messages are discarded rather than printed.
    """
    global _rdkit_log_path
    _rdkit_log_path = log_path
    log_path.write_text("", encoding="utf-8")


@contextmanager
def capture_rdkit_logs(flow_label: str) -> Iterator[None]:
    """Label RDKit messages emitted inside the block with *flow_label*."""
    token = _flow_label.set(flow_label)
    try:
        yield
    finally:
        _flow_label.reset(token)


def mol_from_smiles(smiles: str) -> Optional[Chem.Mol]:
    try:
        return Chem.MolFromSmiles(smiles)
    except Exception:
        return None


def mol_from_inchi(inchi: str) -> Optional[Chem.Mol]:
    try:
        return MolFromInchi(inchi)
    except Exception:
        return None


def canonical_smiles(mol: Chem.Mol) -> str:
    try:
        return Chem.MolToSmiles(mol) or ""
    except Exception:
        return ""


def graph_only_smiles(mol: Chem.Mol) -> str:
    """The canonical SMILES with stereochemistry and isotopic labels removed.

    ChemROF defines `smiles_string` as "a string encoding of a molecular graph,
    no chiral or isotopic information", and declares `isomeric_smiles_string`
    for the rest.  This is what the first of those slots is allowed to hold.

    Charge survives, and should: `[O-][O+]=O` is ozone's graph, not a statement
    about its stereochemistry.  A deuterium becomes an explicit hydrogen, which
    is the same molecular graph with the isotope forgotten -- which is the point.
    """
    try:
        return Chem.MolToSmiles(mol, isomericSmiles=False) or ""
    except Exception:
        return ""


def mol_inchi(mol: Chem.Mol) -> Optional[str]:
    try:
        return MolToInchi(mol)
    except Exception:
        return None


def inchikey(mol: Chem.Mol) -> Optional[str]:
    try:
        inchi_str = MolToInchi(mol)
        return InchiToInchiKey(inchi_str) if inchi_str else None
    except Exception:
        return None


#: The InChI stereo layers that state a *relative* or *racemic* arrangement
#: rather than an absolute one.  ``/s1`` is absolute and is not here.
RELATIVE_STEREO_LAYERS = ("/s2", "/s3")


def states_relative_stereochemistry(inchi: str) -> bool:
    """Whether *inchi* describes stereochemistry standard InChI cannot express.

    ``/s2`` is relative stereochemistry -- "these centres are arranged so with
    respect to each other, in either mirror image" -- and ``/s3`` is racemic.
    Standard InChI has no layer for either, so CAS Common Chemistry writes them
    as *non-standard* InChI, and 40 of the 75 non-standard keys in its cache
    carry ``/s2``:

        (2RS,4SR)-2-methyl-4-propyl-1,3-oxathiane
            InChI=1/C8H16OS/c1-3-4-8-5-6-9-7(2)10-8/h7-8H,3-6H2,1-2H3/t7-,8+/s2

    This matters because RDKit does not refuse such a string.  It reads it and
    quietly returns *one* enantiomer, so a round trip through
    :func:`standard_inchikey_from_inchi` would turn "either mirror image" into
    "specifically this one" -- inventing exactly the stereochemistry #42 is
    about.  So the layer is tested for before any conversion is attempted.
    """
    return any(layer in str(inchi or "") for layer in RELATIVE_STEREO_LAYERS)


#: The InChI layers that state a three-dimensional arrangement: ``/t`` for
#: tetrahedral centres, ``/b`` for double bonds.  ``/m`` and ``/s`` qualify a
#: ``/t`` that is already there and never appear without one.
STEREOCHEMISTRY_LAYER_PREFIXES = ("t", "b")


def states_stereochemistry(inchi: str) -> bool:
    """Whether *inchi* states a three-dimensional arrangement at all.

    A key whose second block is not ``UHFFFAOY`` is usually taken to mean "this
    substance has a stereochemistry", and for almost every record that is true.
    It is not true in general, because that block hashes the isotopic layer as
    well:

        zinc-65    InChI=1S/Zn/i1+0    HCHKCACWOHOZIP-IGMARMGPSA-N
        zinc       InChI=1S/Zn         HCHKCACWOHOZIP-UHFFFAOYSA-N

    A single atom has no arrangement to state, and ``IGMARMGP`` is the signature
    of "isotopic shift of zero" rather than of any shape -- radium-226 and
    radon-222 carry the same eight characters for the same reason.  So a caller
    about to *copy a stereochemistry across* has to ask the structure, not the
    key: see
    `<https://github.com/brightway-labs/brightway-flows/issues/55>`_.

    Reads the layers rather than searching the string, so an ``/i`` or ``/q``
    layer that happens to contain a ``t`` cannot answer yes.
    """
    text = str(inchi or "").strip()
    if not text:
        return False
    # Skip the prefix and the formula: layers begin at the third segment, and a
    # formula starts with an element symbol, never a layer letter.
    for layer in text.split("/")[2:]:
        if layer[:1] in STEREOCHEMISTRY_LAYER_PREFIXES:
            return True
    return False


class ConversionRefusal(StrEnum):
    """Why a structure could not be re-expressed as a standard InChI.

    The refusal used to be a bare `None`, and its one caller assumed the middle
    reason and said so in a review queue title.  For `Zinc-65` that produced a
    row reading "CAS states a relative or racemic stereochemistry" about a
    single atom, which has no stereochemistry at all and whose key agreed with
    ours exactly -- see
    `<https://github.com/brightway-labs/brightway-flows/issues/55>`_.  A
    refusal that carries its own reason cannot be described as a different one.
    """

    #: Empty, or RDKit would not read it.
    UNREADABLE = "unreadable"
    #: States a relative or racemic arrangement, which standard InChI cannot
    #: write down.  Converting would invent an absolute form.
    RELATIVE = "relative"
    #: The round trip did not give back what went in.  RDKit drops the isotopic
    #: layer of a lone labelled atom -- `InChI=1S/Zn/i1+0` comes back as
    #: `InChI=1S/Zn`, zinc-65 read back as ordinary zinc -- so this is the guard
    #: that stops a corrupted structure being used, and it does fire.
    ALTERED = "altered"


@dataclass(frozen=True)
class StandardStructure:
    """A structure re-expressed as standard InChI, or the reason it was not.

    Exactly one of `refusal` and the pair (`inchi`, `inchikey`) is set.
    """

    inchi: str = ""
    inchikey: str = ""
    refusal: Optional[ConversionRefusal] = None


def standard_structure_from_inchi(inchi: str) -> StandardStructure:
    """Re-express *inchi* as a standard InChI and key, or say why not.

    A key says how it was computed, and two keys computed differently cannot be
    compared.  CAS publishes plenty of non-standard keys, and comparing one
    against ours answers nothing -- but CAS also publishes the InChI those keys
    came from, and a structure can be read and re-expressed.  Where that works,
    a number we could only shrug at becomes one we can check against, and
    correct from::

        trans-4-tert-butylcyclohexanol, 21862-63-5
            CAS publishes  CCOQPGVQAWPUPE-KYZUINATNA-N   (non-standard)
            this returns   CCOQPGVQAWPUPE-KYZUINATSA-N   (standard, same hash)

    A refusal means *no comparable answer*, never *no disagreement*, and it
    names which of the three reasons applied.  The last of them is not
    hypothetical: it is what happens to every isotope-labelled single atom.
    """
    text = str(inchi or "").strip()
    if not text:
        return StandardStructure(refusal=ConversionRefusal.UNREADABLE)
    if states_relative_stereochemistry(text):
        return StandardStructure(refusal=ConversionRefusal.RELATIVE)
    mol = mol_from_inchi(text)
    if mol is None:
        return StandardStructure(refusal=ConversionRefusal.UNREADABLE)
    converted_key = inchikey(mol)
    converted_inchi = mol_inchi(mol)
    if not converted_key or not converted_inchi:
        return StandardStructure(refusal=ConversionRefusal.UNREADABLE)
    original = None
    try:
        original = InchiToInchiKey(text)
    except Exception:
        original = None
    if original and original.split("-")[1][:8] != converted_key.split("-")[1][:8]:
        return StandardStructure(refusal=ConversionRefusal.ALTERED)
    return StandardStructure(inchi=converted_inchi, inchikey=converted_key)


def standard_inchikey_from_inchi(inchi: str) -> Optional[str]:
    """A *standard* InChIKey for the structure *inchi* describes, or `None`.

    :func:`standard_structure_from_inchi` without the reason for a refusal.
    """
    return standard_structure_from_inchi(inchi).inchikey or None


def standard_inchi_from_inchi(inchi: str) -> Optional[str]:
    """The *standard* InChI for the structure *inchi* describes, or `None`.

    The string behind :func:`standard_inchikey_from_inchi`, refusing in exactly
    the same cases.  A caller that publishes the converted key needs this too:
    publishing a standard key beside the non-standard InChI it was *not*
    computed from would leave the two describing the substance in different
    notations on the same object.
    """
    return standard_structure_from_inchi(inchi).inchi or None


#: The InChI layers that name three-dimensional arrangements one at a time:
#: ``/t`` a tetrahedral centre, ``/b`` a double bond.  ``/m`` and ``/s`` name
#: nothing of their own -- they say how to read a ``/t`` that is already there
#: -- which is why they are not here and why they must not be compared directly.
STEREO_ELEMENT_LAYER_PREFIXES = ("t", "b")

#: One entry of such a layer: an identifier and a parity.  ``?`` is not a
#: missing entry -- it is the record saying "there is a centre here and it was
#: not determined", which is the whole distinction #56 turns on.
_STEREO_ELEMENT = re.compile(r"^(.+)([+\-?])$")

#: Where a stereo element sits: the layer letter, which occurrence of that
#: letter (a second ``/t`` after ``/i`` states the isotopic stereochemistry),
#: which component of a multi-component structure, and the identifier itself.
_StereoElement = tuple[str, int, int, str]


def _stereo_elements(inchi: str) -> Optional[dict[_StereoElement, str]]:
    """Every arrangement *inchi* names, and what it says about each.

    `None` where the string cannot be read this way, which includes the
    component multipliers (``2*``) a repeated component is abbreviated with:
    expanding those correctly is not worth it for a comparison that is allowed
    to answer "cannot tell".
    """
    parts = str(inchi or "").split("/")
    if len(parts) < 3:
        return None
    elements: dict[_StereoElement, str] = {}
    seen: dict[str, int] = {}
    for segment in parts[2:]:
        layer = segment[:1]
        if layer not in STEREO_ELEMENT_LAYER_PREFIXES:
            continue
        occurrence = seen.get(layer, 0)
        seen[layer] = occurrence + 1
        for component, chunk in enumerate(segment[1:].split(";")):
            if "*" in chunk:
                return None
            for item in chunk.split(","):
                if not item:
                    continue
                match = _STEREO_ELEMENT.match(item)
                if match is None:
                    return None
                elements[(layer, occurrence, component, match.group(1))] = match.group(2)
    return elements


def _with_arrangements_undetermined(
    inchi: str, elements: set[_StereoElement]
) -> str:
    """*inchi* rewritten so that each of *elements* is stated as undetermined.

    The result is a well-formed InChI string but not a canonical one: dropping
    an assignment can change which enantiomer InChI writes down, and only InChI
    can say what the canonical form then is.  So this is an *input* to a round
    trip, never an answer.
    """
    parts = str(inchi).split("/")
    out = list(parts[:2])
    seen: dict[str, int] = {}
    for segment in parts[2:]:
        layer = segment[:1]
        if layer not in STEREO_ELEMENT_LAYER_PREFIXES:
            out.append(segment)
            continue
        occurrence = seen.get(layer, 0)
        seen[layer] = occurrence + 1
        chunks = []
        for component, chunk in enumerate(segment[1:].split(";")):
            items = []
            for item in chunk.split(","):
                match = _STEREO_ELEMENT.match(item) if item else None
                if match and (layer, occurrence, component, match.group(1)) in elements:
                    items.append(match.group(1) + "?")
                elif item:
                    items.append(item)
            chunks.append(",".join(items))
        out.append(layer + ";".join(chunks))
    return "/".join(out)


def states_more_stereochemistry(fuller: str, sparser: str) -> bool:
    """Whether *fuller* states every arrangement *sparser* does, and more.

    The question two InChIKeys cannot answer.  A key hashes the whole set of
    stereo layers at once, so a record that leaves one corner of thirty
    undetermined gets a hash as different from the complete record's as
    inverting all thirty would give::

        α-cyclodextrin  ours  …,22-,23-,24-,25-,…   HFHDHCJBZVLPGP-RWMJIURBSA-N
                        CAS   …,22-,23-,24?,25-,…   HFHDHCJBZVLPGP-FXNRASGISA-N

    By key alone that reads as two substances.  By content it is one substance
    described once fully and once with a gap, and #56 is fifteen rows that
    could not tell those apart.

    **Answered by construction, not by reading the layers off.**  Take the
    fuller record, mark as undetermined exactly the arrangements the sparser one
    leaves undetermined, and ask InChI for the key of what is left.  If that is
    the sparser record's key, the sparser record *is* the fuller one with those
    corners unstated, and the two agree everywhere both speak.

    Comparing the ``/t`` layers directly would get this wrong, and did::

        chloralose      ours  /t2?,3-,4+,5+,6?,7+/m0/s1
                        CAS   /t2-,3+,4-,5-,6-,7-/m1/s1

    Every assigned parity differs and so does the mirror flag, which reads as a
    flat contradiction.  It is not one: blank centres 2 and 6 in CAS's record
    and InChI re-canonicalises the rest to exactly ours.  ``/m`` records which
    of two mirror images the ``/t`` layer was written for, and *which* one that
    is depends on the set of centres being written -- so a ``/t`` layer means
    nothing apart from the ``/m`` beside it, and neither can be compared
    element-wise across two records that assign different centres.  Two of the
    five substances #56 sent to a curator as genuine disagreements are this.

    `False` rather than an exception whenever the question cannot be settled:
    either string unreadable, nothing extra in *fuller*, or a round trip that
    does not land on *sparser*.  Callers use this to decide whether to *stop*
    treating a difference as a disagreement, so an uncertain answer has to leave
    the disagreement standing.
    """
    fuller_elements = _stereo_elements(fuller)
    sparser_elements = _stereo_elements(sparser)
    if fuller_elements is None or sparser_elements is None:
        return False
    stated_by_fuller = {k for k, v in fuller_elements.items() if v != "?"}
    stated_by_sparser = {k for k, v in sparser_elements.items() if v != "?"}
    if not stated_by_sparser < stated_by_fuller:
        return False
    target = standard_inchikey_from_inchi(sparser)
    if target is None:
        return False
    # Not `standard_inchikey_from_inchi`: that refuses a conversion whose stereo
    # hash moves, and here it is *meant* to move -- the string handed in is the
    # deliberately non-canonical one above, and InChI's re-canonicalisation of
    # it is the answer being sought.
    mol = mol_from_inchi(
        _with_arrangements_undetermined(fuller, stated_by_fuller - stated_by_sparser)
    )
    return mol is not None and inchikey(mol) == target


def stereocentre_counts(mol: Chem.Mol) -> tuple[int, int]:
    """How many stereocentres *mol* has, and how many carry an assignment.

    Tells apart the two reasons a structure has no stereochemistry in its key,
    which the key itself writes identically as ``UHFFFAOY``:

        dichloromethane          (0, 0)  -- there is nothing to state
        tryptophan, flattened    (1, 0)  -- there is, and it was not stated

    The first is complete; the second is missing information.  A caller deciding
    whether a substance has *lost* its stereochemistry needs that difference,
    because calling the first a loss would report every simple molecule in the
    list.
    """
    try:
        found = Chem.FindMolChiralCenters(
            mol, includeUnassigned=True, useLegacyImplementation=False
        )
    except Exception:
        return (0, 0)
    assigned = sum(1 for _, label in found if label != "?")
    return (len(found), assigned)


def molecular_formula(mol: Chem.Mol) -> str:
    try:
        return rdMolDescriptors.CalcMolFormula(mol) or ""
    except Exception:
        return ""


def molecular_weight(mol: Chem.Mol) -> float:
    try:
        return round(Descriptors.MolWt(mol), 3)
    except Exception:
        return 0.0


def monoisotopic_mass(mol: Chem.Mol) -> float:
    try:
        return round(Descriptors.ExactMolWt(mol), 6)
    except Exception:
        return 0.0


@dataclass(frozen=True)
class StructureValues:
    """Everything the RDKit transformers derive from one parsed structure.

    The six values are always computed together -- the three transformers that
    want any of them want all of them -- so they are cached together, keyed by
    the string they were read from.

    Strings rather than numbers for the two masses, because that is what the
    properties carry and what the callers compared against; ``""`` where the
    descriptor returned nothing, which is the same "no value" the callers
    already skipped on.
    """

    smiles: str
    inchi: str
    inchikey: str
    formula: str
    molecular_mass: str
    monoisotopic_mass: str


def _structure_values(mol: Chem.Mol) -> StructureValues:
    mass = molecular_weight(mol)
    mono = monoisotopic_mass(mol)
    return StructureValues(
        smiles=canonical_smiles(mol),
        inchi=mol_inchi(mol) or "",
        inchikey=inchikey(mol) or "",
        formula=molecular_formula(mol),
        molecular_mass=str(mass) if mass else "",
        monoisotopic_mass=str(mono) if mono else "",
    )


@lru_cache(maxsize=_STRUCTURE_CACHE_SIZE)
def structure_values_from_smiles(smiles: str) -> Optional[StructureValues]:
    """What RDKit derives from the SMILES *smiles*, or ``None`` if it will not parse.

    Separate from :func:`structure_values_from_inchi` rather than one function
    that tries both notations, because which notation a string is written in is
    known at the call site and guessing it is not safe: an InChI begins
    ``InChI=``, whose leading ``I`` is iodine to a SMILES parser, so a
    try-SMILES-then-InChI reading could accept a structure the caller never
    offered.
    """
    mol = mol_from_smiles(smiles)
    return None if mol is None else _structure_values(mol)


@lru_cache(maxsize=_STRUCTURE_CACHE_SIZE)
def structure_values_from_inchi(inchi: str) -> Optional[StructureValues]:
    """What RDKit derives from the InChI *inchi*, or ``None`` if it will not parse."""
    mol = mol_from_inchi(inchi)
    return None if mol is None else _structure_values(mol)


def structure_svg(mol: Chem.Mol, width: int = 300, height: int = 200) -> str:
    try:
        drawer = rdMolDraw2D.MolDraw2DSVG(width, height)
        drawer.DrawMolecule(mol)
        drawer.FinishDrawing()
        return drawer.GetDrawingText()
    except Exception:
        return ""


@lru_cache(maxsize=_STRUCTURE_CACHE_SIZE)
def canonical_smiles_key(smiles: str) -> Optional[str]:
    """The canonical form of a SMILES *string*, or ``None`` if it will not parse.

    Two toolkits write the same molecule differently -- PubChem's OEChem output
    spells camphor `CC1(C2CCC1(C(=O)C2)C)C` where RDKit writes
    `CC12CCC(CC1=O)C2(C)C` -- so "is this structure already stored?" cannot be
    answered by comparing strings.  Canonicalising both sides answers it.

    `None` is not `""`: a string RDKit cannot read has no canonical form, and
    that is not the same as having no structure.  Callers must leave such a
    value alone rather than treat every unparseable string as equal.
    """
    mol = mol_from_smiles(smiles)
    if mol is None:
        return None
    try:
        return Chem.MolToSmiles(mol) or None
    except Exception:
        return None


def collapse_duplicate_smiles(values: list[str]) -> tuple[list[str], int]:
    """Collapse spellings of one structure to one value; return it and the count dropped.

    Order is otherwise preserved: a group takes the position of its first
    member, and values RDKit cannot parse keep their own place and are never
    merged with anything, since there is no evidence they say the same thing.

    Stereochemistry is part of the structure here, so two stereoisomers are two
    values, not one.  That holds in both slots and both layers: the graph slot
    on a flow object carries no stereochemistry by the time this runs -- the
    isomeric split took it off -- and on a flow it still can, where flattening
    it would be a loss rather than a collapse.

    **The surviving spelling is RDKit's canonical form.**  Where that form is
    already stored -- which is the usual case, because the same RDKit computed
    it -- the collapse only removes the other spelling.  Where two sources each
    supplied a spelling of their own and neither is canonical, one of them has
    to go, and writing the canonical form rather than picking a winner keeps the
    published string consistent with every other structural property in the
    record, all of which are RDKit-derived.

    The dropped spelling's provenance is not this function's to keep: provenance
    on these properties is recorded per property, not per value, so the entry
    that stated where a spelling came from stays attached to the property it
    was collapsed into.
    """
    groups: list[tuple[Optional[str], list[str]]] = []
    position: dict[tuple[str, str], int] = {}
    for value in values:
        key = canonical_smiles_key(value)
        # A string RDKit will not read is grouped with nothing but an identical
        # string: two unparseable values are not evidence of one structure.
        slot = ("canonical", key) if key is not None else ("verbatim", value)
        if slot not in position:
            position[slot] = len(groups)
            groups.append((key, []))
        groups[position[slot]][1].append(value)

    survivors: list[str] = []
    dropped = 0
    for key, spellings in groups:
        if key is None or len(spellings) == 1:
            # A value nothing duplicates keeps the spelling its source gave it.
            # Rewriting it would change a published string with nothing to show
            # for it.
            survivors.append(spellings[0])
        else:
            survivors.append(key)
        dropped += len(spellings) - 1
    return survivors, dropped
