"""Step 1 of answering: understand the user's question (language, discipline, search words, intent)."""
import re
from dataclasses import dataclass, field
from typing import Callable

from . import llm
from .prompts import PARSE_SYS, TRANSLATE_SYS
from .registry import KNOWN_DISCIPLINES, detect_disciplines

# "what changed in the latest rulebook" needs BOTH a change word and an edition word.
CHANGE_WORDS = re.compile(r"\b(chang\w*|differen\w*|what.?s new|updated?|new rules?|revised|revision)\b", re.I)
LATEST_WORDS = re.compile(r"\b(latest|most recent|newest|current|last)\b", re.I)
EDITION_WORDS = re.compile(r"\b(rule ?books?|editions?|versions?|latest|recent|newest|compared|since)\b", re.I)

# Words that only name the rulebook or discipline, so a topic made of them means "all changes".
GENERIC_TOPIC = re.compile(
    r"\b(rule ?books?|rules?|editions?|versions?|latest|recent|newest|ipsc|competition|"
    r"handgun|pcc|pistol caliber carbine|rifle|shotgun|mini rifle|22\s?lr|changes?|changed|new|"
    r"revisions?|revised|updates?|updated|modifications?|amendments?|differences?)\b", re.I)

COMMON_ENGLISH = set("the and what that this with from have can are for not may when which shall must does".split())
SHORT_ENGLISH = {"is", "a", "of", "to", "in", "it", "do", "i"}


@dataclass
class ParsedQuestion:
    disciplines: list = field(default_factory=list)  # [] = not stated
    search_query: str = ""  # English keywords used for searching
    language: str = "English"  # language of the user's question
    intent: str = "answer"  # "answer" or "changes"
    topic: str = ""  # for "changes": what the user asked about, "" = everything
    scope: str = "all"  # for "changes": "latest" = newest edition vs the one before, "all" = every edition

    @property
    def is_english(self) -> bool:
        return self.language.lower().startswith("english")


def clean_topic(topic: str) -> str:
    """A topic that only names the rulebook or discipline means 'everything'."""
    only_generic_words = not GENERIC_TOPIC.sub(" ", topic or "").strip(" ,.-")
    return "" if only_generic_words else topic.strip()


def looks_like_change_question(question: str) -> bool:
    """Cheap keyword check, used when the LLM is unavailable."""
    return bool(CHANGE_WORDS.search(question) and EDITION_WORDS.search(question))


def looks_english(question: str) -> bool:
    """Rough guess: no accented letters and at least one very common English word."""
    if re.search(r"[^\x00-\x7F]", question):
        return False
    words = re.findall(r"[a-z']+", question.lower())
    return not words or any(w in COMMON_ENGLISH or w in SHORT_ENGLISH for w in words)


def parse_question(question: str, forced_discipline: str = "",
                   log: Callable[[str], None] = lambda m: None) -> ParsedQuestion:
    """Ask the LLM to parse the question; fall back to simple keyword rules if it is unavailable."""
    forced = detect_disciplines(forced_discipline) if forced_discipline else []
    try:
        data = llm.complete_json(PARSE_SYS, question, log)
    except llm.LLMError as error:
        log(f"  query parsing skipped ({error}); using raw question")
        return _parse_without_llm(question, forced, log)

    from_llm = [d for d in data.get("disciplines", []) if d in KNOWN_DISCIPLINES]
    return ParsedQuestion(
        disciplines=forced or from_llm or detect_disciplines(question),
        search_query=data.get("search_query") or data.get("question") or question,
        language=str(data.get("language") or "English").strip() or "English",
        intent="changes" if str(data.get("intent", "")).lower() == "changes" else "answer",
        topic=clean_topic(str(data.get("topic") or "")),
        scope=_scope(data.get("scope"), question),
    )


def _scope(value: object, question: str) -> str:
    """"latest" or "all"; trusts the LLM, otherwise looks for words like "latest" in the question."""
    if str(value or "").lower() in ("latest", "all"):
        return str(value).lower()
    return "latest" if LATEST_WORDS.search(question) else "all"


def _parse_without_llm(question: str, forced: list, log: Callable[[str], None]) -> ParsedQuestion:
    parsed = ParsedQuestion(disciplines=forced or detect_disciplines(question), search_query=question)
    if looks_like_change_question(question):
        parsed.intent = "changes"
        parsed.scope = _scope(None, question)
    if not looks_english(question):
        parsed.language = "the same language as the question"
        parsed.search_query = _translate_to_english(question, log)
    return parsed


def _translate_to_english(question: str, log: Callable[[str], None]) -> str:
    try:
        data = llm.complete_json(TRANSLATE_SYS, question, log)
        return str(data.get("search_query") or question)
    except llm.LLMError:
        log("  WARNING: could not translate the question to English; rules are English, "
            "so results may be poor. Try again later or ask in English.")
        return question
