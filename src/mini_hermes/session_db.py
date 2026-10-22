"""The session archive: every message of every session, with full-text search.

The opposite of MEMORY.md on every axis:

    MEMORY.md               state.db
    ~1,300 tokens           no limit
    always in the prompt    only when searched
    curated by the model    written automatically
    costs tokens each call  costs nothing until read

Search is done by SQLite FTS5, not by a model: no LLM call, no embeddings.

The index uses SQLite's built-in `porter` stemmer, so "timezones" finds
"timezone": word forms are reduced to a common stem. It understands English
only. Hermes keeps three indexes side by side (word-based, trigram for
partial words in any language, and one for CJK) and ranks across them.

Hermes counterpart: `hermes_state*.py` (SessionDB, schema v32) and
`tools/session_search_tool.py`.
"""

import sqlite3
from datetime import datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id         INTEGER PRIMARY KEY,
    session_id TEXT NOT NULL,
    role       TEXT NOT NULL,
    content    TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- content='messages': the index does not store the text twice,
-- it points at the messages table. Triggers keep the two in sync.
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    content, content='messages', content_rowid='id', tokenize='porter unicode61'
);

CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts(rowid, content) VALUES (new.id, new.content);
END;
"""


class SessionDB:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA journal_mode=WAL")  # readers do not block the writer
        self.db.executescript(SCHEMA)

    @staticmethod
    def new_session_id() -> str:
        return datetime.now().strftime("%Y%m%d-%H%M%S-%f")

    def save(self, session_id: str, role: str, content: str) -> None:
        if not content.strip():
            return
        self.db.execute(
            "INSERT INTO messages (session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (session_id, role, content, datetime.now().isoformat(timespec="seconds")),
        )
        self.db.commit()

    def search(self, query: str, limit: int = 5, exclude_session: str | None = None) -> list[dict]:
        """Best matches across all sessions, ranked by BM25.

        Returns the **full message**, not an FTS `snippet()`. A 20-token
        snippet is fine for human eyes, but a model fills the cut-off part
        with a guess and presents the guess as something it remembers.
        """
        match = _fts_query(query)
        if not match:
            return []
        rows = self.db.execute(
            """
            SELECT m.session_id, m.role, m.created_at, m.content
            FROM messages_fts JOIN messages m ON m.id = messages_fts.rowid
            WHERE messages_fts MATCH ? AND m.session_id IS NOT ?
            ORDER BY rank
            LIMIT ?
            """,
            (match, exclude_session, limit),
        ).fetchall()
        return [{"session": r[0], "role": r[1], "at": r[2], "text": r[3]} for r in rows]


def _fts_query(text: str) -> str:
    """Turn free text into a safe FTS5 query.

    FTS5 has its own query language where `-`, `*` and `"` mean something.
    Quoting every word makes any input literal. Words are OR-ed: BM25 ranks
    messages that match more of them higher anyway. Words shorter than 4
    chars are dropped: they are mostly "the", "and", "you".
    """
    words = {w.strip('.,!?;:()[]"\'').replace('"', "") for w in text.split()}
    return " OR ".join(f'"{w}"' for w in sorted(words) if len(w) >= 4)
