"""Database connection helper (MySQL)."""
import os
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")


def get_engine() -> Engine:
    """Build a SQLAlchemy engine pointed at the supply chain MySQL warehouse."""
    user = os.getenv("DB_USER", "analyst")
    pwd = os.getenv("DB_PASSWORD", "analyst")
    host = os.getenv("DB_HOST", "localhost")
    port = os.getenv("DB_PORT", "3306")
    db = os.getenv("DB_NAME", "supply_chain")

    url = f"mysql+pymysql://{user}:{pwd}@{host}:{port}/{db}?charset=utf8mb4"
    return create_engine(url, future=True, pool_pre_ping=True)
