import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from santander.sql import SQL_DIR, run_sql_file

PRODUCT_CODES = [
    "ahor_fin", "aval_fin", "cco_fin", "cder_fin", "cno_fin", "ctju_fin", "ctma_fin", "ctop_fin",
    "ctpp_fin", "deco_fin", "deme_fin", "dela_fin", "ecue_fin", "fond_fin", "hip_fin", "plan_fin",
    "pres_fin", "reca_fin", "tjcr_fin", "valo_fin", "viv_fin", "nomina", "nom_pens", "recibo",
]  # fmt: skip
RAW_COLUMNS = [
    "fecha_dato", "ncodpers", "ind_empleado", "pais_residencia", "sexo", "age", "fecha_alta",
    "ind_nuevo", "antiguedad", "indrel", "ult_fec_cli_1t", "indrel_1mes", "tiprel_1mes", "indresi",
    "indext", "conyuemp", "canal_entrada", "indfall", "tipodom", "cod_prov", "nomprov",
    "ind_actividad_cliente", "renta", "segmento",
] + [f"ind_{c}_ult1" for c in PRODUCT_CODES]  # fmt: skip

NORMAL = {
    "fecha_dato": "2015-01-28", "ncodpers": "  1375586", "ind_empleado": "N",
    "pais_residencia": "ES", "sexo": "H", "age": " 35", "fecha_alta": "2015-01-12",
    "ind_nuevo": " 0", "antiguedad": "      6", "indrel": " 1", "indrel_1mes": "1.0",
    "tiprel_1mes": "A", "indresi": "S", "indext": "N", "canal_entrada": "KHL", "indfall": "N",
    "tipodom": " 1", "cod_prov": " 8", "nomprov": "BARCELONA", "ind_actividad_cliente": " 1",
    "renta": "87218.1", "segmento": "02 - PARTICULARES",
}  # fmt: skip


def _row(**overrides):
    row = {c: None for c in RAW_COLUMNS}
    row.update(NORMAL)
    row.update({f"ind_{c}_ult1": "0" for c in PRODUCT_CODES})
    row["ind_nomina_ult1"] = row["ind_nom_pens_ult1"] = " 0"
    row.update(overrides)
    return row


@pytest.fixture
def cleaned(tmp_path):
    rows = [
        _row(),
        # the empty-demographics pattern seen in 2015-01..06: products still valid
        {
            **{c: None for c in RAW_COLUMNS},
            "fecha_dato": "2015-02-28",
            "ncodpers": "  1050611",
            "age": "NA",
            "antiguedad": "NA",
            **{f"ind_{c}_ult1": "0" for c in PRODUCT_CODES},
            "ind_cco_fin_ult1": "1",
            "ind_nomina_ult1": None,
            "ind_nom_pens_ult1": None,
        },
        _row(ncodpers=" 42", age="164", antiguedad="-999999", indrel_1mes="P", indrel="99"),
        _row(ncodpers=" 43", indrel_1mes="3", ind_tjcr_fin_ult1="1"),
    ]
    raw = tmp_path / "raw.parquet"
    table = pa.table({c: pa.array([r[c] for r in rows], pa.string()) for c in RAW_COLUMNS})
    pq.write_table(table, raw)
    out = tmp_path / "out.parquet"
    run_sql_file(SQL_DIR / "01_clean.sql", raw=raw, out=out)
    con = duckdb.connect()
    return {r[1]: dict(zip([d[0] for d in con.description], r, strict=True))
            for r in con.execute(f"SELECT * FROM read_parquet('{out}')").fetchall()}  # fmt: skip


def test_ids_and_numbers_are_trimmed_and_typed(cleaned):
    row = cleaned[1375586]
    assert row["age"] == 35
    assert row["tenure_months"] == 6
    assert row["province_code"] == 8
    assert row["income"] == pytest.approx(87218.1)
    assert row["customer_type_month"] == "1"
    assert row["is_primary_customer"] is True
    assert str(row["month"]) == "2015-01-28"


def test_empty_demographic_rows_are_kept_with_products(cleaned):
    row = cleaned[1050611]
    assert row["age"] is None and row["tenure_months"] is None and row["sex"] is None
    assert row["p_current_account"] == 1
    assert row["p_payroll"] is None  # unknown, not zero


def test_missing_markers_become_null(cleaned):
    row = cleaned[42]
    assert row["age"] is None  # 164
    assert row["tenure_months"] is None  # -999999
    assert row["customer_type_month"] == "P"
    assert row["is_primary_customer"] is False


def test_codes_are_normalised_and_products_named(cleaned):
    assert cleaned[43]["customer_type_month"] == "3"
    assert cleaned[43]["p_credit_card"] == 1
    product_cols = [c for c in cleaned[43] if c.startswith("p_")]
    assert len(product_cols) == 24
    assert "nomprov" not in cleaned[43] and "conyuemp" not in cleaned[43]
