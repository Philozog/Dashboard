from datetime import date

import dash
from dash import dcc, html


dash.register_page(__name__, path="/", name="Home", title="Excelsior", order=0)


def layout(**_kwargs):
    return html.Div(
        [
            html.Div(className="cover-orb cover-orb-a"),
            html.Div(className="cover-orb cover-orb-b"),
            html.Div(
                [
                    html.Div("Personal portfolio intelligence", className="cover-eyebrow"),
                    html.Div("Excelsior", className="cover-wordmark"),
                    html.P("See the risk. Make the call.", className="cover-tagline"),
                    dcc.Link("Enter →", href="/portfolio", className="button-link cover-cta"),
                ],
                className="cover-content",
            ),
            html.Div(f"{date.today():%A, %d %B %Y}", className="cover-footer"),
        ],
        className="cover",
    )
