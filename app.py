from dash import Dash, html, dcc
import dash
import os
from sqlalchemy import create_engine

base_dir = os.path.dirname(__file__)
db_path = os.path.join(base_dir, "portfolio.db")

engine = create_engine(f"sqlite:///{db_path}")

app = Dash(__name__, use_pages=True)

app.layout = html.Div([
    html.H1("Joe Zoghzoghi Portfolio", className="main-title"),

    # Navigation Bar
    html.Div([
        dcc.Link(page["name"], href=page["path"], className="nav-link")
        for page in dash.page_registry.values()
    ], className="navbar"),

    dash.page_container,
])

server = app.server