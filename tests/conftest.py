"""Shared helpers for the tests."""
from pathlib import Path

import pytest

from ipsc.search import Hit


@pytest.fixture
def make_hit():
    """Build a rule passage for tests; override any field with keyword arguments."""
    def build(**fields) -> Hit:
        values = dict(id=1, ref="1.1", title="", text="", page_pdf=1, page_label="1", doc_type="rule", tier=2,
                      rel_path="x.pdf", path=str(Path("x.pdf").resolve()), edition_label="Jan 2026",
                      disciplines=["Handgun"], meta={})
        values.update(fields)
        return Hit(**values)
    return build
