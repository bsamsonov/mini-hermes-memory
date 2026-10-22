from mini_hermes.session_db import SessionDB


def test_search_finds_other_word_forms(tmp_path):
    db = SessionDB(tmp_path / "state.db")
    db.save("s1", "user", "My servers run in the Europe/Kyiv timezone")
    hits = db.search("which timezones do we use?")
    assert hits and "Europe/Kyiv" in hits[0]["text"]


def test_search_returns_full_text_and_skips_a_session(tmp_path):
    db = SessionDB(tmp_path / "state.db")
    long_text = "deploy " + "word " * 100 + "ends with UTC"
    db.save("s1", "assistant", long_text)
    db.save("s2", "user", "deploy again")
    hits = db.search("deploy", exclude_session="s2")
    assert [h["text"] for h in hits] == [long_text]


def test_query_syntax_characters_are_harmless(tmp_path):
    db = SessionDB(tmp_path / "state.db")
    db.save("s1", "user", "C++ and -flags")
    assert db.search('"-flags" OR * NEAR(') is not None
