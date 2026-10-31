"""Check fixed-window search using invented educational text only."""

from copy import deepcopy
import json

import pytest

from stair_monitor.retrieval.baseline import BaselineIndex
from stair_monitor.retrieval.types import Section


def section(section_id, text, position=0, start=0, title=None, navigation=False):
    return Section(
        section_id=section_id, title=title or section_id, heading_path=(title or section_id,),
        source_url="https://example.org/textbook#" + section_id, text=text,
        start_offset=start, end_offset=start+len(text), position=position,
        is_navigation=navigation,
    )


def test_windows_cross_section_boundaries_and_keep_all_source_spans():
    first = section("first", "artery capillary vein", 0)
    heading = section("group-1", "Navigation heading", 1, 40, navigation=True)
    second = section("second", "neuron dendrite axon", 2, 80)
    index = BaselineIndex.build("source", [first, heading, second], chunk_size=4, overlap=1)
    assert len(index.chunks) == 2
    assert index.chunks[0].text == "artery capillary vein\n\nneuron"
    assert index.chunks[0].section_id == "first"
    assert [span.section_id for span in index.chunks[0].source_spans] == ["first", "second"]
    assert [span.token_count for span in index.chunks[0].source_spans] == [3, 1]
    assert index.chunks[0].source_spans[1].start_offset == second.start_offset
    assert "Navigation" not in " ".join(chunk.text for chunk in index.chunks)
    assert index.chunks[1].token_start == 3
    assert index.chunks[1].token_end == 6


def test_section_overlap_tie_uses_document_order():
    first = section("first", "artery capillary", 0)
    second = section("second", "neuron dendrite", 1, 100)
    index = BaselineIndex.build("source", [second, first], chunk_size=4, overlap=0)
    assert index.chunks[0].section_id == "first"


def test_original_punctuation_units_and_source_positions_survive_chunking():
    text = "Invented example: 3.5 mg/mL; pH 7.4 remains recorded."
    source = section("units", text, start=12)
    index = BaselineIndex.build("source", [source], chunk_size=50, overlap=0)
    chunk = index.chunks[0]
    assert "3.5 mg/mL; pH 7.4" in chunk.text
    span = chunk.source_spans[0]
    assert text[span.start_offset-12:span.end_offset-12] == chunk.text


def test_word_vectors_choose_matching_text_and_keep_repeated_titles_distinct():
    first = section("blood", "artery capillary vein blood circulation", 0, title="Overview")
    second = section("nerve", "neuron dendrite axon nerve signal", 1, 100, title="Overview")
    index = BaselineIndex.build("source", [first, second], chunk_size=5, overlap=0)
    result = index.select("How does a neuron send a nerve signal?")
    assert result.status == "selected"
    assert result.section_id == "nerve"
    assert result.section_title == "Overview"
    assert result.method == "baseline_tfidf"
    assert result.score > 0
    assert "neuron" in result.details["chunk_text"]


@pytest.mark.parametrize("query", ["", "   ", "unlistedforeignwordxyz", "the and or"])
def test_empty_or_unknown_query_is_not_a_successful_selection(query):
    index = BaselineIndex.build("source", [section("blood", "artery capillary vein")])
    result = index.select(query)
    assert result.status == "no_match"
    assert result.section_id is None


def test_zero_similarity_is_not_a_successful_selection():
    index = BaselineIndex.build("source", [section("blood", "artery capillary vein")])
    index.vectors.data[:] = 0
    assert index.select("artery").status == "no_match"


def test_export_round_trip_retains_exact_selections_and_vectors():
    index = BaselineIndex.build("source", [
        section("blood", "artery capillary vein blood circulation", 0),
        section("nerve", "neuron dendrite axon nerve signal", 1, 100),
    ], chunk_size=5, overlap=1)
    payload = json.loads(json.dumps(index.export()))
    restored = BaselineIndex.restore(payload)
    for query in ["neuron nerve", "artery blood", "unknownvocabulary"]:
        before, after = index.select(query), restored.select(query)
        assert after.section_id == before.section_id
        assert after.status == before.status
        assert after.score == pytest.approx(before.score) if before.score is not None else after.score is None
        assert after.details == before.details
    assert restored.chunks == index.chunks


@pytest.mark.parametrize("change", [
    {"chunk_size": 0}, {"chunk_size": True}, {"overlap": -1}, {"overlap": 256},
])
def test_invalid_window_settings_are_rejected(change):
    with pytest.raises(ValueError):
        BaselineIndex.build("source", [section("blood", "artery capillary")], **change)


def test_empty_body_and_overlapping_source_ranges_are_rejected():
    with pytest.raises(ValueError, match="empty"):
        BaselineIndex.build("source", [section("empty", "")])
    with pytest.raises(ValueError, match="positions"):
        BaselineIndex.build("source", [
            section("first", "artery capillary", 0), section("second", "neuron axon", 1, 2),
        ])


def test_corrupt_saved_vector_shape_is_rejected():
    index = BaselineIndex.build("source", [section("blood", "artery capillary vein")])
    payload = deepcopy(index.export())
    payload["vectors"]["shape"][0] += 1
    with pytest.raises(ValueError, match="shape"):
        BaselineIndex.restore(payload)
