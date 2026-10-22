"""Settings. Read from `.env` once, at import time.

Hermes counterpart: `hermes_cli/config.py` (layered YAML config with profiles).
Here: a handful of environment variables.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
API_KEY = os.getenv("OPENAI_API_KEY", "")
MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")

# Model for the background review. Empty means "the main model", and that is
# the better default: the review then replays the same conversation and pays
# for it as cache reads (see background_review.py).
REVIEW_MODEL = os.getenv("REVIEW_MODEL", "") or MODEL

# Everything the agent remembers lives here: MEMORY.md, USER.md, skills/, state.db.
HOME = Path(os.getenv("MINI_HERMES_HOME", ".mini-hermes")).resolve()

# The model's context window. Hermes reads it from a model catalog;
# here you set it by hand.
CONTEXT_WINDOW = int(os.getenv("CONTEXT_WINDOW", "64000"))

# Guard against an endless "the model calls the same tool again" loop.
MAX_ITERATIONS = 12
