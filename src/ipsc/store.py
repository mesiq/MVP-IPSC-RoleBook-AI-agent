import json
import sqlite3
from pathlib import Path

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS docs (
    id INTEGER PRIMARY KEY, path TEXT UNIQUE, rel_path TEXT, doc_type TEXT, tier INTEGER,
    disciplines TEXT, edition_label TEXT, edition_year INTEGER, edition_month INTEGER,
    pages INTEGER, sha256 TEXT, n_chunks INTEGER
);
CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY, doc_id INTEGER REFERENCES docs(id) ON DELETE CASCADE,
    ref TEXT, title TEXT, text TEXT, context TEXT, page_pdf INTEGER, page_label TEXT,
    meta TEXT, embedding BLOB
);
CREATE INDEX IF NOT EXISTS chunks_doc ON chunks(doc_id);
CREATE INDEX IF NOT EXISTS chunks_ref ON chunks(ref);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    ref, title, text, context, tokenize="unicode61 tokenchars '.'"
);
"""


def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.executescript(SCHEMA)
    return con


def connect_readonly(path: Path = DB_PATH) -> sqlite3.Connection:
    """Read-only connection for the web app (cheap, never changes the schema)."""
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def delete_doc(con, path: str):
    r = con.execute("SELECT id FROM docs WHERE path=?", (path,)).fetchone()
    if r:
        ids = [x[0] for x in con.execute("SELECT id FROM chunks WHERE doc_id=?", (r["id"],))]
        con.executemany("DELETE FROM chunks_fts WHERE rowid=?", [(i,) for i in ids])
        con.execute("DELETE FROM chunks WHERE doc_id=?", (r["id"],))
        con.execute("DELETE FROM docs WHERE id=?", (r["id"],))


def insert_doc(con, d, tier, pages, sha, chunks) -> int:
    cur = con.execute(
        "INSERT INTO docs(path, rel_path, doc_type, tier, disciplines, edition_label, edition_year,"
        " edition_month, pages, sha256, n_chunks) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (str(d.path), d.rel_path, d.doc_type, tier, json.dumps(d.disciplines), d.edition_label,
         d.edition_year, d.edition_month, pages, sha, len(chunks)))
    doc_id = cur.lastrowid
    for c in chunks:
        cc = con.execute(
            "INSERT INTO chunks(doc_id, ref, title, text, context, page_pdf, page_label, meta)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (doc_id, c.ref, c.title, c.text, c.context, c.page_pdf, c.page_label, json.dumps(c.meta)))
        con.execute("INSERT INTO chunks_fts(rowid, ref, title, text, context) VALUES (?,?,?,?,?)",
                    (cc.lastrowid, c.ref, c.title, c.text, c.context))
    return doc_id
