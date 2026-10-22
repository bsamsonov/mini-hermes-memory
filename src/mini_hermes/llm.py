"""Calling the model.

Hermes talks to LLMs through the plain `openai` SDK, without LangChain or
LangGraph, and so does this project. Every dependency is pinned: a smaller
dependency tree is a smaller blast radius for the next supply-chain attack.

Hermes counterpart: `agent/chat_completion_helpers.py` (retries, provider
fallbacks, streaming). Here: one function, no retries.
"""

from openai import OpenAI

from . import config

_client = None


class Usage:
    """Token counters for the session.

    `cached` is the number that matters for memory design: it shows how much
    of each prompt the provider served from its prefix cache.
    """

    def __init__(self):
        self.calls = 0
        self.prompt = 0
        self.completion = 0
        self.cached = 0
        self.last_prompt = 0

    def add(self, u) -> None:
        if not u:
            return
        self.calls += 1
        self.prompt += u.prompt_tokens
        self.completion += u.completion_tokens
        self.cached += _cached_tokens(u)
        self.last_prompt = u.prompt_tokens

    @property
    def cache_rate(self) -> float:
        return self.cached / self.prompt if self.prompt else 0.0


def _cached_tokens(u) -> int:
    """Providers report cache hits in different fields; read both."""
    flat = getattr(u, "prompt_cache_hit_tokens", None)  # DeepSeek
    if flat is not None:
        return flat
    details = getattr(u, "prompt_tokens_details", None)  # OpenAI
    return getattr(details, "cached_tokens", 0) or 0


usage = Usage()

# Exactly what was sent on the last call. The CLI shows it with /context:
# the easiest way to see the frozen snapshot and the recalled block.
last_request: list[dict] = []


def chat(messages: list[dict], tools: list[dict] | None = None, model: str | None = None):
    """One model call. Returns the assistant message."""
    global _client, last_request
    if _client is None:
        _client = OpenAI(api_key=config.API_KEY, base_url=config.BASE_URL, timeout=120)
    last_request = messages
    # No `tools` key at all when there are none: some gateways reject `null`.
    extra = {"tools": tools} if tools else {}
    response = _client.chat.completions.create(
        model=model or config.MODEL, messages=messages, **extra
    )
    usage.add(response.usage)
    return response.choices[0].message
