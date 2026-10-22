"""Serve the curation design locally; optionally read a published SQLite snapshot."""

from __future__ import annotations

import argparse
import os
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    os.environ["BRIGHTWAY_FLOWS_DATA_DIR"] = str(root / ".data")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=5188)
    parser.add_argument(
        "--database",
        type=Path,
        default=root / ".data/published-consensus-flows.sqlite3",
    )
    parser.add_argument(
        "--register",
        type=Path,
        help="Local curation register with sibling sources directory",
    )
    args = parser.parse_args()
    from brightway_flows.webapps.app import create_app

    app = create_app(database_path=args.database, docs_path=root / "docs")
    if args.register:
        app.config["CURATION_REGISTER_PATH"] = args.register.resolve()
    app.run(host="127.0.0.1", port=args.port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
