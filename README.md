# Population Health Analytics Dashboard

An interactive analytics dashboard exploring chronic disease burden and preventive care
utilisation across U.S. counties, built on CDC PLACES data.  The dashboard is designed
to surface the kind of population-health signals that drive prioritisation decisions in
digital-health and telemedicine settings: which conditions are most prevalent, where
geographic disparities are largest, and how outcomes differ across state and county lines.

**Live demo:** *(deploy to Streamlit Cloud and paste URL here)*

---

## What it does

The dashboard presents county-level age-adjusted prevalence estimates for eleven health
measures drawn from the CDC PLACES 2023 release.  It provides four views:

**KPI summary row** — national average prevalence for the four highest-burden conditions
(diabetes, hypertension, obesity, depression).  When a state is selected, each card
shows the state's deviation from the national mean.

**State comparison chart** — horizontal bar chart ranking all 50 states plus DC by
prevalence for any selected measure.  Bars are coloured to show above- or below-average
performance; a dotted reference line marks the national mean.

**All-measures breakdown** — grouped bar chart showing average prevalence across every
measure in the dataset, segmented by health category (Health Outcomes, Prevention,
Health Risk Behaviors, Disabilities).  Filters to the selected geography.

**County extremes** — side-by-side panels showing the 12 counties with the highest and
lowest prevalence for the active measure, nationally or within a selected state.

A **trend panel** renders year-over-year prevalence lines for up to five conditions
simultaneously when multi-year data is available in the database.

---

## Dataset

**Source:** [CDC PLACES: Local Data for Better Health](https://www.cdc.gov/places/index.html), County Data 2023 release.

PLACES publishes model-based small-area estimates of health outcomes and behaviours for
every U.S. county, derived from the Behavioral Risk Factor Surveillance System (BRFSS)
and combined with Census data.  All values are age-adjusted prevalence rates (%) among
adults aged 18 and older.

Measures loaded into this project:

| Measure ID  | Description                                  | Category               |
|-------------|----------------------------------------------|------------------------|
| DIABETES    | Diagnosed diabetes                           | Health Outcomes        |
| BPHIGH      | High blood pressure                          | Health Outcomes        |
| OBESITY     | Obesity                                      | Health Risk Behaviors  |
| DEPRESSION  | Depression                                   | Health Outcomes        |
| HIGHCHOL    | High cholesterol                             | Health Outcomes        |
| CHD         | Coronary heart disease                       | Health Outcomes        |
| CASTHMA     | Current asthma                               | Health Outcomes        |
| CHECKUP     | Annual checkup in past year                  | Prevention             |
| CSMOKING    | Current smoking                              | Health Risk Behaviors  |
| SLEEP       | Sleeping less than 7 hours                   | Health Risk Behaviors  |
| MHLTH       | Poor mental health ≥ 14 days/month           | Health Outcomes        |

---

## Project structure

```
health_analytics_dashboard/
├── data/
│   ├── __init__.py
│   ├── load_data.py        # Downloads CDC PLACES via Socrata API → SQLite
│   └── health_analytics.db # Pre-built database (committed for one-step deploy)
├── app.py                  # Streamlit dashboard
├── queries.py              # SQL query functions (sqlite3)
├── requirements.txt
├── .streamlit/
│   └── config.toml         # Dark theme + server settings
└── README.md
```

The database layer (`queries.py`) uses non-trivial SQL throughout: CTEs to isolate
intermediate aggregations, `ROW_NUMBER()` window functions to rank counties, multi-table
`JOIN`s across `health_data`, `locations`, and `measures`, and scalar subqueries for
dynamic year filtering.

---

## Running locally

**Prerequisites:** Python 3.10+

```bash
# 1. Clone and install dependencies
git clone <your-repo-url>
cd health_analytics_dashboard
pip install -r requirements.txt

# 2. Build the database (skip if health_analytics.db is already present)
python data/load_data.py

# 3. Launch the dashboard
streamlit run app.py
```

The database build step downloads ~35,000 rows from the CDC PLACES Socrata API and
takes around 30–60 seconds depending on connection speed.  The resulting
`health_analytics.db` file is approximately 4–6 MB.

---

## Deploying to Streamlit Cloud

1. Push the repository to GitHub (including `data/health_analytics.db`).
2. Go to [share.streamlit.io](https://share.streamlit.io) → **New app**.
3. Select the repo, set the main file path to `app.py`, and click **Deploy**.

No secrets or environment variables are required.  The app reads from the SQLite file
committed in the repository, so deployment is a single step with no build phase.

---

## SQL design notes

Query functions in `queries.py` are written to demonstrate analytical SQL patterns
beyond simple selects:

```sql
-- Example: state summary with deviation from national mean (get_state_summary)
WITH state_avgs AS (
    SELECT
        l.state_abbr,
        l.state_name,
        ROUND(AVG(h.data_value), 1) AS avg_prevalence,
        ...
    FROM health_data h
    JOIN locations l ON h.county_fips = l.county_fips
    WHERE h.measure_id = ?
      AND h.year = (SELECT MAX(year) FROM health_data)
    GROUP BY l.state_abbr, l.state_name
),
national AS (
    SELECT ROUND(AVG(avg_prevalence), 1) AS nat_avg
    FROM state_avgs
)
SELECT sa.*, ROUND(sa.avg_prevalence - na.nat_avg, 1) AS diff_from_national
FROM state_avgs sa
CROSS JOIN national na
ORDER BY avg_prevalence DESC
```

```sql
-- Example: top/bottom counties using window functions (get_county_extremes)
WITH ranked_high AS (
    SELECT ..., ROW_NUMBER() OVER (ORDER BY h.data_value DESC) AS rn, 'High' AS cohort
    FROM health_data h JOIN locations l ON h.county_fips = l.county_fips
    WHERE h.measure_id = ?
),
ranked_low AS (
    SELECT ..., ROW_NUMBER() OVER (ORDER BY h.data_value ASC) AS rn, 'Low' AS cohort
    ...
)
SELECT ... FROM ranked_high WHERE rn <= 12
UNION ALL
SELECT ... FROM ranked_low WHERE rn <= 12
```

---

## Tech stack

- **Python 3.10+**
- **Streamlit** — dashboard framework
- **Plotly** — interactive charts (`go.Bar`, `go.Scatter`, `go.Figure`)
- **SQLite / sqlite3** — embedded analytical database
- **pandas** — data wrangling
- **CDC PLACES API** (Socrata) — data source

---

*Data is published by the CDC and is in the public domain.*
