# Santander Marketing ML

Who should a retail bank's marketing team offer a credit card to next month, and which customers is it about to lose?

This project builds cross-sell and churn models on 17 months of real (anonymised) retail banking data, measures them the way a bank would (Gini, lift, campaign ROI), and puts an LLM assistant on top that answers marketers' questions using the model scores and a product knowledge graph.

> **Status:** work in progress. Ingestion, cleaning and target definitions are done and tested; modelling has not started.

## Data

[Santander Product Recommendation](https://www.kaggle.com/competitions/santander-product-recommendation) (Kaggle): one row per customer per month from 2015-01 to 2016-05, ~13.6M rows, with demographics, tenure, channel and ownership flags for 24 products.

The data is not in this repo; the competition rules do not allow redistribution. To run the pipeline, accept the rules on Kaggle, download `train_ver2.csv.zip` and put it in `data/raw/`.

## Data findings

Profiling the full 13.6M rows changed the plan in three places:

| Finding | Evidence | Decision |
|---|---|---|
| The first half of 2015 is a different data regime | `ind_actividad_cliente` never changes between 2015-01 and 2015-06 (0 transitions, vs ~57k 1→0 transitions from July on). In 2015-07 the panel grows from 632k to 830k customers; 93% of the ~200k added customers own no product, 4% are active, median tenure 50 months, so they are dormant existing customers, not new ones | Snapshots start at 2015-07 |
| Zero-product customers almost never buy | Credit card take-up: 0.06% a month without any product vs 0.65% with at least one (2015-07..2016-04) | Population: customers with ≥1 product. Reactivating dormant customers is a different campaign |
| 27,734 rows have every demographic field empty | All in 2015-01..06, 7,340 customers, but product flags are filled | Rows kept; demographics left NULL |

Smaller cleaning rules (padded numbers, `-999999` tenure, `"1"` vs `"1.0"` codes, empty payroll flags) are documented and tested in [`sql/01_clean.sql`](sql/01_clean.sql).

## Targets

Defined in [`sql/02_targets.sql`](sql/02_targets.sql), one row per customer per snapshot month *t*:

- **Cross-sell (credit card):** no credit card at *t*, has one at *t+1*. Only for customers observed at *t+1*.
- **Churn:** zero products, or absent from the data, at both *t+1* and *t+2*. Requiring two months keeps a one-month dip or a single missing snapshot (8,018 customers have gaps in their history) from counting as churn.

| Split | Snapshot months | Cross-sell base | Take-up | Churn base | Churn rate |
|---|---|---|---|---|---|
| train | 2015-07 .. 2015-11 | 3,079,175 | 0.69% | 3,262,176 | 0.38% |
| valid | 2016-01 | 650,940 | 0.58% | 686,379 | 0.36% |
| test | 2016-03 | 657,378 | 0.60% | 691,793 | 0.32% |

Both targets are rare (fewer than 1 in 150), so models are judged on Gini and on lift in the top deciles, which is how a campaign list is actually used.

## Design decisions

- **Time-based validation with a gap, never a random split.** The model scores future months, so it is trained on past months and tested on later ones. The churn label looks two months ahead, so a month is left out between train and validation (2015-12) and between validation and test (2016-02): no training label is observed after a validation or test snapshot.
- **Out-of-core data work.** The raw CSV is streamed from the zip into Parquet, and features are built in DuckDB SQL, so the full 13.6M rows never need to fit in memory (developed on an 8 GB laptop).
- **Raw columns stay as text until SQL.** The source mixes padded numbers, `NA` strings and blanks in the same column; casting happens in one explicit, tested step.
- **Gender is excluded from features.** Personal attributes like `sexo` are kept out of the models, in line with fair-lending practice.

## Roadmap

1. Ingestion: zip → Parquet *(done)*
2. Cleaning, profiling and target definitions *(done)*
3. Customer-month features in SQL: product history, 3-month changes, tenure, channel.
4. Logistic regression baseline and LightGBM; Gini, F1, lift by decile.
5. Campaign ROI simulation and A/B test design with power analysis.
6. Simple customer lifetime value.
7. LLM assistant for marketers: product ontology, knowledge graph retrieval, model scores as tools, evaluation set.
8. Model card and tests.

## Setup

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run python -m santander.ingest        # zip -> data/processed/train_raw.parquet   (~40 s)
uv run python -m santander.sql 01_clean  # typed customer-month table             (~10 s)
uv run python -m santander.sql 02_targets # population, labels and split           (~5 s)
uv run pytest
```

## Layout

```
src/santander/   pipeline code (config, ingestion, features, models)
sql/             feature and target definitions in DuckDB SQL
notebooks/       EDA and reporting only; no pipeline logic
tests/           unit tests on synthetic data
data/            local only, git-ignored
```
