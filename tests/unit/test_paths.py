"""Tests for paths.py: realpath validation, project-root containment."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from specdd.paths import validate_path_under, find_project_root


def test_normal_path(tmp_path):
    allowed = tmp_path / "docs" / "specs"
    allowed.mkdir(parents=True)
    target = allowed / "features" / "foo.md"
    target.parent.mkdir(parents=True)
    target.touch()

    result = validate_path_under("docs/specs/features/foo.md", "docs/specs", str(tmp_path))
    assert result == target.resolve()


def test_path_traversal_rejected(tmp_path):
    (tmp_path / "docs" / "specs").mkdir(parents=True)
    with pytest.raises(ValueError, match="outside allowed root"):
        validate_path_under("docs/specs/../../etc/passwd", "docs/specs", str(tmp_path))


def test_absolute_path_inside_allowed(tmp_path):
    allowed = tmp_path / "docs" / "specs"
    allowed.mkdir(parents=True)
    target = allowed / "foo.md"

    result = validate_path_under(str(target), "docs/specs", str(tmp_path))
    assert result == target.resolve()


def test_absolute_path_outside_rejected(tmp_path):
    (tmp_path / "docs" / "specs").mkdir(parents=True)
    with pytest.raises(ValueError, match="outside allowed root"):
        validate_path_under("/etc/passwd", "docs/specs", str(tmp_path))


def test_symlink_to_outside_rejected(tmp_path):
    allowed = tmp_path / "docs" / "specs"
    allowed.mkdir(parents=True)
    outside = tmp_path.parent / "outside_secret.txt"
    outside.write_text("secret")
    link = allowed / "evil_link.md"
    link.symlink_to(outside)

    with pytest.raises(ValueError, match="outside allowed root"):
        validate_path_under("docs/specs/evil_link.md", "docs/specs", str(tmp_path))


def test_nonexistent_path_still_validated(tmp_path):
    """Paths that don't exist yet should still pass containment check."""
    (tmp_path / "docs" / "specs").mkdir(parents=True)
    result = validate_path_under("docs/specs/new-spec.md", "docs/specs", str(tmp_path))
    assert str(result).startswith(str(tmp_path))


def test_find_project_root(tmp_path):
    specdd_dir = tmp_path / ".specdd"
    specdd_dir.mkdir()
    subdir = tmp_path / "src" / "mypackage"
    subdir.mkdir(parents=True)

    root = find_project_root(subdir)
    assert root == tmp_path


def test_find_project_root_not_found(tmp_path):
    result = find_project_root(tmp_path)
    assert result is None
