"""A scripted stand-in for the model, so tests run offline and free."""

import json
from types import SimpleNamespace

import pytest

from mini_hermes import llm


def answer(text: str):
    return SimpleNamespace(content=text, tool_calls=None)


def tool_call(name: str, **args):
    call = SimpleNamespace(id=f"call_{name}", function=SimpleNamespace(name=name, arguments=json.dumps(args)))
    return SimpleNamespace(content="", tool_calls=[call])


class FakeLLM:
    def __init__(self):
        self.replies = []
        self.requests = []

    def __call__(self, messages, tools=None, model=None):
        self.requests.append(messages)
        return self.replies.pop(0) if self.replies else answer("ok")


@pytest.fixture
def fake_llm(monkeypatch):
    fake = FakeLLM()
    monkeypatch.setattr(llm, "chat", fake)
    return fake
