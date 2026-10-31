"""Search records use invented questions and source text, never patient data."""

from copy import deepcopy
import sqlite3

import pytest

from stair_monitor.retrieval.store import (
    get_run, init_retrieval_db, list_runs, load_index, save_index, save_run,
)
from stair_monitor.storage import SectionRecord, TocEntry, connect, init_db, register_guideline, save_snapshot


@pytest.fixture
def db():
    conn = connect(":memory:")
    init_db(conn)
    register_guideline(conn, slug="fixture", title="Invented text", publisher="Test", source_url="https://example.org/text")
    snapshot = save_snapshot(
        conn, guideline_slug="fixture", raw_content=b"Invented public source fixture",
        fetched_at="2026-10-31T12:00:00Z", source_url="https://example.org/text",
        archive_path="ignored/fixture.txt", text="Invented facts", parser_version="test",
        sections=[SectionRecord("m1", "Invented heading", ("Invented heading",), None,
                                "https://example.org/text#m1", "Invented facts", 0, 14, 0)],
        toc=[TocEntry("Invented heading", "https://example.org/text#m1", 1, 0, "m1")],
    )
    init_retrieval_db(conn)
    yield conn, snapshot
    conn.close()


def run_data(snapshot):
    question = {"id": "sample", "text": "Which invented topic is covered?", "origin": "synthetic",
                "expected_section_id": "m1", "expected_section_title": "Invented heading"}
    results = []
    for method in ["baseline_tfidf", "toc_claude"]:
        selection = {"method": method, "status": "selected", "section_id": "m1",
                     "section_title": "Invented heading", "details": {"mode": "offline_scripted"}}
        results.append({"question_id": "sample", "method": method, "selection": selection})
    return dict(snapshot_id=snapshot, mode="offline_scripted", questions=[question],
                settings={"chunk_size": 256}, results=results)


def test_table_setup_preserves_source_rows_and_schema_version(db):
    conn, snapshot = db
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    init_retrieval_db(conn)
    init_retrieval_db(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == version
    assert conn.execute("SELECT COUNT(*) FROM sections").fetchone()[0] == 1
    assert conn.execute("SELECT snapshot_id FROM snapshots").fetchone()[0] == snapshot


def test_index_round_trip_is_repeatable_and_checked(db):
    conn, snapshot = db
    payload = {"snapshot_id": snapshot, "metadata": {"kind": "tfidf"}, "vectors": {"data": [0.25], "indices": [0]}}
    first = save_index(conn, snapshot, payload)
    assert save_index(conn, snapshot, deepcopy(payload)) == first
    assert load_index(conn, first) == payload
    assert conn.execute("SELECT COUNT(*) FROM retrieval_indexes").fetchone()[0] == 1
    conn.execute("UPDATE retrieval_indexes SET payload_json = '{}' WHERE index_id = ?", (first,))
    with pytest.raises(ValueError, match="hash"):
        load_index(conn, first)


def test_index_cannot_claim_different_source_or_save_unsafe_values(db):
    conn, snapshot = db
    with pytest.raises(ValueError, match="different"):
        save_index(conn, snapshot, {"snapshot_id": "other"})
    with pytest.raises(ValueError, match="finite"):
        save_index(conn, snapshot, {"values": [float("nan")]})
    with pytest.raises(ValueError, match="API keys"):
        save_index(conn, snapshot, {"authorization": "invented secret placeholder"})
    assert conn.execute("SELECT COUNT(*) FROM retrieval_indexes").fetchone()[0] == 0


def test_paired_questions_and_each_method_result_are_retained(db):
    conn, snapshot = db
    data = run_data(snapshot)
    run_id = save_run(conn, **data)
    run = get_run(conn, run_id)
    assert run["questions"] == data["questions"]
    assert run["settings"] == data["settings"]
    assert run["results"] == data["results"]
    assert run["mode"] == "offline_scripted" and run["status"] == "complete"
    assert len(list_runs(conn)) == 1
    assert conn.execute("SELECT COUNT(*) FROM retrieval_results").fetchone()[0] == 2


def test_blocked_live_api_is_saved_as_incomplete_not_selected(db):
    conn, snapshot = db
    data = run_data(snapshot)
    data["mode"] = "live"
    data["results"][1]["selection"] = {
        "method": "toc_claude", "status": "blocked", "section_id": None, "section_title": None,
        "reason": "API key missing", "details": {"mode": "live"},
    }
    run = get_run(conn, save_run(conn, **data))
    assert run["status"] == "incomplete"
    assert run["results"][1]["selection"]["status"] == "blocked"
    assert run["results"][1]["selection"]["section_id"] is None


def test_live_adapter_label_is_retained_without_calling_it_a_scripted_run(db):
    conn, snapshot = db
    data = run_data(snapshot)
    data["mode"] = "live"
    data["results"][1]["selection"]["details"]["mode"] = "live_claude"
    run = get_run(conn, save_run(conn, **data))
    assert run["mode"] == "live" and run["status"] == "complete"
    assert run["results"][1]["selection"]["details"]["mode"] == "live_claude"


@pytest.mark.parametrize("mode", ["live", "offline_scripted"])
def test_toc_result_requires_explicit_adapter_mode(db, mode):
    conn, snapshot = db
    data = run_data(snapshot)
    data["mode"] = mode
    data["results"][1]["selection"]["details"].pop("mode")
    with pytest.raises(ValueError, match="mode"):
        save_run(conn, **data)
    assert conn.execute("SELECT COUNT(*) FROM synthetic_runs").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM retrieval_results").fetchone()[0] == 0


@pytest.mark.parametrize("change", ["missing", "duplicate", "method", "section", "title", "query", "mode", "origin", "question_duplicate"])
def test_invalid_pairs_save_no_partial_run(db, change):
    conn, snapshot = db
    data = run_data(snapshot)
    if change == "missing":
        data["results"].pop()
    elif change == "duplicate":
        data["results"].append(deepcopy(data["results"][0]))
    elif change == "method":
        data["results"][0]["method"] = "unknown"
    elif change == "section":
        data["results"][0]["selection"]["section_id"] = "missing"
    elif change == "title":
        data["results"][0]["selection"]["section_title"] = "Wrong heading"
    elif change == "query":
        data["results"][0]["query"] = "Another question"
    elif change == "mode":
        data["results"][1]["selection"]["details"]["mode"] = "live"
    elif change == "origin":
        data["questions"][0]["origin"] = "user"
    else:
        data["questions"].append(deepcopy(data["questions"][0]))
    with pytest.raises(ValueError):
        save_run(conn, **data)
    assert conn.execute("SELECT COUNT(*) FROM synthetic_runs").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM retrieval_results").fetchone()[0] == 0


def test_failed_run_keeps_unrelated_caller_transaction(db):
    conn, snapshot = db
    conn.execute("BEGIN")
    register_guideline(conn, slug="other", title="Other", publisher="Test", source_url="https://example.org/other")
    data = run_data(snapshot)
    data["results"].pop()
    with pytest.raises(ValueError):
        save_run(conn, **data)
    assert conn.in_transaction
    assert conn.execute("SELECT COUNT(*) FROM guidelines").fetchone()[0] == 2
    conn.execute("ROLLBACK")
    assert conn.execute("SELECT COUNT(*) FROM guidelines").fetchone()[0] == 1


def test_repeated_runs_preserve_separate_attempts(db):
    conn, snapshot = db
    first = save_run(conn, **run_data(snapshot))
    second = save_run(conn, **run_data(snapshot))
    assert first != second and len(list_runs(conn)) == 2
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
