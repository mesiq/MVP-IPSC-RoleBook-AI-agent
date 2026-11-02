"""The web layer, tested offline: the question pipeline is replaced by canned results."""
import pytest
from fastapi.testclient import TestClient

from ipsc import store
from ipsc.changes import Change, ChangeReport, Version
from ipsc.web import app as web
from ipsc.web.limits import JobSlots, RateLimiter
from ipsc.web.schemas import AnswerOut, Citation, to_changes

QUOTE = "Competitors are prohibited from taking a sight picture."


@pytest.fixture
def data_dir(tmp_path):
    folder = tmp_path / "source_data"
    folder.mkdir()
    (folder / "rules.pdf").write_bytes(b"%PDF-1.4 fake")
    (folder / "notes.txt").write_text("not a pdf")
    (tmp_path / "secret.pdf").write_bytes(b"%PDF-1.4 outside the data folder")
    return folder


@pytest.fixture
def client(tmp_path, data_dir):
    db = tmp_path / "test.sqlite"
    store.connect(db).close()  # empty database with the schema
    return TestClient(web.create_app(db, data_dir))


def canned_answer(*args):
    cite = Citation(kind="rule", ref="8.7.1", title="", text=QUOTE, edition="Jan 2026", page="22",
                    link="/files/rules.pdf#page=28")
    return AnswerOut(short_answer="No.", reasoning="See Rule 8.7.1.", certainty="high", certainty_reason="",
                     labels={"short_answer": "Short answer", "reasoning": "Reasoning",
                             "rules_used": "Rules used", "rules_considered": "Considered",
                             "certainty": "Certainty", "high": "HIGH"},
                     language="English", disciplines=["Handgun"], used=[cite], considered=[])


def test_answer_page_shows_verbatim_rule_and_pdf_link(client, monkeypatch):
    monkeypatch.setattr(web, "answer_question", canned_answer)
    page = client.post("/ask", data={"question": "Can I take a sight picture?"})
    assert page.status_code == 200
    assert QUOTE in page.text and "/files/rules.pdf#page=28" in page.text
    assert "<html" in page.text  # a plain browser request gets the whole page


def test_htmx_request_gets_only_the_result_block(client, monkeypatch):
    monkeypatch.setattr(web, "answer_question", canned_answer)
    reply = client.post("/ask", data={"question": "Q?"}, headers={"HX-Request": "true"})
    assert QUOTE in reply.text and "<html" not in reply.text


def test_empty_and_too_long_questions_get_a_friendly_message(client):
    assert "Please type a question" in client.post("/ask", data={"question": "  "}).text
    assert "under 500 characters" in client.post("/ask", data={"question": "x" * 501}).text


def test_unknown_discipline_is_rejected(client):
    assert "Unknown discipline" in client.post("/ask", data={"question": "Q?", "discipline": "Darts"}).text


def test_rate_limit_stops_a_visitor_who_asks_too_often(tmp_path, data_dir, monkeypatch):
    monkeypatch.setattr(web, "RateLimiter", lambda: RateLimiter(max_requests=2, window=60))
    monkeypatch.setattr(web, "answer_question", canned_answer)
    db = tmp_path / "t.sqlite"
    store.connect(db).close()
    limited = TestClient(web.create_app(db, data_dir))
    replies = [limited.post("/ask", data={"question": "Q?"}).text for _ in range(3)]
    assert QUOTE in replies[0] and QUOTE in replies[1]
    assert "Too many requests" in replies[2]
    assert limited.post("/api/ask", json={"question": "Q?"}).status_code == 429


def test_busy_server_says_so(tmp_path, data_dir, monkeypatch):
    monkeypatch.setattr(web, "JobSlots", lambda: JobSlots(size=0, wait=0))
    db = tmp_path / "t.sqlite"
    store.connect(db).close()
    busy = TestClient(web.create_app(db, data_dir))
    assert "busy" in busy.post("/ask", data={"question": "Q?"}).text
    assert busy.post("/api/ask", json={"question": "Q?"}).status_code == 503


def test_json_api_returns_the_same_answer(client, monkeypatch):
    monkeypatch.setattr(web, "answer_question", canned_answer)
    body = client.post("/api/ask", json={"question": "Q?"}).json()
    assert body["used"][0]["text"] == QUOTE and body["certainty"] == "high"
    assert client.get("/api/health").json() == {"status": "ok"}
    assert "Handgun" in client.get("/api/disciplines").json()


def test_pdfs_are_served_but_nothing_else(client):
    assert client.get("/files/rules.pdf").content.startswith(b"%PDF")
    assert client.get("/files/notes.txt").status_code == 404
    assert client.get("/files/missing.pdf").status_code == 404
    assert client.get("/files/..%2Fsecret.pdf").status_code == 404
    assert client.get("/files/../secret.pdf").status_code == 404


def test_pdf_supports_range_requests_for_mobile_viewers(client):
    reply = client.get("/files/rules.pdf", headers={"Range": "bytes=0-3"})
    assert reply.status_code == 206 and reply.content == b"%PDF"


def test_sources_and_other_pages_render(client):
    for path in ("/", "/changes", "/sources", "/api/sources"):
        assert client.get(path).status_code == 200


def test_responses_carry_security_headers(client):
    headers = client.get("/").headers
    assert "default-src 'self'" in headers["content-security-policy"]
    assert headers["x-content-type-options"] == "nosniff"


def test_changes_are_marked_for_display(tmp_path):
    doc = {"edition_label": "Jan 2025", "path": tmp_path / "a.pdf", "rel_path": "a.pdf"}
    new_doc = {"edition_label": "Jan 2026", "path": tmp_path / "b.pdf", "rel_path": "b.pdf"}
    old = Version(doc, "5.1", "Lasers are allowed.", 1, "1")
    new = Version(new_doc, "5.1", "Lasers are prohibited.", 1, "1")
    report = ChangeReport(discipline="Handgun", editions=["Jan 2025", "Jan 2026"], total=1,
                          shown=[Change("5.1", "changed", [old, new])])
    out = to_changes(report)
    older, newer = out.changes[0].versions
    assert [s.text for s in older.segments if s.marked] == ["allowed."]
    assert [s.text for s in newer.segments if s.marked] == ["prohibited."]
    assert newer.newest and not older.newest


def test_changes_page_offers_redline_download(client, monkeypatch, tmp_path):
    doc = {"edition_label": "Jan 2025", "path": tmp_path / "a.pdf", "rel_path": "a.pdf"}
    new_doc = {"edition_label": "Jan 2026", "path": tmp_path / "b.pdf", "rel_path": "b.pdf"}
    old = Version(doc, "5.1", "Lasers are allowed.", 1, "1")
    new = Version(new_doc, "5.1", "Lasers are prohibited.", 1, "1")
    report = ChangeReport(discipline="Handgun", editions=["Jan 2025", "Jan 2026"], total=1,
                          shown=[Change("5.1", "changed", [old, new])])
    monkeypatch.setattr(web, "compare_editions", lambda *args: to_changes(report))
    page = client.post("/changes", data={"discipline": "Handgun", "topic": "", "scope": "all"})
    assert "Download highlighted PDF" in page.text
    assert 'name="older"' in page.text and 'name="newer"' in page.text
    assert 'value="Jan 2025"' in page.text and 'value="Jan 2026"' in page.text


def test_redline_download_returns_pdf(client, monkeypatch):
    monkeypatch.setattr(web, "redline_pdf", lambda *args: ("x.pdf", b"%PDF-1.4\\n%fake"))
    reply = client.post("/changes/redline", data={"discipline": "Handgun", "older": "Jan 2025", "newer": "Jan 2026"})
    assert reply.status_code == 200
    assert reply.headers["content-type"].startswith("application/pdf")
    assert 'attachment; filename="x.pdf"' in reply.headers["content-disposition"]
    assert reply.content.startswith(b"%PDF")
