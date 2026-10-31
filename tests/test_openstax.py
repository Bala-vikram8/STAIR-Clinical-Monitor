"""Import checks use invented textbook text and a small publisher-shaped tree."""

from dataclasses import asdict
from pathlib import Path
import sqlite3

import pytest

from stair_monitor.openstax import build_document, import_openstax, read_contents
from stair_monitor.openstax_downloads import BASE_URL, COLLECTION_PATH, SourceFile
from stair_monitor.storage import connect, get_sections, get_toc, list_snapshots


COLLECTION = b'''<collection xmlns="http://cnx.rice.edu/collxml"
 xmlns:md="http://cnx.rice.edu/mdml"><metadata>
 <md:title>Anatomy and Physiology 2e</md:title>
 <md:license url="http://creativecommons.org/licenses/by-nc-sa/4.0/"/>
 </metadata><content><subcollection><md:title>Invented part</md:title><content>
 <subcollection><md:title>Invented chapter</md:title><content>
 <module document="m100"/><module document="m101"/>
 </content></subcollection></content></subcollection></content></collection>'''


def module(identifier, title="Shared heading"):
    return f'''<document xmlns="http://cnx.rice.edu/cnxml"
 xmlns:md="http://cnx.rice.edu/mdml"><title>{title}</title><metadata>
 <md:content-id>{identifier}</md:content-id></metadata><content>
 <para>Invented source text for {identifier}.</para></content></document>'''.encode()


def test_full_hierarchy_keeps_repeated_titles_and_exact_text_positions():
    doc = build_document(COLLECTION, {"m100": module("m100"), "m101": module("m101")})
    assert doc.module_count == 2 and doc.group_count == 2
    assert len(doc.toc) == len(doc.sections) == 4
    assert doc.sections[2].heading_path == ("Invented part", "Invented chapter", "Shared heading")
    assert doc.sections[2].title == doc.sections[3].title
    assert doc.sections[2].section_id != doc.sections[3].section_id
    assert doc.toc[2].parent_position == 1
    for section in doc.sections:
        assert doc.text[section.start_offset:section.end_offset] == section.text
    assert "Invented source text for m100" in doc.sections[2].text
    assert "m100" not in doc.sections[1].text


def test_missing_module_is_not_a_complete_source():
    with pytest.raises(ValueError, match="exactly match"):
        build_document(COLLECTION, {"m100": module("m100")})


def test_wrong_module_identity_is_rejected():
    with pytest.raises(ValueError, match="different module"):
        build_document(COLLECTION, {"m100": module("m999"), "m101": module("m101")})


@pytest.mark.parametrize("raw", [
    COLLECTION.replace(b'm101', b'm100'),
    COLLECTION.replace(b'm101', b'../../private'),
    COLLECTION.replace(b'<module document="m101"/>', b'<other/>'),
    b'<!DOCTYPE collection [<!ENTITY x "test">]>' + COLLECTION,
])
def test_ambiguous_or_unsupported_contents_cannot_be_silently_skipped(raw):
    with pytest.raises(ValueError):
        read_contents(raw)


def fake_downloads(tmp_path, monkeypatch, modules=None):
    data = {
        COLLECTION_PATH: COLLECTION, "README.md": b"Invented test fixture.", "LICENSE": b"Test fixture.",
        "modules/m100/index.cnxml": module("m100"), "modules/m101/index.cnxml": module("m101"),
    }
    if modules is not None:
        data.update(modules)

    def download(paths, data_dir, **kwargs):
        from hashlib import sha256
        result = {}
        for name in paths:
            path = tmp_path / "files" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data[name])
            result[name] = SourceFile(
                name, path, BASE_URL + name, sha256(data[name]).hexdigest(),
                "2026-10-31T12:00:00+00:00", True,
            )
        return result

    monkeypatch.setattr("stair_monitor.openstax.download_files", download)


def test_complete_import_repeats_without_duplicate_rows(tmp_path, monkeypatch):
    fake_downloads(tmp_path, monkeypatch)
    conn = connect(tmp_path / "source.sqlite3")
    try:
        data_dir = tmp_path / "raw"
        # The real downloader creates these source directories before import.
        from stair_monitor.openstax_downloads import REVISION
        (data_dir / "openstax" / REVISION).mkdir(parents=True)
        first = import_openstax(conn, data_dir, offline=True)
        second = import_openstax(conn, data_dir, offline=True)
        assert first["snapshot_id"] == second["snapshot_id"]
        assert len(list_snapshots(conn)) == 1
        assert len(get_sections(conn, first["snapshot_id"])) == 4
        assert len(get_toc(conn, first["snapshot_id"])) == 4
        source = list_snapshots(conn)[0]
        assert source["publication_date"] is None
        assert source["publication_date_note"] == "unknown – publisher content"
        assert source["verified_at"] == first["checked_at"]
        assert conn.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert not conn.execute('PRAGMA foreign_key_check').fetchall()
    finally:
        conn.close()


def test_bad_body_leaves_no_real_sections(tmp_path, monkeypatch):
    fake_downloads(tmp_path, monkeypatch, {"modules/m101/index.cnxml": b"not valid XML"})
    conn = connect(":memory:")
    from stair_monitor.storage import init_db
    init_db(conn)
    try:
        with pytest.raises(ValueError):
            import_openstax(conn, tmp_path / "raw", offline=True)
        for table in ["snapshots", "sections", "toc_entries"]:
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    finally:
        conn.close()


def test_extra_report_failure_does_not_hide_successful_import(tmp_path, monkeypatch):
    fake_downloads(tmp_path, monkeypatch)
    from stair_monitor.openstax_downloads import REVISION
    data_dir = tmp_path / "raw"
    (data_dir / "openstax" / REVISION).mkdir(parents=True)
    original_write = Path.write_text

    def failed_report(path, *args, **kwargs):
        if path.name == "import-record.json":
            raise OSError("cannot write extra report")
        return original_write(path, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", failed_report)
    conn = connect(":memory:")
    try:
        result = import_openstax(conn, data_dir, offline=True)
        assert "Source stored successfully" in result["record_warning"]
        assert len(list_snapshots(conn)) == 1
        assert len(get_sections(conn, result["snapshot_id"])) == 4
        assert len(get_toc(conn, result["snapshot_id"])) == 4
    finally:
        conn.close()
