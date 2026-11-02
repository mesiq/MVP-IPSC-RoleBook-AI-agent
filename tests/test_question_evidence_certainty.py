from ipsc import certainty, evidence, question


def test_topic_naming_only_the_rulebook_means_all_changes():
    assert question.clean_topic("handgun rulebook changes") == ""
    assert question.clean_topic("sight pictures") == "sight pictures"


def test_change_question_is_recognised_without_llm():
    assert question.looks_like_change_question("what are the changes in the latest PCC rulebook?")
    assert not question.looks_like_change_question("can I take a sight picture?")


def test_language_guess():
    assert question.looks_english("can the shooter take a sight picture?")
    assert not question.looks_english("M\u016f\u017ee st\u0159elec zam\u011b\u0159ovat?")


def test_long_text_is_cut_at_a_sentence_end():
    out = evidence.truncate("First sentence here. " * 100, 200)
    assert out.endswith("[...]") and "First sentence here." in out and len(out) < 230
    assert evidence.truncate("short", 200) == "short"


def test_high_certainty_stays_when_cited_rule_matches_the_question(make_hit):
    rule = make_hit(text="Competitors may not take a sight picture before the start signal.")
    assert certainty.check_certainty("high", [rule], "sight picture start signal")[0] == "high"


def test_high_certainty_is_downgraded_when_cited_rule_is_unrelated(make_hit):
    rule = make_hit(text="Competitors may not take a sight picture before the start signal.")
    level, reason = certainty.check_certainty("high", [rule], "holster police duty belt equipment")
    assert level == "medium" and "downgraded" in reason


def test_no_cited_passage_means_low_certainty(make_hit):
    assert certainty.check_certainty("high", [], "anything")[0] == "low"


def test_scope_is_latest_only_when_the_user_asks_for_the_newest_edition():
    from ipsc.question import _scope
    assert _scope(None, "What changed in the most recent PCC rulebook?") == "latest"
    assert _scope(None, "What changed in the PCC rules since 2019?") == "all"
    assert _scope("latest", "anything") == "latest"
    assert _scope("all", "newest rulebook") == "all"


def test_llm_sees_the_section_heading_that_carries_the_penalty(make_hit):
    rule = make_hit(ref="10.5.10", text="Failure to keep the finger outside the trigger guard.",
                    context="Chapter 10 > 10.5 Disqualification - Unsafe Gun Handling")
    assert "SECTION: Chapter 10 > 10.5 Disqualification - Unsafe Gun Handling" in evidence.format_evidence([rule])
