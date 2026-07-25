"""Bounded, shell-free subprocess execution for local media tools."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import Protocol, Sequence

from larp_audio_mvp.core.errors import (
    ProcessExecutionError,
    ProcessTimeoutError,
)
from larp_audio_mvp.core.logging import get_logger

_STDERR_LIMIT = 2_000


@dataclass(frozen=True, slots=True)
class CommandResult:
    stdout: str
    stderr: str
    return_code: int
    elapsed_seconds: float


class ProcessRunner(Protocol):
    def run(
        self,
        arguments: Sequence[str],
        *,
        timeout_seconds: float,
    ) -> CommandResult: ...


class SubprocessRunner:
    """Execute one command with captured UTF-8 output and a hard timeout."""

    def __init__(self) -> None:
        self._logger = get_logger("audio.process")

    def run(
        self,
        arguments: Sequence[str],
        *,
        timeout_seconds: float,
    ) -> CommandResult:
        if not arguments:
            raise ValueError("subprocess arguments must not be empty")

        started = monotonic()
        executable_name = Path(str(arguments[0])).name
        try:
            completed = subprocess.run(
                list(arguments),
                shell=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            elapsed = monotonic() - started
            self._logger.error(
                "media tool timed out tool=%s elapsed_seconds=%.3f",
                executable_name,
                elapsed,
            )
            raise ProcessTimeoutError(
                f"{executable_name} timed out after {timeout_seconds:g} seconds"
            ) from exc
        except OSError as exc:
            raise ProcessExecutionError(
                f"cannot start media tool {executable_name}: {exc}"
            ) from exc

        elapsed = monotonic() - started
        result = CommandResult(
            stdout=completed.stdout,
            stderr=completed.stderr,
            return_code=completed.returncode,
            elapsed_seconds=elapsed,
        )
        self._logger.info(
            "media tool finished tool=%s exit_code=%d elapsed_seconds=%.3f",
            executable_name,
            result.return_code,
            result.elapsed_seconds,
        )
        if result.return_code != 0:
            stderr = _short_stderr(result.stderr)
            raise ProcessExecutionError(
                f"{executable_name} failed with exit code {result.return_code}: "
                f"{stderr or 'no stderr output'}"
            )
        return result


def _short_stderr(value: str) -> str:
    compact = " ".join(value.split())
    if len(compact) <= _STDERR_LIMIT:
        return compact
    return f"{compact[:_STDERR_LIMIT]}…"
