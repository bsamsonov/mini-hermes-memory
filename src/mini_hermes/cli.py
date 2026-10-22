"""Terminal REPL. Commands starting with `/` are for the human, not the model.

Most of them exist to make memory visible: what is on disk versus what is
frozen in the prompt, what waits for approval, what the provider served
from cache.
"""

import argparse

from . import config, llm
from .agent import Agent

HELP = """\
/memory          memory on disk vs the frozen snapshot in the prompt
/skills          the skills index
/pending         writes waiting for your approval
/approve N       apply pending write N      /reject N   discard it
/forget TEXT     delete the memory entry containing TEXT (no model involved)
/search TEXT     search the session archive
/usage           tokens this session, and how much came from the prompt cache
/context         exactly what was sent to the model on the last call
/new             start a new session (memory written now enters the prompt)
/quit"""


def show_tool(name: str, args: dict, result: str) -> None:
    print(f"  · {name}({_short(args)}) -> {result.splitlines()[0][:100] if result else ''}")


def _short(args: dict) -> str:
    text = ", ".join(f"{k}={v!r}" for k, v in args.items())
    return text if len(text) < 100 else text[:97] + "..."


def command(agent: Agent, line: str) -> Agent:
    """Run a slash command. Returns the agent (a new one after /new)."""
    name, _, arg = line.partition(" ")
    arg = arg.strip()

    if name == "/memory":
        print("ON DISK (raw):\n" + (agent.memory.render(sanitize=False) or "(empty)"))
        print("\nIN THE PROMPT (frozen at session start):\n" + (agent.memory.snapshot or "(empty)"))
    elif name == "/skills":
        print(agent.skills.index() or "(no skills yet)")
    elif name == "/pending":
        if not agent.memory_tool.pending:
            print("nothing pending")
        for item in agent.memory_tool.pending:
            print(f"#{item['id']} from {item['source']} -> {item['target']}: {item['operations']}")
    elif name in ("/approve", "/reject") and arg.isdigit():
        tool = agent.memory_tool
        print(tool.approve(int(arg)) if name == "/approve" else tool.reject(int(arg)))
    elif name == "/forget":
        print(agent.memory.forget(arg))
    elif name == "/search":
        for hit in agent.db.search(arg):
            print(f"[{hit['at']} · {hit['role']}] {hit['text'][:200]}")
    elif name == "/usage":
        u = llm.usage
        print(f"calls {u.calls} · prompt {u.prompt:,} · completion {u.completion:,} · "
              f"cached {u.cached:,} ({u.cache_rate:.0%} of prompt)")
    elif name == "/context":
        for m in llm.last_request:
            print(f"--- {m['role']} ---\n{m.get('content') or m.get('tool_calls')}")
    elif name == "/new":
        agent = Agent(approve_all=agent.memory_tool.approve_all, on_tool=show_tool)
        print("new session, memory snapshot refreshed")
    else:
        print(HELP)
    return agent


def main() -> None:
    parser = argparse.ArgumentParser(description="A small agent with Hermes-style memory.")
    parser.add_argument("--approve-all", action="store_true", help="every memory write waits for /approve")
    args = parser.parse_args()
    if not config.API_KEY:
        raise SystemExit("No OPENAI_API_KEY. Copy .env.example to .env and fill it in.")

    agent = Agent(approve_all=args.approve_all, on_tool=show_tool)
    print(f"mini-hermes · {config.MODEL} · memory in {config.HOME} · /help for commands")
    while True:
        try:
            line = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not line:
            continue
        if line == "/quit":
            break
        if line.startswith("/"):
            agent = command(agent, line)
            continue
        print(agent.run_turn(line))
        if summary := agent.after_turn():
            print(f"💾 self-improvement: {summary}")


if __name__ == "__main__":
    main()
