# News Sentiment: how it works

This page scores the tone of recent news about your holdings and rolls it
up per ticker. This document explains the machine-learning part, the
choices made, and where the whole thing can mislead you.

---

## 1. Why the original model was the wrong pick

The scratch script used `syedkhalid076/RoBERTa-Sentimental-Analysis-v1`:
a general-purpose model with two classes, negative and positive. Two
problems make it a poor fit for financial headlines.

**It has no neutral class.** Most financial news is factual, not
opinionated. "Microsoft to report third quarter results on Thursday"
carries no view at all. A two-class model has nowhere to put that
sentence, so softmax still forces out something like 55% positive. Do
that across twenty headlines and your portfolio score becomes a coin-flip
average of noise rather than a signal.

**It learned the wrong vocabulary.** It was trained on reviews and social
posts. In that world "missed" is mildly bad and "shorted" is meaningless.
In markets, "missed estimates" is a strong negative and "heavily shorted"
is loaded. The model never saw enough finance text to learn that mapping.

### What replaced it

`ProsusAI/finbert` is BERT further trained on financial text: Reuters
TRC2 news plus the Financial PhraseBank, a set of sentences hand-labelled
by finance students and researchers. It emits three classes: positive,
negative and neutral.

Measured on the three test sentences in this repo:

| Headline | positive | neutral | negative |
|---|---|---|---|
| Apple beats earnings estimates and raises guidance | 0.90 | 0.05 | 0.05 |
| Tesla shares plunge after regulator opens investigation | 0.01 | 0.07 | 0.92 |
| Microsoft to report third quarter results on Thursday | 0.02 | 0.92 | 0.06 |

The third row is the one that matters. A factual scheduling headline is
correctly parked in neutral and contributes nothing to the score.

You can swap the checkpoint without touching code by setting
`SENTIMENT_MODEL` in `.env`. Two alternatives worth trying:

- `yiyanghkust/finbert-tone`, trained on earnings-call transcripts
- `mrm8488/distilroberta-finetuned-financial-news-sentiment-analysis`,
  roughly twice as fast, slightly less accurate

Label handling is generic, so a two-class checkpoint still runs. You
simply lose the neutral class and the noise comes back.

---

## 2. What actually happens to a headline

### Tokenising

A neural network cannot read characters. The tokenizer converts text into
integers using a fixed vocabulary of roughly 30,000 word-pieces. Rare
words get split: "ASML" might become `as` + `##ml`. Output is padded or
truncated to 128 tokens, which comfortably covers a headline plus its
summary.

### The forward pass

BERT runs twelve transformer layers over those tokens. Each layer lets
every token look at every other token, which is how the model knows that
"not" in "not a good quarter" flips the meaning of "good". A
bag-of-keywords approach cannot do that, which is exactly why the keyword
fallback in this repo is only a stopgap.

The final layer produces three raw numbers called logits, one per class.
Softmax turns them into probabilities that sum to 1.

### From label to score

Keeping only the winning label throws away most of the information. A
headline at 51% positive and one at 97% positive are not the same news.
So instead:

```
net = P(positive) - P(negative)
score = net * 100          # range -100 to +100
```

Neutral probability never appears in the formula, and it does not need
to. If the model says a headline is 92% neutral, then positive and
negative are both small and their difference is near zero on its own.
That is the property a portfolio signal needs, and it is the property the
two-class model could not give you.

---

## 3. From headlines to one number per ticker

Three adjustments turn a pile of headline scores into something usable.

**Deduplication.** Wire stories get republished by several outlets under
different URLs with the same title. The news module de-duplicates on URL,
which is enough for a news feed but not for an average, where four copies
of one bearish story would count four times. Headlines are therefore
de-duplicated again on a normalised title. On live data this moved ASML
from -40.9 to -26.2 and flipped the whole portfolio from -5.6 to +1.3, so
it is not a cosmetic fix.

**Recency weighting.** A headline's weight halves every three days:

```
weight = 0.5 ** (age_in_days / 3)
```

A five-day-old story still counts, at about a third of today's.

**Importance weighting.** `Services/news.py` already scores headlines on
keywords like earnings, lawsuit and merger. That score, capped, adds up
to another 100% of weight, so a guidance cut outweighs a routine analyst
note.

The ticker score is the weighted mean of its headline scores, on the same
-100 to +100 scale, so a ticker and a single headline are directly
comparable. Above +15 is called bullish, below -15 bearish.

The portfolio number weights each ticker by its share of market value.
Equal-weighting would let a 1% position move the headline number as much
as a 37% position.

---

## 4. How the page connects to the rest of the app

```
portfolio.db
     |
     v
Services/helper.load_data()  ->  Services/insights.prepare_holdings()
     |                                     |
     |  tickers                            |  weight_pct, market_value
     v                                     |
Services/news.fetch_portfolio_news()       |
     |  (15-minute cache, shared)          |
     v                                     |
Services/sentiment.score_articles()        |
     |                                     |
     v                                     v
Services/sentiment.aggregate_by_ticker() -> portfolio_score()
     |
     v
pages/sentiment.py
```

Nothing new was added to the data layer. The page reuses:

- **`Services/helper.load_data()`**, the same holdings table the Portfolio
  page edits. Add a ticker there and it appears here on the next load.
- **`Services/insights.prepare_holdings()`**, which supplies `weight_pct`
  and `market_value` for the value-weighted portfolio score and the
  bubble chart.
- **`Services/news.fetch_portfolio_news()`**, the same cached fetch behind
  the Portfolio News page. Both pages share one cache entry per ticker
  set, so opening this page right after that one spends no extra NewsAPI
  quota. This matters: the free plan allows 100 requests a day.
- **`Services/theme.py`** colours, so the charts match every other page.

The only genuinely new module is `Services/sentiment.py`, which is pure
computation over data the app already had.

---

## 5. Cost and caching

The first run downloads about 420 MB of weights to
`~/.cache/huggingface`. After that, loading takes roughly a second and
inference for two dozen headlines is well under a second on CPU. Both
layers are cached:

- the model is a module-level singleton, loaded once per process
- scores are cached by SHA-1 of the input text, so re-rendering, filtering
  and sorting cost nothing

If `torch` and `transformers` are missing, the module falls back to a
small finance keyword lexicon and the status line on the page says so
explicitly. The fallback exists so the page still renders, not because it
is any good.

---

## 6. What this cannot tell you

Read this section before acting on anything the page shows.

**Tone is not valuation.** The model reads how journalists framed a story.
It never sees a price, a multiple or an earnings number. A stock can have
glowing coverage and still be expensive.

**It cannot know what is already priced in.** Good news that the market
anticipated weeks ago still scores positive here.

**Small samples are noisy.** A ticker with two headlines has a far less
reliable score than one with twelve. The headline count is printed on
every card for exactly that reason. Treat anything under about five
headlines as an anecdote.

**Ticker matching is imperfect.** NewsAPI matches symbols as plain words,
so short or ambiguous tickers pull in unrelated articles. On live data a
Micron article was tagged ASML because ASML appeared in its summary.
Always open the headline list before trusting an outlier.

**Sentiment is a context layer.** It belongs next to the Analytics and
Covariance pages as one more input, not as a signal to trade on.

---

## 7. Files

| File | Role |
|---|---|
| `Services/sentiment.py` | Model loading, scoring, dedupe, aggregation. No I/O beyond the model download. |
| `pages/sentiment.py` | The Dash page: layout, three callbacks, two figures. |
| `assets/style.css` | The `.sent-*` block at the end of the file. |
| `docs/sentiment.md` | This document. |

To try a different model:

```bash
# in .env
SENTIMENT_MODEL=yiyanghkust/finbert-tone
```

To reinstall the dependencies from scratch:

```bash
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install transformers
```
