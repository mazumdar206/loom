"""Tests for mcp/core.py: state machine transitions."""
from __future__ import annotations

import pytest

from specdd.db.connection import db_connection
from specdd.db.migrations import initialize_db
from specdd.db import queries
from specdd.mcp.core import transition_task, LEGAL_TRANSITIONS


@pytest.fixture()
def db_path(tmp_path):
    p = tmp_path / "test.db"
    with db_connection(p) as conn:
        initialize_db(conn)
    return p


@pytest.fixture()
def task_id(db_path):
    with db_connection(db_path) as conn:
        tid = queries.create_task(db_path, "T", None, "trivial", [], "f.feature")
    # Actually use the conn approach
    with db_connection(db_path) as conn:
        tid = queries.create_task(conn, "Test Task", None, "trivial", [], "f.feature")
    return tid, db_path


def test_all_legal_transitions_are_in_set():
    """Sanity-check the legal transitions set matches the spec."""
    expected = {
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
    assert LEGAL_TRANSITIONS == expected


def test_legal_transition_todo_to_in_progress(db_path):
    with db_connection(db_path) as conn:
        tid = queries.create_task(conn, "T", None, "trivial", [], "f.feature")

    result = transition_task(db_path, tid, "TODO", "IN_PROGRESS", "implementer")
    assert result is True

    with db_connection(db_path) as conn:
        task = queries.get_task(conn, tid)
    assert task["status"] == "IN_PROGRESS"


def test_legal_transition_todo_to_planning(db_path):
    with db_connection(db_path) as conn:
        tid = queries.create_task(conn, "T", None, "medium", [], "f.feature")

    result = transition_task(db_path, tid, "TODO", "PLANNING", "implementer")
    assert result is True

    with db_connection(db_path) as conn:
        task = queries.get_task(conn, tid)
    assert task["status"] == "PLANNING"


def test_legal_transition_in_progress_to_done(db_path):
    with db_connection(db_path) as conn:
        tid = queries.create_task(conn, "T", None, "trivial", [], "f.feature")
        queries.atomic_transition(conn, tid, "TODO", "IN_PROGRESS")

    result = transition_task(db_path, tid, "IN_PROGRESS", "DONE", "implementer")
    assert result is True

    with db_connection(db_path) as conn:
        task = queries.get_task(conn, tid)
    assert task["status"] == "DONE"
    assert task["completed_at"] is not None


def test_illegal_transition_raises(db_path):
    with db_connection(db_path) as conn:
        tid = queries.create_task(conn, "T", None, "trivial", [], "f.feature")

    with pytest.raises(ValueError, match="Illegal transition"):
        transition_task(db_path, tid, "TODO", "DONE", "implementer")


def test_illegal_transition_done_to_todo(db_path):
    with pytest.raises(ValueError, match="Illegal transition"):
        transition_task(db_path, 1, "DONE", "TODO", "human")


def test_concurrent_modification_returns_false(db_path):
    with db_connection(db_path) as conn:
        tid = queries.create_task(conn, "T", None, "trivial", [], "f.feature")
        # Move it to IN_PROGRESS manually
        queries.atomic_transition(conn, tid, "TODO", "IN_PROGRESS")

    # Now try to transition from TODO (it's already IN_PROGRESS)
    result = transition_task(db_path, tid, "TODO", "PLANNING", "implementer")
    assert result is False


def test_transition_logs_event(db_path):
    with db_connection(db_path) as conn:
        tid = queries.create_task(conn, "T", None, "trivial", [], "f.feature")

    transition_task(db_path, tid, "TODO", "IN_PROGRESS", "implementer", payload={"test": True})

    with db_connection(db_path) as conn:
        events = queries.get_task_events(conn, tid)
    assert len(events) == 1
    assert events[0]["event_type"] == "todo_to_in_progress"
    assert events[0]["actor"] == "implementer"


def test_full_happy_path_escalation(db_path):
    """Simulate: TODO → IN_PROGRESS → ESCALATED → TODO."""
    with db_connection(db_path) as conn:
        tid = queries.create_task(conn, "T", None, "trivial", [], "f.feature")

    assert transition_task(db_path, tid, "TODO", "IN_PROGRESS", "implementer")
    assert transition_task(db_path, tid, "IN_PROGRESS", "ESCALATED", "implementer")
    assert transition_task(db_path, tid, "ESCALATED", "TODO", "architect")

    with db_connection(db_path) as conn:
        task = queries.get_task(conn, tid)
    assert task["status"] == "TODO"


def test_full_planning_path(db_path):
    """Simulate: TODO → PLANNING → AWAITING_APPROVAL → IN_PROGRESS → DONE."""
    with db_connection(db_path) as conn:
        tid = queries.create_task(conn, "T", None, "medium", [], "f.feature")

    assert transition_task(db_path, tid, "TODO", "PLANNING", "implementer")
    assert transition_task(db_path, tid, "PLANNING", "AWAITING_APPROVAL", "implementer")
    assert transition_task(db_path, tid, "AWAITING_APPROVAL", "IN_PROGRESS", "human")
    assert transition_task(db_path, tid, "IN_PROGRESS", "DONE", "implementer")

    with db_connection(db_path) as conn:
        task = queries.get_task(conn, tid)
    assert task["status"] == "DONE"
