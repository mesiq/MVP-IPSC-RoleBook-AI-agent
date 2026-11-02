# IPSC Rulebook Assistant

A command-line tool that helps Range Officers, Range Masters and Match Directors look up IPSC rules.

You ask a question in any language. The tool finds the matching rules, interpretations and manual
passages in your PDF files and prints **the exact text from the PDFs**, with a link to the source page.
A language model (LLM) only helps to understand the question and to write a short conclusion.
**It never writes or changes rule text.**

A second function compares rulebook editions ("what changed in the latest PCC rulebook?").

```
$ ipsc ask "Can a shooter take a sight picture with a loaded handgun?"

Short answer:
No ... 

Reasoning:
Rule 8.7.1 states that ...

Rules used (verbatim citations):
- Rule 8.7.1  [Jan 2026, p.27]
    "Competitors are prohibited from taking a sight picture and/or dry firing prior to the Start Signal. ..."
    source: file:///.../IPSC Handgun ... .pdf#page=33

Certainty level: HIGH - The rule directly covers the exact situation.
```

## Setup (Windows, Python 3.12)

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -e .[dev]
copy .env.example .env      # then put your API key(s) in .env
```

`.env` settings (see `.env.example`): `LLM_PROVIDER` (`groq` or `gemini`), `LLM_FALLBACK`,
`GROQ_API_KEY`, `GROQ_MODEL`, `GEMINI_API_KEY`, `GEMINI_MODEL`, optional `IPSC_PUBLIC_URL`.

## Adding PDFs

1. Put the PDF anywhere under `source_data\` (the folders `Rules`, `Interpretations`, `Manuals` are just a convention).
2. Next to it create a sidecar file named `<pdf file name>.meta.json`:

   ```json
   {"doc_type": "rule", "discipline": ["Handgun"], "edition": "2026-01"}
   ```

   | field | values |
   |-------|--------|
   | `doc_type` | `rule`, `interpretation` or `manual` |
   | `discipline` | list of `Handgun`, `22LR Handgun`, `PCC`, `Rifle`, `Shotgun`, `Mini Rifle`, `Action Air`. Required for rules; `[]` for interpretations and manuals that apply to everything |
   | `edition` | release month, `YYYY-MM` |

3. Run `ipsc ingest`. A PDF without a valid sidecar is **not ingested**; the message tells you what is wrong.

Rules of the game: a newer rulebook of the same discipline replaces the older one for answers (the older one is
kept for comparisons). Interpretations and manuals are always valid. Combined multi-discipline rulebooks are
not supported. Everything is assumed to be English.

## Commands

| command | what it does |
|---------|--------------|
| `ipsc ingest` | read the PDFs, split them into rule-sized chunks, build the search index (`--force` to redo all) |
| `ipsc sources` | list indexed documents |
| `ipsc ask "question"` | answer with verbatim citations. "What changed ..." questions are routed to `changes` |
| `ipsc changes PCC --topic "sight pictures"` | what changed between editions, with an optional short summary |
| `ipsc search "keywords"` | show raw search hits (no LLM), useful for checking retrieval |
| `ipsc chunks <file part>` | show stored chunks of a PDF, useful for checking the chunking |

## How a question is answered

```
 question
    |
    v
 1. question.py    LLM turns it into search keywords, detects language, discipline, "changes?" intent
    |              (if the LLM is down: simple keyword rules instead)
    v
 2. search.py      hybrid search: keyword (SQLite FTS5) + meaning (embeddings), merged by rank (RRF)
    |              interpretations are boosted and attached to the rules they clarify
    v
 3. evidence.py    choose up to ~14 passages, cut to a size the free LLM tier accepts -> [E1] [E2] ...
    |
    v
 4. answer.py      LLM writes short answer + reasoning and says which passages [E..] it relied on
    |
    v
 5. certainty.py   code double-checks the LLM's "high" certainty
    |
    v
 6. render.py      prints the answer; each cited passage is copied verbatim from the database
```

More detail and the reasons behind the design: [docs/how-it-works.md](docs/how-it-works.md).

## Where to find things

| file | purpose |
|------|---------|
| `src/ipsc/cli.py` | the commands (only argument handling and printing) |
| `src/ipsc/answer.py` | the `ask()` recipe, steps 1-5 above |
| `src/ipsc/question.py` | step 1, understanding the question |
| `src/ipsc/search.py` | step 2, hybrid search, interpretations, edition checks |
| `src/ipsc/evidence.py` | step 3, which passages go to the LLM |
| `src/ipsc/certainty.py` | step 5 |
| `src/ipsc/render.py` | step 6, printing |
| `src/ipsc/prompts.py` | **all LLM instructions** (three prompts) |
| `src/ipsc/llm.py` | calls Groq / Gemini, retries, fallback |
| `src/ipsc/changes.py` | comparing editions of a rulebook |
| `src/ipsc/ingest.py`, `registry.py`, `chunker.py`, `store.py`, `embed.py` | reading PDFs and sidecars, chunking, database, embeddings |
| `src/ipsc/settings.py` | **all tuning numbers**, each explained |
| `src/ipsc/config.py` | paths, `.env`, links to the PDFs |

## Tests

```powershell
pytest                 # unit tests and offline end-to-end tests (fake LLM); no internet needed
pytest -m eval         # retrieval checks against your real index (run `ipsc ingest` first)
ruff check src tests   # style and unused code
```

`tests/test_answer_pipeline.py` is a good place to start reading: it runs `ask()` with a fake LLM.
