"""What a substance name looks like, decided from the name alone.

Every predicate here is a pure function of its arguments: no source tables, no
network, no state.  That is the whole point of the module -- these are the
cheapest checks matching makes and the ones most often reused, so they are kept
where they can be read and tested without constructing a transformer.
"""

from __future__ import annotations

from brightway_flows.pipeline import normalize

# Maps Greek stereo-descriptor letters to their ASCII equivalents so that
# "β-hexachlorocyclohexane" and "beta-hexachlorocyclohexane" compare equal.
# Public because the qualifier-loss shortlist in `curation` needs the same
# equivalence and must not keep a second copy of it: a rename that only respells
# `alpha-` as `α-` would otherwise read as a dropped stereo descriptor.
GREEK_TO_ASCII = str.maketrans({
    "α": "alpha",
    "β": "beta",
    "γ": "gamma",
    "δ": "delta",
    "ε": "epsilon",
    "ζ": "zeta",
    "η": "eta",
    "θ": "theta",
})

MIXTURE_KEYWORDS = {
    "mixture",
    "mix",
    "reaction mass",
    "extract",
    "fraction",
    "solution",
    "preparation",
    "blend",
    "isomeric mixture",
    "petroleum",
    "sludge",
    "oil",
    "waste",
    "alloy",
}

CLASS_KEYWORDS = {
    "compounds",
    "compound",
    "amines",
    "amides",
    "salts",
    "derivatives",
    "extract",
    "oils",
    "products",
    "reaction products",
}


def normalize_stereo(s: str) -> str:
    """Lowercase + collapse whitespace after converting Greek stereo letters to ASCII."""
    return normalize(s.translate(GREEK_TO_ASCII))


def is_mixture_like(text: str) -> bool:
    lowered = text.lower()
    if any(k in lowered for k in MIXTURE_KEYWORDS):
        return True
    if ";" in lowered or " / " in lowered:
        return True
    return False


def is_class_like(text: str) -> bool:
    lowered = text.lower()
    return any(k in lowered for k in CLASS_KEYWORDS)


def contains_isomer_locants(text: str) -> bool:
    return any(ch.isdigit() for ch in text) and "," in text


def alpha_only(text: str) -> str:
    return "".join(ch for ch in text.lower() if ch.isalpha())


def is_exact_name_match_for_group(group_name: str, candidate_name: str) -> bool:
    """Return True when candidate looks like the exact base substance name."""
    g_norm = normalize(group_name)
    c_norm = normalize(candidate_name)
    if g_norm == c_norm:
        return True
    if is_mixture_like(candidate_name):
        return False
    if alpha_only(group_name) == alpha_only(candidate_name):
        g_loc = locant_signature(group_name)
        c_loc = locant_signature(candidate_name)
        if not g_loc or not c_loc or g_loc == c_loc:
            return True
    return False


def locant_signature(text: str) -> tuple[str, ...]:
    out: list[str] = []
    token = ""
    for ch in text:
        if ch.isdigit() or ch == ",":
            token += ch
        elif token:
            out.append(token.strip(","))
            token = ""
    if token:
        out.append(token.strip(","))
    return tuple(out)


def normalize_chebi_id(value: str) -> str:
    text = value.strip()
    if not text:
        return ""
    lowered = text.lower()
    if "chebi:" in lowered:
        suffix = text.split(":", 1)[1].strip()
        return f"CHEBI:{suffix}"
    if "chebi_" in lowered:
        suffix = text.rsplit("_", 1)[1].strip()
        return f"CHEBI:{suffix}"
    if text.isdigit():
        return f"CHEBI:{text}"
    return text.upper()
