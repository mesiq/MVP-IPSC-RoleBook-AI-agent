"""Query parsing (LLM) -> hybrid search (RAG) -> short LLM conclusion -> verbatim citations."""
import re
from dataclasses import dataclass, field

from . import llm, search as srch
from .registry import detect_disciplines

MAX_EVIDENCE = 10
DISC_NAMES = ["Handgun", "22LR Handgun", "PCC", "Rifle", "Shotgun", "Mini Rifle", "Action Air"]

PARSE_SYS = (
    "You prepare search queries for an IPSC rulebook retrieval system. Respond with JSON only: "
    '{"disciplines": [subset of ' + str(DISC_NAMES) + ' mentioned or clearly implied, else []], '
    '"search_query": "English keywords and any rule numbers, using official IPSC terminology", '
    '"question": "the question rephrased clearly"}'
)

ANSWER_SYS = (
    "You assist IPSC Range Officers. Answer ONLY from the numbered evidence passages. "
    "Interpretations (type=interpretation) override rules; newer interpretations override older ones. "
    "Never quote or invent rule text and never mention rules that are not in the evidence; refer to passages "
    "by their id only. Rely only on passages whose wording directly addresses the question; do not stretch "
    "unrelated passages or infer facts they do not state, and list weak ones under 'considered' or omit them. "
    "If the evidence does not answer the question, say so and use certainty 'low'. "
    "Certainty is 'high' only when a passage explicitly covers the exact situation described; if the situation "
    "involves facts the passages do not mention (e.g. a different action than the one the rule names), "
    "use 'medium' or 'low' and say what is missing. "
    "Respond with JSON only: "
    '{"short_answer": "1-2 sentence direct answer", '
    '"reasoning": "A descriptive explanation of 3-6 sentences in plain prose: state which passages apply '
    "(cite each as [E2] etc.), what each one says in your own words, how they combine (interpretations take "
    "priority over rules), any exceptions or conditions, and the conclusion drawn. Never write only ids.\", "
    '"used": ["E1", ...ids actually relied on], "considered": ["E5", ...ids relevant but not decisive], '
    '"certainty": "high|medium|low", "certainty_reason": "one sentence"}'
)


@dataclass
class Answer:
    interpretation: str = ""
    reasoning: str = ""
    used: list = field(default_factory=list)
    considered: list = field(default_factory=list)
    certainty: str = "low"
    certainty_reason: str = ""
    disciplines: list = field(default_factory=list)
    search_query: str = ""
    result: object = None


def _evidence(res, per_rule_interps=3):
    items, seen = [], set()

    def add(h):
        if h.id not in seen:
            seen.add(h.id)
            items.append(h)

    for h in res.interpretations:
        add(h)
    for h in res.rules:
        add(h)
        for it in h.interpretations[:per_rule_interps]:
            add(it)
    for h in res.manuals:
        add(h)
    return items[:MAX_EVIDENCE]


def format_evidence(items) -> str:
    out = []
    for i, h in enumerate(items, 1):
        scope = h.meta.get("scope", "") if h.doc_type == "interpretation" else ", ".join(h.disciplines)
        out.append(f"[E{i}] type={h.doc_type} ref={h.ref} edition={h.edition_label} scope={scope}\n"
                   f"{h.title}\n{h.text[:1000]}")
    return "\n\n".join(out)


def ask(con, question: str, discipline: str = "", top: int = 8, log=lambda m: None) -> tuple:
    """Returns (Answer, evidence_items). evidence_items[i] corresponds to id E{i+1}."""
    discs = detect_disciplines(discipline) if discipline else None
    query = question
    try:
        p = llm.complete_json(PARSE_SYS, question, log)
        query = p.get("search_query") or question
        if not discs:
            discs = [d for d in p.get("disciplines", []) if d in DISC_NAMES] or detect_disciplines(question)
    except llm.LLMError as e:
        log(f"  query parsing skipped ({e}); using raw question")
        discs = discs or detect_disciplines(question)

    res = srch.search(con, f"{question} {query}" if query != question else question, discs, top)
    items = _evidence(res)
    ans = Answer(disciplines=res.disciplines, search_query=query, result=res)
    if not items:
        ans.interpretation = "No relevant passages found in the indexed documents."
        return ans, items

    try:
        data = llm.complete_json(ANSWER_SYS, f"Question: {question}\n\nEvidence:\n{format_evidence(items)}", log)
    except llm.LLMError as e:
        ans.interpretation = f"LLM unavailable ({e}). Showing retrieved passages only."
        ans.considered = list(range(len(items)))
        return ans, items

    def ids(key):
        out = []
        for x in data.get(key, []) or []:
            try:
                n = int(str(x).lstrip("Ee")) - 1
            except ValueError:
                continue
            if 0 <= n < len(items) and n not in out:
                out.append(n)
        return out

    def label(m):
        n = int(m.group(1)) - 1
        if not 0 <= n < len(items):
            return m.group(0)
        h = items[n]
        if h.doc_type == "rule":
            return f"Rule {h.ref}"
        if h.doc_type == "interpretation":
            return f"{h.ref} ({h.edition_label})"
        return f"Manual {h.ref}"

    def humanize(s):
        s = re.sub(r"(?:\b(?:Rule|Interpretation)s?\s+)?\[?\bE(\d+)\b\]?", label, s)
        s = re.sub(r"\b(Rule [\w.]+|Interpretation \d+ \([^)]*\))\s*\(\s*\1\s*\)", r"\1", s)
        return re.sub(r"\(\s*(Rule [\w.]+|Interpretation \d+ \([^)]*\))\s*\)", r"(\1)", s)

    ans.interpretation = humanize(str(data.get("short_answer") or data.get("interpretation", "")).strip())
    ans.reasoning = humanize(str(data.get("reasoning", "")).strip())
    ans.used = ids("used")
    ans.considered = [i for i in ids("considered") if i not in ans.used]
    cert = str(data.get("certainty", "low")).lower()
    ans.certainty = cert if cert in ("high", "medium", "low") else "low"
    ans.certainty_reason = humanize(str(data.get("certainty_reason", "")).strip())
    # Without any cited evidence the conclusion cannot be trusted.
    if not ans.used:
        ans.certainty = "low"
    return ans, items
