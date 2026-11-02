from ipsc import changes, chunker, search


def test_rule_number_broken_by_a_space_is_repaired():
    match = chunker.SPLIT_ID.match("10.5. 8 Competitors who")
    assert match and match.group(1) == "10.5" and match.group(2) == "8"


def test_renumbering_is_not_a_change():
    assert changes._norm("Rule 4.3.2 applies") == changes._norm("Rule 9.9.9 applies")


def test_rule_numbers_broken_by_pdf_spacing_are_cleaned():
    assert changes._clean("see Rule 10.5. 14 here") == "see Rule 10.5.14 here"


def test_edition_labels_become_comparable_keys():
    assert search.edition_key("January 2026") == (2026, 1)
    assert search.edition_key("Jan 2026") == (2026, 1)
    assert search.edition_key("nonsense") is None


def test_interpretation_edition_is_compared_with_the_rulebook(make_hit):
    interpretation = make_hit(doc_type="interpretation", meta={"edition": "January 2025"})
    rulebook_hit = make_hit(edition_label="Jan 2026")
    assert search._edition_relation(interpretation, rulebook_hit) == "older"
    interpretation.meta["edition"] = "January 2026"
    assert search._edition_relation(interpretation, rulebook_hit) == "same"
    interpretation.meta["edition"] = "July 2026"
    assert search._edition_relation(interpretation, rulebook_hit) == "newer"
    interpretation.meta = {}
    assert search._edition_relation(interpretation, rulebook_hit) == "unknown"
