"""The highlighted-changes PDF: markup rules (no database needed) and a real PDF built from a tiny fake database."""
import pymupdf

from ipsc import redline


def chunk(ref, text, context="Chapter 5 > 5.1 Lasers"):
    return {"ref": ref, "text": text, "context": context, "page_pdf": 1, "page_label": "1"}


def test_added_and_removed_words_are_marked_inline():
    block = redline.rule_block([chunk("5.1", "Lasers are allowed.")], [chunk("5.1", "Lasers are prohibited.")])
    assert '<span class="del">allowed.</span>' in block
    assert '<span class="add">prohibited.</span>' in block
    assert block.count("Lasers") == 1  # unchanged words appear once, unmarked


def test_renumbered_rule_shows_old_number_struck_and_new_number_green():
    block = redline.rule_block([chunk("5.2", "Same text.")], [chunk("5.3", "Same text.")])
    assert '<span class="del">5.2</span> <span class="add">5.3</span>' in block
    assert 'class="add">Same' not in block  # wording itself is unchanged


def test_new_rule_is_all_green_and_removed_rule_is_all_red():
    assert 'class="add">A brand new rule.' in redline.rule_block([], [chunk("5.9", "A brand new rule.")])
    gone = redline.rule_block([chunk("5.8", "A deleted rule.")], [])
    assert 'class="del">A deleted rule.' in gone and 'class="del">5.8' in gone


def test_internal_page_labels_are_not_shown_as_rule_numbers():
    assert "p7" not in redline.rule_block([chunk("p7", "Intro text.")], [chunk("p7", "Intro text.")])


def test_text_is_html_escaped():
    block = redline.rule_block([chunk("5.1", "a < b")], [chunk("5.1", "a < b & c")])
    assert "&lt;" in block and "&amp;" in block and "< b" not in block


def test_headings_are_repeated_only_when_the_section_changes():
    first, levels = redline._headings("Chapter 5 > 5.1 Lasers", [])
    assert "<h2>Chapter 5</h2>" in first and "<h3>5.1 Lasers</h3>" in first
    again, levels = redline._headings("Chapter 5 > 5.1 Lasers", levels)
    assert again == ""
    other, _ = redline._headings("Chapter 5 > 5.2 Dress", levels)
    assert "Chapter 5" not in other and "5.2 Dress" in other


def test_a_real_pdf_is_produced(monkeypatch, tmp_path):
    old = [chunk("5.1", "Lasers are allowed."), chunk("5.2", "Gone soon.")]
    new = [chunk("5.1", "Lasers are prohibited.")]
    for index, item in enumerate(old + new):
        item.update(norm=item["text"].lower(), words=item["text"].lower().split(), vec=None)
    monkeypatch.setattr(redline.changes, "load_chunks", lambda con, doc_id: old if doc_id == 1 else new)
    monkeypatch.setattr(redline, "_images", lambda path, last: ({}, pymupdf.Archive()))
    data = redline.build_redline_pdf(
        None, {"id": 1, "edition_label": "Jan 2025", "path": "a.pdf"},
        {"id": 2, "edition_label": "Jan 2026", "path": "b.pdf"})
    with pymupdf.open(stream=data, filetype="pdf") as pdf:
        text = pdf[0].get_text()
        assert "changes since Jan 2025" in text and "prohibited." in text and "Gone soon." in text
        colours = {span["color"] for block in pdf[0].get_text("dict")["blocks"] for line in block.get("lines", [])
                   for span in line["spans"]}
        assert {0x15803D, 0xB91C1C} <= colours
