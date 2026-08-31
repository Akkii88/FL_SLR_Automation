"""
FL-SLR Database Engine & Session Management
============================================
Sets up SQLAlchemy engine, session factory, and base class for models.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from app.core.config import settings

# Build the database URL with absolute path for SQLite
db_url = settings.database_url

# For SQLite, use the project root to build absolute path
if db_url.startswith("sqlite:///"):
    relative_path = db_url.replace("sqlite:///", "")
    db_path = settings.project_root / relative_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_url = f"sqlite:///{db_path}"

engine = create_engine(
    db_url,
    echo=False,  # Set to True for SQL debugging
    connect_args={"check_same_thread": False} if "sqlite" in db_url else {},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """FastAPI dependency: provides a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_database():
    """Create all tables in the database."""
    from app.models import paper, search_run, screening, pdf_file, deduplication, extraction, ai_screening  # noqa: F401
    Base.metadata.create_all(bind=engine)
