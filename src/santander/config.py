"""Paths and time-split settings shared by the pipeline."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_RAW = ROOT / "data" / "raw"
DATA_PROCESSED = ROOT / "data" / "processed"

RAW_ZIP = DATA_RAW / "train_ver2.csv.zip"
RAW_PARQUET = DATA_PROCESSED / "train_raw.parquet"
CUSTOMER_MONTH = DATA_PROCESSED / "customer_month.parquet"
TARGETS = DATA_PROCESSED / "targets.parquet"

# Snapshot months run 2015-01-28 .. 2016-05-28 (one row per customer per month).
# The split itself lives in sql/02_targets.sql; these mirror it for Python code.
# Split by time, never at random, with a one-month gap so no training label is observed
# after a validation or test snapshot (the churn label looks two months ahead).
TRAIN_MONTHS = ("2015-07-28", "2015-08-28", "2015-09-28", "2015-10-28", "2015-11-28")
VALID_MONTHS = ("2016-01-28",)  # tuning and threshold choice
TEST_MONTHS = ("2016-03-28",)  # touched once, for the final report

# Personal attributes kept out of model features (fair-lending practice).
EXCLUDED_FEATURES = ("sexo",)
