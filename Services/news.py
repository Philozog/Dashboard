import os
import re
import threading
from datetime import datetime, timedelta, timezone

import requests


NEWS_ENDPOINT = "https://newsapi.org/v2/everything"
LOOKBACK_DAYS = 7
REQUEST_TIMEOUT = 10
# NewsAPI caps the q parameter at 500 characters; leave headroom.
MAX_QUERY_CHARS = 480
TOPIC_FILTER = "(stock OR shares OR earnings OR guidance OR analyst OR revenue)"
# Serve cached headlines for this long before hitting the API again.
# The free NewsAPI plan allows only 100 requests/day, so every request counts.
CACHE_TTL = timedelta(minutes=15)

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


class NewsFetchError(Exception):
    """Raised when no headlines can be returned, cached or live."""


# One cache entry per distinct set of tickers, holding the full un-trimmed list
# so both pages (different per-ticker caps) share the same API call.
_cache = {}
_lock = threading.Lock()
_last_info = {"source": None, "error": None, "fetched_at": None}


def _api_key():
    # Read lazily so load_dotenv() in app.py is respected regardless of import order.
    return os.getenv("NEWS_API_KEY")


def _set_info(source, error, fetched_at):
    _last_info.update({"source": source, "error": error, "fetched_at": fetched_at})


def last_fetch_info():
    """How the most recent fetch_portfolio_news() call was served."""
    return dict(_last_info)


def describe_fetch(info=None):
    """Human-readable freshness line for the status area of a page."""
    info = info or last_fetch_info()
    fetched_at = info.get("fetched_at")
    age = _relative_minutes(fetched_at) if fetched_at else None
    source = info.get("source")
    if source == "live":
        return "Updated just now."
    if source == "cache":
        return f"Updated {age} (cached; press Refresh to fetch again)."
    if source == "stale":
        return f"Showing headlines cached {age} — live refresh failed: {info.get('error')}"
    return ""


def _relative_minutes(moment):
    minutes = max(int((datetime.now(timezone.utc) - moment).total_seconds() // 60), 0)
    if minutes < 1:
        return "moments ago"
    if minutes < 60:
        return f"{minutes} min ago"
    hours = minutes // 60
    return f"{hours} h ago" if hours < 24 else f"{hours // 24} d ago"


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


def _normalize_tickers(tickers):
    unique = []
    seen = set()
    for ticker in tickers:
        normalized = str(ticker).strip().upper()
        if normalized and normalized not in seen:
            seen.add(normalized)
            unique.append(normalized)
    return unique


def _build_query(tickers):
    symbols = " OR ".join(f'"{ticker}"' for ticker in tickers)
    return f"({symbols}) AND {TOPIC_FILTER}"


def _chunk_tickers(tickers):
    """Group tickers into as few requests as the query length cap allows."""
    chunks, current = [], []
    for ticker in tickers:
        candidate = current + [ticker]
        if current and len(_build_query(candidate)) > MAX_QUERY_CHARS:
            chunks.append(current)
            current = [ticker]
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def _match_ticker(text, tickers):
    for ticker in tickers:
        if re.search(rf"\b{re.escape(ticker)}\b", text):
            return ticker
    return None


def _request_articles(tickers, page_size=100):
    from_date = (datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    params = {
        "q": _build_query(tickers),
        "sortBy": "publishedAt",
        "language": "en",
        "pageSize": page_size,
        "searchIn": "title,description",
        "from": from_date,
        "apiKey": _api_key(),
    }

    response = requests.get(NEWS_ENDPOINT, params=params, timeout=REQUEST_TIMEOUT)
    try:
        payload = response.json()
    except ValueError:
        payload = {}

    if response.status_code != 200 or payload.get("status") != "ok":
        code = payload.get("code") or response.status_code
        if code == "rateLimited":
            raise NewsFetchError(
                "NewsAPI daily quota reached (free plan: 100 requests/day, 50 per 12 h). "
                "Cached headlines stay available; try again after the quota resets."
            )
        raise NewsFetchError(f"NewsAPI error {code}: {payload.get('message') or response.reason}")

    articles = []
    for raw in payload.get("articles", []):
        published_at = _parse_published_at(raw.get("publishedAt"))
        if published_at is None:
            continue
        title = raw.get("title") or "Untitled article"
        description = raw.get("description") or ""
        ticker = _match_ticker(f"{title} {description}", tickers)
        if ticker is None:
            continue

        article = {
            "ticker": ticker,
            "title": title,
            "description": description,
            "url": raw.get("url") or "",
            "source": (raw.get("source") or {}).get("name") or "Unknown source",
            "published_at": published_at,
        }
        article["importance_score"] = _score_article(article)
        articles.append(article)
    return articles


def _fetch_live(tickers):
    all_articles = []
    for chunk in _chunk_tickers(tickers):
        all_articles.extend(_request_articles(chunk))

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
    return deduped


def _trim(articles, per_ticker, max_items):
    per_ticker_count = {}
    trimmed = []
    for article in articles:
        ticker = article["ticker"]
        if per_ticker_count.get(ticker, 0) >= per_ticker:
            continue
        per_ticker_count[ticker] = per_ticker_count.get(ticker, 0) + 1
        trimmed.append(article)
        if len(trimmed) >= max_items:
            break
    return trimmed


def fetch_portfolio_news(tickers, per_ticker=8, max_items=20, force=False):
    """Return ranked headlines for the given tickers.

    Served from cache when fresh (or when force=False and a cached copy exists
    within CACHE_TTL); a live request is made otherwise. If the live request
    fails but a cached copy exists, the cached copy is returned and
    last_fetch_info() reports source="stale" with the error. Raises
    NewsFetchError only when nothing at all can be returned.
    """
    key = tuple(_normalize_tickers(tickers))
    if not key:
        _set_info(None, None, None)
        return []
    if not _api_key():
        _set_info("error", "NEWS_API_KEY is not set.", None)
        raise NewsFetchError("NEWS_API_KEY is not set.")

    now = datetime.now(timezone.utc)
    with _lock:
        cached = _cache.get(key)
        if cached and not force and now - cached["fetched_at"] < CACHE_TTL:
            _set_info("cache", None, cached["fetched_at"])
            return _trim(cached["articles"], per_ticker, max_items)

        try:
            articles = _fetch_live(list(key))
        except (requests.RequestException, NewsFetchError) as exc:
            if cached:
                _set_info("stale", str(exc), cached["fetched_at"])
                return _trim(cached["articles"], per_ticker, max_items)
            _set_info("error", str(exc), None)
            raise NewsFetchError(str(exc)) from exc

        _cache[key] = {"articles": articles, "fetched_at": now}
        _set_info("live", None, now)
        return _trim(articles, per_ticker, max_items)
