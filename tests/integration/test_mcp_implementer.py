"""Integration tests for the Implementer MCP tools (called directly, not via JSON-RPC)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from specdd.db.connection import db_connection
from specdd.db.migrations import initialize_db
from specdd.db import queries
from specdd.mcp.core import transition_task
from specdd.mcp.implementer import create_implementer_mcp


@pytest.fixture()
def project(tmp_path):
    specdd_dir = tmp_path / ".specdd"
    specdd_dir.mkdir()
    (specdd_dir / "logs").mkdir()

    db_path = specdd_dir / "state.db"
    with db_connection(db_path) as conn:
        initialize_db(conn)

    # Minimal config
    (specdd_dir / "config.yml").write_text(
        "version: 1\ntemplate_version: '0.1.0'\n"
        "models:\n  architect: claude\n  implementer: gemini\n"
        "paths:\n  specs: docs/specs\n  bdd_tests: tests/bdd\n  unit_tests: tests/unit\n  source: src\n"
        "approval_thresholds:\n"
        "  trivial: {plan: false, complete: false}\n"
        "  small: {plan: false, complete: true}\n"
        "  medium: {plan: true, complete: true}\n"
        "  large: {plan: true, complete: true}\n"
        "implementer_loop:\n  idle_sleep_initial: 10\n  idle_sleep_max: 300\n"
        "test_runners:\n  bdd: 'pytest'\n  unit: 'pytest tests/unit'\n  timeout_seconds: 30\n"
        "bash_allowlist: []\n"
        "logging:\n  level: INFO\n  retention_days: 14\n"
    )

    # Create spec and feature dirs
    (tmp_path / "docs" / "specs" / "features").mkdir(parents=True)
    (tmp_path / "tests" / "bdd").mkdir(parents=True)
    (tmp_path / "tests" / "unit").mkdir(parents=True)
    (tmp_path / "src").mkdir(parents=True)

    return tmp_path


def _get_mcp_tool(mcp, name):
    """Get a registered tool function from the MCP server by name."""
    import asyncio
    tool = asyncio.run(mcp.get_tool(name))
    return tool.fn


def test_get_next_task_empty(project):
    mcp = create_implementer_mcp(project)
    fn = _get_mcp_tool(mcp, "get_next_task")
    result = fn()
    assert result["ok"] is True
    assert result["task"] is None


def test_get_next_task_returns_todo(project):
    db_path = project / ".specdd" / "state.db"
    with db_connection(db_path) as conn:
        queries.create_task(conn, "T", None, "trivial", [], None)

    mcp = create_implementer_mcp(project)
    fn = _get_mcp_tool(mcp, "get_next_task")
    result = fn()
    assert result["ok"] is True
    assert result["task"]["id"] == 1


def test_start_task_trivial_goes_to_in_progress(project):
    db_path = project / ".specdd" / "state.db"
    with db_connection(db_path) as conn:
        tid = queries.create_task(conn, "T", None, "trivial", [], None)

    mcp = create_implementer_mcp(project)
    fn = _get_mcp_tool(mcp, "start_task")
    result = fn(task_id=tid)

    assert result["ok"] is True
    assert result["plan_required"] is False
    assert result["complexity"] == "trivial"

    with db_connection(db_path) as conn:
        task = queries.get_task(conn, tid)
    assert task["status"] == "IN_PROGRESS"


def test_start_task_medium_goes_to_planning(project):
    db_path = project / ".specdd" / "state.db"
    with db_connection(db_path) as conn:
        tid = queries.create_task(conn, "T", None, "medium", [], None)

    mcp = create_implementer_mcp(project)
    fn = _get_mcp_tool(mcp, "start_task")
    result = fn(task_id=tid)

    assert result["ok"] is True
    assert result["plan_required"] is True

    with db_connection(db_path) as conn:
        task = queries.get_task(conn, tid)
    assert task["status"] == "PLANNING"


def test_start_task_not_found(project):
    mcp = create_implementer_mcp(project)
    fn = _get_mcp_tool(mcp, "start_task")
    result = fn(task_id=9999)
    assert result["ok"] is False
    assert result["error_code"] == "TASK_NOT_FOUND"


def test_start_task_idempotent_in_progress(project):
    db_path = project / ".specdd" / "state.db"
    with db_connection(db_path) as conn:
        tid = queries.create_task(conn, "T", None, "trivial", [], None)

    mcp = create_implementer_mcp(project)
    fn = _get_mcp_tool(mcp, "start_task")
    r1 = fn(task_id=tid)
    r2 = fn(task_id=tid)

    assert r1["ok"] is True
    assert r2["ok"] is True
    assert r2["already_started"] is True


def test_start_task_validates_spec_refs(project):
    db_path = project / ".specdd" / "state.db"
    with db_connection(db_path) as conn:
        tid = queries.create_task(conn, "T", None, "trivial",
                                   ["docs/specs/features/missing.md"], None)

    mcp = create_implementer_mcp(project)
    fn = _get_mcp_tool(mcp, "start_task")
    result = fn(task_id=tid)
    assert result["ok"] is False
    assert result["error_code"] == "SPEC_FILE_MISSING"


def test_start_task_loads_spec_content(project):
    spec_path = project / "docs" / "specs" / "features" / "foo.md"
    spec_path.write_text("# Spec\nThis is a spec.")
    feat_path = project / "tests" / "bdd" / "foo.feature"
    feat_path.write_text("Feature: Foo\n  Scenario: bar\n    Given something")

    db_path = project / ".specdd" / "state.db"
    with db_connection(db_path) as conn:
        tid = queries.create_task(conn, "T", None, "trivial",
                                   ["docs/specs/features/foo.md"],
                                   "tests/bdd/foo.feature")

    mcp = create_implementer_mcp(project)
    fn = _get_mcp_tool(mcp, "start_task")
    result = fn(task_id=tid)

    assert result["ok"] is True
    assert len(result["spec_content"]) == 1
    assert "This is a spec." in result["spec_content"][0]["content"]
    assert "Feature: Foo" in result["feature_content"]


def test_request_plan_approval_ok(project):
    db_path = project / ".specdd" / "state.db"
    with db_connection(db_path) as conn:
        tid = queries.create_task(conn, "T", None, "medium", [], None)
    transition_task(db_path, tid, "TODO", "PLANNING", "implementer")

    mcp = create_implementer_mcp(project)
    fn = _get_mcp_tool(mcp, "request_plan_approval")
    result = fn(task_id=tid, plan_text="My plan: step 1, step 2, step 3")

    assert result["ok"] is True
    assert result["status"] == "AWAITING_APPROVAL"

    with db_connection(db_path) as conn:
        task = queries.get_task(conn, tid)
    assert task["status"] == "AWAITING_APPROVAL"


def test_request_plan_approval_wrong_status(project):
    db_path = project / ".specdd" / "state.db"
    with db_connection(db_path) as conn:
        tid = queries.create_task(conn, "T", None, "trivial", [], None)

    mcp = create_implementer_mcp(project)
    fn = _get_mcp_tool(mcp, "request_plan_approval")
    result = fn(task_id=tid, plan_text="Plan")
    assert result["ok"] is False
    assert result["error_code"] == "INVALID_TRANSITION"


def test_complete_task_requires_refactor_notes(project):
    db_path = project / ".specdd" / "state.db"
    with db_connection(db_path) as conn:
        tid = queries.create_task(conn, "T", None, "trivial", [], None)
    transition_task(db_path, tid, "TODO", "IN_PROGRESS", "implementer")

    mcp = create_implementer_mcp(project)
    fn = _get_mcp_tool(mcp, "complete_task")
    result = fn(task_id=tid, summary="Done", refactor_notes="")
    assert result["ok"] is False
    assert result["error_code"] == "REFACTOR_NOTES_REQUIRED"


def test_complete_task_failing_tests_returns_structured_error(project):
    db_path = project / ".specdd" / "state.db"
    # Create a feature file that will fail
    feat_path = project / "tests" / "bdd" / "fail.feature"
    feat_path.write_text("Feature: Fail\n  Scenario: always fails\n    Given this does not exist\n")

    with db_connection(db_path) as conn:
        tid = queries.create_task(conn, "T", None, "trivial", [],
                                   "tests/bdd/fail.feature")
    transition_task(db_path, tid, "TODO", "IN_PROGRESS", "implementer")

    mcp = create_implementer_mcp(project)
    fn = _get_mcp_tool(mcp, "complete_task")
    # Config has bdd='pytest' which will fail on a .feature file
    result = fn(task_id=tid, summary="Done", refactor_notes="no refactor needed because trivial")

    assert result["ok"] is False
    assert "error_code" in result
    assert "details" in result


def test_complete_task_idempotent_when_done(project):
    db_path = project / ".specdd" / "state.db"
    with db_connection(db_path) as conn:
        tid = queries.create_task(conn, "T", None, "trivial", [], None)
    transition_task(db_path, tid, "TODO", "IN_PROGRESS", "implementer")
    transition_task(db_path, tid, "IN_PROGRESS", "DONE", "implementer")

    mcp = create_implementer_mcp(project)
    fn = _get_mcp_tool(mcp, "complete_task")
    result = fn(task_id=tid, summary="Done", refactor_notes="none needed")
    assert result["ok"] is True
    assert result.get("already_done") is True


def test_escalate_task_validates_length(project):
    db_path = project / ".specdd" / "state.db"
    with db_connection(db_path) as conn:
        tid = queries.create_task(conn, "T", None, "trivial", [], None)
    transition_task(db_path, tid, "TODO", "IN_PROGRESS", "implementer")

    mcp = create_implementer_mcp(project)
    fn = _get_mcp_tool(mcp, "escalate_task")
    result = fn(task_id=tid, conflict="short", proposed_amendment="short")
    assert result["ok"] is False
    assert result["error_code"] == "VALIDATION_ERROR"


def test_escalate_task_ok(project):
    db_path = project / ".specdd" / "state.db"
    with db_connection(db_path) as conn:
        tid = queries.create_task(conn, "T", None, "trivial", [], None)
    transition_task(db_path, tid, "TODO", "IN_PROGRESS", "implementer")

    mcp = create_implementer_mcp(project)
    fn = _get_mcp_tool(mcp, "escalate_task")
    result = fn(
        task_id=tid,
        conflict="The spec says to use library X but library X is deprecated and has no replacement.",
        proposed_amendment="Amend the spec to allow library Y as a replacement for library X.",
    )
    assert result["ok"] is True
    assert result["status"] == "ESCALATED"

    with db_connection(db_path) as conn:
        task = queries.get_task(conn, tid)
    assert task["status"] == "ESCALATED"
