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
