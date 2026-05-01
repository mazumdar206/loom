"""Integration tests for the Architect MCP tools."""
from __future__ import annotations

from pathlib import Path

import pytest

from specdd.db.connection import db_connection
from specdd.db.migrations import initialize_db
from specdd.db import queries
from specdd.mcp.core import transition_task
from specdd.mcp.architect import create_architect_mcp


@pytest.fixture()
def project(tmp_path):
    specdd_dir = tmp_path / ".specdd"
    specdd_dir.mkdir()
    (specdd_dir / "logs").mkdir()

    db_path = specdd_dir / "state.db"
    with db_connection(db_path) as conn:
        initialize_db(conn)

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
        "test_runners:\n  bdd: behave\n  unit: 'pytest tests/unit'\n  timeout_seconds: 120\n"
        "bash_allowlist: []\n"
        "logging:\n  level: INFO\n  retention_days: 14\n"
    )

    (tmp_path / "docs" / "specs" / "features").mkdir(parents=True)
    (tmp_path / "docs" / "specs" / "adrs").mkdir(parents=True)
    (tmp_path / "tests" / "bdd").mkdir(parents=True)
    (tmp_path / "tests" / "unit").mkdir(parents=True)
    (tmp_path / "src").mkdir(parents=True)

    return tmp_path


def _get_tool(mcp, name):
    import asyncio
    tool = asyncio.run(mcp.get_tool(name))
    return tool.fn


def test_list_tasks_empty(project):
    mcp = create_architect_mcp(project)
    fn = _get_tool(mcp, "list_tasks")
    result = fn()
    assert result["ok"] is True
    assert result["tasks"] == []


def test_create_task_ok(project):
    spec = project / "docs" / "specs" / "features" / "foo.md"
    spec.write_text("# Spec")
    feat = project / "tests" / "bdd" / "foo.feature"
    feat.write_text("Feature: Foo")

    mcp = create_architect_mcp(project)
    fn = _get_tool(mcp, "create_task")
    result = fn(
        title="My task",
        description="Desc",
        complexity="trivial",
        spec_refs=["docs/specs/features/foo.md"],
        bdd_feature_path="tests/bdd/foo.feature",
        priority=50,
    )
    assert result["ok"] is True
    assert result["task_id"] == 1


def test_create_task_missing_spec(project):
    feat = project / "tests" / "bdd" / "foo.feature"
    feat.write_text("Feature: Foo")

    mcp = create_architect_mcp(project)
    fn = _get_tool(mcp, "create_task")
    result = fn(
        title="T", description="", complexity="trivial",
        spec_refs=["docs/specs/features/missing.md"],
        bdd_feature_path="tests/bdd/foo.feature",
    )
    assert result["ok"] is False
    assert result["error_code"] == "SPEC_FILE_MISSING"


def test_create_task_invalid_complexity(project):
    mcp = create_architect_mcp(project)
    fn = _get_tool(mcp, "create_task")
    result = fn(title="T", description="", complexity="huge",
                spec_refs=[], bdd_feature_path="")
    assert result["ok"] is False
    assert result["error_code"] == "VALIDATION_ERROR"


def test_update_spec_writes_file(project):
    mcp = create_architect_mcp(project)
    fn = _get_tool(mcp, "update_spec")
    result = fn(path="docs/specs/features/new.md", content="# New Spec\nHello.")
    assert result["ok"] is True
    assert (project / "docs" / "specs" / "features" / "new.md").read_text() == "# New Spec\nHello."


def test_update_spec_path_traversal_rejected(project):
    mcp = create_architect_mcp(project)
    fn = _get_tool(mcp, "update_spec")
    result = fn(path="docs/specs/../../evil.txt", content="evil")
    assert result["ok"] is False
    assert result["error_code"] == "PATH_OUTSIDE_SCOPE"


def test_update_spec_absolute_outside_rejected(project):
    mcp = create_architect_mcp(project)
    fn = _get_tool(mcp, "update_spec")
    result = fn(path="/etc/passwd", content="evil")
    assert result["ok"] is False
    assert result["error_code"] == "PATH_OUTSIDE_SCOPE"


def test_write_feature_ok(project):
    mcp = create_architect_mcp(project)
    fn = _get_tool(mcp, "write_feature")
    result = fn(path="tests/bdd/auth.feature", content="Feature: Auth")
    assert result["ok"] is True
    assert (project / "tests" / "bdd" / "auth.feature").read_text() == "Feature: Auth"


def test_write_feature_path_outside_rejected(project):
    mcp = create_architect_mcp(project)
    fn = _get_tool(mcp, "write_feature")
    result = fn(path="tests/bdd/../../../evil.sh", content="rm -rf /")
    assert result["ok"] is False
    assert result["error_code"] == "PATH_OUTSIDE_SCOPE"


def test_read_file_ok(project):
    target = project / "docs" / "specs" / "features" / "foo.md"
    target.write_text("hello content")

    mcp = create_architect_mcp(project)
    fn = _get_tool(mcp, "read_file")
    result = fn(path="docs/specs/features/foo.md")
    assert result["ok"] is True
    assert result["content"] == "hello content"


def test_read_file_outside_project_rejected(project):
    mcp = create_architect_mcp(project)
    fn = _get_tool(mcp, "read_file")
    result = fn(path="/etc/passwd")
    assert result["ok"] is False
    assert result["error_code"] == "PATH_OUTSIDE_SCOPE"


def test_list_pending_plans_empty(project):
    mcp = create_architect_mcp(project)
    fn = _get_tool(mcp, "list_pending_plans")
    result = fn()
    assert result["ok"] is True
    assert result["plans"] == []


def test_resolve_escalation_apply(project):
    spec = project / "docs" / "specs" / "features" / "foo.md"
    spec.write_text("# Old Spec")

    db_path = project / ".specdd" / "state.db"
    with db_connection(db_path) as conn:
        tid = queries.create_task(conn, "T", None, "trivial", ["docs/specs/features/foo.md"], None)
        queries.insert_escalation(conn, tid, "Conflict description here", "Amendment proposal here")
    transition_task(db_path, tid, "TODO", "IN_PROGRESS", "implementer")
    transition_task(db_path, tid, "IN_PROGRESS", "ESCALATED", "implementer")

    mcp = create_architect_mcp(project)
    fn = _get_tool(mcp, "resolve_escalation")
    result = fn(
        task_id=tid,
        action="apply",
        resolution_notes="Applied the amendment.",
        amended_spec_path="docs/specs/features/foo.md",
        amended_spec_content="# New Spec\nAmended content.",
    )
    assert result["ok"] is True
    assert result["status"] == "TODO"
    assert spec.read_text() == "# New Spec\nAmended content."


def test_resolve_escalation_reject(project):
    db_path = project / ".specdd" / "state.db"
    with db_connection(db_path) as conn:
        tid = queries.create_task(conn, "T", None, "trivial", [], None)
        queries.insert_escalation(conn, tid, "Fundamental conflict here", "Proposed change here")
    transition_task(db_path, tid, "TODO", "IN_PROGRESS", "implementer")
    transition_task(db_path, tid, "IN_PROGRESS", "ESCALATED", "implementer")

    mcp = create_architect_mcp(project)
    fn = _get_tool(mcp, "resolve_escalation")
    result = fn(task_id=tid, action="reject", resolution_notes="Not feasible.")
    assert result["ok"] is True
    assert result["status"] == "REJECTED"


def test_create_adr(project):
    mcp = create_architect_mcp(project)
    fn = _get_tool(mcp, "create_adr")
    result = fn(
        number=2,
        title="Use PostgreSQL",
        status="Accepted",
        context="We need a database.",
        decision="We will use PostgreSQL.",
        consequences="We need a Postgres instance.",
    )
    assert result["ok"] is True
    adr_file = project / "docs" / "specs" / "adrs" / "0002-use-postgresql.md"
    assert adr_file.exists()
    content = adr_file.read_text()
    assert "Use PostgreSQL" in content
    assert "Accepted" in content


def test_list_adrs(project):
    adr = project / "docs" / "specs" / "adrs" / "0001-test.md"
    adr.write_text("# ADR 1")

    mcp = create_architect_mcp(project)
    fn = _get_tool(mcp, "list_adrs")
    result = fn()
    assert result["ok"] is True
    assert len(result["adrs"]) == 1
    assert result["adrs"][0]["filename"] == "0001-test.md"
