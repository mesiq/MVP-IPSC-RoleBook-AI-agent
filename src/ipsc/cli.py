import json

import typer

from . import ingest as ing
from . import store

app = typer.Typer(help="IPSC rulebook assistant (CLI MVP)", no_args_is_help=True)


@app.command()
def ingest(force: bool = typer.Option(False, help="Re-ingest unchanged files")):
    """Scan the project folders and (re)build the chunk database."""
    con = store.connect()
    ing.ingest_all(con, force=force, log=typer.echo)


@app.command()
def sources():
    """List indexed documents and their sidecar metadata."""
    con = store.connect()
    for r in con.execute("SELECT * FROM docs ORDER BY tier DESC, doc_type, edition_year DESC, edition_month DESC"):
        d = ", ".join(json.loads(r["disciplines"])) or "all"
        typer.echo(f"{r['doc_type']:<14} {d:<14} {r['edition_label']:<14} "
                   f"{r['pages']:>3}p {r['n_chunks']:>4} chunks  {r['rel_path']}")


@app.command()
def chunks(doc: str = typer.Argument(..., help="Substring of the file path"),
           ref: str = typer.Option("", help="Only chunks whose ref starts with this"),
           limit: int = 20):
    """Show stored chunks for a document (to verify chunking)."""
    con = store.connect()
    q = ("SELECT c.* FROM chunks c JOIN docs d ON d.id=c.doc_id "
         "WHERE d.rel_path LIKE ? AND c.ref LIKE ? ORDER BY c.id LIMIT ?")
    for r in con.execute(q, (f"%{doc}%", f"{ref}%", limit)):
        typer.echo(f"[{r['ref']}] p.{r['page_label']} (pdf {r['page_pdf']})  {r['context']}\n    {r['text'][:300]}\n")


@app.command()
def search(query: str = typer.Argument(..., help="Question or keywords"),
           discipline: str = typer.Option("", help="e.g. Handgun, PCC, Rifle, Shotgun, 'Mini Rifle', 22LR"),
           top: int = typer.Option(8, help="Max direct hits")):
    """Hybrid (keyword + vector) search. Interpretations are listed first and override rules."""
    from . import search as srch
    from .registry import detect_disciplines
    con = store.connect()
    res = srch.search(con, query, detect_disciplines(discipline) if discipline else None, top)
    typer.echo(f"Disciplines: {', '.join(res.disciplines) or 'all'}\n")

    def show(h, indent=""):
        typer.echo(f"{indent}[{h.ref}] {h.title}  ({h.edition_label}, p.{h.page_label})")
        typer.echo(f"{indent}  {h.text[:500]}")
        typer.echo(f"{indent}  -> {h.link}")
        if h.also_in and len(h.also_in) > 1:
            typer.echo(f"{indent}  (identical in: {', '.join(h.also_in)})")
        if h.cited_by:
            typer.echo(f"{indent}  (cited by {h.cited_by})")

    typer.echo("=== INTERPRETATIONS (priority) ===")
    for h in res.interpretations:
        show(h)
    typer.echo("\n=== RULES ===")
    for h in res.rules:
        show(h)
        for it in h.interpretations:
            typer.echo(f"    ! overridden/clarified by {it.ref} ({it.edition_label}): {it.title}")
    if res.manuals:
        typer.echo("\n=== MANUALS ===")
        for h in res.manuals:
            show(h)


@app.command()
def ask(question: str = typer.Argument(..., help="Your question"),
        discipline: str = typer.Option("", help="Force a discipline, e.g. PCC"),
        top: int = typer.Option(8, help="Max direct hits"),
        debug: bool = typer.Option(False, help="Show parsed query and discipline")):
    """Answer a question: LLM parses it, RAG finds the rules, LLM summarises; citations are verbatim."""
    from . import answer as answer_module
    from .render import print_answer
    con = store.connect()
    a, items = answer_module.ask(con, question, discipline, top, log=typer.echo)
    if a.intent == "changes":
        from . import changes as chg
        typer.echo(f"Detected a 'what changed' question - comparing rulebook editions "
                   f"({a.disciplines[0] if a.disciplines else 'no discipline'}"
                   f"{', topic: ' + a.topic if a.topic else ''}).\n")
        if not a.disciplines:
            typer.echo("Please name the discipline (Handgun, PCC, Rifle, Shotgun, Mini Rifle, 22LR Handgun).")
            return
        chg.run_changes(con, a.disciplines[0], a.topic, 40, typer.echo, language=a.language)
        return
    if debug:
        typer.echo(f"[debug] disciplines={a.disciplines} query={a.search_query!r}")
    print_answer(a, items, typer.echo)


@app.command()
def changes(discipline: str = typer.Argument(..., help="e.g. PCC, Handgun, Rifle"),
            topic: str = typer.Option("", help="Only rules matching this topic, e.g. 'sight pictures'"),
            compare: str = typer.Option("", help="Two path substrings 'A|B' to compare explicit files (testing)"),
            limit: int = typer.Option(40, help="Max rules shown"),
            summary: bool = typer.Option(True, "--summary/--no-summary", help="LLM short summary on top")):
    """Show what changed between editions of a discipline's rulebook (green = new/changed, red = removed)."""
    from . import changes as chg
    con = store.connect()
    docs = None
    if compare:
        rows = [dict(con.execute("SELECT * FROM docs WHERE rel_path LIKE ?", (f"%{p}%",)).fetchone())
                for p in compare.split("|")]
        docs = sorted(rows, key=lambda d: (d["edition_year"], d["edition_month"]))
    chg.run_changes(con, discipline, topic, limit, typer.echo, docs, summary)


if __name__ == "__main__":
    app()
