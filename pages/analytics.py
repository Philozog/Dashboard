
import dash
from dash import html
from Services.updater import update_prices
dash.register_page(__name__, path="/analytics")

layout = html.Div(
    [
        html.H2("Portfolio Analytics", className="subtitle")
    ],
    style={"textAlign": "center", "marginBottom": "20px"}
)