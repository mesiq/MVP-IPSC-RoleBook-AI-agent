import numpy as np

MODEL_NAME = "BAAI/bge-small-en-v1.5"
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

_model = None


def _get_model():
    global _model
    if _model is None:
        from fastembed import TextEmbedding
        _model = TextEmbedding(MODEL_NAME)
    return _model


def embed_passages(texts: list) -> np.ndarray:
    vecs = np.array(list(_get_model().embed(texts, batch_size=32)), dtype=np.float32)
    return vecs / np.linalg.norm(vecs, axis=1, keepdims=True)


def embed_query(text: str) -> np.ndarray:
    v = np.array(list(_get_model().embed([QUERY_PREFIX + text]))[0], dtype=np.float32)
    return v / np.linalg.norm(v)


def chunk_input(ref, title, context, text) -> str:
    return f"{context}\n{ref} {title}\n{text}"[:2000]


def embed_missing(con, log=print, batch=256):
    rows = con.execute("SELECT id, ref, title, context, text FROM chunks WHERE embedding IS NULL").fetchall()
    for i in range(0, len(rows), batch):
        part = rows[i:i + batch]
        vecs = embed_passages([chunk_input(r["ref"], r["title"], r["context"], r["text"]) for r in part])
        con.executemany("UPDATE chunks SET embedding=? WHERE id=?",
                        [(v.tobytes(), r["id"]) for v, r in zip(vecs, part)])
        con.commit()
        log(f"  embedded {min(i + batch, len(rows))}/{len(rows)}")
