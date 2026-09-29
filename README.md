# Apothicaire — Risk Management

A Dash application for recording a personal USD portfolio and studying its
performance, diversification, scenarios and news coverage.

## Run locally

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

Copy `.env.example` to `.env` and supply `NEWS_API_KEY` to enable news.
Portfolio and risk pages work without a news key. Sentiment uses a clearly
labeled keyword fallback unless the optional model dependencies are installed;
see [sentiment setup](docs/sentiment.md).

## Pages

- **Portfolio:** account value, holdings, cash, realized/unrealized P&L; validated
  fractional buy/sell records; independent category edits; cash movements;
  searchable tables; quote timestamps; transaction history and allocation.
- **Analytics:** historical model of today's allocation, alpha, beta, Sharpe,
  Sortino and drawdown; separate account returns recorded since opening.
- **Correlations:** common-history correlations, volatility, diversification,
  contributions to portfolio risk and hypothetical shocks.
- **Monte Carlo:** daily-rebalanced simulations with validated covariance and
  bounded memory use; covered holdings and actual history dates are disclosed.
- **News / News Sentiment:** company-aware headlines and per-result scoring
  provenance, with invested-value coverage.
- **Settings:** allocation targets, concentration limit, drift tolerance,
  risk-free assumption and consistent database backups.

History and benchmark controls are shared across analytical pages. Monte Carlo
uses the history setting; its expected-return assumption is separately disclosed.

## Data and migration

Live data resides in `data/portfolio.db` by default. Set `APOTHICAIRE_DB` to use a
different persistent location. Startup copies and backs up an existing legacy
root-level `portfolio.db`; it preserves original rows and records opening
balances rather than inventing past transactions. Operational databases and
backups are excluded from source control.

Opening cash is zero until entered as a deposit. New buys require recorded cash;
sells require an execution price and cannot exceed existing shares. Trades,
cash movements and account valuations are committed atomically. Quote downloads
occur outside write transactions and never change position edit timestamps.

Read the [upgrade and calculation guide](docs/upgrade-guide.md) before relying
on the new account history. It explains migration, accounting assumptions,
coverage, quote freshness and restoration.

## Verification

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
```

Tests use temporary databases and synthetic market data. CI runs the suite on
pushes and pull requests. Optional browser and lint checks:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m ruff check Services pages tests app.py main.py data_base.py publish.py
.\.venv\Scripts\python.exe -B tests/browser_check.py
```

The browser check uses installed Microsoft Edge in headless mode, a temporary
portfolio and offline quotes. Screenshots go to `test-results/`.

## Deployment

`app.py` exports `app` and `server` without starting a development server.
`python publish.py` prepares a clean, timestamped release under `dist/` without
publishing. It excludes secrets and private data by default; `--include-data`
explicitly includes a current SQLite snapshot. Review that directory before
using it as the Plotly Cloud project path.

Configure secrets on the host and provision durable storage for the operational
database. Bundling SQLite in a release does not guarantee persistence or sync
local and cloud edits. Keep off-machine backups. Existing Plotly app identifiers
remain in `plotly-cloud.toml`; this upgrade does not automatically deploy.

## Structure

`pages/` contains Dash layouts and callbacks. `Services/` contains the ledger,
migrations, settings, price cache, performance calculations, quote updater,
news, sentiment and reusable UI components. `schema.sql` is the canonical
schema; `data_base.py` and the legacy cleanup entry point use safe migrations.
