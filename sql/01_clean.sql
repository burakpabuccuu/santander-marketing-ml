-- Raw text columns -> one typed row per customer per month.
-- Input:  {raw}  (data/processed/train_raw.parquet, every column text)
-- Output: {out}  (data/processed/customer_month.parquet)
--
-- Cleaning rules come from profiling the full file (see README, "Data quality"):
--   * numbers are space-padded ("  35"), so everything is trimmed before casting;
--   * 27,734 rows (2015-01..06, 7,340 customers) have every demographic field empty but
--     valid product flags: they are kept, with demographics left NULL;
--   * antiguedad uses -999999 as a missing marker; ages above 100 are treated as missing;
--   * indrel_1mes mixes "1" and "1.0" for the same code;
--   * dropped: tipodom (constant), nomprov (duplicate of cod_prov),
--     conyuemp (99.99% empty), ult_fec_cli_1t (99.8% empty).

COPY (
    SELECT
        CAST(fecha_dato AS DATE)                               AS month,
        CAST(trim(ncodpers) AS BIGINT)                         AS customer_id,

        -- demographics
        trim(ind_empleado)                                     AS employee_status,
        trim(pais_residencia)                                  AS country,
        trim(sexo)                                             AS sex,  -- kept for fairness checks only, never a feature
        CASE WHEN try_cast(trim(age) AS INTEGER) BETWEEN 0 AND 100
             THEN try_cast(trim(age) AS INTEGER) END           AS age,
        try_cast(trim(cod_prov) AS INTEGER)                    AS province_code,
        try_cast(renta AS DOUBLE)                              AS income,
        nullif(trim(segmento), '')                             AS segment,

        -- relationship with the bank
        try_cast(fecha_alta AS DATE)                           AS first_contract_date,
        CASE WHEN try_cast(trim(antiguedad) AS INTEGER) >= 0
             THEN try_cast(trim(antiguedad) AS INTEGER) END    AS tenure_months,
        try_cast(trim(ind_nuevo) AS TINYINT)                   AS is_new_customer,
        try_cast(trim(indrel) AS INTEGER) = 1                  AS is_primary_customer,
        CASE WHEN trim(indrel_1mes) = 'P' THEN 'P'
             ELSE CAST(try_cast(trim(indrel_1mes) AS DOUBLE) AS INTEGER)::VARCHAR
        END                                                    AS customer_type_month,
        trim(tiprel_1mes)                                      AS relation_type_month,
        trim(indresi) = 'S'                                    AS is_resident,
        trim(indext) = 'S'                                     AS is_foreigner,
        trim(indfall) = 'S'                                    AS is_deceased,
        nullif(trim(canal_entrada), '')                        AS join_channel,
        try_cast(trim(ind_actividad_cliente) AS TINYINT)       AS is_active,

        -- product ownership flags (1 = owns the product this month)
        CAST(trim(ind_ahor_fin_ult1) AS TINYINT)               AS p_savings,
        CAST(trim(ind_aval_fin_ult1) AS TINYINT)               AS p_guarantees,
        CAST(trim(ind_cco_fin_ult1)  AS TINYINT)               AS p_current_account,
        CAST(trim(ind_cder_fin_ult1) AS TINYINT)               AS p_derivatives,
        CAST(trim(ind_cno_fin_ult1)  AS TINYINT)               AS p_payroll_account,
        CAST(trim(ind_ctju_fin_ult1) AS TINYINT)               AS p_junior_account,
        CAST(trim(ind_ctma_fin_ult1) AS TINYINT)               AS p_mas_particular_account,
        CAST(trim(ind_ctop_fin_ult1) AS TINYINT)               AS p_particular_account,
        CAST(trim(ind_ctpp_fin_ult1) AS TINYINT)               AS p_particular_plus_account,
        CAST(trim(ind_deco_fin_ult1) AS TINYINT)               AS p_short_term_deposit,
        CAST(trim(ind_deme_fin_ult1) AS TINYINT)               AS p_medium_term_deposit,
        CAST(trim(ind_dela_fin_ult1) AS TINYINT)               AS p_long_term_deposit,
        CAST(trim(ind_ecue_fin_ult1) AS TINYINT)               AS p_e_account,
        CAST(trim(ind_fond_fin_ult1) AS TINYINT)               AS p_funds,
        CAST(trim(ind_hip_fin_ult1)  AS TINYINT)               AS p_mortgage,
        CAST(trim(ind_plan_fin_ult1) AS TINYINT)               AS p_pension_plan,
        CAST(trim(ind_pres_fin_ult1) AS TINYINT)               AS p_loans,
        CAST(trim(ind_reca_fin_ult1) AS TINYINT)               AS p_taxes,
        CAST(trim(ind_tjcr_fin_ult1) AS TINYINT)               AS p_credit_card,
        CAST(trim(ind_valo_fin_ult1) AS TINYINT)               AS p_securities,
        CAST(trim(ind_viv_fin_ult1)  AS TINYINT)               AS p_home_account,
        -- the two payroll flags are empty on 16,063 rows: unknown, not "does not own"
        try_cast(trim(ind_nomina_ult1)   AS TINYINT)           AS p_payroll,
        try_cast(trim(ind_nom_pens_ult1) AS TINYINT)           AS p_pensions,
        CAST(trim(ind_recibo_ult1)   AS TINYINT)               AS p_direct_debit
    FROM read_parquet('{raw}')
    ORDER BY customer_id, month
) TO '{out}' (FORMAT parquet, COMPRESSION zstd);
