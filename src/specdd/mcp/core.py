"""
Core state machine for SpecDD MCP servers.
All state transitions go through transition_task() — no direct SQL elsewhere.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from specdd.db.connection import db_connection, execute_with_retry
from specdd.db import queries

logger = logging.getLogger(__name__)

# Every legal (from, to) pair. Anything else is rejected.
LEGAL_TRANSITIONS: frozenset[tuple[str, str]] = frozenset(
    {
        ("TODO", "PLANNING"),
        ("TODO", "IN_PROGRESS"),
        ("PLANNING", "AWAITING_APPROVAL"),
        ("PLANNING", "ESCALATED"),
        ("AWAITING_APPROVAL", "IN_PROGRESS"),
        ("AWAITING_APPROVAL", "REJECTED"),
        ("AWAITING_APPROVAL", "TODO"),
        ("IN_PROGRESS", "ESCALATED"),
        ("IN_PROGRESS", "DONE"),
        ("ESCALATED", "TODO"),
        ("ESCALATED", "REJECTED"),
    }
)


def ok(data: dict) -> dict:
    return {"ok": True, **data}


def error(code: str, message: str, details: dict | None = None) -> dict:
    result: dict[str, Any] = {"ok": False, "error_code": code, "message": message}
    if details:
        result["details"] = details
    return result


def transition_task(
    db_path: Path,
    task_id: int,
    expected_from: str,
    to_status: str,
    actor: str,
    payload: dict | None = None,
) -> bool:
    """
    Atomically transition task from expected_from → to_status.
    Returns True if the row was updated; False if the task was not in expected_from
    (concurrent modification). Raises ValueError for illegal transitions.
    """
    if (expected_from, to_status) not in LEGAL_TRANSITIONS:
        raise ValueError(f"Illegal transition: {expected_from} → {to_status}")

    extra: dict[str, Any] = {}
    if to_status == "DONE":
        extra["completed_at"] = "datetime('now')"  # handled specially below

    with db_connection(db_path) as conn:
        if to_status == "DONE":
            cur = execute_with_retry(
                conn,
                "UPDATE tasks SET status = ?, updated_at = datetime('now'), completed_at = datetime('now') WHERE id = ? AND status = ?",
                (to_status, task_id, expected_from),
            )
        else:
            cur = execute_with_retry(
                conn,
                "UPDATE tasks SET status = ?, updated_at = datetime('now') WHERE id = ? AND status = ?",
                (to_status, task_id, expected_from),
            )

        if cur.rowcount == 0:
            return False

        queries.insert_task_event(
            conn,
            task_id,
            event_type=f"{expected_from.lower()}_to_{to_status.lower()}",
            actor=actor,
            payload=json.dumps(payload) if payload else None,
        )

    logger.info(
        "Task %d: %s → %s",
        task_id,
        expected_from,
        to_status,
        extra={"task_id": task_id, "actor": actor},
    )
    return True
