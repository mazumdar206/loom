"""All SQL queries as named functions. Never use f-strings for SQL."""

import json
import sqlite3
from typing import Any


def _row_to_dict(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    return dict(row)


def _rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict]:
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


def get_task(conn: sqlite3.Connection, task_id: int) -> dict | None:
    row = conn.execute(
        "SELECT * FROM tasks WHERE id = ?", (task_id,)
    ).fetchone()
    return _row_to_dict(row)


def list_tasks(conn: sqlite3.Connection, status: str | None = None) -> list[dict]:
    if status:
        rows = conn.execute(
            "SELECT * FROM tasks WHERE status = ? ORDER BY priority, created_at",
            (status,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM tasks ORDER BY priority, created_at"
        ).fetchall()
    return _rows_to_dicts(rows)


def create_task(
    conn: sqlite3.Connection,
    title: str,
    description: str | None,
    complexity: str,
    spec_refs: list[str] | None,
    bdd_feature_path: str | None,
    priority: int = 100,
) -> int:
    spec_refs_json = json.dumps(spec_refs) if spec_refs is not None else None
    cur = conn.execute(
        """
        INSERT INTO tasks(title, description, complexity, status, spec_refs, bdd_feature_path, priority)
        VALUES (?, ?, ?, 'TODO', ?, ?, ?)
        """,
        (title, description, complexity, spec_refs_json, bdd_feature_path, priority),
    )
    return cur.lastrowid  # type: ignore[return-value]


def update_task_status(conn: sqlite3.Connection, task_id: int, status: str) -> bool:
    cur = conn.execute(
        "UPDATE tasks SET status = ?, updated_at = datetime('now') WHERE id = ?",
        (status, task_id),
    )
    return cur.rowcount > 0


def atomic_transition(
    conn: sqlite3.Connection,
    task_id: int,
    expected_from: str,
    to_status: str,
    extra_updates: dict[str, Any] | None = None,
) -> bool:
    """UPDATE tasks WHERE status=expected_from atomically. Returns True if row updated."""
    sets = ["status = ?", "updated_at = datetime('now')"]
    params: list[Any] = [to_status]
    if extra_updates:
        for col, val in extra_updates.items():
            sets.append(f"{col} = ?")
            params.append(val)
    params += [task_id, expected_from]
    sql = f"UPDATE tasks SET {', '.join(sets)} WHERE id = ? AND status = ?"  # noqa: S608
    cur = conn.execute(sql, params)
    return cur.rowcount > 0


def get_next_task(conn: sqlite3.Connection) -> dict | None:
    """
    Top TODO by priority/created_at; falls back to oldest IN_PROGRESS with no
    recent event (for post-approval resume). See spec §13.3.
    """
    row = conn.execute(
        """
        SELECT id, complexity, status FROM tasks
         WHERE status = 'TODO'
            OR (
                status = 'IN_PROGRESS'
                AND NOT EXISTS (
                    SELECT 1 FROM task_events e
                    WHERE e.task_id = tasks.id
                      AND e.created_at > datetime('now', '-5 seconds')
                )
            )
         ORDER BY (CASE status WHEN 'TODO' THEN 0 ELSE 1 END), priority, created_at
         LIMIT 1
        """
    ).fetchone()
    return _row_to_dict(row)


def get_status_summary(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute(
        "SELECT status, COUNT(*) as cnt FROM tasks GROUP BY status"
    ).fetchall()
    return {r["status"]: r["cnt"] for r in rows}


# ---------------------------------------------------------------------------
# Plans
# ---------------------------------------------------------------------------


def insert_plan(conn: sqlite3.Connection, task_id: int, plan_text: str) -> int:
    cur = conn.execute(
        "INSERT INTO plans(task_id, plan_text, status) VALUES(?, ?, 'PENDING')",
        (task_id, plan_text),
    )
    return cur.lastrowid  # type: ignore[return-value]


def get_pending_plan(conn: sqlite3.Connection, task_id: int) -> dict | None:
    row = conn.execute(
        "SELECT * FROM plans WHERE task_id = ? AND status = 'PENDING' ORDER BY created_at DESC LIMIT 1",
        (task_id,),
    ).fetchone()
    return _row_to_dict(row)


def list_pending_plans(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """
        SELECT p.*, t.title as task_title, t.complexity, t.description as task_description
        FROM plans p JOIN tasks t ON p.task_id = t.id
        WHERE p.status = 'PENDING'
        ORDER BY p.created_at
        """
    ).fetchall()
    return _rows_to_dicts(rows)


def approve_plan(conn: sqlite3.Connection, plan_id: int) -> bool:
    cur = conn.execute(
        "UPDATE plans SET status = 'APPROVED', decided_at = datetime('now') WHERE id = ? AND status = 'PENDING'",
        (plan_id,),
    )
    return cur.rowcount > 0


def reject_plan(conn: sqlite3.Connection, plan_id: int, reason: str) -> bool:
    cur = conn.execute(
        "UPDATE plans SET status = 'REJECTED', rejection_reason = ?, decided_at = datetime('now') WHERE id = ? AND status = 'PENDING'",
        (reason, plan_id),
    )
    return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Escalations
# ---------------------------------------------------------------------------


def insert_escalation(
    conn: sqlite3.Connection,
    task_id: int,
    conflict: str,
    proposed_amendment: str,
) -> int:
    cur = conn.execute(
        "INSERT INTO escalations(task_id, conflict, proposed_amendment, status) VALUES(?, ?, ?, 'OPEN')",
        (task_id, conflict, proposed_amendment),
    )
    return cur.lastrowid  # type: ignore[return-value]


def get_open_escalation(conn: sqlite3.Connection, task_id: int) -> dict | None:
    row = conn.execute(
        "SELECT * FROM escalations WHERE task_id = ? AND status = 'OPEN' ORDER BY created_at DESC LIMIT 1",
        (task_id,),
    ).fetchone()
    return _row_to_dict(row)


def list_open_escalations(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """
        SELECT e.*, t.title as task_title, t.complexity
        FROM escalations e JOIN tasks t ON e.task_id = t.id
        WHERE e.status = 'OPEN'
        ORDER BY e.created_at
        """
    ).fetchall()
    return _rows_to_dicts(rows)


def resolve_escalation(
    conn: sqlite3.Connection,
    escalation_id: int,
    status: str,
    resolution_notes: str | None,
) -> bool:
    cur = conn.execute(
        "UPDATE escalations SET status = ?, resolution_notes = ?, resolved_at = datetime('now') WHERE id = ? AND status = 'OPEN'",
        (status, resolution_notes, escalation_id),
    )
    return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Task events
# ---------------------------------------------------------------------------


def insert_task_event(
    conn: sqlite3.Connection,
    task_id: int,
    event_type: str,
    actor: str,
    payload: str | None = None,
) -> int:
    cur = conn.execute(
        "INSERT INTO task_events(task_id, event_type, actor, payload) VALUES(?, ?, ?, ?)",
        (task_id, event_type, actor, payload),
    )
    return cur.lastrowid  # type: ignore[return-value]


def get_task_events(conn: sqlite3.Connection, task_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM task_events WHERE task_id = ? ORDER BY created_at",
        (task_id,),
    ).fetchall()
    return _rows_to_dicts(rows)
