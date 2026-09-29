"""Headline sentiment scoring for portfolio holdings.

Turns the news headlines already fetched by Services.news into a signed
sentiment score per headline, then aggregates those into one score per
ticker. Nothing here touches the network except the one-time model
download that Hugging Face performs on first use.

WHY THIS MODEL
--------------
The default is ProsusAI/finbert, a BERT model fine-tuned on financial
text (Reuters TRC2 headlines plus the Financial PhraseBank). It matters
for two reasons:

1. Vocabulary. In general English "the company missed estimates" is a
   mildly negative sentence. In finance it is a strong sell signal.
   General-purpose sentiment models trained on product reviews and
   tweets have not learned that mapping.

2. A neutral class. Most financial headlines are factual, not
   opinionated: "Apple to report Q3 results on Thursday" is neither
   bullish nor bearish. A two-class model has nowhere to put that
   headline, so it is forced into positive or negative and the
   aggregate score becomes noise. FinBERT emits positive / negative /
   neutral, so neutral news correctly contributes about zero.

Set the SENTIMENT_MODEL environment variable to try another checkpoint.
Label handling below is generic, so binary models still work; you just
lose the neutral class. Useful alternatives:

  ProsusAI/finbert                  3-class, financial, the default
  yiyanghkust/finbert-tone          3-class, financial, earnings calls
  mrm8488/distilroberta-finetuned-financial-news-sentiment-analysis
                                    3-class, about 2x faster, a bit weaker

FALLBACK
--------
If torch/transformers are not installed the module degrades to a small
finance keyword lexicon so the page still renders. The backend is always
reported in backend_status() so the UI can say which one produced the
numbers. The lexicon is a placeholder, not a model.
"""

import hashlib
import math
import os
import re
import threading
from datetime import datetime, timezone

DEFAULT_MODEL = "ProsusAI/finbert"
# Headlines are short; 128 word-pieces covers title + description.
MAX_TOKENS = 128
# Weight of a headline halves every this many days in the ticker average.
RECENCY_HALF_LIFE_DAYS = 3.0
# Aggregate score (-100..100) beyond which a ticker is called bullish/bearish.
BULLISH_CUTOFF = 15.0
BEARISH_CUTOFF = -15.0
# Cap on the in-process score cache.
MAX_CACHE_ENTRIES = 4000


class SentimentUnavailable(Exception):
    """Raised when no backend at all can score text."""


_model_lock = threading.Lock()
_pipeline = None
_load_error = None
_load_attempted = False

_cache = {}
_cache_lock = threading.Lock()


# --------------------------------------------------------------------------
# Backend loading
# --------------------------------------------------------------------------


def model_name():
    """Read lazily so a .env loaded after import is still respected."""
    return os.getenv("SENTIMENT_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL


def _load_pipeline():
    """Build the transformers pipeline once. Returns None if unavailable.

    The first call downloads the weights (about 420 MB for finbert) into
    the Hugging Face cache, usually ~/.cache/huggingface. Later calls,
    and later app restarts, read from that cache and take about a second.
    """
    global _pipeline, _load_error, _load_attempted

    with _model_lock:
        if _load_attempted:
            return _pipeline
        _load_attempted = True
        try:
            from transformers import (
                AutoModelForSequenceClassification,
                AutoTokenizer,
                pipeline,
            )
        except Exception as exc:
            _load_error = (
                "transformers/torch not installed. Run: pip install "
                "transformers torch  ({})".format(exc)
            )
            return None

        try:
            name = model_name()
            tokenizer = AutoTokenizer.from_pretrained(name)
            model = AutoModelForSequenceClassification.from_pretrained(name)
            model.eval()
            _pipeline = pipeline(
                "text-classification",
                model=model,
                tokenizer=tokenizer,
                # Return every class, not just the winner, so we can build a
                # continuous score instead of a hard label.
                top_k=None,
                truncation=True,
                max_length=MAX_TOKENS,
                device=-1,  # CPU. Set to 0 if you have a CUDA GPU.
            )
        except Exception as exc:
            _load_error = "Could not load '{}': {}".format(model_name(), exc)
            _pipeline = None
        return _pipeline


def warm_up():
    """Load the model now rather than on the first user request."""
    return _load_pipeline() is not None


def backend_status():
    """What is actually scoring text right now, for display in the UI."""
    loaded = _pipeline is not None
    return {
        "backend": "transformers" if loaded else "lexicon",
        "model": model_name() if loaded else "finance keyword lexicon",
        "loaded": loaded,
        "attempted": _load_attempted,
        "error": _load_error,
    }


def describe_backend():
    status = backend_status()
    if status["backend"] == "transformers":
        return "Scored by {} running locally on CPU.".format(status["model"])
    reason = status["error"] or "model not loaded yet"
    return "Scored by the keyword fallback, not a model. Reason: {}".format(reason)


# --------------------------------------------------------------------------
# Label normalisation
# --------------------------------------------------------------------------

_POSITIVE_TOKENS = ("positive", "pos", "bullish", "optimistic")
_NEGATIVE_TOKENS = ("negative", "neg", "bearish", "pessimistic")
_NEUTRAL_TOKENS = ("neutral", "neu", "none")


def _normalize_label(raw_label):
    """Map a checkpoint's own label name onto positive/negative/neutral.

    Different Hugging Face models name their classes differently:
    finbert uses positive/negative/neutral, many others emit LABEL_0 and
    LABEL_1. For the LABEL_n form we assume the common ordering
    0=negative, 1=positive, 2=neutral, which matches almost every binary
    sentiment checkpoint on the Hub.
    """
    label = str(raw_label).strip().lower()
    if label in _NEUTRAL_TOKENS or "neutral" in label:
        return "neutral"
    if any(token in label for token in _POSITIVE_TOKENS):
        return "positive"
    if any(token in label for token in _NEGATIVE_TOKENS):
        return "negative"

    match = re.fullmatch(r"label[_\- ]?(\d+)", label)
    if match:
        return {0: "negative", 1: "positive", 2: "neutral"}.get(int(match.group(1)), "neutral")
    return "neutral"


def _probabilities_from_pipeline(result):
    """Collapse a pipeline result into a positive/negative/neutral dict."""
    scores = {"positive": 0.0, "negative": 0.0, "neutral": 0.0}
    rows = result if isinstance(result, list) else [result]
    for row in rows:
        scores[_normalize_label(row.get("label"))] += float(row.get("score", 0.0))

    total = sum(scores.values())
    if total > 0:
        scores = {key: value / total for key, value in scores.items()}
    return scores


# --------------------------------------------------------------------------
# Keyword fallback
# --------------------------------------------------------------------------

_LEXICON_POSITIVE = {
    "beat",
    "beats",
    "surge",
    "surged",
    "soar",
    "soared",
    "rally",
    "rallies",
    "gain",
    "gains",
    "jump",
    "jumped",
    "upgrade",
    "upgraded",
    "outperform",
    "record",
    "strong",
    "growth",
    "profit",
    "raises",
    "raised",
    "approval",
    "approved",
    "wins",
    "win",
    "expands",
    "boost",
    "boosted",
    "buyback",
    "dividend",
    "optimistic",
    "bullish",
    "tops",
    "exceeded",
    "rebound",
}
_LEXICON_NEGATIVE = {
    "miss",
    "misses",
    "missed",
    "plunge",
    "plunged",
    "slump",
    "slumped",
    "fall",
    "falls",
    "fell",
    "drop",
    "drops",
    "dropped",
    "downgrade",
    "downgraded",
    "underperform",
    "weak",
    "loss",
    "losses",
    "cuts",
    "cut",
    "lawsuit",
    "probe",
    "investigation",
    "recall",
    "delay",
    "delayed",
    "warns",
    "warning",
    "bearish",
    "decline",
    "declines",
    "layoff",
    "layoffs",
    "fraud",
    "halt",
    "halted",
    "sued",
    "bankruptcy",
}


def _lexicon_probabilities(text):
    words = re.findall(r"[a-z]+", (text or "").lower())
    positive = sum(1 for word in words if word in _LEXICON_POSITIVE)
    negative = sum(1 for word in words if word in _LEXICON_NEGATIVE)
    hits = positive + negative
    if hits == 0:
        return {"positive": 0.0, "negative": 0.0, "neutral": 1.0}

    # Confidence grows with the number of hits but never reaches certainty.
    confidence = min(0.35 + 0.2 * hits, 0.9)
    positive_share = positive / hits
    return {
        "positive": confidence * positive_share,
        "negative": confidence * (1 - positive_share),
        "neutral": 1 - confidence,
    }


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------


def _cache_key(text, backend=None):
    digest = hashlib.sha1(text.encode("utf-8", "ignore")).hexdigest()
    backend = backend or ("hf" if _pipeline is not None else "lex")
    return "{}:{}:{}".format(backend, model_name(), digest)


def _finalize(probabilities, backend="lex"):
    """Attach the derived fields every caller wants."""
    positive = probabilities["positive"]
    negative = probabilities["negative"]
    neutral = probabilities["neutral"]

    # The signed score. Neutral probability deliberately does not appear:
    # a headline the model calls 90% neutral lands near zero on its own.
    net = positive - negative
    label = max(probabilities, key=probabilities.get)
    return {
        "backend": backend,
        "model": model_name() if backend == "hf" else "finance keyword lexicon",
        "positive": positive,
        "negative": negative,
        "neutral": neutral,
        "net": net,
        "score": net * 100.0,
        "label": label,
        "confidence": probabilities[label],
    }


def score_texts(texts):
    """Score a list of strings. Returns one dict per input, same order.

    Uses the transformers pipeline when it loads, the keyword lexicon
    otherwise. Repeated texts are served from an in-process cache so
    re-rendering the page costs nothing.
    """
    global _load_error

    texts = [(text or "").strip() for text in texts]
    if not texts:
        return []

    _load_pipeline()

    results = [None] * len(texts)
    pending_indices = []
    pending_texts = []

    with _cache_lock:
        for index, text in enumerate(texts):
            if not text:
                results[index] = _finalize({"positive": 0.0, "negative": 0.0, "neutral": 1.0})
                continue
            cached = _cache.get(_cache_key(text))
            if cached is not None:
                results[index] = cached
            else:
                pending_indices.append(index)
                pending_texts.append(text)

    if pending_texts:
        if _pipeline is not None:
            try:
                raw = _pipeline(pending_texts, batch_size=8)
            except Exception as exc:  # inference failed; fall back per text
                _load_error = "Inference failed: {}".format(exc)
                raw = None
            if raw is not None:
                for offset, result in enumerate(raw):
                    probabilities = _probabilities_from_pipeline(result)
                    results[pending_indices[offset]] = _finalize(probabilities, backend="hf")

        for offset, text in enumerate(pending_texts):
            index = pending_indices[offset]
            if results[index] is None:
                results[index] = _finalize(_lexicon_probabilities(text))

        with _cache_lock:
            if len(_cache) > MAX_CACHE_ENTRIES:
                _cache.clear()
            for offset, text in enumerate(pending_texts):
                scored = results[pending_indices[offset]]
                _cache[_cache_key(text, scored["backend"])] = scored

    return results


def article_text(article):
    """The exact string handed to the model, so the UI can show it."""
    title = (article.get("title") or "").strip()
    description = (article.get("description") or "").strip()
    if description and description.lower() not in title.lower():
        return "{}. {}".format(title, description)
    return title


def describe_scores(articles):
    counts = {"hf": 0, "lex": 0}
    for article in articles:
        counts[article["sentiment"].get("backend", "lex")] += 1
    return f"Scoring: {counts['hf']} model results; {counts['lex']} keyword fallback results."


def _title_fingerprint(article):
    """Loose key for spotting the same story republished elsewhere."""
    title = (article.get("title") or "").lower()
    # Many outlets append " - Publisher" to the headline; drop it.
    title = re.split(r"\s+[-|]\s+", title)[0]
    return re.sub(r"[^a-z0-9]+", " ", title).strip()


def dedupe_articles(articles):
    """Drop syndicated repeats of the same headline.

    Services.news already de-duplicates on URL, but wire stories are
    republished under different URLs with an identical title. That does
    not matter for a news feed, where it is merely repetitive, but it
    badly skews a sentiment average: one strongly negative wire story
    carried by four outlets would count four times. The copy kept is the
    one the news module ranked highest, since the list arrives sorted.
    """
    seen = set()
    unique = []
    for article in articles or []:
        fingerprint = (article.get("ticker"), _title_fingerprint(article))
        if not fingerprint[1] or fingerprint in seen:
            continue
        seen.add(fingerprint)
        unique.append(article)
    return unique


def score_articles(articles):
    """Copy of each article with a sentiment key and model_input added."""
    articles = list(articles or [])
    if not articles:
        return []

    texts = [article_text(article) for article in articles]
    scores = score_texts(texts)

    scored = []
    for article, text, sentiment in zip(articles, texts, scores):
        item = dict(article)
        item["model_input"] = text
        item["sentiment"] = sentiment
        scored.append(item)
    return scored


# --------------------------------------------------------------------------
# Aggregation
# --------------------------------------------------------------------------


def _recency_weight(published_at, now=None):
    """Exponential decay so last week's news cannot dominate today's."""
    if not isinstance(published_at, datetime):
        return 1.0
    now = now or datetime.now(timezone.utc)
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)
    age_days = max((now - published_at).total_seconds() / 86400.0, 0.0)
    return math.pow(0.5, age_days / RECENCY_HALF_LIFE_DAYS)


def _importance_weight(article):
    """Let the news module's own impact score nudge the average."""
    return 1.0 + min(article.get("importance_score", 0) or 0, 10) / 10.0


def classify(score):
    if score >= BULLISH_CUTOFF:
        return "Bullish"
    if score <= BEARISH_CUTOFF:
        return "Bearish"
    return "Neutral"


def aggregate_by_ticker(scored_articles, now=None):
    """One weighted sentiment score per ticker.

    Each headline contributes its net score, weighted by how recent it is
    and how important the news module judged it. The result is a
    weighted mean on the same -100..100 scale as a single headline, so
    the two are directly comparable.
    """
    now = now or datetime.now(timezone.utc)
    buckets = {}

    for article in scored_articles or []:
        ticker = article.get("ticker")
        sentiment = article.get("sentiment")
        if not ticker or not sentiment:
            continue

        weight = _recency_weight(article.get("published_at"), now) * _importance_weight(article)
        bucket = buckets.setdefault(
            ticker,
            {
                "ticker": ticker,
                "weighted_sum": 0.0,
                "weight_total": 0.0,
                "headlines": 0,
                "positive": 0,
                "negative": 0,
                "neutral": 0,
                "latest": None,
                "top_headline": None,
                "top_abs": -1.0,
            },
        )

        bucket["weighted_sum"] += weight * sentiment["score"]
        bucket["weight_total"] += weight
        bucket["headlines"] += 1
        bucket[sentiment["label"]] += 1

        published_at = article.get("published_at")
        if isinstance(published_at, datetime) and (
            bucket["latest"] is None or published_at > bucket["latest"]
        ):
            bucket["latest"] = published_at

        # Remember the single most opinionated headline to explain the score.
        if abs(sentiment["score"]) > bucket["top_abs"]:
            bucket["top_abs"] = abs(sentiment["score"])
            bucket["top_headline"] = article

    rows = []
    for bucket in buckets.values():
        total = bucket["weight_total"]
        score = bucket["weighted_sum"] / total if total > 0 else 0.0
        rows.append(
            {
                "ticker": bucket["ticker"],
                "score": score,
                "label": classify(score),
                "headlines": bucket["headlines"],
                "positive": bucket["positive"],
                "negative": bucket["negative"],
                "neutral": bucket["neutral"],
                "latest": bucket["latest"],
                "top_headline": bucket["top_headline"],
            }
        )

    rows.sort(key=lambda row: row["score"], reverse=True)
    return rows


def portfolio_score(ticker_rows, weights=None):
    """Blend per-ticker scores into one number for the whole portfolio.

    Pass weights={'AAPL': 12.5, ...} in percent to weight each ticker by
    its share of portfolio value. Without weights every ticker counts
    the same, which overstates small positions.
    """
    rows = [row for row in ticker_rows or [] if row.get("headlines")]
    if not rows:
        return None

    if weights:
        numerator = 0.0
        denominator = 0.0
        for row in rows:
            weight = float(weights.get(row["ticker"], 0.0) or 0.0)
            if weight <= 0:
                continue
            numerator += weight * row["score"]
            denominator += weight
        if denominator > 0:
            return numerator / denominator

    return sum(row["score"] for row in rows) / len(rows)
