# Deployment

The [review application](review-app.md) is served on a production host using
**gunicorn** behind an **nginx** reverse proxy.

It is a read-only view over one file. The host needs
`consensus-flows.sqlite3` in the directory the application resolves, which
`BRIGHTWAY_FLOWS_DATA_DIR` can override, and nothing else — the JSON review
files it used to need are tables in that database now. It does not run the
pipeline; refresh the data by running a build.

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

Install gunicorn into the project:

```bash
uv add gunicorn
```

## Running with gunicorn

There is one WSGI entry point, `wsgi/app.py`. Run it from the project root
using `uv run`:

```bash
uv run gunicorn --bind 127.0.0.1:5000 --workers 2 wsgi.app:application
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
package on the path. Run from the project root so that `wsgi/` is importable,
or pass `--chdir /path/to/brightway-flows`.

### Environment variables

| Variable | App | Default | Description |
|---|---|---|---|
| `BRIGHTWAY_FLOWS_DATA_DIR` | all | platform data directory | Where `consensus-flows.sqlite3` is read from |
| `BRIGHTWAY_FLOWS_DOCS_DIR` | all | the checkout's `docs/` | Where the documentation served at `/docs/` is read from |

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
ExecStart=/usr/local/bin/uv run gunicorn \
    --bind 127.0.0.1:5000 \
    --workers 2 \
    wsgi.app:application
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

The data directory has to be readable by `User`, and is where the application
looks for `consensus-flows.sqlite3`. It opens the file read-only, so the
pipeline can rewrite it under a running server; restart the service afterwards
only if you want the workers to drop their page cache.
