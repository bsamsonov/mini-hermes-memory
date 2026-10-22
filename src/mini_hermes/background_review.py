"""Background review: a separate pass that decides what is worth remembering.

An agent that saves facts only when it happens to think of it mid-task saves
little: in the middle of a task the model is busy with the task, and memory
loses the competition for attention. So learning is moved **out of the
turn**: after the user has the answer, every N turns, a separate call reads
the conversation with one job only, to update memory and skills.

How the review sees the conversation is a cost decision:

- **Same model (default):** it gets the exact same system prompt and history
  plus one review instruction at the end. The prefix is identical, so the
  provider serves the whole conversation from its prompt cache and the
  review costs little more than the new instruction.
- **Another model** (REVIEW_MODEL): that model has no cache of this
  conversation, the whole prompt is paid in full anyway. So it gets a
  compact digest instead of the full replay.

The review runs with nobody watching, so its writes are limited: it may add
to memory, but its patch/remove go to the pending queue (memory_tool.py).

The user sees one line, "💾 self-improvement: ...". A process that silently
writes into the agent's memory is exactly the opacity that makes people
stop trusting memory.

Hermes counterpart: `agent/background_review.py`. Hermes forks the whole
agent in a daemon thread every `nudge_interval` (default 10) turns. Here the
review runs synchronously after the answer is printed: the order is the
same, the mechanism is easier to follow.
"""

from . import config, llm
from .tools import MEMORY_TOOLS, parse_args

TURNS_BETWEEN_REVIEWS = 10

DIGEST_MESSAGES = 12

PROMPT = """\
Review the conversation above. Is there anything worth keeping for future sessions?

- A durable fact about the user or their environment -> memory tool \
(target 'user' or 'memory').
- A way of doing a kind of task that took several attempts, or that the user \
corrected -> skill_manage (create, or patch an existing skill).
- Do NOT save task progress, temporary state, or anything already in memory below.

If nothing stands out, answer "Nothing to save." and call no tools. \
An empty memory is better than a cluttered one.

Current memory (live, may be newer than your system prompt):
{memory}
"""


def review(agent) -> str | None:
    """One review pass. Returns a one-line summary for the user, or None."""
    instruction = {"role": "user", "content": PROMPT.format(memory=agent.memory.render() or "(empty)")}
    if config.REVIEW_MODEL == config.MODEL:
        # Same prefix as the main conversation -> served from the prompt cache.
        messages = [{"role": "system", "content": agent.system_prompt()}, *agent.history, instruction]
    else:
        messages = [{"role": "user", "content": _digest(agent.history)}, instruction]

    try:
        message = llm.chat(messages, MEMORY_TOOLS, model=config.REVIEW_MODEL)
    except Exception as exc:  # noqa: BLE001 - a failed review must not break the session
        # The user already has their answer; a failed review is not their problem.
        return f"review failed: {exc}"

    if not message.tool_calls:
        return None  # "Nothing to save." is not worth a line on screen

    # No second model call: nobody is waiting for the review's reply.
    results = []
    for call in message.tool_calls:
        args = parse_args(call.function.arguments)
        results.append(agent.tools.run(call.function.name, args, source="review"))
    return " | ".join(results)


def _digest(history: list[dict]) -> str:
    """The recent conversation as plain text, for a model with a cold cache."""
    lines = []
    for m in history[-DIGEST_MESSAGES:]:
        if m.get("content"):
            lines.append(f"{m['role']}: {str(m['content'])[:600]}")
    return "Conversation excerpt:\n" + "\n".join(lines)
