"""Categorization intelligence package."""

from .confidence_engine import score_confidence
from .description_cleaner import clean_description
from .merchant_extractor import extract_merchant_key
from .merchant_memory_service import (
    add_alias,
    learn,
    lookup,
    record_feedback,
    update_usage,
)

__all__ = [
    "add_alias",
    "clean_description",
    "extract_merchant_key",
    "learn",
    "lookup",
    "record_feedback",
    "score_confidence",
    "update_usage",
]
