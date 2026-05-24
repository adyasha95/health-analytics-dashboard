"""
queries.py
==========
SQL query layer for the Health Analytics Dashboard.

Each function executes a query against the local SQLite database and returns a
pandas DataFrame.  Queries are written with readability and non-trivial SQL in
mind: CTEs, window functions (ROW_NUMBER), multi-table JOINs, and scalar
subqueries are used throughout.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

import pandas as pd

DB_PATH = Path(__file__).parent / "data" / "health_analytics.db"


# ── Connection helper ──────────────────────────────────────────────────────────

_IN_MEMORY_CONN: sqlite3.Connection | None = None


def _conn() -> sqlite3.Connection:
    """
    Return a SQLite connection.  Opens the database file directly.
    On filesystems that do not support SQLite locking (e.g. certain network
    mounts), the database is loaded into an in-memory connection once and
    reused for the lifetime of the process.
    """
    global _IN_MEMORY_CONN

    # Happy path — most environments (local, Streamlit Cloud, etc.)
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("SELECT 1 FROM sqlite_master LIMIT 1")
        return conn
    except sqlite3.OperationalError:
        pass

    # Fallback: copy database bytes into an in-memory connection once
    if _IN_MEMORY_CONN is None:
        mem = sqlite3.connect(":memory:")
        disk = sqlite3.connect(f"file:{DB_PATH}?mode=ro&nolock=1", uri=True)
        disk.backup(mem)
        disk.close()
        _IN_MEMORY_CONN = mem

    return _IN_MEMORY_CONN


# ── Metadata ───────────────────────────────────────────────────────────────────

def get_measures() -> pd.DataFrame:
    """Return all measures with category and display labels, sorted by category."""
    sql = """
    SELECT
        measure_id,
        short_name,
        measure_name,
        category,
        unit
    FROM measures
    ORDER BY category, short_name
    """
    with _conn() as conn:
        return pd.read_sql_query(sql, conn)


def get_states() -> pd.DataFrame:
    """Return all state abbreviations and full names present in the data."""
    sql = """
    SELECT DISTINCT state_abbr, state_name
    FROM locations
    ORDER BY state_name
    """
    with _conn() as conn:
        return pd.read_sql_query(sql, conn)


def get_available_years() -> list[int]:
    """Return the sorted list of data years available in the database."""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT year FROM health_data ORDER BY year"
        ).fetchall()
    return [r[0] for r in rows if r[0] is not None]


# ── KPI summary ────────────────────────────────────────────────────────────────

def get_national_kpis(measure_ids: list[str]) -> pd.DataFrame:
    """
    National average (and range) for each requested measure in the most
    recent data year.

    SQL highlights:
    - CTE (measure_stats) computes per-measure aggregates
    - Scalar subquery isolates the latest year
    - JOIN between health_data and measures
    """
    placeholders = ",".join("?" * len(measure_ids))
    sql = f"""
    WITH measure_stats AS (
        SELECT
            h.measure_id,
            m.short_name,
            m.category,
            ROUND(AVG(h.data_value), 1)           AS national_avg,
            ROUND(MIN(h.data_value), 1)            AS min_val,
            ROUND(MAX(h.data_value), 1)            AS max_val,
            COUNT(DISTINCT h.county_fips)          AS counties_reporting
        FROM health_data h
        JOIN measures m ON h.measure_id = m.measure_id
        WHERE h.measure_id IN ({placeholders})
          AND h.year = (SELECT MAX(year) FROM health_data)
        GROUP BY h.measure_id, m.short_name, m.category
    )
    SELECT *
    FROM measure_stats
    ORDER BY national_avg DESC
    """
    with _conn() as conn:
        return pd.read_sql_query(sql, conn, params=measure_ids)


# ── State-level summary ────────────────────────────────────────────────────────

def get_state_summary(
    measure_id: str,
    year: Optional[int] = None,
) -> pd.DataFrame:
    """
    Per-state average prevalence for one measure, plus each state's deviation
    from the national mean.

    SQL highlights:
    - Two CTEs: state_avgs (GROUP BY state) and national (scalar aggregate)
    - Implicit cross-join to compute diff_from_national
    - JOIN between health_data and locations
    - Conditional year filter via scalar subquery fallback
    """
    year_clause = (
        "AND h.year = ?" if year
        else "AND h.year = (SELECT MAX(year) FROM health_data)"
    )
    params: list = [measure_id]
    if year:
        params.append(year)

    sql = f"""
    WITH state_avgs AS (
        SELECT
            l.state_abbr,
            l.state_name,
            ROUND(AVG(h.data_value), 1)           AS avg_prevalence,
            ROUND(MIN(h.data_value), 1)            AS min_county,
            ROUND(MAX(h.data_value), 1)            AS max_county,
            ROUND(MAX(h.data_value) - MIN(h.data_value), 1) AS range_pp,
            COUNT(DISTINCT l.county_fips)          AS counties_n
        FROM health_data h
        JOIN locations l ON h.county_fips = l.county_fips
        WHERE h.measure_id = ?
          {year_clause}
        GROUP BY l.state_abbr, l.state_name
    ),
    national AS (
        SELECT ROUND(AVG(avg_prevalence), 1) AS nat_avg
        FROM state_avgs
    )
    SELECT
        sa.state_abbr,
        sa.state_name,
        sa.avg_prevalence,
        sa.min_county,
        sa.max_county,
        sa.range_pp,
        sa.counties_n,
        na.nat_avg,
        ROUND(sa.avg_prevalence - na.nat_avg, 1) AS diff_from_national
    FROM state_avgs sa
    CROSS JOIN national na
    ORDER BY sa.avg_prevalence DESC
    """
    with _conn() as conn:
        return pd.read_sql_query(sql, conn, params=params)


# ── Trend over time ────────────────────────────────────────────────────────────

def get_prevalence_trend(measure_ids: list[str]) -> pd.DataFrame:
    """
    Year-over-year national average for a set of measures.

    SQL highlights:
    - GROUP BY on two dimensions (year, measure)
    - JOIN between health_data and measures for display labels
    - Used for the multi-line trend chart in the dashboard
    """
    placeholders = ",".join("?" * len(measure_ids))
    sql = f"""
    SELECT
        h.year,
        m.short_name                          AS measure,
        m.measure_id,
        ROUND(AVG(h.data_value), 2)           AS national_avg,
        COUNT(DISTINCT h.county_fips)         AS counties_n
    FROM health_data h
    JOIN measures m ON h.measure_id = m.measure_id
    WHERE h.measure_id IN ({placeholders})
    GROUP BY h.year, m.short_name, m.measure_id
    ORDER BY h.year, m.short_name
    """
    with _conn() as conn:
        return pd.read_sql_query(sql, conn, params=measure_ids)


# ── County extremes ────────────────────────────────────────────────────────────

def get_county_extremes(
    measure_id: str,
    state_abbr: Optional[str] = None,
    n: int = 10,
) -> pd.DataFrame:
    """
    Top-N and bottom-N counties by prevalence for a given measure.

    SQL highlights:
    - Two CTEs with ROW_NUMBER() window functions (ranked high and low)
    - UNION ALL to combine both cohorts in a single result set
    - Optional state filter applied consistently in both CTEs
    - Three-table JOIN: health_data → locations → (implicit measure filter)
    """
    state_clause = "AND l.state_abbr = ?" if state_abbr else ""
    base_params = [measure_id] + ([state_abbr] if state_abbr else [])
    params = base_params + base_params + [n, n]

    sql = f"""
    WITH ranked_high AS (
        SELECT
            l.county_name,
            l.state_abbr,
            h.data_value,
            l.total_population,
            ROW_NUMBER() OVER (ORDER BY h.data_value DESC) AS rn,
            'High' AS cohort
        FROM health_data h
        JOIN locations l ON h.county_fips = l.county_fips
        WHERE h.measure_id = ?
          AND h.year = (SELECT MAX(year) FROM health_data)
          {state_clause}
    ),
    ranked_low AS (
        SELECT
            l.county_name,
            l.state_abbr,
            h.data_value,
            l.total_population,
            ROW_NUMBER() OVER (ORDER BY h.data_value ASC) AS rn,
            'Low'  AS cohort
        FROM health_data h
        JOIN locations l ON h.county_fips = l.county_fips
        WHERE h.measure_id = ?
          AND h.year = (SELECT MAX(year) FROM health_data)
          {state_clause}
    )
    SELECT county_name, state_abbr, data_value, total_population, cohort
    FROM ranked_high WHERE rn <= ?
    UNION ALL
    SELECT county_name, state_abbr, data_value, total_population, cohort
    FROM ranked_low  WHERE rn <= ?
    ORDER BY cohort DESC, data_value DESC
    """
    with _conn() as conn:
        return pd.read_sql_query(sql, conn, params=params)


# ── Category breakdown ─────────────────────────────────────────────────────────

def get_category_breakdown(state_abbr: Optional[str] = None) -> pd.DataFrame:
    """
    Average prevalence for every measure, grouped by health category.
    Optional state filter narrows the county pool.

    SQL highlights:
    - Three-way JOIN: health_data × measures × locations
    - GROUP BY on two dimensions (category + measure)
    - Scalar subquery for latest-year filter
    """
    state_clause = "AND l.state_abbr = ?" if state_abbr else ""
    params = [state_abbr] if state_abbr else []

    sql = f"""
    SELECT
        m.category,
        m.short_name,
        m.measure_id,
        ROUND(AVG(h.data_value), 1)   AS avg_prevalence,
        COUNT(DISTINCT h.county_fips) AS counties_n
    FROM health_data h
    JOIN measures  m ON h.measure_id  = m.measure_id
    JOIN locations l ON h.county_fips = l.county_fips
    WHERE h.year = (SELECT MAX(year) FROM health_data)
      {state_clause}
    GROUP BY m.category, m.short_name, m.measure_id
    ORDER BY m.category, avg_prevalence DESC
    """
    with _conn() as conn:
        return pd.read_sql_query(sql, conn, params=params)


# ── State-level condition correlation ─────────────────────────────────────────

def get_state_condition_matrix(
    measure_ids: list[str],
) -> pd.DataFrame:
    """
    Pivot of state × measure showing avg prevalence — useful for correlation
    analysis or a heatmap view.

    SQL highlights:
    - CTE to pre-aggregate at state × measure level
    - Self-join style aggregation with conditional expressions
    - Returns wide-format data ready for Plotly heatmap
    """
    placeholders = ",".join("?" * len(measure_ids))
    sql = f"""
    WITH base AS (
        SELECT
            l.state_abbr,
            h.measure_id,
            m.short_name,
            ROUND(AVG(h.data_value), 1) AS avg_prevalence
        FROM health_data h
        JOIN measures  m ON h.measure_id  = m.measure_id
        JOIN locations l ON h.county_fips = l.county_fips
        WHERE h.measure_id IN ({placeholders})
          AND h.year = (SELECT MAX(year) FROM health_data)
        GROUP BY l.state_abbr, h.measure_id, m.short_name
    )
    SELECT state_abbr, short_name, avg_prevalence
    FROM base
    ORDER BY state_abbr, short_name
    """
    with _conn() as conn:
        long_df = pd.read_sql_query(sql, conn, params=measure_ids)

    # Pivot to wide format for heatmap
    wide_df = long_df.pivot(
        index="state_abbr", columns="short_name", values="avg_prevalence"
    )
    return wide_df
