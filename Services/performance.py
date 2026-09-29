import numpy as np
import pandas as pd

TRADING_DAYS = 252
ANNUAL_RISK_FREE_RATE = 0.04
BENCHMARK_ANNUAL_RETURN = 0.08
DRIFT_SHRINKAGE = 0.5
MAX_ANNUAL_DRIFT = 0.20
MIN_ANNUAL_DRIFT = -0.20


def compute_returns(prices):
    return prices.pct_change(fill_method=None).replace([np.inf, -np.inf], np.nan).dropna()


def compute_portfolio_returns(returns, weights):
    return returns.mul(weights.reindex(returns.columns, fill_value=0)).sum(
        axis=1, min_count=len(returns.columns)
    )


def compute_ttwr(portfolio_returns):
    return (
        None
        if portfolio_returns is None or portfolio_returns.empty
        else (1 + portfolio_returns).prod() - 1
    )


def drawdowns(returns):
    wealth = (1 + returns).cumprod()
    return wealth / wealth.cummax().clip(lower=1) - 1


def compute_performance_metrics(
    portfolio_returns, benchmark_returns, risk_free=ANNUAL_RISK_FREE_RATE
):
    paired = (
        pd.concat(
            [portfolio_returns.rename("p"), benchmark_returns.rename("b")], axis=1, join="inner"
        )
        .replace([np.inf, -np.inf], np.nan)
        .dropna()
        .sort_index()
    )
    if len(paired) < 2:
        return dict.fromkeys(["sharpe", "sortino", "beta", "alpha", "max_drawdown"])
    daily_rf = np.expm1(np.log1p(risk_free) / TRADING_DAYS)
    excess = paired.p - daily_rf
    annual_excess = excess.mean() * TRADING_DAYS
    vol = paired.p.std() * np.sqrt(TRADING_DAYS)
    downside = np.sqrt(np.mean(np.minimum(excess, 0) ** 2)) * np.sqrt(TRADING_DAYS)
    variance = paired.b.var()
    beta = paired.p.cov(paired.b) / variance if variance > 1e-20 else None
    alpha = (
        (excess.mean() - beta * (paired.b - daily_rf).mean()) * TRADING_DAYS
        if beta is not None
        else None
    )
    return dict(
        sharpe=annual_excess / vol if vol > 0 else None,
        sortino=annual_excess / downside if downside > 0 else None,
        beta=beta,
        alpha=alpha,
        max_drawdown=drawdowns(paired.p).min(),
    )


def valid_covariance(returns):
    complete = returns.replace([np.inf, -np.inf], np.nan).dropna()
    if len(complete) < 2 or complete.shape[1] == 0:
        raise ValueError("At least two common observations are required.")
    cov = complete.cov().to_numpy(float)
    eigenvalues, eigenvectors = np.linalg.eigh((cov + cov.T) / 2)
    if eigenvalues.min() < -1e-10:
        raise ValueError("Invalid covariance matrix.")
    return (eigenvectors * np.maximum(eigenvalues, 0)) @ eigenvectors.T


def risk_contributions(returns, weights):
    cov = valid_covariance(returns)
    w = weights.reindex(returns.columns).to_numpy(float)
    variance = float(w @ cov @ w)
    if variance <= 0:
        return pd.Series(0.0, index=returns.columns)
    return pd.Series(w * (cov @ w) / variance, index=returns.columns)


def portfolio_growth(log_returns, weights):
    return np.exp(log_returns) @ np.asarray(weights)


def simulate_paths(returns, weights, initial_value, years, simulations, seed=42):
    if not np.isfinite(initial_value) or initial_value <= 0:
        raise ValueError("Modeled starting value must be positive and finite.")
    years, simulations = int(years), int(simulations)
    if years not in (1, 3, 5) or simulations not in (500, 1000, 5000, 10000):
        raise ValueError("Unsupported simulation size.")
    complete = returns.replace([np.inf, -np.inf], np.nan).dropna()
    covariance = valid_covariance(complete)
    # Shrink annual arithmetic expected returns, then convert to log drift.
    arithmetic = np.expm1(complete).mean() * TRADING_DAYS
    expected = (
        (DRIFT_SHRINKAGE * arithmetic + (1 - DRIFT_SHRINKAGE) * BENCHMARK_ANNUAL_RETURN)
        .clip(MIN_ANNUAL_DRIFT, MAX_ANNUAL_DRIFT)
        .to_numpy()
    )
    mean = np.log1p(expected) / TRADING_DAYS - 0.5 * np.diag(covariance)
    w = weights.reindex(complete.columns).to_numpy(float)
    if not np.isfinite(w).all() or (w < 0).any() or not np.isclose(w.sum(), 1):
        raise ValueError("Simulation weights must be nonnegative and total 100%.")
    steps = years * TRADING_DAYS
    values = np.empty((steps + 1, simulations))
    values[0] = initial_value
    rng = np.random.default_rng(seed)
    for start in range(0, simulations, 250):
        stop = min(start + 250, simulations)
        samples = rng.multivariate_normal(
            mean, covariance, size=(steps, stop - start), check_valid="raise"
        )
        growth = portfolio_growth(samples, w)
        values[1:, start:stop] = initial_value * np.cumprod(growth, axis=0)
    return np.arange(steps + 1) / TRADING_DAYS, values
