"""Save search indexes and paired synthetic-question runs without changing sources."""

from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
import json
import sqlite3
from typing import Iterator
from uuid import uuid4


METHODS = ("baseline_tfidf", "toc_claude")
MODES = {"offline_scripted", "live"}
STATUSES = {"selected", "no_match", "invalid", "blocked", "error"}

_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS retrieval_indexes (
        index_id TEXT PRIMARY KEY,
        snapshot_id TEXT NOT NULL REFERENCES snapshots(snapshot_id),
        created_at TEXT NOT NULL,
        payload_sha256 TEXT NOT NULL,
        config_json TEXT NOT NULL,
        payload_json TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS synthetic_runs (
        run_id TEXT PRIMARY KEY,
        snapshot_id TEXT NOT NULL REFERENCES snapshots(snapshot_id),
        created_at TEXT NOT NULL,
        mode TEXT NOT NULL CHECK(mode IN ('offline_scripted', 'live')),
        status TEXT NOT NULL CHECK(status IN ('complete', 'incomplete')),
        questions_sha256 TEXT NOT NULL,
        questions_json TEXT NOT NULL,
        settings_json TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS retrieval_results (
        run_id TEXT NOT NULL REFERENCES synthetic_runs(run_id),
        question_id TEXT NOT NULL,
        question_text TEXT NOT NULL,
        origin TEXT NOT NULL CHECK(origin = 'synthetic'),
        method TEXT NOT NULL CHECK(method IN ('baseline_tfidf', 'toc_claude')),
        status TEXT NOT NULL CHECK(status IN ('selected', 'no_match', 'invalid', 'blocked', 'error')),
        selection_json TEXT NOT NULL,
        PRIMARY KEY(run_id, question_id, method)
    )""",
)


@contextmanager
def _write(conn: sqlite3.Connection) -> Iterator[None]:
    # A savepoint preserves unrelated work when the caller already has a transaction.
    conn.execute("SAVEPOINT retrieval_write")
    try:
        yield
        conn.execute("RELEASE SAVEPOINT retrieval_write")
    except BaseException:
        conn.execute("ROLLBACK TO SAVEPOINT retrieval_write")
        conn.execute("RELEASE SAVEPOINT retrieval_write")
        raise


def init_retrieval_db(conn: sqlite3.Connection) -> None:
    """Add search tables without changing the source schema version or its rows."""
    if not conn.execute("PRAGMA foreign_keys").fetchone()[0]:
        raise ValueError("Open storage with foreign-key checks enabled.")
    if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'snapshots'"
    ).fetchone() is None:
        raise ValueError("Prepare the source storage before saving retrieval runs.")
    with _write(conn):
        for statement in _SCHEMA:
            conn.execute(statement)


def _required(value: object, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a nonempty string.")


def _json(value: object) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("Search records must contain plain JSON values and finite numbers.") from exc


def _no_secrets(value: object) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).casefold() in {
                "api_key", "anthropic_api_key", "authorization", "access_token", "refresh_token",
            }:
                raise ValueError("Do not save API keys or authentication fields in search records.")
            _no_secrets(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _no_secrets(item)


def _source(conn: sqlite3.Connection, snapshot_id: str) -> dict[str, str]:
    _required(snapshot_id, "Snapshot ID")
    exists = conn.execute("SELECT 1 FROM snapshots WHERE snapshot_id = ?", (snapshot_id,)).fetchone()
    if exists is None:
        raise ValueError("The saved source snapshot does not exist.")
    return {
        row[0]: row[1]
        for row in conn.execute("SELECT section_id, title FROM sections WHERE snapshot_id = ?", (snapshot_id,))
    }


def save_index(conn: sqlite3.Connection, snapshot_id: str, payload: dict) -> str:
    """Keep vectors as plain JSON values, never executable object files."""
    init_retrieval_db(conn)
    _source(conn, snapshot_id)
    if not isinstance(payload, dict):
        raise ValueError("The index export must be a JSON object.")
    if payload.get("snapshot_id", snapshot_id) != snapshot_id:
        raise ValueError("The index belongs to a different source snapshot.")
    _no_secrets(payload)
    encoded = _json(payload)
    digest = sha256(encoded.encode()).hexdigest()
    index_id = sha256(_json([snapshot_id, digest]).encode()).hexdigest()
    config = payload.get("metadata", payload.get("config", {}))
    with _write(conn):
        conn.execute(
            """INSERT OR IGNORE INTO retrieval_indexes
                (index_id, snapshot_id, created_at, payload_sha256, config_json, payload_json)
                VALUES (?, ?, ?, ?, ?, ?)""",
            (index_id, snapshot_id, datetime.now(timezone.utc).isoformat(), digest, _json(config), encoded),
        )
    return index_id


def load_index(conn: sqlite3.Connection, index_id: str) -> dict:
    """Read and hash-check a saved index before passing it to the vector reader."""
    row = conn.execute(
        "SELECT snapshot_id, payload_sha256, payload_json FROM retrieval_indexes WHERE index_id = ?",
        (index_id,),
    ).fetchone()
    if row is None:
        raise ValueError("The saved index does not exist.")
    if sha256(row[2].encode()).hexdigest() != row[1]:
        raise ValueError("The saved index does not match its recorded hash.")
    if sha256(_json([row[0], row[1]]).encode()).hexdigest() != index_id:
        raise ValueError("The saved index identity does not match its source and hash.")
    payload = json.loads(row[2])
    if not isinstance(payload, dict) or payload.get("snapshot_id", row[0]) != row[0]:
        raise ValueError("The saved index belongs to a different source snapshot.")
    return payload


def _questions(questions: list[dict], sections: dict[str, str]) -> dict[str, dict]:
    if not isinstance(questions, list) or not questions:
        raise ValueError("A run needs a nonempty synthetic question list.")
    by_id = {}
    for question in questions:
        if not isinstance(question, dict):
            raise ValueError("Every question must be a JSON object.")
        _required(question.get("id"), "Question ID")
        _required(question.get("text"), "Synthetic question text")
        if question.get("origin") != "synthetic":
            raise ValueError("Only explicitly marked synthetic questions may be recorded.")
        if question["id"] in by_id:
            raise ValueError("Question IDs must be unique within a run.")
        expected_id = question.get("expected_section_id")
        if expected_id is not None:
            if expected_id not in sections:
                raise ValueError("An expected section is missing from this source snapshot.")
            expected_title = question.get("expected_section_title")
            if expected_title is not None and expected_title != sections[expected_id]:
                raise ValueError("An expected section title does not match its source ID.")
        by_id[question["id"]] = question
    return by_id


def _results(results: list[dict], questions: dict[str, dict], sections: dict[str, str], mode: str) -> dict:
    if not isinstance(results, list):
        raise ValueError("Results must be a list of paired method selections.")
    pairs = {}
    for result in results:
        if not isinstance(result, dict):
            raise ValueError("Every result must be a JSON object.")
        question_id = result.get("question_id")
        method = result.get("method")
        if question_id not in questions or method not in METHODS:
            raise ValueError("A result has an unknown question or retrieval method.")
        key = (question_id, method)
        if key in pairs:
            raise ValueError("A question and method have more than one result.")
        for text_key in ("query", "question_text"):
            if text_key in result and result[text_key] != questions[question_id]["text"]:
                raise ValueError("A result query differs from the saved synthetic question.")
        selection = result.get("selection")
        if not isinstance(selection, dict) or selection.get("method") != method:
            raise ValueError("A selection must identify the same method as its result.")
        if selection.get("status") not in STATUSES:
            raise ValueError("A selection has an unknown result status.")
        section_id = selection.get("section_id")
        title = selection.get("section_title")
        if selection["status"] == "selected":
            if section_id not in sections or (isinstance(section_id, str) and section_id.startswith("group-")):
                raise ValueError("A selected section is missing or is only a navigation heading.")
            if title != sections[section_id]:
                raise ValueError("A selected section title does not match its source ID.")
        elif section_id is not None or title is not None:
            raise ValueError("A nonselected result must not pretend to select a source section.")
        details = selection.get("details", {})
        if not isinstance(details, dict):
            raise ValueError("Selection details must be a JSON object.")
        allowed_adapter_modes = {"live", "live_claude"} if mode == "live" else {"offline_scripted"}
        if method == "toc_claude" and details.get("mode") not in allowed_adapter_modes:
            raise ValueError("The ToC result mode does not match this run's mode.")
        pairs[key] = selection
    expected = {(question_id, method) for question_id in questions for method in METHODS}
    if set(pairs) != expected:
        raise ValueError("Every synthetic question needs one result from each retrieval method.")
    return pairs


def save_run(
    conn: sqlite3.Connection,
    *,
    snapshot_id: str,
    mode: str,
    questions: list[dict],
    settings: dict,
    results: list[dict],
) -> str:
    """Save the same questions and both actual method outcomes together."""
    init_retrieval_db(conn)
    sections = _source(conn, snapshot_id)
    if mode not in MODES:
        raise ValueError("Run mode must be live or offline_scripted.")
    if not isinstance(settings, dict):
        raise ValueError("Run settings must be a JSON object.")
    question_map = _questions(questions, sections)
    paired = _results(results, question_map, sections, mode)
    _no_secrets([questions, settings, results])
    question_json = _json(questions)
    settings_json = _json(settings)
    encoded_pairs = {pair: _json(selection) for pair, selection in paired.items()}
    run_id = str(uuid4())
    status = "incomplete" if any(s["status"] in {"blocked", "error"} for s in paired.values()) else "complete"
    with _write(conn):
        conn.execute(
            """INSERT INTO synthetic_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (run_id, snapshot_id, datetime.now(timezone.utc).isoformat(), mode, status,
             sha256(question_json.encode()).hexdigest(), question_json, settings_json),
        )
        for question_id, question in question_map.items():
            for method in METHODS:
                selection = paired[(question_id, method)]
                conn.execute(
                    "INSERT INTO retrieval_results VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (run_id, question_id, question["text"], "synthetic", method,
                     selection["status"], encoded_pairs[(question_id, method)]),
                )
    return run_id


def get_run(conn: sqlite3.Connection, run_id: str) -> dict:
    """Return a stored paired run, including blocked and invalid selections."""
    row = conn.execute("SELECT * FROM synthetic_runs WHERE run_id = ?", (run_id,)).fetchone()
    if row is None:
        raise ValueError("The saved run does not exist.")
    run = dict(row)
    if sha256(run["questions_json"].encode()).hexdigest() != run["questions_sha256"]:
        raise ValueError("The saved questions do not match their recorded hash.")
    run["questions"] = json.loads(run.pop("questions_json"))
    run["settings"] = json.loads(run.pop("settings_json"))
    result_rows = conn.execute(
        "SELECT question_id, method, selection_json FROM retrieval_results WHERE run_id = ? ORDER BY rowid",
        (run_id,),
    ).fetchall()
    run["results"] = [
        {"question_id": result[0], "method": result[1], "selection": json.loads(result[2])}
        for result in result_rows
    ]
    return run


def list_runs(conn: sqlite3.Connection) -> list[dict]:
    """List run metadata without printing question or response text."""
    return [dict(row) for row in conn.execute(
        """SELECT run_id, snapshot_id, created_at, mode, status, questions_sha256
        FROM synthetic_runs ORDER BY created_at, run_id"""
    )]
