"""The 138 impact categories, and the identifiers they are published under.

Four implementations of EF 3.1 -- the JRC's, the ecoinvent Centre's,
GreenDelta's and this list's own judgement -- times the 25 categories they each
render, plus two implementations of Stepwise 2006 -- its own publisher's and
ours -- times its 19.  What these
pin is everything a consumer would hold in a query:

* the IRI of every one of the 138, in full, because a minted IRI is a promise and
  `tests/test_source_list.py` is the precedent for pinning every one;
* that the id is `uuid5` of the IRI, so the identifier a reader dereferences and
  the identifier a table joins on cannot come apart;
* that the method file's 25 JRC method UUIDs are exactly the 25 in
  `lcia-methods.json`, so a category EF renames in a later release fails a test
  rather than silently ceasing to match;
* that `midpoint_endpoint` is stated on all 138 rather than left to the record's
  default, which is `ENDPOINT`: wrong for every EF category, and right for
  exactly five of Stepwise's;
* that `timeframe` is `LONG` on all 138, which is what publishing only the full
  set means (`plans/lcia-factors.md` section 2.4);
* that all 138 say what their number means, and say whose words those are
  wherever no publisher of the method wrote them.

The other half of the crosswalk -- that the 25 ecoinvent triples are exactly the
ones the workbook's `Indicators` sheet lists under `EF v3.1` -- is asserted where
the workbook is read, which is the change that adds a reader for it.
"""

import tempfile
import unittest
from dataclasses import fields, replace
from pathlib import Path

import orjson

from brightway_flows.domain.lcia import crosswalk
from brightway_flows.domain.lcia.crosswalk import (
    IMPACT_CATEGORIES_FILEPATH,
    STEPWISE_IMPACT_CATEGORIES_FILEPATH,
    by_stated_method_category,
    ef_method,
    impact_categories,
    lcia_method,
    lcia_methods,
)
from brightway_flows.domain.lcia.records import (
    AreaOfProtection,
    CharacterizationFactor,
    ImpactCategoryCharacterizationFactorMismatch,
    ImpactTimeframe,
    MidpointEndpoint,
)
from brightway_flows.domain.units import known_unit_iris
from brightway_flows.filesystem import LCIA_METHODS_FILEPATH
from brightway_flows.lcia import (
    impact_categories_for,
    impact_category_id,
    published_impact_categories,
    published_method,
)
from brightway_flows.lcia.categories import _category

#: EF 3.1's four implementations, by slug, in file order.
JRC, ECOINVENT, GREENDELTA, CONSENSUS = (
    "jrc",
    "ecoinvent-centre",
    "greendelta",
    "brightway-flows",
)

#: What ecoinvent's workbook calls the method this list ingests.
ECOINVENT_METHOD = "EF v3.1"

_PREFIX = "https://vocab.brightway.one/lcia/impact-category/ef/3.1"

#: The 25 slugs, in crosswalk order.  Written out rather than read from the
#: crosswalk, so that a renamed slug fails here: a slug is the last segment of a
#: published IRI and is not a display name.
SLUGS: tuple[str, ...] = (
    "acidification",
    "climate-change",
    "climate-change-biogenic",
    "climate-change-fossil",
    "climate-change-land-use",
    "particulate-matter",
    "ecotoxicity-freshwater",
    "ecotoxicity-freshwater-inorganics",
    "ecotoxicity-freshwater-organics",
    "eutrophication-marine",
    "eutrophication-freshwater",
    "eutrophication-terrestrial",
    "human-toxicity-cancer",
    "human-toxicity-cancer-inorganics",
    "human-toxicity-cancer-organics",
    "human-toxicity-non-cancer",
    "human-toxicity-non-cancer-inorganics",
    "human-toxicity-non-cancer-organics",
    "ionising-radiation-human-health",
    "land-use",
    "ozone-depletion",
    "photochemical-ozone-formation-human-health",
    "resource-use-fossils",
    "resource-use-minerals-and-metals",
    "water-use",
)

_STEPWISE_PREFIX = "https://vocab.brightway.one/lcia/impact-category/stepwise-2006/2006"

#: Stepwise 2006's 19 slugs, in crosswalk order, written out for the same reason
#: as EF's: a slug is the last segment of a published IRI, not a display name.
STEPWISE_SLUGS: tuple[str, ...] = (
    "acidification",
    "economic-costs",
    "ecotoxicity-aquatic",
    "ecotoxicity-terrestrial",
    "eutrophication-aquatic",
    "eutrophication-terrestrial",
    "global-warming-fossil",
    "global-warming-non-fossil",
    "human-toxicity-carcinogens",
    "human-toxicity-non-carcinogens",
    "injuries-road-or-work",
    "ionizing-radiation",
    "mineral-extraction",
    "nature-occupation",
    "non-renewable-energy",
    "ozone-layer-depletion",
    "photochemical-ozone-vegetation",
    "respiratory-inorganics",
    "respiratory-organics",
)

#: Every published impact-category IRI, stated as the five segments it is made
#: of rather than as one string, so that a change to any segment -- the
#: implementation's name, the timeframe, a slug -- is a failure here rather than
#: a silent renaming of 138 published identifiers.
#:
#: `acidification` and `eutrophication-terrestrial` appear under both methods,
#: which is the point of the method segment: one slug, two categories, counted
#: in different units from different models.
PUBLISHED_IRIS: tuple[str, ...] = tuple(
    f"{_PREFIX}/{implementation}/long/{slug}"
    for implementation in (
        "jrc", "ecoinvent-centre", "greendelta", "brightway-flows",
    )
    for slug in SLUGS
) + tuple(
    f"{_STEPWISE_PREFIX}/{implementation}/long/{slug}"
    for implementation in ("twenty-zero-lca", "brightway-flows")
    for slug in STEPWISE_SLUGS
)

#: One id per implementation, stated as a literal.  The other 96 follow from
#: `uuid5` over the IRI, which the IRIs above pin -- but the namespace the hash
#: is taken in does not appear in an IRI, and these four are what would catch a
#: change to it.
PINNED_IDS: dict[str, str] = {
    f"{_PREFIX}/jrc/long/acidification": "7507f0b3-eb52-5e00-aa33-c7e640bdae50",
    f"{_PREFIX}/greendelta/long/acidification": (
        "c3042d91-346d-54a7-a094-83a928813c13"
    ),
    f"{_PREFIX}/ecoinvent-centre/long/acidification": (
        "2e55a9ec-4781-5eaf-9523-af49223e7fc8"
    ),
    f"{_PREFIX}/brightway-flows/long/acidification": (
        "4cda840f-abce-5935-ac63-3ddae34df76e"
    ),
}

#: The four aggregates and what each sums.  Measured over the build of
#: 2026-08-16: across 137,621 flows where an aggregate and at least one of its
#: parts are both stated, the aggregate equals the sum of the parts present
#: exactly, every time.
AGGREGATES: dict[str, tuple[str, ...]] = {
    "Climate change": (
        "Climate change-Fossil",
        "Climate change-Biogenic",
        "Climate change-Land use and land use change",
    ),
    "Ecotoxicity, freshwater": (
        "Ecotoxicity, freshwater_organics",
        "Ecotoxicity, freshwater_inorganics",
    ),
    "Human toxicity, cancer": (
        "Human toxicity, cancer_organics",
        "Human toxicity, cancer_inorganics",
    ),
    "Human toxicity, non-cancer": (
        "Human toxicity, non-cancer_organics",
        "Human toxicity, non-cancer_inorganics",
    ),
}


def _replacing(definition, **changes):
    """A crosswalk row with one field changed, for the malformed-file cases."""
    fields = {name: getattr(definition, name) for name in definition.__slots__}
    return definition.__class__(**{**fields, **changes})


class CrosswalkTestCase(unittest.TestCase):
    """What `data/lcia-impact-categories.json` has to say."""

    def test_twenty_five_categories(self):
        """EF 3.1's own, and the registry's total beside it.

        `impact_categories()` is every method's, so asserting 25 of it stopped
        being a claim about EF the moment a second method was registered.
        """
        self.assertEqual(len(ef_method().categories), 25)
        self.assertEqual(len(lcia_method("stepwise-2006").categories), 19)
        self.assertEqual(len(impact_categories()), 44)

    def test_every_row_is_addressable_three_ways(self):
        """By slug, by the JRC's method UUID, and by ecoinvent's category name.

        Each of the three is a key a later pass joins on, and a duplicate in any
        of them is a factor set silently landing on the wrong category.
        """
        method = ef_method()
        self.assertEqual(len({category.slug for category in method.categories}), 25)
        self.assertEqual(len(method.by_stated_identifier(JRC)), 25)
        self.assertEqual(len(method.by_stated_name(ECOINVENT)), 25)

    def test_the_slugs_are_the_published_ones(self):
        self.assertEqual(
            tuple(category.slug for category in ef_method().categories), SLUGS
        )

    def test_every_reference_unit_is_a_unit(self):
        """15 distinct units, all of them in `units.json`.

        The unit table already carries all of them; somebody added `CTUe`,
        `CTUh`, `SQI`, `DI` and the rest for exactly this, so nothing here mints
        a unit.
        """
        iris = {category.unit_iri for category in ef_method().categories}
        self.assertEqual(len(iris), 15)
        self.assertEqual(iris - known_unit_iris(), set())
        # Stepwise 2006's sixteen. Thirteen were minted for it; the euro it
        # takes from the vocabulary, which already had one; and two it shares
        # with EF 3.1 -- the kilogram of CO2-eq and the kilogram of CFC-11-eq
        # are the same units, not lookalikes, however differently the two
        # methods spell them (#346).
        stepwise = {
            category.unit_iri
            for category in lcia_method("stepwise-2006").categories
        }
        self.assertEqual(len(stepwise), 16)
        self.assertEqual(stepwise - known_unit_iris(), set())
        self.assertEqual(
            {iri.rsplit("/", 1)[-1] for iri in stepwise & iris},
            {"KiloGM-CO2eq", "KiloGM-CFC11eq"},
        )

    def test_every_area_of_protection_is_decided(self):
        """None of the 25 is `UNKNOWN`.

        EF's own `impactCategory` field would leave `Water use` there -- it
        gives the string `other` -- and an area of protection nobody decided is
        the question going back to being unanswerable.
        """
        for category in impact_categories():
            with self.subTest(category.name):
                self.assertIsInstance(category.area_of_protection, AreaOfProtection)
                self.assertNotEqual(
                    category.area_of_protection, AreaOfProtection.UNKNOWN
                )

    def test_a_judgement_carries_its_argument(self):
        """`Water use` is the one that needed an argument, and states one."""
        water = next(c for c in impact_categories() if c.name == "Water use")
        self.assertEqual(water.area_of_protection, AreaOfProtection.ASSETS)
        self.assertIn("AWARE", water.comment)

    def test_the_aggregates_say_what_they_sum(self):
        parts = {c.name: tuple(c.parts) for c in impact_categories() if c.parts}
        self.assertEqual(parts, AGGREGATES)

    def test_an_aggregate_and_its_parts_share_a_group(self):
        by_name = {category.name: category for category in impact_categories()}
        for whole, parts in AGGREGATES.items():
            for name in (whole, *parts):
                with self.subTest(name):
                    self.assertIsNotNone(by_name[name].category_group)
                    self.assertEqual(
                        by_name[name].category_group, by_name[whole].category_group
                    )

    def test_only_the_full_ecoinvent_method_is_crosswalked(self):
        """`EF v3.1 no LT` states no number `EF v3.1` does not, and is not one
        of the implementations this list publishes."""
        for category in ef_method().categories:
            with self.subTest(category.name):
                self.assertEqual(category.stated[ECOINVENT].method, ECOINVENT_METHOD)
                self.assertNotIn("no LT", category.stated[ECOINVENT].name)

    def test_every_row_says_what_ecoinvent_called_it_under_ef30(self):
        """ecoinvent 3.8 ships EF v3.0, and a score computed with it has to
        find its way to one of our 25 rows.  Every row carries the earlier
        spelling; one of them differs -- `photochemical ozone formation`
        against 3.1's `oxidant` -- and three EF 3.0 categories, the `metals`
        halves of the toxicity families, have no row at all."""
        index = by_stated_method_category()
        for category in ef_method().categories:
            with self.subTest(category.name):
                earlier = category.earlier[ECOINVENT]
                self.assertEqual([row.method for row in earlier], ["EF v3.0"])
                self.assertIs(index[("EF v3.0", earlier[0].name)], category)
                self.assertIs(
                    index[("EF v3.1", category.stated[ECOINVENT].name)], category
                )
        self.assertEqual(
            index[("EF v3.0", "photochemical ozone formation: human health")].slug,
            "photochemical-ozone-formation-human-health",
        )
        self.assertNotIn(("EF v3.0", "ecotoxicity: freshwater, metals"), index)

    def test_the_file_holds_what_the_loader_returns(self):
        payload = orjson.loads(IMPACT_CATEGORIES_FILEPATH.read_bytes())
        self.assertEqual(len(payload["categories"]), 25)
        self.assertEqual(payload["method"]["slug"], "ef")
        self.assertEqual(
            [row["slug"] for row in payload["implementations"]],
            [JRC, ECOINVENT, GREENDELTA, CONSENSUS],
        )

    def test_the_registered_methods(self):
        """Two methods are loaded, and the registry is what says so.

        Order matters: it is the order the methods are published in, and the
        order `PUBLISHED_IRIS` is written in.
        """
        self.assertEqual(
            [method.slug for method in lcia_methods()], ["ef", "stepwise-2006"]
        )

    def test_the_roles_are_one_reference_and_one_consensus(self):
        method = ef_method()
        self.assertEqual(method.reference.slug, JRC)
        self.assertEqual(method.consensus.slug, CONSENSUS)
        self.assertEqual(
            [row.slug for row in method.transcriptions],
            [JRC, ECOINVENT, GREENDELTA],
        )

    def test_every_implementation_says_where_its_factors_come_from(self):
        method = ef_method()
        self.assertEqual(
            {row.slug: str(row.factors.route) for row in method.implementations},
            {
                JRC: "published-flows",
                ECOINVENT: "source-list",
                GREENDELTA: "source-list",
                CONSENSUS: "derived",
            },
        )
        self.assertEqual(
            {row.slug: row.factors.source_list for row in method.implementations},
            {
                JRC: "EF-3.1",
                ECOINVENT: "ecoinvent-3.12",
                GREENDELTA: "bafu-2026-v1",
                CONSENSUS: "",
            },
        )
        self.assertEqual(
            method.implementation(ECOINVENT).factors.stated_method, ECOINVENT_METHOD
        )

    def test_only_two_of_the_four_decide_anything(self):
        """Everything transcribed is compared; only a deciding implementation is
        evidence. GreenDelta's is here to be compared with (#157)."""
        method = ef_method()
        self.assertEqual([row.slug for row in method.deciding], [JRC, ECOINVENT])
        self.assertFalse(method.implementation(GREENDELTA).decides)
        self.assertTrue(method.reference.decides)
        self.assertFalse(method.consensus.decides)

    def test_greendelta_kept_the_jrc_identifiers_and_says_so(self):
        """Their package transcribed the ILCD files and left the UUIDs in place,
        which is why their factors are filed by identity rather than by their own
        names -- `Ecotoxicity freshwater (organics)` is theirs alone."""
        method = ef_method()
        self.assertEqual(method.implementation(GREENDELTA).identifiers_from, JRC)
        for category in method.categories:
            with self.subTest(category.name):
                self.assertEqual(
                    category.stated[GREENDELTA].identifier,
                    category.stated[JRC].identifier,
                )


class PublishedCategoryTestCase(unittest.TestCase):
    """The 100 records, and the identifiers they carry."""

    def test_each_method_publishes_its_categories_once_per_implementation(self):
        """EF 3.1's 25 times four, and Stepwise 2006's 19 times two.

        Two rather than four is not an omission: one publisher renders Stepwise,
        so it has a reference implementation and ours and nothing in between.
        """
        self.assertEqual(len(published_impact_categories()), 138)
        for slug, categories, implementations in (
            ("ef", 25, 4),
            ("stepwise-2006", 19, 2),
        ):
            method = lcia_method(slug)
            with self.subTest(slug):
                self.assertEqual(len(method.implementations), implementations)
                for implementation in method.implementations:
                    self.assertEqual(
                        len(impact_categories_for(slug, implementation.slug)),
                        categories,
                    )

    def test_every_published_iri(self):
        iris = tuple(
            category.meta["iri"] for category in published_impact_categories()
        )
        self.assertEqual(iris, PUBLISHED_IRIS)

    def test_an_id_is_the_hash_of_its_iri(self):
        for category in published_impact_categories():
            with self.subTest(category.meta["iri"]):
                self.assertEqual(category.id, impact_category_id(category.meta["iri"]))

    def test_the_pinned_ids(self):
        by_iri = {c.meta["iri"]: c for c in published_impact_categories()}
        for iri, expected in PINNED_IDS.items():
            with self.subTest(iri):
                self.assertEqual(str(by_iri[iri].id), expected)

    def test_no_two_categories_share_an_identifier(self):
        categories = published_impact_categories()
        self.assertEqual(len({category.id for category in categories}), 138)
        self.assertEqual(len({category.meta["iri"] for category in categories}), 138)

    def test_each_category_carries_its_own_method_and_version(self):
        """One `method` record per method, shared by its categories.

        `assertIs` rather than `assertEqual`: two categories of one method point
        at one record, and a category that built its own would publish a second
        method with the same name.
        """
        for slug in ("ef", "stepwise-2006"):
            record = published_method(slug)
            definition = lcia_method(slug)
            for implementation in definition.implementations:
                for category in impact_categories_for(slug, implementation.slug):
                    with self.subTest(category.meta["iri"]):
                        self.assertIs(category.method, record)
                        self.assertEqual(category.method.name, definition.name)
                        self.assertEqual(category.version, definition.version)

    def test_every_category_says_what_its_number_means(self):
        """All 138 publish an indicator, and say whose words it is where no
        publisher of the method wrote one.

        EF 3.1's are the JRC's and the ecoinvent Centre's, transcribed. Stepwise
        2006's one publisher states none -- the SimaPro export it ships in gives
        a category as `name;unit` and nothing else -- so each of its 19 carries
        the words of whoever defined the quantity it is counted in: EDIP 2003's
        "area of unprotected ecosystem" for acidification, IMPACT 2002+'s
        reference substance for the toxicities, the method's own documentation
        for the categories it added. `indicator_source` names them, and appears
        only where the words are not a publisher's statement.
        """
        for category in published_impact_categories():
            with self.subTest(category.meta["iri"]):
                self.assertTrue(category.indicator)
        for implementation in (JRC, ECOINVENT, GREENDELTA, CONSENSUS):
            for category in impact_categories_for("ef", implementation):
                with self.subTest(implementation, category=category.name):
                    self.assertNotIn("indicator_source", category.meta)
        method = lcia_method("stepwise-2006")
        for implementation in method.implementations:
            published = impact_categories_for(method.slug, implementation.slug)
            for definition, category in zip(
                method.categories, published, strict=True
            ):
                with self.subTest(implementation.slug, category=category.name):
                    self.assertEqual(category.indicator, definition.indicator.words)
                    self.assertEqual(
                        category.meta["indicator_source"],
                        definition.indicator.source,
                    )

    def test_an_indicator_nobody_states_is_none(self):
        """Not an empty string, which reads as a publisher who stated an
        indicator and left it blank."""
        payload = orjson.loads(STEPWISE_IMPACT_CATEGORIES_FILEPATH.read_bytes())
        del payload["categories"][0]["indicator"]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "method.json"
            path.write_bytes(orjson.dumps(payload))
            method = crosswalk._read(path)
        record = published_method(method.slug)
        for implementation in method.implementations:
            category = _category(
                method, method.categories[0], implementation, record
            )
            with self.subTest(implementation.slug):
                self.assertIsNone(category.indicator)
                self.assertNotIn("indicator_source", category.meta)

    def test_a_category_says_where_along_the_chain_it_stops(self):
        """Every EF 3.1 category is a midpoint; five of Stepwise 2006's are not.

        Stepwise carries all nineteen forward to quality-adjusted life years and
        to euros, so the method as a whole is an endpoint method; what this field
        says is where each category's own number stops. The five counted in a
        damage unit -- an unprotected ecosystem area, a disappeared fraction, a
        fatal injury, a euro -- stop at the end (#346).
        """
        endpoint = {
            category.name
            for category in published_impact_categories()
            if category.midpoint_endpoint is MidpointEndpoint.ENDPOINT
        }
        self.assertEqual(
            endpoint,
            {
                "Acidification",
                "Economic costs",
                "Eutrophication, terrestrial",
                "Injuries, road or work",
                "Nature occupation",
            },
        )
        for category in impact_categories_for("ef", "jrc"):
            with self.subTest(category.meta["iri"]):
                self.assertEqual(
                    category.midpoint_endpoint, MidpointEndpoint.MIDPOINT
                )

    def test_every_category_is_long_term(self):
        for category in published_impact_categories():
            with self.subTest(category.meta["iri"]):
                self.assertEqual(category.timeframe, ImpactTimeframe.LONG)

    def test_no_category_carries_factors_yet(self):
        """The categories are built here; the factors are matched elsewhere."""
        for category in published_impact_categories():
            with self.subTest(category.meta["iri"]):
                self.assertEqual(category.characterization_factors, [])

    def test_a_unit_is_an_iri(self):
        """A unit is named the way every other unit reference in this project
        names one: by its IRI in `units.json`, not by a second identifier."""
        for category in published_impact_categories():
            with self.subTest(category.meta["iri"]):
                self.assertIsInstance(category.unit_iri, str)
                self.assertTrue(category.unit_iri.startswith("https://"))

    def test_each_implementation_carries_what_only_it_knows(self):
        """Under keys that do not repeat the implementation's name: the bag is
        already its own, and `jrc_method_uuid` inside the JRC's metadata promises
        a `foo_method_uuid` for every implementation added later."""
        self.assertTrue(
            all(
                "method_uuid" in category.meta
                for category in impact_categories_for("ef", JRC)
            )
        )
        self.assertTrue(
            all(
                "release" in category.meta
                for category in impact_categories_for("ef", ECOINVENT)
            )
        )
        self.assertTrue(
            all(
                "stated_name" in category.meta
                for implementation in (JRC, ECOINVENT)
                for category in impact_categories_for("ef", implementation)
            ),
            "what a publisher calls this category is one key across publishers, "
            "which is what makes the two comparable",
        )
        self.assertTrue(
            all(
                set(category.meta) == {"iri"}
                for category in impact_categories_for("ef", CONSENSUS)
            ),
            "the consensus implementation has no publisher metadata to carry",
        )

    def test_the_method_uuids_are_the_ones_ef_shipped(self):
        """The crosswalk's 25 against `lcia-methods.json`, as `extract` wrote it."""
        if not LCIA_METHODS_FILEPATH.exists():
            self.skipTest(f"{LCIA_METHODS_FILEPATH} has not been extracted here")
        shipped = orjson.loads(LCIA_METHODS_FILEPATH.read_bytes())
        index = ef_method().by_stated_identifier(JRC)
        self.assertEqual({m["uuid"] for m in shipped}, set(index))
        by_uuid = {method["uuid"]: method for method in shipped}
        for method_uuid, category in index.items():
            with self.subTest(category.name):
                self.assertEqual(
                    by_uuid[method_uuid]["name"], category.stated[JRC].name
                )


class MalformedMethodFileTestCase(unittest.TestCase):
    """A malformed method file raises where it is read, and is never skipped.

    Through the reader itself rather than through a helper: what a file is
    allowed to say is what `crosswalk._read` accepts, and a test that built
    records directly would be checking a check nobody runs.
    """

    def _read(self, change) -> None:
        """Read EF's file with *change* applied, from a directory of its own."""
        payload = orjson.loads(IMPACT_CATEGORIES_FILEPATH.read_bytes())
        change(payload)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "method.json"
            path.write_bytes(orjson.dumps(payload))
            crosswalk._read(path)

    def test_an_indicator_that_names_no_source_raises(self):
        def change(payload):
            payload["categories"][0]["indicator"] = {
                "words": "Accumulated Exceedance (AE)"
            }

        with self.assertRaisesRegex(ValueError, "source"):
            self._read(change)

    def test_an_indicator_of_ours_beside_the_publishers_raises(self):
        """The JRC states one for acidification, so ours would never be read."""

        def change(payload):
            payload["categories"][0]["indicator"] = {
                "words": "Accumulated Exceedance (AE)",
                "source": "Seppälä et al. 2006",
            }

        with self.assertRaisesRegex(ValueError, "never"):
            self._read(change)

    def test_a_part_no_row_defines_raises(self):
        def change(payload):
            payload["categories"][0]["parts"] = ["A category nobody defines"]

        with self.assertRaises(ValueError):
            self._read(change)

    def test_a_category_that_sums_itself_raises(self):
        def change(payload):
            payload["categories"][0]["parts"] = [payload["categories"][0]["name"]]

        with self.assertRaises(ValueError):
            self._read(change)

    def test_an_unknown_unit_raises(self):
        def change(payload):
            payload["categories"][0]["unit_iri"] = (
                "https://vocab.brightway.one/units/unit/NotAUnit"
            )

        with self.assertRaises(ValueError):
            self._read(change)

    def test_a_second_row_under_one_slug_raises(self):
        def change(payload):
            payload["categories"][1]["slug"] = payload["categories"][0]["slug"]

        with self.assertRaises(ValueError):
            self._read(change)

    def test_two_rows_under_one_publisher_name_raise(self):
        """One name a publisher's factor rows carry, two of our categories: the
        rows would land on whichever the index happened to keep."""

        def change(payload):
            payload["categories"][1]["stated"][ECOINVENT]["name"] = payload[
                "categories"
            ][0]["stated"][ECOINVENT]["name"]

        with self.assertRaises(ValueError):
            self._read(change)

    def test_two_rows_under_one_method_uuid_raise(self):
        def change(payload):
            payload["categories"][1]["stated"][JRC]["identifier"] = payload[
                "categories"
            ][0]["stated"][JRC]["identifier"]

        with self.assertRaises(ValueError):
            self._read(change)

    def test_an_earlier_spelling_of_the_ingested_method_is_refused(self):
        def change(payload):
            payload["categories"][0]["earlier"][ECOINVENT][0]["method"] = (
                ECOINVENT_METHOD
            )

        with self.assertRaises(ValueError):
            self._read(change)

    def test_two_rows_claiming_one_earlier_category_raise(self):
        def change(payload):
            payload["categories"][1]["earlier"] = payload["categories"][0]["earlier"]

        with self.assertRaises(ValueError):
            self._read(change)

    def test_a_row_missing_a_name_raises(self):
        def change(payload):
            del payload["categories"][0]["name"]

        with self.assertRaises(ValueError):
            self._read(change)

    def test_a_second_reference_implementation_raises(self):
        def change(payload):
            payload["implementations"][1]["role"] = "reference"

        with self.assertRaises(ValueError):
            self._read(change)

    def test_no_consensus_implementation_raises(self):
        def change(payload):
            payload["implementations"] = payload["implementations"][:3]

        with self.assertRaises(ValueError):
            self._read(change)

    def test_a_consensus_implementation_under_another_name_raises(self):
        def change(payload):
            payload["implementations"][3]["name"] = "somebody else"

        with self.assertRaises(ValueError):
            self._read(change)

    def test_a_transcription_that_derives_its_factors_raises(self):
        """Only ours is derived, and ours is only derived."""

        def change(payload):
            payload["implementations"][1]["factors"] = {"from": "derived"}

        with self.assertRaises(ValueError):
            self._read(change)

    def test_an_implementation_with_no_factor_route_raises(self):
        def change(payload):
            del payload["implementations"][1]["factors"]

        with self.assertRaises(ValueError):
            self._read(change)

    def test_an_implementation_that_does_not_say_whether_it_decides_raises(self):
        def change(payload):
            del payload["implementations"][1]["decides"]

        with self.assertRaises(ValueError):
            self._read(change)

    def test_a_reference_that_does_not_decide_raises(self):
        def change(payload):
            payload["implementations"][0]["decides"] = False

        with self.assertRaises(ValueError):
            self._read(change)

    def test_a_consensus_implementation_that_decides_raises(self):
        def change(payload):
            payload["implementations"][3]["decides"] = True

        with self.assertRaises(ValueError):
            self._read(change)

    def test_a_borrowed_identifier_that_stopped_matching_raises(self):
        """A package that mints its own UUIDs is a join that has to be written."""

        def change(payload):
            payload["categories"][0]["stated"][GREENDELTA]["identifier"] = (
                "11111111-2222-3333-4444-555555555555"
            )

        with self.assertRaises(ValueError):
            self._read(change)

    def test_identifiers_from_an_undeclared_implementation_raises(self):
        def change(payload):
            payload["implementations"][2]["identifiers_from"] = "nobody"

        with self.assertRaises(ValueError):
            self._read(change)

    def test_a_category_naming_an_undeclared_implementation_raises(self):
        def change(payload):
            payload["categories"][0]["stated"]["nobody"] = {"name": "x"}

        with self.assertRaises(ValueError):
            self._read(change)


class CategoryHoldsItsOwnFactorsTestCase(unittest.TestCase):
    """A category refuses a factor that names a different one.

    The half of the uniqueness rule a record can check about itself: a factor
    listed under one category and linked to another is a factor nobody can find.
    The other half -- one factor per (flow, geography, category) -- cannot be
    seen from one category and belongs where the rows are written.
    """

    def setUp(self):
        self.category = impact_categories_for("ef", JRC)[0]
        self.other = impact_categories_for("ef", ECOINVENT)[0]

    def _factor(self, impact_category_id):
        return CharacterizationFactor(
            elementary_flow_uuid="ef-3.1-flow",
            impact_category_id=impact_category_id,
            amount=1.0,
        )

    def test_a_factor_is_identified_by_its_triple_and_nothing_else(self):
        """No `id` field, deliberately: the category, the flow and the place are
        what make a factor one, and that is the primary key the table declares.
        A fourth identifier would publish two identities for one row."""
        self.assertNotIn(
            "id", {field.name for field in fields(CharacterizationFactor)}
        )

    def test_a_factor_naming_this_category_is_held(self):
        held = self._factor(self.category.id)
        rebuilt = replace(self.category, characterization_factors=[held])
        self.assertEqual(rebuilt.characterization_factors, [held])

    def test_a_factor_naming_another_category_raises(self):
        with self.assertRaises(ImpactCategoryCharacterizationFactorMismatch):
            replace(
                self.category,
                characterization_factors=[self._factor(self.other.id)],
            )


if __name__ == "__main__":
    unittest.main()
