"""The one place an undecided fact about the public site lives.

`plans/public-site.md` §0's first rule: every undecided fact is a visible
placeholder, and nothing pages by hand.  Two things are pinned here:

- `publication.unfilled_facts` finds every fact that is still `None` (or, for
  `maintainers`, still empty, and for `checksums`, still missing a key).  It
  reported the launch blockers while there were any; now that there are none
  it is what would catch a fact going *back* to unset, or a new field added
  and never decided.
- The `placeholder` macro renders a set value as itself and an unset one as
  the amber dashed chip, in both cases without the page template that calls
  it needing to know which.
"""

from __future__ import annotations

import unittest
from pathlib import Path

import flask

from brightway_flows.webapps.app import create_app
from brightway_flows.webapps.app.publication import (
    CHECKSUM_ARTIFACT_KEYS,
    PUBLICATION,
    Maintainer,
    Publication,
    unfilled_facts,
)

_FULLY_DECIDED = Publication(
    version="v1.0.0",
    release_date="2026-11-01",
    doi="10.5281/zenodo.1234567",
    checksums={key: "0" * 64 for key in CHECKSUM_ARTIFACT_KEYS},
    data_licence="CC BY 4.0",
    code_licence="MIT",
    source_list_terms="See each source list's own terms.",
    maintainers=(Maintainer(name="A. Curator", role="Maintainer"),),
    governance="Disputed decisions are reviewed by the maintainers.",
    postal_address="Brightway Labs GmbH, Some Street 1, Zurich",
    contact_email="hello@brightway-lca.com",
    log_retention_period="90 days",
)


class UnfilledFactsTestCase(unittest.TestCase):
    def test_a_fresh_publication_reports_every_fact(self):
        """Nothing has been decided at the start of this plan, so nothing is
        filled in -- the state this module was written for."""
        blockers = unfilled_facts(Publication())
        self.assertIn("version", blockers)
        self.assertIn("data_licence", blockers)
        self.assertIn("governance", blockers)
        self.assertIn("maintainers", blockers)
        for key in CHECKSUM_ARTIFACT_KEYS:
            self.assertIn(f"checksums[{key}]", blockers)

    def test_a_fully_decided_publication_reports_nothing(self):
        self.assertEqual(unfilled_facts(_FULLY_DECIDED), [])

    def test_a_partial_checksum_set_reports_only_what_is_missing(self):
        publication = Publication(checksums={"flows": "0" * 64})
        blockers = unfilled_facts(publication)
        self.assertNotIn("checksums[flows]", blockers)
        self.assertIn("checksums[factors]", blockers)


class DecidedFactsTestCase(unittest.TestCase):
    """What #200 settled, pinned so that it cannot be lost in an edit.

    Nothing is open any more, which was #200's "done when", and the test at
    the end of this class is what keeps it that way now that the tool that
    reported it has been removed.
    """

    def test_the_first_release_is_1_0_on_2026_09_22(self):
        self.assertEqual(PUBLICATION.version, "1.0")
        self.assertEqual(PUBLICATION.release_date, "2026-09-22")
        self.assertEqual(PUBLICATION.doi, "10.5281/zenodo.22857950")

    def test_every_released_file_has_a_sha_256(self):
        """Read off the archived files, so each is 64 hexadecimal digits and
        there is one per artifact the Download page lists."""
        for key in CHECKSUM_ARTIFACT_KEYS:
            with self.subTest(key=key):
                self.assertRegex(PUBLICATION.checksum(key) or "", r"^[0-9a-f]{64}$")

    def test_the_licences_are_spdx_identifiers(self):
        """`data_licence` is quoted into the `license:` field of the
        `CITATION.cff` block on Download, which is SPDX there."""
        self.assertEqual(PUBLICATION.data_licence, "ODbL-1.0")
        self.assertEqual(PUBLICATION.code_licence, "AGPL-3.0-or-later")

    def test_the_contact_facts_are_set(self):
        self.assertEqual(PUBLICATION.contact_email, "flows@brightway-lca.com")
        self.assertIn("Riniken", PUBLICATION.postal_address or "")
        self.assertEqual(PUBLICATION.log_retention_period, "14 days")

    def test_the_source_list_terms_claim_nothing_stricter_than_odbl(self):
        """Public domain (the GLAD mapping files) or the same ODbL this list
        uses (ecoinvent's glossary); no field carries stricter terms."""
        terms = PUBLICATION.source_list_terms or ""
        self.assertIn("public domain", terms)
        self.assertIn("ODbL-1.0", terms)

    def test_the_list_names_its_maintainers(self):
        self.assertEqual(
            [(one.name, one.role) for one in PUBLICATION.maintainers],
            [("Chris Mutel", "Maintainer"),
             ("João Gonçalves", "Maintainer"),
             ("David Turner", "Maintainer")],
        )

    def test_the_governance_says_who_decides_and_where_it_is_going(self):
        governance = PUBLICATION.governance or ""
        self.assertIn("made by the maintainers", governance)
        self.assertIn("more formal and inclusive governance structure", governance)

    def test_nothing_is_left_to_decide(self):
        """#200's "done when", and the only thing still asserting it."""
        self.assertEqual(unfilled_facts(PUBLICATION), [])


class PlaceholderMacroTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app(Path("/nonexistent.sqlite3"))

    def render(self, value, label):
        template = (
            '{% import "partials/placeholder.html" as p %}'
            "{{ p.placeholder(value, label) }}"
        )
        with self.app.app_context():
            return flask.render_template_string(template, value=value, label=label)

    def test_a_set_value_renders_as_itself(self):
        html = self.render("2026-11-01", "RELEASE DATE")
        self.assertEqual(html.strip(), "2026-11-01")
        self.assertNotIn("placeholder", html)

    def test_an_unset_value_renders_the_amber_chip(self):
        html = self.render(None, "DATA LICENCE")
        self.assertIn('class="placeholder"', html)
        self.assertIn("[DATA LICENCE]", html)

    def test_the_chip_never_renders_as_an_empty_string(self):
        """An unfilled fact has to be visible, never a blank a reader would
        have to notice on their own."""
        html = self.render(None, "CODE LICENCE")
        self.assertTrue(html.strip())


if __name__ == "__main__":
    unittest.main()
