"""Prepare an explicit release bundle; this script does not deploy it."""

import argparse
import shutil
from datetime import datetime, timezone
from pathlib import Path


def prepare_release(include_data=False):
    root = Path(__file__).resolve().parent
    target = root / "dist" / f"apothicaire-{datetime.now(timezone.utc):%Y%m%dT%H%M%S%fZ}"
    target.mkdir(parents=True, exist_ok=False)
    for name in ("app.py", "main.py", "schema.sql", "requirements.txt", "plotly-cloud.toml"):
        shutil.copy2(root / name, target / name)
    for directory in ("pages", "Services", "assets"):
        for source in (root / directory).rglob("*"):
            if (
                source.is_file()
                and "__pycache__" not in source.parts
                and source.suffix.lower()
                in (
                    ".py",
                    ".css",
                    ".js",
                    ".png",
                    ".jpg",
                    ".jpeg",
                    ".svg",
                    ".ico",
                    ".woff",
                    ".woff2",
                )
            ):
                destination = target / source.relative_to(root)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
    if include_data:
        from Services.database import backup_database, initialize_database

        snapshot = backup_database(initialize_database())
        (target / "data").mkdir()
        shutil.copy2(snapshot, target / "data" / "portfolio.db")
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--include-data",
        action="store_true",
        help="Include a private database snapshot in the release.",
    )
    args = parser.parse_args()
    print(f"Release prepared (not published): {prepare_release(args.include_data)}")
