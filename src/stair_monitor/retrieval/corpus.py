"""Require a complete stored source before either method can run."""

from hashlib import sha256
import io
import sqlite3
import zipfile

from stair_monitor.openstax import read_contents
from stair_monitor.openstax_downloads import COLLECTION_PATH
from stair_monitor.retrieval.types import Corpus, Section, TocItem
from stair_monitor.sources import OPENSTAX_SOURCE
from stair_monitor.storage import get_sections, get_toc


def load_corpus(connection: sqlite3.Connection, snapshot_id: str | None = None) -> Corpus:
    if snapshot_id is None:
        rows = connection.execute(
            "SELECT snapshot_id FROM snapshots WHERE guideline_slug=? AND verified_at IS NOT NULL "
            "ORDER BY fetched_at DESC, snapshot_id", (OPENSTAX_SOURCE.slug,),
        ).fetchall()
        if not rows:
            raise ValueError("Import the complete OpenStax source before running retrieval.")
        snapshot_id = rows[0]["snapshot_id"]
    saved = connection.execute(
        "SELECT s.*, g.title AS source_title FROM snapshots s JOIN guidelines g "
        "ON g.slug=s.guideline_slug WHERE snapshot_id=?", (snapshot_id,),
    ).fetchone()
    if saved is None or saved["guideline_slug"] != OPENSTAX_SOURCE.slug or not saved["verified_at"]:
        raise ValueError("Choose a checked OpenStax source snapshot.")
    sections = get_sections(connection, snapshot_id)
    toc = get_toc(connection, snapshot_id)
    if sha256(saved["raw_content"]).hexdigest() != saved["raw_sha256"]:
        raise ValueError("The saved source bytes disagree with their hash.")
    try:
        with zipfile.ZipFile(io.BytesIO(saved["raw_content"])) as archive:
            expected = {node.section_id for node in read_contents(archive.read(COLLECTION_PATH))}
    except (zipfile.BadZipFile, KeyError, ValueError) as exc:
        raise ValueError("The saved source has no readable original contents file.") from exc
    if not sections or len(sections) != len(toc):
        raise ValueError("The complete source section map is required for retrieval.")
    by_id = {section["section_id"]: section for section in sections}
    if len(by_id) != len(sections) or set(by_id) != expected or {entry["section_id"] for entry in toc} != set(by_id):
        raise ValueError("The stored contents and section IDs do not match.")
    result = []
    for section in sections:
        start, end = section["start_offset"], section["end_offset"]
        if not section["title"].strip() or saved["text"][start:end] != section["text"]:
            raise ValueError("A source title or text position failed its check.")
        navigation = section["section_id"].startswith("group-")
        if not navigation and not section["text"].strip():
            raise ValueError("A text-bearing source section has no content.")
        result.append(Section(
            section["section_id"], section["title"], tuple(section["heading_path"]),
            section["source_url"], section["text"], start, end, section["position"], navigation,
        ))
    toc_items = []
    for entry in toc:
        section = by_id[entry["section_id"]]
        if entry["title"] != section["title"]:
            raise ValueError("A stored contents title does not match its source section.")
        toc_items.append(TocItem(
            entry["section_id"], entry["title"], tuple(section["heading_path"]),
            entry["source_url"], entry["position"], entry["parent_position"], entry["level"],
            entry["section_id"].startswith("group-"),
        ))
    return Corpus(
        snapshot_id, tuple(result), tuple(toc_items), saved["source_title"], saved["source_url"],
        saved["raw_sha256"],
    )
