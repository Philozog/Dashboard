from datetime import datetime, timezone

import dash
from dash import Input, Output, dcc, html

from Services.helper import load_data
from Services.news import NewsFetchError, describe_fetch, fetch_portfolio_news


MAX_NEWS_ITEMS = 18


dash.register_page(
    __name__,
    path="/portfolio-news",
    name="Portfolio News",
    title="Portfolio News",
)


def _relative_time(published_at):
    now = datetime.now(timezone.utc)
    delta = now - published_at
    total_hours = max(int(delta.total_seconds() // 3600), 0)

    if total_hours < 1:
        return "less than 1 hour ago"
    if total_hours < 24:
        return f"{total_hours} hours ago"

    total_days = total_hours // 24
    if total_days == 1:
        return "1 day ago"
    return f"{total_days} days ago"


def _importance_label(score):
    if score >= 7:
        return "High impact"
    if score >= 3:
        return "Watch"
    return "Latest"


def _serialize_article(article):
    serialized = dict(article)
    published_at = serialized.get("published_at")
    if isinstance(published_at, datetime):
        serialized["published_at"] = published_at.isoformat()
    return serialized


def _deserialize_article(article):
    deserialized = dict(article)
    published_at = deserialized.get("published_at")
    if isinstance(published_at, str):
        deserialized["published_at"] = datetime.fromisoformat(published_at)
    return deserialized


def _why_it_matters(article):
    text = " ".join([article.get("title") or "", article.get("description") or ""]).lower()

    rules = [
        ("earnings", "Earnings can reset market expectations quickly."),
        ("guidance", "Guidance changes often move valuation more than the quarter itself."),
        ("forecast", "Forward outlook matters because the market prices future cash flows."),
        ("revenue", "Revenue updates can signal demand strength or weakness."),
        ("profit", "Profitability changes can alter conviction in the business model."),
        ("merger", "Corporate actions can materially change the company's future profile."),
        ("acquisition", "Acquisitions can affect growth, leverage, and execution risk."),
        ("dividend", "Dividend changes matter for cash return and capital allocation."),
        ("buyback", "Buybacks can influence capital allocation and per-share value."),
        ("lawsuit", "Legal issues can create downside risk and headline volatility."),
        ("investigation", "Investigations can create regulatory and reputational risk."),
        ("fda", "FDA developments can materially change product economics."),
        ("approval", "Approvals can unlock new revenue or reduce uncertainty."),
        ("ceo", "Leadership changes can shift execution and strategy."),
        ("downgrade", "Analyst rating changes can impact sentiment and flows."),
        ("upgrade", "Analyst upgrades can improve sentiment and expectations."),
    ]

    for keyword, explanation in rules:
        if keyword in text:
            return explanation

    return "This is one of the most recent portfolio-related headlines and may affect sentiment or near-term expectations."


def _news_card(article):
    published_at = article["published_at"]
    label = _importance_label(article.get("importance_score", 0))

    return html.Div(
        [
            html.Div(
                [
                    html.Span(article["ticker"], className="news-ticker"),
                    html.Span(label, className=f"news-impact news-impact-{label.lower().replace(' ', '-')}"),
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
                    html.Span(published_at.strftime("%b %d, %I:%M %p UTC")),
                    html.Span(_relative_time(published_at)),
                ],
                className="news-meta",
            ),
            html.P(article.get("description") or "No summary available.", className="news-description"),
            html.Div(
                [
                    html.Span("Why it matters: ", style={"fontWeight": "700"}),
                    html.Span(_why_it_matters(article)),
                ],
                className="news-why",
            ),
            html.Div(
                [
                    html.A("Read", href=article["url"], target="_blank", rel="noreferrer", className="news-action"),
                    html.Span(f'Score {article.get("importance_score", 0)}', className="news-score"),
                ],
                className="news-card-footer",
            ),
        ],
        className="news-card",
    )


def _metric(label, value):
    return html.Div(
        [
            html.Div(value, className="news-metric-value"),
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


layout = html.Div(
    [
        dcc.Location(id="portfolio-news-location"),
        dcc.Store(id="portfolio-news-data"),
        html.Div(
            [
                html.Div(
                    [
                        html.Div("Portfolio News", className="news-eyebrow"),
                        html.H2("Important News For Your Holdings", className="news-heading"),
                        html.P(
                            "Ranked headlines, portfolio filters, and quick context for the stocks you own.",
                            className="news-subheading",
                        ),
                    ],
                    className="news-hero-copy",
                ),
                html.Button("Refresh", id="portfolio-news-refresh-btn", n_clicks=0, className="news-refresh-button"),
            ],
            className="news-hero",
        ),
        html.Div(id="portfolio-news-status", className="news-status"),
        html.Div(id="portfolio-news-metrics", className="news-metrics"),
        html.Div(
            [
                dcc.Input(
                    id="portfolio-news-search",
                    type="search",
                    placeholder="Search headline, source, or summary",
                    className="news-search",
                    debounce=False,
                ),
                dcc.Dropdown(
                    id="portfolio-news-ticker-filter",
                    placeholder="All tickers",
                    clearable=True,
                    className="news-dropdown",
                ),
                dcc.RadioItems(
                    id="portfolio-news-impact-filter",
                    options=[
                        {"label": "All", "value": "all"},
                        {"label": "High impact", "value": "high"},
                        {"label": "Watch", "value": "watch"},
                    ],
                    value="all",
                    className="news-segmented",
                    inputClassName="news-segmented-input",
                    labelClassName="news-segmented-label",
                ),
                dcc.RadioItems(
                    id="portfolio-news-sort",
                    options=[
                        {"label": "Impact", "value": "impact"},
                        {"label": "Newest", "value": "newest"},
                    ],
                    value="impact",
                    className="news-segmented",
                    inputClassName="news-segmented-input",
                    labelClassName="news-segmented-label",
                ),
            ],
            className="news-controls",
        ),
        dcc.Interval(id="portfolio-news-refresh", interval=15 * 60 * 1000, n_intervals=0),
        html.Div(id="portfolio-news-spotlight"),
        html.Div(id="portfolio-news-feed", className="news-feed"),
    ]
)


if not hasattr(dash, "_portfolio_news_callback_registered"):
    dash._portfolio_news_callback_registered = True

    @dash.callback(
        Output("portfolio-news-data", "data"),
        Output("portfolio-news-status", "children"),
        Output("portfolio-news-ticker-filter", "options"),
        Input("portfolio-news-location", "pathname"),
        Input("portfolio-news-refresh", "n_intervals"),
        Input("portfolio-news-refresh-btn", "n_clicks"),
    )
    def update_portfolio_news(_, __, ___):
        holdings = load_data()
        if holdings.empty:
            return [], "No holdings found. Add tickers on the Portfolio page first.", []

        tickers = (
            holdings["ticker"]
            .dropna()
            .astype(str)
            .str.strip()
            .str.upper()
            .tolist()
        )
        tickers = [ticker for ticker in tickers if ticker]
        if not tickers:
            return [], "No holdings found. Add tickers on the Portfolio page first.", []

        all_options = [{"label": ticker, "value": ticker} for ticker in sorted(set(tickers))]
        # Only the Refresh button bypasses the cache; navigation and the
        # background interval are served from cache when it is still fresh.
        force = dash.ctx.triggered_id == "portfolio-news-refresh-btn"
        try:
            articles = fetch_portfolio_news(tickers, per_ticker=8, max_items=MAX_NEWS_ITEMS, force=force)
        except NewsFetchError as exc:
            return [], f"Could not load news: {exc}", all_options

        if not articles:
            return [], f"No headlines mentioned your holdings in the last 7 days. {describe_fetch()}", all_options

        covered_tickers = sorted({article["ticker"] for article in articles})
        status = (
            f"Showing {len(articles)} recent important headlines across {len(covered_tickers)} holdings. "
            f"Covered tickers: {', '.join(covered_tickers)}. {describe_fetch()}"
        )
        options = [{"label": ticker, "value": ticker} for ticker in covered_tickers]
        return [_serialize_article(article) for article in articles], status, options

    @dash.callback(
        Output("portfolio-news-metrics", "children"),
        Output("portfolio-news-spotlight", "children"),
        Output("portfolio-news-feed", "children"),
        Input("portfolio-news-data", "data"),
        Input("portfolio-news-search", "value"),
        Input("portfolio-news-ticker-filter", "value"),
        Input("portfolio-news-impact-filter", "value"),
        Input("portfolio-news-sort", "value"),
    )
    def render_portfolio_news(data, search, ticker, impact_filter, sort_by):
        articles = [_deserialize_article(article) for article in (data or [])]
        if not articles:
            return [], "", _empty_state("No headlines yet", "Headlines appear here once a refresh succeeds — see the status line above.")

        query = (search or "").strip().lower()
        filtered = []
        for article in articles:
            haystack = " ".join(
                [
                    article.get("ticker") or "",
                    article.get("source") or "",
                    article.get("title") or "",
                    article.get("description") or "",
                ]
            ).lower()

            if ticker and article.get("ticker") != ticker:
                continue
            if query and query not in haystack:
                continue
            if impact_filter == "high" and article.get("importance_score", 0) < 7:
                continue
            if impact_filter == "watch" and article.get("importance_score", 0) < 3:
                continue
            filtered.append(article)

        if sort_by == "newest":
            filtered.sort(key=lambda item: item["published_at"], reverse=True)
        else:
            filtered.sort(key=lambda item: (item.get("importance_score", 0), item["published_at"]), reverse=True)

        high_impact = sum(1 for article in articles if article.get("importance_score", 0) >= 7)
        sources = len({article.get("source") for article in articles if article.get("source")})
        newest = max(articles, key=lambda item: item["published_at"])
        metrics = [
            _metric("Headlines", len(articles)),
            _metric("High Impact", high_impact),
            _metric("Sources", sources),
            _metric("Newest", _relative_time(newest["published_at"])),
        ]

        if not filtered:
            return metrics, "", _empty_state("No matches", "Try another ticker, keyword, or impact filter.")

        spotlight = html.Div(
            [
                html.Div("Spotlight", className="news-spotlight-label"),
                html.A(
                    filtered[0]["title"],
                    href=filtered[0]["url"],
                    target="_blank",
                    rel="noreferrer",
                    className="news-spotlight-title",
                ),
                html.Div(
                    f'{filtered[0]["ticker"]} | {filtered[0]["source"]} | {_relative_time(filtered[0]["published_at"])}',
                    className="news-spotlight-meta",
                ),
                html.P(_why_it_matters(filtered[0]), className="news-spotlight-text"),
            ],
            className="news-spotlight",
        )

        cards = [_news_card(article) for article in filtered]
        return metrics, spotlight, cards
