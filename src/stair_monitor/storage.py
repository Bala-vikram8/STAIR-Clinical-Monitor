"""Keep public sources and their saved section maps in SQLite."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from typing import Iterator, Sequence
from urllib.parse import urlsplit


@dataclass(frozen=True)
class SectionRecord:
    """A section's own text, without text owned by its child sections."""

    section_id: str
    title: str
    heading_path: tuple[str, ...]
    parent_id: str | None
    source_url: str
    text: str
    start_offset: int
    end_offset: int
    position: int


@dataclass(frozen=True)
class TocEntry:
    """An original contents entry and the section it points to."""

    title: str
    source_url: str
    level: int
    position: int
    section_id: str
    parent_position: int | None = None


_SCHEMA = """
CREATE TABLE IF NOT EXISTS guidelines (
    slug TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    publisher TEXT NOT NULL,
    source_url TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS snapshots (
    snapshot_id TEXT PRIMARY KEY,
    guideline_slug TEXT NOT NULL REFERENCES guidelines(slug),
    raw_sha256 TEXT NOT NULL,
    raw_content BLOB NOT NULL,
    fetched_at TEXT NOT NULL,
    source_url TEXT NOT NULL,
    archive_path TEXT NOT NULL,
    text TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    edition TEXT,
    publication_date TEXT,
    publication_date_note TEXT NOT NULL DEFAULT '',
    updated_date TEXT,
    date_evidence TEXT NOT NULL,
    reuse_terms TEXT NOT NULL,
    reuse_terms_source_url TEXT,
    verified_at TEXT,
    content_signature TEXT NOT NULL,
    UNIQUE(guideline_slug, raw_sha256, parser_version)
);
CREATE TABLE IF NOT EXISTS sections (
    snapshot_id TEXT NOT NULL REFERENCES snapshots(snapshot_id),
    section_id TEXT NOT NULL,
    title TEXT NOT NULL,
    heading_path TEXT NOT NULL,
    parent_id TEXT,
    source_url TEXT NOT NULL,
    text TEXT NOT NULL,
    start_offset INTEGER NOT NULL CHECK (start_offset >= 0),
    end_offset INTEGER NOT NULL CHECK (end_offset >= start_offset),
    position INTEGER NOT NULL CHECK (position >= 0),
    PRIMARY KEY(snapshot_id, section_id),
    UNIQUE(snapshot_id, position),
    FOREIGN KEY(snapshot_id, parent_id)
        REFERENCES sections(snapshot_id, section_id)
        DEFERRABLE INITIALLY DEFERRED
);
CREATE TABLE IF NOT EXISTS toc_entries (
    snapshot_id TEXT NOT NULL,
    position INTEGER NOT NULL CHECK (position >= 0),
    title TEXT NOT NULL,
    source_url TEXT NOT NULL,
    level INTEGER NOT NULL CHECK (level >= 1),
    section_id TEXT NOT NULL,
    parent_position INTEGER,
    PRIMARY KEY(snapshot_id, position),
    UNIQUE(snapshot_id, section_id),
    FOREIGN KEY(snapshot_id, section_id)
        REFERENCES sections(snapshot_id, section_id),
    FOREIGN KEY(snapshot_id, parent_position)
        REFERENCES toc_entries(snapshot_id, position)
        DEFERRABLE INITIALLY DEFERRED
);
"""


def connect(path: str | Path) -> sqlite3.Connection:
    """Open the database with reference checks enabled on every connection."""
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Create storage tables; refuse to guess how to upgrade a newer database."""
    if conn.in_transaction:
        raise ValueError("Initialize storage before starting a transaction.")
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version not in (0, 1, 2):
        raise ValueError("This database needs a schema version this code does not support.")
    columns = {row[1] for row in conn.execute("PRAGMA table_info(snapshots)")}
    if version == 2 and "publication_date_note" not in columns:
        raise ValueError("The database is missing its publication date note column.")
    migration = ""
    if columns and "publication_date_note" not in columns:
        migration = "ALTER TABLE snapshots ADD COLUMN publication_date_note TEXT NOT NULL DEFAULT '';"
    try:
        conn.executescript(
            "BEGIN IMMEDIATE;\n" + _SCHEMA + migration + "\nPRAGMA user_version = 2;\nCOMMIT;"
        )
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise


@contextmanager
def _write(conn: sqlite3.Connection) -> Iterator[None]:
    # A savepoint also works when a caller already has a transaction open.
    conn.execute("SAVEPOINT storage_write")
    try:
        yield
        conn.execute("RELEASE SAVEPOINT storage_write")
    except BaseException:
        conn.execute("ROLLBACK TO SAVEPOINT storage_write")
        conn.execute("RELEASE SAVEPOINT storage_write")
        raise


def _required(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a nonempty string.")


def _url(value: str) -> None:
    parts = urlsplit(value)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        raise ValueError("Source links must be HTTPS links without embedded credentials.")


def _utc(value: str, name: str) -> None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError(f"{name} must be a full UTC timestamp.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError(f"{name} must include the UTC timezone.")


def _date(value: str | None, name: str) -> None:
    if value is not None:
        try:
            parsed = date.fromisoformat(value)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"{name} must be an ISO date or None when unknown.") from exc
        if parsed.isoformat() != value:
            raise ValueError(f"{name} must use YYYY-MM-DD.")


def register_guideline(
    conn: sqlite3.Connection,
    *,
    slug: str,
    title: str,
    publisher: str,
    source_url: str,
) -> None:
    """Register a proposed source without claiming it has been verified."""
    for name, value in {"slug": slug, "title": title, "publisher": publisher}.items():
        _required(value, name)
    _url(source_url)
    values = (slug, title, publisher, source_url)
    with _write(conn):
        current = conn.execute("SELECT * FROM guidelines WHERE slug = ?", (slug,)).fetchone()
        if current is not None:
            if tuple(current) != values:
                raise ValueError("This source ID is already registered with different details.")
            return
        conn.execute("INSERT INTO guidelines VALUES (?, ?, ?, ?)", values)


def _validate_map(text: str, sections: Sequence[SectionRecord], toc: Sequence[TocEntry]) -> None:
    if not sections or not toc:
        raise ValueError("A saved document needs sections and a checked table of contents.")
    section_map = {s.section_id: s for s in sections}
    if len(section_map) != len(sections):
        raise ValueError("Section IDs must be unique within a saved document.")
    ordered = sorted(sections, key=lambda s: s.position)
    if [s.position for s in ordered] != list(range(len(ordered))):
        raise ValueError("Section positions must be consecutive, starting at zero.")
    previous_end = 0
    for section in ordered:
        _required(section.section_id, "Section ID")
        _required(section.title, "Section title")
        _url(section.source_url)
        if not section.heading_path or section.heading_path[-1] != section.title:
            raise ValueError("Every section path must end with its original title.")
        if not 0 <= section.start_offset <= section.end_offset <= len(text):
            raise ValueError("A section points outside the saved document text.")
        if section.start_offset < previous_end:
            raise ValueError("Section text must not overlap text owned by another section.")
        if text[section.start_offset : section.end_offset] != section.text:
            raise ValueError("Section text does not match its recorded source positions.")
        previous_end = section.end_offset
        if section.parent_id is None:
            if len(section.heading_path) != 1:
                raise ValueError("A root section must have a single-title path.")
        else:
            parent = section_map.get(section.parent_id)
            if parent is None or parent.position >= section.position:
                raise ValueError("A section parent must exist earlier in the document.")
            if tuple(section.heading_path[:-1]) != tuple(parent.heading_path):
                raise ValueError("The section path does not match its parent path.")
    toc_map = {entry.position: entry for entry in toc}
    if sorted(toc_map) != list(range(len(toc))) or len(toc_map) != len(toc):
        raise ValueError("Contents positions must be consecutive, starting at zero.")
    if len({entry.section_id for entry in toc}) != len(toc):
        raise ValueError("Contents links must point to distinct sections.")
    for entry in sorted(toc, key=lambda e: e.position):
        _required(entry.title, "Contents title")
        _url(entry.source_url)
        if entry.section_id not in section_map:
            raise ValueError("A contents link points to a missing section.")
        # A published contents label can be shorter than the linked heading.
        # Preserve both original titles rather than requiring identical wording.
        if entry.parent_position is None:
            if entry.level != 1:
                raise ValueError("A root contents entry must have level one.")
        else:
            parent = toc_map.get(entry.parent_position)
            if parent is None or parent.position >= entry.position or entry.level != parent.level + 1:
                raise ValueError("A contents parent must be an earlier entry at the preceding level.")
            ancestor_id = section_map[entry.section_id].parent_id
            while ancestor_id is not None and ancestor_id != parent.section_id:
                ancestor_id = section_map[ancestor_id].parent_id
            if ancestor_id is None:
                raise ValueError("A contents parent must point to an ancestor of its linked section.")


def save_snapshot(
    conn: sqlite3.Connection,
    *,
    guideline_slug: str,
    raw_content: bytes,
    fetched_at: str,
    source_url: str,
    archive_path: str,
    text: str,
    parser_version: str,
    sections: Sequence[SectionRecord],
    toc: Sequence[TocEntry],
    edition: str | None = None,
    publication_date: str | None = None,
    publication_date_note: str = "",
    updated_date: str | None = None,
    date_evidence: str = "",
    reuse_terms: str = "",
    reuse_terms_source_url: str | None = None,
    verified_at: str | None = None,
) -> str:
    """Save a complete document at once; never overwrite an earlier copy."""
    if not isinstance(raw_content, bytes) or not raw_content:
        raise ValueError("Original source bytes are required.")
    _required(guideline_slug, "Guideline ID")
    _required(parser_version, "Parser version")
    _required(archive_path, "Archive path")
    _required(text, "Document text")
    _url(source_url)
    _utc(fetched_at, "Download time")
    _date(publication_date, "Publication date")
    if not isinstance(publication_date_note, str):
        raise ValueError("Publication date note must be text; use an empty string when absent.")
    _date(updated_date, "Update date")
    if reuse_terms_source_url is not None:
        _url(reuse_terms_source_url)
    if verified_at is not None:
        _utc(verified_at, "Verification time")
        _required(date_evidence, "Evidence for stated dates or their absence")
        _required(reuse_terms, "Reuse terms")
        if reuse_terms_source_url is None:
            raise ValueError("A verified source needs a link to its reuse terms.")
    _validate_map(text, sections, toc)
    raw_hash = sha256(raw_content).hexdigest()
    snapshot_id = sha256(
        json.dumps([guideline_slug, raw_hash, parser_version], separators=(",", ":")).encode()
    ).hexdigest()
    signature_fields = {
        "text": text,
        "source_url": source_url,
        "edition": edition,
        "publication_date": publication_date,
        "updated_date": updated_date,
        "date_evidence": date_evidence,
        "reuse_terms": reuse_terms,
        "reuse_terms_source_url": reuse_terms_source_url,
        "verified_at": verified_at,
        "sections": [asdict(s) for s in sorted(sections, key=lambda s: s.position)],
        "toc": [asdict(e) for e in sorted(toc, key=lambda e: e.position)],
    }
    # Empty notes did not exist in the old format. Keep its signatures valid.
    if publication_date_note:
        signature_fields["publication_date_note"] = publication_date_note
    content_signature = sha256(
        json.dumps(
            signature_fields,
            sort_keys=True,
            ensure_ascii=False,
        ).encode()
    ).hexdigest()
    with _write(conn):
        current = conn.execute(
            "SELECT content_signature FROM snapshots WHERE snapshot_id = ?", (snapshot_id,)
        ).fetchone()
        if current is not None:
            if current[0] != content_signature:
                raise ValueError("This file was already imported differently; use a new parser version.")
            return snapshot_id
        conn.execute(
            """INSERT INTO snapshots (
                snapshot_id, guideline_slug, raw_sha256, raw_content, fetched_at,
                source_url, archive_path, text, parser_version, edition,
                publication_date, publication_date_note, updated_date, date_evidence, reuse_terms,
                reuse_terms_source_url, verified_at, content_signature
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                snapshot_id, guideline_slug, raw_hash, raw_content, fetched_at,
                source_url, archive_path, text, parser_version, edition,
                publication_date, publication_date_note, updated_date, date_evidence, reuse_terms,
                reuse_terms_source_url, verified_at, content_signature,
            ),
        )
        conn.executemany(
            "INSERT INTO sections VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    snapshot_id, section.section_id, section.title,
                    json.dumps(section.heading_path, ensure_ascii=False),
                    section.parent_id, section.source_url, section.text,
                    section.start_offset, section.end_offset, section.position,
                )
                for section in sorted(sections, key=lambda s: s.position)
            ],
        )
        conn.executemany(
            "INSERT INTO toc_entries VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (snapshot_id, e.position, e.title, e.source_url, e.level, e.section_id, e.parent_position)
                for e in sorted(toc, key=lambda e: e.position)
            ],
        )
    return snapshot_id


def list_guidelines(conn: sqlite3.Connection) -> list[dict]:
    """A downloaded document is not verified unless explicitly reviewed."""
    rows = conn.execute(
        """SELECT g.*,
            (SELECT COUNT(*) FROM snapshots s WHERE s.guideline_slug = g.slug) AS snapshot_count,
            CASE WHEN EXISTS (
                SELECT 1 FROM snapshots s
                WHERE s.guideline_slug = g.slug AND s.verified_at IS NOT NULL
            ) THEN 'verified' ELSE 'unverified' END AS verification_status
        FROM guidelines g ORDER BY g.slug"""
    ).fetchall()
    return [dict(row) for row in rows]


def list_snapshots(conn: sqlite3.Connection, guideline_slug: str | None = None) -> list[dict]:
    """List source dates and hashes without dumping original document content."""
    query = """SELECT snapshot_id, guideline_slug, raw_sha256, fetched_at, source_url,
        archive_path, parser_version, edition, publication_date, publication_date_note, updated_date,
        date_evidence, reuse_terms, reuse_terms_source_url, verified_at,
        CASE WHEN verified_at IS NULL THEN 'unverified' ELSE 'verified' END AS verification_status
        FROM snapshots"""
    params: tuple = ()
    if guideline_slug is not None:
        query += " WHERE guideline_slug = ?"
        params = (guideline_slug,)
    query += " ORDER BY fetched_at, snapshot_id"
    return [dict(row) for row in conn.execute(query, params).fetchall()]


def get_toc(conn: sqlite3.Connection, snapshot_id: str) -> list[dict]:
    """Return the saved hierarchy in its original contents order."""
    return [
        dict(row)
        for row in conn.execute(
            "SELECT * FROM toc_entries WHERE snapshot_id = ? ORDER BY position", (snapshot_id,)
        ).fetchall()
    ]


def get_sections(conn: sqlite3.Connection, snapshot_id: str) -> list[dict]:
    """Return section text and its exact location in the normalized document."""
    result = []
    for row in conn.execute(
        "SELECT * FROM sections WHERE snapshot_id = ? ORDER BY position", (snapshot_id,)
    ).fetchall():
        section = dict(row)
        section["heading_path"] = json.loads(section["heading_path"])
        result.append(section)
    return result
