from datetime import date

import dash
from dash import dcc, html

dash.register_page(__name__, path="/", name="Home", title="Apothicaire", order=0)


def layout(**_kwargs):
    return html.Div(
        [
            html.Div(className="cover-orb cover-orb-a"),
            html.Div(className="cover-orb cover-orb-b"),
            html.Div(
                [
                    html.Div("Apothicaire", className="cover-wordmark"),
                    html.P("Risk Management", className="cover-tagline"),
                    dcc.Link("Enter →", href="/portfolio", className="button-link cover-cta"),
                ],
                className="cover-content",
            ),
            html.Div(f"{date.today():%A, %d %B %Y}", className="cover-footer"),
        ],
        className="cover",
    )
