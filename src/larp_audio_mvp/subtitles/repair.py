"""Bounded post-segmentation repair for grammatically stranded fragments."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass


_OPENERS = frozenset(
    {
        "after", "and", "at", "because", "before", "but", "by", "during",
        "for", "from", "if", "in", "of", "on", "to", "when", "while",
        "with", "without",
    }
)
_DETERMINERS = frozenset(
    {"a", "an", "any", "her", "his", "its", "my", "our", "several", "that", "the", "their", "this", "your"}
)


@dataclass(frozen=True, slots=True)
class OrphanRepairMetrics:
    inspected_boundaries: int
    direct_merges: int
    rebalanced_boundaries: int
    elapsed_nanoseconds: int = 0


def is_incomplete_boundary(
    keys: Sequence[str], position: int, protected: frozenset[int]
) -> bool:
    """Return whether a cut strands a bounded local grammatical construction."""

    if not 0 < position < len(keys):
        return False
    if position in protected:
        return True
    final = keys[position - 1]
    if final in _OPENERS:
        return True
    if position >= 2 and keys[position - 2] in _OPENERS and final in _DETERMINERS:
        return True
    return False


def orphan_fragment_count(
    ranges: Sequence[tuple[int, int]],
    keys: Sequence[str],
    protected: frozenset[int],
) -> int:
    return sum(
        right_end - right_start <= 3
        and is_incomplete_boundary(keys, left_end, protected)
        for (_left_start, left_end), (right_start, right_end) in zip(ranges, ranges[1:])
    )


def repair_orphan_ranges(
    ranges: Sequence[tuple[int, int]],
    *,
    keys: Sequence[str],
    protected: frozenset[int],
    mandatory: frozenset[int],
    candidate_is_valid: Callable[[int, int], bool],
) -> tuple[tuple[tuple[int, int], ...], OrphanRepairMetrics]:
    """Merge or locally move invalid boundaries without changing word order."""

    repaired = list(ranges)
    inspected = direct_merges = rebalanced = 0
    index = 0
    while index < len(repaired) - 1:
        left_start, boundary = repaired[index]
        right_start, right_end = repaired[index + 1]
        if boundary != right_start:
            raise ValueError("subtitle ranges must be contiguous")
        inspected += 1
        if boundary in mandatory or not is_incomplete_boundary(keys, boundary, protected):
            index += 1
            continue
        if candidate_is_valid(left_start, right_end):
            repaired[index : index + 2] = [(left_start, right_end)]
            direct_merges += 1
            index = max(0, index - 1)
            continue
        alternatives: list[tuple[tuple[int, int, int], int]] = []
        for proposed in range(left_start + 1, right_end):
            if proposed == boundary or proposed in mandatory:
                continue
            if is_incomplete_boundary(keys, proposed, protected):
                continue
            if not candidate_is_valid(left_start, proposed):
                continue
            if not candidate_is_valid(proposed, right_end):
                continue
            left_width = proposed - left_start
            right_width = right_end - proposed
            alternatives.append(
                ((abs(left_width - right_width), abs(proposed - boundary), proposed), proposed)
            )
        if alternatives:
            proposed = min(alternatives)[1]
            repaired[index : index + 2] = [
                (left_start, proposed),
                (proposed, right_end),
            ]
            rebalanced += 1
        index += 1
    return tuple(repaired), OrphanRepairMetrics(
        inspected_boundaries=inspected,
        direct_merges=direct_merges,
        rebalanced_boundaries=rebalanced,
    )
