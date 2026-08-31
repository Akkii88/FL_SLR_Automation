"""
FL-SLR Database Initialization Script
======================================
Run this to create the database tables.
Usage: python -m app.db.init_db
"""

from app.db.engine import init_database
from app.core.config import settings


def main():
    print(f"Initializing database at: {settings.database_url}")
    init_database()
    print("Database initialized successfully.")


if __name__ == "__main__":
    main()
