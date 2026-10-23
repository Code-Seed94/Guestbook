"""방명록의 SQLite 저장소 함수."""

from pathlib import Path
import sqlite3


CREATE_ENTRIES_TABLE = """
CREATE TABLE IF NOT EXISTS entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""


def _connect(database_path: str | Path) -> sqlite3.Connection:
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=5)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database(database_path: str | Path) -> None:
    """방명록 테이블이 없으면 한 번 생성한다."""
    with _connect(database_path) as connection:
        connection.execute(CREATE_ENTRIES_TABLE)


def create_entry(database_path: str | Path, name: str, message: str) -> dict:
    """검증이 끝난 방명록 한 건을 저장한다."""
    with _connect(database_path) as connection:
        cursor = connection.execute(
            "INSERT INTO entries (name, message) VALUES (?, ?)",
            (name, message),
        )
        row = connection.execute(
            "SELECT id, name, message, created_at FROM entries WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()
    return dict(row)


def list_entries(database_path: str | Path, limit: int = 100) -> list[dict]:
    """최근 방명록부터 최대 100건을 반환한다."""
    safe_limit = max(1, min(limit, 100))
    with _connect(database_path) as connection:
        rows = connection.execute(
            """
            SELECT id, name, message, created_at
            FROM entries
            ORDER BY id DESC
            LIMIT ?
            """,
            (safe_limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def count_entries(database_path: str | Path) -> int:
    """저장된 방명록 개수를 반환한다."""
    with _connect(database_path) as connection:
        row = connection.execute("SELECT COUNT(*) AS count FROM entries").fetchone()
    return int(row["count"])
