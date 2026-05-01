import os
from datetime import datetime, timedelta, timezone

import requests


NEWS_API_KEY = os.getenv("NEWS_API_KEY")
NEWS_ENDPOINT = "https://newsapi.org/v2/everything"
IMPORTANT_KEYWORDS = {
    "earnings": 4,
    "guidance": 4,
    "forecast": 3,
    "revenue": 3,
    "profit": 3,
    "ceo": 3,
    "merger": 4,
    "acquisition": 4,
    "buyback": 3,
    "dividend": 3,
    "sec": 3,
    "investigation": 4,
    "lawsuit": 3,
    "fda": 4,
    "approval": 3,
    "downgrade": 2,
    "upgrade": 2,
    "guides": 2,
}


def _score_article(article):
    text = " ".join(
        [
            article.get("title") or "",
            article.get("description") or "",
        ]
    ).lower()
    score = 0
    for keyword, weight in IMPORTANT_KEYWORDS.items():
        if keyword in text:
            score += weight
    return score


def _parse_published_at(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def fetch_news_for_ticker(ticker, page_size=10):
    if not NEWS_API_KEY:
        return []

    from_date = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
    params = {
        "q": f'"{ticker}" AND (stock OR shares OR earnings OR guidance OR analyst OR revenue)',
        "sortBy": "publishedAt",
        "language": "en",
        "pageSize": page_size,
        "searchIn": "title,description",
        "from": from_date,
        "apiKey": NEWS_API_KEY,
    }

    response = requests.get(NEWS_ENDPOINT, params=params, timeout=20)
    response.raise_for_status()

    articles = []
    for raw in response.json().get("articles", []):
        published_at = _parse_published_at(raw.get("publishedAt"))
        if published_at is None:
            continue

        article = {
            "ticker": ticker,
            "title": raw.get("title") or "Untitled article",
            "description": raw.get("description") or "",
            "url": raw.get("url") or "",
            "source": (raw.get("source") or {}).get("name") or "Unknown source",
            "published_at": published_at,
        }
        article["importance_score"] = _score_article(article)
        articles.append(article)

    articles.sort(
        key=lambda item: (item["importance_score"], item["published_at"]),
        reverse=True,
    )
    return articles


def fetch_portfolio_news(tickers, per_ticker=8, max_items=20):
    unique_tickers = []
    seen = set()
    for ticker in tickers:
        normalized = str(ticker).strip().upper()
        if normalized and normalized not in seen:
            seen.add(normalized)
            unique_tickers.append(normalized)

    all_articles = []
    for ticker in unique_tickers:
        try:
            all_articles.extend(fetch_news_for_ticker(ticker, page_size=per_ticker))
        except requests.RequestException:
            continue

    deduped = []
    seen_urls = set()
    for article in all_articles:
        url = article.get("url")
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        deduped.append(article)

    deduped.sort(
        key=lambda item: (item["importance_score"], item["published_at"]),
        reverse=True,
    )
    return deduped[:max_items]
