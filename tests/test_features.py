from datetime import date

import duckdb
import pytest

from santander.sql import SQL_DIR, run_sql_file

PRODUCTS = [
    "savings", "guarantees", "current_account", "derivatives", "payroll_account",
    "junior_account", "mas_particular_account", "particular_account", "particular_plus_account",
    "short_term_deposit", "medium_term_deposit", "long_term_deposit", "e_account", "funds",
    "mortgage", "pension_plan", "loans", "taxes", "credit_card", "securities", "home_account",
    "payroll", "pensions", "direct_debit",
]  # fmt: skip
MONTHS = (
    [date(2015, 6, 28)]
    + [date(2015, m, 28) for m in range(7, 13)]
    + [date(2016, m, 28) for m in range(1, 6)]
)


def _customer_month(con, path):
    """Two customers over 2015-06..2016-05: one with income, one without and with 2 products."""
    product_cols = ", ".join(
        f"CASE WHEN '{p}' = 'current_account' THEN 1 "
        f"WHEN '{p}' = 'e_account' AND customer_id = 2 THEN 1 ELSE 0 END::TINYINT AS p_{p}"
        for p in PRODUCTS
    )
    con.execute("CREATE TABLE ids (customer_id BIGINT)")
    con.execute("INSERT INTO ids VALUES (1), (2)")
    con.execute("CREATE TABLE months (month DATE)")
    con.executemany("INSERT INTO months VALUES (?)", [(m,) for m in MONTHS])
    con.execute(f"""
        COPY (
            SELECT month, customer_id, 'N' AS employee_status, 'ES' AS country,
                   CASE customer_id WHEN 1 THEN 'H' ELSE 'V' END AS sex,
                   40 AS age, 8 AS province_code,
                   CASE customer_id WHEN 1 THEN 50000.0 END AS income,
                   '02 - PARTICULARES' AS segment, DATE '2010-01-01' AS first_contract_date,
                   60 AS tenure_months, 0::TINYINT AS is_new_customer,
                   TRUE AS is_primary_customer, '1' AS customer_type_month,
                   'A' AS relation_type_month, TRUE AS is_resident, FALSE AS is_foreigner,
                   FALSE AS is_deceased, 'KHE' AS join_channel, 1::TINYINT AS is_active,
                   {product_cols}
            FROM ids, months
        ) TO '{path}' (FORMAT parquet)
    """)


@pytest.fixture
def features(tmp_path):
    con = duckdb.connect()
    cm, tg, out = (tmp_path / f"{n}.parquet" for n in ("cm", "targets", "features"))
    _customer_month(con, cm)
    run_sql_file(SQL_DIR / "02_targets.sql", customer_month=cm, out=tg)
    run_sql_file(SQL_DIR / "03_features.sql", customer_month=cm, targets=tg, out=out)
    rel = con.execute(f"SELECT * FROM read_parquet('{out}')")
    cols = [d[0] for d in rel.description]
    return [dict(zip(cols, r, strict=True)) for r in rel.fetchall()]


def test_only_labelled_split_months(features):
    months = sorted({r["month"] for r in features})
    assert months == [date(2015, m, 28) for m in range(7, 12)] + [
        date(2016, 1, 28),
        date(2016, 3, 28),
    ]
    assert {r["split"] for r in features} == {"train", "valid", "test"}
    assert len(features) == 2 * 7


def test_sex_is_never_a_feature(features):
    assert "sex" not in features[0]
    assert "country" not in features[0]


def test_snapshot_values(features):
    one = next(r for r in features if r["customer_id"] == 1)
    two = next(r for r in features if r["customer_id"] == 2)
    assert (one["n_products"], two["n_products"]) == (1, 2)
    assert (one["income_missing"], two["income_missing"]) == (0, 1)
    assert two["income"] is None  # left missing; each model decides how to handle it
    assert one["y_cross_sell_cc"] == 0 and one["y_churn"] == 0
