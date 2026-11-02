import hashlib

import pymupdf

from . import chunker, store
from .config import DATA_DIR, TIER
from .registry import DocMeta, edition_from_pdf, scan


def sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def build_chunks(meta: DocMeta, doc) -> list:
    if meta.doc_type == "interpretation":
        return chunker.chunk_interpretations(doc)
    if meta.doc_type == "manual":
        return chunker.chunk_manual(doc)
    chunks = chunker.chunk_numbered(doc)
    return [c for c in chunks if c.ref != "p1"]  # cover page


def ingest_all(con, force=False, log=print, embed=True):
    metas = scan(DATA_DIR)
    on_disk = {str(m.path) for m in metas if not m.skip}
    for (path,) in con.execute("SELECT path FROM docs").fetchall():
        if path not in on_disk:
            store.delete_doc(con, path)  # file moved, renamed, removed or no longer accepted
            log(f"- removed from index  {path}")
    con.commit()
    for meta in metas:
        if meta.skip:
            log(f"! skipped    {meta.rel_path}  ({meta.skip})")
            continue
        digest = sha256(meta.path)
        if not force and store.get_doc_hash(con, str(meta.path)) == digest:
            log(f"= unchanged  {meta.rel_path}")
            continue
        store.delete_doc(con, str(meta.path))
        doc = pymupdf.open(meta.path)
        year, month = edition_from_pdf(doc)
        if year:
            meta.edition_year, meta.edition_month, meta.date_source = year, month, "pdf"
        chunks = build_chunks(meta, doc)
        store.insert_doc(con, meta, TIER[meta.doc_type], len(doc), digest, chunks)
        con.commit()
        log(f"+ {meta.doc_type:<14} {meta.edition_label:<14} ({meta.date_source}) {len(chunks):>4} chunks  {meta.rel_path}")
    if embed:
        from . import embed as emb
        emb.embed_missing(con, log)



