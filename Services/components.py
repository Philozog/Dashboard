from dash import html


def metric_card(title, value_id):
    return html.Div(
        [
            html.Div(title, className="metric-title"),
            html.Div("--", id=value_id, className="metric-value"),
        ],
        className="metric-card",
    )
