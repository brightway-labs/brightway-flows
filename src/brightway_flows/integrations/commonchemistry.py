"""Read the cached CAS Common Chemistry details as a structure index.

`CommonchemCasReviewTransformer` fills `commonchemistry-cache.json` for the
names and CAS numbers a build touches, and until now only that transformer read
it back.  The cache holds something no other source does: **CAS's own answer to
whether a registry number denotes one structure at all.**

A detail record for a specific substance carries an `inchiKey`.  A record for a
UVCB, an unspecified isomer or a commercial mixture carries the substance's name
and an *empty* `inchiKey`, because there is no single structure to give::

    75-34-3      1,1-Dichloroethane           InChIKey=SCYULBFZEHDVBN-UHFFFAOYSA-N
    1300-21-6    Dichloroethane               (empty)
    592-41-6     1-Hexene                     InChIKey=LIKMAJRDDDTEIG-UHFFFAOYSA-N
    25264-93-1   Hexene                       (empty)
    68855-54-9   Kieselguhr, soda ash flux-…  (empty)
    111937-03-2  Isononanoic acid, C16-18-…   (empty)

That distinction is the one the pipeline could not previously make, and #35 is
what it costs.  PubChem's `by_cas` index answers every one of those numbers with
a compound -- 1300-21-6 with 1,1-dichloroethane, 8006-64-2 (gum turpentine) with
triethyl citrate, 111937-03-2 with *water* -- because its index aggregates
whatever substance records were standardised onto a compound.  Accepting those
answers gave 80 flow objects a structure for a CAS that denotes no structure,
and made them collide, under InChIKey, with the specific substance whose
structure they had borrowed.

The index below is deliberately thin.  It answers two questions per CAS -- does
Common Chemistry hold a structure, and which one -- and leaves every decision to
the caller.
"""

from __future__ import annotations

import functools
import re
from collections import Counter
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import orjson
import structlog

from brightway_flows.chem import (
    ConversionRefusal,
    StandardStructure,
    standard_structure_from_inchi,
    states_stereochemistry,
)
from brightway_flows.domain.formula import Composition, published_heavy_atoms
from brightway_flows.domain.inchikey import parse_inchikey
from brightway_flows.filesystem import COMMONCHEMISTRY_CACHE_FILEPATH
from brightway_flows.filesystem import PACKAGE_DATA_DIR

logger = structlog.get_logger(__name__)

#: Ships with the package, not the user's data directory: it is a curated part
#: of the pipeline's judgement, like `preferred-label-decisions.json`, and has
#: to be reviewable in the repository rather than editable per machine.
STRUCTURE_DECISIONS_FILEPATH = (
    PACKAGE_DATA_DIR / "commonchemistry-structure-decisions.json"
)

#: Common Chemistry marks up formulae for display -- `C<sub>2</sub>H<sub>4</sub>`
#: -- and the same markup appears in names.  Stripped before comparison.
_HTML_TAG = re.compile(r"<[^>]+>")


def normalise_formula(value: Any) -> str:
    """A Common Chemistry molecular formula with its display markup removed."""
    return _HTML_TAG.sub("", str(value or "")).strip()


#: Everything that is not a letter or a digit, for `normalised_name`.
_NAME_NOISE = re.compile(r"[^a-z0-9]+")


def normalised_name(value: Any) -> str:
    """A chemical name reduced to what two spellings of it have in common.

    Case, spacing, hyphens, commas and brackets all vary between a registry's
    spelling and a source list's -- CAS writes `Disodium hydrogen phosphite`
    and ecoinvent writes `Disodium Phosphonate`, and the synonym list is where
    those meet.  Markup goes too: Common Chemistry ships names containing
    `<sub>` and `<sup>`, so `Sodium phosphite (Na<sub>2</sub>HPO<sub>3</sub>)`
    has to compare equal to the same name written flat.

    Deliberately not a chemistry-aware comparison.  This is used to ask whether
    the registry knows the substance under the name in hand, and a looser
    reading -- stripping a qualifier, matching a prefix -- would start answering
    a different question.
    """
    return _NAME_NOISE.sub("", _HTML_TAG.sub("", str(value or "")).lower())


#: How CAS names a substance whose registration is a *class* rather than one
#: compound: a reaction product, a mass of several, an alkyl-range derivative,
#: or a compound-with.  These carry a full InChI in the cache -- CAS composes it
#: from the components it names -- and that InChI is a recipe rather than a
#: structure: 101357-15-7 is aniline twice with nitrobenzene and hydrogen
#: chloride, which is not a substance anybody can be shown.  Matched against
#: `normalised_name`, so the spacing and punctuation of the phrase do not
#: matter.
_UVCB_NAME_MARKERS = (
    "reactionproducts",
    "reactionmass",
    "derivs",
    "compdswith",
    "compdwith",
)


class CommonChemistryIndex:
    """CAS number to the structure CAS Common Chemistry publishes for it.

    Four states per CAS, and the third and fourth are the ones that stop this
    from over-reaching:

    - **a structure** -- the number denotes one substance, and this is its key.
    - **no composition** -- Common Chemistry answered, and gave
      ``molecularFormula: "Unspecified"``.  It is saying the number has no
      definite composition at all: a UVCB, a petroleum fraction, a commercial
      mixture.  ``Alkanes, C4-5``, ``Turpentine oil``, ``Naphtha``.
    - **a formula but no structure** -- Common Chemistry answered, gave a real
      formula, and published no InChIKey.  Two very different substances land
      here and nothing in the record separates them:

      * an unspecified isomer -- ``Dichloroethane`` C2H4Cl2, ``Hexene`` C6H12,
        ``Trichlorophenol`` C6H3Cl3O.  Definite composition, indefinite
        connectivity.  These are the #35 collisions.
      * a perfectly specific molecule Common Chemistry simply has no key for --
        **``Ozone`` O3**, ``Nitric oxide`` NO, ``Nitrogen dioxide`` NO2,
        ``Chlorine dioxide`` ClO2, ``Doramectin`` C50H74O14.

      319 of the 836 answered-with-no-key records are this shape, so treating
      them all as non-specific would have withheld ozone's structure.  Which
      they are is a curation judgement, taken in
      `commonchemistry-structure-decisions.json`.
    - **not cached** -- never asked, or the request failed.  Says nothing at
      all, and must never be read as any of the other three.
    """

    def __init__(
        self,
        structures: dict[str, str],
        without_composition: set[str],
        formula_only: set[str],
        inchis: dict[str, str] | None = None,
        formulae: dict[str, str] | None = None,
        raw_formulae: dict[str, str] | None = None,
        names: dict[str, frozenset[str]] | None = None,
    ) -> None:
        self._structures = structures
        self._without_composition = without_composition
        self._formula_only = formula_only
        #: Every name CAS registers for a number -- its own `name` and its
        #: `synonyms` -- normalised for comparison by `normalised_name`.  Held
        #: because a caller *publishing* CAS's structure needs evidence that the
        #: number denotes the substance in hand, and the registry naming it the
        #: way this list names it is that evidence.  See `registers_name`.
        self._names = names or {}
        #: Every formula the cache holds, keyed or not, before any judgement
        #: about what it means.  `_formulae` above is the subset belonging to a
        #: number that also has a structure, which is what a caller publishing
        #: CAS's answer may have; this is what a caller *comparing* against it
        #: may have, and the difference is deliberate -- see
        #: `registered_composition_for`.
        self._raw_formulae = raw_formulae or {}
        #: Memoised compositions, one parse per number asked about.
        self._compositions: dict[str, Composition | None] = {}
        #: The InChI and formula behind the keys above.  Optional because for
        #: most of this class's life the key was the whole of what was needed:
        #: a gate that only ever *refuses* a structure has no use for the rest
        #: of one.  #42 gave it a caller that publishes what CAS registers
        #: rather than only weighing candidates against it.
        self._inchis = inchis or {}
        self._formulae = formulae or {}
        #: Memoised conversions, which cost an RDKit parse per number.  Cached
        #: rather than precomputed: the pipeline asks about the few thousand
        #: numbers its flows carry, not all 6,300.  One entry holds the key, the
        #: InChI and -- where there is no answer -- the reason there is none, so
        #: the three cannot drift apart.
        self._comparable: dict[str, StandardStructure] = {}

    def __len__(self) -> int:
        return (
            len(self._structures)
            + len(self._without_composition)
            + len(self._formula_only)
        )

    def inchikey_for(self, cas: str) -> str | None:
        """The InChIKey Common Chemistry publishes for *cas*, if any."""
        return self._structures.get(str(cas or "").strip())

    def inchi_for(self, cas: str) -> str | None:
        """The InChI Common Chemistry publishes for *cas*, if any."""
        return self._inchis.get(str(cas or "").strip())

    def formula_for(self, cas: str) -> str | None:
        """The molecular formula Common Chemistry publishes for *cas*, if any.

        Only for a number that also has a key.  A formula without one is the
        ambiguous third state this class exists to keep separate, and handing it
        out here would be a way around that.
        """
        return self._formulae.get(str(cas or "").strip())

    def registered_formula_for(self, cas: str) -> str | None:
        """The composition CAS registers for *cas*, as CAS writes it.

        Wider than `formula_for`, and narrower than it looks.  This is a
        *composition* offered for publication as a molecular formula, and never
        as an identity: the caller gets no key, no InChI and no structure with
        it, because for these numbers the registry has none.  That is the same
        line `registered_composition_for` draws -- what a substance is made of
        is knowable when what it looks like is not -- and the reason for a
        second accessor is only that a caller *publishing* the answer needs the
        hydrogens `registered_composition_for` drops.

        A single component only.  `C15H24O6.C4H11N` is CAS stating two
        substances in one string, and while `registered_composition` can add
        them up, the sum is not a formula anybody should publish as this
        substance's own.

        `None` for a number that is unknown, whose formula is unreadable, whose
        composition CAS records as `Unspecified`, or that has more than one
        component.  All of them mean no opinion.
        """
        cas = str(cas or "").strip()
        if not cas or self.registered_composition_for(cas) is None:
            return None
        raw = str(self._raw_formulae.get(cas) or "").strip()
        if not raw or "." in raw:
            return None
        return raw

    def registered_composition_for(self, cas: str) -> Composition | None:
        """What CAS registers *cas* as being **made of**: heavy atoms, ratio
        multiplied out.

        Deliberately wider than `formula_for`, and it is the one place in this
        class where the ambiguous "formula but no structure" state is a usable
        answer.  That state is a number whose *connectivity* is indefinite --
        `Dichloroethane` C2H4Cl2, an isomer family -- and its composition is
        perfectly definite.  A caller asking what the substance is made of may
        have it; a caller asking what it looks like still may not.

        `None` for `Unspecified`, for an unreadable formula and for a number
        never asked about.  All three mean no opinion.

        See `domain.formula` for why the ratio is multiplied out and why
        hydrogen is dropped.  The answer is not an identity and must not be
        used as one.
        """
        cas = str(cas or "").strip()
        if not cas:
            return None
        if cas not in self._compositions:
            self._compositions[cas] = published_heavy_atoms(self._raw_formulae.get(cas, ""))
        return self._compositions[cas]

    def _comparable_structure_for(self, cas: str) -> StandardStructure:
        """What CAS registers under *cas*, re-expressed as standard InChI."""
        cas = str(cas or "").strip()
        if cas not in self._comparable:
            self._comparable[cas] = standard_structure_from_inchi(
                self._inchis.get(cas) or ""
            )
        return self._comparable[cas]

    def comparable_inchi_for(self, cas: str) -> str | None:
        """A *standard* InChI for what CAS registers under *cas*, or `None`.

        The companion of `comparable_inchikey_for`, answering in every case that
        one answers and refusing in every case it refuses, so a caller
        publishing the converted key can publish the string it came from rather
        than the non-standard one CAS wrote.
        """
        return self._comparable_structure_for(cas).inchi or None

    def comparable_refusal_for(self, cas: str) -> ConversionRefusal | None:
        """Why *cas* has no comparable key, or `None` if it has one.

        Callers that only need "is there an answer" should ask
        `comparable_inchikey_for`.  This is for the one that has to *describe*
        the absence to a reader, because naming the wrong reason is a defect of
        its own: every isotope-labelled single atom refuses as `ALTERED`, and
        was being reported as relative or racemic stereochemistry (#55).
        """
        return self._comparable_structure_for(cas).refusal

    def registers_stereochemistry(self, cas: str) -> bool:
        """Whether Common Chemistry states a three-dimensional shape for *cas*.

        Asked of the *structure*, not the key, and the difference matters here.
        A key whose second block is not ``UHFFFAOY`` is the usual sign that a
        substance has a stereochemistry, but that block hashes isotopes too, so
        ``Zinc-65`` looks stereo-specific and has no shape at all (#55).  A
        caller about to copy CAS's arrangement onto a flow object would then be
        copying an isotope label instead.

        False for a number that was never asked about, like every other
        statement this class makes.
        """
        return states_stereochemistry(self.inchi_for(cas) or "")

    def comparable_inchikey_for(self, cas: str) -> str | None:
        """A *standard* InChIKey for what CAS registers under *cas*, or `None`.

        `inchikey_for` returns what CAS published, which is often computed a
        different way from every key this project holds and so cannot be
        compared with one.  This returns a key that can be, by reading the InChI
        CAS published alongside it and expressing that structure as a standard
        key -- see :func:`standard_inchikey_from_inchi`.

        `None` means *no comparable answer exists*, which is not the same as
        disagreement.  Mostly that is a number whose stereochemistry is relative
        or racemic, which standard InChI has no way to write down; no amount of
        work will produce a key for those, and they need a person.

        On the 2026-08-12 cache this answers 22 of the 56 substance-and-number
        pairs where CAS states a stereochemistry and the list does not match it.
        The other 34 are the relative and racemic ones.
        """
        return self._comparable_structure_for(cas).inchikey or None

    def has_structure(self, cas: str) -> bool:
        """Whether Common Chemistry publishes a structure for *cas*."""
        return str(cas or "").strip() in self._structures

    def registers_name(self, cas: str, name: str) -> bool:
        """Whether CAS registers *cas* under *name*, however either is spelled.

        The corroboration for publishing a registry structure, and a different
        one from `corroborates_name`, which #129 uses for a composition.  That
        asks the substance's own name to *state a count* the formula agrees
        with -- `Antimony Trisulfide` against `S3Sb2` -- and for a structure
        there is usually no count to state: none of the 35 substances whose
        number carries a structure and which publish none have a name it
        accepts.

        What is available instead is that the registry knows the substance
        under the name this list gives it.  `Disodium Phosphonate` is a synonym
        CAS records for 13708-85-5, so two sources name one substance, which is
        the same two-source test in a form these names can meet.

        It is the gate that refuses what #129's docstring warns of, and it
        refuses it for the right reason rather than by naming the cases: CAS
        registers 7440-61-1 as `Uranium` and nothing calls it `Uranium Alpha`,
        registers 124-38-9 as `Carbon dioxide` and nothing calls it a
        correction flow for a delayed emission, registers 7440-15-5 as
        `Rhenium` and nothing calls it `Rhenium(2+)`.

        False for a number that was never asked about, like every other gate
        here: a caller acting on this publishes data, so silence must not.
        """
        key = normalised_name(name)
        if not key:
            return False
        return key in self._names.get(str(cas or "").strip(), frozenset())

    def registers_a_class_not_a_substance(self, cas: str) -> bool:
        """Whether CAS's own name for *cas* declares it a UVCB rather than a compound.

        Read off CAS's terminology, which is a documented convention rather
        than a guess: `Benzenamine, reaction products with aniline hydrochloride
        and nitrobenzene`, `Benzenesulfonic acid, mono-C10-13-alkyl derivs.,
        compds. with ethanolamine`, `Reaction mass of ...`.

        These are the awkward case for every gate above them.  They are *named*
        and they do carry a structure, so `has_structure` is true and
        `holds_no_composition` is false, and the InChI is real -- CAS composes
        it from the components the name lists.  It is simply not this
        substance's structure, because the registration does not denote one
        substance.  Four of them reach the structure-publishing rule on the
        build this was measured against, and each would publish a definite
        compound in place of a mixture.
        """
        cas = str(cas or "").strip()
        return any(
            marker in name
            for name in self._names.get(cas, frozenset())
            for marker in _UVCB_NAME_MARKERS
        )

    def registers_indefinite_stoichiometry(self, cas: str) -> bool:
        """Whether the formula CAS registers for *cas* states no whole ratio.

        A fraction or an unknown multiplier means the registered formula and
        the registered InChI are not describing the same thing, and the InChI is
        the lesser of the two: CAS gives `Talc` the formula
        ``H2O3Si.3/4Mg`` and an InChI holding a single magnesium, and
        `Ulexite`, `Asbestos (white)` and the octasodium dye at ``.xNa`` are
        the same shape.

        Minerals mostly, which is the substance class where a formula is a
        ratio rather than a molecule.  Publishing the InChI for one would state
        a composition the registry itself does not.
        """
        raw = self._raw_formulae.get(str(cas or "").strip(), "")
        return "/" in raw or bool(re.search(r"(?:^|\.)\s*[a-z]\s*[A-Z]", raw))

    def registers_without_stereochemistry(self, cas: str) -> bool:
        """Whether CAS registers *cas* as a substance with no stereochemistry.

        A *flat* published key -- block 2 beginning ``UHFFFAOY`` -- is the
        registry saying this number denotes the substance with its
        stereochemistry unstated.  Where the isomers are separately registered
        it is plainly deliberate::

            542-75-6    1,3-Dichloropropene   UOORRWUZONOOLO-UHFFFAOYSA-N
            10061-01-5  cis-1,3-…             UOORRWUZONOOLO-YFHOEESVSA-N
            4170-30-3   Crotonaldehyde        MLUCVPSAIODCQM-UHFFFAOYSA-N
            123-73-9    trans-Crotonaldehyde  MLUCVPSAIODCQM-BUHFOSPRSA-N

        The key must also be *standard*.  A non-standard key was computed under
        options that can suppress stereochemistry the substance has, so a flat
        one carries no such statement -- and a caller acting on this refuses
        data, which is the direction where a wrong reading costs a structure.

        5,726 of the 6,300 keyed numbers in the cache are flat, which is why
        this is a statement about *one candidate structure at a time* rather
        than about the number in isolation: see
        `_filter_compounds_by_stereo_specificity`.  False for a CAS that was
        never asked about, like every other gate here.
        """
        parts = parse_inchikey(self.inchikey_for(cas) or "")
        return parts is not None and parts.is_flat and parts.is_standard

    def holds_no_composition(self, cas: str) -> bool:
        """Whether Common Chemistry gave *cas* a formula of ``Unspecified``.

        The confident signal, and the only one acted on without a ruling:
        Common Chemistry is stating positively that the number has no definite
        composition, so nothing reachable through it can be this substance's
        structure.

        False for a CAS that was never asked about.  Callers gating on this are
        refusing to attach data, so the uncached case has to fall through to
        "no opinion".
        """
        return str(cas or "").strip() in self._without_composition

    def has_formula_but_no_structure(self, cas: str) -> bool:
        """Whether *cas* has a definite formula and no published InChIKey.

        Ambiguous on its own -- see the class docstring.  Callers must not gate
        on this without a ruling.
        """
        return str(cas or "").strip() in self._formula_only

    def is_known(self, cas: str) -> bool:
        """Whether Common Chemistry has any usable cached answer for *cas*."""
        cas = str(cas or "").strip()
        return (
            cas in self._structures
            or cas in self._without_composition
            or cas in self._formula_only
        )


def build_commonchemistry_index(payload: dict[str, Any]) -> CommonChemistryIndex:
    """Index the `detail_by_cas` section of a Common Chemistry cache payload.

    Two shapes of record are *not* an answer, and neither may reach
    `without_structure`:

    - **`{}`.** `_lookup_commonchemistry_detail_cached` writes an empty dict
      both for a 404 and for a request that failed after its retries, and
      caches it either way.  286 of the 7,409 entries in the 2026-08-07 cache
      are this, and reading them as "CAS publishes no structure" would let a
      network error or a number Common Chemistry has never heard of withhold a
      flow's structure.  That is the failure this whole module exists to avoid,
      so an unnamed record is filed as *unknown*.
    - **an unparseable `inchiKey`.** A fault in the cache should widen no gate,
      and close none either.

    A genuine "no structure" record is *named* and carries an empty `inchiKey`:
    Common Chemistry answered, told us the substance is
    ``Benzene, C10-13-alkyl derivs.``, and published no structure for it because
    there is not one to publish.  836 entries are that, and they are split here
    by `molecularFormula` into the 517 with no definite composition and the 319
    with a formula and no key -- a distinction the caller needs, because ozone
    is in the second group.
    """
    details = payload.get("detail_by_cas")
    if not isinstance(details, dict):
        return CommonChemistryIndex({}, set(), set())

    structures: dict[str, str] = {}
    inchis: dict[str, str] = {}
    formulae: dict[str, str] = {}
    raw_formulae: dict[str, str] = {}
    names: dict[str, frozenset[str]] = {}
    without_composition: set[str] = set()
    formula_only: set[str] = set()
    malformed = 0
    unanswered = 0
    for cas, record in details.items():
        if not isinstance(cas, str) or not isinstance(record, dict):
            continue
        cas = cas.strip()
        if not cas:
            continue
        # Indexed for every record, not only the keyed ones: `registers_name`
        # is asked about a number before anything is known about what state it
        # is in, and a caller checking the name of an unkeyed number should get
        # the registry's answer rather than a hole.
        registered = {
            normalised_name(value)
            for value in [record.get("name"), *(record.get("synonyms") or [])]
            if isinstance(value, str)
        }
        registered.discard("")
        if registered:
            names[cas] = frozenset(registered)
        stated = normalise_formula(record.get("molecularFormula"))
        if stated and stated != "Unspecified":
            raw_formulae[cas] = stated
        raw = str(record.get("inchiKey") or "").strip()
        if not raw:
            named = str(record.get("name") or "").strip() or str(record.get("rn") or "").strip()
            if not named:
                unanswered += 1
            elif normalise_formula(record.get("molecularFormula")) in ("", "Unspecified"):
                without_composition.add(cas)
            else:
                formula_only.add(cas)
            continue
        parts = parse_inchikey(raw)
        if parts is None:
            malformed += 1
            continue
        structures[cas] = raw.split("=", 1)[-1].strip()
        inchi = str(record.get("inchi") or "").strip()
        if inchi:
            inchis[cas] = inchi
        formula = normalise_formula(record.get("molecularFormula"))
        if formula and formula != "Unspecified":
            formulae[cas] = formula

    if malformed:
        logger.warning("commonchemistry_malformed_inchikeys", count=malformed)
    logger.info(
        "commonchemistry_index_built",
        with_structure=len(structures),
        without_composition=len(without_composition),
        formula_only=len(formula_only),
        unanswered=unanswered,
        named=len(names),
    )
    return CommonChemistryIndex(
        structures,
        without_composition,
        formula_only,
        inchis,
        formulae,
        raw_formulae,
        names,
    )


class StructureRulingVerdict(StrEnum):
    """What a curator ruled about a registry number's structure.

    Not to be confused with
    :class:`brightway_flows.transformers.enrich_references.StructureVerdict`,
    which is what *Common Chemistry* says about a structure offered for a
    number.  This one is what a curator said when Common Chemistry could not
    say, and the two are read one after the other in `_lends_no_structure`.

    The member values are the keys the ruling file groups its entries under.
    """

    #: The number names an isomer family, so no structure reached through it
    #: belongs to any one member.
    ISOMER_AMBIGUOUS = "isomer_ambiguous"
    #: The number names one substance, whatever Common Chemistry's composition
    #: says.
    SPECIFIC = "specific"


@dataclass(frozen=True)
class StructureRuling:
    """One registry number, what it was ruled, and why."""

    cas: str
    verdict: StructureRulingVerdict
    comment: str


@functools.lru_cache(maxsize=1)
def load_structure_decisions() -> dict[str, StructureRuling]:
    """Curated rulings on CAS numbers with a formula and no published structure,
    keyed by registry number.

    One index rather than one collection per verdict: a number is ruled once,
    the two verdicts are answers to the same question, and a caller holding two
    collections has to remember that a number in both is a contradiction nothing
    checks.

    A ruling with no `comment` is dropped.  Every entry here denies a substance
    its structure or overrides the registry, and an assertion of that weight
    has to carry its reasoning -- the same rule `unit-change-allowlist.json`
    follows.

    :raises ValueError: if one number is ruled both ways. Two curators
        disagreeing is not something a reader of either verdict can be left to
        discover.
    """
    if not STRUCTURE_DECISIONS_FILEPATH.exists():
        return {}
    payload = orjson.loads(STRUCTURE_DECISIONS_FILEPATH.read_bytes())
    if not isinstance(payload, dict):
        return {}

    rulings: dict[str, StructureRuling] = {}
    for verdict in StructureRulingVerdict:
        for entry in payload.get(verdict.value, []) or []:
            if not isinstance(entry, dict):
                continue
            cas = str(entry.get("cas") or "").strip()
            comment = str(entry.get("comment") or "").strip()
            if not cas:
                continue
            if not comment:
                logger.warning(
                    "structure_decision_without_comment", cas=cas, ruling=verdict.value
                )
                continue
            previous = rulings.get(cas)
            if previous is not None and previous.verdict is not verdict:
                raise ValueError(
                    f"{STRUCTURE_DECISIONS_FILEPATH.name} rules {cas} both "
                    f"{previous.verdict.value} and {verdict.value}. One number, "
                    f"one answer."
                )
            rulings[cas] = StructureRuling(cas=cas, verdict=verdict, comment=comment)

    counted = Counter(ruling.verdict.value for ruling in rulings.values())
    logger.info("structure_decisions_loaded", **counted)
    return rulings


@functools.lru_cache(maxsize=1)
def load_commonchemistry_index() -> CommonChemistryIndex:
    """Load the on-disk Common Chemistry cache, or an empty index.

    An absent or unreadable cache yields an index that knows nothing, so every
    gate built on it becomes a no-op.  That is the right failure mode for a
    first build on a fresh machine, where the cache does not exist yet.
    """
    if not COMMONCHEMISTRY_CACHE_FILEPATH.exists():
        logger.info("commonchemistry_cache_absent", path=str(COMMONCHEMISTRY_CACHE_FILEPATH))
        return CommonChemistryIndex({}, set(), set())
    try:
        payload = orjson.loads(COMMONCHEMISTRY_CACHE_FILEPATH.read_bytes())
    except Exception as exc:
        logger.warning("commonchemistry_cache_unreadable", error=str(exc))
        return CommonChemistryIndex({}, set(), set())
    index = build_commonchemistry_index(payload)
    logger.info("commonchemistry_index_loaded", entries=len(index))
    return index
