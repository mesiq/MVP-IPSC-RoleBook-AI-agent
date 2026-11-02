"""End-to-end `ask()` with a fake LLM and fake search: runs offline, shows question in -> answer out."""
from ipsc import answer, llm
from ipsc.search import Result


def fake_llm(parse_json, answer_json):
    """Replacement for llm.complete_json: first call parses the question, second writes the answer."""
    replies = iter([parse_json, answer_json])
    return lambda system, user, log=None: next(replies)


def test_ask_returns_verbatim_rule_with_readable_reasoning(monkeypatch, make_hit):
    rule = make_hit(id=7, ref="8.7.1", text="Competitors are prohibited from taking a sight picture.")
    monkeypatch.setattr(answer.search_module, "search",
                        lambda con, query, disciplines, top: Result(["Handgun"], [], [rule], []))
    monkeypatch.setattr(llm, "complete_json", fake_llm(
        {"disciplines": ["Handgun"], "search_query": "sight picture", "language": "English", "intent": "answer"},
        {"short_answer": "No.", "reasoning": "Based on [E1] it is prohibited.", "used": ["E1"],
         "considered": [], "certainty": "high", "certainty_reason": "Direct match."}))

    result, evidence = answer.ask(None, "Can I take a sight picture?")

    assert result.reasoning == "Based on Rule 8.7.1 it is prohibited."
    assert [evidence[n].text for n in result.used] == ["Competitors are prohibited from taking a sight picture."]
    assert result.certainty == "high"



def test_ask_routes_change_questions_to_the_comparison_tool(monkeypatch):
    monkeypatch.setattr(llm, "complete_json", lambda system, user, log=None: {
        "disciplines": ["PCC"], "search_query": "", "language": "English", "intent": "changes", "topic": ""})
    result, evidence = answer.ask(None, "What changed in the PCC rulebook?")
    assert result.intent == "changes" and result.disciplines == ["PCC"] and evidence == []


def test_ask_still_shows_passages_when_the_llm_is_down(monkeypatch, make_hit):
    rule = make_hit(id=1, ref="8.7.1", text="Some rule text.")
    monkeypatch.setattr(answer.search_module, "search",
                        lambda con, query, disciplines, top: Result([], [], [rule], []))

    def llm_down(system, user, log=None):
        raise llm.LLMError("offline")
    monkeypatch.setattr(llm, "complete_json", llm_down)

    result, evidence = answer.ask(None, "Can I take a sight picture?")
    assert "LLM unavailable" in result.short_answer and result.considered == [0]
