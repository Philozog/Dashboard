"""Optional real-browser checks against a temporary portfolio and offline quotes."""

import logging
import os
import sys
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import pandas as pd
from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server


def fake_download(tickers, **kwargs):
    if isinstance(tickers, str):
        tickers = [tickers]
    minute = kwargs.get("interval") == "1m"
    dates = (
        pd.date_range(
            pd.Timestamp.now(tz="UTC").floor("min") - pd.Timedelta(minutes=1), periods=2, freq="min"
        )
        if minute
        else pd.bdate_range("2025-01-01", periods=126)
    )
    data = {}
    for i, ticker in enumerate(sorted(set(tickers))):
        values = (100 + i * 10) * np.cumprod(1 + np.sin(np.arange(len(dates)) + i) * 0.008 + 0.0002)
        data[("Close", ticker)] = values
    return pd.DataFrame(data, index=dates)


def main():
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    with tempfile.TemporaryDirectory() as folder:
        os.environ["APOTHICAIRE_DB"] = str(Path(folder) / "browser.db")
        os.environ["NEWS_API_KEY"] = ""
        import app
        from Services.ledger import transact

        transact("deposit", amount=10000)
        transact("buy", ticker="AAPL", shares=20, price=100, holding_type="Core")
        transact("buy", ticker="AMD", shares=10, price=50, holding_type="Moonshot")
        server = make_server("127.0.0.1", 0, app.server, threaded=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        base = f"http://127.0.0.1:{server.server_port}"
        with patch("yfinance.download", side_effect=fake_download), sync_playwright() as playwright:
            thread.start()
            browser = playwright.chromium.launch(channel="msedge", headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on(
                "response",
                lambda response: (
                    errors.append(f"HTTP {response.status}: {response.url}")
                    if response.status >= 400 and "_dash-update-component" in response.url
                    else None
                ),
            )
            artifacts = Path("test-results")
            artifacts.mkdir(exist_ok=True)
            try:
                page.goto(base + "/portfolio")
                expect(page.locator("#summary-cash")).to_have_text("$7,500.00")
                page.locator("#holding-type-input").click()
                option = page.locator("#holding-type-input .VirtualizedSelectOption").filter(
                    has_text="High Conviction"
                )
                expect(option).to_be_visible()
                assert option.evaluate(
                    "el => { const r = el.getBoundingClientRect(); return el.contains(document.elementFromPoint(r.x+r.width/2, r.y+r.height/2)); }"
                )
                option.click()
                page.locator("#ticker-input").fill("AAPL")
                page.locator("#shares-input").fill("9999")
                page.locator("#avgprice-input").fill("110")
                page.locator("#remove-btn").click()
                expect(page.locator("#portfolio-action-status")).to_contain_text("Cannot sell")
                page.locator("#type-btn").click()
                expect(page.locator("#portfolio-action-status")).to_have_text(
                    "Holding type updated."
                )
                page.screenshot(path=str(artifacts / "portfolio-desktop.png"), full_page=True)

                page.goto(base + "/analytics")
                expect(page.locator("#analytics-status")).to_contain_text(
                    "value coverage: 100.0%", timeout=30000
                )
                expect(page.locator("#alpha")).not_to_have_text("N/A")
                page.screenshot(path=str(artifacts / "analytics-desktop.png"), full_page=True)
                page.goto(base + "/covariance")
                expect(page.locator("#scenario-results")).to_contain_text(
                    "Market scenario:", timeout=30000
                )
                page.goto(base + "/monte-carlo")
                expect(page.locator("#mc-status")).to_contain_text(
                    "value coverage: 100.0%", timeout=60000
                )
                expect(page.locator("#mc-current-value")).to_have_text("$2,500")
                page.goto(base + "/settings")
                page.locator("#target-core").fill("50")
                page.locator("#target-conviction").fill("35")
                page.locator("#target-moonshot").fill("15")
                page.locator("#save-risk-settings").click()
                expect(page.locator("#settings-status")).to_have_text("Risk settings saved.")
                page.locator("#backup-btn").click()
                expect(page.locator("#backup-status")).to_contain_text("Backup created:")

                page.set_viewport_size({"width": 390, "height": 844})
                page.goto(base + "/portfolio")
                expect(page.locator("#summary-nav")).to_have_text("$10,000.00")
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), (
                    "Mobile page overflows horizontally"
                )
                page.locator("#holding-type-input").click()
                expect(
                    page.locator("#holding-type-input .VirtualizedSelectOption").filter(
                        has_text="Moonshot"
                    )
                ).to_be_visible()
                page.screenshot(path=str(artifacts / "portfolio-mobile.png"), full_page=True)
                assert not errors, errors
                print(
                    "Browser checks passed: desktop/mobile dropdown, rejected oversell, category edit, analytics, correlations, Monte Carlo, settings and backup."
                )
            finally:
                browser.close()
                server.shutdown()
                thread.join(timeout=5)
                app.engine.dispose()


if __name__ == "__main__":
    main()
