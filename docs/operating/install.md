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
Common Chemistry, Wikidata and Wikipedia. The project publishes the answers it
has already collected, so a new machine can start from those:

```bash
uv run brightway-flows fetch-cache
```

This downloads `brightway-flows-cache-2026-10-24.tar.gz` from
`files.brightway.dev` (18 MB) and checks that it is the archive the project
published (SHA-256 `b510aa67…c768`). It holds the PubChem, Common Chemistry,
compound-profile, Wikipedia, Wikidata and isotope caches as they stood in the
shared data directory on 24 October 2026.

**Which archive a build starts from is a choice the code makes.** A cache
records what a web service answered on the day it was asked, and PubChem or
Wikidata may answer differently next month. So a published archive is never
replaced: a newer one goes up under a new date, and moving to it is a change to
`DEFAULT_CACHE_URL` and its digest in `cache_archive.py`, reviewed like any
other. Two people running `fetch-cache` on the same commit get the same
answers.

This pins the answers to questions already asked. A build that meets a
substance none of the caches has seen still asks the services for it, and
those answers are today's.

To read an archive from somewhere else, set `BRIGHTWAY_FLOWS_CACHE_URL` or pass
`--url`. A local path or a `file://` URL is read where it lies — a shared
drive, a USB stick, an archive a CI job already downloaded. An archive from
anywhere but the default is not checked against a digest, because the project
does not know one. Caches the data directory already holds are kept rather
than replaced, because they may contain lookups the archive predates;
`--overwrite` replaces them.

To publish one from a machine that has done the work:

```bash
uv run brightway-flows pack-cache --list                 # what would go in
uv run brightway-flows pack-cache -o /tmp/cache.tar.gz   # write it
```

What is in the archive is a fixed list — the per-record web caches — and
unpacking writes nothing else, whatever the archive contains. Five things are
deliberately outside it:

- `settings.json`, which holds the Common Chemistry API key. Archives get
  handed to other people.
- The source lists. ecoinvent's flows arrive under terms the licence holder
  sets, so fetch those yourself. BAFU's ecoSpold export and AGRIBALYSE's
  SimaPro export are downloaded by `fetch-source` from the project's own copy
  on `files.brightway.dev`, each checked against its digest.
- Build outputs — `consensus-flows.sqlite3`, the layered artifacts, the logs. A
  fetched cache should not be mistakable for a build that never ran.
- `EF-v3.1.zip`. It is 200 MB, and one `brightway-flows download` away from
  a public URL; carrying it would triple the archive to save a request nobody
  is rate-limiting. When the JRC's site does not answer, `download` reads the
  same archive from `https://files.brightway.dev/EF-v3.1.zip` instead and
  checks that it is the copy the project holds (SHA-256 `18763515…afb27`).
- The ChEBI dump and the GLAD workbook. Each is one download of a fixed
  version, checked against its digest: ChEBI release 250 from the EBI's
  archive, and the GLAD workbook as of commit `124bef3` of
  `One-Click-LCA/GLAD-ElementaryFlowResources`. `chebi` and
  `ingest-glad-mapping` fetch them.

Nothing in the archive expires on its own, exactly as nothing in the data
directory does. `pack-cache --list` and the `packed_at` the fetch logs are how
you tell how old an archive is. Moving to a newer ChEBI release or GLAD
workbook is a change to the release or commit the code names, not a flag:
`chebi --force` downloads release 250 again.

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
