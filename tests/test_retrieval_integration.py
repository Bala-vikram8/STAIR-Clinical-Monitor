"""Actual stored source, real vector search, explicitly scripted ToC responses."""

from contextlib import closing
import json
from pathlib import Path
import sqlite3

import pytest

from stair_monitor.retrieval.corpus import load_corpus
from stair_monitor.retrieval.run import DEFAULT_QUESTIONS, DEFAULT_SCRIPT, load_questions, run_synthetic
from stair_monitor.retrieval.toc import ScriptedAdapter
from stair_monitor.storage import connect, init_db


@pytest.fixture(scope="module")
def imported_copy(tmp_path_factory):
    source = Path("data/guidelines.sqlite3")
    if not source.is_file():
        pytest.skip("Import OpenStax first to run the full-source integration checks.")
    with closing(sqlite3.connect(f"file:{source}?mode=ro", uri=True)) as original:
        has_source = original.execute(
            "SELECT COUNT(*) FROM snapshots WHERE guideline_slug='openstax-anatomy-physiology'"
        ).fetchone()[0]
        if not has_source:
            pytest.skip("Import OpenStax first to run the full-source integration checks.")
        with closing(connect(tmp_path_factory.mktemp("paired-source") / "copy.sqlite3")) as connection:
            original.backup(connection)
            yield connection


def test_same_real_source_questions_pass_through_both_methods(imported_copy, monkeypatch):
    replies = json.loads(DEFAULT_SCRIPT.read_text())["responses"]
    adapter = ScriptedAdapter(replies)
    monkeypatch.setattr("stair_monitor.retrieval.run.ScriptedAdapter", lambda _: adapter)
    corpus = load_corpus(imported_copy)
    question_set, _ = load_questions(DEFAULT_QUESTIONS, corpus)
    run = run_synthetic(imported_copy, mode="offline_scripted", limit=9)
    assert run["status"] == "complete"
    assert len(run["questions"]) == 9
    assert len(run["results"]) == 18
    assert len(adapter.requests) == 9
    assert {q["text"] for q in run["questions"]} == {r["query"] for r in adapter.requests}
    for request in adapter.requests:
        prompt = json.loads(request["messages"][0]["content"])
        assert len(prompt["table_of_contents"]) == len(corpus.toc) == 232
        assert {item["section_id"] for item in prompt["table_of_contents"]} == {s.section_id for s in corpus.sections}
        assert "expected_section_id" not in request["messages"][0]["content"]
        assert "supporting_quote" not in request["messages"][0]["content"]
        for question in question_set["questions"]:
            if question.get("supporting_quote"):
                assert question["supporting_quote"] not in request["messages"][0]["content"]
    assert all(row["selection"]["details"]["mode"] == "offline_scripted"
               for row in run["results"] if row["method"] == "toc_claude")
    assert any(row["selection"].get("score", 0) for row in run["results"] if row["method"] == "baseline_tfidf")
    assert run["settings"]["baseline"]["chunk_size"] == 256
    assert run["settings"]["baseline"]["overlap"] == 64
    assert len({(r["question_id"], r["method"]) for r in run["results"]}) == 18


def test_live_missing_key_records_blocked_outcomes_not_predictions(imported_copy, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    before = imported_copy.execute('SELECT COUNT(*) FROM retrieval_indexes').fetchone()[0]
    run = run_synthetic(imported_copy, mode="live", limit=5)
    assert run["status"] == "incomplete"
    selections = [r["selection"] for r in run["results"] if r["method"] == "toc_claude"]
    assert len(selections) == 5
    assert all(r["status"] == "blocked" and r["section_id"] is None for r in selections)
    assert all(r["details"]["reason_code"] == "missing_api_key" for r in selections)
    assert imported_copy.execute('SELECT COUNT(*) FROM retrieval_indexes').fetchone()[0] == before


def test_question_loader_rejects_unmarked_questions(imported_copy, tmp_path):
    corpus = load_corpus(imported_copy)
    fixture = json.loads(DEFAULT_QUESTIONS.read_text())
    fixture["questions"][0]["origin"] = "unreviewed"
    path = tmp_path / "not-synthetic.json"
    path.write_text(json.dumps(fixture))
    with pytest.raises(ValueError, match="synthetic"):
        load_questions(path, corpus)


def test_placeholder_source_storage_is_not_retrieval_ready():
    with closing(connect(":memory:")) as connection:
        init_db(connection)
        with pytest.raises(ValueError, match="complete OpenStax"):
            load_corpus(connection)


def test_matching_partial_toc_and_sections_still_fail_complete_source_check(imported_copy):
    imported_copy.execute('SAVEPOINT corrupt_source_for_test')
    try:
        imported_copy.execute("DELETE FROM toc_entries WHERE section_id='m45989'")
        imported_copy.execute("DELETE FROM sections WHERE section_id='m45989'")
        with pytest.raises(ValueError, match="do not match"):
            load_corpus(imported_copy)
    finally:
        imported_copy.execute('ROLLBACK TO SAVEPOINT corrupt_source_for_test')
        imported_copy.execute('RELEASE SAVEPOINT corrupt_source_for_test')
