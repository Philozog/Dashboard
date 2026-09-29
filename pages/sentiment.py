"""News Sentiment page.

Reads the same two sources the rest of the app already uses:

  Services.helper.load_data()      the holdings table behind /portfolio
  Services.news.fetch_portfolio_news()  the headline cache behind /portfolio-news

and adds one step: every headline is run through a finance-tuned
transformer (Services.sentiment) to get a positive/negative/neutral
probability, which is folded into one score per ticker and one score for
the portfolio as a whole.

Because the headline fetch is shared with /portfolio-news, opening this
page costs no extra NewsAPI quota when that page was loaded recently.
"""

from datetime import datetime, timezone

import dash
import plotly.graph_objects as go
from dash import Input, Output, dcc, html

from Services import sentiment as sentiment_service
from Services.helper import load_data
from Services.insights import prepare_holdings
from Services.news import NewsFetchError, describe_fetch, fetch_portfolio_news
from Services.theme import MUTED, NEGATIVE, POSITIVE, TEXT_STRONG

MAX_NEWS_ITEMS = 24
PER_TICKER = 8


dash.register_page(
    __name__,
    path="/sentiment",
    name="News Sentiment",
    title="News Sentiment",
    order=6,
)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _relative_time(published_at):
    delta = datetime.now(timezone.utc) - published_at
    hours = max(int(delta.total_seconds() // 3600), 0)
    if hours < 1:
        return "under 1 h ago"
    if hours < 24:
        return "{} h ago".format(hours)
    days = hours // 24
    return "1 day ago" if days == 1 else "{} days ago".format(days)


def _score_color(score):
    if score >= sentiment_service.BULLISH_CUTOFF:
        return POSITIVE
    if score <= sentiment_service.BEARISH_CUTOFF:
        return NEGATIVE
    return MUTED


def _tone_class(label):
    return "sent-tone sent-tone-{}".format(label.lower())


def _serialize(article):
    out = dict(article)
    published_at = out.get("published_at")
    if isinstance(published_at, datetime):
        out["published_at"] = published_at.isoformat()
    return out


def _deserialize(article):
    out = dict(article)
    published_at = out.get("published_at")
    if isinstance(published_at, str):
        out["published_at"] = datetime.fromisoformat(published_at)
    return out


def _metric(label, value, tone=None):
    return html.Div(
        [
            html.Div(value, className="news-metric-value", style={"color": tone} if tone else None),
            html.Div(label, className="news-metric-label"),
        ],
        className="news-metric",
    )


def _empty_state(title, message):
    return html.Div(
        [
            html.Div(title, className="news-empty-title"),
            html.Div(message, className="news-empty-message"),
        ],
        className="news-empty-state",
    )


# ---------------------------------------------------------------------------
# Figures
# ---------------------------------------------------------------------------


def _ticker_bar_figure(rows):
    """Diverging bar: one bar per holding, left of zero is bearish."""
    ordered = sorted(rows, key=lambda row: row["score"])
    tickers = [row["ticker"] for row in ordered]
    scores = [row["score"] for row in ordered]
    colors = [_score_color(score) for score in scores]

    hover = [
        "<b>{}</b><br>Score {:+.1f}<br>{} headlines<br>"
        "{} positive / {} neutral / {} negative<extra></extra>".format(
            row["ticker"],
            row["score"],
            row["headlines"],
            row["positive"],
            row["neutral"],
            row["negative"],
        )
        for row in ordered
    ]

    figure = go.Figure(
        go.Bar(
            x=scores,
            y=tickers,
            orientation="h",
            marker=dict(color=colors),
            hovertemplate=hover,
            text=["{:+.0f}".format(score) for score in scores],
            textposition="outside",
            cliponaxis=False,
        )
    )
    figure.add_vline(x=0, line_width=1, line_color="rgba(148,163,184,0.45)")
    figure.add_vrect(
        x0=sentiment_service.BEARISH_CUTOFF,
        x1=sentiment_service.BULLISH_CUTOFF,
        fillcolor="rgba(148,163,184,0.07)",
        line_width=0,
        layer="below",
    )
    figure.update_layout(
        title="Sentiment by holding (shaded band counts as neutral)",
        xaxis_title="Weighted sentiment score",
        yaxis_title=None,
        height=max(260, 42 * len(tickers) + 120),
        showlegend=False,
    )
    figure.update_xaxes(range=[-105, 105])
    return figure


def _weight_scatter_figure(rows, weights, market_values):
    """Sentiment against portfolio weight: the far right of the chart is
    where the news actually matters, because that is where the money is."""
    points = [row for row in rows if row["ticker"] in weights]
    if not points:
        return None

    x = [weights[row["ticker"]] for row in points]
    y = [row["score"] for row in points]
    sizes = [max(market_values.get(row["ticker"], 0.0), 1.0) for row in points]
    largest = max(sizes)
    scaled = [18 + 42 * (size / largest) ** 0.5 for size in sizes]

    figure = go.Figure(
        go.Scatter(
            x=x,
            y=y,
            mode="markers+text",
            text=[row["ticker"] for row in points],
            textposition="middle center",
            textfont=dict(color=TEXT_STRONG, size=11),
            marker=dict(
                size=scaled,
                color=[_score_color(row["score"]) for row in points],
                opacity=0.55,
                line=dict(width=1, color="rgba(226,232,240,0.5)"),
            ),
            hovertemplate=(
                "<b>%{text}</b><br>Weight %{x:.1f}%<br>Sentiment %{y:+.1f}<extra></extra>"
            ),
        )
    )
    figure.add_hline(y=0, line_width=1, line_color="rgba(148,163,184,0.45)")
    figure.update_layout(
        title="Sentiment vs position size (bubble = market value)",
        xaxis_title="Portfolio weight (%)",
        yaxis_title="Weighted sentiment score",
        height=420,
        showlegend=False,
    )
    figure.update_yaxes(range=[-105, 105])
    return figure


# ---------------------------------------------------------------------------
# Cards
# ---------------------------------------------------------------------------


def _probability_bar(sentiment):
    """Stacked bar showing the three class probabilities the model returned."""
    segments = [
        ("positive", sentiment["positive"], POSITIVE),
        ("neutral", sentiment["neutral"], MUTED),
        ("negative", sentiment["negative"], NEGATIVE),
    ]
    return html.Div(
        [
            html.Div(
                title="{} {:.0%}".format(name, value),
                className="sent-prob-segment",
                style={
                    "width": "{:.2f}%".format(value * 100),
                    "background": color,
                },
            )
            for name, value, color in segments
            if value > 0
        ],
        className="sent-prob-bar",
    )


def _ticker_card(row):
    score = row["score"]
    top = row.get("top_headline") or {}
    return html.Div(
        [
            html.Div(
                [
                    html.Span(row["ticker"], className="news-ticker"),
                    html.Span(row["label"], className=_tone_class(row["label"])),
                ],
                className="news-card-topline",
            ),
            html.Div(
                "{:+.1f}".format(score),
                className="sent-score",
                style={"color": _score_color(score)},
            ),
            html.Div(
                "{} headlines  ·  {} pos / {} neu / {} neg".format(
                    row["headlines"], row["positive"], row["neutral"], row["negative"]
                ),
                className="sent-card-meta",
            ),
            html.Div(
                [
                    html.Span("Most opinionated: ", style={"fontWeight": "700"}),
                    html.A(
                        top.get("title", "n/a"),
                        href=top.get("url", "#"),
                        target="_blank",
                        rel="noreferrer",
                        className="sent-card-link",
                    ),
                ],
                className="sent-card-top",
            )
            if top
            else html.Div(),
        ],
        className="sent-ticker-card",
    )


def _headline_row(article):
    sentiment = article["sentiment"]
    score = sentiment["score"]
    return html.Div(
        [
            html.Div(
                [
                    html.Span(article["ticker"], className="news-ticker"),
                    html.Span(
                        "{:+.1f}".format(score),
                        className="sent-inline-score",
                        style={"color": _score_color(score)},
                    ),
                    html.Span(
                        sentiment["label"].title(),
                        className=_tone_class(
                            {"positive": "bullish", "negative": "bearish"}.get(
                                sentiment["label"], "neutral"
                            )
                        ),
                    ),
                ],
                className="news-card-topline",
            ),
            html.A(
                article["title"],
                href=article["url"],
                target="_blank",
                rel="noreferrer",
                className="news-title",
            ),
            html.Div(
                [
                    html.Span(article["source"]),
                    html.Span(_relative_time(article["published_at"])),
                    html.Span("confidence {:.0%}".format(sentiment["confidence"])),
                    html.Span("Model: " + sentiment.get("model", "keyword fallback")),
                ],
                className="news-meta",
            ),
            _probability_bar(sentiment),
            html.Div(
                "pos {:.0%}  ·  neu {:.0%}  ·  neg {:.0%}".format(
                    sentiment["positive"], sentiment["neutral"], sentiment["negative"]
                ),
                className="sent-prob-legend",
            ),
        ],
        className="news-card sent-headline-card",
    )


def _explainer():
    steps = [
        (
            "1. Collect",
            "Your holdings come from the portfolio database, the same table "
            "the Portfolio page edits. Their tickers become a NewsAPI query, "
            "cached and shared with the News page so this page "
            "spends no extra API quota.",
        ),
        (
            "2. Tokenise",
            "Each headline plus its summary is cut into word-pieces the model "
            "recognises, then padded and truncated to 128 tokens. This is what "
            "the tokenizer does: it converts text into integer ids, because a "
            "neural network cannot read characters.",
        ),
        (
            "3. Classify",
            "FinBERT reads those ids and outputs three raw numbers called "
            "logits, one per class. A softmax turns them into probabilities "
            "that sum to 1, for example 72% positive, 25% neutral, 3% negative.",
        ),
        (
            "4. Signed score",
            "Instead of keeping only the winning label we take positive minus "
            "negative, scaled to -100..100. A headline the model finds strongly "
            "neutral lands near zero by construction, which is the behaviour a "
            "portfolio signal needs.",
        ),
        (
            "5. Aggregate",
            "Per ticker, headlines are averaged with two weights: recency, "
            "halving every 3 days, and the impact score the news module already "
            "computes from keywords like earnings or lawsuit. The portfolio "
            "number then weights each ticker by its share of market value.",
        ),
    ]

    caveats = [
        "Sentiment measures the tone of coverage, not whether a stock is cheap. "
        "It is a context layer on top of the Analytics and Correlations pages, not a signal to trade on.",
        "A ticker with two headlines has a far noisier score than one with twelve. "
        "The headline count is shown on every card for that reason.",
        "NewsAPI matches tickers as plain words, so short symbols can pull in "
        "unrelated articles. Check the headline list before trusting an outlier.",
        "The model never sees prices. It cannot know a good headline was already priced in.",
    ]

    return html.Div(
        [
            html.Div("How this page works", className="card-title"),
            html.Div(
                [
                    html.Div(
                        [
                            html.Div(title, className="sent-step-title"),
                            html.P(body, className="sent-step-body"),
                        ],
                        className="sent-step",
                    )
                    for title, body in steps
                ],
                className="sent-steps",
            ),
            html.Div("What it cannot tell you", className="sent-caveat-title"),
            html.Ul(
                [html.Li(text) for text in caveats],
                className="sent-caveats",
            ),
        ],
        className="card sent-explainer",
    )


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

layout = html.Div(
    [
        dcc.Location(id="sentiment-location"),
        dcc.Store(id="sentiment-data"),
        html.Div(
            [
                html.Div(
                    [
                        html.Div("News Sentiment", className="news-eyebrow"),
                        html.H2("How The Press Is Framing Your Holdings", className="news-heading"),
                        html.P(
                            "Every recent headline about a position, scored by a "
                            "finance-tuned language model and rolled up per ticker.",
                            className="news-subheading",
                        ),
                    ],
                    className="news-hero-copy",
                ),
                html.Button(
                    "Refresh",
                    id="sentiment-refresh-btn",
                    n_clicks=0,
                    className="news-refresh-button",
                ),
            ],
            className="news-hero",
        ),
        dcc.Loading(
            html.Div(id="sentiment-status", className="news-status"),
            type="dot",
            color=POSITIVE,
        ),
        html.Div(id="sentiment-metrics", className="news-metrics sent-metrics"),
        html.Div(id="sentiment-ticker-cards", className="sent-ticker-grid"),
        html.Div(
            [
                html.Div(
                    dcc.Graph(id="sentiment-bar", config={"displayModeBar": False}),
                    className="card",
                ),
                html.Div(
                    dcc.Graph(id="sentiment-scatter", config={"displayModeBar": False}),
                    className="card",
                ),
            ],
            className="section-grid two",
        ),
        html.Div(
            [
                html.Div("Scored headlines", className="card-title"),
                html.Div(
                    [
                        dcc.Dropdown(
                            id="sentiment-ticker-filter",
                            placeholder="All tickers",
                            clearable=True,
                            className="news-dropdown",
                        ),
                        dcc.RadioItems(
                            id="sentiment-tone-filter",
                            options=[
                                {"label": "All", "value": "all"},
                                {"label": "Positive", "value": "positive"},
                                {"label": "Neutral", "value": "neutral"},
                                {"label": "Negative", "value": "negative"},
                            ],
                            value="all",
                            className="news-segmented",
                            inputClassName="news-segmented-input",
                            labelClassName="news-segmented-label",
                        ),
                        dcc.RadioItems(
                            id="sentiment-sort",
                            options=[
                                {"label": "Strongest", "value": "strength"},
                                {"label": "Most positive", "value": "positive"},
                                {"label": "Most negative", "value": "negative"},
                                {"label": "Newest", "value": "newest"},
                            ],
                            value="strength",
                            className="news-segmented",
                            inputClassName="news-segmented-input",
                            labelClassName="news-segmented-label",
                        ),
                    ],
                    className="news-controls",
                ),
                html.Div(id="sentiment-feed", className="news-feed"),
            ],
        ),
        _explainer(),
    ]
)


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------

if not hasattr(dash, "_sentiment_callback_registered"):
    dash._sentiment_callback_registered = True

    @dash.callback(
        Output("sentiment-data", "data"),
        Output("sentiment-status", "children"),
        Output("sentiment-ticker-filter", "options"),
        Input("sentiment-location", "pathname"),
        Input("sentiment-refresh-btn", "n_clicks"),
    )
    def load_sentiment(pathname, _clicks):
        if pathname != "/sentiment":
            raise dash.exceptions.PreventUpdate

        holdings = prepare_holdings(load_data())
        if holdings.empty:
            return {}, "No holdings found. Add tickers on the Portfolio page first.", []

        tickers = [ticker for ticker in holdings["ticker"].tolist() if ticker]
        all_options = [{"label": ticker, "value": ticker} for ticker in sorted(set(tickers))]

        force = dash.ctx.triggered_id == "sentiment-refresh-btn"
        try:
            articles = fetch_portfolio_news(
                tickers, per_ticker=PER_TICKER, max_items=MAX_NEWS_ITEMS, force=force
            )
        except NewsFetchError as exc:
            return {}, "Could not load headlines: {}".format(exc), all_options

        if not articles:
            return (
                {},
                "No headlines mentioned your holdings in the last 7 days. {}".format(
                    describe_fetch()
                ),
                all_options,
            )

        # Wire stories reach us under several URLs with the same headline.
        # Left in, each copy would count again in the ticker average.
        articles = sentiment_service.dedupe_articles(articles)
        scored = sentiment_service.score_articles(articles)
        weights = dict(zip(holdings["ticker"], holdings["weight_pct"]))
        ticker_rows = sentiment_service.aggregate_by_ticker(scored)
        overall = sentiment_service.portfolio_score(ticker_rows, weights)

        payload = {
            "articles": [_serialize(article) for article in scored],
            "tickers": [
                {
                    **row,
                    "latest": row["latest"].isoformat() if row["latest"] else None,
                    "top_headline": _serialize(row["top_headline"])
                    if row["top_headline"]
                    else None,
                }
                for row in ticker_rows
            ],
            "overall": overall,
            "coverage": sum(weights.get(row["ticker"], 0) for row in ticker_rows),
            "weights": {key: float(value) for key, value in weights.items()},
            "market_values": {
                key: float(value)
                for key, value in zip(holdings["ticker"], holdings["market_value"])
            },
        }

        status = "Scored {} headlines across {} holdings. {} {}".format(
            len(scored),
            len(ticker_rows),
            sentiment_service.describe_scores(scored),
            describe_fetch(),
        )
        options = [{"label": row["ticker"], "value": row["ticker"]} for row in ticker_rows]
        return payload, status, options

    @dash.callback(
        Output("sentiment-metrics", "children"),
        Output("sentiment-ticker-cards", "children"),
        Output("sentiment-bar", "figure"),
        Output("sentiment-scatter", "figure"),
        Input("sentiment-data", "data"),
    )
    def render_overview(data):
        empty = go.Figure()
        empty.update_layout(
            height=300,
            annotations=[
                dict(text="No scored headlines yet", showarrow=False, font=dict(color=MUTED))
            ],
        )

        rows = (data or {}).get("tickers") or []
        if not rows:
            return (
                [],
                _empty_state(
                    "Nothing scored yet",
                    "Headlines appear here once a news refresh succeeds. See the status line above.",
                ),
                empty,
                empty,
            )

        articles = (data or {}).get("articles") or []
        overall = (data or {}).get("overall")
        bullish = sum(1 for row in rows if row["label"] == "Bullish")
        bearish = sum(1 for row in rows if row["label"] == "Bearish")

        metrics = [
            _metric(
                "Sentiment of covered holdings",
                "{:+.1f}".format(overall) if overall is not None else "n/a",
                _score_color(overall or 0.0),
            ),
            _metric("Headlines scored", len(articles)),
            _metric("Bullish names", bullish, POSITIVE if bullish else None),
            _metric("Bearish names", bearish, NEGATIVE if bearish else None),
            _metric("Holdings covered", len(rows)),
            _metric("Invested value covered", f"{data.get('coverage', 0):.1f}%"),
        ]

        cards = [
            _ticker_card(
                {
                    **row,
                    "top_headline": (
                        _deserialize(row["top_headline"]) if row.get("top_headline") else None
                    ),
                }
            )
            for row in rows
        ]

        bar = _ticker_bar_figure(rows)

        weights = (data or {}).get("weights") or {}
        market_values = (data or {}).get("market_values") or {}
        scatter = _weight_scatter_figure(rows, weights, market_values)
        return metrics, cards, bar, scatter or empty

    @dash.callback(
        Output("sentiment-feed", "children"),
        Input("sentiment-data", "data"),
        Input("sentiment-ticker-filter", "value"),
        Input("sentiment-tone-filter", "value"),
        Input("sentiment-sort", "value"),
    )
    def render_feed(data, ticker, tone, sort_by):
        articles = [_deserialize(article) for article in (data or {}).get("articles") or []]
        if not articles:
            return _empty_state(
                "No headlines", "Nothing to score yet. Try Refresh, or check the status line."
            )

        filtered = [
            article
            for article in articles
            if (not ticker or article.get("ticker") == ticker)
            and (tone in (None, "all") or article["sentiment"]["label"] == tone)
        ]

        if sort_by == "newest":
            filtered.sort(key=lambda item: item["published_at"], reverse=True)
        elif sort_by == "positive":
            filtered.sort(key=lambda item: item["sentiment"]["score"], reverse=True)
        elif sort_by == "negative":
            filtered.sort(key=lambda item: item["sentiment"]["score"])
        else:
            filtered.sort(key=lambda item: abs(item["sentiment"]["score"]), reverse=True)

        if not filtered:
            return _empty_state("No matches", "Try another ticker or tone filter.")
        return [_headline_row(article) for article in filtered]
