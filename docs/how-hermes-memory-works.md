# How memory works in Hermes Agent

A map of the memory system of [Hermes Agent](https://github.com/NousResearch/hermes-agent), read from the source at commit [`1186b6b`](https://github.com/NousResearch/hermes-agent/tree/1186b6bd5330185ba61c4f80fbfc073f7febbf0e) (2026-10-21). Hermes changes fast (tens of thousands of commits in a few months), so file names and defaults below may drift; the design has been stable.

## The core idea: budgets, not storage

Most "agent memory" discussions start with storage: vector DB or not, which embedding model. Hermes starts with the **context window as a budget**. Every store answers three questions differently:

1. How does it get into the model's context, and when?
2. Who keeps it within budget?
3. Who writes it, and who can undo a write?

The answers give four stores with very different properties.

| Store | Where | Into the context | Budget | Writer |
|---|---|---|---|---|
| Conversation | memory of the process, `state.db` | directly | the window; compressed | the conversation |
| Curated memory | `MEMORY.md`, `USER.md` | frozen snapshot in the system prompt | 2,200 + 1,375 chars | the model (`memory` tool) |
| Skills | `skills/<name>/SKILL.md` | index in the system prompt, body on demand | none | the model (`skill_manage`), a curator |
| Session archive | `state.db` (SQLite) | `session_search` tool | none | automatic |

On top of these sits an optional **external memory provider** (Honcho, Mem0, Hindsight, Supermemory, RetainDB, ByteRover and others), which adds to the built-in memory and never replaces it.

## 1. Curated memory: small on purpose

`tools/memory_tool_store.py` (`MemoryStore`), `tools/memory_tool.py`.

- **Two files.** `MEMORY.md` holds the agent's notes (environment, conventions, tool quirks); `USER.md` holds the user profile. Entries are bare text joined by `\n§\n`, with no timestamps or tags.
- **Limits in characters**: `memory_char_limit` 2,200 and `user_char_limit` 1,375, roughly 800 + 500 tokens. The code says why characters: they are model-independent.
- **Frozen snapshot.** Both files are rendered into the system prompt once, at session start ("prefix-cache stable"). A write mid-session updates the file and the tool result, not the prompt. Every turn reuses the same cached prefix; the cost is that a new fact reaches the prompt only next session.
- **No `read` action.** Memory is already in the prompt. The actions are `add`, `patch` and `remove`. `patch` replaces a span inside one entry (the older whole-entry `replace` was removed). The target entry is found by a unique substring; several matches are an error.
- **Refuse, don't compress.** An `add` that does not fit is rejected with `current_entries` and usage attached. The model must consolidate: an `operations` batch is applied atomically and the limit is checked on the final state, so one call can remove stale entries and add the new one. After `_MAX_CONSOLIDATION_FAILURES_PER_TURN = 3` failures the model is told to stop and answer the user.
- **What belongs here.** The tool description is strict: only facts that apply to every session. Procedures, pitfalls and per-task preferences go to skills. "Memory is injected into every turn and must stay small."

## 2. Skills: procedural memory

`tools/skills_tool.py`, `tools/skill_manager_tool.py`, `agent/prompt_builder.py`, `agent/curator.py`.

Skills answer "how to do this kind of task the way this user wants it". The system prompt carries only `<available_skills>`, one line per skill, with an instruction to load a matching skill with `skill_view(name)` before starting. The agent writes and fixes skills with `skill_manage` (`create`, `edit`, `patch`, `delete`, and file operations for `references/`).

Skills grow without a hard limit, so Hermes adds maintenance: the **curator** runs when the agent is idle, moves skills through lifecycle states, and may consolidate or archive them. It never deletes (archive only) and never touches pinned skills.

## 3. The session archive

`hermes_state*.py` (about 80 modules, schema version 32), `tools/session_search_tool.py`.

Every message is stored in SQLite with three FTS5 indexes: a word index, a `trigram` index for partial words, and one for CJK text. `session_search` gives the model full-text search over all past sessions. The archive costs nothing until it is searched, which is why it can be unlimited.

Compression does not delete from it: compacted messages are marked `active=0, compacted=1` and stay searchable.

## 4. Context compression

`agent/context_compressor.py` (`ContextCompressor`) and `agent/conversation_compression*.py`.

When the prompt passes a threshold (`threshold_percent = 0.50` of the usable window; 0.75 for small windows), the middle of the conversation is replaced by a structured summary written by a model (sections such as Goal, Constraints & Preferences, Completed Actions, Active State, Key Decisions, Pending User Asks). The head (`protect_first_n = 3`) and a tail are kept verbatim. The default `lean` tail mode keeps a small tail and copies the user's own words into the summary. Large tool outputs are pruned before summarising.

A note tells the model that its persistent memory in the system prompt "remains fully authoritative regardless of compaction". External providers get an `on_pre_compress` hook to save what is about to be summarised.

## 5. Background review: learning outside the turn

`agent/background_review.py`.

After a turn, every `nudge_interval` turns (default 10 for memory, 10 for skills), Hermes forks the agent in a daemon thread and asks it to review the conversation: "should any skill or memory be saved or updated?".

- **Cache-aware.** The fork inherits the parent's provider, model and cached system prompt, and replays the conversation, "so it hits the same prefix cache". If the review is routed to a different model (`auxiliary.background_review`), the cache is cold anyway, so the fork gets a compact digest instead.
- **Unattended means limited.** The review may `add`. Its `patch` and `remove` are never applied unattended; they are staged for the user (`/memory pending`).
- **Visible.** The user sees a one-line "💾 Self-improvement review: ..." summary.

A separate **write-approval gate** (off by default) can stage every write for the user, or ask inline in the CLI.

## 6. External providers and recall

`agent/memory_provider.py`, `agent/memory_manager.py`, `agent/memory_context.py`, `plugins/memory/`.

A provider implements `MemoryProvider`: four required members (`name`, `is_available`, `initialize`, `get_tool_schemas`) and optional hooks (`system_prompt_block`, `prefetch`, `queue_prefetch`, `sync_turn`, `on_turn_start`, `on_session_end`, `on_pre_compress`, `on_delegation`, `on_memory_write`, `shutdown`).

Recalled context is **data, not instructions**. It is fenced in `<memory-context>` with a system note ("recalled memory context, NOT new user input"), attached to the API copy of the user's message for that turn, and scrubbed from what is saved and streamed. External prefetch has an 8-second timeout. Everything sent to a provider passes a secret scrub first.

## 7. Memory as an attack surface

`tools/threat_patterns.py`, `tools/memory_tool_store.py`.

Anything saved to memory is replayed into every future system prompt, so a single poisoned write is a persistent prompt injection. Hermes layers its defences:

- **Scan on write** (`scope="strict"`, about 40 rules): instruction overrides, role hijacks, system-prompt spoofing, hidden HTML comments, exfiltration via `curl`/`wget`, reading secrets, SSH backdoors, C2 and anti-forensic commands, hardcoded secrets, invisible Unicode.
- **Scan on load**: an entry that is already on disk and matches is replaced in the snapshot with `[BLOCKED: ... use memory(action=remove) ...]`; the file keeps the original so a human can see and remove it.
- **Human gates**: staged writes, and no unattended deletes.
- **Fenced recall**: recalled text is labelled as data.

Known gap, stated in the code: NFKC normalisation folds full-width letters but not cross-script look-alikes (Cyrillic "а" vs Latin "a"); that would need Unicode TR#39 data.

## What this repo keeps and drops

See the [module map](../README.md#module-map). In short: all of the policies above are kept; the infrastructure around them (profiles, locking, providers, curator, hub, threads, multi-index ranking) is dropped to keep the code readable in one sitting.
