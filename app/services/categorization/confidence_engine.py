"""Confidence scoring for categorization layers."""

from __future__ import annotations


def score_confidence(
    *,
    memory_hit: bool = False,
    alias_hit: bool = False,
    regex_hit: bool = False,
) -> float:
    if memory_hit:
        return 0.98
    if alias_hit:
        return 0.90
    if regex_hit:
        return 0.75
    return 0.40


__all__ = ["score_confidence"]
