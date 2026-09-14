from dash import Dash, html, dcc, Input, Output
import dash
from dotenv import load_dotenv

from Services.database import get_engine
from Services.theme import register_template

load_dotenv()
register_template()


engine = get_engine()

app = Dash(
    __name__,
    use_pages=True,
    suppress_callback_exceptions=True,
    title="Excelsior",
)

app.layout = html.Div([
    dcc.Location(id="url"),

    html.Div([
        html.H1("Excelsior", className="main-title"),

        # Navigation Bar
        html.Div([
            dcc.Link(page["name"], href=page["path"], className="nav-link")
            for page in dash.page_registry.values()
        ], className="navbar"),
    ], id="app-header", className="app-header"),

    dash.page_container,
])

# The cover page carries its own wordmark, so hide the global title there.
app.clientside_callback(
    "function(path) { return path === '/' ? 'app-header is-cover' : 'app-header'; }",
    Output("app-header", "className"),
    Input("url", "pathname"),
)

server = app.server
