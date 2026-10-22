"""Context compression, for when a session no longer fits the window.

The history is split in three:

    [head]    the first exchange: why all this started   — kept as is
    [middle]  ──► one structured summary written by the model
    [tail]    the latest turns: what is happening now     — kept verbatim

Only the middle is compressed. Losing the head or the tail costs the most.

Compression is **not destructive**. The full text stays in state.db, and
session_search still finds it after compression. That is what makes it safe
to compress aggressively.

Hermes counterpart: `agent/context_compressor.py` (ContextCompressor):
the same defaults (threshold 50% of the window, summary tail ~20%), plus a
"lean" tail mode that also keeps the user's own words verbatim, pruning of
huge tool outputs before summarising, and a cooldown. Here: the core idea.
"""

from . import config, llm

# Compress when the last prompt passed this share of the window.
THRESHOLD = 0.50

# Share of the window the verbatim tail may take.
TAIL_RATIO = 0.20

PROMPT = """\
Compress the conversation fragment below into a handoff summary. It is not \
a retelling for a human: it is working memory, and the assistant must be \
able to continue as if it remembered everything itself.

Fill these sections, skip the empty ones:

## Goal
## Constraints & Preferences
## Completed Actions
## Active State
## Key Decisions
## Pending User Asks
## Critical Context

Be brief and factual. Keep exact file names, commands, numbers and paths: \
those are what the assistant cannot reconstruct.

--- FRAGMENT ---
{transcript}
"""

# Hermes adds a note like this, so that the model does not treat the summary
# as more important than its curated memory.
NOTE = (
    "[Earlier turns were compacted into the summary below. Your persistent memory "
    "(MEMORY.md, USER.md) in the system prompt remains authoritative.]\n\n"
)


def should_compress(last_prompt_tokens: int) -> bool:
    """Judged by the real size of the last prompt, as reported by the API."""
    return last_prompt_tokens > config.CONTEXT_WINDOW * THRESHOLD


def compress(history: list[dict]) -> list[dict]:
    """Replace the middle of the history with one summary message."""
    # We cut only at user messages. Cutting between a tool call and its
    # result would leave an unanswered tool_call, and the API rejects that.
    users = [i for i, m in enumerate(history) if m["role"] == "user"]
    if len(users) < 3:
        return history  # nothing to compress yet

    head_end = users[1]
    tail_start = _tail_start(history, users)
    if tail_start <= head_end:
        return history

    summary = _summarize(history[head_end:tail_start])
    return [
        *history[:head_end],
        {"role": "user", "content": NOTE + summary},
        *history[tail_start:],
    ]


def _tail_start(history: list[dict], users: list[int]) -> int:
    """The longest tail, cut at a user message, that fits the tail budget."""
    budget = config.CONTEXT_WINDOW * TAIL_RATIO
    for start in users:
        # ~3 characters per token. Precision does not matter here: this
        # picks a cut point, it does not count money.
        if sum(len(str(m.get("content") or "")) for m in history[start:]) / 3 <= budget:
            return start
    return users[-1]


def _summarize(messages: list[dict]) -> str:
    """The model writes the summary: only it can tell signal from noise."""
    lines = []
    for m in messages:
        if m["role"] == "tool":
            lines.append(f"[tool result] {str(m['content'])[:400]}")
        elif m.get("tool_calls"):
            names = ", ".join(c["function"]["name"] for c in m["tool_calls"])
            lines.append(f"[tool calls] {names}")
        elif m.get("content"):
            lines.append(f"{m['role']}: {m['content']}")
    message = llm.chat([{"role": "user", "content": PROMPT.format(transcript="\n".join(lines))}])
    return message.content or "(summary failed)"
