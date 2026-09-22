"""The homepage at `/`.  Step 8 of `plans/public-site.md`.

What is pinned here is what the Home boards cannot show:

- **`/` is the homepage, and `/docs/` is still the documentation.**  Every link
  written into an issue or a commit points at `/docs/`.
- **Every number is the build's.**  The counts and the example card are read
  at request time, never copied from the board (`AGENTS.md` rule 31); with no
  database they are left out, not shown as 0 (§4).
- **Every undecided fact is a placeholder** (§0's first rule): the version.
- **The "Start here" questions are among the ones `docs/index.md` asks.**  The
  same questions are published in two places, and a test is what keeps them
  one list.
- **The homepage has one search box.**  The masthead's is left off it.

The `/` shortcut reaching the lookup box is `app.js`'s and was checked in a
browser.
"""

import dataclasses
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from markupsafe import escape
from test_webapp_download_about import _decided, _undecided
from test_webapp_sections import _elementary, _flow, _flow_object, _write_fixture

from brightway_flows.domain.flow_object import FlowObject
from brightway_flows.domain.vocabulary import (
    CHEMINF_CAS_REGISTRY_NUMBER,
    CHEMROF_INCHI2D_KEY_STRING,
    CHEMROF_IUPAC_NAME,
    CHEMROF_MOLECULAR_FORMULA,
    CHEMROF_MOLECULAR_MASS,
    CHEMROF_MONOISOTOPIC_MASS,
    CHEMROF_SMILES_STRING,
)
from brightway_flows.webapps.app import create_app, db, documentation, start
from brightway_flows.webapps.app.queries import home as queries
from brightway_flows.webapps.app.views import home as view

DOCS_ROOT = Path(__file__).resolve().parent.parent / "docs"

CO2_KEY = "CURLTUGMZLYLDI-UHFFFAOYSA-N"

#: What `enrich_references` records for carbon dioxide, in the shape it writes
#: it: four registries the card links to, one it does not (ECHA is among the
#: dozens PubChem cross-references), a second ChEBI identifier for the same
#: substance, and a ChEBI xref whose prefix has no expansion.
CO2_REFERENCES = [
    "https://pubchem.ncbi.nlm.nih.gov/compound/280",
    {"@id": "https://www.ebi.ac.uk/chebi/searchId.do?chebiId=CHEBI:16526"},
    {"@id": "https://www.ebi.ac.uk/chebi/searchId.do?chebiId=CHEBI:48898"},
    {"@id": "https://commonchemistry.cas.org/detail?cas_rn=124-38-9"},
    {"@id": "https://www.wikidata.org/wiki/Q1997"},
    {"@id": "https://chem.echa.europa.eu/100.004.271"},
    "Beilstein:1900390",
]

#: Hexafluoroethane's, from the same build.  Two CAS Common Chemistry URLs and
#: only one of them this substance's number: `_links` has to pick 76-16-4, the
#: number the card prints, over the one the URL ordering puts first.
C2F6_REFERENCES = [
    {"@id": "https://www.ebi.ac.uk/chebi/searchId.do?chebiId=CHEBI:32905"},
    {"@id": "https://commonchemistry.cas.org/detail?cas_rn=60720-23-2"},
    {"@id": "https://commonchemistry.cas.org/detail?cas_rn=76-16-4"},
    {"@id": "https://pubchem.ncbi.nlm.nih.gov/compound/6431"},
    {"@id": "https://pubchem.ncbi.nlm.nih.gov/erg/#2193"},
    {"@id": "https://www.wikidata.org/wiki/Q417035"},
]

#: Paraquat's, from the same build.
PARAQUAT_REFERENCES = [
    {"@id": "https://www.ebi.ac.uk/chebi/searchId.do?chebiId=CHEBI:34905"},
    {"@id": "https://commonchemistry.cas.org/detail?cas_rn=4685-14-7"},
    {"@id": "https://pubchem.ncbi.nlm.nih.gov/compound/15939"},
    {"@id": "https://www.wikidata.org/wiki/Q26841324"},
]


def _ref(list_name, list_version, name, number):
    return {
        "list_name": list_name,
        "list_version": list_version,
        "source_flow_uuid": f"src-{list_name}-{number}",
        "source_flow_name": name,
    }


def _example_object(flow_object_id, name, *, cas, inchikey, smiles, formula,
                    iupac, mass, monoisotopic, references) -> FlowObject:
    """One card's substance, carrying what the card reads off a real build.

    *formula* is a list because the build states it more than once for one of
    the three, and `_settled` -- which drops an unsettled property rather than
    printing the first of its candidates -- is only exercised by a fixture that
    does the same.

    *monoisotopic* is stored although no card reads it, because the build
    stores it: a substance's properties are what they are, and a fixture that
    left it out could not catch the card printing it again.

    The masses are numbers here because they are numbers in the build: the
    vocabulary declares them `xsd:double` and the SQLite writer stores what it
    is given.  Storing them as strings is what let the card ship reading them
    with a reader that keeps only strings.
    """
    return FlowObject(
        flow_object_id=flow_object_id,
        prefLabel=[{"@value": name, "@language": "en"}],
        altLabel=[],
        classifications={CHEMINF_CAS_REGISTRY_NUMBER: {"@value": [cas]}},
        properties={
            CHEMROF_INCHI2D_KEY_STRING: {"@value": [inchikey]},
            CHEMROF_SMILES_STRING: {"@value": [smiles]},
            CHEMROF_MOLECULAR_FORMULA: {"@value": list(formula)},
            CHEMROF_MOLECULAR_MASS: {"@value": [mass]},
            CHEMROF_IUPAC_NAME: {"@value": [iupac]},
            CHEMROF_MONOISOTOPIC_MASS: {"@value": list(monoisotopic)},
        },
        references=list(references),
        created_from={},
    )


def _write_home_fixture(path: Path) -> None:
    """The three example objects with their source rows, and one other object.

    Every spelling below is the one the six-list build of 2026-09-04 records,
    and each object has a row in all three of `EXAMPLE_SOURCE_LISTS`, which is
    what `load_example` requires before it will draw a card.

    Three shapes worth having in a fixture:

    - **Carbon dioxide** is spelled one way twice and another way once by
      ecoinvent 3.12, so the card has a most common spelling to pick.
    - **Hexafluoroethane** is the same in EF 3.1, which ships `HFC-116` and
      `PFC-116` for the one substance -- and the name the card then shows is
      the one with a hydrogen that C2F6 does not have.
    - **Paraquat** carries two formulas, so its card is one the `_settled`
      rule really does take a line off.
    """
    objects = [
        _example_object(
            view.EXAMPLE_FLOW_OBJECT_ID, "Carbon Dioxide (fossil)",
            cas="124-38-9", inchikey=CO2_KEY, smiles="O=C=O", formula=["CO2"],
            iupac="dioxidocarbon", mass=44.009,
            # Two roundings of one number, as the build carries them here.
            monoisotopic=[43.989829, 43.98983], references=CO2_REFERENCES,
        ),
        _example_object(
            "fo-2eef9f5fb57f623c", "Hexafluoroethane",
            cas="76-16-4", inchikey="WMIYKQLTONQJES-UHFFFAOYSA-N",
            smiles="FC(F)(F)C(F)(F)F", formula=["C2F6"], iupac="Hexafluoroethane",
            mass=138.01, monoisotopic=[137.990419], references=C2F6_REFERENCES,
        ),
        _example_object(
            "fo-d5e5a11080bed5ec", "Paraquat",
            cas="4685-14-7", inchikey="INFDPOAKFNIJBF-UHFFFAOYSA-N",
            smiles="C[n+]1ccc(-c2cc[n+](C)cc2)cc1",
            # The ion's charge is stated in one of the two and not the other,
            # so the build has not settled which formula this substance has.
            formula=["C12H14N2", "C12H14N2+2"],
            iupac="1,1'-dimethyl-[4,4'-bipyridin]-1,1'-diium",
            mass=186.258, monoisotopic=[186.1146], references=PARAQUAT_REFERENCES,
        ),
    ]
    refs = {
        "u-air": (view.EXAMPLE_FLOW_OBJECT_ID, [
            _ref("ecoinvent", "3.12", "Carbon dioxide, fossil", 1),
            _ref("EF", "3.1", "carbon dioxide (fossil)", 2),
            _ref("stepwise", "2006-1.09", "Carbon dioxide", 3),
            _ref("bafu", "2026-v1", "Carbon dioxide, fossil", 4)]),
        "u-water": (view.EXAMPLE_FLOW_OBJECT_ID, [
            _ref("ecoinvent", "3.12", "Carbon dioxide, fossil", 5),
            _ref("ecoinvent", "3.12", "carbon dioxide, fossil", 6)]),
        "u-c2f6": ("fo-2eef9f5fb57f623c", [
            _ref("ecoinvent", "3.12", "Hexafluoroethane", 7),
            _ref("EF", "3.1", "HFC-116", 8),
            _ref("EF", "3.1", "HFC-116", 9),
            _ref("EF", "3.1", "PFC-116", 10),
            _ref("bafu", "2026-v1", "Ethane, hexafluoro-, HFC-116", 11)]),
        "u-paraquat": ("fo-d5e5a11080bed5ec", [
            _ref("ecoinvent", "3.12", "Paraquat", 12),
            _ref("EF", "3.1", "1,1'-dimethyl-4,4'-bipyridinium", 13),
            _ref("bafu", "2026-v1", "Paraquat", 14)]),
    }
    flows = [_flow(uuid, "Carbon dioxide, fossil") for uuid in refs]
    elementary = [
        dataclasses.replace(_elementary(uuid, flow_object_id), source_refs=rows)
        for uuid, (flow_object_id, rows) in refs.items()
    ]
    # Another object, a deprecated flow of its own, and a fifth list.
    flows += [_flow("u-ch4", "Methane"), _flow("u-ch4-old", "Methane", deprecated=True)]
    elementary += [
        dataclasses.replace(_elementary("u-ch4", "fo-ch4"),
                            source_refs=[_ref("agribalyse", "3.2", "Methane", 15)]),
        _elementary("u-ch4-old", "fo-ch4"),
    ]
    _write_fixture(path, flows=flows,
                   flow_objects=objects + [_flow_object("fo-ch4", "Methane")],
                   elementary=elementary)


class _HomeTestCase(unittest.TestCase):
    with_database = True
    with_docs = True

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        tmp = Path(self._tmp.name)
        self.path = tmp / "consensus-flows.sqlite3"
        if self.with_database:
            _write_home_fixture(self.path)
        docs_path = DOCS_ROOT if self.with_docs else tmp / "no-docs"
        app = create_app(self.path, docs_path=docs_path, data_dir=tmp)
        app.config["TESTING"] = True
        self.client = app.test_client()

    def body(self, path: str = "/") -> str:
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200, path)
        return response.get_data(as_text=True)

    def connection(self):
        connection = db.connect(self.path)
        self.addCleanup(connection.close)
        return connection


class StartTestCase(unittest.TestCase):
    def test_every_slug_is_a_page_in_docs(self):
        for entry in start.QUESTIONS:
            with self.subTest(question=entry.question):
                found = documentation.resolve(DOCS_ROOT, entry.slug.split("#", 1)[0])
                self.assertIsNotNone(found, entry.slug)
                self.assertEqual(found[0], "page")

    def test_the_questions_are_the_ones_docs_index_asks(self):
        """`docs/index.md` is published outside this app too, so it keeps them."""
        text = (DOCS_ROOT / "index.md").read_text(encoding="utf-8")
        section = text.split("## Where to start", 1)[1].split("\n## ", 1)[0]
        asked = [" ".join(q.split()) for q in re.findall(r'\*\*"(.+?)"\*\*', section, re.S)]
        self.assertEqual(sorted(asked), sorted(entry.question for entry in start.QUESTIONS))

    def test_four_are_homepage_links_as_on_the_board(self):
        self.assertEqual([entry.label for entry in start.links()],
                         ["Can I trust it?", "Using the files", "How a flow is decided",
                          "What we found"])


class HarmonisationSectionsTestCase(unittest.TestCase):
    """Where each card says what was done to its flow.

    The link is a page and a `#fragment`, and the fragment is the half that can
    rot silently: a reworded heading takes its anchor with it and drops the
    reader at the top of a page that no longer says what the card promised.  So
    the section is looked for in the rendered page, by the id the `toc`
    extension gives it, and not only in the file tree.
    """

    def test_every_card_links_a_section_that_exists(self):
        for entry in view.EXAMPLE_HARMONISATION.values():
            with self.subTest(label=entry.label):
                slug, _, fragment = entry.slug.partition("#")
                found = documentation.resolve(DOCS_ROOT, slug)
                self.assertIsNotNone(found, entry.slug)
                self.assertEqual(found[0], "page")
                self.assertTrue(fragment, entry.slug)
                page = documentation.load_page(DOCS_ROOT, slug, known_titles={})
                self.assertIn(f'id="{fragment}"', page.html, entry.slug)

    def test_the_three_examples_are_the_three_that_are_keyed(self):
        """A card whose id changes loses its link rather than keeping a dead one."""
        self.assertEqual(sorted(view.EXAMPLE_HARMONISATION),
                         sorted(view.EXAMPLE_FLOW_OBJECT_IDS))


class HomeQueriesTestCase(_HomeTestCase):
    def test_the_counts_are_the_builds(self):
        counts = queries.load_counts(self.connection())
        self.assertEqual(counts.flow_objects, 4)
        # The deprecated methane flow is not one the list publishes.
        self.assertEqual(counts.elementary_flows, 5)
        self.assertEqual(counts.source_lists,
                         ("agribalyse 3.2", "bafu 2026-v1", "ecoinvent 3.12", "EF 3.1",
                          "stepwise 2006-1.09"))

    def test_the_example_reads_its_rows_from_the_build(self):
        example = queries.load_example(
            self.connection(), view.EXAMPLE_FLOW_OBJECT_ID, view.EXAMPLE_SOURCE_LISTS
        )
        self.assertIsNotNone(example)
        self.assertEqual(example.name, "Carbon Dioxide (fossil)")
        self.assertEqual(example.cas_number, "124-38-9")
        self.assertEqual(example.inchikey, CO2_KEY)
        self.assertEqual(
            example.source_rows,
            (("ecoinvent 3.12", "Carbon dioxide, fossil"),
             ("EF 3.1", "carbon dioxide (fossil)"),
             ("bafu 2026-v1", "Carbon dioxide, fossil")),
        )
        self.assertEqual((example.row_count, example.list_count), (6, 4))

    def test_the_example_links_four_registries_in_the_cards_order(self):
        """One link each, the four `EXAMPLE_RESOURCES` names and nothing else.

        ECHA is in the fixture and not in the list: PubChem cross-references
        dozens of registries, and the card is an example rather than the
        substance's reference table.
        """
        example = queries.load_example(
            self.connection(), view.EXAMPLE_FLOW_OBJECT_ID, view.EXAMPLE_SOURCE_LISTS
        )
        self.assertEqual(
            example.links,
            (("ChEBI", "https://www.ebi.ac.uk/chebi/searchId.do?chebiId=CHEBI:16526"),
             ("CAS Common Chemistry", "https://commonchemistry.cas.org/detail?cas_rn=124-38-9"),
             ("PubChem", "https://pubchem.ncbi.nlm.nih.gov/compound/280"),
             ("Wikidata", "https://www.wikidata.org/wiki/Q1997")),
        )

    def test_the_properties_are_read_from_the_build(self):
        example = queries.load_example(
            self.connection(), view.EXAMPLE_FLOW_OBJECT_ID, view.EXAMPLE_SOURCE_LISTS
        )
        self.assertEqual(
            (example.formula, example.iupac_name, example.smiles),
            ("CO2", "dioxidocarbon", "O=C=O"),
        )
        self.assertEqual(example.molecular_mass, "44.009")

    def test_a_mass_the_build_stated_twice_is_left_off_the_card(self):
        """The same `_settled` rule as the formula, and for the same reason.

        Half of the 101 flow objects carrying two molar masses carry two
        different masses rather than one rounded twice, so the first of them
        is not a fact the build has stated.
        """
        self.assertEqual(queries._settled(["44.009"]), "44.009")
        self.assertEqual(queries._settled(["101.105", "246.327"]), "")

    def test_the_mass_is_read_although_the_build_stores_it_as_a_number(self):
        """The vocabulary declares it `xsd:double` and the build writes a JSON number.

        Read like the formula and the InChIKey -- with a reader that keeps
        strings and drops everything else -- the mass came back empty and the
        card printed none, for every substance.
        """
        self.assertEqual(queries._measurements(
            {"m": {"@value": [44.009]}}, "m"), ["44.009"])
        self.assertEqual(queries._measurements(
            {"m": {"@value": [43.989829, 43.98983]}}, "m"), ["43.989829", "43.98983"])
        # A bare number rather than a list, a string number, and an integer.
        self.assertEqual(queries._measurements({"m": {"@value": 18.015}}, "m"), ["18.015"])
        self.assertEqual(queries._measurements({"m": {"@value": ["44.009"]}}, "m"), ["44.009"])
        self.assertEqual(queries._measurements({"m": {"@value": [12]}}, "m"), ["12"])
        # And nothing where there is nothing to state.
        for empty in ({}, {"m": {}}, {"m": {"@value": []}}, {"m": {"@value": [None, ""]}}):
            with self.subTest(properties=empty):
                self.assertEqual(queries._measurements(empty, "m"), [])

    def test_a_registry_link_follows_the_number_the_card_prints(self):
        """Hexafluoroethane collects two CAS Common Chemistry URLs.

        Only one of them is the 76-16-4 the card states, and it is not the one
        the reference ordering puts first.  A card stating one number and
        linking another would be the confusion it exists to clear up.
        """
        example = queries.load_example(
            self.connection(), "fo-2eef9f5fb57f623c", view.EXAMPLE_SOURCE_LISTS
        )
        self.assertEqual(example.cas_number, "76-16-4")
        self.assertEqual(
            dict(example.links)["CAS Common Chemistry"],
            "https://commonchemistry.cas.org/detail?cas_rn=76-16-4",
        )

    def test_an_identity_the_build_states_twice_is_left_out(self):
        """Two formulas means the structure is not settled; the card does not pick."""
        self.assertEqual(queries._settled(["CO2"]), "CO2")
        for values in ([], ["C2H2O4", "C5H8O4"]):
            with self.subTest(values=values):
                self.assertEqual(queries._settled(values), "")

    def test_the_example_says_whether_a_structure_can_be_drawn(self):
        example = queries.load_example(
            self.connection(), view.EXAMPLE_FLOW_OBJECT_ID, view.EXAMPLE_SOURCE_LISTS
        )
        self.assertTrue(example.has_structure)

    def test_a_substance_with_no_smiles_and_no_references_has_neither(self):
        """Both are the build's; methane in this fixture carries neither."""
        example = queries.load_example(
            self.connection(), "fo-ch4", (("agribalyse", "3.2"),)
        )
        self.assertFalse(example.has_structure)
        self.assertEqual(example.links, ())

    def test_no_example_when_the_build_does_not_have_it(self):
        self.assertIsNone(queries.load_example(self.connection(), "fo-nope", view.EXAMPLE_SOURCE_LISTS))

    def test_no_example_when_a_list_has_no_row_for_it(self):
        """The card is several lists naming one flow; short of that it says nothing.

        ecoinvent 3.8 is in no fixture row, and carbon dioxide is in every
        other list here, so what is being asked is exactly the missing one.
        """
        self.assertIsNone(queries.load_example(
            self.connection(), view.EXAMPLE_FLOW_OBJECT_ID,
            (("EF", "3.1"), ("ecoinvent", "3.8")),
        ))


class HomePageTestCase(_HomeTestCase):
    def test_the_root_is_the_homepage_and_the_docs_stay_at_docs(self):
        body = self.body("/")
        self.assertRegex(body, r'<h1 class="home__title"[^>]*>One identity for every elementary flow.</h1>')
        self.assertIn('class="docs', self.body("/docs/"))

    def test_the_site_name_links_home(self):
        self.assertIn('<a class="masthead__brand" href="/">', self.body("/docs/"))

    def test_every_undecided_fact_is_a_placeholder(self):
        with _undecided():
            body = self.body()
        hero = body[body.index('class="home__hero"'):body.index('class="home-lookup"')]
        self.assertIn("[v1.0.0]", hero)

    def test_the_hero_carries_the_decided_version(self):
        """#200: the first release is 1.0."""
        body = self.body()
        hero = body[body.index('class="home__hero"'):body.index('class="home-lookup"')]
        self.assertIn('<span class="mono">1.0</span>', hero)
        self.assertNotIn("[v1.0.0]", hero)

    def test_a_decided_fact_replaces_its_placeholder(self):
        with _decided():
            body = self.body()
        hero = body[body.index('class="home__hero"'):body.index('class="home-lookup"')]
        self.assertIn('<span class="mono">v1.0.0</span>', hero)
        self.assertNotIn("[v1.0.0]", body)

    def test_the_counts_come_from_the_build(self):
        body = self.body()
        counts = body[body.index('class="home-counts"'):body.index('class="home-lookup"')]
        self.assertIn('home-counts__number">4</b> flow objects', counts)
        self.assertIn('home-counts__number">5</b> elementary flows', counts)
        self.assertIn('home-counts__number">5</b> source lists', counts)

    def test_the_example_card_is_read_from_the_build(self):
        body = self.body()
        card = body[body.index('class="home-example"'):]
        for text in ("ecoinvent 3.12", "carbon dioxide (fossil)", "Carbon Dioxide (fossil)",
                     "124-38-9", CO2_KEY, "Named in 3 source lists, 5 source rows in all",
                     f'href="/flow-objects/{view.EXAMPLE_FLOW_OBJECT_ID}"'):
            with self.subTest(text=text):
                self.assertIn(text, card)

    def test_one_card_per_example_under_one_label(self):
        """How many cards there are is `EXAMPLE_FLOW_OBJECT_IDS` and nothing else."""
        body = self.body()
        self.assertEqual(body.count('<article class="home-example" data-example>'),
                         len(view.EXAMPLE_FLOW_OBJECT_IDS))
        self.assertEqual(body.count('class="home-examples__eyebrow"'), 1)

    def test_the_cards_are_different_substances_disagreed_about_differently(self):
        """Three cards making one point three times would be one card.

        Carbon dioxide is the flow every reader knows; hexafluoroethane is the
        name five of the six lists get wrong; paraquat is the one list that is
        precise while the rest use the common name.
        """
        body = self.body()
        for name, ecoinvent_spelling, ef_spelling in (
            ("Carbon Dioxide (fossil)", "Carbon dioxide, fossil", "carbon dioxide (fossil)"),
            ("Hexafluoroethane", "Hexafluoroethane", "HFC-116"),
            ("Paraquat", "Paraquat", "1,1&#39;-dimethyl-4,4&#39;-bipyridinium"),
        ):
            with self.subTest(name=name):
                self.assertIn(f">{name}</a>", body)
                self.assertIn(ecoinvent_spelling, body)
                self.assertIn(ef_spelling, body)
        # The BAFU spelling is on the card too, which is what the third list
        # is there for: it is the lineage AGRIBALYSE and Stepwise share.
        self.assertIn("Ethane, hexafluoro-, HFC-116", body)
        self.assertEqual(body.count("bafu 2026-v1"), len(view.EXAMPLE_FLOW_OBJECT_IDS))

    def test_each_card_links_what_was_done_to_its_own_flow(self):
        """The card shows three spellings; the link says how they became one flow.

        Per card rather than one link for all three, because the three were
        decided differently: an origin qualifier, a duplicate-row ruling and a
        corrected name.
        """
        cards = self.body().split('<article class="home-example" data-example>')[1:]
        self.assertEqual(len(cards), len(view.EXAMPLE_FLOW_OBJECT_IDS))
        for flow_object_id, card in zip(view.EXAMPLE_FLOW_OBJECT_IDS, cards):
            entry = view.EXAMPLE_HARMONISATION[flow_object_id]
            with self.subTest(label=entry.label):
                self.assertIn(f'href="/docs/{entry.slug}"', card)
                # `EF's` reaches the page as `EF&#39;s`, which is the template
                # escaping it rather than the label being something else.
                self.assertIn(f"{escape(entry.label)} →", card)
                # The section link is one of two, beside the record itself.
                self.assertIn("View the flow object →", card)
        # Each card's is its own: three cards, three different sections.
        self.assertEqual(
            len({entry.slug for entry in view.EXAMPLE_HARMONISATION.values()}), 3
        )

    def test_the_section_the_card_links_is_reachable_from_the_page(self):
        """`/docs/<page>` answers, and the section is on the page it answers with."""
        for entry in view.EXAMPLE_HARMONISATION.values():
            slug, _, fragment = entry.slug.partition("#")
            with self.subTest(slug=slug):
                response = self.client.get(f"/docs/{slug}")
                self.assertEqual(response.status_code, 200)
                self.assertIn(f'id="{fragment}"', response.get_data(as_text=True))

    def test_a_formula_the_build_stated_twice_is_absent_from_that_card(self):
        """Paraquat's is `C12H14N2` and `C12H14N2+2`, so its card has no formula line.

        The other two cards have theirs: this is the `_settled` rule taking a
        line off one card, not the template forgetting a line.
        """
        body = self.body()
        self.assertIn("Formula CO2", body)
        self.assertIn("Formula C2F6", body)
        self.assertNotIn("C12H14N2", body)
        # And what the card does show of paraquat is the rest of its identity.
        self.assertIn("CAS 4685-14-7", body)
        self.assertIn("Molecular mass 186.258 g/mol", body)

    def test_an_id_this_build_has_no_card_for_is_dropped(self):
        """Three examples stay three rather than becoming three and a hole."""
        ids = view.EXAMPLE_FLOW_OBJECT_IDS + ("fo-nope",)
        with mock.patch.object(view, "EXAMPLE_FLOW_OBJECT_IDS", ids):
            body = self.body()
        self.assertEqual(body.count('<article class="home-example" data-example>'),
                         len(view.EXAMPLE_FLOW_OBJECT_IDS))

    def test_the_examples_are_under_the_lookup_box(self):
        """Back where they were: the box, then what a lookup finds."""
        body = self.body()
        lookup = body.index('class="home-lookup"')
        self.assertLess(lookup, body.index('class="home-examples"'))
        self.assertLess(body.index('class="home-examples"'),
                        body.index('class="home-start"'))
        self.assertNotIn("home-lookup__try", body)

    def test_every_example_is_on_the_page_and_the_arrows_start_hidden(self):
        """`app.js` hides all but one; with it blocked they are all readable.

        The arrows are the other half of that rule: markup that showed them
        without the script would show a control that does nothing.
        """
        body = self.body()
        self.assertNotIn("hidden>\n        <article", body)
        self.assertIn("data-examples-nav hidden", body)
        self.assertIn('data-examples-step="-1"', body)
        self.assertIn('data-examples-step="1"', body)
        self.assertIn(f"1 of {len(view.EXAMPLE_FLOW_OBJECT_IDS)}", body)
        # `app.js` sets this when it takes over, and the rule that separates
        # one stacked card from the next is what it turns off.  In the markup
        # it would leave the cards with nothing between them.
        self.assertNotIn("data-examples-stepped", body)

    def test_the_inchikey_is_labelled_as_one(self):
        """An unlabelled 27-character string is not an identifier a reader knows."""
        body = self.body()
        card = body[body.index('class="home-example"'):]
        self.assertIn(f"InChIKey {CO2_KEY}", card)

    def test_the_card_draws_the_structure_from_the_substances_own_smiles(self):
        body = self.body()
        card = body[body.index('class="home-example"'):]
        self.assertIn(
            f'src="/flow-objects/{view.EXAMPLE_FLOW_OBJECT_ID}/structure.svg"', card
        )
        # And the endpoint the card points at answers with a diagram.
        response = self.client.get(f"/flow-objects/{view.EXAMPLE_FLOW_OBJECT_ID}/structure.svg")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "image/svg+xml")

    def test_the_card_names_every_fact_and_states_the_mass_unit(self):
        """One list, registry numbers and structure together, each one named.

        The record carries a bare number; the unit is the template's.
        """
        body = self.body()
        facts = body[body.index('class="home-example__facts'):body.index('class="home-example__links"')]
        for text in ("CAS 124-38-9", f"InChIKey {CO2_KEY}", "Formula CO2",
                     "Molecular mass 44.009 g/mol", "IUPAC name dioxidocarbon",
                     "SMILES O=C=O"):
            with self.subTest(text=text):
                self.assertIn(text, facts)

    def test_the_monoisotopic_mass_is_off_the_card(self):
        """Two masses differing in the second decimal place, under two names.

        The build states both and the flow object page shows both; the card
        has one line per fact and shows the molar mass alone.
        """
        body = self.body()
        self.assertNotIn("Monoisotopic", body)
        self.assertNotIn("43.989829", body)
        self.assertEqual(body.count("g/mol"), len(view.EXAMPLE_FLOW_OBJECT_IDS))

    def test_the_card_links_the_four_registries_and_no_others(self):
        body = self.body()
        card = body[body.index('class="home-example__links"'):body.index('class="home-example__sources"')]
        for resource in ("ChEBI", "CAS Common Chemistry", "PubChem", "Wikidata"):
            with self.subTest(resource=resource):
                self.assertIn(f">{resource}</a>", card)
        self.assertNotIn("echa.europa.eu", card)

    def test_a_substance_with_no_structure_gets_no_broken_image(self):
        """`substances.structure` 404s without a SMILES, so the card asks first."""
        example = queries.load_example(
            self.connection(), view.EXAMPLE_FLOW_OBJECT_ID, view.EXAMPLE_SOURCE_LISTS
        )
        plain = dataclasses.replace(example, has_structure=False, links=(),
                                    formula="", iupac_name="", smiles="",
                                    molecular_mass="")
        with mock.patch.object(view.queries, "load_example", return_value=plain):
            body = self.body()
        card = body[body.index('class="home-example"'):]
        self.assertIn("Carbon Dioxide (fossil)", card)
        for absent in ("home-example__structure", "home-example__links",
                       "Formula ", "g/mol", "SMILES "):
            with self.subTest(absent=absent):
                self.assertNotIn(absent, card)
        # The registry numbers are not properties and are still there.
        self.assertIn("CAS 124-38-9", card)

    def test_the_actions_and_the_lookup_form(self):
        body = self.body()
        hero = body[body.index('class="home__hero"'):body.index('class="home-lookup"')]
        self.assertIn('href="/download/"', hero)
        self.assertIn('href="/flows/">Browse flows</a>', hero)
        self.assertRegex(body, r'<form class="home-lookup__form" role="search" action="/search" method="get">')
        self.assertIn('id="home-q" name="q"', body)

    def test_the_masthead_search_box_is_left_off_the_homepage_only(self):
        self.assertNotIn('id="site-search"', self.body("/"))
        self.assertIn('id="site-search"', self.body("/docs/"))

    def test_start_here_links_the_four_questions_and_all_documentation(self):
        body = self.body()
        start_section = body[body.index('id="start"'):]
        start_section = start_section[:start_section.index("</nav>")]
        self.assertIn('id="start-heading">Start here:</h2>', start_section)
        for entry in start.links():
            with self.subTest(label=entry.label):
                self.assertIn(f'<a href="/docs/{entry.slug}">{entry.label}</a>', start_section)
        self.assertIn('href="/docs/">All documentation', start_section)

    def test_the_citation_and_the_release_details_are_left_to_the_footer(self):
        body = self.body()
        self.assertNotIn('id="cite"', body)
        footer = body[body.index('class="footer"'):]
        self.assertIn('href="/download/#cite"', footer)
        self.assertIn("ODbL-1.0", footer)


class HomeWithoutDatabaseTestCase(_HomeTestCase):
    with_database = False

    def test_the_numbers_are_left_out_not_zero(self):
        body = self.body()
        self.assertIn('<h1 class="home__title"', body)
        self.assertNotIn('class="home-counts"', body)
        self.assertNotIn('class="home-example"', body)
        for query in ("q=Carbon+dioxide,+fossil", "q=Nickel(2%2B)", "q=124-38-9"):
            with self.subTest(query=query):
                self.assertIn(f'href="/search?{query}"', body)


class HomeWithoutDocsTestCase(_HomeTestCase):
    with_docs = False

    def test_where_to_start_is_left_out(self):
        body = self.body()
        self.assertNotIn('id="start"', body)
        self.assertNotIn(start.QUESTIONS[0].question, body)

    def test_the_cards_lose_their_docs_link_and_keep_the_rest(self):
        """A link into a tree that is not there is a link to nothing (§4).

        The masthead and the footer link `/docs/` whatever this checkout has,
        so it is the cards that are read here and not the page.
        """
        body = self.body()
        examples = body[body.index('class="home-examples"'):body.index('</main>')]
        self.assertNotIn('href="/docs/', examples)
        for entry in view.EXAMPLE_HARMONISATION.values():
            with self.subTest(label=entry.label):
                self.assertNotIn(entry.label, examples)
        self.assertEqual(examples.count("View the flow object →"),
                         len(view.EXAMPLE_FLOW_OBJECT_IDS))


if __name__ == "__main__":
    unittest.main()
