"""Download small files from the publisher's fixed OpenStax revision."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Sequence

import httpx


REVISION = "5ae32b3f4bc24ed003e91dc38bf47dba80751044"
BASE_URL = (
    "https://raw.githubusercontent.com/openstax/osbooks-anatomy-physiology/"
    f"{REVISION}/"
)
COLLECTION_PATH = "collections/anatomy-and-physiology-2e.collection.xml"
_METADATA_PATHS = {COLLECTION_PATH, "README.md", "LICENSE"}


class SourceDownloadError(Exception):
    """A source file could not be downloaded or checked."""


@dataclass(frozen=True)
class SourceFile:
    relative_path: str
    path: Path
    url: str
    sha256: str
    fetched_at: str
    from_cache: bool


def _validate_path(relative_path: str) -> None:
    if relative_path not in _METADATA_PATHS and not re.fullmatch(
        r"modules/m[0-9]+/index\.cnxml", relative_path
    ):
        raise SourceDownloadError("Only the selected OpenStax contents and section files are allowed.")


def _paths(data_dir: Path, relative_path: str) -> tuple[Path, Path]:
    _validate_path(relative_path)
    target = data_dir / "openstax" / REVISION / "files" / relative_path
    record = target.with_name(target.name + ".download.json")
    return target, record


def _check_time(value: str) -> None:
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        valid = (
            timestamp.tzinfo is not None
            and timestamp.utcoffset() == timezone.utc.utcoffset(timestamp)
        )
    except (ValueError, TypeError, AttributeError) as exc:
        raise SourceDownloadError("Download records need a full UTC timestamp.") from exc
    if not valid:
        raise SourceDownloadError("Download records need a full UTC timestamp.")


def _load_cached(data_dir: Path, relative_path: str) -> SourceFile | None:
    target, record = _paths(data_dir, relative_path)
    if not target.exists() and not record.exists():
        return None
    try:
        details = json.loads(record.read_text())
        content = target.read_bytes()
        fetched_at = details["fetched_at"]
        _check_time(fetched_at)
        valid = (
            details["url"] == BASE_URL + relative_path
            and details["status"] == 200
            and details["sha256"] == sha256(content).hexdigest()
            and details["bytes"] == len(content)
            and bool(content.strip())
        )
        if not valid:
            raise ValueError("The saved content or download record does not match.")
    except (OSError, ValueError, TypeError, KeyError, AttributeError, SourceDownloadError) as exc:
        raise SourceDownloadError(
            f"Saved OpenStax file failed its check: {relative_path}. "
            "Keep it for inspection; do not silently replace it."
        ) from exc
    return SourceFile(relative_path, target, details["url"], details["sha256"], fetched_at, True)


def _save(
    data_dir: Path, relative_path: str, content: bytes, fetched_at: str
) -> SourceFile:
    _check_time(fetched_at)
    if not content.strip():
        raise SourceDownloadError("An empty source file cannot be cached.")
    target, record = _paths(data_dir, relative_path)
    digest = sha256(content).hexdigest()
    target.parent.mkdir(parents=True, exist_ok=True)
    details = {
        "url": BASE_URL + relative_path,
        "status": 200,
        "fetched_at": fetched_at,
        "sha256": digest,
        "bytes": len(content),
    }
    with target.open("xb") as file:
        file.write(content)
    with record.open("x", encoding="utf-8") as file:
        json.dump(details, file, indent=2)
        file.write("\n")
    return SourceFile(relative_path, target, details["url"], digest, fetched_at, False)


def _download_one(
    relative_path: str,
    data_dir: Path,
    client: httpx.Client,
    offline: bool,
    max_bytes: int,
) -> SourceFile:
    cached = _load_cached(data_dir, relative_path)
    if cached is not None:
        return cached
    if offline:
        raise SourceDownloadError(f"This OpenStax file is not saved yet: {relative_path}.")
    try:
        with client.stream("GET", BASE_URL + relative_path, follow_redirects=False) as response:
            if response.status_code != 200:
                raise SourceDownloadError(
                    f"OpenStax file was not saved: {relative_path}; HTTP {response.status_code}. "
                    "No redirect or retry was attempted."
                )
            parts = []
            total = 0
            for block in response.iter_bytes():
                total += len(block)
                if total > max_bytes:
                    raise SourceDownloadError(f"OpenStax file is too large: {relative_path}.")
                parts.append(block)
            content = b"".join(parts)
            if not content.strip():
                raise SourceDownloadError(f"OpenStax returned an empty file: {relative_path}.")
    except httpx.HTTPError as exc:
        # Connection failures may include private proxy details. Keep them out of output.
        raise SourceDownloadError(
            f"Could not reach the publisher file: {relative_path}. "
            "Check the network policy, proxy, and TLS trust settings."
        ) from exc
    return _save(data_dir, relative_path, content, datetime.now(timezone.utc).isoformat())


def download_files(
    relative_paths: Sequence[str],
    data_dir: Path,
    *,
    client: httpx.Client | None = None,
    workers: int = 6,
    offline: bool = False,
    max_bytes: int = 4 * 1024 * 1024,
) -> dict[str, SourceFile]:
    """Fetch each small source file once, or check and reuse its saved original."""
    if not 1 <= workers <= 8:
        raise ValueError("Use between one and eight download workers.")
    if max_bytes < 1:
        raise ValueError("The download size limit must be positive.")
    paths = list(dict.fromkeys(relative_paths))
    for relative_path in paths:
        _validate_path(relative_path)
    if not paths:
        return {}
    if client is None:
        # Use the injected proxy and CA trust normally; keep certificate checks enabled.
        with httpx.Client(timeout=30, follow_redirects=False) as owned_client:
            return download_files(
                paths, data_dir, client=owned_client, workers=workers,
                offline=offline, max_bytes=max_bytes,
            )
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(
            lambda path: _download_one(path, data_dir, client, offline, max_bytes), paths
        ))
    return {result.relative_path: result for result in results}


def seed_previous_downloads(
    data_dir: Path,
    report_path: Path = Path("reports/openstax-anatomy-access.json"),
) -> int:
    """Reuse earlier source checks only when URL, status, bytes, and hash all agree."""
    if not report_path.is_file():
        return 0
    report = json.loads(report_path.read_text())
    copied = 0
    for item in report.get("downloads", []):
        url = item.get("url", "")
        if not url.startswith(BASE_URL) or item.get("status") != 200:
            raise SourceDownloadError("An earlier download record is not for this publisher revision.")
        relative_path = url[len(BASE_URL):]
        _validate_path(relative_path)
        previous = Path(item["path"])
        content = previous.read_bytes()
        if len(content) != item["bytes"] or sha256(content).hexdigest() != item["sha256"]:
            raise SourceDownloadError("An earlier source file disagrees with its recorded hash.")
        if _load_cached(data_dir, relative_path) is None:
            _save(data_dir, relative_path, content, item["checked_at"])
            copied += 1
    return copied
