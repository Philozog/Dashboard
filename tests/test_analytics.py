import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

with patch("dash.register_page"):
    from pages import analytics


class AlphaTests(unittest.TestCase):
    def setUp(self):
        self.market = pd.Series(
            [-0.02, 0.01, 0.005, -0.008, 0.015],
            index=pd.date_range("2026-01-05", periods=5),
        )

    def test_benchmark_has_zero_alpha(self):
        metrics = analytics.compute_performance_metrics(self.market, self.market)
        self.assertAlmostEqual(metrics["beta"], 1)
        self.assertAlmostEqual(metrics["alpha"], 0)

    def test_known_regression_intercept(self):
        daily_rf = (1.04 ** (1 / 252)) - 1
        portfolio = daily_rf + 1.5 * (self.market - daily_rf) + 0.0002
        metrics = analytics.compute_performance_metrics(portfolio, self.market)
        self.assertAlmostEqual(metrics["beta"], 1.5)
        self.assertAlmostEqual(metrics["alpha"], 0.0504)

    def test_alignment_and_invalid_observations(self):
        portfolio = self.market.copy()
        portfolio.iloc[0] = np.inf
        portfolio.iloc[1] = np.nan
        metrics = analytics.compute_performance_metrics(portfolio, self.market.iloc[::-1])
        self.assertAlmostEqual(metrics["beta"], 1)
        self.assertAlmostEqual(metrics["alpha"], 0)

    def test_undefined_beta_has_no_alpha(self):
        flat = pd.Series(0.0, index=self.market.index)
        self.assertIsNone(analytics.compute_performance_metrics(self.market, flat)["alpha"])
        self.assertIsNone(
            analytics.compute_performance_metrics(self.market[:1], self.market[:1])["alpha"]
        )

    def test_missing_prices_are_not_forward_filled(self):
        prices = pd.Series([100, np.nan, 110, 121])
        returns = analytics.compute_returns(prices)
        self.assertEqual(returns.index.tolist(), [3])
        self.assertAlmostEqual(returns.iloc[0], 0.1)

    def test_spy_holding_remains_in_portfolio(self):
        prices = pd.DataFrame(
            {"SPY": 100 * np.cumprod(1 + np.sin(np.arange(41)) * 0.01)},
            index=pd.date_range("2026-01-01", periods=41),
        )
        holdings = pd.DataFrame({"ticker": ["SPY"], "market_value": [1000]})
        with (
            patch.object(analytics, "load_data", return_value=holdings),
            patch.object(analytics, "get_historical_prices", return_value=prices),
            patch.object(analytics, "get_settings", return_value={"risk_free": 0.04}),
        ):
            result = analytics.update_analytics("/analytics")
        self.assertEqual(result[4], "1.00")
        self.assertAlmostEqual(float(result[5].rstrip("%")), 0)


if __name__ == "__main__":
    unittest.main()
