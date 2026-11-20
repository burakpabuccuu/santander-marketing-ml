"""Open the pipeline outputs in the DuckDB web UI for interactive exploration.

Creates a small local database (data/processed/explore.duckdb) holding only views over the
Parquet files, so every table is browsable by name without copying any data, then starts
the DuckDB UI in the default browser. Stop it with Ctrl+C.
"""

import argparse

import duckdb

from santander.config import CUSTOMER_MONTH, DATA_PROCESSED, FEATURES, RAW_PARQUET, TARGETS

EXPLORE_DB = DATA_PROCESSED / "explore.duckdb"
TABLES = {
    "raw": RAW_PARQUET,
    "customer_month": CUSTOMER_MONTH,
    "targets": TARGETS,
    "features": FEATURES,
}


def build_views(db_path=EXPLORE_DB) -> list[str]:
    """(Re)create one view per existing Parquet output. Returns the view names."""
    con = duckdb.connect(str(db_path))
    created = []
    for name, path in TABLES.items():
        if path.exists():
            con.execute(
                f"CREATE OR REPLACE VIEW {name} AS SELECT * FROM read_parquet('{path.as_posix()}')"
            )
            created.append(name)
        else:
            con.execute(f"DROP VIEW IF EXISTS {name}")
    con.close()
    return created


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--no-browser", action="store_true", help="start the server without opening a browser"
    )
    args = parser.parse_args(argv)

    views = build_views()
    print(f"Views: {', '.join(views) or 'none (run the pipeline first)'}")
    # Not read-only: the UI keeps its notebooks in its own attached database, and a read-only
    # instance makes every attached database read-only too. The data is still safe: the tables
    # here are views over Parquet files, which no query in the UI can modify.
    con = duckdb.connect(str(EXPLORE_DB))
    con.execute("CALL start_ui_server()" if args.no_browser else "CALL start_ui()")
    print("DuckDB UI: http://localhost:4213  (Ctrl+C to stop)")
    try:
        while True:
            input()
    except (KeyboardInterrupt, EOFError):
        pass
    con.execute("CALL stop_ui_server()")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
