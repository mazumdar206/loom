"""Tests for DB layer: schema, connection, queries."""
from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

import pytest

from specdd.db.connection import db_connection, execute_with_retry, get_connection
from specdd.db.migrations import initialize_db, get_schema_version
from specdd.db import queries


@pytest.fixture()
def db_path(tmp_path):
    p = tmp_path / "test.db"
    with db_connection(p) as conn:
        initialize_db(conn)
    return p


def test_schema_version(db_path):
    with db_connection(db_path) as conn:
        assert get_schema_version(conn) == 1


def test_schema_version_empty():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = Path(f.name)
    conn = get_connection(path)
    assert get_schema_version(conn) == 0
    conn.close()
    path.unlink()


def test_create_and_get_task(db_path):
    with db_connection(db_path) as conn:
        task_id = queries.create_task(
            conn,
            title="Test task",
            description="A description",
            complexity="small",
            spec_refs=["docs/specs/features/test.md"],
            bdd_feature_path="tests/bdd/test.feature",
            priority=50,
        )
        assert task_id is not None

        task = queries.get_task(conn, task_id)
    assert task is not None
    assert task["title"] == "Test task"
    assert task["complexity"] == "small"
    assert task["status"] == "TODO"
    assert task["priority"] == 50
    refs = json.loads(task["spec_refs"])
    assert refs == ["docs/specs/features/test.md"]


def test_get_task_not_found(db_path):
    with db_connection(db_path) as conn:
        task = queries.get_task(conn, 9999)
    assert task is None


def test_list_tasks_empty(db_path):
    with db_connection(db_path) as conn:
        tasks = queries.list_tasks(conn)
    assert tasks == []


def test_list_tasks_filtered(db_path):
    with db_connection(db_path) as conn:
        queries.create_task(conn, "T1", None, "trivial", [], "tests/bdd/a.feature")
        queries.create_task(conn, "T2", None, "small", [], "tests/bdd/b.feature")
        queries.update_task_status(conn, 2, "IN_PROGRESS")

        todo = queries.list_tasks(conn, "TODO")
        in_prog = queries.list_tasks(conn, "IN_PROGRESS")

    assert len(todo) == 1
    assert todo[0]["title"] == "T1"
    assert len(in_prog) == 1
    assert in_prog[0]["title"] == "T2"


def test_atomic_transition(db_path):
    with db_connection(db_path) as conn:
        task_id = queries.create_task(conn, "T", None, "trivial", [], "f.feature")
        result = queries.atomic_transition(conn, task_id, "TODO", "IN_PROGRESS")
        assert result is True

        task = queries.get_task(conn, task_id)
    assert task["status"] == "IN_PROGRESS"


def test_atomic_transition_wrong_from(db_path):
    with db_connection(db_path) as conn:
        task_id = queries.create_task(conn, "T", None, "trivial", [], "f.feature")
        # Task is TODO, but we expect IN_PROGRESS
        result = queries.atomic_transition(conn, task_id, "IN_PROGRESS", "DONE")
        assert result is False


def test_get_next_task_todo_priority(db_path):
    with db_connection(db_path) as conn:
        queries.create_task(conn, "Low", None, "trivial", [], "a.feature", priority=200)
        queries.create_task(conn, "High", None, "trivial", [], "b.feature", priority=10)
        next_task = queries.get_next_task(conn)
    assert next_task is not None
    assert next_task["id"] == 2  # High priority (lower number = higher priority)


def test_get_next_task_empty(db_path):
    with db_connection(db_path) as conn:
        result = queries.get_next_task(conn)
    assert result is None


def test_insert_and_get_plan(db_path):
    with db_connection(db_path) as conn:
        task_id = queries.create_task(conn, "T", None, "medium", [], "f.feature")
        plan_id = queries.insert_plan(conn, task_id, "My plan text")
        plan = queries.get_pending_plan(conn, task_id)
    assert plan is not None
    assert plan["plan_text"] == "My plan text"
    assert plan["status"] == "PENDING"


def test_approve_plan(db_path):
    with db_connection(db_path) as conn:
        task_id = queries.create_task(conn, "T", None, "medium", [], "f.feature")
        plan_id = queries.insert_plan(conn, task_id, "Plan")
        result = queries.approve_plan(conn, plan_id)
        assert result is True
        plan = queries.get_pending_plan(conn, task_id)
    assert plan is None  # No longer PENDING


def test_reject_plan(db_path):
    with db_connection(db_path) as conn:
        task_id = queries.create_task(conn, "T", None, "medium", [], "f.feature")
        plan_id = queries.insert_plan(conn, task_id, "Plan")
        result = queries.reject_plan(conn, plan_id, "Not good enough")
        assert result is True


def test_insert_and_get_escalation(db_path):
    with db_connection(db_path) as conn:
        task_id = queries.create_task(conn, "T", None, "medium", [], "f.feature")
        esc_id = queries.insert_escalation(conn, task_id, "Conflict text here", "Proposed amendment text")
        esc = queries.get_open_escalation(conn, task_id)
    assert esc is not None
    assert esc["conflict"] == "Conflict text here"
    assert esc["status"] == "OPEN"


def test_resolve_escalation(db_path):
    with db_connection(db_path) as conn:
        task_id = queries.create_task(conn, "T", None, "medium", [], "f.feature")
        esc_id = queries.insert_escalation(conn, task_id, "Conflict", "Amendment")
        queries.resolve_escalation(conn, esc_id, "RESOLVED", "Fixed it")
        esc = queries.get_open_escalation(conn, task_id)
    assert esc is None  # No longer OPEN


def test_task_events(db_path):
    with db_connection(db_path) as conn:
        task_id = queries.create_task(conn, "T", None, "trivial", [], "f.feature")
        queries.insert_task_event(conn, task_id, "created", "architect", json.dumps({"x": 1}))
        queries.insert_task_event(conn, task_id, "started", "implementer", None)
        events = queries.get_task_events(conn, task_id)
    assert len(events) == 2
    assert events[0]["event_type"] == "created"
    assert events[1]["actor"] == "implementer"


def test_status_summary(db_path):
    with db_connection(db_path) as conn:
        queries.create_task(conn, "A", None, "trivial", [], "a.feature")
        queries.create_task(conn, "B", None, "small", [], "b.feature")
        queries.update_task_status(conn, 2, "DONE")
        summary = queries.get_status_summary(conn)
    assert summary["TODO"] == 1
    assert summary["DONE"] == 1


def test_list_pending_plans(db_path):
    with db_connection(db_path) as conn:
        task_id = queries.create_task(conn, "T", None, "medium", [], "f.feature")
        queries.insert_plan(conn, task_id, "My plan")
        plans = queries.list_pending_plans(conn)
    assert len(plans) == 1
    assert plans[0]["task_title"] == "T"


def test_execute_with_retry_passthrough(db_path):
    """execute_with_retry should work for normal queries."""
    with db_connection(db_path) as conn:
        cur = execute_with_retry(conn, "SELECT 1 + 1 AS result")
        row = cur.fetchone()
    assert row["result"] == 2
