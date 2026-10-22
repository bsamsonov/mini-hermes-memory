from mini_hermes import background_review, config
from mini_hermes.agent import Agent
from tests.conftest import answer, tool_call


def test_memory_write_does_not_change_this_sessions_prompt(tmp_path, fake_llm):
    agent = Agent(home=tmp_path, workspace=tmp_path)
    fake_llm.replies = [
        tool_call("memory", target="user", operations=[{"action": "add", "content": "Name is Boris"}]),
        answer("Nice to meet you, Boris"),
        answer("Hello again"),
    ]
    agent.run_turn("Hi, I'm Boris")
    agent.run_turn("Hello")

    first, last = fake_llm.requests[0][0], fake_llm.requests[-1][0]
    assert first == last  # byte-identical system prompt -> prefix cache stays warm
    assert "Name is Boris" in Agent(home=tmp_path).system_prompt()


def test_recalled_block_never_enters_history(tmp_path, fake_llm):
    agent = Agent(home=tmp_path, workspace=tmp_path)
    agent.db.save("older-session", "user", "The staging database listens on port 5433")
    fake_llm.replies = [answer("Port 5433")]

    agent.run_turn("which port does the staging database use?")

    sent_user_message = fake_llm.requests[0][1]["content"]
    assert "<memory-context>" in sent_user_message
    assert all("<memory-context>" not in str(m["content"]) for m in agent.history)


def test_review_replays_the_same_prefix_for_the_cache(tmp_path, fake_llm, monkeypatch):
    monkeypatch.setattr(config, "REVIEW_MODEL", config.MODEL)
    monkeypatch.setattr(background_review, "TURNS_BETWEEN_REVIEWS", 1)
    agent = Agent(home=tmp_path, workspace=tmp_path)
    fake_llm.replies = [
        answer("Sure, short answers from now on"),
        tool_call("memory", target="user", operations=[{"action": "add", "content": "Prefers short answers"}]),
    ]
    agent.run_turn("Please keep answers short")
    summary = agent.after_turn()

    main_call, review_call = fake_llm.requests
    assert review_call[: len(main_call)] == main_call  # same prefix
    assert summary.startswith("added")


def test_tool_errors_are_results_not_crashes(tmp_path, fake_llm):
    agent = Agent(home=tmp_path, workspace=tmp_path)
    fake_llm.replies = [tool_call("read_file", path="../../etc/passwd"), answer("Can't read that")]
    agent.run_turn("show me /etc/passwd")
    assert "outside the working directory" in agent.history[2]["content"]


def test_single_operation_shape_is_accepted(tmp_path, fake_llm):
    # The schema asks for `operations`, but models often send one flat operation.
    agent = Agent(home=tmp_path, workspace=tmp_path)
    fake_llm.replies = [tool_call("memory", target="user", action="add", content="Lives in Kyiv"), answer("Noted")]
    agent.run_turn("I live in Kyiv")
    assert agent.memory.entries["user"] == ["Lives in Kyiv"]
