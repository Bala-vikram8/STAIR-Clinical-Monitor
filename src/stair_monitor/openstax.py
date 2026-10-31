"""Import the publisher's full contents list and linked textbook text."""

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import io
import json
from pathlib import Path
import re
import sqlite3
from typing import Mapping
import xml.etree.ElementTree as ET
import zipfile

from stair_monitor.openstax_downloads import (
    BASE_URL, COLLECTION_PATH, REVISION, download_files,
)
from stair_monitor.openstax_text import parse_module
from stair_monitor.sources import OPENSTAX_SOURCE
from stair_monitor.storage import (
    SectionRecord, TocEntry, init_db, list_snapshots, register_guideline, save_snapshot,
)


PARSER_VERSION = "openstax-text-v1"
PUBLICATION_DATE_NOTE = "unknown – publisher content"
_COL = "{http://cnx.rice.edu/collxml}"
_MD = "{http://cnx.rice.edu/mdml}"
_CN = "{http://cnx.rice.edu/cnxml}"


@dataclass(frozen=True)
class ContentsNode:
    section_id: str
    title: str | None
    parent_id: str | None
    parent_position: int | None
    parent_titles: tuple[str, ...]
    position: int
    module_id: str | None


@dataclass(frozen=True)
class Document:
    text: str
    sections: tuple[SectionRecord, ...]
    toc: tuple[TocEntry, ...]
    module_count: int
    group_count: int
    warnings: tuple[str, ...]


def _xml(raw: bytes) -> ET.Element:
    # Textbook files are data. Never accept external entity declarations.
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise ValueError("Source XML contains a document type or entity declaration.")
    try:
        return ET.fromstring(raw)
    except ET.ParseError as exc:
        raise ValueError("The publisher contents file is not valid XML.") from exc


def read_contents(raw: bytes) -> tuple[ContentsNode, ...]:
    """Keep the exact publisher order, including parts and chapter groups."""
    root = _xml(raw)
    if root.tag != _COL + "collection":
        raise ValueError("Expected the publisher's collection XML.")
    content = root.find(_COL + "content")
    if content is None:
        raise ValueError("The source has no contents list.")
    nodes: list[ContentsNode] = []
    seen_modules: set[str] = set()

    def visit(element, parent_id=None, parent_position=None, parent_titles=()):
        for child in element:
            position = len(nodes)
            if child.tag == _COL + "module":
                module_id = child.get("document", "")
                if not re.fullmatch(r"m[0-9]+", module_id) or module_id in seen_modules:
                    raise ValueError("The contents list has a missing or repeated section ID.")
                seen_modules.add(module_id)
                nodes.append(ContentsNode(
                    module_id, None, parent_id, parent_position, parent_titles, position, module_id,
                ))
            elif child.tag == _COL + "subcollection":
                title = " ".join("".join(child.find(_MD + "title").itertext()).split()) if child.find(_MD + "title") is not None else ""
                inner = child.find(_COL + "content")
                if not title or inner is None or not len(inner):
                    raise ValueError("A publisher contents group has no title or children.")
                group_id = f"group-{position:04d}"
                nodes.append(ContentsNode(
                    group_id, title, parent_id, parent_position, parent_titles, position, None,
                ))
                visit(inner, group_id, position, (*parent_titles, title))
            else:
                raise ValueError("An unsupported contents entry must be reviewed before import.")

    visit(content)
    if not seen_modules:
        raise ValueError("The contents list has no linked section files.")
    return tuple(nodes)


def build_document(collection: bytes, modules: Mapping[str, bytes]) -> Document:
    """Require every linked body before building a complete saved source."""
    nodes = read_contents(collection)
    expected = {node.module_id for node in nodes if node.module_id is not None}
    if set(modules) != expected:
        raise ValueError("Section files do not exactly match the complete contents list.")
    sections = []
    toc = []
    parts: list[str] = []
    warnings = []
    offset = 0
    for node in nodes:
        if node.module_id is None:
            title = node.title
            own_text = title
            url = BASE_URL + COLLECTION_PATH
        else:
            raw = modules[node.module_id]
            root = _xml(raw)
            original_id = root.findtext(f"{_CN}metadata/{_MD}content-id")
            if original_id != node.module_id:
                raise ValueError("A downloaded section identifies itself as a different module.")
            parsed = parse_module(raw)
            title = parsed.title
            own_text = title + "\n\n" + parsed.text
            url = BASE_URL + f"modules/{node.module_id}/index.cnxml"
            warnings.extend(f"{node.module_id}: {warning}" for warning in parsed.warnings)
        if not title:
            raise ValueError("A contents title remains unresolved; no source was imported.")
        if parts:
            parts.append("\n\n")
            offset += 2
        start = offset
        parts.append(own_text)
        offset += len(own_text)
        path = (*node.parent_titles, title)
        sections.append(SectionRecord(
            node.section_id, title, path, node.parent_id, url, own_text, start, offset, node.position,
        ))
        toc.append(TocEntry(
            title, url, len(path), node.position, node.section_id, node.parent_position,
        ))
    return Document(
        "".join(parts), tuple(sections), tuple(toc), len(expected), len(nodes) - len(expected),
        tuple(warnings),
    )


def _bundle(files: Mapping[str, bytes]) -> bytes:
    """Fixed ZIP timestamps make the same source files produce the same hash."""
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        for name in sorted(files):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.external_attr = 0o644 << 16
            archive.writestr(info, files[name])
    return output.getvalue()


def import_openstax(
    connection: sqlite3.Connection, data_dir: Path, *, offline: bool = False,
) -> dict:
    """Save one complete source, or leave the section tables unchanged on failure."""
    metadata = download_files([COLLECTION_PATH, "README.md", "LICENSE"], data_dir, offline=offline)
    collection = metadata[COLLECTION_PATH].path.read_bytes()
    root = _xml(collection)
    if root.findtext(f"{_COL}metadata/{_MD}title") != "Anatomy and Physiology 2e":
        raise ValueError("The publisher collection title differs from the selected book.")
    license_element = root.find(f"{_COL}metadata/{_MD}license")
    if license_element is None or "by-nc-sa/4.0" not in license_element.get("url", ""):
        raise ValueError("The source licence needs review before this import.")
    nodes = read_contents(collection)
    module_ids = [node.module_id for node in nodes if node.module_id is not None]
    bodies = download_files(
        [f"modules/{module_id}/index.cnxml" for module_id in module_ids], data_dir, offline=offline,
    )
    files = {**metadata, **bodies}
    raw_files = {name: file.path.read_bytes() for name, file in files.items()}
    document = build_document(collection, {
        module_id: raw_files[f"modules/{module_id}/index.cnxml"] for module_id in module_ids
    })
    archive_content = _bundle(raw_files)
    digest = sha256(archive_content).hexdigest()
    folder = data_dir / "openstax" / REVISION
    archive_path = folder / f"{digest}.zip"
    if archive_path.exists():
        if archive_path.read_bytes() != archive_content:
            raise ValueError("The saved book archive disagrees with its hash.")
    else:
        with archive_path.open("xb") as file:
            file.write(archive_content)
    fetched_at = max(
        (file.fetched_at for file in files.values()),
        key=lambda value: datetime.fromisoformat(value.replace("Z", "+00:00")),
    )
    init_db(connection)
    register_guideline(connection, **{
        "slug": OPENSTAX_SOURCE.slug, "title": OPENSTAX_SOURCE.title,
        "publisher": OPENSTAX_SOURCE.publisher, "source_url": OPENSTAX_SOURCE.url,
    })
    previous = next((row for row in list_snapshots(connection, OPENSTAX_SOURCE.slug)
                     if row["raw_sha256"] == digest and row["parser_version"] == PARSER_VERSION), None)
    checked_at = previous["verified_at"] if previous else datetime.now(timezone.utc).isoformat()
    snapshot_id = save_snapshot(
        connection, guideline_slug=OPENSTAX_SOURCE.slug, raw_content=archive_content,
        fetched_at=fetched_at, source_url=OPENSTAX_SOURCE.url + f"/tree/{REVISION}",
        archive_path=str(archive_path), text=document.text, parser_version=PARSER_VERSION,
        sections=document.sections, toc=document.toc, edition="2e", publication_date=None,
        publication_date_note=PUBLICATION_DATE_NOTE, updated_date=None,
        date_evidence="unknown – publisher content; no book publication date supplied in collection metadata. File and revision dates are not treated as publication dates.",
        reuse_terms="OpenStax/Rice University, Anatomy and Physiology 2e. CC BY-NC-SA 4.0. Keep attribution and item-specific notices. Noncommercial reuse; share adaptations on the same terms.",
        reuse_terms_source_url=BASE_URL + "LICENSE", verified_at=checked_at,
    )
    result = {
        "checked_at": checked_at, "source_slug": OPENSTAX_SOURCE.slug,
        "source_type": "open textbook, not a treatment guideline", "revision": REVISION,
        "snapshot_id": snapshot_id, "archive_path": str(archive_path), "raw_sha256": digest,
        "publication_date": PUBLICATION_DATE_NOTE, "publication_date_value": None,
        "updated_date": None, "parser_version": PARSER_VERSION,
        "complete_toc": True, "complete_text_modules": True,
        "module_sections": document.module_count, "navigation_groups": document.group_count,
        "section_rows": len(document.sections), "toc_rows": len(document.toc),
        "normalized_characters": len(document.text), "warnings": list(document.warnings),
        "files": [asdict(file) | {"path": str(file.path)} for file in files.values()],
        "limits": [
            "Text and figure descriptions imported; binary images and linked videos are not downloaded.",
            "Source completeness is not a clinical review or a claim that this edition is current.",
            "CDC and WHO remain in the historical verification record; no requests were retried.",
        ],
    }
    # The database is already complete. A missing extra report must not turn a
    # successful import into a reported failure or hide the saved section rows.
    try:
        (folder / "import-record.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    except OSError:
        result["record_warning"] = "Source stored successfully; the extra import report could not be written. Check the local data folder's write permissions."
    return result
