"""Small records shared by both retrieval methods."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Section:
    section_id: str
    title: str
    heading_path: tuple[str, ...]
    source_url: str
    text: str
    start_offset: int
    end_offset: int
    position: int
    is_navigation: bool = False


@dataclass(frozen=True)
class TocItem:
    section_id: str
    title: str
    heading_path: tuple[str, ...]
    source_url: str
    position: int
    parent_position: int | None
    level: int
    is_navigation: bool = False


@dataclass(frozen=True)
class Corpus:
    snapshot_id: str
    sections: tuple[Section, ...]
    toc: tuple[TocItem, ...]
    source_title: str = ""
    source_url: str = ""
    source_sha256: str = ""


@dataclass(frozen=True)
class Selection:
    method: str
    status: str
    section_id: str | None = None
    section_title: str | None = None
    reason: str | None = None
    score: float | None = None
    details: dict = field(default_factory=dict)
