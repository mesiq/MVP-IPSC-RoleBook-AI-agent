import difflib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import embed
from .registry import detect_disciplines

RRF_K = 60
POOL = 60
# Interpretations override rules; manuals are guidance only.
TIER_BOOST = {3: 1.5, 2: 1.0, 1: 0.7}
STOP = set("a an and are as at be by can do does for from has have how i if in is it of on or the to what when where which who with".split())
RULE_NO = re.compile(r"\b\d{1,2}(?:\.\d{1,2}){1,5}\b")


@dataclass
class Hit:
    id: int
    ref: str
    title: str
    text: str
    page_pdf: int
    page_label: str
    doc_type: str
    tier: int
    rel_path: str
    path: str
    edition_label: str
    disciplines: list
    meta: dict
    score: float = 0.0
    interpretations: list = field(default_factory=list)  # for rule hits
    cited_by: str = ""
    also_in: list = field(default_factory=list)
    _norm: str = ""

    @property
    def link(self) -> str:
        return f"{Path(self.path).as_uri()}#page={self.page_pdf}"


@dataclass
class Result:
    disciplines: list
    interpretations: list
    rules: list
    manuals: list


def _active_docs(con, disciplines):
    """Most recent rulebook per discipline; all interpretations; most recent manual per file family."""
    docs = [dict(r) for r in con.execute("SELECT * FROM docs")]
    rule_docs = [d for d in docs if d["doc_type"] == "rule"]
    latest = {}  # newest rulebook per discipline set
    for d in rule_docs:
        key = (d["edition_year"], d["edition_month"], d["version"])
        k = d["disciplines"]
        if k not in latest or key > latest[k][0]:
            latest[k] = (key, d)
    rules = [v[1] for v in latest.values()]
    if disciplines:
        rules = [d for d in rules if set(json.loads(d["disciplines"])) & set(disciplines)]
    manuals = [d for d in docs if d["doc_type"] == "manual"]
    if disciplines:
        manuals = [d for d in manuals if not json.loads(d["disciplines"])
                   or set(json.loads(d["disciplines"])) & set(disciplines)]
    interps = [d for d in docs if d["doc_type"] == "interpretation"]
    return rules + manuals + interps


def _fts_query(q: str) -> str:
    toks = [t for t in re.findall(r"[A-Za-z0-9][A-Za-z0-9.\-]*", q.lower()) if t not in STOP]
    toks = [t.rstrip(".-") for t in toks]
    return " OR ".join(f'"{t}"' for t in toks if t)


def _fts_rank(con, q, ids):
    fq = _fts_query(q)
    if not fq:
        return []
    ph = ",".join("?" * len(ids))
    rows = con.execute(
        f"SELECT f.rowid FROM chunks_fts f JOIN chunks c ON c.id=f.rowid "
        f"WHERE chunks_fts MATCH ? AND c.doc_id IN ({ph}) "
        f"ORDER BY bm25(chunks_fts, 8.0, 4.0, 1.0, 1.0) LIMIT {POOL}", (fq, *ids)).fetchall()
    return [r[0] for r in rows]


def _vec_rank(con, q, ids):
    ph = ",".join("?" * len(ids))
    rows = con.execute(f"SELECT id, embedding FROM chunks WHERE doc_id IN ({ph}) AND embedding IS NOT NULL",
                       ids).fetchall()
    if not rows:
        return []
    mat = np.vstack([np.frombuffer(r["embedding"], dtype=np.float32) for r in rows])
    sims = mat @ embed.embed_query(q)
    order = np.argsort(-sims)[:POOL]
    return [rows[i]["id"] for i in order]


def _load(con, ids) -> dict:
    ph = ",".join("?" * len(ids))
    rows = con.execute(
        f"SELECT c.id, c.ref, c.title, c.text, c.page_pdf, c.page_label, c.meta, d.doc_type, d.tier, "
        f"d.rel_path, d.path, d.edition_label, d.disciplines, d.edition_year, d.edition_month "
        f"FROM chunks c JOIN docs d ON d.id=c.doc_id WHERE c.id IN ({ph})", list(ids)).fetchall()
    return {r["id"]: Hit(r["id"], r["ref"], r["title"], r["text"], r["page_pdf"], r["page_label"],
                         r["doc_type"], r["tier"], r["rel_path"], r["path"], r["edition_label"],
                         json.loads(r["disciplines"]), json.loads(r["meta"] or "{}")) for r in rows}


def _applies(interp: Hit, disciplines: list, rule_disciplines: list = None) -> bool:
    scope = interp.meta.get("disciplines") or []
    if not scope:
        return True
    target = disciplines or rule_disciplines or []
    return not target or bool(set(scope) & set(target))


def _covers(cited: str, ref: str) -> bool:
    return ref == cited or ref.startswith(cited + ".")


def _rule_ids_by_ref(con, ref, rule_ids) -> list:
    if not rule_ids:
        return []
    ph = ",".join("?" * len(rule_ids))
    return [r[0] for r in con.execute(
        f"SELECT id FROM chunks WHERE ref=? AND doc_id IN ({ph})", (ref, *rule_ids))]


def _collapse_duplicates(ranked: list) -> list:
    """Same rule with (near-)identical wording in several rulebooks is reported once."""
    def pri(h):
        ds = [DISC_PRIORITY.index(d) for d in h.disciplines if d in DISC_PRIORITY]
        return min(ds) if ds else 99

    out = []
    for h in ranked:
        norm = re.sub(r"\W+", "", h.text.lower())
        dup = None
        if h.doc_type == "rule":
            for o in out:
                if o.doc_type == "rule" and o.ref == h.ref and \
                        difflib.SequenceMatcher(None, o._norm, norm).quick_ratio() > 0.95 and \
                        difflib.SequenceMatcher(None, o._norm, norm).ratio() > 0.95:
                    dup = o
                    break
        if dup:
            dup.also_in.extend(d for d in h.disciplines if d not in dup.also_in)
            if pri(h) < pri(dup):  # show the most general rulebook as the source
                for f in ("id", "text", "page_pdf", "page_label", "rel_path", "path", "disciplines", "_norm"):
                    setattr(dup, f, getattr(h, f)) if f != "_norm" else setattr(dup, f, norm)
            continue
        h._norm = norm
        h.also_in = list(h.disciplines) if h.doc_type == "rule" else []
        out.append(h)
    return out


DISC_PRIORITY = ["Handgun", "PCC", "Rifle", "Shotgun", "Mini Rifle", "22LR Handgun", "Action Air"]


def search(con, query: str, disciplines: list = None, top_k: int = 8) -> Result:
    disciplines = disciplines or detect_disciplines(query)
    docs = _active_docs(con, disciplines)
    ids = [d["id"] for d in docs]
    rule_ids = {d["id"] for d in docs if d["doc_type"] == "rule"}

    fts = _fts_rank(con, query, ids)
    vec = _vec_rank(con, query, ids)
    score = {}
    for ranking in (fts, vec):
        for r, cid in enumerate(ranking):
            score[cid] = score.get(cid, 0.0) + 1.0 / (RRF_K + r + 1)

    hits = _load(con, list(score)) if score else {}
    for cid, h in hits.items():
        h.score = score[cid] * TIER_BOOST[h.tier]

    # Exact rule numbers typed by the user are strong signals.
    for no in RULE_NO.findall(query):
        for cid in _rule_ids_by_ref(con, no, rule_ids):
            if cid not in hits:
                hits.update(_load(con, [cid]))
            hits[cid].score += 0.1

    ranked = sorted(hits.values(), key=lambda h: -h.score)
    ranked = _collapse_duplicates(ranked)[:top_k]
    interps = [h for h in ranked if h.doc_type == "interpretation"]
    rules = [h for h in ranked if h.doc_type == "rule"]
    manuals = [h for h in ranked if h.doc_type == "manual"]

    # Pull in rules cited by matched interpretations.
    have = {(h.rel_path, h.ref) for h in rules}
    for it in interps:
        for no in it.meta.get("rules", []):
            for cid in _rule_ids_by_ref(con, no, rule_ids):
                h = _load(con, [cid])[cid]
                if (h.rel_path, h.ref) not in have and _applies(it, disciplines, h.disciplines):
                    h.cited_by = f"{it.ref} ({it.title})"
                    h.score = 0.0
                    rules.append(h)
                    have.add((h.rel_path, h.ref))

    # Attach every applicable interpretation (any edition) to each rule hit; newest first.
    all_interps = list(_load(con, [r[0] for r in con.execute(
        "SELECT c.id FROM chunks c JOIN docs d ON d.id=c.doc_id WHERE d.doc_type='interpretation'")]).values())
    ed = {d["rel_path"]: (d["edition_year"], d["edition_month"], d["version"]) for d in docs}
    all_interps.sort(key=lambda h: ed.get(h.rel_path, (0, 0, 0)), reverse=True)
    for rule in rules:
        for it in all_interps:
            if any(_covers(c, rule.ref) for c in it.meta.get("rules", [])) \
                    and _applies(it, disciplines, rule.disciplines):
                rule.interpretations.append(it)
    # Surface linked interpretations in the main list as well.
    seen = {h.id for h in interps}
    for rule in rules:
        for it in rule.interpretations:
            if it.id not in seen:
                interps.append(it)
                seen.add(it.id)
    interps.sort(key=lambda h: (-ed.get(h.rel_path, (0, 0, 0))[0], -ed.get(h.rel_path, (0, 0, 0))[1],
                                -ed.get(h.rel_path, (0, 0, 0))[2], -h.score))
    return Result(disciplines, interps, rules, manuals)
