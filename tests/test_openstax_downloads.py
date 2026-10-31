"""Check public-file caching without contacting the publisher."""

from hashlib import sha256
import json

import httpx
import pytest

from stair_monitor.openstax_downloads import (
    BASE_URL, COLLECTION_PATH, SourceDownloadError, download_files, seed_previous_downloads,
)


def test_files_are_downloaded_once_and_can_be_used_offline(tmp_path):
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(200, content=b"<document>Invented source text</document>")

    paths = [COLLECTION_PATH, "modules/m123/index.cnxml", "modules/m123/index.cnxml"]
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        first = download_files(paths, tmp_path, client=client)
        second = download_files(paths, tmp_path, client=client, offline=True)
    assert len(seen) == 2
    assert len(first) == 2
    assert all(not file.from_cache for file in first.values())
    assert all(file.from_cache for file in second.values())
    for path, file in first.items():
        assert file.url == BASE_URL + path
        assert file.sha256 == sha256(file.path.read_bytes()).hexdigest()
        assert file.fetched_at.endswith("+00:00")


@pytest.mark.parametrize("path", [
    "../LICENSE", "modules/../../LICENSE", "modules/m123/other.cnxml",
    "modules/not-a-module/index.cnxml", "https://example.com/file", "LICENSE?secret",
])
def test_only_selected_revision_paths_can_be_requested(tmp_path, path):
    def handler(request):
        pytest.fail("An invalid path must not make a network request.")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(SourceDownloadError, match="Only the selected"):
            download_files([path], tmp_path, client=client)
    assert not list(tmp_path.rglob("*"))


@pytest.mark.parametrize("status", [302, 403, 404, 429, 500])
def test_failed_request_is_not_saved_or_retried(tmp_path, status):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(status, headers={"location": "https://example.com/file"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(SourceDownloadError, match=f"HTTP {status}"):
            download_files(["LICENSE"], tmp_path, client=client)
    assert len(seen) == 1
    assert not list(tmp_path.rglob("*"))


def test_corrupt_cache_is_rejected_without_network_replacement(tmp_path):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, content=b"Original fixture")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        saved = download_files(["LICENSE"], tmp_path, client=client)["LICENSE"]
        saved.path.write_bytes(b"Changed fixture")
        with pytest.raises(SourceDownloadError, match="failed its check"):
            download_files(["LICENSE"], tmp_path, client=client)
    assert len(calls) == 1


def test_missing_offline_file_is_a_visible_error(tmp_path):
    with httpx.Client(transport=httpx.MockTransport(lambda r: pytest.fail("offline"))) as client:
        with pytest.raises(SourceDownloadError, match="not saved yet"):
            download_files(["LICENSE"], tmp_path, client=client, offline=True)


@pytest.mark.parametrize("content, limit, message", [
    (b" ", 100, "empty"), (b"too large", 3, "too large"),
])
def test_empty_and_oversized_files_are_not_saved(tmp_path, content, limit, message):
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=content))) as client:
        with pytest.raises(SourceDownloadError, match=message):
            download_files(["LICENSE"], tmp_path, client=client, max_bytes=limit)
    assert not list(tmp_path.rglob("*"))


def test_proxy_details_are_not_in_the_user_message(tmp_path):
    def handler(request):
        raise httpx.ProxyError("private proxy information")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(SourceDownloadError) as error:
            download_files(["LICENSE"], tmp_path, client=client)
    assert "private proxy information" not in str(error.value)


def test_previous_download_can_seed_an_offline_cache(tmp_path):
    content = b"Invented publisher metadata"
    previous = tmp_path / "old-license"
    previous.write_bytes(content)
    report = tmp_path / "report.json"
    report.write_text(json.dumps({"downloads": [{
        "url": BASE_URL + "LICENSE", "status": 200, "bytes": len(content),
        "sha256": sha256(content).hexdigest(), "path": str(previous),
        "checked_at": "2026-10-30T12:00:00+00:00",
    }]}))
    cache = tmp_path / "new-cache"
    assert seed_previous_downloads(cache, report) == 1
    assert seed_previous_downloads(cache, report) == 0
    saved = download_files(["LICENSE"], cache, offline=True)["LICENSE"]
    assert saved.path.read_bytes() == content
    assert saved.fetched_at == "2026-10-30T12:00:00+00:00"


def test_seed_rejects_changed_earlier_source(tmp_path):
    previous = tmp_path / "old-license"
    previous.write_bytes(b"changed")
    report = tmp_path / "report.json"
    report.write_text(json.dumps({"downloads": [{
        "url": BASE_URL + "LICENSE", "status": 200, "bytes": 3,
        "sha256": "wrong", "path": str(previous),
        "checked_at": "2026-10-30T12:00:00+00:00",
    }]}))
    with pytest.raises(SourceDownloadError, match="disagrees"):
        seed_previous_downloads(tmp_path / "new-cache", report)


def test_seed_rejects_an_unknown_download_time(tmp_path):
    content = b"Invented publisher metadata"
    previous = tmp_path / "old-license"
    previous.write_bytes(content)
    report = tmp_path / "report.json"
    report.write_text(json.dumps({"downloads": [{
        "url": BASE_URL + "LICENSE", "status": 200, "bytes": len(content),
        "sha256": sha256(content).hexdigest(), "path": str(previous),
        "checked_at": "unknown",
    }]}))
    with pytest.raises(SourceDownloadError, match="UTC timestamp"):
        seed_previous_downloads(tmp_path / "new-cache", report)
    assert not (tmp_path / "new-cache").exists()
