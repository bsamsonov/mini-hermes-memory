"""The `memory` tool and the human gate in front of it.

The store (memory_store.py) knows how to write. This module decides
**whether a write happens now, or waits for a human**:

- The background review (see background_review.py) runs with nobody
  watching. It may `add`, but its `patch` and `remove` never apply
  unattended: they go to the pending queue. Adding a wrong fact is cheap to
  undo; silently deleting the right one is not.
- With `approve_all=True`, every write waits for a human. Off by default,
  as in Hermes.

The reply to a queued write looks like success on purpose: the model should
not learn about the gate and try to get around it by rephrasing.

Hermes counterpart: `tools/memory_tool.py` (schema, `_background_delete_gate`,
`_apply_write_gate`) and `tools/write_approval.py` (`/memory pending`).
"""

from .memory_store import MemoryStore

# The description is part of the prompt. It is written for the model.
SCHEMA = {
    "type": "function",
    "function": {
        "name": "memory",
        "description": (
            "Save durable facts to persistent memory. Memory is injected into every future "
            "session, so it must stay small.\n\n"
            "WHEN: only facts that apply to EVERY session: who the user is, their standing "
            "preferences, stable facts about their environment. A procedure for a kind of "
            "task belongs in a skill (skill_manage), not here.\n"
            "One fact per entry: short entries are easy to patch and to drop later.\n"
            "SKIP: task progress, temporary state, things that are easy to rediscover.\n"
            "IF FULL: an add is rejected with the current entries shown. Reissue ONE call "
            "with `operations` that removes or shortens stale entries and adds the new one.\n"
            "You never need to read memory: it is already in your system prompt."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "enum": ["memory", "user"],
                    "description": "'user' = who the user is; 'memory' = your own notes.",
                },
                "operations": {
                    "type": "array",
                    "description": "Applied atomically; the size limit is checked on the final result.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "action": {"type": "string", "enum": ["add", "patch", "remove"]},
                            "content": {"type": "string", "description": "New entry (add) or replacement text (patch)."},
                            "old_text": {"type": "string", "description": "A unique fragment of the entry to patch or remove."},
                        },
                        "required": ["action"],
                    },
                },
            },
            "required": ["target", "operations"],
        },
    },
}


class MemoryTool:
    def __init__(self, store: MemoryStore, approve_all: bool = False):
        self.store = store
        self.approve_all = approve_all
        self.pending: list[dict] = []
        self._next_id = 1

    def call(self, target: str, operations: list[dict], source: str = "agent") -> str:
        """Entry point for the model. `source` is "agent" or "review"."""
        unattended_delete = source == "review" and any(
            op.get("action") in ("patch", "remove") for op in operations
        )
        if self.approve_all or unattended_delete:
            return self._stage(target, operations, source)
        return self.store.apply(target, operations)

    def _stage(self, target: str, operations: list[dict], source: str) -> str:
        self.pending.append(
            {"id": self._next_id, "target": target, "operations": operations, "source": source}
        )
        self._next_id += 1
        return "Queued for the user's approval. No need to repeat this write."

    def approve(self, item_id: int) -> str:
        item = self._take(item_id)
        if item is None:
            return f"no pending write #{item_id}"
        return self.store.apply(item["target"], item["operations"])

    def reject(self, item_id: int) -> str:
        return f"discarded #{item_id}" if self._take(item_id) else f"no pending write #{item_id}"

    def _take(self, item_id: int) -> dict | None:
        for i, item in enumerate(self.pending):
            if item["id"] == item_id:
                return self.pending.pop(i)
        return None
