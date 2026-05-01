"""Integration tests for CLI commands against a real initialized project."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from specdd.db.connection import db_connection
from specdd.db.migrations import initialize_db
from specdd.db import queries
from specdd.mcp.core import transition_task


@pytest.fixture()
def project(tmp_path):
    """Initialize a minimal specdd project for CLI testing."""
    specdd_dir = tmp_path / ".specdd"
    specdd_dir.mkdir()
    logs_dir = specdd_dir / "logs"
    logs_dir.mkdir()

    db_path = specdd_dir / "state.db"
    with db_connection(db_path) as conn:
        initialize_db(conn)

    # Minimal config
    config_yml = specdd_dir / "config.yml"
    config_yml.write_text(
        "version: 1\n"
        "template_version: '0.1.0'\n"
        "models:\n  architect: claude-sonnet-4-6\n  implementer: gemini\n"
        "paths:\n  specs: docs/specs\n  bdd_tests: tests/bdd\n  unit_tests: tests/unit\n  source: src\n"
        "approval_thresholds:\n"
        "  trivial: {plan: false, complete: false}\n"
        "  small: {plan: false, complete: true}\n"
        "  medium: {plan: true, complete: true}\n"
        "  large: {plan: true, complete: true, spec: true}\n"
        "implementer_loop:\n  idle_sleep_initial: 10\n  idle_sleep_max: 300\n"
        "test_runners:\n  bdd: behave\n  unit: 'pytest tests/unit'\n  timeout_seconds: 120\n"
        "bash_allowlist: ['pytest *', 'behave *', 'git diff*', 'git status']\n"
        "logging:\n  level: INFO\n  retention_days: 14\n"
    )

    return tmp_path


def _cli(args: list[str], cwd: Path, input: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "specdd"] + args,
        capture_output=True,
        text=True,
        cwd=cwd,
        input=input,
    )


def test_status_empty_project(project):
    result = _cli(["status"], project)
    assert result.returncode == 0
    assert "SpecDD Status" in result.stdout


def test_status_json(project):
    result = _cli(["status", "--json"], project)
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert "tasks_by_status" in data
    assert "pending_plans" in data


def test_tasks_list_empty(project):
    result = _cli(["tasks", "list"], project)
    assert result.returncode == 0


def test_tasks_list_json_empty(project):
    result = _cli(["tasks", "list", "--json"], project)
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["tasks"] == []


def test_tasks_show_not_found(project):
    result = _cli(["tasks", "show", "999"], project)
    assert result.returncode == 1


def test_tasks_show_found(project):
    db_path = project / ".specdd" / "state.db"
    with db_connection(db_path) as conn:
        tid = queries.create_task(conn, "My Task", "Desc", "trivial", [], None)

    result = _cli(["tasks", "show", str(tid)], project)
    assert result.returncode == 0
    assert "My Task" in result.stdout


def test_plans_pending_empty(project):
    result = _cli(["plans", "pending"], project)
    assert result.returncode == 0
    assert "No plans pending" in result.stdout


def test_approve_no_task(project):
    result = _cli(["approve", "999"], project)
    assert result.returncode == 1


def test_approve_success(project):
    db_path = project / ".specdd" / "state.db"
    with db_connection(db_path) as conn:
        tid = queries.create_task(conn, "T", None, "medium", [], None)
        queries.insert_plan(conn, tid, "My plan")

    # Move to AWAITING_APPROVAL
    transition_task(db_path, tid, "TODO", "PLANNING", "implementer")
    transition_task(db_path, tid, "PLANNING", "AWAITING_APPROVAL", "implementer")

    result = _cli(["approve", str(tid)], project)
    assert result.returncode == 0

    with db_connection(db_path) as conn:
        task = queries.get_task(conn, tid)
    assert task["status"] == "IN_PROGRESS"


def test_reject_success(project):
    db_path = project / ".specdd" / "state.db"
    with db_connection(db_path) as conn:
        tid = queries.create_task(conn, "T", None, "medium", [], None)
        queries.insert_plan(conn, tid, "My plan")

    transition_task(db_path, tid, "TODO", "PLANNING", "implementer")
    transition_task(db_path, tid, "PLANNING", "AWAITING_APPROVAL", "implementer")

    result = _cli(["reject", str(tid), "Not good"], project)
    assert result.returncode == 0

    with db_connection(db_path) as conn:
        task = queries.get_task(conn, tid)
    assert task["status"] == "REJECTED"


def test_escalations_empty(project):
    result = _cli(["escalations"], project)
    assert result.returncode == 0
    assert "No open escalations" in result.stdout


def test_validate_specs_clean(project):
    result = _cli(["validate-specs"], project)
    assert result.returncode == 0


def test_validate_specs_missing_spec(project):
    db_path = project / ".specdd" / "state.db"
    with db_connection(db_path) as conn:
        queries.create_task(
            conn, "T", None, "trivial",
            ["docs/specs/features/missing.md"],
            None
        )

    result = _cli(["validate-specs"], project)
    assert result.returncode == 1
    assert "missing_spec_ref" in result.stdout


def test_validate_specs_missing_feature(project):
    db_path = project / ".specdd" / "state.db"
    with db_connection(db_path) as conn:
        queries.create_task(
            conn, "T", None, "trivial", [],
            "tests/bdd/missing.feature"
        )

    result = _cli(["validate-specs"], project)
    assert result.returncode == 1
    assert "missing_feature_file" in result.stdout


def test_version_flag():
    result = subprocess.run(
        [sys.executable, "-m", "specdd", "--version"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "0.1.0" in result.stdout
