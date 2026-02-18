from dash import Dash, html
import os
from sqlalchemy import create_engine


base_dir = os.path.dirname(__file__)
db_path = os.path.join(base_dir, "portfolio.db")

engine = create_engine(f"sqlite:///{db_path}")


app = Dash(__name__, use_pages=True)

from pages import covariance, portfolio


app.layout = html.Div(
    [
        portfolio.layout,
        html.Hr(style={"margin": "36px 0"}),
        covariance.layout,
    ]
)

server = app.server
