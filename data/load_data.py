"""
data/load_data.py
=================
Downloads the CDC PLACES Local Data for Better Health (County Level, 2023 release)
via the Socrata open-data API, then builds a normalized SQLite database.

Usage:
    python data/load_data.py

The script is idempotent — re-running it rebuilds the database from scratch.
The resulting `health_analytics.db` file is committed to the repo so that the
Streamlit Cloud deployment works without a separate build step.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pandas as pd
import requests

# ── Paths ─────────────────────────────────────────────────────────────────────
HERE = Path(__file__).parent
DB_PATH = HERE / "health_analytics.db"

# ── CDC PLACES Socrata endpoint ────────────────────────────────────────────────
# Dataset: PLACES Local Data for Better Health — County Data 2023
# https://data.cdc.gov/500-Cities-Places/PLACES-Local-Data-for-Better-Health-County-Data-20/swc5-untb
SOCRATA_URL = "https://data.cdc.gov/resource/swc5-untb.json"

# ── Measures of interest ───────────────────────────────────────────────────────
# Selected for their relevance to a telemedicine / digital-health context:
# chronic disease burden, mental health, preventive care utilisation.
KEY_MEASURES = [
    "DIABETES",   # Diagnosed diabetes
    "BPHIGH",     # High blood pressure
    "OBESITY",    # Obesity
    "DEPRESSION", # Depression
    "HIGHCHOL",   # High cholesterol
    "CHD",        # Coronary heart disease
    "CASTHMA",    # Current asthma
    "CHECKUP",    # Annual checkup in past year (prevention)
    "CSMOKING",   # Current smoking
    "SLEEP",      # Sleeping less than 7 hours
    "MHLTH",      # Poor mental health >= 14 days/month
]

SELECT_COLS = (
    "Year,StateAbbr,StateDesc,LocationName,LocationID,"
    "Category,Measure,ShortQuestionText,"
    "DataValue,Low_Confidence_Limit,High_Confidence_Limit,"
    "TotalPopulation,MeasureId,DataValueUnit"
)

BATCH_SIZE = 10_000


# ── Download ───────────────────────────────────────────────────────────────────

def fetch_places_data(measures: list[str]) -> pd.DataFrame:
    """Pull county-level age-adjusted prevalence for the given measure IDs."""
    measure_sql = ",".join(f"'{m}'" for m in measures)
    where_clause = f"DataValueTypeID='AgeAdjPrv' AND MeasureId in({measure_sql})"

    all_records: list[dict] = []
    offset = 0

    print(f"Fetching CDC PLACES data for {len(measures)} measures …")
    while True:
        params = {
            "$where":  where_clause,
            "$select": SELECT_COLS,
            "$limit":  BATCH_SIZE,
            "$offset": offset,
            "$order":  "Year,StateAbbr,MeasureId",
        }
        resp = requests.get(SOCRATA_URL, params=params, timeout=120)
        resp.raise_for_status()

        batch: list[dict] = resp.json()
        if not batch:
            break

        all_records.extend(batch)
        print(f"  … {len(all_records):,} rows fetched")

        if len(batch) < BATCH_SIZE:
            break
        offset += BATCH_SIZE

    if not all_records:
        sys.exit("No records returned from CDC PLACES API. Check your connection and try again.")

    df = pd.DataFrame(all_records)
    print(f"Download complete: {len(df):,} rows across {df['StateAbbr'].nunique()} states.")
    return df


# ── Transform ──────────────────────────────────────────────────────────────────

def clean(df: pd.DataFrame) -> pd.DataFrame:
    numeric_cols = ["DataValue", "Low_Confidence_Limit", "High_Confidence_Limit", "TotalPopulation"]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df["Year"] = pd.to_numeric(df.get("Year"), errors="coerce").astype("Int64")
    df = df.dropna(subset=["DataValue", "LocationID"])
    return df


# ── Load ───────────────────────────────────────────────────────────────────────

def build_database(df: pd.DataFrame) -> None:
    """Create a normalized three-table SQLite database from the cleaned DataFrame."""
    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()

    # Drop existing tables so the script is idempotent
    for tbl in ("health_data", "locations", "measures"):
        cur.execute(f"DROP TABLE IF EXISTS {tbl}")

    # ── locations ──────────────────────────────────────────────────────────────
    locs = (
        df[["StateAbbr", "StateDesc", "LocationName", "LocationID", "TotalPopulation"]]
        .drop_duplicates(subset="LocationID")
        .rename(columns={
            "StateAbbr":       "state_abbr",
            "StateDesc":       "state_name",
            "LocationName":    "county_name",
            "LocationID":      "county_fips",
            "TotalPopulation": "total_population",
        })
    )
    locs.to_sql("locations", conn, if_exists="replace", index=False)

    # ── measures ───────────────────────────────────────────────────────────────
    meas = (
        df[["MeasureId", "Measure", "Category", "ShortQuestionText", "DataValueUnit"]]
        .drop_duplicates(subset="MeasureId")
        .rename(columns={
            "MeasureId":        "measure_id",
            "Measure":          "measure_name",
            "Category":         "category",
            "ShortQuestionText":"short_name",
            "DataValueUnit":    "unit",
        })
    )
    meas.to_sql("measures", conn, if_exists="replace", index=False)

    # ── health_data ────────────────────────────────────────────────────────────
    hd = (
        df[[
            "Year", "LocationID", "MeasureId",
            "DataValue", "Low_Confidence_Limit", "High_Confidence_Limit",
        ]]
        .rename(columns={
            "Year":                  "year",
            "LocationID":            "county_fips",
            "MeasureId":             "measure_id",
            "DataValue":             "data_value",
            "Low_Confidence_Limit":  "ci_low",
            "High_Confidence_Limit": "ci_high",
        })
    )
    hd.to_sql("health_data", conn, if_exists="replace", index=False)

    # Indexes for dashboard query performance
    cur.execute("CREATE INDEX idx_hd_measure ON health_data(measure_id)")
    cur.execute("CREATE INDEX idx_hd_fips    ON health_data(county_fips)")
    cur.execute("CREATE INDEX idx_hd_year    ON health_data(year)")
    cur.execute("CREATE INDEX idx_loc_state  ON locations(state_abbr)")

    conn.commit()
    conn.close()

    # Quick stats
    conn2 = sqlite3.connect(DB_PATH)
    rows = conn2.execute("SELECT COUNT(*) FROM health_data").fetchone()[0]
    counties = conn2.execute("SELECT COUNT(*) FROM locations").fetchone()[0]
    conn2.close()

    print(f"\nDatabase written to: {DB_PATH}")
    print(f"  health_data : {rows:,} rows")
    print(f"  locations   : {counties:,} counties")
    print(f"  measures    : {len(meas)} measures")


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    raw_df   = fetch_places_data(KEY_MEASURES)
    clean_df = clean(raw_df)
    build_database(clean_df)
