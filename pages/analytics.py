
import dash
from dash import html
from pages.updater import update_prices
dash.register_page(__name__, path="/analytics")

layout = html.Div(
    [
        html.H1("Portfolio Analytics"),
    ],
    style={"textAlign": "center", "marginBottom": "20px", "color": "#EA84FC"},
)