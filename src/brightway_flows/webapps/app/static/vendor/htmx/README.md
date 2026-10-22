# htmx 2.0.11

Curation uses htmx for server-rendered live search, fragment navigation and URL
history. Its small adapter handles input timing and reinitializes the existing
personal shortlist and triage controls after a swap. Filtering and sorting stay
in Flask; ordinary GET URLs and Enter-to-submit remain usable without JavaScript.

This dependency fits the existing Jinja application without a frontend framework,
client-side copy of the register, or JavaScript build step. Turbo would bring a
broader navigation model; Alpine alone would still leave transport and history to
maintain here. htmx covers these particular needs directly.

- Documentation: <https://htmx.org/docs/>
- Active search: <https://htmx.org/examples/active-search/>
- Release file: <https://unpkg.com/htmx.org@2.0.11/dist/htmx.min.js>
- License: BSD 2-Clause, preserved in `LICENSE`.
- SHA-384 (base64): `2OatzQy1H+Zd/IIrjr1TcuDGqLXeHhbooAyJY1KdQMKnr4LZ22k31GBLdYKHmVjg`

The script is served locally. There are no runtime CDN requests. Eval and response
script execution are disabled. Curation HTML is excluded from htmx's localStorage
history cache; Back/Forward retrieves the corresponding GET view from the server.
Only the existing personal notes, shortlist and triage use browser storage.

For an upgrade, review upstream release notes, download the pinned release and
license, verify the published checksum, and update the template and integrity test
together. Exercise search, rapid input, column filters, sorting, pagination,
Back/Forward and personal controls against the local preview.
