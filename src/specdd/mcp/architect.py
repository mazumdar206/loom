"""specdd-architect-mcp — FastMCP server for the Architect (Claude) role."""
from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path

import fastmcp

from specdd.config import load_config
from specdd.db.connection import db_connection
from specdd.db import queries
from specdd.logging_config import setup_logging
from specdd.mcp.core import ok, error, transition_task
from specdd.paths import get_db_path, get_logs_dir, validate_path_under

logger = logging.getLogger(__name__)


def _atomic_write(resolved: Path, content: str) -> None:
    """Write content atomically via tmpfile + rename."""
    resolved.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=resolved.parent, prefix=".tmp_specdd_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.replace(tmp_path, resolved)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def create_architect_mcp(project_root: Path) -> fastmcp.FastMCP:
    db_path = get_db_path(project_root)
    mcp = fastmcp.FastMCP("specdd-architect")

    def _cfg():
        return load_config(project_root)

    # ------------------------------------------------------------------
    # list_tasks
    # ------------------------------------------------------------------
    @mcp.tool()
    def list_tasks(status: str = "") -> dict:
        """List tasks, optionally filtered by status."""
        logger.info("Tool: list_tasks(status=%s)", status, extra={"tool": "list_tasks"})
        with db_connection(db_path) as conn:
            tasks = queries.list_tasks(conn, status or None)
        return ok({"tasks": tasks, "count": len(tasks)})

    # ------------------------------------------------------------------
    # get_task
    # ------------------------------------------------------------------
    @mcp.tool()
    def get_task(task_id: int) -> dict:
        """Get full task detail including event history."""
        logger.info("Tool: get_task(%d)", task_id, extra={"tool": "get_task", "task_id": task_id})
        with db_connection(db_path) as conn:
            task = queries.get_task(conn, task_id)
            if not task:
                return error("TASK_NOT_FOUND", f"No task with id {task_id}")
            events = queries.get_task_events(conn, task_id)
        return ok({"task": task, "events": events})

    # ------------------------------------------------------------------
    # create_task
    # ------------------------------------------------------------------
    @mcp.tool()
    def create_task(
        title: str,
        description: str,
        complexity: str,
        spec_refs: list[str],
        bdd_feature_path: str,
        priority: int = 100,
    ) -> dict:
        """
        Create a new task. Validates all spec_refs exist under docs/specs/ and
        bdd_feature_path exists under tests/bdd/. Each task has exactly one feature file.
        """
        logger.info("Tool: create_task(title=%s)", title, extra={"tool": "create_task"})
        if complexity not in ("trivial", "small", "medium", "large"):
            return error("VALIDATION_ERROR", f"complexity must be one of: trivial, small, medium, large. Got: {complexity!r}")

        try:
            cfg = _cfg()
        except FileNotFoundError as exc:
            return error("CONFIG_NOT_FOUND", str(exc))

        # Validate spec_refs
        for ref in spec_refs:
            try:
                resolved = validate_path_under(ref, cfg.paths.specs, str(project_root))
            except ValueError as exc:
                return error("PATH_OUTSIDE_SCOPE", str(exc), details={"path": ref})
            if not resolved.exists():
                return error("SPEC_FILE_MISSING", f"Spec file '{ref}' does not exist.", details={"path": ref})

        # Validate bdd_feature_path (exactly one)
        if not bdd_feature_path:
            return error("VALIDATION_ERROR", "bdd_feature_path is required (1:1 with task).")
        try:
            feat_resolved = validate_path_under(bdd_feature_path, cfg.paths.bdd_tests, str(project_root))
        except ValueError as exc:
            return error("PATH_OUTSIDE_SCOPE", str(exc), details={"path": bdd_feature_path})
        if not feat_resolved.exists():
            return error(
                "FEATURE_FILE_MISSING",
                f"Feature file '{bdd_feature_path}' does not exist. Create it with write_feature first.",
                details={"path": bdd_feature_path},
            )

        with db_connection(db_path) as conn:
            task_id = queries.create_task(conn, title, description, complexity, spec_refs, bdd_feature_path, priority)
            queries.insert_task_event(conn, task_id, "created", "architect",
                                      json.dumps({"complexity": complexity, "priority": priority}))

        logger.info("Task %d created: %s", task_id, title, extra={"task_id": task_id})
        return ok({"task_id": task_id, "status": "TODO"})

    # ------------------------------------------------------------------
    # update_spec
    # ------------------------------------------------------------------
    @mcp.tool()
    def update_spec(path: str, content: str) -> dict:
        """
        Write a spec file under docs/specs/. Performs the actual file write
        atomically. Path must be under docs/specs/.
        """
        logger.info("Tool: update_spec(%s)", path, extra={"tool": "update_spec"})
        try:
            cfg = _cfg()
            resolved = validate_path_under(path, cfg.paths.specs, str(project_root))
        except ValueError as exc:
            return error("PATH_OUTSIDE_SCOPE", str(exc), details={"path": path})
        except FileNotFoundError as exc:
            return error("CONFIG_NOT_FOUND", str(exc))

        _atomic_write(resolved, content)
        logger.info("Spec written: %s", resolved, extra={"tool": "update_spec"})
        return ok({"path": path, "bytes_written": len(content.encode("utf-8"))})

    # ------------------------------------------------------------------
    # write_feature
    # ------------------------------------------------------------------
    @mcp.tool()
    def write_feature(path: str, content: str) -> dict:
        """
        Write a BDD .feature file under tests/bdd/. Atomic write.
        Path must be under tests/bdd/.
        """
        logger.info("Tool: write_feature(%s)", path, extra={"tool": "write_feature"})
        try:
            cfg = _cfg()
            resolved = validate_path_under(path, cfg.paths.bdd_tests, str(project_root))
        except ValueError as exc:
            return error("PATH_OUTSIDE_SCOPE", str(exc), details={"path": path})
        except FileNotFoundError as exc:
            return error("CONFIG_NOT_FOUND", str(exc))

        _atomic_write(resolved, content)
        logger.info("Feature written: %s", resolved, extra={"tool": "write_feature"})
        return ok({"path": path, "bytes_written": len(content.encode("utf-8"))})

    # ------------------------------------------------------------------
    # read_file
    # ------------------------------------------------------------------
    @mcp.tool()
    def read_file(path: str) -> dict:
        """Read any project file (read-only). Path must be within the project root."""
        logger.info("Tool: read_file(%s)", path, extra={"tool": "read_file"})
        candidate = Path(path)
        if candidate.is_absolute():
            resolved = candidate.resolve()
        else:
            resolved = (project_root / path).resolve()

        try:
            resolved.relative_to(project_root)
        except ValueError:
            return error("PATH_OUTSIDE_SCOPE", f"Path '{path}' is outside the project root.")

        if not resolved.exists():
            return error("FILE_NOT_FOUND", f"File not found: {path}", details={"path": path})
        if not resolved.is_file():
            return error("NOT_A_FILE", f"Path is not a file: {path}")
        return ok({"path": path, "content": resolved.read_text(encoding="utf-8")})

    # ------------------------------------------------------------------
    # list_pending_plans
    # ------------------------------------------------------------------
    @mcp.tool()
    def list_pending_plans() -> dict:
        """List all plans with status=PENDING."""
        logger.info("Tool: list_pending_plans", extra={"tool": "list_pending_plans"})
        with db_connection(db_path) as conn:
            plans = queries.list_pending_plans(conn)
        return ok({"plans": plans, "count": len(plans)})

    # ------------------------------------------------------------------
    # list_escalations
    # ------------------------------------------------------------------
    @mcp.tool()
    def list_escalations() -> dict:
        """List all escalations with status=OPEN."""
        logger.info("Tool: list_escalations", extra={"tool": "list_escalations"})
        with db_connection(db_path) as conn:
            escalations = queries.list_open_escalations(conn)
        return ok({"escalations": escalations, "count": len(escalations)})

    # ------------------------------------------------------------------
    # get_escalation
    # ------------------------------------------------------------------
    @mcp.tool()
    def get_escalation(task_id: int) -> dict:
        """Get full escalation context: conflict, proposed amendment, spec content, related ADRs."""
        logger.info("Tool: get_escalation(%d)", task_id, extra={"tool": "get_escalation", "task_id": task_id})
        with db_connection(db_path) as conn:
            task = queries.get_task(conn, task_id)
            if not task:
                return error("TASK_NOT_FOUND", f"No task with id {task_id}")
            escalation = queries.get_open_escalation(conn, task_id)

        if not escalation:
            return error("ESCALATION_NOT_FOUND", f"No open escalation for task {task_id}")

        # Collect spec content
        spec_refs = _parse_spec_refs(task.get("spec_refs"))
        spec_contents: list[dict] = []
        for ref in spec_refs:
            ref_path = project_root / ref
            content = ref_path.read_text(encoding="utf-8") if ref_path.exists() else f"(missing: {ref})"
            spec_contents.append({"path": ref, "content": content})

        # Related ADRs
        adrs_dir = project_root / "docs" / "specs" / "adrs"
        adrs: list[str] = []
        if adrs_dir.exists():
            for adr_file in sorted(adrs_dir.glob("*.md")):
                adrs.append(adr_file.name)

        return ok({
            "escalation": escalation,
            "task": task,
            "spec_content": spec_contents,
            "related_adrs": adrs,
        })

    # ------------------------------------------------------------------
    # resolve_escalation
    # ------------------------------------------------------------------
    @mcp.tool()
    def resolve_escalation(
        task_id: int,
        action: str,
        resolution_notes: str,
        amended_spec_path: str = "",
        amended_spec_content: str = "",
    ) -> dict:
        """
        Resolve an escalation. action must be 'apply', 'modify', or 'reject'.
        - apply/modify: write amended spec, escalation→RESOLVED, task→TODO
        - reject: task→REJECTED, escalation→REJECTED
        """
        logger.info("Tool: resolve_escalation(%d, action=%s)", task_id, action, extra={"tool": "resolve_escalation", "task_id": task_id})
        if action not in ("apply", "modify", "reject"):
            return error("VALIDATION_ERROR", "action must be 'apply', 'modify', or 'reject'.")

        with db_connection(db_path) as conn:
            task = queries.get_task(conn, task_id)
            if not task:
                return error("TASK_NOT_FOUND", f"No task with id {task_id}")
            escalation = queries.get_open_escalation(conn, task_id)

        if not escalation:
            return error("ESCALATION_NOT_FOUND", f"No open escalation for task {task_id}")

        if task["status"] != "ESCALATED":
            return error("INVALID_TRANSITION", f"Task {task_id} is not ESCALATED (current: {task['status']}).")

        if action in ("apply", "modify"):
            if not amended_spec_path or not amended_spec_content:
                return error("VALIDATION_ERROR", "amended_spec_path and amended_spec_content are required for apply/modify.")
            try:
                cfg = _cfg()
                resolved = validate_path_under(amended_spec_path, cfg.paths.specs, str(project_root))
            except ValueError as exc:
                return error("PATH_OUTSIDE_SCOPE", str(exc), details={"path": amended_spec_path})
            except FileNotFoundError as exc:
                return error("CONFIG_NOT_FOUND", str(exc))

            _atomic_write(resolved, amended_spec_content)

            with db_connection(db_path) as conn:
                queries.resolve_escalation(conn, escalation["id"], "RESOLVED", resolution_notes)

            transitioned = transition_task(db_path, task_id, "ESCALATED", "TODO", "architect",
                                           payload={"action": action, "amended_spec": amended_spec_path})
            if not transitioned:
                return error("INVALID_TRANSITION", "Task state changed concurrently.")
            return ok({"task_id": task_id, "status": "TODO", "spec_updated": amended_spec_path})

        else:  # reject
            with db_connection(db_path) as conn:
                queries.resolve_escalation(conn, escalation["id"], "REJECTED", resolution_notes)

            transitioned = transition_task(db_path, task_id, "ESCALATED", "REJECTED", "architect",
                                           payload={"action": "reject"})
            if not transitioned:
                return error("INVALID_TRANSITION", "Task state changed concurrently.")
            return ok({"task_id": task_id, "status": "REJECTED"})

    # ------------------------------------------------------------------
    # list_adrs
    # ------------------------------------------------------------------
    @mcp.tool()
    def list_adrs() -> dict:
        """List all ADR files in docs/specs/adrs/."""
        logger.info("Tool: list_adrs", extra={"tool": "list_adrs"})
        adrs_dir = project_root / "docs" / "specs" / "adrs"
        if not adrs_dir.exists():
            return ok({"adrs": []})
        adrs = []
        for adr_file in sorted(adrs_dir.glob("*.md")):
            adrs.append({"filename": adr_file.name, "path": str(adr_file.relative_to(project_root))})
        return ok({"adrs": adrs, "count": len(adrs)})

    # ------------------------------------------------------------------
    # create_adr
    # ------------------------------------------------------------------
    @mcp.tool()
    def create_adr(
        number: int,
        title: str,
        status: str,
        context: str,
        decision: str,
        consequences: str,
    ) -> dict:
        """Write a Nygard-format ADR to docs/specs/adrs/<N>-<kebab-title>.md."""
        logger.info("Tool: create_adr(%d, %s)", number, title, extra={"tool": "create_adr"})
        kebab = _to_kebab(title)
        filename = f"{number:04d}-{kebab}.md"
        adr_path = f"docs/specs/adrs/{filename}"

        try:
            cfg = _cfg()
            resolved = validate_path_under(adr_path, cfg.paths.specs, str(project_root))
        except ValueError as exc:
            return error("PATH_OUTSIDE_SCOPE", str(exc))
        except FileNotFoundError as exc:
            return error("CONFIG_NOT_FOUND", str(exc))

        content = (
            f"# {number}. {title}\n\n"
            f"Date: {_today()}\n\n"
            f"## Status\n\n{status}\n\n"
            f"## Context\n\n{context}\n\n"
            f"## Decision\n\n{decision}\n\n"
            f"## Consequences\n\n{consequences}\n"
        )
        _atomic_write(resolved, content)
        return ok({"path": adr_path, "filename": filename})

    return mcp


def _parse_spec_refs(spec_refs_json: str | None) -> list[str]:
    if not spec_refs_json:
        return []
    try:
        refs = json.loads(spec_refs_json)
        return refs if isinstance(refs, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def _to_kebab(title: str) -> str:
    import re
    s = title.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def _today() -> str:
    from datetime import date
    return date.today().isoformat()


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="specdd architect MCP server")
    parser.add_argument("--project-root", default=".", type=Path)
    args, _ = parser.parse_known_args()
    project_root = args.project_root.resolve()

    logs_dir = get_logs_dir(project_root)
    if (project_root / ".specdd").exists():
        try:
            cfg = load_config(project_root)
            setup_logging(logs_dir, cfg.logging.level)
        except Exception:
            setup_logging(logs_dir, "INFO")

    logging.getLogger("specdd").info("specdd-architect-mcp starting, project_root=%s", project_root)

    mcp = create_architect_mcp(project_root)
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
