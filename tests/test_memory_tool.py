from mini_hermes.memory_store import MemoryStore
from mini_hermes.memory_tool import MemoryTool


def add(text):
    return {"action": "add", "content": text}


def test_background_review_may_add(tmp_path):
    tool = MemoryTool(MemoryStore(tmp_path))
    assert tool.call("user", [add("Likes tea")], source="review").startswith("added")


def test_background_review_cannot_delete_unattended(tmp_path):
    tool = MemoryTool(MemoryStore(tmp_path))
    tool.call("user", [add("Likes tea")])
    reply = tool.call("user", [{"action": "remove", "old_text": "tea"}], source="review")
    assert reply.startswith("Queued")
    assert tool.store.entries["user"] == ["Likes tea"]
    assert tool.approve(tool.pending[0]["id"]).startswith("removed")
    assert tool.store.entries["user"] == []


def test_approve_all_queues_every_write(tmp_path):
    tool = MemoryTool(MemoryStore(tmp_path), approve_all=True)
    assert tool.call("memory", [add("fact")]).startswith("Queued")
    assert tool.store.entries["memory"] == []
    assert tool.reject(1) == "discarded #1"
    assert tool.pending == []
