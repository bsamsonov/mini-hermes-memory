"""Skills: procedural memory that loads only when it is needed.

MEMORY.md answers "what is true in every session". A skill answers "how do
I do this kind of task, the way this user wants it". The difference decides
where the text lives:

    MEMORY.md                       skills/<name>.md
    facts for every session         a procedure for one kind of task
    whole text in every prompt      only name + description in the prompt
    ~1,300 tokens, hard limit       no limit: the body loads on demand

So the system prompt carries just an index of skills, and the model calls
`skill_view(name)` when a task matches. A hundred skills cost a hundred
index lines, not a hundred procedures.

Skills are written by the agent itself (`skill_manage`), most often by the
background review after a task that took several attempts. A skill is read
into the context as instructions, so it gets the same threat scan as memory.

Hermes counterpart: `tools/skills_tool.py` (skill_view),
`tools/skill_manager_tool.py` (skill_manage), `agent/prompt_builder.py`
(`<available_skills>`). Hermes skills are folders with SKILL.md, references
and scripts, plus a hub, a curator and usage tracking. Here: one file per skill.
"""

import re
from pathlib import Path

from . import threat_patterns

NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")

VIEW_SCHEMA = {
    "type": "function",
    "function": {
        "name": "skill_view",
        "description": "Load the full instructions of a skill listed in <available_skills>.",
        "parameters": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    },
}

MANAGE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "skill_manage",
        "description": (
            "Create or fix a skill: the procedure for a kind of task, done the way this user "
            "wants it. Write steps in order, with concrete commands, and attach each pitfall "
            "to the step it affects. A rule, not a story of what happened this time.\n"
            "create: needs name, description (one line: when to use it), content.\n"
            "patch: replaces old_text with content inside an existing skill."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["create", "patch"]},
                "name": {"type": "string", "description": "lowercase-with-dashes"},
                "description": {"type": "string"},
                "content": {"type": "string"},
                "old_text": {"type": "string"},
            },
            "required": ["action", "name", "content"],
        },
    },
}


class Skills:
    def __init__(self, directory: Path):
        self.dir = directory
        # Frozen like the memory snapshot, for the same prefix-cache reason:
        # a skill created mid-session shows up in the index next session.
        self.index_snapshot = self.index()

    def _path(self, name: str) -> Path:
        return self.dir / f"{name}.md"

    def index(self) -> str:
        """The `<available_skills>` block for the system prompt."""
        lines = []
        for path in sorted(self.dir.glob("*.md")):
            description, _ = _parse(path.read_text(encoding="utf-8"))
            lines.append(f"- {path.stem}: {description}")
        if not lines:
            return ""
        return (
            "## Skills\n"
            "If a skill below matches the task, load it with skill_view(name) before "
            "you start, and follow it.\n"
            "<available_skills>\n" + "\n".join(lines) + "\n</available_skills>"
        )

    def view(self, name: str) -> str:
        if not NAME.match(name) or not self._path(name).exists():
            return f"ERROR: no skill '{name}'"
        _, body = _parse(self._path(name).read_text(encoding="utf-8"))
        if why := threat_patterns.scan(body):
            return f"BLOCKED: skill '{name}' looks poisoned ({why}). Tell the user."
        return body

    def manage(self, action: str, name: str, content: str,
               description: str = "", old_text: str = "") -> str:
        if not NAME.match(name):
            return "ERROR: name must be lowercase letters, digits and dashes"
        if why := threat_patterns.scan(f"{description}\n{content}"):
            return f"BLOCKED: {why}. Nothing was saved. Tell the user."

        path = self._path(name)
        if action == "create":
            if path.exists():
                return f"ERROR: skill '{name}' exists, use patch"
            if not description:
                return "ERROR: create needs a one-line description"
            self.dir.mkdir(parents=True, exist_ok=True)
            path.write_text(f"description: {description.strip()}\n\n{content.strip()}\n", encoding="utf-8")
            return f"created skill '{name}'"
        if action == "patch":
            if not path.exists():
                return f"ERROR: no skill '{name}'"
            text = path.read_text(encoding="utf-8")
            if not old_text or text.count(old_text) != 1:
                return "ERROR: old_text must occur exactly once in the skill"
            path.write_text(text.replace(old_text, content), encoding="utf-8")
            return f"patched skill '{name}'"
        return f"ERROR: unknown action '{action}'"


def _parse(text: str) -> tuple[str, str]:
    """A skill file is a `description:` line, a blank line, then the body."""
    first, _, body = text.partition("\n")
    if first.startswith("description:"):
        return first.removeprefix("description:").strip(), body.strip()
    return "", text.strip()
