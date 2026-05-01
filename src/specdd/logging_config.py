import json
import logging
import logging.handlers
from datetime import datetime, timezone
from pathlib import Path


class _JsonLinesFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data: dict = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            data["exc"] = self.formatException(record.exc_info)
        for extra_key in ("task_id", "tool", "actor"):
            if hasattr(record, extra_key):
                data[extra_key] = getattr(record, extra_key)
        return json.dumps(data)


def setup_logging(logs_dir: Path, level: str = "INFO") -> None:
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_level = getattr(logging, level.upper(), logging.INFO)

    handler = logging.handlers.TimedRotatingFileHandler(
        logs_dir / "runtime.log",
        when="midnight",
        interval=1,
        backupCount=14,
        encoding="utf-8",
    )
    handler.setFormatter(_JsonLinesFormatter())

    specdd_logger = logging.getLogger("specdd")
    specdd_logger.setLevel(log_level)
    # Avoid adding duplicate handlers if called multiple times
    if not any(isinstance(h, logging.handlers.TimedRotatingFileHandler) for h in specdd_logger.handlers):
        specdd_logger.addHandler(handler)


def write_test_log(
    logs_dir: Path,
    task_id: int,
    test_type: str,
    result,
) -> Path:
    tests_dir = logs_dir / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log_file = tests_dir / f"{task_id}-{ts}-{test_type}.log"
    content = (
        f"Command exit: {result.returncode}\n"
        f"Duration: {result.duration_s:.2f}s\n"
        f"Timed out: {result.timed_out}\n"
        f"\n--- STDOUT ---\n{result.stdout}\n"
        f"\n--- STDERR ---\n{result.stderr}\n"
    )
    log_file.write_text(content, encoding="utf-8")
    return log_file
