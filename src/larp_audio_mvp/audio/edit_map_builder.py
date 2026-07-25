"""Build a complete source-to-target edit map from policy decisions."""

from __future__ import annotations

from typing import Sequence

from larp_audio_mvp.audio.pause_policy import PauseShorteningPolicy
from larp_audio_mvp.core.contracts import (
    AudioInfo,
    EditKind,
    EditMap,
    EditSpan,
    PauseShorteningDecision,
    SampleRange,
)
from larp_audio_mvp.core.errors import EditMapError


class EditMapBuilder:
    """Create a contiguous partition; no timeline values are inferred later."""

    def build(
        self,
        audio: AudioInfo,
        decisions: Sequence[PauseShorteningDecision],
        *,
        policy: PauseShorteningPolicy,
    ) -> EditMap:
        if audio.total_samples is None or audio.total_samples <= 0:
            raise EditMapError(
                "edit map requires an exact positive source sample count",
                code="MISSING_TOTAL_SAMPLES",
            )
        if not audio.sha256:
            raise EditMapError(
                "edit map requires the source SHA-256",
                code="MISSING_SOURCE_HASH",
            )

        removals = sorted(
            (decision for decision in decisions if decision.remove_range is not None),
            key=lambda item: item.remove_range.start,  # type: ignore[union-attr]
        )
        _validate_decisions(removals, audio.total_samples)
        spans: list[EditSpan] = []
        source_cursor = 0
        target_cursor = 0

        for decision in removals:
            assert decision.remove_range is not None
            removal = decision.remove_range
            if source_cursor < removal.start:
                kept_length = removal.start - source_cursor
                spans.append(
                    EditSpan(
                        kind=EditKind.KEEP,
                        source_range=SampleRange(source_cursor, removal.start),
                        output_range=SampleRange(
                            target_cursor, target_cursor + kept_length
                        ),
                        reason="preserve_source_audio",
                    )
                )
                target_cursor += kept_length
            spans.append(
                EditSpan(
                    kind=EditKind.REMOVE,
                    source_range=removal,
                    target_anchor=target_cursor,
                    candidate_range=SampleRange(
                        decision.pause.start_sample,
                        decision.pause.end_sample,
                    ),
                    retained_before_samples=decision.retained_before_samples,
                    retained_after_samples=decision.retained_after_samples,
                    reason=decision.reason,
                )
            )
            source_cursor = removal.end

        if source_cursor < audio.total_samples:
            kept_length = audio.total_samples - source_cursor
            spans.append(
                EditSpan(
                    kind=EditKind.KEEP,
                    source_range=SampleRange(source_cursor, audio.total_samples),
                    output_range=SampleRange(
                        target_cursor, target_cursor + kept_length
                    ),
                    reason="preserve_source_audio",
                )
            )
            target_cursor += kept_length

        return EditMap(
            schema_version="1",
            policy_version=policy.version,
            sample_rate=audio.sample_rate,
            source_total_samples=audio.total_samples,
            output_total_samples=target_cursor,
            source_sha256=audio.sha256,
            spans=tuple(spans),
            policy_snapshot=policy.snapshot(audio.sample_rate),
            warnings=("signal_only_pause_policy_without_stt_alignment",),
        )


def _validate_decisions(
    decisions: Sequence[PauseShorteningDecision], total_samples: int
) -> None:
    previous_end = 0
    for decision in decisions:
        assert decision.remove_range is not None
        removal = decision.remove_range
        if removal.end > total_samples:
            raise EditMapError(
                "removal exceeds source timeline", code="REMOVAL_OUT_OF_BOUNDS"
            )
        if removal.start < previous_end:
            raise EditMapError(
                "removal decisions overlap", code="OVERLAPPING_REMOVALS"
            )
        previous_end = removal.end
