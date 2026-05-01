"""specdd-implementer-mcp — FastMCP server for the Implementer (Gemini) role."""
from __future__ import annotations

import json
import logging
from pathlib import Path

import fastmcp

from specdd.config import load_config
from specdd.db.connection import db_connection
from specdd.db import queries
from specdd.logging_config import setup_logging, write_test_log
from specdd.mcp.core import ok, error, transition_task, LEGAL_TRANSITIONS
from specdd.paths import get_db_path, get_logs_dir, validate_path_under
from specdd.subprocess_runner import run_with_timeout, tail

logger = logging.getLogger(__name__)


def create_implementer_mcp(project_root: Path) -> fastmcp.FastMCP:
    db_path = get_db_path(project_root)
    logs_dir = get_logs_dir(project_root)
    mcp = fastmcp.FastMCP("specdd-implementer")

    # ------------------------------------------------------------------
    # get_next_task
    # ------------------------------------------------------------------
    @mcp.tool()
    def get_next_task() -> dict:
        """Return the next task ready for work (top TODO, or orphaned IN_PROGRESS)."""
        logger.info("Tool: get_next_task", extra={"tool": "get_next_task"})
        with db_connection(db_path) as conn:
            task = queries.get_next_task(conn)
        if not task:
            return ok({"task": None, "message": "Queue empty."})
        return ok({"task": {"id": task["id"], "complexity": task["complexity"], "status": task["status"]}})

    # ------------------------------------------------------------------
    # start_task
    # ------------------------------------------------------------------
    @mcp.tool()
    def start_task(task_id: int) -> dict:
        """
        Atomically claim a TODO task. Returns full payload: spec content,
        feature file content, complexity, plan_required.
        For trivial/small: TODO→IN_PROGRESS. For medium/large: TODO→PLANNING.
        Idempotent if already PLANNING or IN_PROGRESS.
        """
        logger.info("Tool: start_task(%d)", task_id, extra={"tool": "start_task", "task_id": task_id})
        with db_connection(db_path) as conn:
            task = queries.get_task(conn, task_id)

        if not task:
            return error("TASK_NOT_FOUND", f"No task with id {task_id}")

        status = task["status"]

        # Idempotent paths
        if status in ("PLANNING", "IN_PROGRESS"):
            logger.info("start_task(%d): duplicate call, task already %s", task_id, status, extra={"task_id": task_id})
            with db_connection(db_path) as conn:
                queries.insert_task_event(conn, task_id, "duplicate_start_call", "implementer",
                                          json.dumps({"current_status": status}))
            return _build_start_payload(task, project_root, already_started=True)

        if status != "TODO":
            return error(
                "INVALID_TRANSITION",
                f"Task {task_id} is in status '{status}', expected 'TODO'.",
                details={"current_status": status},
            )

        # Validate spec_refs exist on disk
        spec_refs = _parse_spec_refs(task.get("spec_refs"))
        for ref in spec_refs:
            ref_path = project_root / ref
            if not ref_path.exists():
                return error(
                    "SPEC_FILE_MISSING",
                    f"Spec file '{ref}' referenced by task {task_id} does not exist.",
                    details={"missing_path": ref},
                )

        complexity = task["complexity"]
        plan_required = complexity in ("medium", "large")
        to_status = "PLANNING" if plan_required else "IN_PROGRESS"

        transitioned = transition_task(db_path, task_id, "TODO", to_status, "implementer",
                                       payload={"complexity": complexity})
        if not transitioned:
            return error(
                "INVALID_TRANSITION",
                f"Task {task_id} state changed concurrently; re-read and retry.",
                details={"expected": "TODO"},
            )

        return _build_start_payload(task, project_root, already_started=False)

    # ------------------------------------------------------------------
    # read_spec
    # ------------------------------------------------------------------
    @mcp.tool()
    def read_spec(path: str) -> dict:
        """Read a spec file (read-only). Path must be under docs/specs/."""
        logger.info("Tool: read_spec(%s)", path, extra={"tool": "read_spec"})
        try:
            with db_connection(db_path) as conn:
                cfg = load_config(project_root)
            resolved = validate_path_under(path, cfg.paths.specs, str(project_root))
        except ValueError as exc:
            return error("PATH_OUTSIDE_SCOPE", str(exc), details={"path": path})
        except FileNotFoundError as exc:
            return error("CONFIG_NOT_FOUND", str(exc))

        if not resolved.exists():
            return error("FILE_NOT_FOUND", f"Spec file not found: {path}", details={"path": path})
        return ok({"path": path, "content": resolved.read_text(encoding="utf-8")})

    # ------------------------------------------------------------------
    # request_plan_approval
    # ------------------------------------------------------------------
    @mcp.tool()
    def request_plan_approval(task_id: int, plan_text: str) -> dict:
        """
        Submit a plan for human approval. Task must be in PLANNING status.
        Transitions PLANNING→AWAITING_APPROVAL.
        """
        logger.info("Tool: request_plan_approval(%d)", task_id, extra={"tool": "request_plan_approval", "task_id": task_id})
        with db_connection(db_path) as conn:
            task = queries.get_task(conn, task_id)

        if not task:
            return error("TASK_NOT_FOUND", f"No task with id {task_id}")
        if task["status"] != "PLANNING":
            return error(
                "INVALID_TRANSITION",
                f"Task {task_id} is in '{task['status']}', must be PLANNING to submit a plan.",
                details={"current_status": task["status"]},
            )

        if len(plan_text.splitlines()) > 50:
            logger.warning("Plan for task %d is >50 lines; consider condensing.", task_id, extra={"task_id": task_id})

        with db_connection(db_path) as conn:
            queries.insert_plan(conn, task_id, plan_text)

        transitioned = transition_task(db_path, task_id, "PLANNING", "AWAITING_APPROVAL", "implementer",
                                       payload={"plan_submitted": True})
        if not transitioned:
            return error("INVALID_TRANSITION", "Task state changed concurrently; re-read and retry.")

        return ok({
            "message": "Plan submitted. Exit now and wait for human approval via 'specdd approve'.",
            "task_id": task_id,
            "status": "AWAITING_APPROVAL",
        })

    # ------------------------------------------------------------------
    # complete_task
    # ------------------------------------------------------------------
    @mcp.tool()
    def complete_task(
        task_id: int,
        summary: str,
        refactor_notes: str,
        commit_sha: str = "",
    ) -> dict:
        """
        Run BDD + unit tests and mark task DONE if both pass.
        Returns structured errors on failure so the model can fix and retry.
        """
        logger.info("Tool: complete_task(%d)", task_id, extra={"tool": "complete_task", "task_id": task_id})

        if not refactor_notes or not refactor_notes.strip():
            return error(
                "REFACTOR_NOTES_REQUIRED",
                "refactor_notes must be non-empty. State 'no refactor needed because X' if no refactoring was done.",
            )

        with db_connection(db_path) as conn:
            task = queries.get_task(conn, task_id)

        if not task:
            return error("TASK_NOT_FOUND", f"No task with id {task_id}")

        if task["status"] == "DONE":
            logger.info("complete_task(%d): already DONE (idempotent)", task_id, extra={"task_id": task_id})
            with db_connection(db_path) as conn:
                queries.insert_task_event(conn, task_id, "duplicate_complete_call", "implementer", None)
            return ok({"task_id": task_id, "status": "DONE", "already_done": True})

        if task["status"] != "IN_PROGRESS":
            return error(
                "INVALID_TRANSITION",
                f"Task {task_id} is in '{task['status']}', must be IN_PROGRESS to complete.",
                details={"current_status": task["status"]},
            )

        try:
            cfg = load_config(project_root)
        except FileNotFoundError as exc:
            return error("CONFIG_NOT_FOUND", str(exc))

        # BDD test
        bdd_feature = task.get("bdd_feature_path") or ""
        import shlex
        bdd_cmd = f"{cfg.test_runners.bdd} {shlex.quote(bdd_feature)}" if bdd_feature else cfg.test_runners.bdd
        bdd_result = run_with_timeout(bdd_cmd, cfg.test_runners.timeout_seconds, cwd=str(project_root))
        write_test_log(logs_dir, task_id, "bdd", bdd_result)

        if bdd_result.timed_out:
            return error(
                "TESTS_TIMED_OUT",
                f"BDD tests exceeded {cfg.test_runners.timeout_seconds}s timeout.",
                details={"command": bdd_cmd, "stdout_tail": tail(bdd_result.stdout, 2000)},
            )
        if bdd_result.returncode != 0:
            return error(
                "BDD_TESTS_FAILED",
                "BDD tests did not pass. Review output, fix code, and call complete_task again.",
                details={
                    "command": bdd_cmd,
                    "returncode": bdd_result.returncode,
                    "stdout_tail": tail(bdd_result.stdout, 2000),
                    "stderr_tail": tail(bdd_result.stderr, 2000),
                },
            )

        # Unit tests
        unit_result = run_with_timeout(cfg.test_runners.unit, cfg.test_runners.timeout_seconds, cwd=str(project_root))
        write_test_log(logs_dir, task_id, "unit", unit_result)

        if unit_result.timed_out or unit_result.returncode != 0:
            return error(
                "UNIT_TESTS_FAILED",
                "Unit tests did not pass. Fix and call complete_task again.",
                details={
                    "command": cfg.test_runners.unit,
                    "returncode": unit_result.returncode,
                    "stdout_tail": tail(unit_result.stdout, 2000),
                    "stderr_tail": tail(unit_result.stderr, 2000),
                },
            )

        # All green
        transitioned = transition_task(
            db_path, task_id, "IN_PROGRESS", "DONE", "implementer",
            payload={"summary": summary, "refactor_notes": refactor_notes, "commit_sha": commit_sha},
        )
        if not transitioned:
            return error("INVALID_TRANSITION", "Task state changed concurrently; re-read and retry.")

        return ok({"task_id": task_id, "status": "DONE"})

    # ------------------------------------------------------------------
    # escalate_task
    # ------------------------------------------------------------------
    @mcp.tool()
    def escalate_task(task_id: int, conflict: str, proposed_amendment: str) -> dict:
        """
        Escalate a task due to a fundamental blocker. Both fields must be >20 chars.
        Transitions IN_PROGRESS or PLANNING → ESCALATED.
        """
        logger.info("Tool: escalate_task(%d)", task_id, extra={"tool": "escalate_task", "task_id": task_id})

        if len(conflict.strip()) <= 20:
            return error("VALIDATION_ERROR", "conflict must be more than 20 characters.")
        if len(proposed_amendment.strip()) <= 20:
            return error("VALIDATION_ERROR", "proposed_amendment must be more than 20 characters.")

        with db_connection(db_path) as conn:
            task = queries.get_task(conn, task_id)

        if not task:
            return error("TASK_NOT_FOUND", f"No task with id {task_id}")

        current = task["status"]
        if current not in ("IN_PROGRESS", "PLANNING"):
            return error(
                "INVALID_TRANSITION",
                f"Task {task_id} is in '{current}'; can only escalate from IN_PROGRESS or PLANNING.",
                details={"current_status": current},
            )

        with db_connection(db_path) as conn:
            queries.insert_escalation(conn, task_id, conflict, proposed_amendment)

        transitioned = transition_task(db_path, task_id, current, "ESCALATED", "implementer",
                                       payload={"conflict": conflict[:200]})
        if not transitioned:
            return error("INVALID_TRANSITION", "Task state changed concurrently; re-read and retry.")

        return ok({
            "task_id": task_id,
            "status": "ESCALATED",
            "message": "Escalation recorded. Exit now. Run 'specdd resolve' to resolve.",
        })

    return mcp


def _parse_spec_refs(spec_refs_json: str | None) -> list[str]:
    if not spec_refs_json:
        return []
    try:
        refs = json.loads(spec_refs_json)
        return refs if isinstance(refs, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def _build_start_payload(task: dict, project_root: Path, already_started: bool) -> dict:
    spec_refs = _parse_spec_refs(task.get("spec_refs"))
    spec_contents: list[dict] = []
    for ref in spec_refs:
        ref_path = project_root / ref
        content = ref_path.read_text(encoding="utf-8") if ref_path.exists() else f"(file not found: {ref})"
        spec_contents.append({"path": ref, "content": content})

    feature_path = task.get("bdd_feature_path") or ""
    feature_content = ""
    if feature_path:
        fp = project_root / feature_path
        if fp.exists():
            feature_content = fp.read_text(encoding="utf-8")

    complexity = task["complexity"]
    plan_required = complexity in ("medium", "large")

    # Collect related ADRs
    adrs_dir = project_root / "docs" / "specs" / "adrs"
    adrs: list[str] = []
    if adrs_dir.exists():
        for adr_file in sorted(adrs_dir.glob("*.md")):
            adrs.append(adr_file.name)

    return ok({
        "task_id": task["id"],
        "title": task["title"],
        "description": task.get("description") or "",
        "complexity": complexity,
        "plan_required": plan_required,
        "spec_content": spec_contents,
        "feature_content": feature_content,
        "adrs": adrs,
        "already_started": already_started,
    })


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="specdd implementer MCP server")
    parser.add_argument("--project-root", default=".", type=Path)
    args, _ = parser.parse_known_args()
    project_root = args.project_root.resolve()

    # Setup logging if .specdd exists
    logs_dir = get_logs_dir(project_root)
    if (project_root / ".specdd").exists():
        try:
            cfg = load_config(project_root)
            setup_logging(logs_dir, cfg.logging.level)
        except Exception:
            setup_logging(logs_dir, "INFO")

    logging.getLogger("specdd").info("specdd-implementer-mcp starting, project_root=%s", project_root)

    mcp = create_implementer_mcp(project_root)
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
