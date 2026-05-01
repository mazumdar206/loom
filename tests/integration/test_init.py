"""Integration tests for specdd init."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


def _run_init(project_dir: Path, inputs: str, extra_args: list[str] | None = None) -> subprocess.CompletedProcess:
    args = [sys.executable, "-m", "specdd", "init"] + (extra_args or [])
    return subprocess.run(
        args,
        input=inputs,
        capture_output=True,
        text=True,
        cwd=project_dir,
    )


def _default_inputs(name="testproject") -> str:
    return f"{name}\n\n\n\n\n\n"  # project name + accept all defaults


def test_init_creates_expected_files(tmp_path):
    result = _run_init(tmp_path, _default_inputs(), ["--force"])
    assert result.returncode == 0, result.stderr

    # Core files
    assert (tmp_path / ".specdd" / "config.yml").exists()
    assert (tmp_path / ".specdd" / "state.db").exists()
    assert (tmp_path / ".specdd" / "logs").exists()
    assert (tmp_path / ".claude" / "settings.json").exists()
    assert (tmp_path / ".gemini" / "settings.json").exists()
    assert (tmp_path / "CLAUDE.md").exists()
    assert (tmp_path / "GEMINI.md").exists()
    assert (tmp_path / "run-implementer.sh").exists()

    # Spec dirs
    for subdir in ("architecture", "api", "features", "adrs"):
        assert (tmp_path / "docs" / "specs" / subdir).is_dir()

    # ADR 0001
    assert (tmp_path / "docs" / "specs" / "adrs" / "0001-record-architecture-decisions.md").exists()

    # Test dirs
    assert (tmp_path / "tests" / "bdd").is_dir()
    assert (tmp_path / "tests" / "unit").is_dir()

    # run-implementer.sh is executable
    assert (tmp_path / "run-implementer.sh").stat().st_mode & 0o111


def test_init_creates_gitignore(tmp_path):
    _run_init(tmp_path, _default_inputs(), ["--force"])
    gitignore = tmp_path / ".gitignore"
    assert gitignore.exists()
    content = gitignore.read_text()
    assert ".specdd/state.db" in content


def test_init_appends_to_existing_gitignore(tmp_path):
    gitignore = tmp_path / ".gitignore"
    gitignore.write_text("*.pyc\n__pycache__/\n")

    _run_init(tmp_path, _default_inputs(), ["--force"])

    content = gitignore.read_text()
    assert "*.pyc" in content  # Original preserved
    assert ".specdd/state.db" in content  # Appended


def test_init_config_has_project_values(tmp_path):
    inputs = "myapp\nclaude-sonnet-4-6\ngemini-3-flash\nsrc\nbehave\npytest\n"
    _run_init(tmp_path, inputs, ["--force"])

    config = (tmp_path / ".specdd" / "config.yml").read_text()
    assert "claude-sonnet-4-6" in config
    assert "gemini-3-flash" in config


def test_init_db_has_schema_version(tmp_path):
    _run_init(tmp_path, _default_inputs(), ["--force"])

    from specdd.db.connection import db_connection
    from specdd.db.migrations import get_schema_version
    db_path = tmp_path / ".specdd" / "state.db"
    with db_connection(db_path) as conn:
        version = get_schema_version(conn)
    assert version == 1


def test_init_idempotent_no_force(tmp_path):
    """Second init without --force should ask about each file (simulate 'n' to all)."""
    _run_init(tmp_path, _default_inputs(), ["--force"])

    # Second run — say 'n' to all prompts (don't overwrite)
    # Input: project name + "n" for each file prompt
    all_no = "testproject\n\n\n\n\n\n" + "n\n" * 20
    result = _run_init(tmp_path, all_no)
    # Should not crash
    assert result.returncode == 0


def test_init_does_not_create_src_files(tmp_path):
    _run_init(tmp_path, _default_inputs(), ["--force"])
    # src/ should not be created by init
    src = tmp_path / "src"
    assert not src.exists()


def test_claude_md_contains_project_name(tmp_path):
    inputs = "myfancyproject\n\n\n\n\n\n"
    _run_init(tmp_path, inputs, ["--force"])
    content = (tmp_path / "CLAUDE.md").read_text()
    assert "myfancyproject" in content


def test_gemini_md_contains_project_name(tmp_path):
    inputs = "myfancyproject\n\n\n\n\n\n"
    _run_init(tmp_path, inputs, ["--force"])
    content = (tmp_path / "GEMINI.md").read_text()
    assert "myfancyproject" in content
