# Installation

## Requirements

- **Python 3.14 or later**
- **[uv](https://docs.astral.sh/uv/)** for dependency and environment management
- **Java** — required by OPSIN, which parses IUPAC chemical names
- **Disk space** — budget 40 GB or more. The reference-data caches are large
  and `consensus-flows.sqlite3` runs to several gigabytes.
- **Time** — the first full run takes several hours. See
  [Running a transform](running.md).

Optional, and only for specific workflows:

- **ecoinvent credentials**, for downloading and merging ecoinvent flows.
  Configured through
  [ecoinvent_interface](https://github.com/brightway-lca/ecoinvent_interface).
- **A CAS Common Chemistry API key**, which enables the highest-quality CAS
  and name evidence.

## Set up the environment

```bash
uv venv
uv run brightway-flows --help
```

`uv run` builds the environment on first use, so there is no separate install
step. Every command below is run the same way.

## Register the Common Chemistry key

Persist it once in the application settings file:

```bash
uv run brightway-flows set-commonchemistry-token --token "<COMMON_CHEMISTRY_API_KEY>"
```

Or supply it per run through the environment, which takes precedence over the
persisted value:

```bash
COMMONCHEMISTRY_API_KEY="<KEY>" uv run brightway-flows build
```

Without a key the pipeline still runs; the Common Chemistry evidence is simply
unavailable, and the identity decisions that depend on it are weaker.

## Where files are written

Everything — downloads, caches, outputs, review queues — goes to a single data
directory:

| Platform | Location |
|---|---|
| macOS | `~/Library/Application Support/brightway-flows/` |
| Linux | `~/.local/share/brightway-flows/` |
| Windows | `%LOCALAPPDATA%\brightway-labs\brightway-flows\` |

Override it with an environment variable:

```bash
export BRIGHTWAY_FLOWS_DATA_DIR=/path/to/somewhere
```

**Use this for test runs.** A bounded run overwrites the layered artifacts and
the SQLite database in whatever directory it points at, so a `--max-flows` run
against your real data directory will replace real outputs with a small subset.
Pointing it elsewhere costs nothing and avoids the problem — though note that
the reference-data caches live there too, so a fresh directory means
re-downloading them.

## Start from somebody else's caches

The hours the first run costs are almost all rate-limited requests to PubChem,
ChEBI, Common Chemistry, Wikidata and Wikipedia. Those answers are the same
wherever they are fetched, so they can be moved between machines instead:

```bash
export BRIGHTWAY_FLOWS_CACHE_URL=https://example.org/brightway-flows-cache.tar.gz
uv run brightway-flows fetch-cache
```

`--url` passes the location instead, and a local path or a `file://` URL is
read where it lies — a shared drive, a USB stick, an archive a CI job already
downloaded. Caches the data directory already holds are kept rather than
replaced, because they may contain lookups the archive predates; `--overwrite`
replaces them.

To publish one from a machine that has done the work:

```bash
uv run brightway-flows pack-cache --list                 # what would go in
uv run brightway-flows pack-cache -o /tmp/cache.tar.gz   # write it
```

What is in the archive is a fixed list — the per-record web caches, the ChEBI
dump, the GLAD workbook — and unpacking writes nothing else, whatever the
archive contains. Four things are deliberately outside it:

- `settings.json`, which holds the Common Chemistry API key. Archives get
  handed to other people.
- The licensed source lists. ecoinvent's flows and BAFU's ecoSpold export
  arrive under terms their licence holders set, so fetch those yourself.
- Build outputs — `consensus-flows.sqlite3`, the layered artifacts, the logs. A
  fetched cache should not be mistakable for a build that never ran.
- `EF-v3.1.zip`. It is 200 MB, and one `brightway-flows download` away from
  a public URL; carrying it would triple the archive to save a request nobody
  is rate-limiting.

Nothing in the archive expires on its own, exactly as nothing in the data
directory does. `chebi --force` and the other refresh flags are still how a
source is deliberately brought up to date; `pack-cache --list` and the
`packed_at` the fetch logs are how you tell how old an archive is.

## Verify the installation

```bash
uv run brightway-flows download
uv run brightway-flows extract
```

This fetches the EF 3.1 archive (about 200 MB) and parses it into
`ef-31-flows.json`. If that succeeds, the toolchain is working and you can
proceed to [Running a transform](running.md).

## Build the documentation locally

```bash
uv run mkdocs serve
```

Served at [http://127.0.0.1:8000](http://127.0.0.1:8000).
