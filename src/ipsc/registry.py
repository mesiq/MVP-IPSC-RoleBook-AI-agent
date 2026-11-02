"""Document metadata comes from a `<file>.meta.json` sidecar next to each PDF:

    {"doc_type": "rule", "discipline": ["Handgun"], "edition": "2026-01"}

doc_type: rule | interpretation | manual. discipline: list (empty = applies to all).
"""
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .config import FOLDER_TYPES

MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
DOC_TYPES = ("rule", "interpretation", "manual")

# Order matters: most specific first. Used to spot disciplines in user questions.
DISCIPLINES = [
    ("22LR Handgun", r"\.?22\s*lr(?:[\s\-_]*handgun)?"),
    ("Mini Rifle", r"mini[\s\-_]*rifle"),
    ("PCC", r"pistol[\s\-_]*caliber[\s\-_]*carbine|\bpcc\b"),
    ("Shotgun", r"shotgun"),
    ("Rifle", r"rifle"),
    ("Handgun", r"handgun"),
    ("Action Air", r"action[\s\-_]*air"),
]
KNOWN_DISCIPLINES = [n for n, _ in DISCIPLINES]


class MetaError(ValueError):
    pass


@dataclass
class DocMeta:
    path: Path
    rel_path: str
    doc_type: str
    disciplines: list = field(default_factory=list)  # [] = all / not specific
    edition_year: int = 0
    edition_month: int = 0

    @property
    def edition_label(self) -> str:
        return f"{MONTH_NAMES[self.edition_month - 1]} {self.edition_year}"


def detect_disciplines(text: str) -> list:
    found = []
    t = text.lower()
    for name, pat in DISCIPLINES:
        if re.search(pat, t):
            found.append(name)
            t = re.sub(pat, " ", t)  # "mini rifle" must not also match "rifle"
    return found


def sidecar_path(pdf: Path) -> Path:
    return pdf.with_name(pdf.name + ".meta.json")


def template(pdf: Path, root: Path) -> str:
    """Best-guess sidecar content for a PDF that has none."""
    rel = pdf.relative_to(root)
    guess = next((FOLDER_TYPES[p.lower()] for p in rel.parts[:-1] if p.lower() in FOLDER_TYPES), "rule")
    discs = detect_disciplines(pdf.stem) if guess == "rule" else []
    return json.dumps({"doc_type": guess, "discipline": discs, "edition": "YYYY-MM"})


def load_meta(pdf: Path, root: Path) -> DocMeta:
    side = sidecar_path(pdf)
    if not side.exists():
        raise MetaError(f"missing {side.name}; create it, e.g. {template(pdf, root)}")
    try:
        raw = json.loads(side.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as e:
        raise MetaError(f"{side.name}: invalid JSON ({e})")
    doc_type = raw.get("doc_type")
    if doc_type not in DOC_TYPES:
        raise MetaError(f"{side.name}: doc_type must be one of {DOC_TYPES}")
    discs = raw.get("discipline", [])
    if isinstance(discs, str):
        discs = [discs]
    bad = [d for d in discs if d not in KNOWN_DISCIPLINES]
    if bad or (doc_type == "rule" and not discs):
        raise MetaError(f"{side.name}: discipline must be a non-empty list (rules) of {KNOWN_DISCIPLINES}"
                        + (f"; unknown: {bad}" if bad else ""))
    m = re.fullmatch(r"(\d{4})-(0[1-9]|1[0-2])", str(raw.get("edition", "")))
    if not m:
        raise MetaError(f"{side.name}: edition must look like 2026-01")
    return DocMeta(pdf, pdf.relative_to(root).as_posix(), doc_type, sorted(discs),
                   int(m.group(1)), int(m.group(2)))


def scan(root: Path) -> tuple:
    """Returns (docs with valid sidecars, [(rel_path, problem)])."""
    docs, problems = [], []
    for p in sorted(root.rglob("*.pdf")):
        try:
            docs.append(load_meta(p, root))
        except MetaError as e:
            problems.append((p.relative_to(root).as_posix(), str(e)))
    return docs, problems
