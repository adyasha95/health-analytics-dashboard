"""
app.py
======
Population Health Analytics Dashboard
Built on CDC PLACES Local Data for Better Health (County Level, 2023)

Run locally:
    streamlit run app.py
"""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import queries

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Population Health Analytics",
    page_icon="🏥",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Design tokens ──────────────────────────────────────────────────────────────
C = {
    "primary":   "#4f8ef7",
    "teal":      "#2dd4bf",
    "purple":    "#a78bfa",
    "danger":    "#f87171",
    "amber":     "#fbbf24",
    "green":     "#34d399",
    "bg":        "#0f1117",
    "card":      "#161b27",
    "border":    "#252d3d",
    "text":      "#e2e8f0",
    "muted":     "#7c8599",
}

CHART_LAYOUT = dict(
    paper_bgcolor=C["card"],
    plot_bgcolor=C["card"],
    font=dict(color=C["text"], family="Inter, system-ui, sans-serif", size=12),
    margin=dict(l=12, r=16, t=48, b=36),
)

AXIS_STYLE = dict(
    gridcolor=C["border"],
    linecolor=C["border"],
    zerolinecolor=C["border"],
    tickfont=dict(size=11),
)

# KPIs always shown in the summary row
KPI_MEASURES = ["DIABETES", "BPHIGH", "OBESITY", "DEPRESSION"]
KPI_META = {
    "DIABETES":   ("Diabetes",      "🩸", C["danger"]),
    "BPHIGH":     ("Hypertension",  "❤️", C["primary"]),
    "OBESITY":    ("Obesity",       "⚖️", C["amber"]),
    "DEPRESSION": ("Depression",    "🧠", C["purple"]),
}

# ── Global CSS ─────────────────────────────────────────────────────────────────
st.markdown(
    f"""
    <style>
      /* Page background */
      .stApp {{ background-color: {C["bg"]}; }}

      /* Sidebar */
      section[data-testid="stSidebar"] {{
        background-color: #0b0f1a;
        border-right: 1px solid {C["border"]};
      }}

      /* KPI cards */
      div[data-testid="metric-container"] {{
        background: {C["card"]};
        border: 1px solid {C["border"]};
        border-radius: 12px;
        padding: 18px 22px 14px;
      }}
      div[data-testid="metric-container"] label {{
        color: {C["muted"]} !important;
        font-size: 0.72rem !important;
        letter-spacing: 0.07em;
        text-transform: uppercase;
        font-weight: 600;
      }}
      div[data-testid="stMetricValue"] {{
        color: {C["text"]} !important;
        font-size: 2rem !important;
        font-weight: 700 !important;
        letter-spacing: -0.01em;
      }}
      div[data-testid="stMetricDelta"] svg {{ display: none; }}
      div[data-testid="stMetricDelta"] > div {{
        font-size: 0.78rem !important;
        font-weight: 500;
      }}

      /* Horizontal rule */
      hr {{ border-color: {C["border"]} !important; margin: 12px 0; }}

      /* Chart wrappers */
      .chart-wrap {{
        background: {C["card"]};
        border: 1px solid {C["border"]};
        border-radius: 12px;
        padding: 4px 4px 0;
        margin-bottom: 8px;
      }}

      /* Section labels */
      .section-label {{
        color: {C["muted"]};
        font-size: 0.72rem;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        font-weight: 600;
        margin-bottom: 6px;
      }}
    </style>
    """,
    unsafe_allow_html=True,
)


# ── Cached data loaders ────────────────────────────────────────────────────────

@st.cache_data(ttl=3600, show_spinner=False)
def _measures() -> pd.DataFrame:
    return queries.get_measures()

@st.cache_data(ttl=3600, show_spinner=False)
def _states() -> pd.DataFrame:
    return queries.get_states()

@st.cache_data(ttl=3600, show_spinner=False)
def _years() -> list[int]:
    return queries.get_available_years()

@st.cache_data(ttl=3600, show_spinner=False)
def _kpis(measure_ids: tuple) -> pd.DataFrame:
    return queries.get_national_kpis(list(measure_ids))

@st.cache_data(ttl=3600, show_spinner=False)
def _state_summary(measure_id: str) -> pd.DataFrame:
    return queries.get_state_summary(measure_id)

@st.cache_data(ttl=3600, show_spinner=False)
def _trend(measure_ids: tuple) -> pd.DataFrame:
    return queries.get_prevalence_trend(list(measure_ids))

@st.cache_data(ttl=3600, show_spinner=False)
def _county_extremes(measure_id: str, state: str | None) -> pd.DataFrame:
    return queries.get_county_extremes(measure_id, state, n=12)

@st.cache_data(ttl=3600, show_spinner=False)
def _category_breakdown(state: str | None) -> pd.DataFrame:
    return queries.get_category_breakdown(state)

@st.cache_data(ttl=3600, show_spinner=False)
def _matrix(measure_ids: tuple) -> pd.DataFrame:
    return queries.get_state_condition_matrix(list(measure_ids))


# ── Sidebar ────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown(
        f"<div style='font-size:1.05rem;font-weight:700;color:{C['text']};margin-bottom:2px'>"
        "🏥 Population Health</div>"
        f"<div style='font-size:0.75rem;color:{C['muted']};margin-bottom:16px'>"
        "CDC PLACES · County Level · 2023</div>",
        unsafe_allow_html=True,
    )
    st.markdown("---")

    measures_df = _measures()
    states_df   = _states()

    # State filter
    state_options  = ["All States"] + list(states_df["state_name"])
    sel_state_name = st.selectbox("📍 Geography", state_options, index=0)
    sel_state: str | None = None
    if sel_state_name != "All States":
        sel_state = states_df.loc[
            states_df["state_name"] == sel_state_name, "state_abbr"
        ].values[0]

    st.markdown("---")

    # Category → measure cascade
    categories = ["All categories"] + sorted(measures_df["category"].unique().tolist())
    sel_cat = st.selectbox("📊 Health Category", categories, index=0)

    if sel_cat != "All categories":
        avail = measures_df[measures_df["category"] == sel_cat]
    else:
        avail = measures_df

    measure_map: dict[str, str] = avail.set_index("measure_id")["short_name"].to_dict()
    default_idx = list(measure_map.keys()).index("DIABETES") if "DIABETES" in measure_map else 0

    sel_measure_id: str = st.selectbox(
        "📋 Primary Measure",
        options=list(measure_map.keys()),
        index=default_idx,
        format_func=lambda x: measure_map[x],
    )
    sel_measure_label = measure_map[sel_measure_id]

    st.markdown("---")

    # Trend comparison selector
    st.markdown(
        f"<div style='color:{C['muted']};font-size:0.72rem;text-transform:uppercase;"
        "letter-spacing:0.07em;font-weight:600;margin-bottom:6px'>Trend Comparison</div>",
        unsafe_allow_html=True,
    )
    all_measure_map: dict[str, str] = measures_df.set_index("measure_id")["short_name"].to_dict()
    trend_ids: list[str] = st.multiselect(
        "Select up to 5 measures",
        options=list(all_measure_map.keys()),
        default=["DIABETES", "BPHIGH", "OBESITY", "MHLTH"],
        format_func=lambda x: all_measure_map.get(x, x),
        max_selections=5,
    )

    st.markdown("---")
    _c_muted   = C["muted"]
    _c_primary = C["primary"]
    st.markdown(
        f"<div style='color:{_c_muted};font-size:0.73rem;line-height:1.5'>"
        "Metric: age-adjusted prevalence (%) among adults.<br>"
        f"Source: <a href='https://www.cdc.gov/places' style='color:{_c_primary}' target='_blank'>"
        "CDC PLACES 2023</a>.</div>",
        unsafe_allow_html=True,
    )


# ── Page header ────────────────────────────────────────────────────────────────

geo_badge = ""
if sel_state_name != "All States":
    _c_border = C["border"]
    _c_muted  = C["muted"]
    geo_badge = (
        f" <span style='background:{_c_border};color:{_c_muted};"
        f"padding:2px 10px;border-radius:6px;font-size:0.75rem;"
        f"vertical-align:middle;font-weight:500'>{sel_state_name}</span>"
    )

st.markdown(
    f"<h1 style='margin:0 0 2px;font-size:1.65rem;font-weight:800;"
    f"letter-spacing:-0.02em;color:{C['text']}'>"
    f"Population Health Dashboard{geo_badge}</h1>"
    f"<p style='margin:0 0 16px;color:{C['muted']};font-size:0.85rem'>"
    "CDC PLACES 2023 &nbsp;·&nbsp; County-level health outcomes "
    "&nbsp;·&nbsp; Age-adjusted prevalence</p>",
    unsafe_allow_html=True,
)
st.markdown("---")


# ── KPI Row ────────────────────────────────────────────────────────────────────

kpi_df = _kpis(tuple(KPI_MEASURES))

# If a state is selected, pull state-level values for the delta
state_vals: dict[str, float] = {}
if sel_state:
    for mid in KPI_MEASURES:
        ss = _state_summary(mid)
        row = ss[ss["state_abbr"] == sel_state]
        if not row.empty:
            state_vals[mid] = float(row["avg_prevalence"].values[0])

kpi_cols = st.columns(4, gap="small")
for i, mid in enumerate(KPI_MEASURES):
    label, icon, color = KPI_META[mid]
    row = kpi_df[kpi_df["measure_id"] == mid]
    if row.empty:
        continue
    nat_avg = float(row["national_avg"].values[0])

    delta_val: str | None = None
    delta_color = "off"
    if sel_state and mid in state_vals:
        diff = round(state_vals[mid] - nat_avg, 1)
        delta_val  = f"{diff:+.1f}pp vs national avg"
        delta_color = "inverse"   # red = higher than national = worse health outcome

    with kpi_cols[i]:
        st.metric(
            label=f"{icon}  {label}",
            value=f"{nat_avg}%",
            delta=delta_val,
            delta_color=delta_color,
        )

st.markdown("<div style='margin-bottom:8px'></div>", unsafe_allow_html=True)
st.markdown("---")


# ── Row 1: State comparison (left) + All-measures breakdown (right) ────────────

col_states, col_measures = st.columns([3, 2], gap="medium")

with col_states:
    state_df = _state_summary(sel_measure_id)

    if not state_df.empty:
        nat_avg_line = float(state_df["nat_avg"].values[0])

        # Colour each bar by deviation direction; highlight selected state
        def _bar_color(row: pd.Series) -> str:
            if sel_state and row["state_abbr"] == sel_state:
                return C["amber"]
            return C["danger"] if row["diff_from_national"] > 0 else C["teal"]

        state_df = state_df.sort_values("avg_prevalence", ascending=True)
        bar_colors = [_bar_color(r) for _, r in state_df.iterrows()]

        fig_states = go.Figure()
        fig_states.add_trace(
            go.Bar(
                x=state_df["avg_prevalence"],
                y=state_df["state_abbr"],
                orientation="h",
                marker_color=bar_colors,
                marker_line_width=0,
                customdata=state_df[
                    ["state_name", "counties_n", "nat_avg", "diff_from_national",
                     "min_county", "max_county"]
                ].values,
                hovertemplate=(
                    "<b>%{customdata[0]}</b><br>"
                    "Prevalence: <b>%{x:.1f}%</b><br>"
                    "vs national avg: %{customdata[3]:+.1f}pp<br>"
                    "County range: %{customdata[4]:.1f}% – %{customdata[5]:.1f}%<br>"
                    "Counties reporting: %{customdata[1]}"
                    "<extra></extra>"
                ),
            )
        )
        # National average reference line
        fig_states.add_vline(
            x=nat_avg_line,
            line_dash="dot",
            line_color=C["muted"],
            line_width=1.5,
            annotation_text=f"National avg {nat_avg_line}%",
            annotation_font_size=10,
            annotation_font_color=C["muted"],
            annotation_position="top right",
        )

        fig_states.update_layout(
            **CHART_LAYOUT,
            title=dict(
                text=f"<b>State Comparison</b>  ·  {sel_measure_label}",
                font=dict(size=13, color=C["text"]),
                x=0,
                xanchor="left",
            ),
            height=500,
            xaxis=dict(title="Prevalence (%)", **AXIS_STYLE),
            yaxis=dict(title=None, tickfont=dict(size=10), **AXIS_STYLE),
            showlegend=False,
            bargap=0.18,
        )
        st.markdown("<div class='chart-wrap'>", unsafe_allow_html=True)
        st.plotly_chart(fig_states, use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)

with col_measures:
    cat_df = _category_breakdown(sel_state)

    if not cat_df.empty:
        cat_df = cat_df.sort_values("avg_prevalence", ascending=True)

        COLOR_MAP = {
            cat: color for cat, color in zip(
                cat_df["category"].unique(),
                [C["primary"], C["teal"], C["purple"], C["amber"], C["green"]],
            )
        }

        fig_cat = go.Figure()
        for cat in cat_df["category"].unique():
            sub = cat_df[cat_df["category"] == cat]
            fig_cat.add_trace(
                go.Bar(
                    x=sub["avg_prevalence"],
                    y=sub["short_name"],
                    orientation="h",
                    name=cat,
                    marker_color=COLOR_MAP.get(cat, C["primary"]),
                    marker_line_width=0,
                    customdata=sub[["category", "counties_n"]].values,
                    hovertemplate=(
                        "<b>%{y}</b><br>"
                        "Prevalence: <b>%{x:.1f}%</b><br>"
                        "Category: %{customdata[0]}<br>"
                        "Counties: %{customdata[1]}"
                        "<extra></extra>"
                    ),
                )
            )

        geo_label = sel_state_name if sel_state else "National"
        fig_cat.update_layout(
            **CHART_LAYOUT,
            title=dict(
                text=f"<b>All Measures</b>  ·  {geo_label}",
                font=dict(size=13, color=C["text"]),
                x=0,
                xanchor="left",
            ),
            height=500,
            barmode="stack",
            xaxis=dict(title="Prevalence (%)", **AXIS_STYLE),
            yaxis=dict(title=None, tickfont=dict(size=10), **AXIS_STYLE),
            legend=dict(
                orientation="h",
                y=-0.22,
                x=0,
                font=dict(size=10),
                bgcolor="rgba(0,0,0,0)",
            ),
            bargap=0.18,
        )
        st.markdown("<div class='chart-wrap'>", unsafe_allow_html=True)
        st.plotly_chart(fig_cat, use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)


# ── Row 2: Prevalence trend ────────────────────────────────────────────────────

st.markdown("---")
st.markdown(
    f"<div class='section-label'>Prevalence Trend Over Time</div>",
    unsafe_allow_html=True,
)

if trend_ids:
    trend_df = _trend(tuple(trend_ids))

    if trend_df.empty or trend_df["year"].nunique() < 2:
        st.info(
            "This CDC PLACES release contains a single reference year. "
            "Multi-year trend data will appear here when multiple years are loaded.",
            icon="ℹ️",
        )
    else:
        trend_colors = [
            C["primary"], C["teal"], C["purple"], C["amber"], C["danger"]
        ]
        fig_trend = go.Figure()
        for idx, mid in enumerate(trend_df["measure_id"].unique()):
            sub  = trend_df[trend_df["measure_id"] == mid].sort_values("year")
            name = sub["measure"].values[0]
            fig_trend.add_trace(
                go.Scatter(
                    x=sub["year"],
                    y=sub["national_avg"],
                    mode="lines+markers",
                    name=name,
                    line=dict(color=trend_colors[idx % len(trend_colors)], width=2.5),
                    marker=dict(size=7),
                    hovertemplate=(
                        f"<b>{name}</b><br>"
                        "Year: %{x}<br>"
                        "Prevalence: <b>%{y:.1f}%</b>"
                        "<extra></extra>"
                    ),
                )
            )
        fig_trend.update_layout(
            **CHART_LAYOUT,
            title=dict(
                text="<b>National Average Prevalence</b>  ·  Year over Year",
                font=dict(size=13, color=C["text"]),
                x=0,
                xanchor="left",
            ),
            height=320,
            xaxis=dict(title="Year", tickmode="linear", dtick=1, **AXIS_STYLE),
            yaxis=dict(title="Prevalence (%)", **AXIS_STYLE),
            legend=dict(
                orientation="h",
                y=-0.28,
                x=0,
                font=dict(size=11),
                bgcolor="rgba(0,0,0,0)",
            ),
            hovermode="x unified",
        )
        st.markdown("<div class='chart-wrap'>", unsafe_allow_html=True)
        st.plotly_chart(fig_trend, use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)
else:
    st.caption("Select measures in the sidebar to populate the trend chart.")


# ── Row 3: County extremes ─────────────────────────────────────────────────────

st.markdown("---")
geo_scope = f"in {sel_state_name}" if sel_state else "nationally"
st.markdown(
    f"<div class='section-label'>County Extremes  ·  {sel_measure_label}  ·  {geo_scope}</div>",
    unsafe_allow_html=True,
)

county_df = _county_extremes(sel_measure_id, sel_state)

if not county_df.empty:
    county_df["label"] = county_df["county_name"] + ",  " + county_df["state_abbr"]

    high_df = county_df[county_df["cohort"] == "High"].sort_values("data_value", ascending=True)
    low_df  = county_df[county_df["cohort"] == "Low"].sort_values("data_value", ascending=True)

    fig_counties = go.Figure()

    # Bottom panel: lowest counties (green)
    fig_counties.add_trace(
        go.Bar(
            x=low_df["data_value"],
            y=low_df["label"],
            orientation="h",
            name="Lowest prevalence",
            marker_color=C["teal"],
            marker_line_width=0,
            xaxis="x",
            yaxis="y",
            customdata=low_df["total_population"].values,
            hovertemplate=(
                "<b>%{y}</b><br>"
                "Prevalence: <b>%{x:.1f}%</b><br>"
                "Population: %{customdata:,.0f}"
                "<extra></extra>"
            ),
        )
    )

    # Top panel: highest counties (red)
    fig_counties.add_trace(
        go.Bar(
            x=high_df["data_value"],
            y=high_df["label"],
            orientation="h",
            name="Highest prevalence",
            marker_color=C["danger"],
            marker_line_width=0,
            xaxis="x2",
            yaxis="y2",
            customdata=high_df["total_population"].values,
            hovertemplate=(
                "<b>%{y}</b><br>"
                "Prevalence: <b>%{x:.1f}%</b><br>"
                "Population: %{customdata:,.0f}"
                "<extra></extra>"
            ),
        )
    )

    x_min = max(0, county_df["data_value"].min() - 2)
    x_max = county_df["data_value"].max() + 2

    fig_counties.update_layout(
        **CHART_LAYOUT,
        height=380,
        margin=dict(l=12, r=16, t=36, b=36),
        grid=dict(rows=1, columns=2, pattern="independent"),
        xaxis=dict(
            title="Prevalence (%)", range=[x_min, x_max],
            **AXIS_STYLE, domain=[0, 0.48],
        ),
        yaxis=dict(title=None, tickfont=dict(size=10), **AXIS_STYLE, anchor="x"),
        xaxis2=dict(
            title="Prevalence (%)", range=[x_min, x_max],
            **AXIS_STYLE, domain=[0.52, 1.0],
        ),
        yaxis2=dict(title=None, tickfont=dict(size=10), **AXIS_STYLE, anchor="x2"),
        legend=dict(
            orientation="h", y=1.06, x=0,
            font=dict(size=11), bgcolor="rgba(0,0,0,0)",
        ),
        showlegend=True,
        annotations=[
            dict(
                text="Lowest Prevalence", x=0.24, y=1.04, xref="paper", yref="paper",
                showarrow=False, font=dict(size=11, color=C["teal"]), xanchor="center",
            ),
            dict(
                text="Highest Prevalence", x=0.76, y=1.04, xref="paper", yref="paper",
                showarrow=False, font=dict(size=11, color=C["danger"]), xanchor="center",
            ),
        ],
    )

    st.markdown("<div class='chart-wrap'>", unsafe_allow_html=True)
    st.plotly_chart(fig_counties, use_container_width=True)
    st.markdown("</div>", unsafe_allow_html=True)


# ── Footer ─────────────────────────────────────────────────────────────────────

st.markdown("---")
st.markdown(
    f"<div style='text-align:center;color:{C['muted']};font-size:0.78rem;padding:4px 0 12px'>"
    "Data: <a href='https://www.cdc.gov/places' target='_blank' "
    f"style='color:{C['primary']};text-decoration:none'>CDC PLACES Local Data for Better Health</a>"
    " &nbsp;·&nbsp; Age-adjusted prevalence (%) among adults aged 18+ "
    " &nbsp;·&nbsp; Built with Streamlit &amp; Plotly"
    "</div>",
    unsafe_allow_html=True,
)
