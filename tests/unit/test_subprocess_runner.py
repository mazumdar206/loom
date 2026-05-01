"""Tests for subprocess_runner.py."""
from __future__ import annotations

import pytest

from specdd.subprocess_runner import run_with_timeout, tail, SubprocessResult


def test_success_exit_zero():
    result = run_with_timeout("echo hello", timeout=5)
    assert result.returncode == 0
    assert "hello" in result.stdout
    assert result.timed_out is False
    assert result.duration_s >= 0


def test_nonzero_exit():
    result = run_with_timeout("exit 42", timeout=5)
    assert result.returncode == 42
    assert result.timed_out is False


def test_stderr_captured():
    result = run_with_timeout("echo error >&2", timeout=5)
    assert "error" in result.stderr


def test_stdout_and_stderr():
    result = run_with_timeout("echo out; echo err >&2", timeout=5)
    assert "out" in result.stdout
    assert "err" in result.stderr


def test_timeout_fires():
    result = run_with_timeout("sleep 60", timeout=1)
    assert result.timed_out is True
    assert result.returncode == -1
    assert result.duration_s < 5  # Should have stopped quickly


def test_duration_reasonable():
    result = run_with_timeout("sleep 0.1", timeout=5)
    assert result.duration_s >= 0.05


def test_tail_short():
    assert tail("hello", 100) == "hello"


def test_tail_truncates():
    text = "a" * 100
    result = tail(text, 50)
    assert result.startswith("...[truncated]")
    assert len(result) < 100


def test_tail_exact():
    text = "x" * 50
    assert tail(text, 50) == text
