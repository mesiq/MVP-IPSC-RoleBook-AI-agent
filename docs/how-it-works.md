# How it works

This page explains the ideas behind the code and follows one question through the program.

## The key ideas

1. **The LLM never writes rule text.** A model can paraphrase or invent. So the answer only says *which*
   passages it relied on (`[E1]`, `[E2]`...), and the program prints those passages straight from the
   database, together with a link to the PDF page. A user can always verify.
2. **Interpretations outrank rules.** An interpretation explains how a rule must be applied. Search boosts
   them (`settings.TIER_BOOST`), they are attached to the rules they mention, and the answer prompt tells
   the LLM that newer interpretations override older ones. If an interpretation was written for an older
   rulebook edition than the one being searched, the output shows a `note:` so the user checks the wording.
3. **Only the newest rulebook of a discipline is searched.** Older editions stay in the database for the
   "what changed" tool only.
4. **Chunks are single rule statements**, e.g. one chunk per `8.7.1`. That is why citations are exact.
5. **Hybrid search.** Keyword search finds exact terms and rule numbers; embeddings find similar meaning
   ("sight picture" ~ "aiming"). Both give a ranked list; Reciprocal Rank Fusion merges them.
6. **Renumbering is not a change.** When comparing editions, rules are matched by their *text*, with
   rule numbers ignored. Inserting a rule at the start does not make every later rule "changed".
7. **Metadata comes from you.** Each PDF has a `.meta.json` sidecar (type, discipline, edition). Nothing
   is guessed from file names.

## One question, step by step

Question: *"Can a shooter take a sight picture with a loaded handgun?"*

| step | module | what happens |
|------|--------|--------------|
| 1 | `question.parse_question` | The LLM returns `{"disciplines": ["Handgun"], "search_query": "sight picture loaded handgun start signal", "language": "English", "intent": "answer"}` |
| 2 | `search.search` | Keyword and vector search run over the Handgun rulebook, interpretations and manuals. Results are merged, duplicates across disciplines collapsed, interpretations attached to rules, parent and sub-rules added as context |
| 3 | `evidence.build_evidence` | The best ~10 passages (+ context) are numbered `[E1]...` and cut to fit the LLM budget |
| 4 | `answer.ask` | The LLM reads the passages and returns JSON: short answer, reasoning, `used: ["E1"]`, certainty |
| 5 | `certainty.check_certainty` | If the LLM says "high" but the cited passage shares too few words with the question, it becomes "medium" |
| 6 | `render.print_answer` | `[E1]` in the text becomes "Rule 8.7.1"; the cited chunks are printed verbatim with page and link |

If the LLM is unreachable in step 1, simple keyword rules are used; if it is unreachable in step 4, the
retrieved passages are still shown.

## Other languages

The user may write in any language. The LLM translates the question to English search keywords (rules are
English). The short answer, reasoning and the headings are written in the user's language. Citations are
never translated.

## "What changed" questions

`question.py` detects the intent (LLM, or keyword fallback). `changes.py` returns a `ChangeReport` (plain data); `render.py` prints it in the terminal and the web templates
show the same data as HTML.

1. loads all editions of the discipline's rulebook (exactly the same discipline set), oldest to newest;
2. aligns rules between neighbouring editions: identical text first, then similar text (fuzzy + embeddings),
   then split/merge detection;
3. follows each rule through all editions and reports it as changed, new or removed (with a "renumbered"
   flag); appendices are ignored;
4. prints highlighted word-level differences (green = new/changed, red = removed) with every edition's
   verbatim text and link, preceded by a short LLM summary.

A reworded rule can show up as removed + new. That is accepted.

## Ingest

`ipsc ingest` reads each PDF with its sidecar (`registry.py`), skips unchanged files (SHA-256 and metadata
compared), splits the PDF into chunks (`chunker.py`: numbered rules, interpretations, manuals), stores them in
SQLite with a full-text index (`store.py`) and computes embeddings (`embed.py`, `bge-small-en-v1.5` on CPU).

Marked-up PDFs: struck-through text (thin red lines) is removed while reading so only valid wording is kept.

## Tuning

Change numbers in `src/ipsc/settings.py`. Change LLM instructions in `src/ipsc/prompts.py`.
The Groq free tier allows about 8,000 tokens per minute, which is why the evidence is limited in size.
