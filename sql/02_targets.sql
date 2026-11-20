-- Modelling population and labels, one row per customer per snapshot month.
-- Input:  {customer_month}  (output of 01_clean.sql)
-- Output: {out}             (data/processed/targets.parquet)
--
-- Population at snapshot month t (decided from profiling, see README "Data findings"):
--   * t >= 2015-07-28. Before July 2015 the activity flag never changes and ~200k dormant,
--     long-tenure customers are missing from the panel, so the first half-year is a
--     different data regime.
--   * the customer owns at least one product at t and is not flagged deceased.
--     Zero-product customers buy a credit card 11x less often (0.06% vs 0.65% a month);
--     reactivating them is a different campaign, not cross-sell.
--
-- Labels:
--   y_cross_sell_cc  no credit card at t, has one at t+1. Defined only when the customer
--                    has no card at t and appears at t+1.
--   y_churn          zero products (or absent) at both t+1 and t+2. Two months are required
--                    so a single missing snapshot or a one-month dip is not counted.
--                    Defined only when month t+2 exists in the data.
--
-- Split, with a gap so no training label is observed after a validation/test snapshot:
--   train t in 2015-07..2015-11 (latest label month 2016-01)
--   valid t =  2016-01          (2015-12 left out as a gap)
--   test  t =  2016-03          (2016-02 left out as a gap; touched once)

COPY (
    WITH m AS (
        SELECT
            customer_id,
            month,
            coalesce(is_deceased, FALSE) AS is_deceased,
            p_credit_card,
            coalesce(p_savings, 0) + coalesce(p_guarantees, 0) + coalesce(p_current_account, 0)
            + coalesce(p_derivatives, 0) + coalesce(p_payroll_account, 0)
            + coalesce(p_junior_account, 0) + coalesce(p_mas_particular_account, 0)
            + coalesce(p_particular_account, 0) + coalesce(p_particular_plus_account, 0)
            + coalesce(p_short_term_deposit, 0) + coalesce(p_medium_term_deposit, 0)
            + coalesce(p_long_term_deposit, 0) + coalesce(p_e_account, 0) + coalesce(p_funds, 0)
            + coalesce(p_mortgage, 0) + coalesce(p_pension_plan, 0) + coalesce(p_loans, 0)
            + coalesce(p_taxes, 0) + coalesce(p_credit_card, 0) + coalesce(p_securities, 0)
            + coalesce(p_home_account, 0) + coalesce(p_payroll, 0) + coalesce(p_pensions, 0)
            + coalesce(p_direct_debit, 0) AS n_products
        FROM read_parquet('{customer_month}')
    ),
    last_month AS (SELECT max(month) AS m FROM m),
    joined AS (
        SELECT
            a.customer_id,
            a.month,
            a.n_products,
            a.p_credit_card,
            b.p_credit_card AS cc_next,
            b.n_products    AS n_next,
            c.n_products    AS n_next2,
            a.month + INTERVAL 2 MONTH <= (SELECT m FROM last_month) AS horizon2_observed
        FROM m a
        LEFT JOIN m b ON b.customer_id = a.customer_id AND b.month = a.month + INTERVAL 1 MONTH
        LEFT JOIN m c ON c.customer_id = a.customer_id AND c.month = a.month + INTERVAL 2 MONTH
        WHERE a.month >= DATE '2015-07-28'
          AND a.n_products > 0
          AND NOT a.is_deceased
    )
    SELECT
        customer_id,
        CAST(month AS DATE) AS month,
        CASE
            WHEN month BETWEEN DATE '2015-07-28' AND DATE '2015-11-28' THEN 'train'
            WHEN month = DATE '2016-01-28' THEN 'valid'
            WHEN month = DATE '2016-03-28' THEN 'test'
        END AS split,
        CASE WHEN p_credit_card = 0 AND cc_next IS NOT NULL
             THEN CAST(cc_next AS TINYINT) END AS y_cross_sell_cc,
        CASE WHEN horizon2_observed
             THEN CAST(coalesce(n_next, 0) = 0 AND coalesce(n_next2, 0) = 0 AS TINYINT)
        END AS y_churn
    FROM joined
    ORDER BY customer_id, month
) TO '{out}' (FORMAT parquet, COMPRESSION zstd);
