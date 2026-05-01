import sqlite3
import time
import logging
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger(__name__)


def _apply_pragmas(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row


def get_connection(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), isolation_level=None)
    _apply_pragmas(conn)
    return conn


@contextmanager
def db_connection(db_path: Path):
    conn = get_connection(db_path)
    try:
        yield conn
    finally:
        conn.close()


def execute_with_retry(
    conn: sqlite3.Connection, sql: str, params=()
) -> sqlite3.Cursor:
    delays = [0.05, 0.2, 0.8]
    last_error: Exception | None = None
    attempts = [0.0] + delays
    for i, delay in enumerate(attempts):
        if delay:
            time.sleep(delay)
        try:
            return conn.execute(sql, params)
        except sqlite3.OperationalError as e:
            msg = str(e).lower()
            if "database is locked" in msg or "database is busy" in msg:
                last_error = e
                logger.debug("DB locked, retry %d/3", i)
                continue
            raise
    raise last_error  # type: ignore[misc]


def executemany_with_retry(
    conn: sqlite3.Connection, sql: str, params_seq
) -> sqlite3.Cursor:
    delays = [0.05, 0.2, 0.8]
    last_error: Exception | None = None
    for i, delay in enumerate([0.0] + delays):
        if delay:
            time.sleep(delay)
        try:
            return conn.executemany(sql, params_seq)
        except sqlite3.OperationalError as e:
            msg = str(e).lower()
            if "database is locked" in msg or "database is busy" in msg:
                last_error = e
                logger.debug("DB locked (executemany), retry %d/3", i)
                continue
            raise
    raise last_error  # type: ignore[misc]
