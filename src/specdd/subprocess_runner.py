import subprocess
import time
from dataclasses import dataclass


@dataclass
class SubprocessResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool
    duration_s: float


def run_with_timeout(cmd: str, timeout: int, cwd: str | None = None) -> SubprocessResult:
    start = time.monotonic()
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
        )
        duration = time.monotonic() - start
        return SubprocessResult(
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            timed_out=False,
            duration_s=duration,
        )
    except subprocess.TimeoutExpired as e:
        duration = time.monotonic() - start
        stdout = ""
        stderr = ""
        if e.stdout:
            stdout = e.stdout.decode() if isinstance(e.stdout, bytes) else e.stdout
        if e.stderr:
            stderr = e.stderr.decode() if isinstance(e.stderr, bytes) else e.stderr
        return SubprocessResult(
            returncode=-1,
            stdout=stdout,
            stderr=stderr,
            timed_out=True,
            duration_s=duration,
        )


def tail(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return "...[truncated]\n" + text[-max_chars:]
