# Apothicaire: account records and risk calculations

## Existing holdings

The operational database is now `data/portfolio.db`, or the absolute path in
`APOTHICAIRE_DB`. On first startup, an existing root-level `portfolio.db` is
copied with SQLite's backup API. The original remains untouched. Before a
migration, another backup is saved under the operational database's `backups/`
directory. The old positions table remains as `portfolio_legacy` inside the
migrated database.

Duplicate tickers are normalized and combined by summing shares and cost basis;
the most recent available positive quote is retained. Invalid or unnamed
holdings stop migration instead of being discarded. A unique ticker constraint
prevents new duplicates. Schema versions are recorded in `PRAGMA user_version`.

Existing positions become **opening balances**, dated when the ledger starts.
Their original purchase dates, prior sales, deposits, dividends and fees are
unknown. No historical transactions are fabricated. Opening cash is zero: record
the actual cash available as a deposit before recording new purchases.

## Using the Portfolio page

- Record buys and sells using quantity, execution price and optional fees.
  Fractional shares are supported. Purchases require recorded cash; sales cannot
  exceed the shares held. Invalid operations roll back and show a message.
- Use **Update type** to change an existing holding's category without a trade.
- Record deposits, withdrawals, dividends and fees under **Cash movements**.
- Realized P&L uses average cost, with purchase fees included in cost basis and
  sale fees deducted from proceeds. It is not a tax-lot report.
- Transaction history is append-only through the UI. It begins at migration;
  imported positions do not imply that previous realized P&L was zero.
- The holdings table stores numbers as numbers and supports sorting and filters.
- Quote time is the actual market observation timestamp, distinct from position
  edit time and the last refresh attempt. Unverified or older prices are labeled.
  A closed market can legitimately leave older quotes on screen.

## Analytics and risk assumptions

The shared history selector applies to Analytics, Correlations and Monte Carlo.
The benchmark selector applies to Analytics and Correlations; Monte Carlo's
8% shrinkage assumption is separate from that comparison benchmark.

Historical adjusted prices come from one cached service. Missing prices are not
forward-filled. Holdings need at least 30 valid returns, and displayed estimates
need at least 30 common observations. Each page reports actual dates, excluded
holdings and invested-value coverage. These models exclude cash and renormalize
the covered holdings to 100%; they do not represent uncovered positions.

**Current allocation return** is a historical model of today's invested weights,
rebalanced daily. It is not the realized performance of the account. Alpha is
the daily excess-return regression intercept, annualized arithmetically using
252 trading days. Sharpe uses daily excess returns. Sortino uses the root mean
square shortfall below the daily risk-free target across all observations.
Drawdown includes the initial investment before the first return.

**Recorded account return** links observed portfolio valuations, including cash.
Deposits and withdrawals are excluded using a pre-flow valuation immediately
before each recorded flow. Dividends and fees affect returns. Observations occur
on quote refreshes and transactions, not through a continuously running market
feed. Stale quotes or missing activity will affect this account return. Earlier
history cannot be reconstructed from the original positions-only database.

**Monte Carlo** uses aligned log-return histories and a validated covariance
matrix. Annual arithmetic expected returns are shrunk 50% toward 8%, capped at
-20% and +20%, then converted to daily log drift. Each simulated day's asset
simple returns are combined at fixed portfolio weights (daily rebalancing).
Paths run in batches of 250 with a fixed seed for repeatability. The displayed
starting value is the value of the covered holdings, not the entire account.
The normal-return model does not capture all crash risks or regime changes.

**Risk contribution** reports each holding's share of modeled portfolio variance.
The market shock scenario uses historical beta and covered invested value. The
holding-type scenario directly shocks all positions in the selected category.
These are separate scenarios, not combined forecasts or probabilities.

## Settings, news and sentiment

Risk-free rate, allocation targets, concentration limit and drift tolerance are
saved under Settings. Targets must sum to 100%. History and benchmark preferences
are remembered in the browser. All monetary values assume one USD account;
foreign-currency conversion and corporate-action ledger adjustments are not
automatically performed.

News queries use symbols plus explicit company aliases in `Services/news.py`.
Short symbols require stronger matching to avoid ordinary-word collisions. One
story can be associated with several holdings and is deduplicated per holding.
Company matching is still a heuristic; extend the alias map for other holdings.

Each sentiment result records its actual backend. A failed model inference can
fall back to keywords without being cached or labeled as a model result.
Portfolio sentiment is labeled as applying only to covered holdings, with the
percentage of invested value covered displayed beside it. Model dependencies
are optional in `requirements-sentiment.txt`; the default installation uses the
keyword fallback unless the model libraries and weights are available.

## Backups and deployment

Create a consistent SQLite backup from Settings. Keep off-machine copies too.
To restore, stop the app and set `APOTHICAIRE_DB` to a copied backup, then restart.
Never overwrite an active database. The old root database is a preserved legacy
copy and is no longer the live database.

`python publish.py` prepares a clean release directory without secrets, caches,
tests or portfolio data. Add `--include-data` only when intentionally including
a current snapshot of private account data. It does not publish anything.
Configure `NEWS_API_KEY` and a durable `APOTHICAIRE_DB` path in the hosting
environment. A bundled SQLite snapshot is not synchronization or a persistence
guarantee: verify durable storage before relying on cloud edits. Local and cloud
databases are independent unless you deliberately provision shared storage.

The source changes have not been published to Plotly Cloud. Publishing is a
separate deployment step; use the reviewed release directory, not the entire
development workspace.

## Verification

Run `python -B -m unittest discover -s tests -v`. These tests use temporary
databases and synthetic market data. CI runs the suite on pushes and PRs.

Optional browser verification: install `requirements-dev.txt`, then run
`python -B tests/browser_check.py`. It uses installed headless Microsoft Edge,
an isolated temporary portfolio and offline quotes. Screenshots are saved under
`test-results/`, which is excluded from Git and release packages.
