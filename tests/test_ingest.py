import zipfile

import pyarrow.parquet as pq

from santander.ingest import zip_to_parquet

# Mirrors the quirks of the real file: quoted header, padded numbers, "NA" text, blanks.
SAMPLE = (
    '"fecha_dato","ncodpers","age","antiguedad","renta","ind_tjcr_fin_ult1"\n'
    '2015-01-28,1375586," 35","      6",87218.1,0\n'
    '2015-01-28,1050611," 23","     NA",,1\n'
    '2015-02-28,1375586," 35","      7",NA,NA\n'
)


def _make_zip(tmp_path):
    zip_path = tmp_path / "train_ver2.csv.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("train_ver2.csv", SAMPLE)
    return zip_path


def test_rows_and_columns_survive(tmp_path):
    out = tmp_path / "train_raw.parquet"
    rows = zip_to_parquet(_make_zip(tmp_path), out, block_size=1 << 10)

    table = pq.read_table(out)
    assert rows == 3
    assert table.num_rows == 3
    assert table.column_names == [
        "fecha_dato",
        "ncodpers",
        "age",
        "antiguedad",
        "renta",
        "ind_tjcr_fin_ult1",
    ]


def test_everything_is_text_and_na_is_null(tmp_path):
    out = tmp_path / "train_raw.parquet"
    zip_to_parquet(_make_zip(tmp_path), out)
    table = pq.read_table(out).to_pydict()

    assert all(str(t) == "string" for t in pq.read_schema(out).types)
    assert table["age"][0] == " 35"  # padding kept; trimmed and cast later in SQL
    assert table["renta"][1] is None  # blank
    assert table["renta"][2] is None  # "NA"
    assert table["ind_tjcr_fin_ult1"][2] is None


def test_no_temp_file_left_behind(tmp_path):
    out = tmp_path / "train_raw.parquet"
    zip_to_parquet(_make_zip(tmp_path), out)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["train_raw.parquet", "train_ver2.csv.zip"]
