import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
import pandas as pd

from Services import database, ledger, market, news, performance, sentiment, settings, updater


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "portfolio.db"
        database.initialize_database(self.path)

    def test_schema_and_idempotency(self):
        ledger.transact("deposit", amount=100, path=self.path)
        database.initialize_database(self.path)
        self.assertEqual(ledger.account_summary(self.path)["cash"], 100)
        with database.connect(self.path) as conn:
            self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            conn.executescript((database.BASE_DIR / "schema.sql").read_text())

    def test_bad_migration_keeps_original_rows(self):
        old = Path(self.tmp.name) / "invalid.db"
        with sqlite3.connect(old, factory=database.ManagedConnection) as conn:
            conn.execute("CREATE TABLE portfolio(ticker TEXT, shares REAL, avg_price REAL)")
            conn.execute("INSERT INTO portfolio VALUES('',5,100)")
        with self.assertRaises(ValueError):
            database.initialize_database(old)
        with sqlite3.connect(old, factory=database.ManagedConnection) as conn:
            self.assertEqual(conn.execute("SELECT shares FROM portfolio").fetchone()[0], 5)
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 0)

    def test_quotes_use_latest_quantity_and_separate_timestamps(self):
        ledger.transact("deposit", amount=1000, path=self.path)
        ledger.transact(
            "buy", ticker="AAPL", shares=2, price=100, holding_type="Core", path=self.path
        )
        observation = pd.Timestamp("2026-01-05 21:00", tz="UTC")

        def holdings():
            with database.connect(self.path) as conn:
                return pd.read_sql_query("SELECT * FROM portfolio", conn)

        def download(**kwargs):
            # Simulate a trade while the remote price request is in flight.
            ledger.transact("sell", ticker="AAPL", shares=1, price=110, path=self.path)
            return pd.DataFrame({("Close", "AAPL"): [120.0]}, index=[observation])

        with (
            patch.object(updater, "load_data", side_effect=holdings),
            patch.object(updater, "connect", side_effect=lambda: database.connect(self.path)),
            patch.object(updater.yf, "download", side_effect=download) as fetch,
        ):
            self.assertIn("Refreshed 1", updater.update_prices())
            self.assertIn("15 minutes", updater.update_prices())
            self.assertEqual(fetch.call_count, 1)
        with database.connect(self.path) as conn:
            row = conn.execute("SELECT * FROM portfolio").fetchone()
            self.assertEqual(row["shares"], 1)
            self.assertEqual(row["market_value"], 120)
            self.assertEqual(row["quote_updated_at"], observation.isoformat())
            self.assertNotEqual(row["last_updated"], row["quote_updated_at"])

    def test_fractional_buy_sell_and_realized_pnl(self):
        ledger.transact("deposit", amount=1000, path=self.path)
        ledger.transact(
            "buy",
            ticker=" aapl ",
            shares=2.5,
            price=100,
            holding_type="Core",
            fees=5,
            path=self.path,
        )
        ledger.transact("sell", ticker="AAPL", shares=1, price=120, fees=1, path=self.path)
        summary = ledger.account_summary(self.path)
        self.assertAlmostEqual(summary["cash"], 864)
        self.assertAlmostEqual(summary["realized"], 17)
        with database.connect(self.path) as conn:
            row = conn.execute("SELECT * FROM portfolio").fetchone()
            self.assertEqual(row["shares"], 1.5)
            self.assertEqual(row["avg_price"], 102)
            self.assertIsNone(row["quote_updated_at"])

    def test_invalid_trades_roll_back(self):
        ledger.transact("deposit", amount=1000, path=self.path)
        ledger.transact(
            "buy", ticker="AAPL", shares=2, price=100, holding_type="Core", path=self.path
        )
        for kwargs in [
            dict(kind="sell", ticker="AAPL", shares=3, price=100),
            dict(kind="buy", ticker="AAPL", shares=-2, price=100, holding_type="Core"),
            dict(kind="buy", ticker="AAPL", shares=1, price=float("nan"), holding_type="Core"),
            dict(kind="buy", ticker="AAPL", shares=1, price=100, holding_type="Unknown"),
            dict(kind="withdrawal", amount=900),
            dict(kind="buy", ticker="B", shares=20, price=100, holding_type="Core"),
        ]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                ledger.transact(**kwargs, path=self.path)
        self.assertEqual(len(ledger.transaction_history(self.path)), 2)
        self.assertEqual(ledger.account_summary(self.path)["cash"], 800)

    def test_cash_flows_do_not_create_returns(self):
        ledger.transact("deposit", amount=100, path=self.path)
        ledger.transact("deposit", amount=50, path=self.path)
        ledger.transact("withdrawal", amount=20, path=self.path)
        self.assertAlmostEqual(ledger.account_performance(self.path).growth.iloc[-1], 1)
        ledger.transact("dividend", amount=13, path=self.path)
        self.assertAlmostEqual(ledger.account_performance(self.path).growth.iloc[-1], 1.1)

    def test_fee_reduces_return(self):
        ledger.transact("deposit", amount=100, path=self.path)
        ledger.transact("fee", amount=2, path=self.path)
        self.assertAlmostEqual(ledger.account_performance(self.path).growth.iloc[-1], 0.98)

    def test_category_edit_does_not_change_quote_time(self):
        ledger.transact("deposit", amount=100, path=self.path)
        ledger.transact("buy", ticker="A", shares=1, price=10, holding_type="Core", path=self.path)
        ledger.set_holding_type("A", "Moonshot", self.path)
        with database.connect(self.path) as conn:
            row = conn.execute("SELECT * FROM portfolio").fetchone()
            self.assertEqual(row["holding_type"], "Moonshot")
            self.assertIsNone(row["quote_updated_at"])

    def test_backup_preserves_data(self):
        ledger.transact("deposit", amount=100, path=self.path)
        backup = database.backup_database(self.path)
        with sqlite3.connect(backup, factory=database.ManagedConnection) as conn:
            self.assertEqual(
                conn.execute("SELECT SUM(amount) FROM transactions").fetchone()[0], 100
            )

    def test_settings_validation_and_persistence(self):
        settings.save_settings(
            {"Core": 50, "High Conviction": 35, "Moonshot": 15}, 20, 4, 0.03, self.path
        )
        self.assertEqual(settings.get_settings(self.path)["concentration"], 20)
        with self.assertRaises(ValueError):
            settings.save_settings(
                {"Core": 60, "High Conviction": 35, "Moonshot": 15}, 20, 4, 0.03, self.path
            )

    def test_legacy_migration_preserves_duplicates(self):
        old = Path(self.tmp.name) / "old.db"
        with sqlite3.connect(old, factory=database.ManagedConnection) as conn:
            conn.execute(
                "CREATE TABLE portfolio(ticker TEXT,shares REAL,avg_price REAL,current_price REAL,holding_type TEXT,last_updated TEXT)"
            )
            conn.executemany(
                "INSERT INTO portfolio VALUES(?,?,?,?,?,?)",
                [
                    (" aapl ", 2, 100, 120, "Core", "2026-01-01"),
                    ("AAPL", 3, 110, 130, "Core", "2026-02-01"),
                ],
            )
        database.initialize_database(old)
        with database.connect(old) as conn:
            row = conn.execute("SELECT * FROM portfolio").fetchone()
            self.assertEqual(row["shares"], 5)
            self.assertEqual(row["avg_price"], 106)
            self.assertEqual(row["market_value"], 650)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM portfolio_legacy").fetchone()[0], 2)
            self.assertEqual(conn.execute("SELECT kind FROM transactions").fetchone()[0], "opening")
        self.assertTrue(list((old.parent / "backups").glob("*.db")))


class PerformanceTests(unittest.TestCase):
    def test_initial_drawdown(self):
        returns = pd.Series([-0.1, 0.02])
        self.assertAlmostEqual(performance.drawdowns(returns).min(), -0.1)

    def test_repeated_losses_have_downside(self):
        returns = pd.Series([-0.01, -0.01, 0.03, 0.01])
        result = performance.compute_performance_metrics(
            returns, pd.Series([-0.02, 0.01, 0.02, 0.03]), risk_free=0
        )
        expected = (
            returns.mean() * 252 / (np.sqrt(np.mean(np.minimum(returns, 0) ** 2)) * np.sqrt(252))
        )
        self.assertAlmostEqual(result["sortino"], expected)

    def test_weighted_simple_return(self):
        growth = performance.portfolio_growth(np.log([1.1, 0.9]), [0.5, 0.5])
        self.assertAlmostEqual(growth, 1)

    def test_covariance_uses_common_dates(self):
        frame = pd.DataFrame({"A": [0.1, 0.2, np.nan, 0.3], "B": [0.2, 0.1, 0.3, 0.4]})
        np.testing.assert_allclose(performance.valid_covariance(frame), frame.dropna().cov())
        self.assertGreaterEqual(
            np.linalg.eigvalsh(performance.valid_covariance(frame)).min(), -1e-12
        )

    def test_risk_contributions_sum_to_one(self):
        returns = pd.DataFrame({"A": [0.01, -0.02, 0.03], "B": [0.03, 0.01, -0.01]})
        self.assertAlmostEqual(
            performance.risk_contributions(returns, pd.Series({"A": 0.6, "B": 0.4})).sum(), 1
        )

    def test_simulation_repeatable_positive_and_bounded(self):
        returns = pd.DataFrame(
            np.random.default_rng(1).normal(0, 0.01, (40, 2)), columns=["A", "B"]
        )
        weights = pd.Series({"A": 0.5, "B": 0.5})
        axis, paths = performance.simulate_paths(returns, weights, 1000, 1, 500)
        self.assertEqual(paths.shape, (253, 500))
        self.assertTrue((paths > 0).all())
        np.testing.assert_array_equal(
            paths, performance.simulate_paths(returns, weights, 1000, 1, 500)[1]
        )
        with self.assertRaises(ValueError):
            performance.simulate_paths(returns, weights, 1000, 100, 1000000)

    def test_no_forward_fill_and_coverage(self):
        prices = pd.DataFrame({"A": [100, np.nan, 110, 121, 120], "B": [100, 101, 102, 103, 104]})
        returns = market.clean_returns(prices, min_observations=2)
        self.assertEqual(returns.index.tolist(), [3, 4])


class NewsTests(unittest.TestCase):
    def test_story_is_associated_with_each_matching_holding(self):
        response = Mock(status_code=200)
        response.json.return_value = {
            "status": "ok",
            "articles": [
                {
                    "title": "Apple and Microsoft report earnings",
                    "description": "Revenue rises",
                    "publishedAt": "2026-09-29T12:00:00Z",
                    "url": "https://example.com/earnings",
                    "source": {"name": "Test"},
                }
            ],
        }
        with patch.object(news.requests, "get", return_value=response):
            articles = news._fetch_live(["AAPL", "MSFT"])
        self.assertEqual({article["ticker"] for article in articles}, {"AAPL", "MSFT"})

    def test_cache_key_does_not_depend_on_ticker_order(self):
        with (
            patch.object(news, "_api_key", return_value="test"),
            patch.object(news, "_cache", {}),
            patch.object(news, "_fetch_live", return_value=[]) as fetch,
        ):
            news.fetch_portfolio_news(["MSFT", "AAPL"])
            news.fetch_portfolio_news(["AAPL", "MSFT"])
            self.assertEqual(fetch.call_count, 1)

    def test_company_names_and_multiple_holdings(self):
        self.assertEqual(
            news._match_tickers("Apple and Microsoft report earnings", ["AAPL", "MSFT"]),
            ["AAPL", "MSFT"],
        )
        self.assertEqual(news._match_tickers("A strong quarter for the market", ["A"]), [])
        self.assertEqual(news._match_tickers("$A beats estimates", ["A"]), ["A"])

    def test_importance_uses_words(self):
        self.assertEqual(news._score_article({"title": "second thoughts"}), 0)

    def test_inference_failure_identifies_fallback(self):
        with (
            patch.object(sentiment, "_load_pipeline"),
            patch.object(sentiment, "_pipeline", Mock(side_effect=RuntimeError("test failure"))),
            patch.object(sentiment, "_cache", {}),
        ):
            result = sentiment.score_texts(["profits surge"])[0]
            self.assertEqual(result["backend"], "lex")
            self.assertIn("lex:", next(iter(sentiment._cache)))
            self.assertIn("1 keyword fallback", sentiment.describe_scores([{"sentiment": result}]))

    def test_coverage_score_is_for_covered_holdings(self):
        rows = [{"ticker": "A", "headlines": 2, "score": 60}]
        self.assertEqual(sentiment.portfolio_score(rows, {"A": 10, "B": 90}), 60)


if __name__ == "__main__":
    unittest.main()
