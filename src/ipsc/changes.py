"""Compare rule text between editions of the same discipline's rulebook.

Rules are aligned by content, not by number: renumbering, punctuation, case, whitespace and page
furniture never count as a change. Chunks that were split or merged between editions are grouped.
"""
import difflib
import json
import re
from collections import defaultdict, deque
from dataclasses import dataclass, field

import numpy as np
import typer

from .config import source_link
from .settings import CONTAIN_MIN, FUZZY_MIN, TOPK

NUM = re.compile(r"\b\d{1,2}(?:\.\d{1,2}){1,5}\b")
SPLIT_NUM = re.compile(r"(\d\.)\s+(?=\d)")
HEAD_NUM = re.compile(r"(?<![\d.])\d{1,2}\.(?=\s+[A-Z][a-z])")


def _clean(text: str) -> str:
    """Repair rule numbers broken by PDF spacing, e.g. '10.5. 14' -> '10.5.14'."""
    return SPLIT_NUM.sub(r"\1", text.replace("\xad", ""))


PLACEHOLDERS = {"not applicable", "intentionally blank", "intentionally left blank", "reserved", "deleted"}


@dataclass
class Version:
    doc: dict
    ref: str
    text: str
    page_pdf: int
    page_label: str

    @property
    def label(self) -> str:
        return self.doc['edition_label']

    @property
    def link(self) -> str:
        return source_link(self.doc["path"], self.doc["rel_path"], self.page_pdf)


@dataclass
class Change:
    ref: str
    kind: str  # changed | new | removed
    versions: list = field(default_factory=list)  # oldest -> newest, only editions containing the rule
    renumbered: bool = False


def _tokens(text: str) -> list:
    # a trailing section-heading number such as "... 18. Aftermarket parts" is page furniture, not wording
    text = HEAD_NUM.sub("#", _clean(text))
    t = NUM.sub("#", text.lower())
    return re.sub(r"[^a-z0-9#\s]", " ", t).split()


def _norm(text: str) -> str:
    return " ".join(_tokens(text))


def rulebook_editions(con, disciplines: list) -> list:
    """All rulebook docs for exactly this discipline set, oldest -> newest."""
    want = sorted(disciplines)
    docs = [dict(r) for r in con.execute("SELECT * FROM docs WHERE doc_type='rule'")]
    docs = [d for d in docs if sorted(json.loads(d["disciplines"])) == want]
    docs.sort(key=lambda d: (d["edition_year"], d["edition_month"]))
    return docs


def _load(con, doc_id) -> list:
    out = []
    for r in con.execute("SELECT ref, text, page_pdf, page_label, embedding FROM chunks "
                         "WHERE doc_id=? AND ref!='p1' ORDER BY id", (doc_id,)):
        n = _norm(r["text"])
        if r["ref"].startswith("Appendix"):
            continue  # appendices are not compared between editions
        if not n or n in PLACEHOLDERS:
            continue
        vec = np.frombuffer(r["embedding"], dtype=np.float32) if r["embedding"] else None
        part = re.match(r"(.*) \(part (\d+)\)$", r["ref"])
        if part and int(part.group(2)) > 1 and out and out[-1]["ref"] == part.group(1):
            prev = out[-1]  # re-join pieces of one long section so splitting never counts as a change
            prev["text"] += " " + r["text"]
            prev["norm"] = _norm(prev["text"])
            prev["words"] = prev["norm"].split()
            continue
        if part:
            r_ref = part.group(1)
        else:
            r_ref = r["ref"]
        out.append({"ref": r_ref, "text": r["text"], "norm": n, "words": n.split(),
                    "page_pdf": r["page_pdf"], "page_label": r["page_label"], "vec": vec})
    return out


def _ratio(a: list, b: list) -> float:
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


def _containment(small: list, big: list) -> float:
    sm = difflib.SequenceMatcher(None, small, big, autojunk=False)
    return sum(m.size for m in sm.get_matching_blocks()) / max(len(small), 1)


def _candidates(src, dst, k):
    """For each src chunk, indices of the k most similar dst chunks by embedding (or many if no vectors)."""
    if not src or not dst:
        return [[] for _ in src]
    if any(c["vec"] is None for c in src + dst):
        return [list(range(len(dst)))[:50] for _ in src]
    sims = np.vstack([c["vec"] for c in src]) @ np.vstack([c["vec"] for c in dst]).T
    return [list(np.argsort(-row)[:k]) for row in sims]


def align(old: list, new: list) -> list:
    """Return groups [(old_idx_list, new_idx_list)] covering every chunk exactly once."""
    o2n, n2o = {}, {}

    # 1. identical content (numbers/formatting ignored); prefer the same reference, else document order
    pool = defaultdict(deque)
    for i, c in enumerate(old):
        pool[c["norm"]].append(i)
    for j, c in enumerate(new):
        q = pool.get(c["norm"])
        if not q:
            continue
        pick = next((i for i in q if old[i]["ref"] == c["ref"]), q[0])
        q.remove(pick)
        o2n[pick], n2o[j] = j, pick

    # 2. similar content, best pairs first
    lo = [i for i in range(len(old)) if i not in o2n]
    ln = [j for j in range(len(new)) if j not in n2o]
    cands = _candidates([old[i] for i in lo], [new[j] for j in ln], TOPK)
    scored = []
    for a, i in enumerate(lo):
        for b in cands[a]:
            j = ln[b]
            r = _ratio(old[i]["words"], new[j]["words"])
            if r >= FUZZY_MIN:
                scored.append((r, i, j))
    for r, i, j in sorted(scored, reverse=True):
        if i not in o2n and j not in n2o:
            o2n[i], n2o[j] = j, i

    # 3. groups: start from the 1:1 pairs
    groups, og, ng = [], {}, {}
    for i, j in o2n.items():
        groups.append(([i], [j]))
        og[i] = ng[j] = len(groups) - 1

    def attach(src, dst, src_is_old):
        """Leftover src chunks contained in a dst chunk (split/merge) join that chunk's group."""
        mine, other = (og, ng) if src_is_old else (ng, og)
        left = [x for x in range(len(src)) if x not in mine]
        cs = _candidates([src[x] for x in left], dst, TOPK + 2)
        for a, x in enumerate(left):
            if len(src[x]["words"]) < 5:
                continue
            best = max(((_containment(src[x]["words"], dst[y]["words"]), y) for y in cs[a]),
                       default=(0, None))
            if best[0] < CONTAIN_MIN:
                continue
            y = best[1]
            gi = other.get(y)
            if gi is None:
                groups.append(([], []))
                gi = len(groups) - 1
                other[y] = gi
                groups[gi][1 if src_is_old else 0].append(y)
            groups[gi][0 if src_is_old else 1].append(x)
            mine[x] = gi

    attach(new, old, False)
    attach(old, new, True)

    for i in range(len(old)):
        if i not in og:
            groups.append(([i], []))
    for j in range(len(new)):
        if j not in ng:
            groups.append(([], [j]))
    return [(sorted(o), sorted(n)) for o, n in groups]


def _version(doc, chunks, idxs) -> Version:
    parts = [chunks[i] for i in idxs]
    refs = [p["ref"] for p in parts]
    ref = refs[0] if len(set(refs)) == 1 else " + ".join(dict.fromkeys(refs))
    return Version(doc, ref, " ".join(re.sub(r"\s+", " ", p["text"]).strip() for p in parts),
                   parts[0]["page_pdf"], parts[0]["page_label"])


def compare(con, docs: list, refs: set = None) -> tuple:
    """Return (changes, renumbered_only_count). Aligns consecutive editions and follows each rule through them."""
    chunks = [_load(con, d["id"]) for d in docs]
    n = len(docs)
    threads = []  # each: {"versions": [(doc_index, Version)]}
    owner = [dict() for _ in docs]  # per doc: chunk idx -> thread idx

    for i in range(n - 1):
        for o, nw in align(chunks[i], chunks[i + 1]):
            if o:
                t = owner[i].get(o[0])
                if t is None:
                    threads.append({"versions": [(i, _version(docs[i], chunks[i], o))]})
                    t = len(threads) - 1
                    for x in o:
                        owner[i][x] = t
            else:
                threads.append({"versions": []})
                t = len(threads) - 1
            if nw:
                threads[t]["versions"].append((i + 1, _version(docs[i + 1], chunks[i + 1], nw)))
                for x in nw:
                    owner[i + 1][x] = t

    changes, renumbered = [], 0
    for th in threads:
        vs = th["versions"]
        if not vs:
            continue
        first, last = vs[0][0], vs[-1][0]
        texts = [_norm(v.text) for _, v in vs]
        if first > 0 and last == n - 1:
            kind = "new"
        elif last < n - 1 and first == 0:
            kind = "removed"
        elif first > 0 or last < n - 1:
            continue
        elif len(set(texts)) > 1:
            kind = "changed"
        else:
            if len({v.ref for _, v in vs}) > 1:
                renumbered += 1
            continue
        newest = vs[-1][1]
        if refs is not None and not (last == n - 1 and newest.ref in refs):
            continue
        changes.append(Change(newest.ref if kind != "removed" else vs[0][1].ref, kind, [v for _, v in vs],
                              renumbered=len({v.ref for _, v in vs}) > 1))
    return changes, renumbered


def _diff_brief(c, width=350) -> str:
    """Compact description of one change for the LLM: only the words that differ between editions."""
    if c.kind == "new":
        return "NEW: " + c.versions[-1].text[:width]
    if c.kind == "removed":
        return "REMOVED: " + c.versions[0].text[:width]
    a, b = _clean(c.versions[-2].text).split(), _clean(c.versions[-1].text).split()
    sm = difflib.SequenceMatcher(None, [_mask(w) for w in a], [_mask(w) for w in b], autojunk=False)
    parts = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag != "equal":
            parts.append(f"[was: {' '.join(a[i1:i2])[:width] or '-'}] [now: {' '.join(b[j1:j2])[:width] or '-'}]")
    return "CHANGED: " + " ".join(parts)[:width * 2]


SUMMARY_SYS = (
    "You summarise differences between editions of IPSC rulebooks for Range Officers. You get numbered changes "
    "(C1..Cn) showing only what differs. Use only that information; never invent rule text or numbers. "
    "Ignore pure rewording or typo fixes unless the meaning changes. Respond with JSON only: "
    '{"overview": "2-3 sentences on the main themes of the changes", '
    '"points": [{"id": "C3", "change": "one plain sentence on what changed and why it matters in practice"}]} '
    "List at most 12 points, the most significant first."
)


def summarize(found: list, editions: str, log=lambda m: None, limit=25, language="English"):
    """Return (overview, [(Change, sentence)]) or None when the LLM is unavailable."""
    from . import llm
    chosen = sorted(found, key=lambda c: _ref_key(c.ref))[:limit]
    brief = "\n".join(f"C{i}: Rule {c.ref}{' (renumbered)' if c.renumbered else ''} - {_diff_brief(c)}"
                      for i, c in enumerate(chosen, 1))
    try:
        data = llm.complete_json(SUMMARY_SYS, f"Write the overview and points in {language}.\n"
                                              f"Editions compared: {editions}\n\n{brief}", log)
    except llm.LLMError as e:
        log(f"  summary skipped ({e})")
        return None
    pts = []
    for p in data.get("points", []) or []:
        try:
            n = int(str(p.get("id", "")).lstrip("Cc")) - 1
        except ValueError:
            continue
        if 0 <= n < len(chosen) and p.get("change"):
            pts.append((chosen[n], str(p["change"]).strip()))
    return str(data.get("overview", "")).strip(), pts


def run_changes(con, discipline: str, topic: str = "", limit: int = 40, echo=typer.echo, explicit_docs: list = None,
                summary: bool = True, language: str = "English"):
    """Compare the editions of a discipline's rulebook and print the changes (shared by CLI and ask)."""
    from . import search as srch
    from .registry import detect_disciplines
    discs = detect_disciplines(discipline)
    docs = explicit_docs or (rulebook_editions(con, discs) if discs else [])
    if len(docs) < 2:
        echo(f"Only {len(docs)} edition(s) of the {discipline} rulebook are indexed - nothing to compare yet.\n"
             "Add the older/newer PDF to source_data\\Rules and run 'ipsc ingest'.")
        return
    echo("Editions compared: " + " -> ".join(f"{d['edition_label']}" for d in docs))
    refs = None
    if topic:
        res = srch.search(con, topic, discs or None, 15)
        refs = {h.ref for h in res.rules}
        echo(f"Topic '{topic}': checking rules {', '.join(sorted(refs))}")
    found, renum = compare(con, docs, refs)
    echo(f"{len(found)} rule(s) differ in wording." + (f" Showing first {limit}." if len(found) > limit else ""))
    echo(f"({renum} further rule(s) were only renumbered/reformatted - not listed.)")
    shown = sorted(found, key=lambda c: _ref_key(c.ref))[:limit]
    if summary and shown:
        s = summarize(shown, " -> ".join(f"{d['edition_label']}" for d in docs), echo,
                      language=language)
        if s:
            overview, points = s
            echo(f"\nSummary of changes:\n{overview}\n")
            for c, text in points:
                echo(f"- Rule {c.ref} [{c.kind.upper()}]: {text}")
            echo("\nDetails with verbatim citations:")
    render(shown, echo)


def _ref_key(ref: str):
    return [int(x) for x in re.findall(r"\d+", ref)[:8]] or [999]


def _mask(w: str) -> str:
    return NUM.sub("#", re.sub(r"[^\w.#]", "", w.lower())).strip(".")


def highlight(prev: str, cur: str) -> str:
    """cur with words that are new or changed relative to prev in green bold."""
    a, b = _clean(prev).split(), _clean(cur).split()
    sm = difflib.SequenceMatcher(None, [_mask(w) for w in a], [_mask(w) for w in b], autojunk=False)
    out = []
    for tag, _, _, j1, j2 in sm.get_opcodes():
        seg = " ".join(b[j1:j2])
        if seg:
            out.append(typer.style(seg, fg="green", bold=True) if tag in ("replace", "insert") else seg)
    return " ".join(out)


def strike(cur: str, nxt: str) -> str:
    """cur with words that were removed or replaced in the next edition in red."""
    a, b = _clean(cur).split(), _clean(nxt).split()
    sm = difflib.SequenceMatcher(None, [_mask(w) for w in a], [_mask(w) for w in b], autojunk=False)
    out = []
    for tag, i1, i2, _, _ in sm.get_opcodes():
        seg = " ".join(a[i1:i2])
        if seg:
            out.append(typer.style(seg, fg="red") if tag in ("replace", "delete") else seg)
    return " ".join(out)


def render(changes: list, echo=typer.echo, max_text=900):
    for c in sorted(changes, key=lambda c: _ref_key(c.ref)):
        echo(f"\n- Rule {c.ref}  [{c.kind.upper()}]" + ("  (renumbered)" if c.renumbered else ""))
        for i, v in enumerate(c.versions):
            if len(c.versions) == 1:
                body = v.text
            elif i == len(c.versions) - 1:
                body = highlight(c.versions[i - 1].text, v.text)
            else:
                body = strike(v.text, c.versions[i + 1].text)
            if len(body) > max_text:
                body = body[:max_text] + " ..."
            echo(f"  Citation version {v.label}, Rule {v.ref} (p.{v.page_label}):\n    {body}\n"
                 f"    source: {v.link}")
