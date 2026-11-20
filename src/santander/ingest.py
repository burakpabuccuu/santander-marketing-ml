"""Stream the Kaggle CSV out of its zip into a single Parquet file.

The CSV is ~2.3 GB unzipped, so it is never extracted to disk or loaded whole:
it is read in blocks straight from the zip and written block by block.
Every column is kept as text here; types are cast later in SQL, because the raw
file mixes padded numbers ("  35"), "NA" strings and blanks in the same column.
"""

import argparse
import sys
import zipfile
from pathlib import Path

import pyarrow as pa
import pyarrow.csv as pacsv
import pyarrow.parquet as pq

from santander.config import RAW_PARQUET, RAW_ZIP


def _header(stream) -> list[str]:
    first = stream.readline().decode("utf-8").strip()
    return [name.strip().strip('"') for name in first.split(",")]


def zip_to_parquet(zip_path: Path, out_path: Path, block_size: int = 64 << 20) -> int:
    """Convert the single CSV inside ``zip_path`` to ``out_path``. Returns the row count."""
    with zipfile.ZipFile(zip_path) as zf:
        csv_names = [n for n in zf.namelist() if n.endswith(".csv")]
        if len(csv_names) != 1:
            raise ValueError(f"expected one CSV in {zip_path.name}, found {csv_names}")
        name = csv_names[0]

        with zf.open(name) as stream:
            columns = _header(stream)

        convert = pacsv.ConvertOptions(
            column_types={c: pa.string() for c in columns},
            strings_can_be_null=True,
            null_values=["", "NA"],
        )
        read = pacsv.ReadOptions(block_size=block_size)

        out_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = out_path.with_suffix(".parquet.tmp")
        rows = 0
        with zf.open(name) as stream:
            reader = pacsv.open_csv(stream, read_options=read, convert_options=convert)
            with pq.ParquetWriter(tmp_path, reader.schema, compression="zstd") as writer:
                for batch in reader:
                    writer.write_batch(batch)
                    rows += batch.num_rows
        tmp_path.replace(out_path)
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--zip", type=Path, default=RAW_ZIP)
    parser.add_argument("--out", type=Path, default=RAW_PARQUET)
    args = parser.parse_args(argv)

    if not args.zip.exists():
        print(f"Missing {args.zip}. Download it from Kaggle first.", file=sys.stderr)
        return 1
    rows = zip_to_parquet(args.zip, args.out)
    size_mb = args.out.stat().st_size / 1e6
    print(f"Wrote {rows:,} rows to {args.out} ({size_mb:,.0f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
