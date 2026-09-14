from pathlib import Path

from sqlalchemy import create_engine


BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "portfolio.db"
DATABASE_URL = f"sqlite:///{DB_PATH.as_posix()}"


def get_engine():
    return create_engine(DATABASE_URL)
