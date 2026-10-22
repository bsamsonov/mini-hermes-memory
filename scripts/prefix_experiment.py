"""How much of each request could the provider's prefix cache serve?

Providers cache a prompt by its exact prefix: a request can reuse the cache
only up to the first character that differs from an earlier request. So the
share of each request that repeats the previous one is the upper bound of
what caching can save, and it can be measured with any provider, including
ones that do not report cache hits. If the provider does report them
(`cached_tokens`), the script prints the real number next to it.

The same scripted conversation runs twice, against a real model:

    frozen    memory enters the system prompt once per session (Hermes)
    refresh   the system prompt is rebuilt after every memory write

Usage:  uv run python scripts/prefix_experiment.py
"""

import json
import tempfile
from itertools import pairwise
from pathlib import Path

from mini_hermes import llm
from mini_hermes.agent import Agent

TURNS = [
    "Hi! I'm Boris, a software architect in Kyiv. Please remember that.",
    "I prefer short answers, code first. Remember that too.",
    "Our staging database is Postgres 16 on port 5433. Note it.",
    "What is a good default connection pool size for a small Python web service?",
    "We deploy with GitHub Actions to a single VM. Remember that.",
    "Give me a one-line psql command to connect to our staging database.",
    "I'm moving to Lisbon next month, so update my location when you save it.",
    "Summarise what you know about me and my setup in three bullet points.",
]


def run(mode: str) -> list[str]:
    """Run the conversation, return every request exactly as it was sent."""
    requests = []
    real_chat = llm.chat
    llm.usage = llm.Usage()

    def recording_chat(messages, tools=None, model=None):
        requests.append(json.dumps(messages, ensure_ascii=False))
        return real_chat(messages, tools, model)

    llm.chat = recording_chat
    try:
        with tempfile.TemporaryDirectory() as home:
            agent = Agent(home=Path(home), workspace=Path(home))
            for text in TURNS:
                agent.run_turn(text)
                if mode == "refresh":
                    # What a naive design does: always show the latest memory.
                    agent.memory.snapshot = agent.memory.render()
    finally:
        llm.chat = real_chat
    return requests


def shared_prefix(a: str, b: str) -> int:
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


def report(mode: str, requests: list[str]) -> None:
    total = sum(len(r) for r in requests[1:])
    reusable = sum(shared_prefix(prev, cur) for prev, cur in pairwise(requests))
    print(f"{mode:8} requests={len(requests):3}  chars sent={total:8,}  "
          f"repeats previous request: {reusable / total:.0%}  "
          f"provider cache hits: {llm.usage.cached:,} of {llm.usage.prompt:,} tokens "
          f"({llm.usage.cache_rate:.0%})")


if __name__ == "__main__":
    for mode in ("frozen", "refresh"):
        report(mode, run(mode))
