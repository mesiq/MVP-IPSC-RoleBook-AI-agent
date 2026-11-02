"""Printing an Answer. Kept apart from answer.py so a future web UI can reuse Answer as data."""
from typing import Callable

from .answer import Answer

Echo = Callable[[str], None]


def print_citation(hit, echo: Echo) -> None:
    """One passage exactly as stored in the rulebook, with edition, page and a link to the PDF."""
    kind = {"interpretation": "", "manual": "Manual "}.get(hit.doc_type, "Rule ")
    name = hit.ref if hit.doc_type == "rule" else f"{hit.ref}: {hit.title}"
    echo(f"- {kind}{name}  [{hit.edition_label}, p.{hit.page_label}]")
    echo(f'    "{hit.text}"')
    echo(f"    source: {hit.link}")
    if hit.edition_note:
        echo(f"    note: {hit.edition_note}")


def print_answer(answer: Answer, evidence: list, echo: Echo) -> None:
    """Short answer, reasoning, verbatim citations, certainty (headings in the user's language)."""
    labels = answer.labels
    echo(f"\n{labels['short_answer']}:\n{answer.short_answer}\n")
    if answer.reasoning:
        echo(f"{labels['reasoning']}:\n{answer.reasoning}\n")

    echo(f"{labels['rules_used']}:")
    for number in answer.used:
        print_citation(evidence[number], echo)
    if answer.considered:
        echo(f"\n{labels['rules_considered']}:")
        for number in answer.considered:
            print_citation(evidence[number], echo)

    level = labels.get(answer.certainty, answer.certainty.upper())
    reason = f" - {answer.certainty_reason}" if answer.certainty_reason else ""
    echo(f"\n{labels['certainty']}: {level}{reason}")
