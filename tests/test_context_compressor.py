from mini_hermes import config
from mini_hermes.context_compressor import compress, should_compress
from tests.conftest import answer


def test_threshold_is_half_the_window():
    assert not should_compress(config.CONTEXT_WINDOW // 2)
    assert should_compress(config.CONTEXT_WINDOW // 2 + 1)


def test_middle_is_summarised_head_and_tail_kept(fake_llm, monkeypatch):
    monkeypatch.setattr(config, "CONTEXT_WINDOW", 300)  # tail budget: 60 tokens ~ 180 chars
    history = []
    for i in range(6):
        history += [{"role": "user", "content": f"question {i} " + "x" * 60},
                    {"role": "assistant", "content": f"answer {i}"}]
    fake_llm.replies = [answer("## Goal\nsummary")]

    out = compress(history)

    assert out[:2] == history[:2]  # head: the first exchange
    assert "## Goal" in out[2]["content"] and "authoritative" in out[2]["content"]
    assert out[-2:] == history[-2:]  # tail: the latest exchange
    assert len(out) < len(history)
