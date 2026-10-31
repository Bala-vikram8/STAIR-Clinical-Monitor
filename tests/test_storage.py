"""Storage checks use invented text, never medical records or live API calls."""

from dataclasses import replace
from hashlib import sha256
import sqlite3

import pytest

from stair_monitor.storage import (
    SectionRecord,
    TocEntry,
    connect,
    get_sections,
    get_toc,
    init_db,
    list_guidelines,
    list_snapshots,
    register_guideline,
    save_snapshot,
)


SOURCE = "https://www.cdc.gov/example-guideline"


@pytest.fixture
def db():
    conn = connect(":memory:")
    init_db(conn)
    register_guideline(conn, slug="example", title="Invented example", publisher="Test", source_url=SOURCE)
    yield conn
    conn.close()


def document(**changes):
    text = "Intro\nFirst\nSecond"
    sections = [
        SectionRecord("intro", "Overview", ("Overview",), None, SOURCE + "#intro", "Intro", 0, 5, 0),
        SectionRecord("first", "Details", ("Overview", "Details"), "intro", SOURCE + "#first", "First", 6, 11, 1),
        SectionRecord("second", "Details", ("Details",), None, SOURCE + "#second", "Second", 12, 18, 2),
    ]
    toc = [
        TocEntry("Overview", SOURCE + "#intro", 1, 0, "intro"),
        TocEntry("Details", SOURCE + "#first", 2, 1, "first", 0),
        TocEntry("Details", SOURCE + "#second", 1, 2, "second"),
    ]
    values = dict(
        guideline_slug="example", raw_content=b"<html>invented test source</html>",
        fetched_at="2026-10-30T12:00:00Z", source_url=SOURCE,
        archive_path="ignored/example.html", text=text, parser_version="test-v1",
        sections=sections, toc=toc,
    )
    values.update(changes)
    return values


def test_candidate_registration_does_not_invent_dates_or_verification(db):
    register_guideline(db, slug="example", title="Invented example", publisher="Test", source_url=SOURCE)
    assert list_guidelines(db) == [{
        "slug": "example", "title": "Invented example", "publisher": "Test",
        "source_url": SOURCE, "snapshot_count": 0, "verification_status": "unverified",
    }]
    assert list_snapshots(db) == []


def test_import_is_repeatable_and_preserves_original_bytes_and_unknown_dates(db):
    first = save_snapshot(db, **document())
    second = save_snapshot(db, **document(fetched_at="2026-10-31T12:00:00Z"))
    assert first == second
    snapshot = list_snapshots(db)[0]
    assert len(list_snapshots(db)) == 1
    assert snapshot["publication_date"] is None
    assert snapshot["updated_date"] is None
    assert snapshot["verification_status"] == "unverified"
    assert snapshot["fetched_at"] == "2026-10-30T12:00:00Z"
    assert snapshot["raw_sha256"] == sha256(document()["raw_content"]).hexdigest()
    assert db.execute("SELECT raw_content FROM snapshots").fetchone()[0] == document()["raw_content"]


def test_repeated_titles_keep_distinct_paths_and_hierarchy(db):
    snapshot = save_snapshot(db, **document())
    sections = get_sections(db, snapshot)
    assert sections[1]["title"] == sections[2]["title"]
    assert sections[1]["heading_path"] == ["Overview", "Details"]
    assert sections[2]["heading_path"] == ["Details"]
    assert get_toc(db, snapshot)[1]["parent_position"] == 0
    assert sections[1]["text"] == document()["text"][6:11]


def test_updated_file_and_parser_version_keep_earlier_copies(db):
    old = save_snapshot(db, **document())
    original_sections = get_sections(db, old)
    updated = save_snapshot(db, **document(raw_content=b"changed source bytes"))
    reinterpreted = save_snapshot(db, **document(parser_version="test-v2"))
    assert len({old, updated, reinterpreted}) == 3
    assert len(list_snapshots(db)) == 3
    assert get_sections(db, old) == original_sections
    assert db.execute(
        "SELECT raw_content FROM snapshots WHERE snapshot_id = ?", (old,)
    ).fetchone()[0] == document()["raw_content"]


def test_same_file_in_different_guidelines_keeps_both(db):
    register_guideline(db, slug="other", title="Other", publisher="Test", source_url=SOURCE + "/other")
    first = save_snapshot(db, **document())
    second = save_snapshot(db, **document(guideline_slug="other"))
    assert first != second
    assert len(list_snapshots(db, "other")) == 1


def test_changed_interpretation_requires_new_parser_version(db):
    save_snapshot(db, **document())
    with pytest.raises(ValueError, match="already imported differently"):
        save_snapshot(db, **document(publication_date="2021-07-23"))
    assert list_snapshots(db)[0]["publication_date"] is None


def test_foreign_keys_prevent_orphans_and_failed_save_is_atomic(db):
    assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    with pytest.raises(sqlite3.IntegrityError):
        save_snapshot(db, **document(guideline_slug="missing"))
    assert list_snapshots(db) == []
    assert db.execute("SELECT COUNT(*) FROM sections").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM toc_entries").fetchone()[0] == 0


@pytest.mark.parametrize("change", [
    {"parent_id": "missing"},
    {"parent_id": "second"},
    {"heading_path": ("Wrong parent", "Details")},
    {"end_offset": 1000},
    {"start_offset": 0},
    {"text": "Not in the source"},
    {"position": 0},
])
def test_bad_section_map_does_not_save_partial_document(db, change):
    values = document()
    values["sections"][1] = replace(values["sections"][1], **change)
    with pytest.raises(ValueError):
        save_snapshot(db, **values)
    assert list_snapshots(db) == []


@pytest.mark.parametrize("change", [
    {"section_id": "missing"},
    {"parent_position": 2},
    {"level": 4},
    {"position": 5},
    {"section_id": "intro"},
])
def test_bad_contents_map_does_not_save_partial_document(db, change):
    values = document()
    values["toc"][1] = replace(values["toc"][1], **change)
    with pytest.raises(ValueError):
        save_snapshot(db, **values)
    assert list_snapshots(db) == []


def test_contents_parent_cannot_point_to_an_unrelated_section(db):
    values = document()
    values["toc"][2] = replace(values["toc"][2], parent_position=0, level=2)
    with pytest.raises(ValueError, match="ancestor"):
        save_snapshot(db, **values)
    assert list_snapshots(db) == []


def test_original_contents_label_may_abbreviate_the_section_heading(db):
    values = document()
    values["toc"][0] = replace(values["toc"][0], title="Intro")
    snapshot = save_snapshot(db, **values)
    assert get_toc(db, snapshot)[0]["title"] == "Intro"
    assert get_sections(db, snapshot)[0]["title"] == "Overview"


@pytest.mark.parametrize("field,value", [
    ("fetched_at", "2026-10-30"),
    ("fetched_at", "2026-10-30T12:00:00-05:00"),
    ("publication_date", "unknown"),
    ("updated_date", "2026-02-31"),
    ("source_url", "https://secret@example.com/private"),
])
def test_invalid_metadata_is_rejected(db, field, value):
    with pytest.raises(ValueError):
        save_snapshot(db, **document(**{field: value}))
    assert list_snapshots(db) == []


def test_verification_requires_explicit_evidence_and_reuse_source(db):
    with pytest.raises(ValueError, match="Evidence"):
        save_snapshot(db, **document(verified_at="2026-10-30T12:01:00Z"))
    snapshot_id = save_snapshot(db, **document(
        verified_at="2026-10-30T12:01:00Z",
        date_evidence="Invented fixture has no stated publication or update date.",
        reuse_terms="Invented test text only.",
        reuse_terms_source_url="https://www.cdc.gov/example-reuse-policy",
    ))
    assert list_snapshots(db)[0]["snapshot_id"] == snapshot_id
    assert list_snapshots(db)[0]["publication_date"] is None
    assert list_guidelines(db)[0]["verification_status"] == "verified"


def test_file_database_persists_and_init_is_repeatable(tmp_path):
    path = tmp_path / "local" / "guidelines.sqlite3"
    with connect(path) as conn:
        init_db(conn)
        register_guideline(conn, slug="example", title="Invented example", publisher="Test", source_url=SOURCE)
        snapshot = save_snapshot(conn, **document())
    with connect(path) as conn:
        init_db(conn)
        assert list_snapshots(conn)[0]["snapshot_id"] == snapshot
        assert len(get_sections(conn, snapshot)) == 3


def test_conflicting_source_registration_is_not_overwritten(db):
    with pytest.raises(ValueError, match="different details"):
        register_guideline(db, slug="example", title="Changed title", publisher="Test", source_url=SOURCE)
    assert list_guidelines(db)[0]["title"] == "Invented example"


def test_save_joins_caller_transaction_without_committing_it(db):
    db.execute("BEGIN")
    save_snapshot(db, **document())
    assert db.in_transaction
    db.execute("ROLLBACK")
    assert list_snapshots(db) == []


def test_failed_save_preserves_other_writes_in_the_caller_transaction(db):
    db.execute("BEGIN")
    register_guideline(
        db, slug="other", title="Other invented example", publisher="Test",
        source_url=SOURCE + "/other",
    )
    with pytest.raises(sqlite3.IntegrityError):
        save_snapshot(db, **document(guideline_slug="missing"))
    assert db.in_transaction
    assert {row["slug"] for row in list_guidelines(db)} == {"example", "other"}
    assert list_snapshots(db) == []
    db.execute("COMMIT")
    assert {row["slug"] for row in list_guidelines(db)} == {"example", "other"}


def test_unknown_publication_date_has_a_separate_preserved_note(db):
    note = "unknown – publisher content"
    snapshot = save_snapshot(db, **document(publication_date_note=note))
    saved = list_snapshots(db)[0]
    assert saved["snapshot_id"] == snapshot
    assert saved["publication_date"] is None
    assert saved["publication_date_note"] == note
    assert save_snapshot(db, **document(publication_date_note=note)) == snapshot
    with pytest.raises(ValueError, match="already imported differently"):
        save_snapshot(db, **document(publication_date_note="Different publication note"))
    assert list_snapshots(db)[0]["publication_date_note"] == note


@pytest.mark.parametrize("note", [None, 2026, ["unknown"]])
def test_publication_date_note_must_be_text(db, note):
    with pytest.raises(ValueError, match="Publication date note must be text"):
        save_snapshot(db, **document(publication_date_note=note))
    assert list_snapshots(db) == []


def test_version_one_migration_preserves_rows_and_old_import_signatures(tmp_path):
    path = tmp_path / "old-guidelines.sqlite3"
    with connect(path) as conn:
        init_db(conn)
        register_guideline(conn, slug="example", title="Invented example", publisher="Test", source_url=SOURCE)
        register_guideline(conn, slug="other", title="Other", publisher="Test", source_url=SOURCE + "/other")
        snapshot = save_snapshot(conn, **document())
        old_sections = get_sections(conn, snapshot)
        old_toc = get_toc(conn, snapshot)
        # This is the signature produced by the original version-one importer.
        old_signature = "6d0e3ecf31453df53db3649dbe212c03048f03d584601b2d2ae5bf949a37cf9d"
        assert conn.execute("SELECT content_signature FROM snapshots").fetchone()[0] == old_signature
        # Removing only the added column recreates the original storage schema.
        conn.execute("ALTER TABLE snapshots DROP COLUMN publication_date_note")
        conn.execute("PRAGMA user_version = 1")

    with connect(path) as conn:
        init_db(conn)
        init_db(conn)
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
        assert {row["slug"] for row in list_guidelines(conn)} == {"example", "other"}
        assert list_snapshots(conn)[0]["publication_date_note"] == ""
        assert list_snapshots(conn)[0]["publication_date"] is None
        assert get_sections(conn, snapshot) == old_sections
        assert get_toc(conn, snapshot) == old_toc
        assert conn.execute("SELECT content_signature FROM snapshots").fetchone()[0] == old_signature
        assert conn.execute("SELECT raw_content FROM snapshots").fetchone()[0] == document()["raw_content"]
        assert save_snapshot(conn, **document()) == snapshot
        assert len(list_snapshots(conn)) == 1
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_migration_keeps_candidate_sources_without_inventing_snapshots(tmp_path):
    path = tmp_path / "candidates.sqlite3"
    with connect(path) as conn:
        init_db(conn)
        register_guideline(conn, slug="example", title="Invented example", publisher="Test", source_url=SOURCE)
        conn.execute("ALTER TABLE snapshots DROP COLUMN publication_date_note")
        conn.execute("PRAGMA user_version = 1")
    with connect(path) as conn:
        init_db(conn)
        assert list_snapshots(conn) == []
        assert list_guidelines(conn)[0]["verification_status"] == "unverified"
        assert list_guidelines(conn)[0]["title"] == "Invented example"
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 2


def test_group_heading_can_have_no_own_text_without_losing_child_text(db):
    text = "The complete invented module text."
    sections = [
        SectionRecord("group", "Group", ("Group",), None, SOURCE + "#group", "", 0, 0, 0),
        SectionRecord("module", "Module", ("Group", "Module"), "group", SOURCE + "#module", text, 0, len(text), 1),
    ]
    toc = [
        TocEntry("Group", SOURCE + "#group", 1, 0, "group"),
        TocEntry("Module", SOURCE + "#module", 2, 1, "module", 0),
    ]
    snapshot = save_snapshot(db, **document(text=text, sections=sections, toc=toc))
    assert [section["text"] for section in get_sections(db, snapshot)] == ["", text]
    assert get_toc(db, snapshot)[1]["parent_position"] == 0


def test_future_schema_version_is_not_overwritten(db):
    db.execute("PRAGMA user_version = 99")
    with pytest.raises(ValueError, match="schema version"):
        init_db(db)
    assert db.execute("PRAGMA user_version").fetchone()[0] == 99
    assert list_guidelines(db)[0]["title"] == "Invented example"
