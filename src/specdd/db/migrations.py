import sqlite3
from pathlib import Path

_SCHEMA_SQL = Path(__file__).parent / "schema.sql"


def initialize_db(conn: sqlite3.Connection) -> None:
    schema = _SCHEMA_SQL.read_text()
    conn.executescript(schema)
    conn.execute(
        "INSERT OR IGNORE INTO schema_version(version) VALUES(?)",
        (1,),
    )


def get_schema_version(conn: sqlite3.Connection) -> int:
    try:
        row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
        return int(row[0]) if row and row[0] is not None else 0
    except sqlite3.OperationalError:
        return 0
