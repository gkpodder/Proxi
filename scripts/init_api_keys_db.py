"""Initialize the Proxi SQLite API key store."""

from proxi.security.key_store import init_db


def main() -> int:
    db_path = init_db()
    print(f"Initialized API key store at {db_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
