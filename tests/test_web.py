"""Comparison pages use invented stored rows and never call a model."""

from contextlib import closing
from copy import deepcopy
import sqlite3

from fastapi.testclient import TestClient
from bs4 import BeautifulSoup
import pytest

from stair_monitor.retrieval.store import init_retrieval_db, save_run
from stair_monitor.storage import SectionRecord, TocEntry, connect, init_db, register_guideline, save_snapshot
from stair_monitor.web import NoLiveRun, comparison_data, create_app, render_comparison


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "view.sqlite3"
    connection = connect(path)
    init_db(connection)
    register_guideline(connection, slug="test", title="Invented public textbook", publisher="Test publisher", source_url="https://example.org/book")
    snapshot = save_snapshot(
        connection, guideline_slug="test", raw_content=b"Invented source text", fetched_at="2026-10-31T10:00:00Z",
        source_url="https://example.org/book", archive_path="ignored/source.txt", text="Made-up body.", parser_version="test",
        publication_date_note="unknown – publisher content",
        sections=[SectionRecord("m1", "Invented section", ("Invented section",), None,
                                "https://example.org/book#section", "Made-up body.", 0, 13, 0)],
        toc=[TocEntry("Invented section", "https://example.org/book#section", 1, 0, "m1")],
    )
    init_retrieval_db(connection)
    yield connection, path, snapshot
    connection.close()


def save_example(connection, snapshot, *, mode="live", status="selected", evidence=True, text="Which invented topic is described?"):
    questions = [{"id": "synthetic-01", "text": text, "origin": "synthetic"}]
    baseline = {"method": "baseline_tfidf", "status": "selected", "section_id": "m1", "section_title": "Invented section", "details": {}}
    toc = {"method": "toc_claude", "status": status,
           "section_id": "m1" if status == "selected" else None,
           "section_title": "Invented section" if status == "selected" else None,
           "reason": "API key missing" if status == "blocked" else None,
           "details": {"mode": "live_claude" if mode == "live" else "offline_scripted"}}
    if evidence:
        toc["details"].update(raw_response='{"status":"selected"}', response_model="claude-opus-5-5" if mode == "live" else "offline-scripted-test-double")
    return save_run(connection, snapshot_id=snapshot, mode=mode, questions=questions,
                    settings={"toc_model": "claude-opus-5-5"}, results=[
                        {"question_id": "synthetic-01", "method": "baseline_tfidf", "selection": baseline},
                        {"question_id": "synthetic-01", "method": "toc_claude", "selection": toc},
                    ])


def test_latest_live_run_is_default_even_when_scripted_run_is_newer(db):
    connection, path, snapshot = db
    live = save_example(connection, snapshot, status="blocked", evidence=False)
    save_example(connection, snapshot, mode="offline_scripted")
    client = TestClient(create_app(path))
    response = client.get("/api/comparison")
    assert response.status_code == 200
    data = response.json()
    assert data["run_id"] == live and data["mode"] == "live"
    assert data["live_responses"] == 0
    assert data["rows"][0]["toc"]["status"] == "blocked"
    html = client.get("/").text
    assert "Live run incomplete" in html
    assert "Live attempt · no completed response" in html
    assert "API key missing" in html
    assert "Live API response" not in html
    assert "unknown – publisher content" in html


def test_newest_live_error_does_not_fall_back_to_older_success(db):
    connection, _, snapshot = db
    save_example(connection, snapshot)
    latest = save_example(connection, snapshot, status="error", evidence=False)
    data = comparison_data(connection)
    assert data["run_id"] == latest and data["status"] == "incomplete"
    assert data["status_counts"]["toc"]["error"] == 1
    assert data["live_responses"] == 0


def test_explicit_scripted_history_is_clearly_labelled(db):
    connection, path, snapshot = db
    scripted = save_example(connection, snapshot, mode="offline_scripted")
    client = TestClient(create_app(path))
    html = client.get("/", params={"run_id": scripted}).text
    assert "Offline test run" in html
    assert "Scripted test reply · not a Claude prediction" in html
    assert "Live API response" not in html
    assert client.get("/api/comparison").status_code == 404
    assert "No live retrieval run" in client.get("/").text


def test_completed_live_response_has_evidence_and_matching_question(db):
    connection, path, snapshot = db
    save_example(connection, snapshot)
    client = TestClient(create_app(path))
    data = client.get("/api/comparison").json()
    assert data["question_count"] == data["live_responses"] == 1
    assert data["rows"][0]["baseline"]["section_title"] == "Invented section"
    assert data["rows"][0]["toc"]["section_title"] == "Invented section"
    assert data["rows"][0]["question"] == "Which invented topic is described?"
    assert data["rows"][0]["mode"] == "live"
    assert data["rows"][0]["toc"]["mode"] == "live"
    assert data["rows"][0]["baseline"]["mode"] == "live"
    assert data["model"] == "claude-opus-5-5"
    assert "Live API response" in client.get("/").text
    assert "raw_response" not in str(data)


def test_live_label_alone_is_not_a_completed_provider_response(db):
    connection, _, snapshot = db
    save_example(connection, snapshot, evidence=False)
    data = comparison_data(connection)
    assert data["live_responses"] == 0
    html = render_comparison(connection)
    assert "response evidence incomplete" in html
    assert "Live API response" not in html
    assert "Live run incomplete" in html


def test_html_escapes_untrusted_question_title_and_urls(db):
    connection, path, snapshot = db
    save_example(connection, snapshot, text='<script>alert("not executed")</script>')
    connection.execute("UPDATE sections SET source_url='javascript:alert(1)'")
    connection.execute("UPDATE guidelines SET title='<img src=x onerror=alert(1)>'")
    client = TestClient(create_app(path))
    html = client.get("/").text
    assert '<script>alert(' not in html
    assert '&lt;script&gt;' in html
    assert '<img src=x' not in html
    assert '&lt;img src=x' in html
    assert 'href="javascript:' not in html


def test_unknown_run_and_missing_database_are_explicit(db, tmp_path):
    _, path, _ = db
    client = TestClient(create_app(path))
    assert client.get("/", params={"run_id": "missing"}).status_code == 404
    assert client.get("/api/comparison", params={"run_id": "missing"}).status_code == 404
    absent = tmp_path / "absent.sqlite3"
    missing_client = TestClient(create_app(absent))
    assert missing_client.get("/").status_code == 503
    assert missing_client.get("/health").status_code == 503
    assert not absent.exists()


def test_orphaned_method_outcome_is_not_shown_as_a_valid_pair(db):
    connection, path, snapshot = db
    run = save_example(connection, snapshot)
    connection.execute("DELETE FROM retrieval_results WHERE run_id=? AND method='toc_claude'", (run,))
    client = TestClient(create_app(path))
    assert client.get("/").status_code == 503
    assert client.get("/api/comparison").status_code == 503


def test_routes_are_read_only_and_do_not_expose_answer_or_query_endpoint(db):
    connection, path, snapshot = db
    save_example(connection, snapshot)
    before = connection.total_changes
    client = TestClient(create_app(path))
    assert client.get("/").status_code == 200
    assert client.get("/health").json()["status"] == "ready"
    assert client.get("/api/comparison").status_code == 200
    assert client.post("/").status_code == 405
    assert client.post("/answer", json={"query": "not accepted"}).status_code == 404
    assert connection.total_changes == before


def test_standalone_renderer_and_route_use_the_same_page(db):
    connection, path, snapshot = db
    save_example(connection, snapshot)
    expected = render_comparison(connection)
    response = TestClient(create_app(path)).get("/")
    assert response.text == expected
    page = BeautifulSoup(expected, "html.parser")
    for hidden in page.select("style, script"):
        hidden.decompose()
    visible = page.get_text(" ", strip=True)
    assert "No answer generator is included" in visible
    assert "Accuracy" not in visible
    assert "0%" not in visible
