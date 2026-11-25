# Deployment

The [review application](review-app.md) is served on a production host using
**gunicorn** behind an **nginx** reverse proxy.

It is a read-only view over one published release. The host needs one small
file, `release.json`, which says which release that is; the application
downloads the release's database from Zenodo itself. It does not run the
pipeline, and no build has to be copied to the host.

## Which data it serves

Release 1.1.0, for example, is six files on
[Zenodo](https://zenodo.org/records/23554066): the database
(`consensus-flows.sqlite3`, 2.6 GB), the three JSON exports, the release
snapshot and the migration from 1.0.0. Every page of the application reads
the database and nothing else, so that is the one file a host downloads: a
host whose `release.json` names 1.1.0 puts `consensus-flows.sqlite3` in
`published/1.1.0/` of its data directory, checks it against the SHA-256 the
file records, and serves from there. The other five stay on Zenodo. The
Download page and the foot of the Build page list all six, with the sizes
`release.json` records, and link to Zenodo for them.

`release.json` is written by `brightway-flows release-upload` when the release
is uploaded ([Publishing a release](running.md#publishing-a-release)). The
application looks for it in the data directory, or at the path
`BRIGHTWAY_FLOWS_RELEASE_FILE` names. It is also where the version, the date,
the DOI and the checksums on the homepage and the Download page come from.

The download happens the first time the application starts with a release it
does not have. On a server, do it before starting instead:

```bash
uv run --no-sync brightway-flows release-download
```

gunicorn stops a worker that takes longer than its timeout to start, and
2.6 GB takes longer than that. The command carries on from where an
interrupted run stopped; with the database in place it does nothing, and
starting the application asks nothing of Zenodo. If the database is not
there and cannot be downloaded, the application still starts, serves the
documentation, and says on every data page which command to run.

Three cases read a build on the host instead of a release:

- `BRIGHTWAY_FLOWS_WEBAPP_LOCAL=1` is set, or the application was started
  with `brightway-flows webapp --local`. This is for development, and for a
  review server showing a build that is not released yet. It reads
  `consensus-flows.sqlite3` from the data directory, and still shows the
  release's version and DOI if there is a `release.json`.
- There is no `release.json`. The application has no release to download, so
  it reads the data directory, and the version, date, DOI and checksums are
  shown as placeholders.
- `release.json` is named by `BRIGHTWAY_FLOWS_RELEASE_FILE` and is missing or
  malformed. This one is an error: the application does not start.

It also serves this documentation at `/docs/`, read from the `docs/` directory
of the checkout it runs from. Nothing is built: the markdown is rendered per
request, so a host serves whatever its checkout says, and `git pull` is the
whole deployment step for a corrected page. A host running the package without
a checkout beside it gets a page saying where it looked, and can be pointed at
a tree with `BRIGHTWAY_FLOWS_DOCS_DIR`.

`/` is the homepage, not the documentation. It reads its counts and its example
flow from the database, and its "Where to start" links from the same `docs/`
tree; without the database it leaves the numbers out, and without `docs/` it
leaves the links out, so neither is needed for it to render.

## Prerequisites

gunicorn and Flask come with the `webapp` extra. A server that only serves a
build it was given needs nothing else, and none of what fetching and building
need:

```bash
uv sync --no-default-groups --extra webapp
```

That is 38 packages. A plain `uv sync` installs everything a checkout uses —
129 packages, with what fetching, building and testing need — and serves the
same application.

**Start the server with `uv run --no-sync`**, as every command on this page
does. A bare `uv run` first brings the environment up to what a checkout
installs, so the first start would put the other 91 packages back.

## Running with gunicorn

There is one WSGI entry point, `wsgi/app.py`. Run it from the project root
using `uv run --no-sync`:

```bash
uv run --no-sync gunicorn --bind 127.0.0.1:5000 --workers 2 wsgi.app:application
```

This block used to list four, on ports 5001 to 5004 — one of which,
`wsgi.merge:application`, had not imported since `run_report` replaced
`merge_review` and the module it loaded was deleted. Anyone following these
instructions got an `ImportError`. There is one entry point now, and a test
imports every file under `wsgi/` and asserts it exposes an application.

Workers are cheap here: nothing is loaded at import, and each request opens one
read-only connection and closes it. The applications this replaces read a
189 MB JSON file and a 267 MB cache into memory before a worker could serve
anything.

`uv run` ensures gunicorn uses the project's virtualenv and has the project
package on the path, and `--no-sync` has it use the environment as `uv sync`
left it. Run from the project root so that `wsgi/` is importable,
or pass `--chdir /path/to/brightway-flows`.

### Environment variables

| Variable | App | Default | Description |
|---|---|---|---|
| `BRIGHTWAY_FLOWS_DATA_DIR` | all | platform data directory | Where `release.json` is looked for, where the release is downloaded to (`published/<version>/`), and where a local build is read from |
| `BRIGHTWAY_FLOWS_RELEASE_FILE` | all | `release.json` in the data directory | The file naming the published release to serve |
| `BRIGHTWAY_FLOWS_WEBAPP_LOCAL` | all | unset | Set to `1` to serve the build in the data directory instead of the published release |
| `BRIGHTWAY_FLOWS_DOCS_DIR` | all | the checkout's `docs/` | Where the documentation served at `/docs/` is read from |
| `BRIGHTWAY_FLOWS_EXPECTATIONS_DIR` | all | the checkout's `expectations/` | Where the files shown at `/expectations/` are read from |

There is no variable that takes the SQLite database off the site. It may be
published, so `/run/` and `/download/` both offer it and nothing has to be
switched on.

## nginx configuration

One `server` block. Example, served at `/review/` on `example.com`:

```nginx
server {
    listen 443 ssl;
    server_name example.com;

    location /review/ {
        proxy_pass         http://127.0.0.1:5000/;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
    }
}
```

At its own subdomain (`review.example.com`) use a plain
`proxy_pass http://127.0.0.1:5000;` without a sub-path, which requires no URL
rewriting.

## Systemd service (optional)

Example unit file at `/etc/systemd/system/bwf-review.service`:

```ini
[Unit]
Description=Brightway flows review webapp
After=network.target

[Service]
User=www-data
WorkingDirectory=/path/to/brightway-flows
Environment=BRIGHTWAY_FLOWS_DATA_DIR=/srv/brightway-flows
TimeoutStartSec=infinity
ExecStartPre=/usr/local/bin/uv run --no-sync brightway-flows release-download
ExecStart=/usr/local/bin/uv run --no-sync gunicorn \
    --bind 127.0.0.1:5000 \
    --workers 2 \
    wsgi.app:application
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

`ExecStartPre` downloads the release before gunicorn starts, and does nothing
once it is there; `TimeoutStartSec=infinity` lets the first download finish.
The data directory has to be writable by `User` for that download, and holds
`release.json`. To move to a new release, replace `release.json` and restart
the service.

A server set to read a local build (`BRIGHTWAY_FLOWS_WEBAPP_LOCAL=1`) opens
`consensus-flows.sqlite3` read-only, so the pipeline can rewrite it under a
running server; restart the service afterwards only if you want the workers
to drop their page cache. Leave `ExecStartPre` out of such a unit.
