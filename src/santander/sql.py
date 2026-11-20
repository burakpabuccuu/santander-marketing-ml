"""Run the SQL files in ``sql/`` with DuckDB.

SQL files use ``{name}`` placeholders for file paths only; values never come from users.
"""

import argparse
import time
from pathlib import Path

import duckdb

from santander.config import CUSTOMER_MONTH, RAW_PARQUET, ROOT, TARGETS

SQL_DIR = ROOT / "sql"

# Default inputs and outputs for each pipeline step.
STEPS: dict[str, dict[str, Path]] = {
    "01_clean": {"raw": RAW_PARQUET, "out": CUSTOMER_MONTH},
    "02_targets": {"customer_month": CUSTOMER_MONTH, "out": TARGETS},
}


def run_sql_file(path: Path, memory_limit: str = "3GB", **paths: Path) -> None:
    """Fill the path placeholders in ``path`` and execute it."""
    sql = path.read_text(encoding="utf-8").format(**{k: v.as_posix() for k, v in paths.items()})
    if "out" in paths:
        paths["out"].parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute(f"SET memory_limit = '{memory_limit}'")
    con.execute(sql)
    con.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one pipeline SQL step.")
    parser.add_argument("step", choices=sorted(STEPS))
    args = parser.parse_args(argv)

    start = time.perf_counter()
    run_sql_file(SQL_DIR / f"{args.step}.sql", **STEPS[args.step])
    out = STEPS[args.step]["out"]
    rows = duckdb.execute(f"SELECT count(*) FROM read_parquet('{out.as_posix()}')").fetchone()[0]
    print(f"{args.step}: {rows:,} rows -> {out} in {time.perf_counter() - start:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
