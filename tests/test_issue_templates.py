"""The issue forms, and the links in the application that open them.

Two of these links existed for weeks before the forms did: `about.html` and
`search.html` both pointed at `?template=wrong-match.yml`, and GitHub answers a
`template=` naming no file by showing the blank issue form with no warning. The
reader sees a form; nobody sees that the one they were sent to is not there.

So the checks here are about the join rather than about the YAML, which GitHub
validates itself and reports on the repository's own pages:

- every `?template=` the application emits names a file that exists;
- every field a link pre-fills is a field that form declares, because GitHub
  drops an unknown parameter silently and the contributor retypes what the page
  was already showing -- which is the whole thing the pre-filling is for;
- every relative link out of a form resolves, on the same grounds as
  `test_documentation.py`: a form is prose that cites repository paths.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = ROOT / ".github" / "ISSUE_TEMPLATE"
APP_TEMPLATES = ROOT / "src" / "brightway_flows" / "webapps" / "app" / "templates"

#: `?template=wrong-match.yml&amp;published-flow=…` in an `href`. The form name
#: and the parameters after it are captured separately: the first has to name a
#: file, and each of the rest has to name a field in it.
_LINK = re.compile(r"issues/new\?template=([a-z0-9.-]+)((?:&amp;|&)[a-z-]+=[^\"'\s]*)?")

#: `&amp;published-flow={{ … }}` -> `published-flow`.
_PARAMETER = re.compile(r"(?:&amp;|&)([a-z-]+)=")

#: `  - type: input` followed by `    id: published-flow`, which is all this
#: needs from the YAML and is why it does not import a parser.
_FIELD_ID = re.compile(r"^\s+id:\s*([a-z0-9-]+)\s*$", re.MULTILINE)

#: `[text](target)` with a relative target.
_MARKDOWN_LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")

#: The two keys the chooser reads, at the top level rather than on a field --
#: every form has a `description:` on some field, so the anchoring is the check.
_TOP_LEVEL_NAME = re.compile(r"^name:\s*\S", re.MULTILINE)
_TOP_LEVEL_DESCRIPTION = re.compile(r"^description:\s*\S", re.MULTILINE)


def forms() -> dict[str, str]:
    """Every issue form, by filename. `config.yml` is the chooser, not a form."""
    return {
        path.name: path.read_text(encoding="utf-8")
        for path in sorted(TEMPLATE_DIR.glob("*.yml"))
        if path.name != "config.yml"
    }


def links() -> list[tuple[Path, str, list[str]]]:
    """Every `issues/new?template=` in the application, with its parameters."""
    found = []
    for path in sorted(APP_TEMPLATES.rglob("*.html")):
        for name, query in _LINK.findall(path.read_text(encoding="utf-8")):
            found.append((path, name, _PARAMETER.findall(query or "")))
    return found


class IssueFormTestCase(unittest.TestCase):
    def test_there_are_forms(self):
        """A rename of the directory would otherwise pass everything below."""
        self.assertTrue(forms(), f"no issue forms under {TEMPLATE_DIR}")

    def test_the_chooser_is_there(self):
        """Without `config.yml` the contact links and the blank-issue setting
        are GitHub's defaults, which are not the ones this repository wants."""
        self.assertTrue((TEMPLATE_DIR / "config.yml").is_file())

    def test_every_form_declares_a_name_and_a_description(self):
        """Both are what the chooser shows on the card. A form missing either is
        rejected by GitHub and never appears."""
        for name, text in forms().items():
            with self.subTest(form=name):
                self.assertRegex(text, _TOP_LEVEL_NAME, f"{name} has no name")
                self.assertRegex(
                    text, _TOP_LEVEL_DESCRIPTION, f"{name} has no description"
                )

    def test_every_relative_link_out_of_a_form_resolves(self):
        for name, text in forms().items():
            for target in _MARKDOWN_LINK.findall(text):
                if target.startswith(("http://", "https://", "mailto:", "#")):
                    continue
                path = target.split("#", 1)[0]
                if not path:
                    continue
                with self.subTest(form=name, target=target):
                    self.assertTrue(
                        (ROOT / path).exists(), f"{name} links to {target}"
                    )


class ApplicationLinkTestCase(unittest.TestCase):
    def test_every_link_names_a_form_that_exists(self):
        """The failure this whole file is for."""
        available = set(forms())
        for path, name, _ in links():
            with self.subTest(page=path.name, template=name):
                self.assertIn(
                    name,
                    available,
                    f"{path.relative_to(ROOT)} opens {name}, which is not in "
                    f"{TEMPLATE_DIR.relative_to(ROOT)}",
                )

    def test_every_prefilled_field_is_a_field_of_that_form(self):
        """GitHub drops a parameter naming no field, and drops it silently."""
        declared = {
            name: set(_FIELD_ID.findall(text)) for name, text in forms().items()
        }
        for path, name, parameters in links():
            if name not in declared:
                continue  # the test above owns that failure
            for parameter in parameters:
                with self.subTest(page=path.name, template=name, field=parameter):
                    self.assertIn(
                        parameter,
                        declared[name],
                        f"{path.relative_to(ROOT)} pre-fills {parameter!r} on "
                        f"{name}, which declares no such field",
                    )

    def test_the_flow_and_substance_pages_both_offer_one(self):
        """About tells the reader that every flow and substance page has a link
        that opens a pre-filled issue. These are the two pages it means."""
        for page in ("flow_detail.html", "substance_detail.html"):
            with self.subTest(page=page):
                self.assertIn(
                    "issues/new?template=",
                    (APP_TEMPLATES / page).read_text(encoding="utf-8"),
                )


if __name__ == "__main__":
    unittest.main()
