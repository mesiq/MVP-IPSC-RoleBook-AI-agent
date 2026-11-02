"""Step 3 of answering: choose which passages the LLM sees, and format them as [E1], [E2] ..."""
from . import settings
from .search import Hit, Result


def build_evidence(result: Result) -> list:
    """Interpretations first, then rules (each with its interpretations), then manuals, then context.

    The position in the returned list defines the passage id: item 0 is [E1], item 1 is [E2] ...
    """
    items = []
    seen = set()

    def add(hit: Hit) -> None:
        if hit.id not in seen:
            seen.add(hit.id)
            items.append(hit)

    for hit in result.interpretations:
        add(hit)
    for rule in result.rules:
        add(rule)
        for interpretation in rule.interpretations[:settings.INTERPS_PER_RULE]:
            add(interpretation)
    for manual in result.manuals:
        add(manual)
    items = items[:settings.MAX_EVIDENCE]

    # Parent and sub-rules give context and exceptions; they use their own extra budget.
    for rule in result.rules:
        for related in rule.related:
            if len(items) >= settings.MAX_EVIDENCE + settings.MAX_RELATED:
                break
            if related.id not in seen:
                seen.add(related.id)
                related.cited_by = f"context for {rule.ref}"
                items.append(related)

    return _fit_budget(items)


def _fit_budget(items: list) -> list:
    """Drop trailing passages once the total text would exceed the prompt budget."""
    kept = []
    total = 0
    for hit in items:
        total += min(len(hit.text), settings.MAX_PASSAGE_CHARS)
        if total > settings.MAX_TOTAL_CHARS and kept:
            break
        kept.append(hit)
    return kept


def truncate(text: str, limit: int = 0) -> str:
    """Shorten long text at a sentence end (or word end) instead of in the middle of a word."""
    limit = limit or settings.MAX_PASSAGE_CHARS
    if len(text) <= limit:
        return text
    cut = text[:limit]
    sentence_end = max(cut.rfind(". "), cut.rfind("; "), cut.rfind(": "))
    if sentence_end > limit * 0.5:
        cut = cut[:sentence_end + 1]
    else:
        cut = cut[:cut.rfind(" ")]
    return cut + " [...]"


def format_evidence(items: list) -> str:
    """The text block the LLM reads: one labelled passage per item."""
    blocks = []
    for number, hit in enumerate(items, 1):
        if hit.doc_type == "interpretation":
            scope = hit.meta.get("scope", "")
        else:
            scope = ", ".join(hit.disciplines)
        notes = ""
        if hit.edition_note:
            notes += f" NOTE={hit.edition_note}"
        if hit.cited_by.startswith("context for"):
            notes += f" ({hit.cited_by})"
        header = f"[E{number}] type={hit.doc_type} ref={hit.ref} edition={hit.edition_label} scope={scope}{notes}"
        blocks.append(f"{header}\n{hit.title}\n{truncate(hit.text)}")
    return "\n\n".join(blocks)
