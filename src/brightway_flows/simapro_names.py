"""Reading names that SimaPro shaped.

A list whose flows came, at some remove, out of SimaPro inherits naming habits
nothing else has.  They are not errors -- each was a reasonable choice for a
program listing flows in one flat, sorted column -- but they put information in
the *name* that this list keeps somewhere else, so a name arrives describing a
flow we already hold and matching nothing.

Undoing them is only ever right for such a list, which is what
``SourceList.simapro_origin`` says and what every caller here must check first.
Applied anywhere else these are not corrections but guesses: de-inverting
``Benzene, chloro-`` is right for a SimaPro-lineage list and a licence to invent
a structure for any other list that happens to have a comma in a name.

The habits divide by **what the name is carrying**, and the two kinds are read
at opposite ends of the pipeline.

**A name spelled another way is evidence of last resort.**  ``Benzene,
Chloro-`` and ``Arsenic V`` name a substance in a spelling this list does not
use, so the answer is a second name to try.  :func:`simapro_name_aliases` is
the entry point, and its one caller --
:func:`brightway_flows.merge.matching.resolve_flow_object` -- reaches for
it only after every registry number and every name the vendor actually shipped
has failed.  That ordering is the safety: a row that matches on its CAS or on
its own label never has a derived name considered at all, so a rule that is
wrong can only affect a row that was going to be reported unmatched anyway.
Enriching every row with the derived spelling *before* matching would put it in
front of rows already matching correctly, where the CAS branch narrows on
labels and a wrong spelling can move a match that was right.

**A field written into the name is read out of it before matching.**  ``Water,
AE`` is not another way to spell a substance; it is a substance with a
*geography* attached, and geography is something this list holds elsewhere.  A
second name to try would not be enough -- the row would still carry the place
in the name it creates a flow under, and every rule between the split and
matching would still see a name it does not recognise.  So
:func:`split_geography_suffix` runs at the stage each list's manifest declares
(``simapro.geography_split``, #192): in BAFU's adapter, where the place is
part of the identity its uuids derive from, or in ``load_flows`` for a list
whose uuids must not move -- AGRIBALYSE -- where it rewrites the working row
and leaves the vendor file untouched.  Applied to every row rather than as a
fallback, which is why :data:`GEOGRAPHY_BASE_LABELS` is a whitelist and earns
the scrutiny it does.

Six habits are implemented.  Four are aliases: the CAS-index inversion (#285),
the same inversion applied to an ordinary phrase -- ``Heat, waste`` for waste
heat (#288) -- the charged and oxidised forms spelled ``Arsenic V`` and ``Iron,
ion`` (#286), and a fused ring's locant written in round brackets,
``Benzo(a)anthracene`` for benzo[a]anthracene (#103).  Two are splits: the
geography written into the name as ``Water, RER`` (#65), and the unit written
into it as ``Water/m3`` (#67).

The aliases divide again, and the merge reads the division.  Two of the four
produce a *systematic chemical name* -- built from the parent compound and what
is attached to it, by a rule that fires only on the syntax of one -- and
:func:`systematic_name_aliases` is that pair.  It matters because a systematic
name can be trusted as evidence where a name a vendor typed cannot: see that
function, and #103.

The phrase inversion is an alias and not a split, and the division above is
what decides that: ``Heat, waste`` carries no field this list holds elsewhere.
It is one substance under one name, spelled in an order this list does not use,
so the answer is a second name to try and the ordering keeps it honest.

The two splits meet at :meth:`brightway_flows.sources.SourceList.load_flows`,
geography first and both *after* a list's manual fixes, because the fixes are
written by reading the vendor's file and a curator should not have to predict
what an earlier rule left behind -- and because a fix is how a row a split
declines gets corrected at all.  (BAFU is the grandfathered exception: its
adapter splits the geography while extracting, because the place is baked into
the identity its published uuids derive from.)  Both are rewrites of the row
rather than annotations, and both reach the name a **created** flow is
published under, which an alias consulted during matching never could.  What a
rewrite must not lose is the vendor's own string: a split row keeps it in
``original_name`` and its synonyms, the merge records it as the mapping's
``source_flow_name``, and the member-name pass publishes it as a label of the
substance the row lands on -- ``Phosphorus, CN`` still answers, for any
consumer (#192).

Those are a build's two points, and a row that did not come through a build has
neither: nobody extracted it, and nobody wrote manual fixes for it.  So there is
a third point, :func:`prepare_row_for_matching`, which runs both splits in the
order a build reaches them and belongs to the caller who asks where one row
goes.  It is what the lookup runs, and without it every SimaPro-shaped row whose
name carries a unit or a place reaches matching under a name no flow object in
any list answers to (#328).

"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass

#: An index-inverted name: a parent compound, a comma, the substituents, and a
#: trailing hyphen marking where they attach.  The hyphen is the whole signal --
#: without it ``Water, cooling`` and ``Gas, natural`` would be swept up, and
#: neither is a *chemical* inversion: the join here is a concatenation, and
#: ``coolingwater`` and ``naturalgas`` are not words.  They are inversions of
#: another kind, joined with a space, and :func:`deinvert_phrase_name` reads
#: them.
#:
#: The parent is allowed to contain spaces (``Acetic acid, chloro-`` is
#: chloroacetic acid) but not a comma: the split is at the *first* comma,
#: because the substituent half routinely contains its own -- ``Benzene,
#: 1,2-dichloro-`` is one parent and one locant-bearing substituent, not three
#: fields.
_INVERTED = re.compile(
    r"""
    ^
    (?P<parent>[^,]+?)      # `Benzene`, `Acetic acid`
    ,\s*
    (?P<substituent>\S.*?)  # `chloro`, `1,2-dichloro`, `2-(thiocyanatemethylthio)benzo`
    -                       # the attachment hyphen this pattern turns on
    \s*$
    """,
    re.VERBOSE,
)


#: A positional descriptor at the end of the substituent -- `dibenzo-p-`,
#: `xylene, o-`.  Here the trailing hyphen is part of the *parent's* own name
#: (`dibenzo-p-dioxin`) rather than a mark of where a substituent attaches, so
#: the shape is declined: reading it needs to know that `dibenzo-p-dioxin` is
#: one word, which is chemistry this rule does not have.
#:
#: Found by running the rule over every BAFU row rather than over the unmatched
#: ones: `Dioxin, 2,3,7,8 Tetrachlorodibenzo-p-` already matched, so a plain
#: concatenation would have hung `2,3,7,8 tetrachlorodibenzo-pdioxin` on a flow
#: that was already right.
_POSITIONAL_TAIL = re.compile(r"-(?:[omnp]|N|sec|tert|cis|trans)$", re.IGNORECASE)

#: A substituent that is *only* a positional descriptor -- `Xylene, o-` is
#: o-xylene.  Concatenating gives `oxylene`, which is not a name.  Joined with
#: a hyphen for the same reason a locant-led parent is: the hyphen between a
#: descriptor and what it describes is nomenclature, not a guess.
#:
#: BAFU 2026 v1 ships none of these; it is here because the spelling belongs to
#: the convention rather than to one export, and the alternative is emitting
#: `oxylene` the first time a list does ship one.
_BARE_DESCRIPTOR = re.compile(r"^(?:[omnp]|N|sec|tert|cis|trans)$", re.IGNORECASE)

#: A parent that begins with its own locant -- `2-Butene` in `2-Butene,
#: 2-methyl-`.  Concatenating gives `2-methyl2-butene`; the nomenclature is
#: `2-methyl-2-butene`, and the hyphen between a substituent and a locant-led
#: parent is a rule rather than a guess.
_LOCANT_LED = re.compile(r"^[0-9]")


def deinvert_cas_index_name(name: str) -> str | None:
    """``"Benzene, chloro-"`` -> ``"chlorobenzene"``; ``None`` if not inverted.

    A printed chemical index sorts on the parent compound so that everything
    derived from benzene files together, and writes the modification after it.
    Read the two halves in the other order and join them and you have the name
    people actually use.

    The join is a concatenation, not a swap, and that is what makes this
    different from the comma inversion already in the codebase for lists that
    ship *both* spellings.  Nothing here can be inferred from the list itself:
    BAFU ships ``Benzene, Chloro-`` and never ``chlorobenzene``, so the
    un-inverted form has to be constructed.

    Case is not decided here.  The result is lower-cased because that is what
    the caller compares on, and the label writers own presentation.

    Returns ``None`` rather than guessing whenever the shape is not certain --
    a confident wrong structure is worse than an unmatched row.
    """
    match = _INVERTED.match(name.strip()) if name else None
    if match is None:
        return None
    parent = match["parent"].strip()
    substituent = match["substituent"].strip()
    if not parent or not substituent:
        return None
    # A second trailing field is a trade or family name rather than a
    # substituent -- `Ethane, 1,1,1,2-tetrafluoro-, HFC-134a` -- and the regex
    # already declines it by requiring the hyphen last.  This guards the
    # remaining case: a substituent that is itself only punctuation.
    if not any(character.isalnum() for character in substituent):
        return None
    if _POSITIONAL_TAIL.search(substituent):
        return None
    needs_hyphen = _LOCANT_LED.match(parent) or _BARE_DESCRIPTOR.match(substituent)
    joiner = "-" if needs_hyphen else ""
    return f"{substituent}{joiner}{parent}".lower()


#: A phrase written head-first: a noun, a comma, and the words that belong in
#: front of it.  ``Heat, waste`` is waste heat, ``Coal, brown`` is brown coal.
#: The habit is the same one the chemical rule undoes -- a flat sorted column
#: files everything about coal together -- but the join is a space, because
#: these are two words and not a substituent running into its parent.
#:
#: Exactly one comma.  Two or more is a list of qualifiers rather than a noun
#: and its modifier (``Water, cooling, unspecified natural origin``), and which
#: of them fronts is not something this can decide.
_PHRASE_INVERTED = re.compile(r"^(?P<head>[^,]+),\s*(?P<modifier>[^,]+)$")

#: A modifier that is a prepositional phrase, which English already writes
#: after the noun: ``Energy, from coal`` is *energy from coal*, not *from coal
#: energy*.  26 of BAFU's names are this -- five `Energy, from X` carriers,
#: seventeen `Transformation, from/to X` land classes, `Carbon dioxide, in air`
#: -- and fronting any of them makes a string nothing says.
_PREPOSITION_LED = re.compile(
    r"^(?:from|in|to|as|at|per|with|without|of|on)\b", re.IGNORECASE
)

#: A head that is an acronym -- ``COD, Chemical Oxygen Demand``, ``PAH,
#: polycyclic aromatic hydrocarbons``.  What follows the comma there is the
#: *expansion* of the head, not a modifier of it, and swapping the two gives
#: `chemical oxygen demand cod`.  Seven of BAFU's names are written this way,
#: and three already reach EF 3.1's flow by a curated synonym instead (#68),
#: which is the right shape for an expansion: somebody states the pairing
#: rather than a rule deriving it.
_ACRONYM_HEAD = re.compile(r"^[A-Z]{2,}[0-9]*$")

#: A modifier that opens with something other than a letter.  Eight of BAFU's
#: names, and the guard earns its place on four of them: ``1,4-Butanediol``,
#: ``2,4-D``, ``4,4'-Biphenol`` and one long carboxamide are single chemical
#: names whose comma sits *inside* a locant, so reading them as two fields
#: gives `4-butanediol 1` for a substance that was never inverted at all.  The
#: other four are `Particulates, < 10 um` and its siblings, where the second
#: half is a measurement and a measurement does not front a noun.
_OPENS_WITH_A_LETTER = re.compile(r"^[^\W\d_]", re.UNICODE)


def _brackets_balanced(text: str) -> bool:
    """Does every bracket *text* opens also close in it?

    A half with an unclosed bracket means the comma was inside a name rather
    than between two fields: ``Dibenz(a,h)anthracene`` is one substance, and
    splitting it gives ``Dibenz(a`` and ``h)anthracene``.  Found by running the
    rule over every BAFU name, which is also where the measurement and
    preposition shapes came from.
    """
    depth = 0
    for character in text:
        if character in "([{":
            depth += 1
        elif character in ")]}":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


def deinvert_phrase_name(name: str) -> str | None:
    """``"Heat, waste"`` -> ``"waste heat"``; ``None`` if it is not that shape.

    The same habit as the chemical inversion and a different join.  A flat
    sorted column wants everything about coal filed under `Coal`, so the
    modifier moves behind a comma; read the two halves in the other order with
    a space between them and you have the phrase people use.

    Eight of BAFU's names are this and name something the list already holds
    under the other spelling: `Clay, bentonite`, `Coal, brown`, `Coal, hard`,
    `Gas, natural`, `Heat, waste`, `Oil, crude`, `Water, lake`, `Water, river`.
    Not one is a chemical, which is why the chemical rule was never going to
    reach them: its signal is the attachment hyphen, and a phrase has none.

    Five of the eight are placed by it -- 19 rows, `Heat, waste` being 15 of
    them.  The other three carry a registry number and so reach the CAS branch,
    which runs first: `Water, lake` and `Water, river` carry water's, which
    twelve substances share, and `Gas, natural` carries natural gas's, which the
    coal-mine off-gas wears too (#80).  Those three do not fail here, they tie
    there -- and
    :func:`~brightway_flows.merge.matching._narrow_to_preferred_name` asks
    this rule again once the tie is declared, where an alias is still the last
    thing consulted and still cannot move a match that was right (#86).

    What it declines, and why each is somebody else's question rather than a
    shape to guess at:

    ``Benzene, Chloro-``
        The trailing hyphen makes it a substituent, and
        :func:`deinvert_cas_index_name` owns it -- including the names that
        rule itself declines, which must stay declined rather than fall
        through to a swap that would spell them a third way.
    ``Iron, ion``
        :func:`unspecified_ion` owns it; ``ion iron`` is not a spelling of
        anything.
    ``Energy, from coal``
        A prepositional phrase, already in the order English writes it.
    ``COD, Chemical Oxygen Demand``
        The second half expands the first rather than modifying it.
    ``1,4-Butanediol``, ``Particulates, < 10 um``
        A locant, and a measurement.  Neither comma separates two fields.
    ``Gas, natural/m3``
        The unit is in the name (#67). ``Gas, natural`` is a phrase inversion
        and this is that name with a second habit layered on it, so it is read
        once the unit has been taken off and not before -- which a manual fix
        does, so both spellings of that row are live and this is the order they
        are read in.

    ``Water, RER``
        A place, and #65's to read.  BAFU no longer ships one this far --
        :func:`split_geography_suffix` takes it out at extraction -- so this
        declines nothing in the registered lists today.  It is kept because
        the alias entry point promises to say nothing about a geography
        (a list whose adapter does not split would arrive here with one), and
        it asks :data:`GEOGRAPHY_CODES` rather than deciding for itself, so
        the two places a place is recognised cannot come to differ.
    """
    match = _PHRASE_INVERTED.match(name.strip()) if name else None
    if match is None:
        return None
    head = match["head"].strip()
    modifier = match["modifier"].strip()
    if not head or not modifier:
        return None
    if "/" in name:
        return None
    if modifier.endswith("-") or head.endswith("-"):
        return None
    if modifier.lower() in {"ion", "ions"}:
        return None
    if not _OPENS_WITH_A_LETTER.match(modifier):
        return None
    if _PREPOSITION_LED.match(modifier):
        return None
    # Deferred to `GEOGRAPHY_CODES` rather than tested here: a place is #65's
    # to recognise, and one vocabulary consulted twice cannot disagree with
    # itself the way a second `[A-Z]{2,5}` opinion beside it would.  Declines
    # nothing BAFU still ships -- :func:`split_geography_suffix` takes the
    # place out at extraction -- and holds for a name that reaches here with
    # one anyway: a list whose adapter does not split, or a base label the
    # whitelist there does not admit.
    if modifier.casefold() in _GEOGRAPHY_CODES_BY_CASEFOLD:
        return None
    if _ACRONYM_HEAD.match(head):
        return None
    if not _brackets_balanced(head) or not _brackets_balanced(modifier):
        return None
    return f"{modifier} {head}".lower()


#: A fusion locant written in round brackets: the `(a)` of `Benzo(a)anthracene`
#: where the consensus list writes `Benzo[a]anthracene`.
#:
#: The letters name the peripheral bonds of a ring system, lettered `a`, `b`,
#: `c` ... around the parent, and they say which bond the second ring is fused
#: to.  Square brackets are the nomenclature; round ones are the substitute a
#: program with one flat sorted column of plain text falls back on, and they
#: carry no other meaning, so rewriting them changes nothing about the
#: substance being named.
#:
#: The contents are held to what a fusion locant can be, which is what keeps
#: this off every other bracket in a chemical name.  The letters run from `a`,
#: in order, so a real one never reaches far into the alphabet -- `a`, `b`,
#: `k`, `a,h`, `g,h,i`, `cd` are the shapes that occur -- and they may be
#: preceded by the ring-atom locants the fusion is numbered from, as in
#: `Indeno(1,2,3-cd)pyrene`.  ``a`` to ``l`` and at most four letters is
#: measured rather than chosen: it admits every fused-ring name the three
#: merged lists ship and declines the two other things BAFU writes in round
#: brackets, `Thiazole, 2-(thiocyanatemethylthio)benzo-` -- a substituent, not
#: a locant -- and `Particulates, < 10 Um (stationary)`.
_FUSION_LOCANT = re.compile(
    r"""
    \(
    (?P<locant>
        (?:[0-9]+(?:,[0-9]+)*-)?    # `1,2,3-` in `1,2,3-cd`
        [a-l](?:,?[a-l]){0,3}       # `a`, `a,h`, `g,h,i`, `ghi`, `cd`
        '?
    )
    \)
    """,
    re.VERBOSE,
)

#: What has to sit in front of a bracket for it to be a fusion locant: the tail
#: of the parent ring's own name.  `Benzo`, `Dibenz`, `Indeno`.  A bracket that
#: opens a name, or follows a space or a digit, is something else -- a
#: qualifier, or a measurement -- and is left alone.
_FUSION_PREFIX = re.compile(r"[A-Za-z]$")

#: And what has to sit *after* it: the rest of the ring system's name.  A
#: fusion locant is punctuation inside one word -- `benzo` + `[a]` +
#: `anthracene` -- so a bracket the name ends at, or one followed by a space,
#: is naming something else.  This is what declines `Copper(ii) Sulphide`.
_FUSION_SUFFIX = re.compile(r"^[A-Za-z]")

#: A locant that is really an oxidation state.  ``Iron(iii)oxide`` runs the
#: valence straight into the next word, so the brackets sit exactly where a
#: fusion locant's do and only the letters tell them apart.
#:
#: The cost is `Benzo(i)...`: `i` is a real fusion locant, and a name using it
#: alone is declined here rather than risk retyping a valence.  None of the
#: three merged lists ships one, the shape is :func:`valence_in_parentheses`'s
#: to read where it is a valence, and an unmatched row is reported while a
#: wrong rewrite is silent.  A locant *set* is unaffected -- the `i` of
#: ``Benzo(g,h,i)perylene`` is not a bare numeral.
_ROMAN_NUMERAL = re.compile(r"^i{1,3}$", re.IGNORECASE)


def bracket_fusion_locants(name: str) -> str | None:
    """``"Benzo(a)anthracene"`` -> ``"benzo[a]anthracene"``; ``None`` if not that.

    Polycyclic aromatic hydrocarbons are named for the rings they are built
    from and the bond the rings are fused at: benzo[a]anthracene is an
    anthracene with a benzene ring joined at the bond lettered *a*.  The
    letter belongs in square brackets.  Lists that came out of a flat text
    export write it in round ones instead -- BAFU ships eight PAHs that way and
    ecoinvent 3.12 ships seven -- and the two spellings never meet.

    Nothing is added or removed, only retyped, which is what separates this
    from the other rules here: :func:`deinvert_cas_index_name` constructs a
    name that appears nowhere in the source list, while this one writes the
    same name in the punctuation the nomenclature uses.

    Every bracket group in the name has to be a locant, and there has to be at
    least one; a name with one locant and one substituent in round brackets is
    declined rather than half-converted, because the half that is a substituent
    would then be asserted to be a locant.  A locant also has to sit *inside* a
    word, with the parent ring before it and the rest of the name after -- the
    guard that separates it from an oxidation state, which is written in the
    same brackets and belongs to :func:`valence_in_parentheses`.

    Returns ``None`` rather than guessing whenever the shape is not certain,
    for the reason :func:`deinvert_cas_index_name` does.
    """
    text = name.strip() if name else ""
    if "(" not in text:
        return None
    converted: list[str] = []
    position = 0
    found = 0
    for match in _FUSION_LOCANT.finditer(text):
        if not _FUSION_PREFIX.search(text[: match.start()]):
            return None
        if not _FUSION_SUFFIX.match(text[match.end() :]):
            return None
        if _ROMAN_NUMERAL.match(match["locant"]):
            return None
        converted.append(text[position : match.start()])
        converted.append(f"[{match['locant']}]")
        position = match.end()
        found += 1
    if not found:
        return None
    converted.append(text[position:])
    rewritten = "".join(converted)
    # Every round bracket accounted for.  One left over means the name mixes a
    # locant with something this rule cannot read, and a name half in each
    # convention is a spelling nobody uses.
    if "(" in rewritten or ")" in rewritten:
        return None
    return rewritten.lower()


#: An oxidation state written as a bare Roman numeral after the element:
#: `Arsenic V`, `Cadmium II`.  The consensus list writes the same thing with
#: parentheses -- `Arsenic (v)`, `Cadmium (ii)` -- so the two never meet.
#:
#: The base is required to be a single alphabetic word because valence notation
#: is about elements, and that keeps the rule off anything else that happens to
#: end in a capital letter.  All ten of BAFU's are elements.
_VALENCE = re.compile(
    r"^(?P<element>[A-Za-z]+)\s+(?P<numeral>I{1,3}|IV|VI{0,2}|VII)$"
)

#: The charged form with no state given: `Iron, ion`.  The list writes an ion
#: as `<name> ion` where it names one at all, so the comma is the whole
#: difference.
_UNSPECIFIED_ION = re.compile(r"^(?P<base>[^,]+),\s*ions?$", re.IGNORECASE)


def valence_in_parentheses(name: str) -> str | None:
    """``"Arsenic V"`` -> ``"arsenic (v)"``; ``None`` if there is no valence.

    A Roman numeral after an element is its oxidation state -- how many
    electrons the atom has given up -- and it is not decoration.  Arsenic III
    and arsenic V behave differently in water and are characterised
    differently, which is why the list holds them as separate substances.

    Corroborated rather than invented: `Cadmium II`, `Chromium III`, `Mercury
    II` and `Nickel II` all match by CAS today, and the objects they land on are
    spelled `Cadmium (ii)`, `Chromium (iii)`, `Mercury (ii)` and `Nickel (ii)`.
    The parenthesised form is the list's own convention, read off its own data.
    """
    match = _VALENCE.match(name.strip()) if name else None
    if match is None:
        return None
    return f"{match['element']} ({match['numeral']})".lower()


def unspecified_ion(name: str) -> str | None:
    """``"Iron, ion"`` -> ``"iron ion"``; ``None`` if it is not that shape.

    Says the substance is dissolved and charged without saying what the charge
    is.  That is a real gap and this does not close it: the alias is the same
    claim in the spelling the list uses, and matching then finds a substance or
    does not.

    What it cannot do is attach a charged row to the **uncharged element**,
    which is the failure #286 names.  The guarantee is structural rather than a
    matter of getting six names right: the alias always ends in ` ion`, and
    every object in the list answering to `<name> ion` is a species that is an
    ion by definition -- the polyatomic anions, `Perchlorate`, `Sulfate`,
    `Chloride` and their kind.  A neutral element is spelled `Iron`, answers to
    `Iron`, and is never reached from here.

    So `Iron, ion` finds nothing, because the list holds `Iron(2+)` and
    `Iron(3+)` and neither answers to `iron ion` -- which is the right outcome
    for a row that does not say which one it is.
    """
    match = _UNSPECIFIED_ION.match(name.strip()) if name else None
    if match is None:
        return None
    base = match["base"].strip()
    return f"{base} ion".lower() if base else None


#: Every flow name a geography may be written onto, without the geography.
#:
#: A whitelist, and that is the whole safety of the rule.  A trailing
#: two-letter token is not rare in a flow name -- BAFU ships ``Silver, 0.007%
#: in sulfide, Ag 0.004%, Pb, Zn, Cd, In``, where `In` is indium and not India
#: -- so reading the *code* alone decides which of two chemistries a name has
#: by its capitalisation.  Requiring the part in front to be a label this list
#: already recognises means a name has to be a regionalised spelling of a flow
#: we hold before anything is stripped from it, and no amount of getting the
#: casing wrong can reach a substance.
#:
#: Read off BAFU 2026 v1, which is every list registered today whose names
#: SimaPro shaped.  Lower-cased because the caller's names are not:
#: enrichment hands back ``Water, Cooling, Unspecified Natural Origin`` where
#: the vendor shipped ``Water, cooling, unspecified natural origin``.
#:
#: A release that regionalises a flow this does not name will not strip it,
#: and will say so: ``test_the_rule_fires_on_every_name_bafu_ships`` pins the
#: count against the fetched list.  That is the intended failure -- a new base
#: label is a curation decision, not something to infer from a comma.
GEOGRAPHY_BASE_LABELS = frozenset(
    {
        "nitrogen dioxide",
        # AGRIBALYSE 3.2 writes a country or a region onto emissions and
        # withdrawals across nine bases beyond the land and water families
        # below -- 33 sulfur dioxide rows, 58 turbine-use water rows, seven
        # ammonia rows with the vendor's custom regions among them, and a
        # handful each of nitrate, nitrogen monoxide, phosphorus, sulfur
        # oxides, nitrogen oxides and the NMVOC bucket (#190, #192).  These
        # entries used to serve only the lookup, because no build ran the
        # splitter for this list; since the manifest says
        # `geography_split: "load"` they are load-bearing in a build too, and
        # the counts above are what phase 2 of
        # plans/simapro-row-preparation.md moved.
        "ammonia",
        "nitrate",
        "nitrogen monoxide",
        "nitrogen oxides",
        "nmvoc, non-methane volatile organic compounds",
        "phosphorus",
        "sulfur dioxide",
        "sulfur oxides",
        "water, turbine use, unspecified natural origin",
        # AGRIBALYSE 3.2 writes a country onto four of its land classes --
        # `Occupation, annual crop, CN` -- the same habit as BAFU's rail rows.
        "occupation, annual crop",
        "occupation, traffic area, rail network",
        "occupation, traffic area, rail/road embankment",
        "transformation, from annual crop",
        "transformation, from permanent crop",
        "transformation, to annual crop",
        "water",
        "water, cooling, unspecified natural origin",
        "water, embodied in product",
        "water, lake",
        "water, river",
        "water, unspecified",
        "water, unspecified natural origin",
        "water, well",
    }
)

#: ISO 3166-1 alpha-2, in full rather than the 76 BAFU happens to use.
#:
#: The standard is a closed vocabulary with a defined meaning for every member,
#: so admitting all of it costs nothing the base labels do not already guard --
#: and it is what keeps #65's "a BAFU release that adds a country does not need
#: the rule rewritten" true.
_ISO_3166_ALPHA_2 = frozenset(
    """
    AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD BE BF
    BG BH BI BJ BL BM BN BO BQ BR BS BT BV BW BY BZ CA CC CD CF CG
    CH CI CK CL CM CN CO CR CU CV CW CX CY CZ DE DJ DK DM DO DZ EC
    EE EG EH ER ES ET FI FJ FK FM FO FR GA GB GD GE GF GG GH GI GL
    GM GN GP GQ GR GS GT GU GW GY HK HM HN HR HT HU ID IE IL IM IN
    IO IQ IR IS IT JE JM JO JP KE KG KH KI KM KN KP KR KW KY KZ LA
    LB LC LI LK LR LS LT LU LV LY MA MC MD ME MF MG MH MK ML MM MN
    MO MP MQ MR MS MT MU MV MW MX MY MZ NA NC NE NF NG NI NL NO NP
    NR NU NZ OM PA PE PF PG PH PK PL PM PN PR PS PT PW PY QA RE RO
    RS RU RW SA SB SC SD SE SG SH SI SJ SK SL SM SN SO SR SS ST SV
    SX SY SZ TC TD TF TG TH TJ TK TL TM TN TO TR TT TV TW TZ UA UG
    UM US UY UZ VA VC VE VG VI VN VU WF WS YE YT ZA ZM ZW
    """.split()
)

#: The non-country groupings, admitted one at a time rather than in bulk.
#:
#: Unlike ISO 3166 these are a vendor's list with no standard behind them:
#: `RER` is ecoinvent's Europe and is not defined as the continent, `OECD` is
#: an economic grouping and not a place at all.  Each one is therefore a
#: decision that this project agrees it names a region, and the five here are
#: the five BAFU 2026 v1 ships.  Adding `RoW` -- which means "everywhere the
#: rest of this dataset does not cover", and so has no fixed extent -- would
#: need more thought than the others, and no registered list needs it.
_REGION_CODES = frozenset({
    "Europe", "GLO", "OECD", "RAF", "RER",
    # AGRIBALYSE 3.2 brings thirteen more, every one glossed by the vendor's
    # own comment on the rows that carry it (#192).  Six are ecoinvent
    # regions: `RAS` "Asia", `RNA` "Northern America", `RLA` "Latin America
    # and the Caribbean", `SAS` "South Asia", `RME` "Middle East", `WEU`
    # "Western Europe".  Six are United States electricity-grid regions --
    # `ASCC`, `HICC`, `RFC`, `SERC`, `TRE`, `WECC` -- and `UCTE` is the
    # European grid of the same vintage.  A grid region is a place the way a
    # country is for the accounting that wrote it: the row's water was drawn
    # wherever that grid generates.
    "RAS", "RNA", "RLA", "SAS", "RME", "WEU",
    "ASCC", "HICC", "RFC", "SERC", "TRE", "WECC", "UCTE",
})

#: A code the standard has withdrawn, and what to read it as instead.
#:
#: `CS` was Serbia and Montenegro, a state that dissolved in 2006 and whose
#: code ISO has since withdrawn.  BAFU still ships `Water, CS`, in 64 exchanges
#: with real amounts, so it cannot be treated as a dead entry -- it is read as
#: Serbia, which is the successor that kept the territory the flow's processes
#: sit in.
#:
#: This does not change any match: `Water, CS` and `Water, RS` both strip to
#: `water` and land on the same flow either way.  What it settles is the code
#: this project reports for the row, so that whatever publishes the geography
#: names a country that exists.
WITHDRAWN_GEOGRAPHY_CODES = {"CS": "RS"}

#: Every code a geography suffix may be spelled with.
GEOGRAPHY_CODES = frozenset(
    _ISO_3166_ALPHA_2 | _REGION_CODES | set(WITHDRAWN_GEOGRAPHY_CODES)
)

_GEOGRAPHY_CODES_BY_CASEFOLD = {code.casefold(): code for code in GEOGRAPHY_CODES}

#: The last comma-separated field of a name, which is where a geography goes.
#:
#: The comma may not be preceded by whitespace, so `Ammonia , NL` is left
#: alone -- a space before a comma is a typo, and a rule that reads through one
#: is guessing.  Unlike `flowmapper.fields.split_location_suffix`, whose shape
#: this follows, the space *after* the comma is optional: that requirement was
#: carrying the safety on its own there, and here the base-label whitelist
#: carries it, so a release that ships `Water,CH` is read rather than silently
#: skipped.
_GEOGRAPHY_SUFFIX = re.compile(r"(?<!\s),\s*(?P<code>[^,]+?)\s*$")


def split_geography_suffix(name: str) -> tuple[str, str] | None:
    """``"Water, AE"`` -> ``("Water", "AE")``; ``None`` if there is no geography.

    Where the water was taken is not what the water *is*, and this list records
    where a flow happened in the flow's context rather than in its name.  So a
    list that writes the place into the name has it read back out here: the 181
    regionalised names BAFU ships are spellings of eleven flows, and separating
    the two halves is what lets each row be the row its unregionalised sibling
    already is (#65).

    Both halves are returned exactly as the vendor spelled them.  The base
    because a caller wants the flow's name back, not a case-folded key -- and
    the **code as written**, not canonicalised, because this is what a caller
    keys identity on: `Water, CS` and `Water, RS` are two rows BAFU shipped,
    and resolving the first to the second here would fuse them the day a
    release puts both in one context.  :func:`canonical_geography_code` is the
    other half, and is a statement about the place rather than about the row.

    Matching is case-insensitive on both halves -- enrichment hands back `Water,
    Unspecified Natural Origin, KW` where the vendor shipped lower case.  What
    makes that safe is the base label rather than the capitalisation of the
    code: see :data:`GEOGRAPHY_BASE_LABELS`.
    """
    match = _GEOGRAPHY_SUFFIX.search(name.strip()) if name else None
    if match is None:
        return None
    written = match["code"]
    if written.casefold() not in _GEOGRAPHY_CODES_BY_CASEFOLD:
        return None
    base = name.strip()[: match.start()].strip()
    if base.casefold() not in GEOGRAPHY_BASE_LABELS:
        return None
    return base, written


def canonical_geography_code(code: str) -> str:
    """The place *code* names, with a withdrawn code resolved to its successor.

    Separate from :func:`split_geography_suffix` because the two answer
    different questions.  Splitting is syntax and belongs to the row: it says
    what the vendor wrote.  This is a curation decision and belongs to the
    place: it says `CS` -- Serbia and Montenegro, whose code ISO withdrew when
    the state dissolved in 2006 -- should be read as Serbia.

    Keeping them apart is what lets identity stay faithful to the vendor while
    what gets reported names a country that exists.
    """
    resolved = _GEOGRAPHY_CODES_BY_CASEFOLD.get(code.casefold(), code)
    return WITHDRAWN_GEOGRAPHY_CODES.get(resolved, resolved)


#: The unit, written into the name after a slash: ``Water/m3``, ``Wood,
#: unspecified, standing/kg``.  The slash has to be the last one and the tail a
#: single unbroken token, which is what keeps the shape off the names that
#: legitimately contain one -- BAFU's ``Occupation, traffic area, rail/road
#: embankment`` is four of them, and its tail has a space in it.  A tail with no
#: space would still have to be this row's unit to be read as one.
_UNIT_SUFFIX = re.compile(r"^(?P<name>.*\S)\s*/\s*(?P<unit>\S+)\s*$")


def name_without_unit_suffix(name: str, unit: str) -> str | None:
    """``("Water/m3", "m3")`` -> ``"Water"``; ``None`` if the tail is not the unit.

    SimaPro lists flows in one flat column keyed on names alone, so a substance
    measured two ways has to say which way in the name.  This list carries the
    unit as its own field, so the copy in the name says the same thing twice --
    and, being a copy, it is also why the row matches nothing: no flow object
    anywhere answers to a name with a unit stuck on the end (#67).

    The comparison is against the row's own unit and is case-insensitive but
    otherwise exact, which is the whole safety of it.  ``Gas, mine, off-gas,
    process, coal mining/m3`` measured in ``Nm3`` is declined: the name says one
    measure and the field says another, and which of them was meant is a
    curator's question rather than a pattern's.  It is answered in the list's
    manual fixes, which run first.

    Returns ``None`` when there is nothing to strip, so a caller can write the
    result back only where the rule fired.  Whether it *should* be written back
    is :func:`unit_suffix_rewrites`, which sees the rest of the list.
    """
    match = _UNIT_SUFFIX.match(name.strip()) if name and unit else None
    if match is None:
        return None
    if match["unit"].casefold() != unit.strip().casefold():
        return None
    return match["name"].strip() or None


def unit_suffix_rewrites(
    rows: Iterable[tuple[str, str]],
) -> dict[tuple[str, str], str]:
    """Which of *rows* lose the unit from their name.

    *rows* are ``(name, unit)`` pairs, and the answer is keyed on the pair
    rather than on the name: one list can ship the same name in two units, and
    each of those rows has to be asked about its own unit rather than about the
    name they share.

    **A suffix comes off wherever it is a copy of the row's own unit**, and
    there is no case where it stays.  That is a change of reading, so it is
    worth saying what it replaces.  This used to decline a pair of rows that
    would strip to one name in two different units -- on the ground that the
    suffix was the only thing telling them apart, and that BAFU's process water
    in ``kg`` beside the same name in ``m3`` counts two different things: 63 of
    the release's datasets carry both spellings in ``resources / land``, and the
    mass there is a fixed 6.6e-05 of what the volume implies rather than the
    1/1000 a density would give.

    The measurement stands; the conclusion drawn from it does not.  A flow's
    identity is its substance and its context, ``(flow_object_id,
    context_iri)`` is unique, and the unit is not in it -- so two rows that
    agree on a substance and a compartment reach one flow whatever their names
    say, and they always did.  Declining the suffix kept two *names* apart above
    a single flow, which bought nothing and cost the rows their match: a name
    with a unit stuck on the end reaches no flow object in any list.  Whether
    the two rows should be one quantity is a real question and this is not where
    it is answered -- it is answered by a curator reading the vendor's archive
    and stating a conversion in that list's manual fixes, as
    `bafu-2026-v1-manual-fixes.json` does for standing wood at 0.00204 m3/kg and
    for water at 1000 kg/m3.  (#67, #78)
    """
    return {
        (name, unit): base
        for name, unit in rows
        if (base := name_without_unit_suffix(name, unit)) is not None
    }


#: The steps :func:`prepare_row_for_matching` runs, in the order it runs them.
#:
#: Named rather than left implicit so a prepared row can say which habits were
#: undone, and so a step added here is a step a caller sees the name of.
#: The third step is not a split: it is the lineage's curated corrections
#: (`simapro-lineage-manual-fixes.json`) applied to a lookup query, reported
#: here because a caller reads one tuple to learn what was done to their row.
LINEAGE_FIX_STEP = "lineage-fix"
PREPARATION_STEPS: tuple[str, ...] = ("unit-suffix", "geography", LINEAGE_FIX_STEP)


@dataclass(frozen=True)
class PreparedRow:
    """A row's name as matching should see it, and what came out of the name.

    :attr:`shipped_name` is the spelling the caller sent, and is set only where
    it differs from :attr:`name`.  It is not decoration: `_strip_unit_suffixes`
    keeps the vendor's spelling as a synonym for the same reason, because a name
    a rule rewrote is still a name the row is known by and dropping it would
    lose the one label a curated synonym might have been written against.

    :attr:`location` is the place the geography split took out.  Nothing in
    matching reads it -- a `SourceRow` has no such field, and the place only
    ever seeded BAFU's flow uuid and the land-class identity of #290 -- so it is
    returned to be reported rather than to be matched on.
    """

    name: str
    #: The name as the caller wrote it, where a step rewrote it.
    shipped_name: str = ""
    #: The place taken out of the name, spelled as the caller wrote it.
    location: str = ""
    #: Which of :data:`PREPARATION_STEPS` fired, in order.
    steps: tuple[str, ...] = ()


def prepare_row_for_matching(name: str, unit: str) -> PreparedRow:
    """Both splits at once, for a row that reached matching by no other route.

    The two splits run at two points of a *build*, and the module docstring
    above says why each is where it is.  Neither point exists for somebody who
    hands this project a row and asks where it goes: there is no adapter, so
    nothing read the geography out, and there is no `load_flows`, so nothing
    took the unit back out of the name.  The row arrives spelled the way SimaPro
    spells it, and reaches `resolve_flow_object` under a name no flow object in
    any list answers to -- which is not "we do not hold this substance", it is
    the question never having been asked.

    So this is the third point, and it exists for the callers who have neither
    of the first two.  It is the same two functions in the order a build reaches
    them, which is the order they have to be in: ``Water, AE/m3`` is a unit
    stuck on a regionalised name, and taking the place off first leaves ``Water/
    m3`` with the geography rule looking at ``m3``.

    Only ever call this for a list whose ``simapro_origin`` is true, like
    everything else here.

    Idempotent, and that matters more here than it looks: a caller may well hand
    over rows some of which an exporter already split.  A name with nothing left
    to take off comes back unchanged, with no steps recorded.

    >>> prepare_row_for_matching("Wood, unspecified, standing/m3", "m3").name
    'Wood, unspecified, standing'
    >>> prepare_row_for_matching("Wood, unspecified, standing/m3", "kg").name
    'Wood, unspecified, standing/m3'
    """
    prepared, steps = name.strip(), []
    location = ""

    if (stripped := name_without_unit_suffix(prepared, unit)) is not None:
        prepared = stripped
        steps.append("unit-suffix")

    if split := split_geography_suffix(prepared):
        prepared, location = split
        steps.append("geography")

    if not steps:
        return PreparedRow(name=name.strip())
    return PreparedRow(
        name=prepared,
        shipped_name=name.strip(),
        location=location,
        steps=tuple(steps),
    )


def simapro_name_aliases(name: str) -> list[str]:
    """Every other spelling of *name* that SimaPro's habits imply.

    The entry point a caller should use, rather than any single rule: the
    habits are a set, and a caller that asked for one by name would have to be
    edited to gain the others.

    Only the aliases.  The two splits -- the geography (#65) and the unit
    (#67) -- are not offered here, because by the time a caller reaches this
    there is no suffix left to offer a spelling for.  What guarantees that is
    the row having been *prepared*: a build prepares it at the two points the
    module docstring names, and everybody else calls
    :func:`prepare_row_for_matching`.  A caller who skips it does not get a
    weaker answer here, it gets none -- the aliases are rules about a substance's
    name, and none of them recognises one with a unit stuck on the end.

    Only ever call this for a list whose ``simapro_origin`` is true.

    Returns an empty list for a name no habit recognises, which is most of
    them.  Never returns *name* itself, so a caller can add the result as
    alternative labels without checking for the one it already has.
    """
    return _aliases_from(name, _ALIAS_RULES)


def systematic_name_aliases(name: str) -> list[str]:
    """The subset of :func:`simapro_name_aliases` that is nomenclature.

    A spelling produced by these two rules is a *systematic chemical name*: it
    is built from the parent compound and what is attached to it, by a rule
    that fires only on the syntax of one -- an attachment hyphen, a fusion
    locant in brackets.  Neither can produce a trade name, a catalogue code or
    an ordinary English phrase, because neither reads a name that is one.

    That is a narrower claim than "this list's habits imply this spelling", and
    the merge needs the two apart.  ``Ethene, 1,1-dichloro-`` rewrites to
    `1,1-dichloroethene`, which the list holds as a synonym of
    1,1-dichloroethylene rather than as its published name, and
    :func:`~brightway_flows.merge.matching._narrow_label_candidates`
    otherwise refuses a synonym as evidence against a substance that carries a
    registry number -- the refusal that stops `Granite` reaching Penoxsulam and
    `Propylene Carbonate` reaching Talc, both through a shared catalogue code
    somebody wrote in a name field.  A systematic name cannot be either of
    those things, so it is admitted where a shipped name is not (#103).

    :func:`deinvert_phrase_name` is deliberately absent.  `Clay, Bentonite` ->
    `bentonite clay` is an ordinary English phrase, which is exactly the
    territory a trade name occupies, and the argument above does not reach it;
    that row is corrected by a curated registry number instead.
    :func:`valence_in_parentheses` and :func:`unspecified_ion` are absent for a
    duller reason -- no row in the three merged lists needs them here, so
    nothing measured says what admitting them would do.
    """
    return _aliases_from(name, _SYSTEMATIC_ALIAS_RULES)


#: The rules whose output is nomenclature rather than another way of saying the
#: same words.  See :func:`systematic_name_aliases` for what turns on it.
_SYSTEMATIC_ALIAS_RULES = (
    deinvert_cas_index_name,
    bracket_fusion_locants,
)

#: Every rule, systematic first so a caller reading `labels_used` sees the
#: strongest spelling first.
_ALIAS_RULES = (
    *_SYSTEMATIC_ALIAS_RULES,
    deinvert_phrase_name,
    valence_in_parentheses,
    unspecified_ion,
)


def _aliases_from(name: str, rules: tuple[Callable[[str], str | None], ...]) -> list[str]:
    """*rules* applied to *name*, deduplicated, never returning *name* itself."""
    aliases: list[str] = []
    for rule in rules:
        if (alias := rule(name)) is not None:
            aliases.append(alias)
    lowered = name.strip().lower()
    return [alias for alias in dict.fromkeys(aliases) if alias and alias != lowered]
