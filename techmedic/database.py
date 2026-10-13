from __future__ import annotations

import json
from sqlcipher3 import dbapi2 as sqlite3
from .database_crypto import load_key, DatabaseKeyError
import uuid
from datetime import datetime, timezone
from contextlib import contextmanager
from collections.abc import Iterator
from pathlib import Path
from typing import Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def _connect(db_path: Path) -> Iterator[sqlite3.Connection]:
    """Transaction-scoped connection, reliably closed on Windows and elsewhere.

    sqlite3.Connection.__enter__/__exit__ commit or roll back but DO NOT close
    the database handle. Windows forbids deletion of open SQLite database files,
    which made TemporaryDirectory teardown fail in offline tests (especially
    visible under Python 3.14). Explicit close is required even on exception.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path = Path(db_path)
    if db_path.exists():
        with db_path.open('rb') as stream:
            if stream.read(16) == b'SQLite format 3\x00':
                raise DatabaseKeyError('Plaintext SQLite is not supported. Start with a fresh encrypted database; no migration is performed.')
    key = load_key(db_path)
    con = sqlite3.connect(str(db_path))
    try:
        version = con.execute("PRAGMA cipher_version").fetchone()
        if not version or not version[0]:
            raise DatabaseKeyError('SQLCipher is unavailable; plaintext fallback is forbidden.')
        con.execute("PRAGMA key = \"x'" + key.hex() + "'\"")
        del key
        con.execute("PRAGMA cipher_compatibility = 4")
        con.execute("PRAGMA temp_store = MEMORY")
        con.execute("SELECT count(*) FROM sqlite_master").fetchone()
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        with con:
            yield con
    finally:
        con.close()


def init_db(db_path: Path) -> None:
    with _connect(db_path) as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS cases (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                device_type TEXT NOT NULL DEFAULT '',
                manufacturer TEXT NOT NULL DEFAULT '',
                model TEXT NOT NULL DEFAULT '',
                operating_system TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'investigating',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS turns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id TEXT NOT NULL,
                user_text TEXT NOT NULL,
                diagnostic_state_json TEXT NOT NULL,
                jev_result_json TEXT NOT NULL,
                safety_json TEXT NOT NULL,
                research_json TEXT NOT NULL DEFAULT '{}',
                assistant_text TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(case_id) REFERENCES cases(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_cases_updated_at ON cases(updated_at DESC);

            CREATE INDEX IF NOT EXISTS idx_turns_case_id_id
            ON turns(case_id, id);
            """
        )
        columns = {row[1] for row in con.execute("PRAGMA table_info(turns)").fetchall()}
        if "research_json" not in columns:
            con.execute("ALTER TABLE turns ADD COLUMN research_json TEXT NOT NULL DEFAULT '{}'")


def create_case(
    db_path: Path,
    title: str,
    device_type: str = "",
    manufacturer: str = "",
    model: str = "",
    operating_system: str = "",
) -> str:
    case_id = str(uuid.uuid4())
    now = _utc_now()
    with _connect(db_path) as con:
        con.execute(
            """
            INSERT INTO cases(
                id, title, device_type, manufacturer, model,
                operating_system, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'investigating', ?, ?)
            """,
            (
                case_id,
                title.strip() or "New TechMedic case",
                device_type.strip(),
                manufacturer.strip(),
                model.strip(),
                operating_system.strip(),
                now,
                now,
            ),
        )
    return case_id


def update_case(
    db_path: Path, case_id: str, *,
    title: str | None = None, status: str | None = None,
    device_type: str | None = None, manufacturer: str | None = None,
    model: str | None = None, operating_system: str | None = None,
) -> None:
    fields: list[str] = []
    values: list[Any] = []
    if title is not None:
        fields.append("title = ?")
        values.append(title)
    if status is not None:
        fields.append("status = ?")
        values.append(status)
    for column, value in (
        ("device_type", device_type), ("manufacturer", manufacturer),
        ("model", model), ("operating_system", operating_system),
    ):
        if value is not None and value.strip():
            # Preserve known case identity but replace provisional placeholders
            # such as "Unknown" when later turns establish the actual OS.
            fields.append(
                f"{column} = CASE WHEN LOWER(TRIM({column})) IN "
                "('', 'unknown', 'not known', 'not provided', 'not specified', "
                "'undetermined', 'n/a', 'none') THEN ? ELSE " + column + " END"
            )
            values.append(value.strip())
    fields.append("updated_at = ?")
    values.append(_utc_now())
    values.append(case_id)
    with _connect(db_path) as con:
        con.execute(f"UPDATE cases SET {', '.join(fields)} WHERE id = ?", values)


def add_turn(
    db_path: Path,
    case_id: str,
    user_text: str,
    diagnostic_state: dict[str, Any],
    jev_result: dict[str, Any],
    safety: dict[str, Any],
    assistant_text: str,
    research: dict[str, Any] | None = None,
) -> int:
    with _connect(db_path) as con:
        cur = con.execute(
            """
            INSERT INTO turns(
                case_id, user_text, diagnostic_state_json, jev_result_json,
                safety_json, research_json, assistant_text, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                case_id,
                user_text,
                json.dumps(diagnostic_state, ensure_ascii=False),
                json.dumps(jev_result, ensure_ascii=False),
                json.dumps(safety, ensure_ascii=False),
                json.dumps(research or {}, ensure_ascii=False),
                assistant_text,
                _utc_now(),
            ),
        )
        return int(cur.lastrowid)


def get_case(db_path: Path, case_id: str) -> dict[str, Any] | None:
    with _connect(db_path) as con:
        row = con.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
    return dict(row) if row else None


def list_cases(db_path: Path, limit: int = 30) -> list[dict[str, Any]]:
    with _connect(db_path) as con:
        rows = con.execute(
            "SELECT * FROM cases ORDER BY updated_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(row) for row in rows]


def get_turns(db_path: Path, case_id: str, *, limit: int | None = None) -> list[dict[str, Any]]:
    if limit is not None and (not isinstance(limit, int) or limit < 1):
        raise ValueError('History limit must be a positive integer')
    with _connect(db_path) as con:
        if limit is None:
            rows = con.execute(
                "SELECT * FROM turns WHERE case_id = ? ORDER BY id ASC", (case_id,)
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM turns WHERE case_id = ? ORDER BY id DESC LIMIT ?", (case_id, limit)
            ).fetchall()[::-1]
    out: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["diagnostic_state"] = json.loads(item.pop("diagnostic_state_json"))
        item["jev_result"] = json.loads(item.pop("jev_result_json"))
        item["safety"] = json.loads(item.pop("safety_json"))
        research_json = item.pop("research_json", "{}")
        item["research"] = json.loads(research_json or "{}")
        out.append(item)
    return out


def get_latest_state(db_path: Path, case_id: str) -> dict[str, Any] | None:
    with _connect(db_path) as con:
        row = con.execute(
            """
            SELECT diagnostic_state_json
            FROM turns
            WHERE case_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (case_id,),
        ).fetchone()
    return json.loads(row[0]) if row else None


def delete_case(db_path: Path, case_id: str) -> None:
    with _connect(db_path) as con:
        con.execute("DELETE FROM cases WHERE id = ?", (case_id,))
