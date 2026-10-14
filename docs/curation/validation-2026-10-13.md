# Focused correction checks — 13 October 2026

This receipt was produced by the local Curation development run using CPython
3.14.7 and the locked development dependencies. It checks existing correction
code at `19d6cc6268e59e18fcbb47bfec0f440fb0f6a353`.

| Area | Test files | Distinct tests passing |
|---|---|---:|
| Unit decisions and water identity | `test_unit_changes.py`, `test_water_conversion_survives_the_split.py` | 40 |
| Characterisation and amount conversion | `test_characterise.py` | 53 |
| Factor rulings | `test_factor_rulings.py` | 29 |

The initial combined run passed 121 tests and 143 subtests. One additional test
could not execute because this fresh checkout lacked the public ChEBI input.
After making that cached public input available, the blocked test was run
again and passed. It also passed on the unchanged baseline checkout. Thus all
122 distinct selected tests passed; the first run was not wholly successful.

Commands (from the repository root):

```sh
uv run --python 3.14.7 --frozen pytest -q \
  tests/test_characterise.py tests/test_unit_changes.py \
  tests/test_water_conversion_survives_the_split.py tests/test_factor_rulings.py

uv run --python 3.14.7 --frozen pytest -q \
  tests/test_water_conversion_survives_the_split.py::IdentitySurvivesTheSplitTestCase::test_an_elementary_flow_keeps_its_identifier_when_its_object_moves
```

These focused checks do not demonstrate a full same-input build, scientific
approval, or inclusion in a published release. PR #387 has a different revision
and was not executed by this run; its reported checks remain linked to that PR.
The optional published SQLite snapshot used by the local website is historical
display data, not an output of these tests.
