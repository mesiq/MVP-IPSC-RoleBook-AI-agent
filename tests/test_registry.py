import json

import pytest

from ipsc import config, registry


def write_pdf_with_sidecar(folder, name, sidecar):
    """Create an empty .pdf and (unless sidecar is None) its .meta.json."""
    folder.mkdir(exist_ok=True)
    pdf = folder / name
    pdf.write_bytes(b"")
    if sidecar is not None:
        registry.sidecar_path(pdf).write_text(sidecar, encoding="utf-8")
    return pdf


def test_sidecar_gives_type_discipline_and_edition(tmp_path):
    pdf = write_pdf_with_sidecar(
        tmp_path / "Rules", "a.pdf", json.dumps({"doc_type": "rule", "discipline": ["PCC"], "edition": "2026-01"}))
    meta = registry.load_meta(pdf, tmp_path)
    assert (meta.doc_type, meta.disciplines, meta.edition_year, meta.edition_month) == ("rule", ["PCC"], 2026, 1)
    assert meta.edition_label == "Jan 2026"


@pytest.mark.parametrize("bad_sidecar", [
    None,  # no sidecar at all
    "{not json",
    '{"doc_type": "novel", "edition": "2026-01"}',
    '{"doc_type": "rule", "discipline": [], "edition": "2026-01"}',  # rules need a discipline
    '{"doc_type": "rule", "discipline": ["Nope"], "edition": "2026-01"}',
    '{"doc_type": "rule", "discipline": ["PCC"], "edition": "2026-13"}',
])
def test_invalid_sidecar_is_rejected(tmp_path, bad_sidecar):
    pdf = write_pdf_with_sidecar(tmp_path / "Rules", "b.pdf", bad_sidecar)
    with pytest.raises(registry.MetaError):
        registry.load_meta(pdf, tmp_path)


def test_scan_reports_files_without_valid_sidecar(tmp_path):
    folder = tmp_path / "Rules"
    write_pdf_with_sidecar(folder, "ok.pdf", '{"doc_type": "manual", "edition": "2021-03"}')
    write_pdf_with_sidecar(folder, "nometa.pdf", None)
    docs, problems = registry.scan(tmp_path)
    assert [d.rel_path for d in docs] == ["Rules/ok.pdf"]
    assert problems[0][0] == "Rules/nometa.pdf"


def test_disciplines_are_found_in_text():
    assert registry.detect_disciplines("IPSC Mini Rifle Rules") == ["Mini Rifle"]  # not also "Rifle"
    assert registry.detect_disciplines("Pistol Caliber Carbine") == ["PCC"]
    assert sorted(registry.detect_disciplines("Handgun and Rifle")) == ["Handgun", "Rifle"]


def test_public_url_replaces_file_link(monkeypatch):
    monkeypatch.setattr(config, "PUBLIC_URL", "https://h/files")
    assert config.source_link("C:/x/a b.pdf", "Rules/a b.pdf", 3) == "https://h/files/Rules/a%20b.pdf#page=3"
