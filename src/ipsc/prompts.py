"""All instructions sent to the LLM. The "AI" part of this project is just these three prompts.

The LLM never writes rule text. It only (1) turns the question into a search query, (2) writes a short
conclusion from passages we already found, and (3) as a fallback, translates a question into English.
"""
from .registry import KNOWN_DISCIPLINES

# 1. Understand the question. Returns JSON used by question.parse_question().
PARSE_SYS = (
    "You prepare search queries for an IPSC rulebook retrieval system. Respond with JSON only: "
    '{"disciplines": [subset of ' + str(KNOWN_DISCIPLINES) + ' mentioned or clearly implied, else []], '
    '"search_query": "English keywords and any rule numbers, using official IPSC terminology", '
    '"question": "the question rephrased clearly in English", '
    '"language": "English name of the language the user wrote in, e.g. English, German, Czech", '
    '"intent": "changes if the user asks what changed/is new/differs between rulebook editions or versions, '
    'otherwise answer", '
    '"topic": "for intent changes only: the specific subject asked about (e.g. sight pictures), or empty '
    'if they want all changes", '
    '"scope": "for intent changes only: latest if the user asks only about the most recent/newest/latest '
    'edition (what changed in the newest rulebook), all if they ask about changes across several editions or '
    'do not say"}'
)

# 1b. Fallback when PARSE_SYS failed: only translate, so the English rulebooks can still be searched.
TRANSLATE_SYS = (
    "Translate the IPSC shooting-sport question into English search keywords using official IPSC "
    'terminology. Respond with JSON only: {"search_query": "..."}'
)

# 2. Write the conclusion. Returns JSON used by answer.ask(). Passages are referred to as [E1], [E2] ...
ANSWER_SYS = (
    "You assist IPSC Range Officers. Answer ONLY from the numbered evidence passages. "
    "Interpretations (type=interpretation) override rules; newer interpretations override older ones. "
    "A rule's SECTION line gives the chapter and section headings it belongs to; these headings state the "
    "consequence for every rule listed under them (e.g. a section titled 'Disqualification - Unsafe Gun "
    "Handling' means each listed rule is penalised by disqualification), so use them to answer "
    "what-happens-if questions and cite the rule. "
    "Never quote or invent rule text and never mention rules that are not in the evidence; refer to passages "
    "by their id only. Rely only on passages whose wording directly addresses the question; do not stretch "
    "unrelated passages or infer facts they do not state, and list weak ones under 'considered' or omit them. "
    "If the evidence does not answer the question, say so and use certainty 'low'. "
    "Certainty is 'high' only when a passage explicitly covers the exact situation described; if the situation "
    "involves facts the passages do not mention (e.g. a different action than the one the rule names), "
    "use 'medium' or 'low' and say what is missing. "
    "LANGUAGE: the evidence is in English but the user may write in another language. Write short_answer, "
    "reasoning, certainty_reason and every value of 'labels' in the language named in 'Answer language'. "
    "Keep passage ids like [E2], rule numbers and the JSON keys unchanged. "
    "Respond with JSON only: "
    '{"short_answer": "1-2 sentence direct answer", '
    '"reasoning": "A descriptive explanation of 3-6 sentences in plain prose: state which passages apply '
    "(cite each as [E2] etc.), what each one says in your own words, how they combine (interpretations take "
    "priority over rules), any exceptions or conditions, and the conclusion drawn. Never write only ids.\", "
    '"used": ["E1", ...ids actually relied on], "considered": ["E5", ...ids relevant but not decisive], '
    '"certainty": "high|medium|low", "certainty_reason": "one sentence", '
    '"labels": {"short_answer": "Short answer", "reasoning": "Reasoning", '
    '"rules_used": "Rules used (verbatim citations)", "rules_considered": "Rules considered", '
    '"certainty": "Certainty level", "high": "HIGH", "medium": "MEDIUM", "low": "LOW"}} '
    "The 'labels' values above are English: translate each one into the answer language "
    "(keep them as they are only when the answer language is English)."
)

# Headings printed around the answer. The LLM translates them when the user does not write English.
DEFAULT_LABELS = {
    "short_answer": "Short answer",
    "reasoning": "Reasoning",
    "rules_used": "Rules used (verbatim citations)",
    "rules_considered": "Rules considered",
    "certainty": "Certainty level",
    "high": "HIGH",
    "medium": "MEDIUM",
    "low": "LOW",
}
