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


def _months(start, end):
    y, m = start
    out = []
    while (y, m) <= end:
        out.append(date(y, m, 28))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


ALL = _months((2015, 6), (2016, 5))


def d(y, m):
    return date(y, m, 28)


def _rows():
    """(customer_id, month, current_account, credit_card, is_deceased)"""
    rows = []
    # 1: always has a current account, takes a credit card in 2015-09
    rows += [(1, m, 1, int(m >= d(2015, 9)), False) for m in ALL]
    # 2: churns: products until 2015-09, none in 2015-10 and 2015-11, then leaves
    rows += [(2, m, int(m <= d(2015, 9)), 0, False) for m in ALL if m <= d(2015, 11)]
    # 3: one-month dip in 2015-10, back in 2015-11
    rows += [(3, m, int(m != d(2015, 10)), 0, False) for m in ALL]
    # 4: leaves the panel after 2015-09
    rows += [(4, m, 1, 0, False) for m in ALL if m <= d(2015, 9)]
    # 5: never owns anything
    rows += [(5, m, 0, 0, False) for m in ALL]
    # 6: deceased flag
    rows += [(6, m, 1, 0, True) for m in ALL]
    return rows


@pytest.fixture
def targets(tmp_path):
    con = duckdb.connect()
    product_cols = ", ".join(
        f"{'cc' if p == 'credit_card' else 'ca' if p == 'current_account' else '0'}"
        f"::TINYINT AS p_{p}"
        for p in PRODUCTS
    )
    con.execute("CREATE TABLE r (customer_id BIGINT, month DATE, ca INT, cc INT, dec BOOLEAN)")
    con.executemany("INSERT INTO r VALUES (?, ?, ?, ?, ?)", _rows())
    cm = tmp_path / "customer_month.parquet"
    con.execute(
        f"COPY (SELECT customer_id, month, dec AS is_deceased, {product_cols} FROM r) "
        f"TO '{cm}' (FORMAT parquet)"
    )
    out = tmp_path / "targets.parquet"
    run_sql_file(SQL_DIR / "02_targets.sql", customer_month=cm, out=out)
    rows = con.execute(f"SELECT * FROM read_parquet('{out}')").fetchall()
    return {(r[0], r[1]): {"split": r[2], "xs": r[3], "churn": r[4]} for r in rows}


def test_population_rules(targets):
    customers = {c for c, _ in targets}
    assert 5 not in customers  # no products
    assert 6 not in customers  # deceased
    assert min(m for _, m in targets) == d(2015, 7)  # first half of 2015 excluded


def test_cross_sell_label(targets):
    assert targets[(1, d(2015, 7))]["xs"] == 0
    assert targets[(1, d(2015, 8))]["xs"] == 1  # card appears in 2015-09
    assert targets[(1, d(2015, 9))]["xs"] is None  # already has the card
    assert targets[(4, d(2015, 9))]["xs"] is None  # not observed next month


def test_churn_needs_two_empty_months(targets):
    assert targets[(2, d(2015, 8))]["churn"] == 0
    assert targets[(2, d(2015, 9))]["churn"] == 1
    assert (2, d(2015, 10)) not in targets  # zero products: outside the population
    assert targets[(3, d(2015, 9))]["churn"] == 0  # one-month dip is not churn
    assert targets[(4, d(2015, 9))]["churn"] == 1  # left the panel


def test_churn_undefined_beyond_the_data(targets):
    assert targets[(1, d(2016, 3))]["churn"] == 0
    assert targets[(1, d(2016, 4))]["churn"] is None  # 2016-06 is not in the data


def test_split_has_gaps(targets):
    assert targets[(1, d(2015, 11))]["split"] == "train"
    assert targets[(1, d(2015, 12))]["split"] is None
    assert targets[(1, d(2016, 1))]["split"] == "valid"
    assert targets[(1, d(2016, 2))]["split"] is None
    assert targets[(1, d(2016, 3))]["split"] == "test"
