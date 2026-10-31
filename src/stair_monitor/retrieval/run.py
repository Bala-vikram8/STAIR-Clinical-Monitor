"""Run the same synthetic development questions through both section pickers."""

from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
import sqlite3

from stair_monitor.retrieval.baseline import BaselineIndex
from stair_monitor.retrieval.corpus import load_corpus
from stair_monitor.retrieval.store import get_run, init_retrieval_db, load_index, save_index, save_run
from stair_monitor.retrieval.toc import ScriptedAdapter, TocPicker
from stair_monitor.retrieval.types import Corpus


DEFAULT_QUESTIONS = Path("fixtures/synthetic-retrieval-questions.json")
DEFAULT_SCRIPT = Path("fixtures/scripted-toc-replies.json")


def load_questions(path: Path, corpus: Corpus) -> tuple[dict, str]:
    raw = path.read_bytes()
    data = json.loads(raw)
    if not isinstance(data, dict) or data.get("source_snapshot_id") != corpus.snapshot_id:
        raise ValueError("The synthetic questions belong to a different source snapshot.")
    questions = data.get("questions")
    if not isinstance(questions, list) or not questions or len(questions) > 50:
        raise ValueError("Choose a small, nonempty synthetic development question set.")
    by_id = {s.section_id: s for s in corpus.sections if not s.is_navigation}
    ids = set()
    texts = set()
    for question in questions:
        if (
            not isinstance(question, dict)
            or question.get("origin") != "synthetic"
            or not isinstance(question.get("id"), str)
            or not isinstance(question.get("text"), str)
            or not question["id"].strip()
            or not question["text"].strip()
            or len(question["text"]) > 2000
        ):
            raise ValueError("Only short, explicitly synthetic questions are accepted.")
        if question["id"] in ids or question["text"] in texts:
            raise ValueError("Synthetic question IDs and texts must be distinct.")
        ids.add(question["id"])
        texts.add(question["text"])
        if question.get("source_snapshot_id") != corpus.snapshot_id:
            raise ValueError("A synthetic question points to a different saved source.")
        expected = question.get("expected_section_id")
        if expected is not None:
            section = by_id.get(expected)
            quote = question.get("supporting_quote")
            if section is None or question.get("expected_section_title") != section.title:
                raise ValueError("An expected answer-key section does not exist in this source.")
            if not isinstance(quote, str) or not quote.strip() or quote not in section.text:
                raise ValueError("An answer-key supporting passage is absent from its source section.")
        elif question.get("expected_section_title") is not None or question.get("supporting_quote") is not None:
            raise ValueError("A question with no expected section cannot invent a source passage.")
    return data, sha256(raw).hexdigest()


def _index(connection, corpus):
    init_retrieval_db(connection)
    # Reuse only the same saved source and the exact fixed baseline settings.
    for row in connection.execute(
        "SELECT index_id FROM retrieval_indexes WHERE snapshot_id=? ORDER BY created_at DESC",
        (corpus.snapshot_id,),
    ):
        candidate = BaselineIndex.restore(load_index(connection, row["index_id"]))
        if candidate.metadata["chunk_size"] == 256 and candidate.metadata["overlap"] == 64:
            return candidate, row["index_id"]
    index = BaselineIndex.build(corpus.snapshot_id, corpus.sections, chunk_size=256, overlap=64)
    return index, save_index(connection, corpus.snapshot_id, index.export())


def run_synthetic(
    connection: sqlite3.Connection,
    *,
    mode: str = "offline_scripted",
    questions_path: Path = DEFAULT_QUESTIONS,
    script_path: Path = DEFAULT_SCRIPT,
    limit: int = 5,
    model: str | None = None,
) -> dict:
    """No free-text patient input, dashboard, treatment answer, or final benchmark."""
    if mode not in {"offline_scripted", "live"}:
        raise ValueError("Choose offline_scripted or live mode.")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 10:
        raise ValueError("Run between one and ten synthetic questions at a time.")
    corpus = load_corpus(connection)
    question_set, question_file_hash = load_questions(questions_path, corpus)
    questions = question_set["questions"][:limit]
    adapter = None
    script_hash = None
    if mode == "offline_scripted":
        raw = script_path.read_bytes()
        script = json.loads(raw)
        if script.get("mode") != "offline_scripted" or not isinstance(script.get("responses"), dict):
            raise ValueError("Offline ToC tests require an explicitly labelled scripted response file.")
        if any(question["text"] not in script["responses"] for question in questions):
            raise ValueError("A synthetic question has no scripted test response.")
        adapter = ScriptedAdapter(script["responses"])
        script_hash = sha256(raw).hexdigest()
    baseline, index_id = _index(connection, corpus)
    picker = TocPicker(corpus, adapter=adapter, model=model)
    results = []
    for question in questions:
        # The answer key and source quotations stay in the test harness.
        # Each method receives only the identical synthetic question text.
        for selection in (baseline.select(question["text"]), picker.select(question["text"])):
            results.append({
                "question_id": question["id"], "method": selection.method,
                "selection": asdict(selection),
            })
    settings = {
        "purpose": "development smoke test; not a held-out benchmark",
        "question_set_version": question_set.get("version"),
        "question_file_sha256": question_file_hash, "script_file_sha256": script_hash,
        "index_id": index_id, "baseline": baseline.metadata,
        "toc_model": picker.model, "max_questions": limit,
        "full_toc_entries": len(corpus.toc), "source_sha256": corpus.source_sha256,
        "mode_notice": (
            "The ToC selections are scripted test-double replies, not Claude predictions. "
            "Do not compare their accuracy with the baseline."
            if mode == "offline_scripted" else
            "Claude results are live only when their status records a completed API response. "
            "Blocked and error outcomes are not predictions."
        ),
        "answer_generation": False, "dashboard": False,
    }
    run_id = save_run(
        connection, snapshot_id=corpus.snapshot_id, mode=mode,
        questions=questions, settings=settings, results=results,
    )
    return get_run(connection, run_id)


def sample_rows(run: dict, limit: int = 5) -> list[dict]:
    by_pair = {(row["question_id"], row["method"]): row["selection"] for row in run["results"]}
    rows = []
    for question in run["questions"][:limit]:
        baseline = by_pair[(question["id"], "baseline_tfidf")]
        toc = by_pair[(question["id"], "toc_claude")]
        rows.append({
            "question_id": question["id"], "question": question["text"],
            "baseline_section": baseline["section_title"], "baseline_status": baseline["status"],
            "toc_section": toc["section_title"], "toc_status": toc["status"],
            "toc_mode": toc.get("details", {}).get("mode"),
            "toc_reason": toc.get("reason"),
        })
    return rows
