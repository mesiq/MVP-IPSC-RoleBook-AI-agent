"""Step 5 of answering: a code-side check on the certainty the LLM claims.

The LLM can be over-confident, so "high" is kept only if a cited passage really shares
words with the question.
"""
import re

from . import settings
from .question import COMMON_ENGLISH
from .search import STOP

HIGH, MEDIUM, LOW = "high", "medium", "low"
LEVELS = (HIGH, MEDIUM, LOW)

WORD = re.compile(r"[A-Za-z]{4,}")


def _key_terms(text: str) -> set:
    """Words of 4+ letters, shortened to 5 letters so 'penalty' and 'penalties' match."""
    ignored = COMMON_ENGLISH | STOP
    return {w.lower()[:5] for w in WORD.findall(text) if w.lower() not in ignored}


def parse_level(value: object) -> str:
    """Normalise whatever the LLM returned to high / medium / low (unknown means low)."""
    level = str(value).lower()
    return level if level in LEVELS else LOW


def check_certainty(level: str, cited: list, query: str) -> tuple:
    """Returns (final level, explanation to append, or "" when nothing changed)."""
    if not cited:
        return LOW, ""  # no cited evidence: the conclusion cannot be trusted
    if level != HIGH:
        return level, ""
    question_terms = _key_terms(query)
    if not question_terms:
        return level, ""
    best_share = max(
        len(question_terms & _key_terms(hit.title + " " + hit.text)) / len(question_terms) for hit in cited)
    if best_share < settings.MIN_COVERAGE:
        return MEDIUM, f"downgraded: cited passages cover only {best_share:.0%} of the question's key terms"
    return level, ""
