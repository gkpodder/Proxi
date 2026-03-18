"""Initialize the Proxi SQLite API key store.

This script initializes the API keys and enabled_mcps tables in the
SQLite database. The database is always stored in the config/ directory
for centralized configuration management.
"""

from pathlib import Path

from proxi.security.key_store import init_db

# Always use config directory for database storage
CONFIG_DB_PATH = Path("config/api_keys.db")


def main() -> int:
    """Initialize the API key store database in config/api_keys.db."""
    db_path = init_db(db_path=CONFIG_DB_PATH)
    print(f"Initialized API key store at {db_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
