import argparse
import hashlib
import json

import pymupdf

from . import chunker, store
from .config import DATA_DIR, TIER
from .registry import DocMeta, scan


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
    metas, problems = scan(DATA_DIR)
    on_disk = {str(m.path) for m in metas}
    for (path,) in con.execute("SELECT path FROM docs").fetchall():
        if path not in on_disk:
            store.delete_doc(con, path)  # file moved, renamed, removed or without valid metadata
            log(f"- removed from index  {path}")
    con.commit()
    for rel, problem in problems:
        log(f"! NOT INGESTED  {rel}\n    {problem}")
    for meta in metas:
        digest = sha256(meta.path)
        stored = con.execute("SELECT sha256, edition_year, edition_month, doc_type, disciplines FROM docs "
                             "WHERE path=?", (str(meta.path),)).fetchone()
        same_meta = stored and (stored["edition_year"], stored["edition_month"], stored["doc_type"],
                                json.loads(stored["disciplines"])) == (
            meta.edition_year, meta.edition_month, meta.doc_type, meta.disciplines)
        if not force and stored and stored["sha256"] == digest and same_meta:
            log(f"= unchanged  {meta.rel_path}")
            continue
        store.delete_doc(con, str(meta.path))
        doc = pymupdf.open(meta.path)
        chunks = build_chunks(meta, doc)
        store.insert_doc(con, meta, TIER[meta.doc_type], len(doc), digest, chunks)
        con.commit()
        log(f"+ {meta.doc_type:<14} {meta.edition_label:<10} {len(chunks):>4} chunks  {meta.rel_path}")
    if embed:
        from . import embed as emb
        emb.embed_missing(con, log)





def main() -> None:
    """Command `ipsc-ingest`: (re)build the search index from the PDFs in the data folder."""
    parser = argparse.ArgumentParser(description="Scan the source folder and (re)build the chunk database.")
    parser.add_argument("--force", action="store_true", help="re-ingest unchanged files too")
    ingest_all(store.connect(), force=parser.parse_args().force)


if __name__ == "__main__":
    main()
