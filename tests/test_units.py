from ipsc import answer, changes, chunker, registry, search
from ipsc.search import Hit


def make_hit(**kw):
    base = dict(id=1, ref="1.1", title="", text="", page_pdf=1, page_label="1", doc_type="rule", tier=2,
                rel_path="x.pdf", path="x.pdf", edition_label="Jan 2026", disciplines=["Handgun"], meta={})
    base.update(kw)
    return Hit(**base)


def test_split_rule_number_repaired():
    m = chunker.SPLIT_ID.match("10.5. 8 Competitors who")
    assert m and m.group(1) == "10.5" and m.group(2) == "8"


def test_changes_clean_and_tokens_ignore_numbering():
    assert changes._clean("see Rule 10.5. 14 here") == "see Rule 10.5.14 here"
    assert changes._norm("Rule 4.3.2 applies") == changes._norm("Rule 9.9.9 applies")


def test_detect_disciplines():
    assert registry.detect_disciplines("IPSC Mini Rifle Rules") == ["Mini Rifle"]
    assert registry.detect_disciplines("Pistol Caliber Carbine") == ["PCC"]
    assert sorted(registry.detect_disciplines("Handgun and Rifle")) == ["Handgun", "Rifle"]


def test_detect_edition_prefers_edition_over_issue_date():
    assert registry.detect_edition("IPSC Handgun Rules - Jan 2026 Edition - Final 29 Dec 2025") == (2026, 1)
    assert registry.detect_edition("RulesRifle2019") == (2019, 0)


def test_classify_skips_combined(tmp_path):
    (tmp_path / "Rules").mkdir()
    p = tmp_path / "Rules" / "2019RulesCombined5Disciplines_v2.pdf"
    p.write_bytes(b"")
    assert registry.classify(p, tmp_path).skip


def test_clean_topic_and_change_detection():
    assert answer.clean_topic("handgun rulebook changes") == ""
    assert answer.clean_topic("sight pictures") == "sight pictures"
    assert answer.looks_like_change_question("what are the changes in the latest PCC rulebook?")
    assert not answer.looks_like_change_question("can I take a sight picture?")


def test_edition_key_and_relation():
    assert search.edition_key("January 2026") == (2026, 1)
    assert search.edition_key("Jan 2026") == (2026, 1)
    assert search.edition_key("nonsense") is None
    it = make_hit(doc_type="interpretation", meta={"edition": "January 2025"})
    assert search._edition_relation(it, make_hit()) == "older"
    it.meta["edition"] = "January 2026"
    assert search._edition_relation(it, make_hit()) == "same"
    it.meta["edition"] = "July 2026"
    assert search._edition_relation(it, make_hit()) == "newer"
    it.meta = {}
    assert search._edition_relation(it, make_hit()) == "unknown"


def test_truncate_at_sentence():
    text = "First sentence here. " * 100
    out = answer.truncate(text, 200)
    assert out.endswith("[...]") and "First sentence here." in out and len(out) < 230
    assert answer.truncate("short", 200) == "short"


def test_certainty_cap():
    h = make_hit(text="Competitors may not take a sight picture before the start signal.")
    assert answer.cap_certainty("high", [h], "sight picture start signal")[0] == "high"
    assert answer.cap_certainty("high", [h], "holster police duty belt equipment")[0] == "medium"
    assert answer.cap_certainty("low", [h], "holster police duty belt")[0] == "low"


def test_looks_english():
    assert answer.looks_english("can the shooter take a sight picture?")
    assert not answer.looks_english("MÅ¯Å¾e stÅ™elec zamÄ›Å™ovat?")
