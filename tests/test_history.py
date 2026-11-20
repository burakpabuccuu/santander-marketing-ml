"""History features: point-in-time correctness and hand-checked values."""

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
ALL_MONTHS = [date(2015, m, 28) for m in range(1, 13)] + [date(2016, m, 28) for m in range(1, 6)]
SEP_2015 = date(2015, 9, 28)


def _rows(future_mortgage=False):
    """(customer_id, month, is_active, current_account, e_account, mortgage)

    1: current account throughout, opens an e-account in 2015-09, becomes active in 2015-09.
    2: same, but missing from the data in 2015-08 (a gap).
    With future_mortgage, customer 1 also takes a mortgage from 2015-11 on.
    """
    rows = []
    for m in ALL_MONTHS:
        active = int(m >= SEP_2015)
        e_acc = int(m >= SEP_2015)
        mortgage = int(future_mortgage and m >= date(2015, 11, 28))
        rows.append((1, m, active, 1, e_acc, mortgage))
        if m != date(2015, 8, 28):
            rows.append((2, m, active, 1, e_acc, 0))
    return rows


def _features(tmp_path, rows, tag):
    con = duckdb.connect()
    con.execute(
        "CREATE TABLE r (customer_id BIGINT, month DATE, act INT, ca INT, ea INT, mort INT)"
    )
    con.executemany("INSERT INTO r VALUES (?, ?, ?, ?, ?, ?)", rows)
    source = {"current_account": "ca", "e_account": "ea", "mortgage": "mort"}
    products = ", ".join(f"{source.get(p, '0')}::TINYINT AS p_{p}" for p in PRODUCTS)
    cm, tg, out = (tmp_path / f"{tag}_{n}.parquet" for n in ("cm", "targets", "features"))
    con.execute(f"""
        COPY (
            SELECT customer_id, month, 'N' AS employee_status, 'H' AS sex, 40 AS age,
                   8 AS province_code, 50000.0 AS income, '02 - PARTICULARES' AS segment,
                   60 AS tenure_months, 0::TINYINT AS is_new_customer,
                   TRUE AS is_primary_customer, '1' AS customer_type_month,
                   'A' AS relation_type_month, TRUE AS is_resident, FALSE AS is_foreigner,
                   FALSE AS is_deceased, 'KHE' AS join_channel, act::TINYINT AS is_active,
                   {products}
            FROM r
        ) TO '{cm}' (FORMAT parquet)
    """)
    run_sql_file(SQL_DIR / "02_targets.sql", customer_month=cm, out=tg)
    run_sql_file(SQL_DIR / "03_features.sql", customer_month=cm, targets=tg, out=out)
    rel = con.execute(f"SELECT * FROM read_parquet('{out}')")
    cols = [d[0] for d in rel.description]
    return {(r[0], r[1]): dict(zip(cols, r, strict=True)) for r in rel.fetchall()}


@pytest.fixture
def feats(tmp_path):
    return _features(tmp_path, _rows(), "base")


def test_no_feature_uses_the_future(tmp_path, feats):
    """Changing months after t must leave every feature at t unchanged (labels may change)."""
    changed = _features(tmp_path, _rows(future_mortgage=True), "future")
    cutoff = date(2015, 10, 28)  # the mortgage appears in 2015-11
    checked = 0
    for key, row in feats.items():
        if key[1] <= cutoff:
            before = {k: v for k, v in row.items() if not k.startswith("y_")}
            after = {k: v for k, v in changed[key].items() if not k.startswith("y_")}
            assert before == after, key
            checked += 1
    assert checked == 7  # 2015-07..10: customer 1 x4, customer 2 x3 (missing in 2015-08)
    # sanity check that the change itself is visible from 2015-11 on
    assert changed[(1, date(2015, 11, 28))]["products_added_1m"] == 1


def test_values_around_a_new_product(feats):
    sep = feats[(1, SEP_2015)]
    assert sep["n_products_1m_ago"] == 1
    assert sep["products_added_1m"] == 1 and sep["products_added_3m"] == 1
    assert sep["products_dropped_1m"] == 0
    assert sep["months_since_product_change"] == 0
    assert sep["activity_change_1m"] == 1

    nov = feats[(1, date(2015, 11, 28))]
    assert nov["products_added_1m"] == 0
    assert nov["products_added_3m"] == 1  # 2015-08 had no e-account
    assert nov["months_since_product_change"] == 2


def test_lookback_is_capped_at_six_months(feats):
    # last change was 2015-09, more than 5 months before 2016-03
    assert feats[(1, date(2016, 3, 28))]["months_since_product_change"] == 6


def test_frozen_activity_period_is_unknown_not_zero(feats):
    assert feats[(1, date(2015, 7, 28))]["activity_change_1m"] is None


def test_gap_month_is_not_observed_rather_than_empty(feats):
    sep = feats[(2, SEP_2015)]
    assert sep["months_observed_3m"] == 2  # 2015-06 and 2015-07, not 2015-08
    assert sep["n_products_1m_ago"] is None  # unknown, not 0
    assert sep["products_added_1m"] is None
    assert sep["products_added_3m"] == 1  # 2015-06 is observed
    assert feats[(1, SEP_2015)]["months_observed_3m"] == 3
