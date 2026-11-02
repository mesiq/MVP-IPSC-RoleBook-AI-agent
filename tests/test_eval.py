"""Retrieval evaluation: each question must surface at least one expected rule/interpretation reference.

Requires the indexed database (`ipsc ingest`). Run with: pytest -m eval
"""
import pytest

from ipsc import search, store
from ipsc.config import DB_PATH

pytestmark = pytest.mark.eval

# (question, disciplines, acceptable refs - a hit on any of them passes)
CASES = [
    ("can a shooter take a sight picture before the start signal", ["Handgun"], {"8.7.1"}),
    ("dry firing before the start signal", ["Handgun"], {"8.7.1"}),
    ("holster requires trigger finger to unlock", ["Handgun"], {"5.2.7.4"}),
    ("law enforcement duty holster", ["Handgun"], {"5.2.8"}),
    ("match director competing in a level IV match", [], {"Interpretation 1"}),
    ("shortcut stepping outside the passageway fault lines", ["22LR Handgun"], {"2.2.1.5"}),
    ("competitor touches handgun after standby before start signal", ["Handgun"], {"8.2.3"}),
    ("pre-match who may compete", ["Handgun"], {"6.6.2"}),
    ("unsafe gun handling finger in trigger guard", ["Handgun"], {"10.5.3.1", "10.5.3.5", "10.5.9"}),
    ("muzzle breaking 180 degree safety angle disqualification", ["Handgun"], {"10.5.2"}),
    ("failure to engage a target procedural penalty", ["Handgun"], {"10.2.1", "10.2.3", "10.2.4"}),
    ("no-shoot hit penalty", ["Handgun"], {"9.4.2", "10.2.1", "10.2.3"}),
    ("reshoot due to range equipment failure", ["Handgun"], {"4.7.1", "4.7.2"}),
    ("how is hit factor calculated", ["Handgun"], {"9.2.1", "9.2.2"}),
    ("minor power factor ammunition velocity chronograph", ["Handgun"], {"5.6.1", "5.6.2", "5.6.3"}),
    ("arbitration appeal to the range master", ["Handgun"], {"11.1.1", "11.1.2", "11.1.3", "11.2.1"}),
    ("scoring target penalties paper targets", ["Handgun"], {"9.1.5", "9.1.6.1"}),
]


@pytest.fixture(scope="module")
def con():
    if not DB_PATH.exists():
        pytest.skip("no index; run `ipsc ingest`")
    return store.connect()


@pytest.mark.parametrize("question,discs,expected", CASES)
def test_retrieval(con, question, discs, expected):
    res = search.search(con, question, discs, top_k=10)
    found = {h.ref for h in res.interpretations + res.rules + res.manuals}
    found |= {r.ref for h in res.rules for r in h.related}
    assert found & expected, f"{question!r}: expected one of {sorted(expected)}, got {sorted(found)}"
