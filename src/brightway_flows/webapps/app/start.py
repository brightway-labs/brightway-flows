"""The homepage's "Where to start": a reader's question, and the page that answers it.

The same questions are asked in `docs/index.md`, which is published outside this
application too, so they are written twice.  `tests/test_webapp_home.py`
compares the two lists, and checks that every slug here is a page in `docs/`:
a question that drifts, or a page that moves, fails there rather than on the
homepage.

The homepage asks four of them, each as a short `label` rather than the whole
question: a row of links under the fold reads at a glance, and the full
questions are one click away on `/docs/`.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Question:
    """One question.  `slug` is a docs page, with a `#fragment` where the
    answer is one section of it.  A question with a `label` is a link on the
    homepage, under that label; one without is asked only in the docs.
    """

    question: str
    slug: str
    label: str = ""


#: The homepage's four first, in the order it shows them; then the rest.
QUESTIONS: tuple[Question, ...] = (
    Question(
        "What is this project claiming, and can I trust it?",
        "concepts/why",
        "Can I trust it?",
    ),
    Question(
        "I have the output files and want to use them.",
        "using/outputs",
        "Using the files",
    ),
    Question(
        "How does a row in a source list become a flow in this one?",
        "deciding",
        "How a flow is decided",
    ),
    Question(
        "What has this actually found in the published lists?",
        "findings",
        "What we found",
    ),
    Question(
        "I know one of the source lists. What did you change in it?",
        "changes",
    ),
    Question(
        "I have a flow list of my own and want to know which consensus flows its "
        "rows are.",
        "using/matching-your-own-list",
    ),
    Question(
        "What is still open, for the list I care about?",
        "reference/limitations#open-questions-by-source-list-and-by-topic",
    ),
    Question("I need to run or re-run the pipeline.", "operating/install"),
    Question("I am reviewing the harmonisation decisions.", "operating/review-app"),
)


def links() -> tuple[Question, ...]:
    return tuple(entry for entry in QUESTIONS if entry.label)
