"""Parse and compare InChIKeys without letting the standard flag lie.

An InChIKey is three hyphenated blocks, ``AAAAAAAAAAAAAA-BBBBBBBBFV-P``:

- **block 1**, 14 characters, hashes the connectivity -- the skeleton.
- **block 2**, 10 characters: 8 characters hashing stereochemistry and
  isotopic labelling, then ``F``, the *standard flag*, then ``V``, the InChI
  version.
- **block 3**, one character, the protonation state.

``F`` is ``S`` for a key derived from a standard InChI and ``N`` for one derived
from a non-standard InChI.  It says how the key was *computed*, not what the
substance *is*.

**Ignoring the flag is sound for equality and unsound for inequality**, and
getting only the first half of that right is what #42 measured as 91 defects
where there are 45.

Equality first, because that is the easy half.  CAS Common Chemistry publishes
non-standard keys freely while RDKit and PubChem give us standard ones, so a
literal string comparison finds differences that are not there::

    β-Hexachlorocyclohexane   ours  JLYXXMFPNIAWKQ-CDRYSYESSA-N
                              CAS   JLYXXMFPNIAWKQ-CDRYSYESNA-N
    δ-Hexachlorocyclohexane   ours  JLYXXMFPNIAWKQ-GPIVLXJGSA-N
                              CAS   JLYXXMFPNIAWKQ-GPIVLXJGNA-N

Both pairs are the same molecule -- 22 flow objects agree with Common Chemistry
only once the flag is disregarded -- and equal stereo hashes stay equal whatever
options produced them.

Inequality does not follow the same way.  A non-standard InChI is computed under
options the key does not record, and the stereo hash is a hash *of those
options' output*.  Where CAS uses them, it is precisely to say something
standard InChI cannot::

    Trans-4-tert-butylcyclohexanol   ours  CCOQPGVQAWPUPE-UHFFFAOYSA-N
                                     CAS   CCOQPGVQAWPUPE-KYZUINATNA-N
                                     CAS   InChI=1/C10H20O/...*/t8-,9-*
    (2RS,4SR)-2-methyl-4-propyl-      ours  GKGOLPMYJJXRGD-SFYZADRCSA-N
      1,3-oxathiane                   CAS   GKGOLPMYJJXRGD-HGXVMFPFNA-N
                                      CAS   InChI=1/C8H16OS/...*/t7-,8+/s2*

``/s2`` is *relative* stereochemistry, which standard InChI has no layer for; 40
of the 75 non-standard keys in the Common Chemistry cache carry it.  No standard
key can ever equal one of these, however right the structure behind it is.  So a
stereo-hash difference against a non-standard key is not a disagreement about
the substance -- it is two hashes that were never comparable, and callers get
:attr:`StructureComparison.INCOMPARABLE` rather than a verdict the evidence does
not support.

Of the 91 flow objects #42 counted, 45 are this: 9 of the 10 "stereo lost" and
36 of the 48 "stereo conflict".  The 33 "stereo invented" are all standard on
both sides and are a real defect.

One more thing the blocks decide is which of two keys for one substance is
worth publishing.  Block 1 hashes connectivity alone, so the stereochemistry-free
key of a substance is its own key with block 2 replaced by ``UHFFFAOYSA`` --
`QIVBCDIJIAJPQS-VIFPVBQESA-N` and `QIVBCDIJIAJPQS-UHFFFAOYSA-N` are L-tryptophan
and the flat form of the same skeleton.  Stored side by side in one slot they are
indistinguishable from two candidate identities, and the flat one is also
DL-tryptophan's real key, so a merge rule keying on this field fuses two
substances that are not the same (#50).  :func:`without_redundant_flat_keys`
drops the flat key where a specific one for the same skeleton is present: on the
2026-08-12 build that is 427 values across 419 flow objects and 5,416 elementary
flows, and nothing is lost, because the dropped string is recoverable from the
one that survives without a chemistry toolkit.

So no caller compares these strings directly; they call
:func:`compare_structures`, :func:`same_structure`, or key on
:func:`structure_identity`.

The version character is kept in the comparison deliberately.  A future InChI
version could hash the same substance differently, and silently treating v1 and
v2 keys as interchangeable would be the same mistake in a new place -- so a
version difference is `INCOMPARABLE` too, for the same reason the flag is.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum
from typing import NamedTuple

#: Block 2 begins with this hash when the structure has no stereochemistry and
#: no isotopic labelling -- the "flat" key.
FLAT_STEREO_HASH = "UHFFFAOY"

#: The standard flag of a key derived from a standard InChI.  Anything else is
#: a key whose stereo hash was computed under options it does not record.
STANDARD_FLAG = "S"

_BLOCK_LENGTHS = (14, 10, 1)


class StructureComparison(StrEnum):
    """What two InChIKeys say about each other.

    Three values rather than a boolean, because the third is what keeps the
    comparison honest.  `DIFFERENT` is an assertion -- these are not the same
    substance -- and asserting it from a stereo hash computed under unknown
    InChI options is asserting more than the keys support.  See the module
    docstring for the ``/s2`` case that makes this concrete.
    """

    #: The keys describe the same structure.
    SAME = "same"
    #: The keys describe different structures, and both were computed under
    #: options that make the difference meaningful.
    DIFFERENT = "different"
    #: The keys cannot be compared: one is unreadable, they were computed under
    #: different InChI options, or they come from different InChI versions.
    #: Not evidence of agreement, and not evidence of disagreement either.
    INCOMPARABLE = "incomparable"


class InChIKeyParts(NamedTuple):
    """An InChIKey split into the parts that mean different things."""

    #: Connectivity hash: which atoms are bonded to which.
    skeleton: str
    #: Stereochemistry and isotope hash, without the flag or version characters.
    stereo: str
    #: ``S`` for standard InChI, ``N`` for non-standard.  Never compared for
    #: equality; it decides whether the *stereo* hashes are comparable at all.
    standard_flag: str
    #: InChI version character, ``A`` for version 1.
    version: str
    #: Protonation state.
    protonation: str

    @property
    def is_flat(self) -> bool:
        """Whether the key encodes no stereochemistry and no isotopes."""
        return self.stereo == FLAT_STEREO_HASH

    @property
    def is_standard(self) -> bool:
        """Whether the key came from a standard InChI.

        Anything that is not ``S`` is treated as non-standard, including a flag
        character this module has never seen.  An unrecognised flag is a key
        computed some way we cannot account for, which is the case for caution,
        not against it.
        """
        return self.standard_flag == STANDARD_FLAG


def parse_inchikey(value: str) -> InChIKeyParts | None:
    """Split *value* into its parts, or `None` if it is not an InChIKey.

    Tolerates the ``InChIKey=`` prefix, because that is how CAS Common
    Chemistry stores the value in its cached detail records.
    """
    text = str(value or "").strip()
    if text.upper().startswith("INCHIKEY="):
        text = text.split("=", 1)[1].strip()
    blocks = text.split("-")
    if len(blocks) != 3:
        return None
    if [len(block) for block in blocks] != list(_BLOCK_LENGTHS):
        return None
    if not all(block.isalpha() and block.isupper() for block in blocks):
        return None
    skeleton, middle, protonation = blocks
    return InChIKeyParts(
        skeleton=skeleton,
        stereo=middle[:8],
        standard_flag=middle[8],
        version=middle[9],
        protonation=protonation,
    )


def _structure_group(parts: InChIKeyParts) -> tuple[str, str, str]:
    """The parts two keys must share to be describing one substance's structure.

    Everything except the stereo hash and the standard flag: two keys agreeing
    on these are the same skeleton, in the same protonation state, hashed by the
    same InChI version, and differ only in how much of the stereochemistry they
    state.
    """
    return (parts.skeleton, parts.version, parts.protonation)


def structure_identity(value: str) -> tuple[str, str, str, str] | None:
    """The parts of *value* that identify a structure, for use as a dict key.

    Everything except the standard flag.  Two InChIKeys describe the same
    structure exactly when this is equal for both.
    """
    parts = parse_inchikey(value)
    if parts is None:
        return None
    return (parts.skeleton, parts.stereo, parts.version, parts.protonation)


def compare_structures(left: str, right: str) -> StructureComparison:
    """What *left* and *right* say about each other.

    The order of the checks is the argument:

    1. **Unreadable** either side, and there is nothing to compare.
    2. **Different skeletons** is a different substance.  The connectivity hash
       is not what the stereo options move, so this stands whatever the flags
       say -- and it has to, because it is the check that finds the wrong-hit
       structures of #35 and #38.
    3. **Different InChI versions** are two hashing schemes, not two substances.
    4. **Different protonation** is a real difference in the substance, and the
       block that carries it is not touched by the stereo options either.
    5. **Equal stereo hashes** are equal however they were computed.  This is
       the β-hexachlorocyclohexane case, and it is why the flag is not part of
       :func:`structure_identity`.
    6. Only then, unequal stereo hashes: a disagreement if both keys are
       standard, and `INCOMPARABLE` if either is not.
    """
    left_parts = parse_inchikey(left)
    right_parts = parse_inchikey(right)
    if left_parts is None or right_parts is None:
        return StructureComparison.INCOMPARABLE
    if left_parts.skeleton != right_parts.skeleton:
        return StructureComparison.DIFFERENT
    if left_parts.version != right_parts.version:
        return StructureComparison.INCOMPARABLE
    if left_parts.protonation != right_parts.protonation:
        return StructureComparison.DIFFERENT
    if left_parts.stereo == right_parts.stereo:
        return StructureComparison.SAME
    if not (left_parts.is_standard and right_parts.is_standard):
        return StructureComparison.INCOMPARABLE
    return StructureComparison.DIFFERENT


def same_structure(left: str, right: str) -> bool:
    """Whether two InChIKeys describe the same structure.

    `False` when either is unparseable: an unreadable key is not evidence of
    agreement, and callers use this to decide whether to *keep* data.

    Use this only where `False` means "do not treat these as the same".  Where
    `False` would be read as "these are different substances", call
    :func:`compare_structures` instead and handle
    :attr:`StructureComparison.INCOMPARABLE` -- the two are not the same claim,
    and 45 of #42's 91 reported defects are the difference.
    """
    return compare_structures(left, right) is StructureComparison.SAME


def same_skeleton(left: str, right: str) -> bool:
    """Whether two InChIKeys share a connectivity hash.

    True for two stereoisomers of one molecule, and for a stereo-defined key
    against the flat key of the same skeleton.  Used to tell a stereochemistry
    disagreement (#42) from a wholly different substance (#35).
    """
    left_parts = parse_inchikey(left)
    right_parts = parse_inchikey(right)
    if left_parts is None or right_parts is None:
        return False
    return left_parts.skeleton == right_parts.skeleton


def without_redundant_flat_keys(values: Iterable[str]) -> list[str]:
    """*values* with each flat key a specific key of the same structure covers removed.

    Grouped by skeleton, version and protonation, and the flat key of a group
    goes only when that group holds a key carrying stereochemistry or isotopes.
    Per group rather than per record, because a record can hold keys for more
    than one skeleton and the second one is usually a wrong hit (#6, #38):
    `D-menthol` publishes `NOOLISFMXDJSKH-AEJSXWLSSA-N` and its flat form, and
    also `TWDOPJXHIBEHIL-UHFFFAOYSA-N`, a different chemical altogether.  The
    first flat key is a simplification of something the record already states
    and goes; the second is the only evidence that the wrong structure is there
    and stays.  Of the 474 flat keys sharing a record with a specific one on the
    2026-08-12 build, 427 are the first kind and 47 the second.

    Protonation and version join the skeleton in the group because a flat key
    that differs in either is not the flat form of *that* specific key -- it
    describes a different protonation state, or was hashed by a scheme this one
    cannot speak for.

    The standard flag does not.  A flat hash makes no statement about
    stereochemistry however it was computed -- a non-standard InChI can suppress
    stereochemistry the substance has, which is why
    `CommonChemistryIndex.registers_without_stereochemistry` will not read one
    as a registry saying "no stereochemistry here" -- so a flat key is never the
    more specific of the two, whichever flag it carries.  It does not arise
    today: in all 427 groups where this fires, both keys are standard.

    A value that is not an InChIKey is returned untouched.  Order is preserved,
    so a caller that sorted its values keeps them sorted.
    """
    parsed = [(value, parse_inchikey(value)) for value in values]
    specific = {
        _structure_group(parts)
        for _, parts in parsed
        if parts is not None and not parts.is_flat
    }
    return [
        value
        for value, parts in parsed
        if parts is None
        or not parts.is_flat
        or _structure_group(parts) not in specific
    ]
