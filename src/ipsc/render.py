"""Printing an Answer or a ChangeReport in the terminal. Kept apart from the logic so a web UI can reuse the data."""
from typing import Callable

import typer

from .answer import Answer
from .changes import ChangeReport, version_segments

Echo = Callable[[str], None]


def print_changes(report: ChangeReport, echo: Echo) -> None:
    """Edition comparison: LLM summary first, then every edition's verbatim text (green new, red removed)."""
    if report.notice:
        echo(f"{report.notice}\nAdd the older/newer PDF (with its .meta.json) to source_data and run 'ipsc ingest'.")
        return
    echo("Editions compared: " + " -> ".join(report.editions))
    if report.topic:
        echo(f"Topic '{report.topic}': checking rules {', '.join(report.topic_refs)}")
    shown_note = f" Showing first {len(report.shown)}." if report.total > len(report.shown) else ""
    echo(f"{report.total} rule(s) differ in wording.{shown_note}")
    echo(f"({report.renumbered} further rule(s) were only renumbered/reformatted - not listed.)")
    if report.overview or report.points:
        echo(f"\nSummary of changes:\n{report.overview}\n")
        for change, text in report.points:
            echo(f"- Rule {change.ref} [{change.kind.upper()}]: {text}")
        echo("\nDetails with verbatim citations:")
    for change in report.shown:
        echo(f"\n- Rule {change.ref}  [{change.kind.upper()}]" + ("  (renumbered)" if change.renumbered else ""))
        for index, version in enumerate(change.versions):
            body = " ".join(typer.style(text, fg="green" if index == len(change.versions) - 1 else "red",
                                        bold=True) if marked else text
                            for text, marked in version_segments(change, index))
            echo(f"  Citation version {version.label}, Rule {version.ref} (p.{version.page_label}):\n    {body}\n"
                 f"    source: {version.link}")


def print_citation(hit, echo: Echo) -> None:
    """One passage exactly as stored in the rulebook, with edition, page and a link to the PDF."""
    kind = {"interpretation": "", "manual": "Manual "}.get(hit.doc_type, "Rule ")
    name = hit.ref if hit.doc_type == "rule" else f"{hit.ref}: {hit.title}"
    echo(f"- {kind}{name}  [{hit.edition_label}, p.{hit.page_label}]")
    if hit.doc_type == "rule" and hit.context:
        echo(f"    section: {hit.context}")
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

    level = labels.get(answer.certainty, answer.certainty.upper())
    reason = f" - {answer.certainty_reason}" if answer.certainty_reason else ""
    echo(f"{labels['certainty']}: {level}{reason}\n")

    echo(f"{labels['rules_used']}:")
    for number in answer.used:
        print_citation(evidence[number], echo)
    if answer.considered:
        echo(f"\n{labels['rules_considered']}:")
        for number in answer.considered:
            print_citation(evidence[number], echo)
