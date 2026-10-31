"""Save official pages for inspection. A download is not source verification."""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx

from stair_monitor.sources import SOURCES, Source


class DownloadError(Exception):
    """The public page could not be saved safely."""


@dataclass(frozen=True)
class Download:
    source_slug: str
    final_url: str
    sha256: str
    archive_path: Path
    record_path: Path


def _check_url(url: str) -> None:
    try:
        parsed = urlsplit(url)
        allowed = (
            parsed.scheme == "https"
            and parsed.hostname in {"www.cdc.gov", "cdc.gov"}
            and parsed.username is None
            and parsed.password is None
            and parsed.port in {None, 443}
        )
    except ValueError as exc:
        raise DownloadError("Only official CDC HTTPS pages may be downloaded.") from exc
    if not allowed:
        raise DownloadError("Only official CDC HTTPS pages may be downloaded.")


def fetch_page(
    source: Source,
    data_dir: Path,
    *,
    client: httpx.Client | None = None,
    max_bytes: int = 20 * 1024 * 1024,
) -> Download:
    """Archive a candidate page; do not guess its date, contents, or reuse terms."""
    if source not in SOURCES:
        raise DownloadError("Choose a source from the project's public source list.")
    if max_bytes < 1:
        raise ValueError("The download size limit must be positive.")
    if client is None:
        # Keep the environment proxy and TLS trust settings; never disable checks.
        with httpx.Client(timeout=30, follow_redirects=False) as owned_client:
            return fetch_page(source, data_dir, client=owned_client, max_bytes=max_bytes)

    url = source.url
    try:
        for _ in range(6):
            _check_url(url)
            with client.stream("GET", url, follow_redirects=False) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        raise DownloadError("The CDC redirect has no destination.")
                    url = urljoin(url, location)
                    continue
                if response.status_code != 200:
                    raise DownloadError(
                        f"CDC page was not saved: HTTP {response.status_code}. "
                        "Check the network policy and the source address."
                    )
                media_type = response.headers.get("content-type", "").split(";")[0].strip()
                if media_type not in {"text/html", "application/xhtml+xml"}:
                    raise DownloadError("Expected an HTML guideline page; nothing was imported.")
                parts = []
                total = 0
                for block in response.iter_bytes():
                    total += len(block)
                    if total > max_bytes:
                        raise DownloadError("The page exceeds the download size limit.")
                    parts.append(block)
                content = b"".join(parts)
                if not content.strip():
                    raise DownloadError("CDC returned an empty page; nothing was imported.")
                break
        else:
            raise DownloadError("Too many CDC redirects; nothing was imported.")
    except httpx.HTTPError as exc:
        # Proxy messages can contain connection details. Do not dump them to logs.
        raise DownloadError(
            "Could not reach the official CDC page. Check the network policy, "
            "proxy, and TLS trust settings. Nothing was imported."
        ) from exc

    fetched_at = datetime.now(timezone.utc)
    digest = hashlib.sha256(content).hexdigest()
    folder = data_dir / "raw" / source.slug
    folder.mkdir(parents=True, exist_ok=True)
    archive = folder / f"{digest}.html"
    if archive.exists():
        if archive.read_bytes() != content:
            raise DownloadError("A saved file disagrees with its hash; do not overwrite it.")
    else:
        with archive.open("xb") as file:
            file.write(content)

    record = folder / f"{digest}-{fetched_at.strftime('%Y%m%dT%H%M%S%fZ')}.json"
    with record.open("x", encoding="utf-8") as file:
        json.dump(
            {
                "source_slug": source.slug,
                "requested_url": source.url,
                "final_url": url,
                "fetched_at": fetched_at.isoformat(),
                "sha256": digest,
                "archive_path": str(archive),
                "content_type": media_type,
                "verification_status": "not checked",
                "publication_date": None,
                "updated_date": None,
                "note": "A saved page is not a verified guideline or a complete import.",
            },
            file,
            indent=2,
        )
        file.write("\n")
    return Download(source.slug, url, digest, archive, record)
