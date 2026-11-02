import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

DATA_DIR = Path(os.getenv("IPSC_DATA_DIR", ROOT / "source_data"))
DB_PATH = Path(os.getenv("IPSC_DB_PATH", ROOT / "data" / "ipsc.sqlite"))

# Folder name (lowercase) -> document type. Both spellings of
# "Interpretations" are accepted.
FOLDER_TYPES = {
    "rules": "rule",
    "interpretations": "interpretation",
    "inerpretations": "interpretation",
    "manuals": "manual",
}

# Retrieval priority: interpretations override rules, manuals are guidance.
TIER = {"interpretation": 3, "rule": 2, "manual": 1}
