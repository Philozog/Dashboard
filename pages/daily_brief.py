import dash
from dash import html, dcc
from pages.news import fetch_news
from pages.portfolio import load_data
from dash import Output, Input


dash.register_page(__name__, path="/daily_brief")

layout = html.Div(
    [
        html.H2("Portfolio News"),
        dcc.Interval(id="news-interval", interval=10 * 60 * 1000),
        html.Div(id="news-feed"),
    ]
)


@dash.callback(
    Output("news-feed", "children"),
    Input("news-interval", "n_intervals"),
)

def update_news(n_intervals):
    df=load_data()
    tickers=df['ticker'].unique().tolist()
    news=fetch_news(tickers,page_size=3)

    if not news:
        return html.P("No news available at the moment.")
    
    return [
        html.Div(
            [
                html.A(article["title"], href=article["url"], target="_blank"),
                html.Div(
                    f'{article["ticker"]} • {article["source"]} • {article["published"].strftime("%Y-%m-%d %H:%M")}',
                    style={"fontSize": "0.8em", "color": "gray"},
                ),
            ],
            style={"marginBottom": "10px"},
        )
        for article in news[:20]
    ]
    