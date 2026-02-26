"""SQLite database engine and session management."""

from sqlmodel import SQLModel, create_engine, Session
from app.config import settings

engine = create_engine(settings.DATABASE_URL, echo=False)


def create_db_and_tables() -> None:
    """Create all database tables if they do not exist."""
    SQLModel.metadata.create_all(engine)


def get_session() -> Session:
    """Return a new database session (caller is responsible for closing it)."""
    return Session(engine)
