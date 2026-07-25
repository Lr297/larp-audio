"""Bounded deterministic weighted sequence alignment for script and ASR words."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Sequence

from larp_audio_mvp.alignment.normalizer import comparison_key, structural_key
from larp_audio_mvp.config import AlignmentSettings
from larp_audio_mvp.core.contracts import AlignmentMatchType, RecognizedWord, ScriptToken
from larp_audio_mvp.core.errors import AlignmentLimitExceededError


@dataclass(frozen=True, slots=True)
class AlignmentOperation:
    """One deterministic traceback operation; no displayed text is stored here."""

    match_type: AlignmentMatchType
    script_indices: tuple[int, ...]
    recognition_indices: tuple[int, ...]
    similarity: Fraction | None


@dataclass(frozen=True, slots=True)
class _Candidate:
    score: int
    priority: int
    next_i: int
    next_j: int
    operation: AlignmentOperation


class ScriptAsrAlignmentEngine:
    """Needleman-Wunsch-style global alignment with bounded 1:2/2:1 steps."""

    def __init__(self, settings: AlignmentSettings) -> None:
        self._settings = settings

    def align(
        self,
        script_words: Sequence[ScriptToken],
        recognition_words: Sequence[RecognizedWord],
    ) -> tuple[AlignmentOperation, ...]:
        rows = len(script_words) + 1
        columns = len(recognition_words) + 1
        cells = rows * columns
        if cells > self._settings.max_dp_cells:
            raise AlignmentLimitExceededError(
                f"alignment requires {cells} DP cells; configured limit is "
                f"{self._settings.max_dp_cells}",
                code="ALIGNMENT_DP_LIMIT_EXCEEDED",
            )

        script_keys = tuple(_script_key(word) for word in script_words)
        asr_keys = tuple(comparison_key(word.text) for word in recognition_words)
        script_surfaces = tuple(word.exact_text for word in script_words)
        asr_surfaces = tuple(word.text.strip() for word in recognition_words)
        scores = [[0] * columns for _ in range(rows)]
        choices: list[list[_Candidate | None]] = [
            [None] * columns for _ in range(rows)
        ]

        for i in range(rows - 1, -1, -1):
            for j in range(columns - 1, -1, -1):
                if i == len(script_words) and j == len(recognition_words):
                    continue
                candidates = self._candidates(
                    i,
                    j,
                    script_keys,
                    asr_keys,
                    script_surfaces,
                    asr_surfaces,
                    scores,
                )
                selected = max(candidates, key=lambda item: (item.score, -item.priority))
                scores[i][j] = selected.score
                choices[i][j] = selected

        operations: list[AlignmentOperation] = []
        i = 0
        j = 0
        while i < len(script_words) or j < len(recognition_words):
            selected = choices[i][j]
            if selected is None:  # pragma: no cover - protected by DP construction
                raise RuntimeError("alignment traceback is incomplete")
            operations.append(selected.operation)
            i, j = selected.next_i, selected.next_j
        return tuple(operations)

    def _candidates(
        self,
        i: int,
        j: int,
        script_keys: tuple[str, ...],
        asr_keys: tuple[str, ...],
        script_surfaces: tuple[str, ...],
        asr_surfaces: tuple[str, ...],
        scores: list[list[int]],
    ) -> list[_Candidate]:
        n = len(script_keys)
        m = len(asr_keys)
        candidates: list[_Candidate] = []

        if i < n and j < m:
            script_key = script_keys[i]
            asr_key = asr_keys[j]
            if script_key == asr_key and script_key:
                exact_surface = script_surfaces[i] == asr_surfaces[j]
                match_type = (
                    AlignmentMatchType.EXACT
                    if exact_surface
                    else AlignmentMatchType.NORMALIZED
                )
                priority = 0 if match_type is AlignmentMatchType.EXACT else 1
                reward = 1_000 if priority == 0 else 900
                candidates.append(
                    _candidate(
                        scores,
                        reward,
                        priority,
                        i + 1,
                        j + 1,
                        match_type,
                        (i,),
                        (j,),
                        Fraction(1),
                    )
                )
            else:
                similarity = string_similarity(script_key, asr_key)
                if self._fuzzy_allowed(script_key, asr_key, similarity):
                    candidates.append(
                        _candidate(
                            scores,
                            650 + int(similarity * 200),
                            2,
                            i + 1,
                            j + 1,
                            AlignmentMatchType.FUZZY,
                            (i,),
                            (j,),
                            similarity,
                        )
                    )

            if self._settings.enable_split_merge and j + 1 < m:
                if structural_key((script_key,)) == structural_key(
                    (asr_key, asr_keys[j + 1])
                ):
                    candidates.append(
                        _candidate(
                            scores,
                            1_400,
                            3,
                            i + 1,
                            j + 2,
                            AlignmentMatchType.ONE_SCRIPT_TO_MANY_ASR,
                            (i,),
                            (j, j + 1),
                            Fraction(1),
                        )
                    )
            if self._settings.enable_split_merge and i + 1 < n:
                if structural_key((script_key, script_keys[i + 1])) == structural_key(
                    (asr_key,)
                ):
                    candidates.append(
                        _candidate(
                            scores,
                            1_400,
                            3,
                            i + 2,
                            j + 1,
                            AlignmentMatchType.MANY_SCRIPT_TO_ONE_ASR,
                            (i, i + 1),
                            (j,),
                            Fraction(1),
                        )
                    )

            candidates.append(
                _candidate(
                    scores,
                    -650,
                    4,
                    i + 1,
                    j + 1,
                    AlignmentMatchType.SUBSTITUTION,
                    (i,),
                    (j,),
                    string_similarity(script_key, asr_key),
                )
            )

        if i < n:
            candidates.append(
                _candidate(
                    scores,
                    -400,
                    5,
                    i + 1,
                    j,
                    AlignmentMatchType.UNRESOLVED,
                    (i,),
                    (),
                    None,
                )
            )
        if j < m:
            candidates.append(
                _candidate(
                    scores,
                    -350,
                    6,
                    i,
                    j + 1,
                    AlignmentMatchType.UNRESOLVED,
                    (),
                    (j,),
                    None,
                )
            )
        return candidates

    def _fuzzy_allowed(
        self, left: str, right: str, similarity: Fraction
    ) -> bool:
        if not self._settings.enable_fuzzy_matching:
            return False
        if min(len(left), len(right)) < self._settings.min_fuzzy_token_length:
            return False
        threshold = Fraction(self._settings.fuzzy_threshold)
        return similarity >= threshold


def string_similarity(left: str, right: str) -> Fraction:
    """Exact normalized Levenshtein similarity using standard-library integers."""

    if left == right:
        return Fraction(1)
    maximum = max(len(left), len(right))
    if maximum == 0:
        return Fraction(1)
    if not left or not right:
        return Fraction(0)
    if len(left) > len(right):
        left, right = right, left
    previous = list(range(len(left) + 1))
    for row, right_character in enumerate(right, start=1):
        current = [row]
        for column, left_character in enumerate(left, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[column] + 1,
                    previous[column - 1] + (left_character != right_character),
                )
            )
        previous = current
    return Fraction(maximum - previous[-1], maximum)


def _script_key(token: ScriptToken) -> str:
    if token.comparison_key is None:  # pragma: no cover - contract invariant
        raise ValueError("script word has no comparison key")
    return token.comparison_key


def _candidate(
    scores: list[list[int]],
    reward: int,
    priority: int,
    next_i: int,
    next_j: int,
    match_type: AlignmentMatchType,
    script_indices: tuple[int, ...],
    recognition_indices: tuple[int, ...],
    similarity: Fraction | None,
) -> _Candidate:
    return _Candidate(
        score=reward + scores[next_i][next_j],
        priority=priority,
        next_i=next_i,
        next_j=next_j,
        operation=AlignmentOperation(
            match_type=match_type,
            script_indices=script_indices,
            recognition_indices=recognition_indices,
            similarity=similarity,
        ),
    )
