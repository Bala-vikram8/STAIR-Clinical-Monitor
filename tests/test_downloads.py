"""Use made-up HTML, never patient data or live CDC requests."""

import json

import httpx
import pytest

from stair_monitor.downloads import DownloadError, fetch_page
from stair_monitor.sources import SOURCES


def client_for(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_archive_does_not_claim_source_verification(tmp_path):
    content = b"<html><h1>Made-up public source fixture</h1></html>"
    with client_for(lambda request: httpx.Response(200, content=content,
                    headers={"content-type": "text/html; charset=utf-8"})) as client:
        first = fetch_page(SOURCES[0], tmp_path, client=client)
        second = fetch_page(SOURCES[0], tmp_path, client=client)
    record = json.loads(first.record_path.read_text())
    assert first.archive_path.read_bytes() == content
    assert first.archive_path == second.archive_path
    assert first.record_path != second.record_path
    assert record["verification_status"] == "not checked"
    assert record["publication_date"] is None
    assert record["updated_date"] is None
    assert record["fetched_at"].endswith("+00:00")


@pytest.mark.parametrize("status", [403, 404, 429, 500])
def test_failed_request_saves_no_page(tmp_path, status):
    with client_for(lambda request: httpx.Response(status)) as client:
        with pytest.raises(DownloadError, match=f"HTTP {status}"):
            fetch_page(SOURCES[0], tmp_path, client=client)
    assert not list(tmp_path.rglob("*"))


@pytest.mark.parametrize("target", [
    "https://example.com/page", "http://www.cdc.gov/page",
    "https://www.cdc.gov:bad/page", "https://www.cdc.gov:99999/page",
])
def test_redirect_cannot_leave_official_https_hosts(tmp_path, target):
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(302, headers={"location": target})

    with client_for(handler) as client:
        with pytest.raises(DownloadError, match="official CDC"):
            fetch_page(SOURCES[0], tmp_path, client=client)
    assert len(calls) == 1
    assert not list(tmp_path.rglob("*"))


def test_valid_redirect_records_final_address(tmp_path):
    def handler(request):
        if str(request.url) == SOURCES[0].url:
            return httpx.Response(301, headers={"location": "/public-fixture.html"})
        return httpx.Response(200, text="<html>Made-up fixture</html>",
                              headers={"content-type": "text/html"})

    with client_for(handler) as client:
        result = fetch_page(SOURCES[0], tmp_path, client=client)
    assert result.final_url == "https://www.cdc.gov/public-fixture.html"


def test_request_failure_message_does_not_expose_proxy_details(tmp_path):
    def handler(request):
        raise httpx.ProxyError("private proxy detail")

    with client_for(handler) as client:
        with pytest.raises(DownloadError) as error:
            fetch_page(SOURCES[0], tmp_path, client=client)
    assert "private proxy detail" not in str(error.value)
    assert not list(tmp_path.rglob("*"))


@pytest.mark.parametrize("headers, content, limit, message", [
    ({"content-type": "application/pdf"}, b"pdf", 100, "HTML"),
    ({"content-type": "text/html"}, b" ", 100, "empty"),
    ({"content-type": "text/html"}, b"too long", 3, "size limit"),
])
def test_invalid_or_oversized_page_is_not_saved(tmp_path, headers, content, limit, message):
    with client_for(lambda request: httpx.Response(200, headers=headers,
                                                  content=content)) as client:
        with pytest.raises(DownloadError, match=message):
            fetch_page(SOURCES[0], tmp_path, client=client, max_bytes=limit)
    assert not list(tmp_path.rglob("*"))
