# Module inventory and contextual review validation

The local Curation preview now shows implementation evidence inside a review
package and an individual case. The shared module reference links back to those
packages and separates implementation links from proposed destinations.

Validation on 13 October 2026:

- The focused Curation and web navigation/control suite passed: **174 tests and
  104 subtests**. It covers complete registered-input descriptions, transformer
  order and class documentation, separate input readers, version and origin
  separation, proposed-case filtering, source download restrictions and existing
  revision-specific review rules.
- Ruff checks `F821,F401,F811` passed for the changed Python files.
- The separate local evidence bundle was reconciled against all original source
  rows, hashes and package memberships. Its module audit verifies every actual,
  proposed and recorded implementation relationship, complete source downloads
  and the module detail routes. The machine-readable receipts remain with that
  local bundle.
- Browser checks exercised package implementation cards, module backlinks,
  catalogue search and navigation from a proposed destination to its paginated
  cases. The existing application typography and colours are retained.

These checks verify the read-only representation. Test source, an execution
receipt, a scientific review and release adoption remain separate evidence. The
register states its source baseline; the displayed published database has its
own historical run.
