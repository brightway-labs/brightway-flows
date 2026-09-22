"""A label's bare ``m`` names a convention, not a state letter.

An inventory writes one letter for an excited state. The nuclear data uses
several, ordered by excitation energy: PubChem spells them ``m``, ``n``, ``p``,
``q`` and ChemLIN spells the same ones ``m``, ``m1``, ``m2``, ``m3``. Energy
order is not lifetime order, so the state a source can actually inventory --
the one that lives long enough to be measured -- is not reliably the one spelled
``m``.

Silver-110 is the case, and the whole of it: of the 74 mass numbers this list
carries it is the only one whose ground state is outlived by an excited state.
PubChem files the 249.863-day state as ``110Agn`` and gives ``110Agm`` to a
660-nanosecond state no inventory reports, so reading the letter literally would
answer ``Silver-110m`` with the 660 ns row -- a worse record than the ground
state it replaced, and one none of the checks in `_nuclide_record_checks` can
see, because an isomer decaying by isomeric transition is what an isomer does
(#24).

The convention is already stated in ``element_cache`` for the ChemLIN slugs.
These pin it on the PubChem side, and pin that applying it moves nothing else.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from brightway_flows.filesystem import PUBCHEM_ELEMENTS_CACHE_FILEPATH
from brightway_flows.domain.nuclides import Nuclide, parse_nuclide
from brightway_flows.flow_layers.elements import _resolve_metastable_state

#: The cache in *this* data directory, not the platform one: a worktree points
#: `BRIGHTWAY_FLOWS_DATA_DIR` at its own, and a test that reads past it is
#: reading a file this worktree may not be using.
CACHE = PUBCHEM_ELEMENTS_CACHE_FILEPATH

#: Every isomer the published list carries today. The correction must be a
#: no-op for all of them, or it is not a correction.
LISTED_ISOMERS = (
    "Kr-85m", "Xe-133m", "Tc-99m", "Te-123m", "Xe-131m", "Xe-135m", "Pa-234m",
)


def _isomer_index() -> dict[tuple[str, int], list[tuple[Nuclide, str]]]:
    """The index `elements` builds, from the same cache and the same parser."""
    index: dict[tuple[str, int], list[tuple[Nuclide, str]]] = {}
    for element in json.loads(CACHE.read_text())["elements"]:
        for row in element.get("isotope_decay", []):
            nuclide = parse_nuclide(str(row.get("nuclide") or ""), symbol=element["symbol"])
            if nuclide is None or nuclide.is_ground_state:
                continue
            index.setdefault((nuclide.symbol, nuclide.mass_number), []).append(
                (nuclide, str(row.get("half_life_and_uncertainty") or ""))
            )
    return index


def _split(key: str) -> tuple[str, int, str]:
    symbol, _, rest = key.partition("-")
    digits = "".join(c for c in rest if c.isdigit())
    return symbol, int(digits), rest[len(digits):]


class ResolutionTestCase(unittest.TestCase):
    """The choice itself, against a hand-built index."""

    #: `110Agm` is the first excited state by energy and lasts 660 ns;
    #: `110Agn` is the second and lasts 249.863 days.
    SILVER = {
        ("Ag", 110): [
            (Nuclide("Ag", 110, "m"), "660 ns ± 40"),
            (Nuclide("Ag", 110, "n"), "249.863 d ± 0.024"),
        ]
    }

    def test_a_bare_m_takes_the_longest_lived_state(self):
        got, resolution = _resolve_metastable_state(
            Nuclide("Ag", 110, "m"), isomers_by_symbol_mass=self.SILVER
        )
        self.assertEqual(got, Nuclide("Ag", 110, "n"))
        self.assertEqual(resolution["strategy"], "longest_lived_metastable_state")
        self.assertEqual(resolution["claimed_state"], "m")
        self.assertEqual(resolution["selected_state"], "n")

    def test_the_candidates_it_chose_between_are_recorded(self):
        """The resolution is published on the object. A choice a curator
        cannot see the alternatives to is not reviewable."""
        _got, resolution = _resolve_metastable_state(
            Nuclide("Ag", 110, "m"), isomers_by_symbol_mass=self.SILVER
        )
        self.assertEqual(
            [c["nuclide"] for c in resolution["candidates"]], ["Ag-110m", "Ag-110n"]
        )
        self.assertEqual(
            resolution["candidates"][1]["half_life_and_uncertainty"], "249.863 d ± 0.024"
        )

    def test_a_named_state_is_looked_up_as_written(self):
        """`n` is a state, not a convention. Only the bare `m` is a request for
        whichever state the source could have meant."""
        for state in ("n", "m1", "m2"):
            with self.subTest(state=state):
                got, resolution = _resolve_metastable_state(
                    Nuclide("Ag", 110, state), isomers_by_symbol_mass=self.SILVER
                )
                self.assertEqual(got.state, state)
                self.assertEqual(resolution["strategy"], "state_taken_as_written")

    def test_a_ground_state_is_untouched(self):
        got, resolution = _resolve_metastable_state(
            Nuclide("Ag", 110), isomers_by_symbol_mass=self.SILVER
        )
        self.assertEqual(got, Nuclide("Ag", 110))
        self.assertEqual(resolution["strategy"], "state_taken_as_written")

    def test_a_single_excited_state_is_not_a_choice(self):
        got, resolution = _resolve_metastable_state(
            Nuclide("Tc", 99, "m"),
            isomers_by_symbol_mass={("Tc", 99): [(Nuclide("Tc", 99, "m"), "6.0066 h ± 0.0002")]},
        )
        self.assertEqual(got, Nuclide("Tc", 99, "m"))
        self.assertEqual(resolution["strategy"], "state_taken_as_written")
        self.assertEqual(resolution["candidates"], [])

    def test_a_state_with_no_readable_half_life_does_not_win_by_default(self):
        """`half_life_days` returns None for a half-life it cannot read, and
        the unreadable one must sort last rather than compare as larger."""
        got, _resolution = _resolve_metastable_state(
            Nuclide("Ag", 110, "m"),
            isomers_by_symbol_mass={
                ("Ag", 110): [
                    (Nuclide("Ag", 110, "m"), "660 ns ± 40"),
                    (Nuclide("Ag", 110, "n"), ""),
                ]
            },
        )
        self.assertEqual(got, Nuclide("Ag", 110, "m"))

    def test_a_mass_number_with_no_excited_state_is_untouched(self):
        got, resolution = _resolve_metastable_state(
            Nuclide("Ag", 110, "m"), isomers_by_symbol_mass={}
        )
        self.assertEqual(got, Nuclide("Ag", 110, "m"))
        self.assertEqual(resolution["strategy"], "state_taken_as_written")


class CachedTableTestCase(unittest.TestCase):
    """The same choice against the real table, which is what the run reads."""

    def setUp(self):
        if not CACHE.exists():
            self.skipTest("PubChem element cache not present in this data directory")
        self.index = _isomer_index()

    def test_silver_110m_is_the_249_day_state(self):
        got, resolution = _resolve_metastable_state(
            Nuclide("Ag", 110, "m"), isomers_by_symbol_mass=self.index
        )
        self.assertEqual(got.key, "Ag-110n")
        self.assertEqual(resolution["strategy"], "longest_lived_metastable_state")

    def test_every_isomer_the_list_carries_is_unmoved(self):
        """The seven isomers already published all have `m` as their
        longest-lived state, so this changes no record that exists today."""
        for key in LISTED_ISOMERS:
            with self.subTest(nuclide=key):
                symbol, mass, state = _split(key)
                got, resolution = _resolve_metastable_state(
                    Nuclide(symbol, mass, state), isomers_by_symbol_mass=self.index
                )
                self.assertEqual(got.key, key)
                self.assertEqual(resolution["strategy"], "state_taken_as_written")

    def test_silver_110_is_the_only_one_of_them_this_list_carries(self):
        """Across all 118 elements, 162 mass numbers have an excited state that
        outlives the one PubChem spells `m`, so the convention is not a
        one-nuclide special case and is not written as one. What makes it safe
        to apply now is that silver-110 is the only one of the 162 this list has
        a flow for: every other nuclide it carries either has no isomer or has
        `m` as the longest-lived. A label naming one of the other 161 would be
        resolved the same way, and would be a new decision to review rather than
        a silent rebinding of an existing record."""
        moved = {
            f"{symbol}-{mass}"
            for (symbol, mass) in self.index
            if _resolve_metastable_state(
                Nuclide(symbol, mass, "m"), isomers_by_symbol_mass=self.index
            )[1]["strategy"] == "longest_lived_metastable_state"
        }
        self.assertIn("Ag-110", moved)
        self.assertEqual(
            sorted(key for key in LISTED_ISOMERS if key.rstrip("m") in moved), []
        )


#: The fixes files that have to carry the correction, discovered rather than
#: listed: for five months this test named `ecoinvent-3.12-manual-fixes.json`
#: alone, and the four other registered ecoinvent versions went on shipping the
#: bare label with nothing to say so (#26).  A version added tomorrow is
#: covered by the glob without anyone remembering this file.
FIXES_DIR = Path(__file__).resolve().parent.parent / "src/brightway_flows/data"
SILVER_LABELS = {"ef-3.1-manual-fixes.json": ("silver-110", "silver-110m")}
FIXES_FILENAMES = ["ef-3.1-manual-fixes.json"] + sorted(
    path.name for path in FIXES_DIR.glob("ecoinvent-*-manual-fixes.json")
)


class ManualFixTestCase(unittest.TestCase):
    """The label correction the resolution exists to make safe."""

    def _fixes(self, name: str) -> list[dict]:
        return json.loads((FIXES_DIR / name).read_text())["fixes"]

    def test_every_list_is_corrected_to_the_isomer(self):
        """One list corrected and the other not is worse than neither: the two
        would then disagree about which nuclide this is, and the merge would
        have to arbitrate between them.  Every registered ecoinvent version
        ships the bare label, so every one of them has to state the correction
        -- which is what #26 was."""
        for filename in FIXES_FILENAMES:
            original, corrected = SILVER_LABELS.get(
                filename, ("Silver-110", "Silver-110m")
            )
            with self.subTest(list=filename):
                fixes = [
                    fix
                    for fix in self._fixes(filename)
                    if fix.get("match", {}).get("name") == original
                    and fix.get("field") == "name"
                ]
                self.assertEqual(len(fixes), 1)
                self.assertEqual(fixes[0]["new_value"], corrected)
                self.assertEqual(fixes[0]["original_value"], original)

    def test_the_cas_is_left_alone(self):
        """14391-76-5 is indexed as `Silver, isotope of mass 110` -- a mass
        number, not a nuclear state -- so it does not contradict the corrected
        label, and no cited number for the isomer exists to replace it with."""
        for filename in FIXES_FILENAMES:
            with self.subTest(list=filename):
                self.assertEqual(
                    [
                        fix
                        for fix in self._fixes(filename)
                        if "14391-76-5" in (
                            str(fix.get("original_value")) + str(fix.get("remove_value"))
                        )
                    ],
                    [],
                )


if __name__ == "__main__":
    unittest.main()
