"""Preflight-only output path planning for the two-file subtitle transaction."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path

from larp_audio_mvp.core.errors import (
    SubtitleExistingOutputReadError,
    SubtitleOutputCollisionError,
    SubtitleOutputPathError,
    SubtitleOutputPreparationError,
)

_MAX_EXISTING_OUTPUT_BYTES = 64 * 1024 * 1024


def _lexical_absolute(path: Path) -> Path:
    return Path(os.path.abspath(os.path.expanduser(os.fspath(path))))


def _resolved(path: Path, *, role: str) -> Path:
    try:
        return _lexical_absolute(path).resolve(strict=False)
    except (OSError, RuntimeError, UnicodeError) as exc:
        raise SubtitleOutputPathError(
            f"cannot normalize {role} path: {path}",
            code="SUBTITLE_OUTPUT_PATH_INVALID",
        ) from exc


def _identity(path: Path) -> str:
    return os.path.normcase(os.path.normpath(os.fspath(path)))


def _same_existing_file(left: Path, right: Path) -> bool:
    try:
        return left.exists() and right.exists() and os.path.samefile(left, right)
    except OSError:
        return False


@dataclass(frozen=True, slots=True)
class SubtitlePathPlan:
    alignment_path: Path
    subtitle_blocks_path: Path
    srt_path: Path
    subtitle_blocks_partial_path: Path
    srt_partial_path: Path
    subtitle_blocks_rollback_path: Path
    srt_rollback_path: Path
    normalized_identities: tuple[tuple[str, str], ...]

    @classmethod
    def build(
        cls,
        *,
        alignment_path: Path,
        subtitle_blocks_path: Path,
        srt_path: Path,
    ) -> "SubtitlePathPlan":
        alignment_lexical = _lexical_absolute(alignment_path)
        blocks_lexical = _lexical_absolute(subtitle_blocks_path)
        srt_lexical = _lexical_absolute(srt_path)
        for role, lexical in (
            ("subtitle_blocks output", blocks_lexical),
            ("SRT output", srt_lexical),
        ):
            try:
                if lexical.is_symlink():
                    raise SubtitleOutputPathError(
                        f"{role} must not be a symbolic link: {lexical}",
                        code="SUBTITLE_OUTPUT_PATH_INVALID",
                    )
            except OSError as exc:
                raise SubtitleOutputPathError(
                    f"cannot inspect {role}: {lexical}",
                    code="SUBTITLE_OUTPUT_PATH_INVALID",
                ) from exc

        alignment = _resolved(alignment_lexical, role="alignment input")
        blocks = _resolved(blocks_lexical, role="subtitle_blocks output")
        srt = _resolved(srt_lexical, role="SRT output")
        partial_blocks = blocks.with_name(f"{blocks.stem}.partial{blocks.suffix}")
        partial_srt = srt.with_name(f"{srt.stem}.partial{srt.suffix}")
        rollback_blocks = blocks.with_name(f"{blocks.name}.rollback")
        rollback_srt = srt.with_name(f"{srt.name}.rollback")
        named = (
            ("alignment input", alignment),
            ("subtitle_blocks output", blocks),
            ("SRT output", srt),
            ("subtitle_blocks staging", partial_blocks),
            ("SRT staging", partial_srt),
            ("subtitle_blocks rollback", rollback_blocks),
            ("SRT rollback", rollback_srt),
        )
        identities = tuple((role, _identity(path)) for role, path in named)
        for index, (left_role, left_path) in enumerate(named):
            for right_role, right_path in named[index + 1 :]:
                if _identity(left_path) == _identity(right_path) or _same_existing_file(
                    left_path, right_path
                ):
                    raise SubtitleOutputCollisionError(
                        f"path collision between {left_role} and {right_role}",
                        code="SUBTITLE_OUTPUT_COLLISION",
                    )

        plan = cls(
            alignment_path=alignment,
            subtitle_blocks_path=blocks,
            srt_path=srt,
            subtitle_blocks_partial_path=partial_blocks,
            srt_partial_path=partial_srt,
            subtitle_blocks_rollback_path=rollback_blocks,
            srt_rollback_path=rollback_srt,
            normalized_identities=identities,
        )
        plan._validate_types()
        return plan

    def _validate_types(self) -> None:
        self._require_regular_input()
        for role, path in (
            ("subtitle_blocks output", self.subtitle_blocks_path),
            ("SRT output", self.srt_path),
        ):
            self._validate_optional_regular_output(role, path)
            self._validate_parent(role, path.parent)
        for role, path in (
            ("subtitle_blocks staging", self.subtitle_blocks_partial_path),
            ("SRT staging", self.srt_partial_path),
            ("subtitle_blocks rollback", self.subtitle_blocks_rollback_path),
            ("SRT rollback", self.srt_rollback_path),
        ):
            try:
                if path.exists() or path.is_symlink():
                    raise SubtitleOutputPathError(
                        f"{role} path is already occupied: {path}",
                        code="SUBTITLE_STAGING_PATH_OCCUPIED",
                    )
            except OSError as exc:
                raise SubtitleOutputPathError(
                    f"cannot inspect {role}: {path}",
                    code="SUBTITLE_OUTPUT_PATH_INVALID",
                ) from exc

    def _require_regular_input(self) -> None:
        try:
            metadata = self.alignment_path.stat()
        except FileNotFoundError as exc:
            raise SubtitleOutputPathError(
                f"alignment input does not exist: {self.alignment_path}",
                code="SUBTITLE_ALIGNMENT_INPUT_MISSING",
            ) from exc
        except OSError as exc:
            raise SubtitleOutputPathError(
                f"cannot inspect alignment input: {self.alignment_path}",
                code="SUBTITLE_OUTPUT_PATH_INVALID",
            ) from exc
        if not stat.S_ISREG(metadata.st_mode):
            raise SubtitleOutputPathError(
                f"alignment input is not a regular file: {self.alignment_path}",
                code="SUBTITLE_ALIGNMENT_INPUT_INVALID",
            )

    @staticmethod
    def _validate_optional_regular_output(role: str, path: Path) -> None:
        try:
            if not path.exists():
                return
            metadata = path.stat(follow_symlinks=False)
        except OSError as exc:
            raise SubtitleOutputPathError(
                f"cannot inspect existing {role}: {path}",
                code="SUBTITLE_OUTPUT_PATH_INVALID",
            ) from exc
        if not stat.S_ISREG(metadata.st_mode):
            raise SubtitleOutputPathError(
                f"existing {role} is not a regular file: {path}",
                code="SUBTITLE_OUTPUT_PATH_INVALID",
            )

    @staticmethod
    def _validate_parent(role: str, parent: Path) -> None:
        try:
            current = parent
            while not current.exists() and current != current.parent:
                current = current.parent
            if not current.is_dir():
                raise SubtitleOutputPathError(
                    f"parent for {role} is not a directory: {current}",
                    code="SUBTITLE_OUTPUT_PARENT_INVALID",
                )
        except (OSError, RuntimeError) as exc:
            raise SubtitleOutputPathError(
                f"cannot inspect parent for {role}: {current}",
                code="SUBTITLE_OUTPUT_PARENT_INVALID",
            ) from exc

    def prepare_directories(self) -> None:
        for role, parent in (
            ("subtitle_blocks output", self.subtitle_blocks_path.parent),
            ("SRT output", self.srt_path.parent),
        ):
            try:
                parent.mkdir(parents=True, exist_ok=True)
                if not parent.is_dir():
                    raise NotADirectoryError(os.fspath(parent))
            except OSError as exc:
                raise SubtitleOutputPreparationError(
                    f"cannot prepare parent for {role}: {parent}",
                    code="SUBTITLE_OUTPUT_PREPARATION_FAILED",
                ) from exc

    def read_existing_outputs(self) -> tuple[bytes | None, bytes | None]:
        return (
            self._read_existing(self.subtitle_blocks_path, "subtitle_blocks output"),
            self._read_existing(self.srt_path, "SRT output"),
        )

    @staticmethod
    def _read_existing(path: Path, role: str) -> bytes | None:
        try:
            if not path.exists():
                return None
            size = path.stat().st_size
            if size > _MAX_EXISTING_OUTPUT_BYTES:
                raise SubtitleExistingOutputReadError(
                    f"existing {role} exceeds {_MAX_EXISTING_OUTPUT_BYTES} bytes",
                    code="SUBTITLE_EXISTING_OUTPUT_TOO_LARGE",
                )
            payload = path.read_bytes()
            payload.decode("utf-8")
            return payload
        except SubtitleExistingOutputReadError:
            raise
        except (OSError, UnicodeError) as exc:
            raise SubtitleExistingOutputReadError(
                f"cannot back up existing {role}: {path}",
                code="SUBTITLE_EXISTING_OUTPUT_READ_FAILED",
            ) from exc
