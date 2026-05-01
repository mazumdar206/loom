from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


_ALLOWED_KEYS = frozenset(
    {
        "version",
        "template_version",
        "models",
        "paths",
        "approval_thresholds",
        "implementer_loop",
        "test_runners",
        "bash_allowlist",
        "logging",
    }
)


@dataclass
class ModelsConfig:
    architect: str = "claude-sonnet-4-6"
    implementer: str = "gemini-3-flash"


@dataclass
class PathsConfig:
    specs: str = "docs/specs"
    bdd_tests: str = "tests/bdd"
    unit_tests: str = "tests/unit"
    source: str = "src"


@dataclass
class ApprovalRule:
    plan: bool = False
    complete: bool = False
    spec: bool = False


@dataclass
class ImplementerLoopConfig:
    idle_sleep_initial: int = 10
    idle_sleep_max: int = 300


@dataclass
class TestRunnersConfig:
    bdd: str = "behave"
    unit: str = "pytest tests/unit"
    timeout_seconds: int = 120


@dataclass
class LoggingConfig:
    level: str = "INFO"
    retention_days: int = 14


@dataclass
class Config:
    version: int
    template_version: str
    models: ModelsConfig
    paths: PathsConfig
    approval_thresholds: dict[str, ApprovalRule]
    implementer_loop: ImplementerLoopConfig
    test_runners: TestRunnersConfig
    bash_allowlist: list[str]
    logging: LoggingConfig

    def plan_required(self, complexity: str) -> bool:
        return self.approval_thresholds.get(complexity, ApprovalRule()).plan

    def complete_approval_required(self, complexity: str) -> bool:
        return self.approval_thresholds.get(complexity, ApprovalRule()).complete


def load_config(project_root: Path) -> Config:
    config_path = project_root / ".specdd" / "config.yml"
    if not config_path.exists():
        raise FileNotFoundError(f"Config not found at {config_path}. Run 'specdd init' first.")

    with open(config_path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)

    if data is None:
        raise ValueError("Config file is empty.")

    unknown = set(data.keys()) - _ALLOWED_KEYS
    if unknown:
        raise ValueError(f"Unknown config keys: {sorted(unknown)}")

    models_raw = data.get("models", {})
    models = ModelsConfig(
        architect=models_raw.get("architect", "claude-sonnet-4-6"),
        implementer=models_raw.get("implementer", "gemini-3-flash"),
    )

    paths_raw = data.get("paths", {})
    paths = PathsConfig(
        specs=paths_raw.get("specs", "docs/specs"),
        bdd_tests=paths_raw.get("bdd_tests", "tests/bdd"),
        unit_tests=paths_raw.get("unit_tests", "tests/unit"),
        source=paths_raw.get("source", "src"),
    )

    thresholds_raw = data.get("approval_thresholds", {})
    thresholds: dict[str, ApprovalRule] = {}
    for complexity, rule_raw in thresholds_raw.items():
        thresholds[complexity] = ApprovalRule(
            plan=rule_raw.get("plan", False),
            complete=rule_raw.get("complete", False),
            spec=rule_raw.get("spec", False),
        )

    loop_raw = data.get("implementer_loop", {})
    loop = ImplementerLoopConfig(
        idle_sleep_initial=loop_raw.get("idle_sleep_initial", 10),
        idle_sleep_max=loop_raw.get("idle_sleep_max", 300),
    )

    runners_raw = data.get("test_runners", {})
    runners = TestRunnersConfig(
        bdd=runners_raw.get("bdd", "behave"),
        unit=runners_raw.get("unit", "pytest tests/unit"),
        timeout_seconds=runners_raw.get("timeout_seconds", 120),
    )

    logging_raw = data.get("logging", {})
    log_cfg = LoggingConfig(
        level=logging_raw.get("level", "INFO"),
        retention_days=logging_raw.get("retention_days", 14),
    )

    return Config(
        version=data.get("version", 1),
        template_version=data.get("template_version", "0.1.0"),
        models=models,
        paths=paths,
        approval_thresholds=thresholds,
        implementer_loop=loop,
        test_runners=runners,
        bash_allowlist=data.get("bash_allowlist", []),
        logging=log_cfg,
    )
