import dash
from dash import Dash, Input, Output, dcc, html
from dotenv import load_dotenv

load_dotenv()

from Services.database import get_engine
from Services.theme import register_template

register_template()


engine = get_engine()

app = Dash(
    __name__,
    use_pages=True,
    suppress_callback_exceptions=True,
    title="Apothicaire",
)

app.layout = html.Div(
    [
        dcc.Location(id="url"),
        dcc.Store(id="settings-version", data=0),
        html.Div(
            [
                html.H1("Apothicaire", className="main-title"),
                # Navigation Bar
                html.Div(
                    [
                        dcc.Link(page["name"], href=page["path"], className="nav-link")
                        for page in dash.page_registry.values()
                    ],
                    className="navbar",
                ),
            ],
            id="app-header",
            className="app-header",
        ),
        html.Div(
            [
                html.Div(
                    [
                        html.Label("History window", htmlFor="analysis-period"),
                        dcc.Dropdown(
                            id="analysis-period",
                            options=[
                                {"label": label, "value": value}
                                for label, value in [
                                    ("6 months", "6mo"),
                                    ("1 year", "1y"),
                                    ("3 years", "3y"),
                                    ("5 years", "5y"),
                                ]
                            ],
                            value="1y",
                            clearable=False,
                            persistence=True,
                            persistence_type="local",
                        ),
                    ]
                ),
                html.Div(
                    [
                        html.Label("Benchmark", htmlFor="analysis-benchmark"),
                        dcc.Dropdown(
                            id="analysis-benchmark",
                            options=[{"label": v, "value": v} for v in ["SPY", "QQQ", "VT", "AGG"]],
                            value="SPY",
                            clearable=False,
                            persistence=True,
                            persistence_type="local",
                        ),
                    ]
                ),
                html.Span(
                    "Shared by Analytics, Correlations and Monte Carlo history.", className="muted"
                ),
            ],
            id="analysis-controls",
            className="analysis-controls card",
        ),
        dash.page_container,
    ]
)

# The cover page carries its own wordmark, so hide the global title there.
app.clientside_callback(
    "function(path) { return path === '/' ? 'app-header is-cover' : 'app-header'; }",
    Output("app-header", "className"),
    Input("url", "pathname"),
)

server = app.server

app.clientside_callback(
    "function(path) { return {display: ['/analytics','/covariance','/monte-carlo'].includes(path) ? 'flex' : 'none'}; }",
    Output("analysis-controls", "style"),
    Input("url", "pathname"),
)
