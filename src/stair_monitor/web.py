"""Read-only comparison page built from saved paired retrieval runs."""

from contextlib import contextmanager
from datetime import datetime
from html import escape
from pathlib import Path
import sqlite3
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

from stair_monitor.retrieval.store import get_run


class NoLiveRun(LookupError):
    """The page must not replace a missing live run with scripted results."""


class RunNotFound(LookupError):
    """An explicitly requested run does not exist."""


def _public_url(value) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password:
            return value
    except ValueError:
        pass
    return None


def _has_live_response(selection: dict, run_mode: str) -> bool:
    details = selection.get("details", {})
    model = details.get("response_model")
    return (
        run_mode == "live"
        and details.get("mode") in {"live", "live_claude"}
        and selection.get("status") in {"selected", "no_match", "invalid"}
        and isinstance(details.get("raw_response"), str)
        and bool(details["raw_response"].strip())
        and isinstance(model, str)
        and bool(model.strip())
        and "script" not in model.lower()
        and "offline" not in model.lower()
    )


def comparison_data(connection: sqlite3.Connection, run_id: str | None = None) -> dict:
    """Return only the reviewed fields needed by the table and JSON view."""
    if run_id is None:
        latest = connection.execute(
            "SELECT run_id FROM synthetic_runs WHERE mode='live' ORDER BY created_at DESC, rowid DESC LIMIT 1"
        ).fetchone()
        if latest is None:
            raise NoLiveRun("No live retrieval run has been saved yet. Scripted results are kept separate.")
        run_id = latest[0]
    try:
        run = get_run(connection, run_id)
    except ValueError as exc:
        if str(exc) == "The saved run does not exist.":
            raise RunNotFound("The requested retrieval run does not exist.") from exc
        raise
    source = connection.execute(
        "SELECT s.source_url,s.publication_date,s.publication_date_note,g.title,g.publisher "
        "FROM snapshots s JOIN guidelines g ON g.slug=s.guideline_slug WHERE s.snapshot_id=?",
        (run["snapshot_id"],),
    ).fetchone()
    if source is None:
        raise ValueError("The run has no saved source record.")
    source = dict(source)
    links = {row[0]: _public_url(row[1]) for row in connection.execute(
        "SELECT section_id,source_url FROM sections WHERE snapshot_id=?", (run["snapshot_id"],)
    )}
    pairs = {}
    for result in run["results"]:
        key = (result["question_id"], result["method"])
        if key in pairs:
            raise ValueError("The run contains a repeated method result.")
        pairs[key] = result["selection"]
    rows = []
    live_responses = 0
    for question in run["questions"]:
        if question.get("origin") != "synthetic":
            raise ValueError("The comparison view accepts synthetic questions only.")
        row = {"question_id": question["id"], "question": question["text"], "mode": run["mode"]}
        for method, label in [("baseline_tfidf", "baseline"), ("toc_claude", "toc")]:
            selection = pairs.pop((question["id"], method), None)
            if selection is None:
                raise ValueError("A question is missing one of its paired method outcomes.")
            if selection.get("method") != method:
                raise ValueError("A saved result identifies a different retrieval method.")
            if selection.get("status") not in {"selected", "no_match", "invalid", "blocked", "error"}:
                raise ValueError("A saved result has an unknown outcome status.")
            details = selection.get("details", {})
            if method == "toc_claude":
                modes = {"live", "live_claude"} if run["mode"] == "live" else {"offline_scripted"}
                if details.get("mode") not in modes:
                    raise ValueError("The saved ToC outcome's mode does not match its run.")
            actual_live = method == "toc_claude" and _has_live_response(selection, run["mode"])
            live_responses += int(actual_live)
            row[label] = {
                "section_id": selection.get("section_id"),
                "section_title": selection.get("section_title"),
                "status": selection["status"],
                "reason": selection.get("reason"),
                "source_url": links.get(selection.get("section_id")),
                "mode": run["mode"],
                "live_response": actual_live,
                "response_model": details.get("response_model") if actual_live else None,
            }
        rows.append(row)
    if pairs:
        raise ValueError("The saved run contains results for other questions.")
    if not rows:
        raise ValueError("The saved run contains no synthetic questions.")
    statuses = {label: {status: sum(row[label]["status"] == status for row in rows)
                       for status in ["selected", "no_match", "invalid", "blocked", "error"]}
                for label in ["baseline", "toc"]}
    return {
        "run_id": run["run_id"], "mode": run["mode"], "status": run["status"],
        "created_at": run["created_at"], "snapshot_id": run["snapshot_id"],
        "model": run["settings"].get("toc_model", "not recorded"),
        "source_title": source["title"], "publisher": source["publisher"],
        "source_url": _public_url(source["source_url"]),
        "publication_date": source["publication_date_note"] or source["publication_date"] or "unknown",
        "question_count": len(rows), "live_responses": live_responses,
        "status_counts": statuses, "rows": rows,
        "answer_generation": False,
    }


_CSS = """
:root{font-family:system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#15302f;background:#f4f7f5;font-size:16px}
*{box-sizing:border-box}body{margin:0}main{max-width:1220px;margin:0 auto;padding:48px 24px 36px}h1{font-size:clamp(1.8rem,4vw,2.6rem);line-height:1.15;margin:0 0 12px;font-weight:700;letter-spacing:-.045em}
p{line-height:1.6}.intro{max-width:740px;color:#526663;margin:0 0 24px}.meta{font-size:.9rem;color:#5a6a67}.bar{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin-bottom:20px}.pill{display:inline-block;border-radius:6px;padding:5px 10px;font-size:.78rem;font-weight:700;line-height:1.2;background:#e0ebe6;color:#204c40;white-space:nowrap}.live{background:#d5eee5;color:#14543f}.scripted{background:#f4e3c1;color:#6c4a12}.blocked,.error,.invalid{background:#f8e6dc;color:#7f3d22}.no_match{background:#e8eceb;color:#4d5f5a}.selected{background:#e0eee7;color:#24573f}
.notice{padding:16px 18px;background:#fff3e8;border:1px solid #ead6c4;border-radius:9px;margin:16px 0 24px;line-height:1.55}.notice.good{background:#eaf5ee;border-color:#cde1d4}.summary{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin:0 0 24px}.stat{background:#fff;padding:19px 20px;border:1px solid #dae3dd;border-radius:10px}.stat strong{display:block;font-size:1.65rem;letter-spacing:-.035em;margin-top:8px}.stat span{font-size:.86rem;color:#5e6f67}
.table-wrap{overflow-x:auto;background:white;border:1px solid #d5e1d9;border-radius:12px}table{border-collapse:collapse;width:100%;min-width:760px;text-align:left}caption{text-align:left;padding:20px 22px;font-weight:700;border-bottom:1px solid #e3e9e4}th{background:#edf3ef;font-size:.83rem;font-weight:650;color:#455e52;padding:15px 20px}td{padding:22px 20px;vertical-align:top;border-top:1px solid #e7ede8;line-height:1.5}th:first-child{width:44%}td small{display:block;font-size:.78rem;color:#677b71;margin:0 0 9px}td .pill{margin-bottom:9px}.section-title{display:block;font-weight:600;margin-bottom:9px}.reason{display:block;font-size:.84rem;color:#6a685f;margin-top:8px}a{color:#21674d;text-decoration:underline;text-decoration-color:#a4c7b8;text-underline-offset:3px}a:hover{color:#104330}.source{margin:24px 0 0;font-size:.88rem;color:#5f6f66}.source p{margin:8px 0}details{margin-top:20px;padding:14px 0;border-top:1px solid #dce4de;font-size:.83rem;color:#617168}summary{cursor:pointer;font-weight:600}code{font-size:.78rem;overflow-wrap:anywhere}.empty{background:#fff;border:1px solid #d6e1da;border-radius:12px;padding:30px;margin-top:20px}footer{font-size:.83rem;color:#6b796f;margin-top:26px;line-height:1.6}@media(max-width:680px){main{padding:28px 16px}.summary{grid-template-columns:1fr}.stat{display:flex;align-items:center;justify-content:space-between;gap:12px}.stat strong{margin:0;font-size:1.3rem}.bar{gap:8px}td,th{padding:16px}}
"""


def _h(value) -> str:
    return escape(str(value), quote=True)


def _time(value: str) -> str:
    try:
        date = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return date.astimezone(ZoneInfo("America/Chicago")).strftime("%b %d, %Y at %I:%M %p %Z")
    except (ValueError, TypeError):
        return value


def _shell(contents: str) -> str:
    return '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Section retrieval comparison</title><style>' + _CSS + '</style></head><body><main>' + contents + '</main></body></html>'


def _empty(message: str) -> str:
    return _shell('<h1>Section retrieval comparison</h1><div class="empty">' + _h(message) + '</div><footer>No answer generator is included.</footer>')


def _cell(selection: dict, method: str, mode: str) -> str:
    labels = {"selected": "Section selected", "no_match": "No matching section", "invalid": "Invalid selection",
              "blocked": "Blocked", "error": "Request failed"}
    status = selection["status"]
    title = selection.get("section_title")
    result = '<span class="pill ' + _h(status) + '">' + _h(labels[status]) + '</span>'
    if title and status == "selected":
        if selection.get("source_url"):
            result += '<a class="section-title" href="' + _h(selection["source_url"]) + '" target="_blank" rel="noopener noreferrer">' + _h(title) + '</a>'
        else:
            result += '<span class="section-title">' + _h(title) + '</span>'
    elif status == "no_match":
        result += '<span class="section-title">No section returned</span>'
    else:
        result += '<span class="section-title">No verified section returned</span>'
    if method == "toc":
        if mode != "live":
            note = "Scripted test reply · not a Claude prediction"
        elif selection["live_response"]:
            note = "Live API response"
        elif status in {"blocked", "error"}:
            note = "Live attempt · no completed response"
        else:
            note = "Live run · response evidence incomplete"
        result += '<small>' + _h(note) + '</small>'
    else:
        result += '<small>Local fixed-chunk vector search</small>'
    if selection.get("reason"):
        result += '<span class="reason">' + _h(selection["reason"]) + '</span>'
    return result


def render_comparison(connection: sqlite3.Connection, run_id: str | None = None) -> str:
    """Render the same saved rows for the local app and a standalone HTML file."""
    data = comparison_data(connection, run_id)
    live = data["mode"] == "live"
    mode_label = "live" if live else "offline · scripted"
    if not live:
        notice = '<div class="notice"><strong>Offline test run.</strong> ToC replies are predefined test responses, not Claude predictions. This page cannot establish a retrieval advantage.</div>'
    elif data["live_responses"] < data["question_count"] or data["status"] != "complete":
        notice = '<div class="notice"><strong>Live run incomplete.</strong> Missing or failed Claude responses remain visible. They are not replaced with scripted replies or counted as successful predictions.</div>'
    else:
        notice = '<div class="notice good"><strong>Live responses recorded.</strong> Both methods received the same synthetic questions. This small development set is not a clinical test or a broad accuracy benchmark.</div>'
    rows = []
    for row in data["rows"]:
        badge = '<span class="pill ' + ("live" if live else "scripted") + '">' + _h(mode_label) + '</span>'
        rows.append('<tr><td><small>' + _h(row["question_id"]) + '</small>' + badge + '<div>' + _h(row["question"]) + '</div></td><td>' + _cell(row["baseline"], "baseline", data["mode"]) + '</td><td>' + _cell(row["toc"], "toc", data["mode"]) + '</td></tr>')
    source_title = _h(data["source_title"])
    if data["source_url"]:
        source_title = '<a href="' + _h(data["source_url"]) + '" target="_blank" rel="noopener noreferrer">' + source_title + '</a>'
    return _shell(
        '<h1>Section retrieval comparison</h1><p class="intro">See which textbook section each method returns for the same synthetic question. The baseline searches fixed text chunks; Claude chooses from the full table of contents.</p>'
        '<div class="bar"><span class="pill ' + ("live" if live else "scripted") + '">' + _h(mode_label) + '</span><span class="meta">' + _h(data["model"]) + ' · ' + _h(_time(data["created_at"])) + '</span></div>'
        + notice
        + '<div class="summary"><div class="stat"><span>Synthetic questions</span><strong>' + str(data["question_count"]) + '</strong></div><div class="stat"><span>Completed live Claude responses</span><strong>' + str(data["live_responses"]) + ' / ' + str(data["question_count"]) + '</strong></div><div class="stat"><span>Run status</span><strong>' + _h(data["status"].capitalize()) + '</strong></div></div>'
        + '<div class="table-wrap"><table><caption>Same questions, side-by-side section choices</caption><thead><tr><th scope="col">Synthetic question</th><th scope="col">Baseline · word vectors</th><th scope="col">ToC · Claude</th></tr></thead><tbody>' + ''.join(rows) + '</tbody></table></div>'
        + '<div class="source"><p><strong>Public source:</strong> ' + source_title + ' · ' + _h(data["publisher"]) + '</p><p><strong>Publication date:</strong> ' + _h(data["publication_date"]) + '</p><p>Educational textbook text only. Source selection is not medical advice. No patient data or treatment answers.</p></div>'
        + '<details><summary>Run details</summary><p>Saved run: <code>' + _h(data["run_id"]) + '</code></p><p>Source snapshot: <code>' + _h(data["snapshot_id"]) + '</code></p><p>The baseline uses TF-IDF word vectors and cosine search. Claude sees the complete stored contents list, not section bodies or the test answer key. These results cover a small synthetic development set.</p></details>'
        + '<footer>Read-only saved results. Opening this page makes no model request. No answer generator is included.</footer>'
    )


@contextmanager
def _read_connection(path: str | Path):
    database = Path(path).resolve()
    if not database.is_file():
        raise FileNotFoundError("The source database is not available.")
    connection = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    try:
        yield connection
    finally:
        connection.close()


def create_app(db_path: str | Path = "data/guidelines.sqlite3") -> FastAPI:
    app = FastAPI(title="Section retrieval comparison", docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/", response_class=HTMLResponse)
    def comparison(run_id: str | None = None):
        try:
            with _read_connection(db_path) as connection:
                return HTMLResponse(render_comparison(connection, run_id))
        except NoLiveRun as exc:
            return HTMLResponse(_empty(str(exc)))
        except RunNotFound as exc:
            return HTMLResponse(_empty(str(exc)), status_code=404)
        except (OSError, sqlite3.Error, ValueError):
            return HTMLResponse(_empty("Saved comparison data is unavailable or incomplete. Prepare the source and run the paired retrieval test first."), status_code=503)

    @app.get("/api/comparison")
    def comparison_json(run_id: str | None = None):
        try:
            with _read_connection(db_path) as connection:
                return comparison_data(connection, run_id)
        except (NoLiveRun, RunNotFound) as exc:
            return JSONResponse({"detail": str(exc)}, status_code=404)
        except (OSError, sqlite3.Error, ValueError):
            return JSONResponse({"detail": "Saved comparison data is unavailable or incomplete."}, status_code=503)

    @app.get("/health")
    def health():
        try:
            with _read_connection(db_path) as connection:
                sources = connection.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
                live_runs = connection.execute("SELECT COUNT(*) FROM synthetic_runs WHERE mode='live'").fetchone()[0]
                if not sources:
                    raise ValueError("No source snapshot")
            return {"status": "ready", "stored_sources": sources, "live_runs": live_runs}
        except (OSError, sqlite3.Error, ValueError):
            return JSONResponse({"status": "not ready", "detail": "Prepare the source database and retrieval records first."}, status_code=503)

    return app


app = create_app()
