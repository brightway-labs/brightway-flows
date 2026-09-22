"""A resource correction is a negative amount of the resource it corrects (#69).

BAFU 2026 ships eleven names ending in `resource correction`, in fourteen rows,
all of them in the resources compartment.  Read as names they look like
bookkeeping that no flow list should carry -- there is no "gravel resource
correction" anybody could go and measure -- and #69 raised them on that basis,
alongside the energy carriers `tests/test_bafu_energy_carriers.py` covers.

What they are is stated by BAFU itself, in the general comment of one of the
datasets that carries one: "Resource correction added for share of primary
aluminium for KBOB recommendation 2016."  A dataset built with recycled material
books a correction against the primary extraction charged upstream of it.  The
correction and the extraction are one quantity written in two places, and it is
their *sum* that is the extraction that happened -- which only comes out right
if both land on one flow.

Measured over all 11,947 datasets in the BAFU 2026 ecoSpold release:

- The eleven names appear 363 times.  341 of those amounts are negative; the 22
  positive ones are all sand or gravel in asphalt layers, so a correction
  adjusts the primary share in either direction rather than only crediting it.
- The resource being corrected is almost never in the same dataset: 3 of 45 for
  aluminium, 2 of 23 for zinc, 3 of 72 for biomass energy, and 0 for the other
  eight names.  A row that does not accompany the extraction it corrects is a
  credit against an extraction charged somewhere else, which is precisely the
  case that needs the two on one flow.
- Where both do appear together, the correction is -0.61 to -0.67 times the
  resource for aluminium and -0.17 to -0.19 for biomass energy: a recycled
  share, not a second measurement of the same material.

**Nine of the eleven need nothing from this project.**  BAFU writes the
resource's own registry number on them -- `Aluminium, resource correction`
carries 7429-90-5, `Sand, resource correction` carries 14808-60-7 -- so the
merge puts them on the resource's flow object by CAS, and has all along.  That
is the vendor stating the equivalence itself, and it is what decides the
question for the other two rather than any judgement made here.

**The two exceptions are the two whose resource carries no number.**  BAFU's own
`Gravel` row has none, and an amount of energy has none to carry, so there was
nothing for the correction to inherit and each minted a substance of its own:
`Gravel, Resource Correction` on `fo-5fa16bb1526bea87`, and the biomass energy
one on `fo-988f31a6ca1dda16`, both with no formula, no mass and no structure.
`bafu-2026-v1-manual-fixes.json` gives each the name the base list knows the
resource by, which is the same instrument #74 used for the resource itself and
for the same reason: with no identifier on either side, the shared string is the
only evidence there is.

The quieter cost of leaving them alone was arithmetic rather than tidiness.  A
minted flow carries no characterisation factor, so a negative amount on it
scores zero, and the recycled-content credit BAFU wrote silently stopped
working.  Publishing them as separate flows -- the other option #69 offered --
would have kept that fault and made it permanent.

`Carbon dioxide, non-fossil, resource correction` is deliberately not part of
this family.  It is a biogenic-carbon device that ecoinvent itself ships as a
distinct flow and this list follows, which is why `qualifiers.py` detects
`biogenic_resource_correction` at all; these eleven are amounts of a resource,
and the merge treats them as such.
"""

import unittest

import orjson

from brightway_flows.manual_fixes import apply_manual_fixes
from brightway_flows.pipeline.loading import _normalize_input_flow_record
from brightway_flows.sources import base_source_list, known_source_lists

#: Every BAFU name ending in `resource correction`, and the BAFU name of the
#: resource each one corrects.  Asserted as a whole set: a twelfth arriving is a
#: row nobody has looked at, and it should fail here rather than be swept in.
CORRECTIONS = {
    "Aluminium, resource correction": "Aluminium",
    "Chromium, resource correction": "Chromium",
    "Copper, resource correction": "Copper",
    "Energy, gross calorific value, in biomass, resource correction":
        "Energy, gross calorific value, in biomass",
    "Gravel, resource correction": "Gravel",
    "Iron, resource correction": "Iron",
    "Lead, resource correction": "Lead",
    "Nickel, resource correction": "Nickel",
    "Sand, resource correction": "Sand",
    "Tin, resource correction": "Tin",
    "Zinc, resource correction": "Zinc",
}

#: The nine BAFU numbers itself, and the number it writes on each.  These reach
#: the resource's flow object by CAS with nothing curated, and they are the
#: evidence the other two rest on.
NUMBERED = {
    "Aluminium, resource correction": "7429-90-5",
    "Chromium, resource correction": "7440-47-3",
    "Copper, resource correction": "7440-50-8",
    "Iron, resource correction": "7439-89-6",
    "Lead, resource correction": "7439-92-1",
    "Nickel, resource correction": "7440-02-0",
    "Sand, resource correction": "14808-60-7",
    "Tin, resource correction": "7440-31-5",
    "Zinc, resource correction": "7440-66-6",
}

#: The two with no number, and the name the base list knows their resource by.
#: `gravel` is EF 3.1's own spelling of BAFU's `Gravel`; `biomass` is what EF
#: calls the energy in a forest's wood, which is #74's finding.
BY_NAME = {
    "Gravel, resource correction": ("gravel", "kg"),
    "Energy, gross calorific value, in biomass, resource correction": ("biomass", "MJ"),
}

#: Copper and nickel are corrected in datasets where BAFU ships no resource row
#: of its own, so there is no BAFU row to compare their number against -- only
#: the base list's.
NO_BAFU_RESOURCE_ROW = {"Copper", "Nickel"}


def _load():
    """BAFU's rows with the curated fixes applied, and the base list's rows."""
    bafu = known_source_lists().get("bafu-2026-v1")
    if bafu is None:
        raise unittest.SkipTest("BAFU 2026 v1 is not registered")
    base = base_source_list()
    missing = [s.key for s in (bafu, base) if not s.flows_path.exists()]
    if missing:
        raise unittest.SkipTest(f"flows not fetched for {', '.join(sorted(missing))}")

    rows = orjson.loads(bafu.flows_path.read_bytes())
    apply_manual_fixes(rows, bafu.manual_fixes_path, label=bafu.key)
    normalized = [
        _normalize_input_flow_record(row, source_hint=bafu.key) or row for row in rows
    ]
    return normalized, orjson.loads(base.flows_path.read_bytes())


class ResourceCorrectionTestCase(unittest.TestCase):
    """Shared loading, so the archive is read once for the whole file."""

    @classmethod
    def setUpClass(cls):
        cls.bafu_rows, cls.base_rows = _load()

    def _rows_named(self, name):
        return [row for row in self.bafu_rows if row.get("name") == name]

    def _resource_rows(self, name):
        return [
            row for row in self._rows_named(name)
            if (row.get("context") or [""])[0] == "resources"
        ]

    def _labels(self, row):
        """The names the merge looks a row up by: what it shipped, plus synonyms."""
        return {
            str(label).strip().lower()
            for label in (str(row.get("name") or ""), *(row.get("synonyms") or ()))
        }

    def _cas(self, row):
        return list(row.get("cas_numbers") or ())


class TheFamilyTestCase(ResourceCorrectionTestCase):
    """The eleven names, and what they have in common."""

    def test_bafu_ships_the_eleven_names_this_is_about(self):
        """A twelfth is a decision to make, not a member to inherit."""
        shipped = {
            str(row.get("name") or "")
            for row in self.bafu_rows
            if "resource correction" in str(row.get("name") or "").lower()
        }
        self.assertEqual(shipped, set(CORRECTIONS))

    def test_every_correction_is_filed_as_a_resource(self):
        """Which is why the merge reads them as resources in the first place."""
        for name in CORRECTIONS:
            with self.subTest(name):
                rows = self._rows_named(name)
                self.assertTrue(rows)
                for row in rows:
                    self.assertEqual((row.get("context") or [""])[0], "resources")

    def test_every_correction_is_measured_in_its_resources_unit(self):
        """A correction in another unit would not be an amount of the resource.

        Copper and nickel have no BAFU resource row to compare against, so they
        are checked against the base list's flow instead, further down.
        """
        for name, resource in CORRECTIONS.items():
            if resource in NO_BAFU_RESOURCE_ROW:
                continue
            with self.subTest(name):
                units = {str(row.get("unit") or "") for row in self._rows_named(name)}
                resource_units = {
                    str(row.get("unit") or "") for row in self._resource_rows(resource)
                }
                self.assertTrue(resource_units)
                self.assertEqual(units, resource_units)

    def test_bafu_keeps_its_own_spelling_everywhere(self):
        """Nothing here renames a row: what BAFU published is what it published.

        `bootstrap_labels` reads a row's name and its synonyms when the row is
        matched and then purges both, so a curated string is read by the merge
        and published nowhere, while `source_refs` keeps the vendor's name.
        """
        for name in CORRECTIONS:
            with self.subTest(name):
                for row in self._rows_named(name):
                    self.assertEqual(row.get("name"), name)


class TheVendorsOwnNumbersTestCase(ResourceCorrectionTestCase):
    """Nine corrections carry the resource's registry number, and always did.

    This is the whole basis of the decision in #69: BAFU numbers a correction
    as the substance it corrects wherever it has a number to write, so a
    correction is an amount of that substance in the vendor's own account of it.
    Nothing is curated for these; they are asserted because they are the
    evidence, and because a build that stopped putting them on the resource
    would change what the two curated rows below mean.
    """

    def test_each_numbered_correction_carries_that_number(self):
        for name, cas in NUMBERED.items():
            with self.subTest(name):
                for row in self._rows_named(name):
                    self.assertEqual(self._cas(row), [cas])

    def test_the_number_is_the_one_bafu_puts_on_the_resource_itself(self):
        for name, cas in NUMBERED.items():
            resource = CORRECTIONS[name]
            if resource in NO_BAFU_RESOURCE_ROW:
                continue
            with self.subTest(name):
                rows = self._resource_rows(resource)
                self.assertTrue(rows)
                for row in rows:
                    self.assertEqual(self._cas(row), [cas])

    def test_bafu_ships_no_resource_row_for_the_two_exceptions(self):
        """So `test_the_number_is_the_one_...` cannot be vacuously skipped.

        Copper and nickel are corrected in datasets that do not extract them,
        and BAFU ships no `Copper` or `Nickel` resource row at all.  Their
        number is checked against the base list instead.
        """
        for resource in sorted(NO_BAFU_RESOURCE_ROW):
            with self.subTest(resource):
                self.assertEqual(self._resource_rows(resource), [])

    def test_the_base_list_carries_every_one_of_those_numbers(self):
        """A number no flow object answers to would match nothing."""
        base_cas = {
            cas
            for row in self.base_rows
            for cas in (row.get("cas_numbers") or ())
        }
        for name, cas in NUMBERED.items():
            with self.subTest(name):
                self.assertIn(cas, base_cas)


class TheTwoWithNoNumberTestCase(ResourceCorrectionTestCase):
    """`Gravel` and the energy in a forest's wood, matched on their names.

    These are the two rows `bafu-2026-v1-manual-fixes.json` touches.  Each is
    given the name the base list knows its resource by, so it reaches the same
    flow object the resource reaches -- by label, because there is no number on
    either side to reach it by.
    """

    def test_neither_correction_carries_a_number(self):
        """Which is why a name is all there is to match them on."""
        for name in BY_NAME:
            with self.subTest(name):
                for row in self._rows_named(name):
                    self.assertEqual(self._cas(row), [])

    def test_neither_resource_carries_one_either(self):
        """The reason, and not a coincidence: there was nothing to inherit."""
        for name in BY_NAME:
            resource = CORRECTIONS[name]
            with self.subTest(resource):
                rows = self._resource_rows(resource)
                self.assertTrue(rows)
                for row in rows:
                    self.assertEqual(self._cas(row), [])

    def test_each_is_looked_up_under_the_name_the_base_list_knows(self):
        """The whole of the fix: one shared string, and the merge does the rest."""
        for name, (base_name, _) in BY_NAME.items():
            with self.subTest(name):
                rows = self._rows_named(name)
                self.assertTrue(rows)
                for row in rows:
                    self.assertIn(base_name, self._labels(row))

    def test_the_resource_is_looked_up_under_that_same_name(self):
        """So the two land on one object rather than merely on similar ones.

        `Gravel` reaches EF's `gravel` under its own spelling; the biomass row
        reaches EF's `biomass` under the synonym #74 gave it.
        """
        for name, (base_name, _) in BY_NAME.items():
            resource = CORRECTIONS[name]
            with self.subTest(resource):
                for row in self._resource_rows(resource):
                    self.assertIn(base_name, self._labels(row))

    def test_the_base_list_ships_that_flow_in_the_same_unit(self):
        """And carries no number on it, which is what makes a label match safe.

        `_narrow_label_candidates` keeps a label hit on a flow object with no
        CAS and rejects an alternative-label hit on one that has a CAS, so the
        route these two take exists only because neither side is numbered.
        """
        for name, (base_name, unit) in BY_NAME.items():
            with self.subTest(base_name):
                flows = [
                    row for row in self.base_rows
                    if str(row.get("name") or "").lower() == base_name
                ]
                self.assertEqual(len(flows), 1)
                self.assertEqual(flows[0].get("unit"), unit)
                self.assertEqual(list(flows[0].get("cas_numbers") or ()), [])
                self.assertEqual(
                    {str(row.get("unit") or "") for row in self._rows_named(name)},
                    {unit},
                )

    def test_the_biomass_correction_is_filed_in_two_compartments(self):
        """Both follow the resource, one onto EF's flow and one onto a new one.

        `biotic` reaches EF's `biomass` flow directly.  EF carries nothing in
        `unspecified`, so that row joins the flow the resource's own unspecified
        row creates under the shared object -- a created flow is keyed on its
        object and its context, and the second row to reach one joins it.  A
        third compartment would reach the object unread, so it is asserted.
        """
        name = "Energy, gross calorific value, in biomass, resource correction"
        self.assertEqual(
            {tuple(row.get("context") or ()) for row in self._rows_named(name)},
            {("resources", "biotic"), ("resources", "unspecified")},
        )

    def test_the_gravel_correction_is_filed_where_gravel_is(self):
        name = "Gravel, resource correction"
        self.assertEqual(
            {tuple(row.get("context") or ()) for row in self._rows_named(name)},
            {tuple(row.get("context") or ()) for row in self._resource_rows("Gravel")},
        )
