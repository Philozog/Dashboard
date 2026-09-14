"""Shared visual theme for every Plotly figure in the app.

Colors mirror the CSS tokens in assets/style.css; keep the two in sync.
"""
import plotly.graph_objects as go
import plotly.io as pio


TEXT = "#e2e8f0"
TEXT_STRONG = "#f8fafc"
MUTED = "#94a3b8"
GRID = "rgba(148, 163, 184, 0.12)"
HOVER_BG = "#1e293b"

ACCENT = "#10b981"
ACCENT_BRIGHT = "#34d399"
POSITIVE = "#34d399"
NEGATIVE = "#fb7185"
WARNING = "#fbbf24"

# Categorical series colors — emerald first, then hues that stay distinct
# from it so two-series charts (portfolio vs benchmark) read at a glance.
CATEGORICAL = [
    "#34d399",
    "#38bdf8",
    "#fbbf24",
    "#a78bfa",
    "#f472b6",
    "#2dd4bf",
    "#fb7185",
    "#818cf8",
    "#4ade80",
    "#22d3ee",
]

HOLDING_TYPE_COLORS = {
    "Core": POSITIVE,
    "High Conviction": WARNING,
    "Moonshot": NEGATIVE,
    "Unassigned": MUTED,
}

TEMPLATE_NAME = "excelsior"


def register_template():
    """Register the app template and make it the Plotly default."""
    axis = dict(
        gridcolor=GRID,
        zerolinecolor=GRID,
        linecolor=GRID,
        tickcolor=GRID,
        tickfont=dict(color=MUTED),
        title=dict(font=dict(color=MUTED)),
    )
    layout = go.Layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, Segoe UI, sans-serif", color=TEXT, size=13),
        title=dict(font=dict(size=17, color=TEXT_STRONG), x=0.02, xanchor="left"),
        colorway=CATEGORICAL,
        xaxis=axis,
        yaxis=axis,
        legend=dict(bgcolor="rgba(0,0,0,0)", bordercolor=GRID, font=dict(color=TEXT)),
        hoverlabel=dict(bgcolor=HOVER_BG, bordercolor=GRID, font=dict(color=TEXT_STRONG)),
        margin=dict(l=48, r=24, t=56, b=44),
    )
    pio.templates[TEMPLATE_NAME] = go.layout.Template(layout=layout)
    pio.templates.default = TEMPLATE_NAME
