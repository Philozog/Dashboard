from dash import Dash, html, dcc
import dash
from dotenv import load_dotenv

from Services.database import get_engine

load_dotenv()


engine = get_engine()

app = Dash(
    __name__,
    use_pages=True,
    suppress_callback_exceptions=True,
    title="Apothicaire Portfolio",
)

app.layout = html.Div([
    html.H1("Apothicaire Portfolio", className="main-title"),

    # Navigation Bar
    html.Div([
        dcc.Link(page["name"], href=page["path"], className="nav-link")
        for page in dash.page_registry.values()
    ], className="navbar"),

    dash.page_container,
])

server = app.server
