"""The section picker is tested without API calls or patient information."""

from types import SimpleNamespace
import json

import pytest

from stair_monitor.retrieval.toc import (
    ClaudeAdapter, DEFAULT_MODEL, ScriptedAdapter, TocPicker,
)
from stair_monitor.retrieval.types import Corpus, Section, TocItem


@pytest.fixture
def corpus():
    sections = (
        Section("group-0", "Invented part", ("Invented part",), "https://example.org/book", "heading only", 0, 12, 0, True),
        Section("m1", "Shared title", ("Invented part", "Shared title"), "https://example.org/m1", "body text must never be sent", 13, 40, 1),
        Section("m2", "Shared title", ("Shared title",), "https://example.org/m2", "another private-to-retrieval body", 41, 80, 2),
        Section("m3", "Final section", ("Final section",), "https://example.org/m3", "last body text is also excluded", 81, 120, 3),
    )
    toc = tuple(TocItem(
        section.section_id, section.title, section.heading_path, section.source_url,
        section.position, 0 if section.section_id == "m1" else None,
        len(section.heading_path), section.is_navigation,
    ) for section in sections)
    return Corpus("fixture-snapshot", sections, toc, "Invented public book")


def choice(section_id="m1", title="Shared title"):
    return json.dumps({"status": "selected", "section_id": section_id, "section_title": title})


def test_full_contents_includes_last_entry_and_navigation_but_no_bodies(corpus):
    adapter = ScriptedAdapter({"Invented question": choice("m3", "Final section")})
    result = TocPicker(corpus, adapter=adapter).pick("Invented question")
    assert result.status == "selected" and result.section_id == "m3"
    sent = adapter.requests[0]
    payload = json.loads(sent["messages"][0]["content"])
    assert [row["section_id"] for row in payload["table_of_contents"]] == ["group-0", "m1", "m2", "m3"]
    assert payload["table_of_contents"][0]["selectable"] is False
    assert payload["table_of_contents"][-1]["selectable"] is True
    assert payload["table_of_contents"][1]["path"] == ["Invented part", "Shared title"]
    assert "body text must never be sent" not in str(sent)
    assert "last body text is also excluded" not in str(sent)
    assert result.details["toc_entry_count"] == 4
    assert result.details["mode"] == "offline_scripted"
    assert result.details["response_model"] == "offline-scripted-test-double"
    assert result.details["token_count_kind"] == "scripted_test_count"
    assert len(result.details["prompt_sha256"]) == len(result.details["toc_sha256"]) == 64
    assert result.method == "toc_claude"


def test_duplicate_titles_are_resolved_by_exact_id_without_fuzzy_repair(corpus):
    first = TocPicker(corpus, adapter=ScriptedAdapter({"q": choice("m1")})).select("q")
    second = TocPicker(corpus, adapter=ScriptedAdapter({"q": choice("m2")})).select("q")
    assert first.section_title == second.section_title == "Shared title"
    assert first.section_id == "m1" and second.section_id == "m2"


@pytest.mark.parametrize("raw, reason", [
    ("not json", "invalid_json"),
    ('```json\n{"status":"no_match","section_id":null,"section_title":null}\n```', "invalid_json"),
    ('[]', "invalid_response_fields"),
    ('{"status":"selected","section_id":"m1"}', "invalid_response_fields"),
    (json.dumps({"status":"selected","section_id":"m1","section_title":"Shared title","reason":"extra"}), "invalid_response_fields"),
    (choice("unknown"), "unknown_section_id"),
    (choice("m1", "shared title"), "section_title_mismatch"),
    (choice("group-0", "Invented part"), "navigation_heading_selected"),
    (json.dumps({"status":"no_match","section_id":"m1","section_title":"Shared title"}), "invalid_choice"),
    (json.dumps({"status":"selected","section_id":None,"section_title":None}), "invalid_choice"),
])
def test_invalid_model_output_is_kept_as_failure(corpus, raw, reason):
    result = TocPicker(corpus, adapter=ScriptedAdapter({"q": raw})).pick("q")
    assert result.status == "invalid"
    assert result.section_id is None and result.section_title is None
    assert result.details["reason_code"] == reason
    assert result.details["raw_response"] == raw


def test_explicit_refusal_is_distinct_from_invalid_output(corpus):
    raw = json.dumps({"status": "no_match", "section_id": None, "section_title": None})
    result = TocPicker(corpus, adapter=ScriptedAdapter({"q": raw})).pick("q")
    assert result.status == "no_match"
    assert result.details["reason_code"] == "model_no_match"


def test_empty_query_does_not_invoke_adapter(corpus):
    adapter = ScriptedAdapter({})
    result = TocPicker(corpus, adapter=adapter).pick(" \n")
    assert result.status == "no_match"
    assert adapter.requests == [] and adapter.completion_calls == 0


def test_missing_script_is_an_error_not_a_fabricated_selection(corpus):
    result = TocPicker(corpus, adapter=ScriptedAdapter({})).pick("q")
    assert result.status == "error" and result.details["reason_code"] == "api_error"
    assert result.section_id is None


def test_missing_key_makes_no_sdk_client_or_network_request(corpus, monkeypatch):
    import anthropic

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    def unexpected(*args, **kwargs):
        pytest.fail("The SDK must not be initialized when the key is absent.")

    monkeypatch.setattr(anthropic, "Anthropic", unexpected)
    result = TocPicker(corpus).pick("Invented question")
    assert result.status == "blocked"
    assert result.details["mode"] == "live_claude"
    assert result.details["reason_code"] == "missing_api_key"
    assert result.details["raw_response"] is None


class FakeMessages:
    def __init__(self, *, input_tokens=123, raw=None, stop_reason="end_turn", failure=None):
        self.input_tokens = input_tokens
        self.raw = choice() if raw is None else raw
        self.stop_reason = stop_reason
        self.failure = failure
        self.count_calls = []
        self.create_calls = []

    def count_tokens(self, **kwargs):
        self.count_calls.append(kwargs)
        if self.failure == "count":
            raise RuntimeError("do-not-display-connection-detail")
        return SimpleNamespace(input_tokens=self.input_tokens)

    def create(self, **kwargs):
        self.create_calls.append(kwargs)
        if self.failure == "create":
            raise RuntimeError("do-not-display-connection-detail")
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=self.raw)],
            stop_reason=self.stop_reason, model=DEFAULT_MODEL,
            usage=SimpleNamespace(input_tokens=self.input_tokens, output_tokens=20),
        )


class FakeSDK:
    def __init__(self, **kwargs):
        self.messages = FakeMessages(**kwargs)
        self.options = []

    def with_options(self, **kwargs):
        self.options.append(kwargs)
        return self


def test_live_adapter_counts_the_exact_prompt_before_creating(corpus):
    sdk = FakeSDK()
    result = TocPicker(corpus, adapter=ClaudeAdapter(sdk)).pick("Invented question")
    assert result.status == "selected"
    assert len(sdk.messages.count_calls) == len(sdk.messages.create_calls) == 1
    count, create = sdk.messages.count_calls[0], sdk.messages.create_calls[0]
    assert count["messages"] == create["messages"]
    assert count["system"] == create["system"]
    assert count["model"] == create["model"] == DEFAULT_MODEL
    assert create["max_tokens"] == 256
    assert "temperature" not in create
    assert sdk.options == [{"max_retries": 0, "timeout": 30}]
    assert result.details["input_tokens"] == 123
    assert result.details["usage"] == {"input_tokens": 123, "output_tokens": 20}
    assert result.details["token_count_kind"] == "api_count"
    assert result.details["temperature"] == "provider default; field omitted"


def test_over_budget_blocks_completion_without_truncating_contents(corpus):
    sdk = FakeSDK(input_tokens=1001)
    result = TocPicker(corpus, adapter=ClaudeAdapter(sdk), max_input_tokens=1000).pick("q")
    assert result.status == "blocked"
    assert result.details["reason_code"] == "context_budget_exceeded"
    assert result.details["input_tokens"] == 1001
    assert sdk.messages.create_calls == []
    sent = json.loads(sdk.messages.count_calls[0]["messages"][0]["content"])
    assert len(sent["table_of_contents"]) == len(corpus.toc)


def test_scripted_token_count_is_not_misreported_as_live(corpus):
    adapter = ScriptedAdapter({"q": choice()}, input_tokens=200)
    result = TocPicker(corpus, adapter=adapter, max_input_tokens=100).pick("q")
    assert result.status == "blocked" and adapter.completion_calls == 0
    assert result.details["token_count_kind"] == "scripted_test_count"


@pytest.mark.parametrize("operation", ["count", "create"])
def test_api_failures_do_not_dump_proxy_or_credential_text(corpus, operation):
    sdk = FakeSDK(failure=operation)
    result = TocPicker(corpus, adapter=ClaudeAdapter(sdk)).pick("q")
    assert result.status == "error"
    assert result.details["reason_code"] == "api_error"
    assert "do-not-display-connection-detail" not in str(result)


@pytest.mark.parametrize("count", [None, 0, -1, True, "123"])
def test_unusable_api_count_does_not_trigger_completion(corpus, count):
    sdk = FakeSDK(input_tokens=count)
    result = TocPicker(corpus, adapter=ClaudeAdapter(sdk)).pick("q")
    assert result.status == "error"
    assert sdk.messages.create_calls == []


def test_cut_off_response_is_invalid_even_if_text_looks_like_complete_json(corpus):
    sdk = FakeSDK(stop_reason="max_tokens")
    result = TocPicker(corpus, adapter=ClaudeAdapter(sdk)).pick("q")
    assert result.status == "invalid"
    assert result.details["reason_code"] == "incomplete_model_response"


def test_explicit_pinned_model_setting_is_used(corpus, monkeypatch):
    monkeypatch.setenv("STAIR_CLAUDE_MODEL", "claude-sonnet-4-5-20250929")
    adapter = ScriptedAdapter({"q": choice()})
    TocPicker(corpus, adapter=adapter).pick("q")
    assert adapter.requests[0]["model"] == "claude-sonnet-4-5-20250929"
    with pytest.raises(ValueError, match="explicit Claude model"):
        TocPicker(corpus, model="claude-sonnet-latest")


def test_missing_contents_entry_is_rejected_before_any_picker_call(corpus):
    incomplete = Corpus(corpus.snapshot_id, corpus.sections, corpus.toc[:-1])
    with pytest.raises(ValueError, match="complete contents"):
        TocPicker(incomplete)
