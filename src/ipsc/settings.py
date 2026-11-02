"""Every tuning number in one place. Change a value here, nothing else needs editing."""

# --- Search (search.py) ---------------------------------------------------------------------------
RRF_K = 60  # Reciprocal Rank Fusion constant. Higher = keyword and vector ranks count more equally.
POOL = 60  # How many candidates keyword search and vector search each contribute before merging.
# Multiplies a hit's score by its document type. Interpretations override rules, manuals are guidance.
TIER_BOOST = {3: 1.5, 2: 1.0, 1: 0.7}  # 3 = interpretation, 2 = rule, 1 = manual
RELATED_FOR = 3  # For this many top rule hits, also fetch the parent rule and sub-rules.
MAX_SUBRULES = 3  # Max sub-rules fetched per rule (e.g. 10.5.3 -> 10.5.3.1, 10.5.3.2 ...).

# --- Evidence sent to the LLM (evidence.py) -------------------------------------------------------
MAX_EVIDENCE = 10  # Passages from search results.
MAX_RELATED = 4  # Extra passages for parent / sub-rules, on top of MAX_EVIDENCE.
INTERPS_PER_RULE = 3  # Interpretations attached to each rule.
MAX_PASSAGE_CHARS = 1300  # One passage is cut (at a sentence end) beyond this length.
# Total evidence budget. Groq's free tier allows 8,000 tokens per minute, so keep the prompt small.
MAX_TOTAL_CHARS = 11000

# --- Certainty check (certainty.py) ---------------------------------------------------------------
# A "high" certainty needs a cited passage that shares at least this share of the question's key words.
MIN_COVERAGE = 0.3

# --- Comparing rulebook editions (changes.py) -----------------------------------------------------
FUZZY_MIN = 0.55  # Minimum similarity to treat two rules from different editions as the same rule.
CONTAIN_MIN = 0.85  # Share of an old rule contained in a new one to count a split or merge.
TOPK = 6  # Embedding neighbours examined when looking for the matching rule.
