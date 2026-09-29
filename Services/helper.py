"""Read canonical holdings; migrations are handled centrally."""

import pandas as pd

from Services.database import connect

EXPECTED_COLUMNS = [
    "id",
    "ticker",
    "shares",
    "avg_price",
    "current_price",
    "market_value",
    "last_updated",
    "Total_Profit_Loss",
    "holding_type",
    "quote_updated_at",
    "quote_checked_at",
]


def load_data():
    with connect() as conn:
        holdings = pd.read_sql_query("SELECT * FROM portfolio ORDER BY ticker", conn)[
            EXPECTED_COLUMNS
        ]
    # Legacy last_updated mixed edits and fetch times. Do not present it as a
    # verified market observation until the new updater has fetched a quote.
    holdings.loc[holdings["quote_checked_at"].isna(), "quote_updated_at"] = None
    return holdings
