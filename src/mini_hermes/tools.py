"""The agent's tools: memory, skills, the session archive and one file reader.

Tool descriptions are part of the prompt, written for the model.

`read_file` is the only tool that is not about memory. It is here because it
is the realistic way poison gets in: the agent reads a file written by
someone else and decides a line in it is worth remembering
(see examples/poisoned_readme.md).

Hermes counterpart: `tools/registry.py`, `toolsets.py` and dozens of tools.
"""

import json
from pathlib import Path

from . import memory_tool, skills
from .memory_tool import MemoryTool
from .session_db import SessionDB
from .skills import Skills

# A cap on any tool result: one big file must not eat the context window.
MAX_RESULT = 4000

READ_FILE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "read_file",
        "description": "Read a text file inside the working directory.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
}

SESSION_SEARCH_SCHEMA = {
    "type": "function",
    "function": {
        "name": "session_search",
        "description": (
            "Full-text search over all past sessions. Use it when the user refers to "
            "something discussed before that is not in your memory."
        ),
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
}

SCHEMAS = [
    memory_tool.SCHEMA,
    skills.VIEW_SCHEMA,
    skills.MANAGE_SCHEMA,
    SESSION_SEARCH_SCHEMA,
    READ_FILE_SCHEMA,
]

# What the background review may call: writing only, no reading the world.
MEMORY_TOOLS = [memory_tool.SCHEMA, skills.MANAGE_SCHEMA]


class Tools:
    def __init__(self, memory: MemoryTool, skills: Skills, db: SessionDB,
                 session_id: str, workspace: Path):
        self.memory = memory
        self.skills = skills
        self.db = db
        self.session_id = session_id
        self.workspace = workspace.resolve()

    def run(self, name: str, args: dict, source: str = "agent") -> str:
        """Run a tool. An error is a result for the model, not an exception.

        The model should see what went wrong and correct itself, instead of
        the whole turn crashing.
        """
        try:
            result = self._dispatch(name, args, source)
        except Exception as exc:  # noqa: BLE001 - errors go back to the model
            result = f"ERROR in {name}: {exc}"
        if len(result) > MAX_RESULT:
            result = result[:MAX_RESULT] + "\n... [truncated]"
        return result

    def _dispatch(self, name: str, args: dict, source: str) -> str:
        if name == "memory":
            return self.memory.call(args["target"], _operations(args), source)
        if name == "skill_view":
            return self.skills.view(args["name"])
        if name == "skill_manage":
            return self.skills.manage(**args)
        if name == "session_search":
            return self._session_search(args["query"])
        if name == "read_file":
            return self._read_file(args["path"])
        return f"ERROR: no tool '{name}'"

    def _session_search(self, query: str) -> str:
        hits = self.db.search(query, exclude_session=self.session_id)
        if not hits:
            return "nothing found"
        return "\n\n".join(f"[{h['at']} · {h['role']}] {h['text']}" for h in hits)

    def _read_file(self, path: str) -> str:
        # Resolve first, check second: that handles both `../` and symlinks.
        target = (self.workspace / path).resolve()
        if not target.is_relative_to(self.workspace):
            return "ERROR: path is outside the working directory"
        return target.read_text(encoding="utf-8", errors="replace")


def _operations(args: dict) -> list[dict]:
    """The batch, even when the model sent a single operation.

    The schema asks for `operations`, but models often send one flat
    `{action, content}` anyway. Hermes accepts both shapes; so do we.
    """
    if args.get("operations"):
        return args["operations"]
    if args.get("action"):
        return [{k: args[k] for k in ("action", "content", "old_text") if k in args}]
    return []


def parse_args(raw: str | None) -> dict:
    """Tool arguments arrive as a JSON string, and it may well be broken."""
    try:
        args = json.loads(raw or "{}")
        return args if isinstance(args, dict) else {}
    except json.JSONDecodeError:
        return {}
