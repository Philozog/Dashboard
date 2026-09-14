"""Decision helpers for the Portfolio page: allocation drift, rebalance
actions and plain-English takeaways. Pure functions over the holdings
DataFrame returned by Services.helper.load_data() — no I/O here.
"""
import pandas as pd


# Percent of portfolio value each holding type should hold.
ALLOCATION_TARGETS = {"Core": 60, "High Conviction": 30, "Moonshot": 10}
# Drift smaller than this (percentage points) is left alone.
DRIFT_TOLERANCE_PTS = 5
# Single-name weight above which we flag concentration risk.
CONCENTRATION_LIMIT_PCT = 25
# Unrealized gain/loss on cost that triggers a suggestion.
TRIM_GAIN_PCT = 50
REVIEW_LOSS_PCT = -20
# Return correlation above which two names are treated as one position.
CORRELATION_ALERT = 0.7

NUMERIC_COLUMNS = ["shares", "avg_price", "current_price", "market_value", "Total_Profit_Loss"]


def prepare_holdings(df):
    """Numeric view of load_data() output: no TOTAL row, weight and P&L %."""
    columns = ["ticker", "holding_type", *NUMERIC_COLUMNS, "weight_pct", "pnl_pct"]
    if df is None or df.empty:
        return pd.DataFrame(columns=columns)

    out = df.copy()
    out["ticker"] = out["ticker"].fillna("").astype(str).str.strip().str.upper()
    out = out[(out["ticker"] != "") & (out["ticker"] != "TOTAL")]
    for column in NUMERIC_COLUMNS:
        out[column] = pd.to_numeric(out.get(column), errors="coerce").fillna(0.0)
    if "holding_type" not in out.columns:
        out["holding_type"] = None
    out["holding_type"] = out["holding_type"].fillna("Unassigned").replace("", "Unassigned")

    total = out["market_value"].sum()
    out["weight_pct"] = out["market_value"] / total * 100 if total > 0 else 0.0
    cost = out["avg_price"] * out["shares"]
    out["pnl_pct"] = (out["Total_Profit_Loss"] / cost * 100).where(cost > 0, 0.0)
    return out[columns].reset_index(drop=True)


def rebalance_plan(holdings):
    """One row per target bucket: current vs target and the trade that closes the gap."""
    total = float(holdings["market_value"].sum()) if not holdings.empty else 0.0
    by_type = holdings.groupby("holding_type")["market_value"].sum() if total > 0 else pd.Series(dtype=float)

    rows = []
    for bucket, target_pct in ALLOCATION_TARGETS.items():
        current_value = float(by_type.get(bucket, 0.0))
        current_pct = current_value / total * 100 if total > 0 else 0.0
        gap_pct = current_pct - target_pct
        gap_value = total * gap_pct / 100

        if total <= 0:
            status, action = "ok", "No holdings"
        elif abs(gap_pct) <= DRIFT_TOLERANCE_PTS:
            status, action = "ok", "On target"
        elif gap_pct > 0:
            status, action = "over", f"Trim ~${abs(gap_value):,.0f}"
        else:
            status, action = "under", f"Add ~${abs(gap_value):,.0f}"

        rows.append({
            "bucket": bucket,
            "current_pct": current_pct,
            "target_pct": target_pct,
            "gap_pct": gap_pct,
            "gap_value": gap_value,
            "status": status,
            "action": action,
        })

    unassigned_value = float(by_type.drop(labels=list(ALLOCATION_TARGETS), errors="ignore").sum())
    if unassigned_value > 0:
        pct = unassigned_value / total * 100
        rows.append({
            "bucket": "Unassigned",
            "current_pct": pct,
            "target_pct": 0,
            "gap_pct": pct,
            "gap_value": unassigned_value,
            "status": "warn",
            "action": "Assign a type",
        })
    return rows


def correlated_pairs(returns, threshold=CORRELATION_ALERT):
    """(ticker_a, ticker_b, corr) for every pair above threshold, strongest first."""
    if returns is None or returns.empty or returns.shape[1] < 2:
        return []
    corr = returns.corr()
    pairs = []
    columns = list(corr.columns)
    for i, left in enumerate(columns):
        for right in columns[i + 1:]:
            value = float(corr.at[left, right])
            if pd.notna(value) and value >= threshold:
                pairs.append((left, right, value))
    pairs.sort(key=lambda item: item[2], reverse=True)
    return pairs


def takeaways(holdings, rebalance_rows=None, pairs=None, headline=None):
    """List of (level, text) bullets. level is one of alert / warn / good / info."""
    if holdings.empty:
        return [("info", "Add holdings above to get takeaways.")]

    items = []

    top = holdings.sort_values("weight_pct", ascending=False).iloc[0]
    if top["weight_pct"] > CONCENTRATION_LIMIT_PCT:
        items.append((
            "alert",
            f"{top['ticker']} is {top['weight_pct']:.0f}% of the portfolio — above your "
            f"{CONCENTRATION_LIMIT_PCT}% concentration line.",
        ))
    else:
        items.append((
            "good",
            f"No single position above {CONCENTRATION_LIMIT_PCT}% — largest is "
            f"{top['ticker']} at {top['weight_pct']:.0f}%.",
        ))

    rows = rebalance_rows if rebalance_rows is not None else rebalance_plan(holdings)
    off_target = [row for row in rows if row["status"] in ("over", "under")]
    if off_target:
        worst = max(off_target, key=lambda row: abs(row["gap_pct"]))
        direction = "over" if worst["gap_pct"] > 0 else "under"
        items.append((
            "warn",
            f"{worst['bucket']} is {abs(worst['gap_pct']):.0f} pts {direction} its "
            f"{worst['target_pct']}% target — {len(off_target)} rebalance action"
            f"{'s' if len(off_target) != 1 else ''} below.",
        ))
    else:
        items.append(("good", f"Allocation is within {DRIFT_TOLERANCE_PTS} pts of target in every bucket."))

    winners = holdings[holdings["pnl_pct"] >= TRIM_GAIN_PCT]
    if not winners.empty:
        best = winners.sort_values("pnl_pct", ascending=False).iloc[0]
        items.append((
            "info",
            f"{best['ticker']} is up {best['pnl_pct']:.0f}% on cost "
            f"(${best['Total_Profit_Loss']:,.0f}) — consider locking in some gains.",
        ))

    losers = holdings[holdings["pnl_pct"] <= REVIEW_LOSS_PCT]
    if not losers.empty:
        worst = losers.sort_values("pnl_pct").iloc[0]
        items.append((
            "warn",
            f"{worst['ticker']} is down {abs(worst['pnl_pct']):.0f}% on cost — "
            "review the thesis or the position size.",
        ))

    if pairs:
        left, right, value = pairs[0]
        items.append((
            "warn",
            f"{left} and {right} move together (correlation {value:.2f}) — "
            "for risk they behave like one position.",
        ))

    if headline:
        items.append(("info", f"Top headline — {headline['ticker']}: {headline['title']}"))

    return items
