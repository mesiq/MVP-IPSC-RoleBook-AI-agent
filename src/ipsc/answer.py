"""The question-answering pipeline. `ask()` reads like a recipe:

    1. understand the question   (question.py, LLM)
    2. search the rulebooks      (search.py, no LLM)
    3. pick the evidence         (evidence.py)
    4. write a short conclusion  (LLM, using prompts.ANSWER_SYS)
    5. check the certainty       (certainty.py)

Rule text is never produced by the LLM. The answer only lists *which* passages were used; the CLI then
prints those passages verbatim from the database.
"""
import re
from dataclasses import dataclass, field
from typing import Callable

from . import certainty, llm
from . import search as search_module
from .evidence import build_evidence, format_evidence
from .prompts import ANSWER_SYS, DEFAULT_LABELS
from .question import ParsedQuestion, parse_question

Log = Callable[[str], None]


@dataclass
class Answer:
    short_answer: str = ""
    reasoning: str = ""
    used: list = field(default_factory=list)  # positions in the evidence list of passages relied on
    considered: list = field(default_factory=list)  # positions of passages that were relevant, not decisive
    certainty: str = certainty.LOW
    certainty_reason: str = ""
    disciplines: list = field(default_factory=list)
    search_query: str = ""
    intent: str = "answer"  # "changes" means: hand over to the edition-comparison tool
    topic: str = ""
    language: str = "English"
    labels: dict = field(default_factory=lambda: dict(DEFAULT_LABELS))  # headings in the user's language
    result: object = None  # the raw search result, for debugging


def ask(con, question: str, discipline: str = "", top: int = 8, log: Log = lambda m: None) -> tuple:
    """Answer one question. Returns (Answer, evidence); evidence[i] is the passage called [E{i+1}]."""
    parsed = parse_question(question, discipline, log)
    if parsed.intent == "changes":
        return _changes_request(parsed), []

    result = search_module.search(con, _search_text(question, parsed), parsed.disciplines, top)
    evidence = build_evidence(result)
    answer = Answer(disciplines=result.disciplines, search_query=parsed.search_query,
                    language=parsed.language, result=result)
    if not evidence:
        answer.short_answer = "No relevant passages found in the indexed documents."
        return answer, evidence

    try:
        prompt = (f"Answer language: {parsed.language}\nQuestion: {question}\n\n"
                  f"Evidence:\n{format_evidence(evidence)}")
        data = llm.complete_json(ANSWER_SYS, prompt, log)
    except llm.LLMError as error:
        answer.short_answer = f"LLM unavailable ({error}). Showing retrieved passages only."
        answer.considered = list(range(len(evidence)))
        return answer, evidence

    _fill_from_llm(answer, data, evidence, parsed)
    return answer, evidence


def _changes_request(parsed: ParsedQuestion) -> Answer:
    return Answer(disciplines=parsed.disciplines, search_query=parsed.search_query, intent="changes",
                  topic=parsed.topic, language=parsed.language)


def _search_text(question: str, parsed: ParsedQuestion) -> str:
    """English questions are searched with their own words plus the parsed keywords.

    Rules are English, so a non-English question is searched only through its English keywords.
    """
    if parsed.is_english and parsed.search_query != question:
        return f"{question} {parsed.search_query}"
    return parsed.search_query


def _fill_from_llm(answer: Answer, data: dict, evidence: list, parsed: ParsedQuestion) -> None:
    """Copy the LLM's JSON into the Answer, converting passage ids like E2 into readable names."""
    def readable(text: object) -> str:
        return _humanize(str(text).strip(), evidence, parsed.is_english)

    answer.short_answer = readable(data.get("short_answer") or "")
    answer.reasoning = readable(data.get("reasoning") or "")
    answer.used = _passage_numbers(data.get("used"), len(evidence))
    answer.considered = [n for n in _passage_numbers(data.get("considered"), len(evidence))
                         if n not in answer.used]
    answer.certainty_reason = readable(data.get("certainty_reason") or "")

    labels = data.get("labels")
    if isinstance(labels, dict):
        answer.labels.update({key: str(value).strip() for key, value in labels.items()
                              if key in DEFAULT_LABELS and str(value).strip()})

    level = certainty.parse_level(data.get("certainty", certainty.LOW))
    cited = [evidence[n] for n in answer.used]
    answer.certainty, downgrade_reason = certainty.check_certainty(level, cited, parsed.search_query)
    if downgrade_reason:
        answer.certainty_reason = f"{answer.certainty_reason} ({downgrade_reason})".strip()


def _passage_numbers(ids: object, count: int) -> list:
    """['E2', 'E5'] -> [1, 4]. Ignores unknown or repeated ids."""
    numbers = []
    for item in ids or []:
        try:
            number = int(str(item).lstrip("Ee")) - 1
        except ValueError:
            continue
        if 0 <= number < count and number not in numbers:
            numbers.append(number)
    return numbers


def _humanize(text: str, evidence: list, english: bool) -> str:
    """Replace passage ids such as [E2] by 'Rule 8.7.1' or 'Interpretation 1 (Oct 2025)'."""
    def name(match: re.Match) -> str:
        number = int(match.group(1)) - 1
        if not 0 <= number < len(evidence):
            return match.group(0)
        hit = evidence[number]
        if hit.doc_type == "rule":
            # in other languages the answer text already carries the local word for "rule"
            return f"Rule {hit.ref}" if english else hit.ref
        if hit.doc_type == "interpretation":
            return f"{hit.ref} ({hit.edition_label})"
        return f"Manual {hit.ref}"

    text = re.sub(r"(?:\b(?:Rule|Interpretation)s?\s+)?\[?\bE(\d+)\b\]?", name, text)
    # tidy "Rule 8.7.1 (Rule 8.7.1)" and "(Rule 8.7.1)" produced by the replacement above
    text = re.sub(r"\b(Rule [\w.]+|Interpretation \d+ \([^)]*\))\s*\(\s*\1\s*\)", r"\1", text)
    return re.sub(r"\(\s*(Rule [\w.]+|Interpretation \d+ \([^)]*\))\s*\)", r"(\1)", text)
