-- Model features, one row per labelled customer-month (rows with a split).
-- Inputs: {customer_month} (01_clean.sql), {targets} (02_targets.sql)
-- Output: {out} (data/processed/features.parquet): keys + split + labels + features
--
-- Rule for every feature: it may only use information available at the snapshot month t.
-- Nothing from t+1 or later, otherwise the model learns from the future and its validation
-- scores are too optimistic.
--
-- Built in layers; each layer is one CTE:
--   1. snapshot  what the customer looks like at t (profile, relationship, products owned)
--   2. history   how ownership and activity changed over the months before t
--
-- History features look back a fixed number of months (at most 6), never "since the start
-- of the data": the data starts in 2015-01, so an open-ended lookback would give July 2015
-- rows 6 months of history and March 2016 rows 14. The model would then learn the calendar
-- position instead of customer behaviour, and train and test rows would not be comparable.

COPY (
    WITH
    -- Each month's product set packed into one integer, one bit per product
    -- (bit 0 = savings ... bit 23 = direct debit). Comparing two months is then cheap:
    --   bit_count(now & ~before)  products added      bit_count(before & ~now)  products dropped
    masks AS (
        SELECT
            customer_id,
            month,
            is_active,
              (coalesce(p_savings, 0)::INTEGER                 << 0)
            | (coalesce(p_guarantees, 0)::INTEGER              << 1)
            | (coalesce(p_current_account, 0)::INTEGER         << 2)
            | (coalesce(p_derivatives, 0)::INTEGER             << 3)
            | (coalesce(p_payroll_account, 0)::INTEGER         << 4)
            | (coalesce(p_junior_account, 0)::INTEGER          << 5)
            | (coalesce(p_mas_particular_account, 0)::INTEGER  << 6)
            | (coalesce(p_particular_account, 0)::INTEGER      << 7)
            | (coalesce(p_particular_plus_account, 0)::INTEGER << 8)
            | (coalesce(p_short_term_deposit, 0)::INTEGER      << 9)
            | (coalesce(p_medium_term_deposit, 0)::INTEGER     << 10)
            | (coalesce(p_long_term_deposit, 0)::INTEGER       << 11)
            | (coalesce(p_e_account, 0)::INTEGER               << 12)
            | (coalesce(p_funds, 0)::INTEGER                   << 13)
            | (coalesce(p_mortgage, 0)::INTEGER                << 14)
            | (coalesce(p_pension_plan, 0)::INTEGER            << 15)
            | (coalesce(p_loans, 0)::INTEGER                   << 16)
            | (coalesce(p_taxes, 0)::INTEGER                   << 17)
            | (coalesce(p_credit_card, 0)::INTEGER             << 18)
            | (coalesce(p_securities, 0)::INTEGER              << 19)
            | (coalesce(p_home_account, 0)::INTEGER            << 20)
            | (coalesce(p_payroll, 0)::INTEGER                 << 21)
            | (coalesce(p_pensions, 0)::INTEGER                << 22)
            | (coalesce(p_direct_debit, 0)::INTEGER            << 23) AS product_mask
        FROM read_parquet('{customer_month}')
    ),

    -- The same customer one and three calendar months earlier. Joined on the exact month,
    -- not with LAG(): 8,018 customers have gaps, and LAG would silently return an older
    -- month. A missing month stays NULL ("not observed"), which is not the same as
    -- "owned nothing".
    steps AS (
        SELECT
            m.customer_id,
            m.month,
            m.product_mask,
            m.is_active,
            p1.product_mask AS mask_1m_ago,
            p3.product_mask AS mask_3m_ago,
            p1.is_active    AS is_active_1m_ago,
            m.product_mask <> p1.product_mask AS products_changed  -- NULL if t-1 not observed
        FROM masks AS m
        LEFT JOIN masks AS p1
               ON p1.customer_id = m.customer_id AND p1.month = m.month - INTERVAL 1 MONTH
        LEFT JOIN masks AS p3
               ON p3.customer_id = m.customer_id AND p3.month = m.month - INTERVAL 3 MONTH
    ),

    history AS (
        SELECT
            customer_id,
            month,

            -- how many of the 3 previous months the customer was observed (0-3)
            count(*) OVER (
                PARTITION BY customer_id ORDER BY month
                RANGE BETWEEN INTERVAL 3 MONTH PRECEDING AND INTERVAL 1 MONTH PRECEDING
            )                                                    AS months_observed_3m,

            bit_count(mask_1m_ago)                               AS n_products_1m_ago,
            bit_count(mask_3m_ago)                               AS n_products_3m_ago,
            bit_count(product_mask & ~mask_1m_ago)               AS products_added_1m,
            bit_count(mask_1m_ago & ~product_mask)               AS products_dropped_1m,
            bit_count(product_mask & ~mask_3m_ago)               AS products_added_3m,
            bit_count(mask_3m_ago & ~product_mask)               AS products_dropped_3m,

            -- months since the product set last changed, looking back at most 6 months;
            -- 6 means "no change in the last 6 months" (same scale for every snapshot month)
            coalesce(
                date_diff('month',
                    max(CASE WHEN products_changed THEN month END) OVER (
                        PARTITION BY customer_id ORDER BY month
                        RANGE BETWEEN INTERVAL 5 MONTH PRECEDING AND CURRENT ROW
                    ),
                    month),
                6)                                               AS months_since_product_change,

            -- the activity flag is frozen until 2015-07 (first real changes appear in
            -- 2015-08), so a change before then is unknown, not zero
            CASE WHEN month >= DATE '2015-08-28'
                 THEN is_active - is_active_1m_ago END           AS activity_change_1m
        FROM steps
    ),

    snapshot AS (
        SELECT
            customer_id,
            month,

            -- profile
            age,
            tenure_months,
            income,
            CAST(income IS NULL AS TINYINT)          AS income_missing,
            segment,
            province_code,
            employee_status,
            CAST(is_foreigner AS TINYINT)            AS is_foreigner,
            CAST(is_resident AS TINYINT)             AS is_resident,
            -- sex is deliberately not selected: kept out of every model (fair lending)

            -- relationship with the bank
            join_channel,
            customer_type_month,
            relation_type_month,
            CAST(is_primary_customer AS TINYINT)     AS is_primary_customer,
            is_new_customer,
            is_active,

            -- products owned at t (credit card included: always 0 in the cross-sell base,
            -- but informative for churn)
            p_savings, p_guarantees, p_current_account, p_derivatives, p_payroll_account,
            p_junior_account, p_mas_particular_account, p_particular_account,
            p_particular_plus_account, p_short_term_deposit, p_medium_term_deposit,
            p_long_term_deposit, p_e_account, p_funds, p_mortgage, p_pension_plan, p_loans,
            p_taxes, p_credit_card, p_securities, p_home_account, p_payroll, p_pensions,
            p_direct_debit,
            coalesce(p_savings, 0) + coalesce(p_guarantees, 0) + coalesce(p_current_account, 0)
            + coalesce(p_derivatives, 0) + coalesce(p_payroll_account, 0)
            + coalesce(p_junior_account, 0) + coalesce(p_mas_particular_account, 0)
            + coalesce(p_particular_account, 0) + coalesce(p_particular_plus_account, 0)
            + coalesce(p_short_term_deposit, 0) + coalesce(p_medium_term_deposit, 0)
            + coalesce(p_long_term_deposit, 0) + coalesce(p_e_account, 0) + coalesce(p_funds, 0)
            + coalesce(p_mortgage, 0) + coalesce(p_pension_plan, 0) + coalesce(p_loans, 0)
            + coalesce(p_taxes, 0) + coalesce(p_credit_card, 0) + coalesce(p_securities, 0)
            + coalesce(p_home_account, 0) + coalesce(p_payroll, 0) + coalesce(p_pensions, 0)
            + coalesce(p_direct_debit, 0)            AS n_products
        FROM read_parquet('{customer_month}')
    )
    SELECT
        t.customer_id,
        t.month,
        t.split,
        t.y_cross_sell_cc,
        t.y_churn,
        s.* EXCLUDE (customer_id, month),
        h.* EXCLUDE (customer_id, month)
    FROM read_parquet('{targets}') AS t
    JOIN snapshot AS s USING (customer_id, month)
    JOIN history AS h USING (customer_id, month)
    WHERE t.split IS NOT NULL
    ORDER BY t.customer_id, t.month
) TO '{out}' (FORMAT parquet, COMPRESSION zstd);
