"""Derive document metadata from folder + (inexact) filename."""
import re
from dataclasses import dataclass, field
from pathlib import Path

from .config import FOLDER_TYPES

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_MON = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"

# Order matters: most specific first.
DISCIPLINES = [
    ("22LR Handgun", r"\.?22\s*lr(?:[\s\-_]*handgun)?"),
    ("Mini Rifle", r"mini[\s\-_]*rifle"),
    ("PCC", r"pistol[\s\-_]*caliber[\s\-_]*carbine|\bpcc\b"),
    ("Shotgun", r"shotgun"),
    ("Rifle", r"rifle"),
    ("Handgun", r"handgun"),
    ("Action Air", r"action[\s\-_]*air"),
]


@dataclass
class DocMeta:
    path: Path
    rel_path: str
    doc_type: str
    disciplines: list = field(default_factory=list)  # [] = all / not specific
    edition_year: int = 0
    edition_month: int = 0
    version: int = 1
    title: str = ""
    date_source: str = "filename"  # "pdf" when the edition date was read from the PDF text
    skip: str = ""  # reason the file is not ingested

    @property
    def edition_label(self) -> str:
        if not self.edition_year:
            return "unknown"
        if not self.edition_month:
            return str(self.edition_year)
        name = [k for k, v in MONTHS.items() if v == self.edition_month][0].capitalize()
        return f"{name} {self.edition_year}"

    @property
    def edition_key(self) -> tuple:
        return (self.edition_year, self.edition_month, self.version)


def detect_disciplines(text: str) -> list:
    found = []
    t = text.lower()
    for name, pat in DISCIPLINES:
        if re.search(pat, t):
            found.append(name)
            t = re.sub(pat, " ", t)  # "mini rifle" must not also match "rifle"
    return found


def detect_edition(text: str) -> tuple:
    t = text.replace("_", " ").replace("-", " ")
    # Prefer "<Mon> <Year> Edition" over issue dates like "Final 29 Dec 2025".
    m = re.search(_MON + r"\s*(20\d\d)\s*edition", t, re.I)
    if not m:
        m = re.search(_MON + r"\s*(20\d\d)", t, re.I)
    if m:
        return int(m.group(2)), MONTHS[m.group(1).lower()[:3]]
    m = re.search(r"(20\d\d)", t)
    return (int(m.group(1)), 0) if m else (0, 0)


def edition_from_pdf(doc) -> tuple:
    """Edition (year, month) printed on the cover, e.g. 'JANUARY 2026 EDITION' or 'MAY 2026 INTERPRETATIONS'.

    Returns (0, 0) when the PDF text carries no such statement.
    """
    text = " ".join(" ".join(doc[i].get_text().split()) for i in range(min(2, len(doc))))
    m = re.search(_MON + r"\W{0,3}(20\d\d)\s*(?:edition|interpretations)", text, re.I)
    if m:
        return int(m.group(2)), MONTHS[m.group(1).lower()[:3]]
    m = re.search(r"(20\d\d)\s*(?:edition|interpretations)", text, re.I)
    return (int(m.group(1)), 0) if m else (0, 0)


def classify(path: Path, root: Path) -> DocMeta | None:
    rel = path.relative_to(root)
    doc_type = None
    for part in rel.parts[:-1]:
        doc_type = FOLDER_TYPES.get(part.lower())
        if doc_type:
            break
    if not doc_type:
        return None
    stem = path.stem
    year, month = detect_edition(stem)
    v = re.search(r"\bv(\d+)\b", stem, re.I)
    discs = detect_disciplines(stem) if doc_type != "interpretation" else []
    skip = ""
    if doc_type == "rule" and re.search(r"combined|\d+\s*disciplines", stem, re.I):
        skip = "combined multi-discipline rulebooks are not supported"
    return DocMeta(path, rel.as_posix(), doc_type, discs, year, month,
                   int(v.group(1)) if v else 1, stem, skip=skip)


def scan(root: Path) -> list:
    docs = []
    for p in sorted(root.rglob("*.pdf")):
        if ".venv" in p.parts:
            continue
        d = classify(p, root)
        if d:
            docs.append(d)
    return docs
