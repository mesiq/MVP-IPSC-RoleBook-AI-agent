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
    """List indexed documents and the metadata derived from their names."""
    con = store.connect()
    for r in con.execute("SELECT * FROM docs ORDER BY tier DESC, doc_type, edition_year DESC, edition_month DESC"):
        d = ", ".join(json.loads(r["disciplines"])) or "all"
        typer.echo(f"{r['doc_type']:<14} {d:<14} {r['edition_label']:<14} v{r['version']} "
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
    from . import answer as ans_mod
    con = store.connect()
    a, items = ans_mod.ask(con, question, discipline, top, log=typer.echo)
    if debug:
        typer.echo(f"[debug] disciplines={a.disciplines} query={a.search_query!r}")

    def cite(i):
        h = items[i]
        kind = {"interpretation": "", "manual": "Manual "}.get(h.doc_type, "Rule ")
        label = f"{h.ref}: {h.title}" if h.doc_type != "rule" else h.ref
        typer.echo(f"- {kind}{label}  [{h.edition_label}, p.{h.page_label}]")
        typer.echo(f"    \"{h.text}\"")
        typer.echo(f"    source: {h.link}")

    typer.echo(f"\nShort answer:\n{a.interpretation}\n")
    if a.reasoning:
        typer.echo(f"Reasoning:\n{a.reasoning}\n")
    typer.echo("Rules used (verbatim citations):")
    for i in a.used:
        cite(i)
    if a.considered:
        typer.echo("\nRules considered:")
        for i in a.considered:
            cite(i)
    typer.echo(f"\nCertainty level: {a.certainty.upper()}" + (f" - {a.certainty_reason}" if a.certainty_reason else ""))


@app.command()
def changes(discipline: str = typer.Argument(..., help="e.g. PCC, Handgun, Rifle"),
            topic: str = typer.Option("", help="Only rules matching this topic, e.g. 'sight pictures'"),
            compare: str = typer.Option("", help="Two path substrings 'A|B' to compare explicit files (testing)"),
            limit: int = typer.Option(40, help="Max rules shown")):
    """Show what changed between editions of a discipline's rulebook (green = new/changed, red = removed)."""
    from . import changes as chg
    from . import search as srch
    from .registry import detect_disciplines
    con = store.connect()
    if compare:
        pats = compare.split("|")
        rows = [dict(con.execute("SELECT * FROM docs WHERE rel_path LIKE ?", (f"%{p}%",)).fetchone()) for p in pats]
        docs = sorted(rows, key=lambda d: (d["edition_year"], d["edition_month"], d["version"]))
    else:
        discs = detect_disciplines(discipline)
        docs = chg.rulebook_editions(con, discs)
    if len(docs) < 2:
        typer.echo(f"Only {len(docs)} edition(s) of the {discipline} rulebook are indexed - nothing to compare yet.\n"
                   "Add the older/newer PDF to the Rules folder and run 'ipsc ingest'.")
        return
    typer.echo("Editions compared: " + " -> ".join(f"{d['edition_label']} v{d['version']}" for d in docs))
    refs = None
    if topic:
        res = srch.search(con, topic, detect_disciplines(discipline) or None, 15)
        refs = {h.ref for h in res.rules}
        typer.echo(f"Topic '{topic}': checking rules {', '.join(sorted(refs))}")
    found, renum = chg.compare(con, docs, refs)
    typer.echo(f"{len(found)} rule(s) differ in wording." + (f" Showing first {limit}." if len(found) > limit else ""))
    typer.echo(f"({renum} further rule(s) were only renumbered/reformatted - not listed.)")
    chg.render(sorted(found, key=lambda c: chg._ref_key(c.ref))[:limit])


if __name__ == "__main__":
    app()
