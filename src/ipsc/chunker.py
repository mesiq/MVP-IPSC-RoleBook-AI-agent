"""PDF text extraction (line level, with geometry) and chunking."""
import re
from dataclasses import dataclass, field

import pymupdf

RULE_ID = re.compile(r"^(\d{1,2}(?:\.\d{1,2}){1,5})\.?(?:\s+(.*))?$")
# Some PDFs print a stray space inside a rule number at line start: "10.5. 8 Using ..."
SPLIT_ID = re.compile(r"^(\d{1,2}(?:\.\d{1,2})+)\.\s+(\d{1,2})(?=\s+[A-Z(\"“]|$)")
APPENDIX = re.compile(r"^(APPENDIX\s+[A-Z]\d*)\s*[:\-â€“]?\s*(.*)$")
CHAPTER = re.compile(r"^CHAPTER\s+(\d+)\s*[:\-â€“]?\s*(.*)$", re.I)
ROMAN = re.compile(r"^[ivxlc]+$|^\d{1,3}$")
HEADER = re.compile(r"^IPSC .*(Rules|Manual|Handbook).*(Edition|\d{4})", re.I)
FOOTER = re.compile(r"^(Copyright|Â©)", re.I)
MAX_CHARS = 1800


@dataclass
class Line:
    x0: float
    y0: float
    text: str


@dataclass
class Chunk:
    ref: str            # rule number / interpretation number / appendix id
    title: str
    text: str
    context: str        # breadcrumb used to enrich embeddings
    page_pdf: int       # 1-based PDF page index (used in #page= links)
    page_label: str     # printed page number
    meta: dict = field(default_factory=dict)


def _strike_lines(page) -> list:
    """Thin horizontal lines drawn through text mid-height (marked-up PDFs: deleted wording)."""
    out = []
    for dr in page.get_drawings():
        r = dr["rect"]
        col = dr.get("fill") or dr.get("color")
        red = col is not None and len(col) == 3 and col[0] > 0.7 and col[1] < 0.3 and col[2] < 0.3
        if red and r.height < 3 and r.width > 3:
            out.append((r.x0, r.x1, (r.y0 + r.y1) / 2))
    return out


def _char_struck(bbox, strikes) -> bool:
    x0, y0, x1, y1 = bbox
    h, cx = y1 - y0, (x0 + x1) / 2
    return h > 0 and any(sx0 - 0.5 <= cx <= sx1 + 0.5 and y0 + 0.3 * h <= sy <= y0 + 0.7 * h
                         for sx0, sx1, sy in strikes)


def page_lines(page) -> list:
    out = []
    h = page.rect.height
    strikes = _strike_lines(page)
    if strikes:
        blocks = page.get_text("rawdict")["blocks"]
    else:
        blocks = page.get_text("dict")["blocks"]
    for block in blocks:
        for pdf_line in block.get("lines", []):
            if strikes:
                t = "".join(c["c"] for s in pdf_line["spans"] for c in s["chars"]
                            if not _char_struck(c["bbox"], strikes))
            else:
                t = "".join(s["text"] for s in pdf_line["spans"])
            t = t.replace("\xa0", " ").strip()
            if t:
                out.append(Line(pdf_line["bbox"][0], pdf_line["bbox"][1], t))
    out.sort(key=lambda line: (round(line.y0), line.x0))
    return out, h


def is_toc(lines) -> bool:
    if not lines:
        return False
    dots = sum(1 for line in lines if re.search(r"\.{5,}", line.text))
    return dots / len(lines) > 0.25


def strip_page_furniture(lines, height):
    """Remove running headers, footers and page numbers; return (lines, label)."""
    label = ""
    kept = []
    for line in lines:
        top, bottom = line.y0 < height * 0.08, line.y0 > height * 0.93
        if (top or bottom) and (HEADER.match(line.text) or FOOTER.search(line.text)):
            continue
        if (top or bottom) and ROMAN.match(line.text):
            label = line.text
            continue
        kept.append(line)
    return kept, label


def _split_long(text: str, limit=MAX_CHARS) -> list:
    if len(text) <= limit:
        return [text]
    parts, cur = [], ""
    for sent in re.split(r"(?<=[.;:])\s+", text):
        if cur and len(cur) + len(sent) > limit:
            parts.append(cur)
            cur = sent
        else:
            cur = f"{cur} {sent}".strip()
    if cur:
        parts.append(cur)
    return parts


def chunk_numbered(doc: pymupdf.Document) -> list:
    """Rulebooks and manuals: one chunk per numbered rule/section/appendix."""
    chunks, cur = [], None
    chapter = section = ""

    def flush():
        nonlocal cur, section
        c, cur = cur, None
        if not c:
            return
        body = re.sub(r"\s+", " ", c["text"]).strip()
        if not body:
            return
        if c["heading"] and len(body) <= 120:
            section = f"{c['ref']} {body}"  # pure heading: context only
            return
        crumbs = " > ".join(x for x in (chapter, section if not c["ref"].startswith("Appendix") else "") if x)
        title = c["title"]
        pieces = _split_long(body)
        for i, piece in enumerate(pieces):
            ref = c["ref"] if len(pieces) == 1 else f"{c['ref']} (part {i + 1})"
            chunks.append(Chunk(ref, title, piece, crumbs, c["page"], c["label"]))

    for pno, page in enumerate(doc, 1):
        lines, h = page_lines(page)
        if is_toc(lines):
            continue
        lines, label = strip_page_furniture(lines, h)
        if not lines:
            continue
        margin = min(line.x0 for line in lines)
        for line in lines:
            txt = SPLIT_ID.sub(r"\1.\2", line.text)
            m_ch, m_ap = CHAPTER.match(txt), APPENDIX.match(txt)
            m_id = RULE_ID.match(txt) if line.x0 <= margin + 100 else None
            if m_id and m_id.group(2) and not re.match(r"[A-Z(\"“]", m_id.group(2)):
                m_id = None  # e.g. wrapped "1.5 meters ..." is not a rule number
            if m_ch:
                flush()
                chapter = f"Chapter {m_ch.group(1)}: {m_ch.group(2)}".strip(" :")
                section = ""
                continue
            if m_ap:
                flush()
                chapter = f"{m_ap.group(1).title()}: {m_ap.group(2)}".strip(" :")
                section = ""
                cur = dict(ref=m_ap.group(1).title(), title=m_ap.group(2), text="", page=pno,
                           label=label, heading=False)
                continue
            if m_id:
                flush()
                rid, rest = m_id.group(1), m_id.group(2) or ""
                cur = dict(ref=rid, title="", text=rest, page=pno, label=label,
                           heading=rid.count(".") == 1)
                continue
            if cur is None:
                cur = dict(ref=f"p{pno}", title="", text="", page=pno, label=label, heading=False)
            cur["text"] += " " + txt
    flush()
    return chunks

def _manual_lines(page):
    out = []
    for b in page.get_text("dict")["blocks"]:
        for pdf_line in b.get("lines", []):
            sp = [s for s in pdf_line["spans"] if s["text"].strip()]
            if not sp:
                continue
            text = "".join(s["text"] for s in sp).replace("\xa0", " ").strip()
            bold = all((s["flags"] & 16) or "bold" in s["font"].lower() for s in sp)
            big = max(s["size"] for s in sp) >= 13
            out.append((text, bold or big, pdf_line["bbox"][1]))
    return out


def chunk_manual(doc: pymupdf.Document) -> list:
    """Manuals: body text grouped under the nearest preceding bold/large heading."""
    chunks, heading, buf, buf_page, buf_label = [], "", [], 1, ""
    last_was_heading = False

    def flush():
        nonlocal buf
        text = re.sub(r"\s+", " ", " ".join(buf)).strip()
        buf = []
        if len(text) < 40:
            return
        for i, piece in enumerate(_split_long(text, 1200)):
            ref = heading or f"p.{buf_label}"
            chunks.append(Chunk(ref + (f" (part {i + 1})" if i else ""), heading, piece, heading,
                                buf_page, buf_label))

    for pno, page in enumerate(doc, 1):
        lines = _manual_lines(page)
        h = page.rect.height
        digits = sum(1 for t, _, _ in lines if re.fullmatch(r"\d{1,3}", t))
        if digits >= 6 and any(re.fullmatch(r"(Index|Contents|Table of Contents)", t, re.I) for t, _, _ in lines):
            continue  # table of contents
        label = next((t for t, _, y in lines if y > h * 0.9 and re.fullmatch(r"\d{1,3}", t)), "")
        label = label or next((t for t, _, y in lines if y < h * 0.08 and re.fullmatch(r"\d{1,3}", t)), str(pno))
        for text, is_head, y in lines:
            if FOOTER.search(text) or HEADER.match(text) or re.fullmatch(r"\d{1,3}", text):
                continue
            if is_head and len(text) <= 110:
                if last_was_heading:
                    heading += " " + text  # wrapped heading
                else:
                    flush()
                    heading = text
                    buf_page, buf_label = pno, label
                last_was_heading = True
                continue
            last_was_heading = False
            if not buf:
                buf_page, buf_label = pno, label
            buf.append(text)
            if sum(len(x) for x in buf) > 1200:
                flush()
    flush()
    return chunks

# ---- interpretations -------------------------------------------------------

INTERP_NO = re.compile(r"^(\d{1,3})\.$")
EDITION_RE = re.compile(r"([A-Z][a-z]+ 20\d\d) Edition")
RULE_REF = re.compile(r"\b(?:Rules?|Section)\s+(\d+(?:\.\d+)*)")
APPX_REF = re.compile(r"Appendix\s+([A-Z]\d*)")


def chunk_interpretations(doc: pymupdf.Document) -> list:
    """One chunk per numbered interpretation; scope parsed from 'In respect of:'."""
    flat = []  # (text or "" for blank, pdf page)
    for pno, page in enumerate(doc, 1):
        for b in page.get_text("dict")["blocks"]:
            for pdf_line in b.get("lines", []):
                flat.append(("".join(s["text"] for s in pdf_line["spans"]).replace("\xa0", " ").strip(), pno))
    items, cur = [], None
    for text, pno in flat:
        if INTERP_NO.match(text):
            cur = dict(no=INTERP_NO.match(text).group(1), page=pno, lines=[])
            items.append(cur)
        elif cur is not None:
            cur["lines"].append(text)
    chunks = []
    for it in items:
        lines = it["lines"]
        title_i = next((i for i, x in enumerate(lines) if x), None)
        if title_i is None:
            continue
        title, rest = lines[title_i], lines[title_i + 1:]
        scope_lines, body_lines, state = [], [], "pre"
        for x in rest:
            if state == "pre":
                if x.startswith("In respect of"):
                    state = "scope"
                    if ":" in x and x.split(":", 1)[1].strip():
                        scope_lines.append(x.split(":", 1)[1].strip())
                elif x:
                    body_lines.append(x)
            elif state == "scope":
                if x:
                    scope_lines.append(x)
                elif scope_lines:
                    state = "body"
            else:
                if x:
                    body_lines.append(x)
        scope = " ".join(scope_lines)
        meta = {
            "scope": scope,
            "disciplines": _scope_disciplines(scope),
            "edition": (EDITION_RE.search(scope) or [None, ""])[1],
            "rules": RULE_REF.findall(scope),
            "appendices": APPX_REF.findall(scope),
        }
        body = re.sub(r"\s+", " ", " ".join(body_lines)).strip()
        chunks.append(Chunk(f"Interpretation {it['no']}", title, body,
                            f"{title} | In respect of: {scope}", it["page"], str(it["page"]), meta))
    return chunks

def _scope_disciplines(scope: str) -> list:
    from .registry import detect_disciplines
    if re.search(r"\bAll IPSC\b", scope):
        return []
    return detect_disciplines(scope)







