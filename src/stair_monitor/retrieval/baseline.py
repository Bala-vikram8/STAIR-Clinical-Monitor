"""Search regular text windows with word-based vectors and cosine similarity."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import math
import re
from typing import Sequence

import numpy as np
from scipy.sparse import csr_matrix
import sklearn
from sklearn.feature_extraction.text import TfidfVectorizer

from stair_monitor.retrieval.types import Section, Selection


METHOD = "baseline_tfidf"
_WORD = re.compile(r"\b\w+\b", flags=re.UNICODE)
_FORMAT_VERSION = 1


@dataclass(frozen=True)
class SourceSpan:
    """The exact part of a stored section that contributes to a chunk."""

    section_id: str
    start_offset: int
    end_offset: int
    token_count: int


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    position: int
    text: str
    token_start: int
    token_end: int
    start_offset: int
    end_offset: int
    source_spans: tuple[SourceSpan, ...]
    section_id: str
    section_title: str


@dataclass(frozen=True)
class _Token:
    section_index: int
    start: int
    end: int


def _vectorizer(*, vocabulary=None) -> TfidfVectorizer:
    return TfidfVectorizer(
        lowercase=True,
        token_pattern=r"(?u)\b\w+\b",
        ngram_range=(1, 2),
        stop_words="english",
        norm="l2",
        sublinear_tf=True,
        dtype=np.float64,
        vocabulary=vocabulary,
    )


def _make_chunks(
    snapshot_id: str, sections: Sequence[Section], chunk_size: int, overlap: int,
) -> tuple[Chunk, ...]:
    if not isinstance(chunk_size, int) or isinstance(chunk_size, bool) or chunk_size < 1:
        raise ValueError("Chunk size must be a positive whole number.")
    if not isinstance(overlap, int) or isinstance(overlap, bool) or not 0 <= overlap < chunk_size:
        raise ValueError("Chunk overlap must be a whole number smaller than the chunk size.")
    bodies = sorted((section for section in sections if not section.is_navigation), key=lambda s: s.position)
    if not bodies:
        raise ValueError("There are no text-bearing sections to index.")
    if len({section.section_id for section in bodies}) != len(bodies):
        raise ValueError("Text-bearing sections must have distinct source IDs.")
    if len({section.position for section in bodies}) != len(bodies):
        raise ValueError("Text-bearing sections must have distinct source positions.")
    tokens: list[_Token] = []
    previous_end = 0
    for index, section in enumerate(bodies):
        if not section.text.strip():
            raise ValueError("A text-bearing source section is empty.")
        if (
            section.start_offset < previous_end
            or section.end_offset - section.start_offset != len(section.text)
        ):
            raise ValueError("Source section text or its character positions are inconsistent.")
        previous_end = section.end_offset
        tokens.extend(_Token(index, match.start(), match.end()) for match in _WORD.finditer(section.text))
    if not tokens:
        raise ValueError("The source has no word tokens to index.")

    chunks = []
    step = chunk_size - overlap
    for token_start in range(0, len(tokens), step):
        token_end = min(token_start + chunk_size, len(tokens))
        window = tokens[token_start:token_end]
        spans = []
        text_parts = []
        cursor = 0
        while cursor < len(window):
            first = window[cursor]
            last_index = cursor + 1
            while last_index < len(window) and window[last_index].section_index == first.section_index:
                last_index += 1
            last = window[last_index - 1]
            section = bodies[first.section_index]
            spans.append(SourceSpan(
                section.section_id,
                section.start_offset + first.start,
                section.start_offset + last.end,
                last_index - cursor,
            ))
            # Keep original punctuation, units, and inline source labels within each span.
            text_parts.append(section.text[first.start:last.end])
            cursor = last_index
        dominant = max(spans, key=lambda span: span.token_count)
        source = next(section for section in bodies if section.section_id == dominant.section_id)
        text = "\n\n".join(text_parts)
        chunk_id = sha256(json.dumps(
            [snapshot_id, chunk_size, overlap, token_start, token_end, text],
            ensure_ascii=False, separators=(",", ":"),
        ).encode()).hexdigest()
        chunks.append(Chunk(
            chunk_id, len(chunks), text, token_start, token_end,
            spans[0].start_offset, spans[-1].end_offset, tuple(spans),
            dominant.section_id, source.title,
        ))
        if token_end == len(tokens):
            break
    return tuple(chunks)


class BaselineIndex:
    """An explicit lexical baseline; these are TF-IDF vectors, not neural embeddings."""

    def __init__(self, snapshot_id, chunks, vectorizer, vectors, metadata):
        self.snapshot_id = snapshot_id
        self.chunks: tuple[Chunk, ...] = tuple(chunks)
        self.vectorizer = vectorizer
        self.vectors: csr_matrix = vectors.tocsr()
        self.metadata = metadata

    @classmethod
    def build(
        cls, snapshot_id: str, sections: Sequence[Section], *, chunk_size: int = 256, overlap: int = 64,
    ) -> BaselineIndex:
        if not isinstance(snapshot_id, str) or not snapshot_id.strip():
            raise ValueError("A stored source snapshot ID is required.")
        chunks = _make_chunks(snapshot_id, sections, chunk_size, overlap)
        vectorizer = _vectorizer()
        try:
            vectors = vectorizer.fit_transform([chunk.text for chunk in chunks]).tocsr()
        except ValueError as exc:
            raise ValueError("The source has no searchable words after common words are removed.") from exc
        metadata = {
            "method": METHOD,
            "snapshot_id": snapshot_id,
            "vector_kind": "TF-IDF word vectors",
            "similarity": "cosine",
            "chunk_size": chunk_size,
            "overlap": overlap,
            "chunk_unit": "Unicode word tokens",
            "window_rule": "fixed windows across text-bearing sections; navigation headings excluded",
            "section_rule": "most overlapping source tokens; ties use document order",
            "token_pattern": r"\b\w+\b",
            "lowercase": True,
            "ngram_range": [1, 2],
            "stop_words": "scikit-learn English list",
            "sublinear_tf": True,
            "norm": "l2",
            "scikit_learn_version": sklearn.__version__,
            "chunks": len(chunks),
            "vocabulary_size": len(vectorizer.vocabulary_),
        }
        return cls(snapshot_id, chunks, vectorizer, vectors, metadata)

    def select(self, query: str) -> Selection:
        if not isinstance(query, str) or not query.strip():
            return Selection(method=METHOD, status="no_match", reason="The synthetic question is empty.")
        query_vector = self.vectorizer.transform([query])
        if not query_vector.nnz:
            return Selection(
                method=METHOD, status="no_match",
                reason="The question has no searchable words in this source's vector vocabulary.",
            )
        scores = (self.vectors @ query_vector.T).toarray().ravel()
        position = int(np.argmax(scores))
        score = float(scores[position])
        if not math.isfinite(score) or score <= 0:
            return Selection(method=METHOD, status="no_match", reason="No chunk has a positive word-vector match.")
        chunk = self.chunks[position]
        return Selection(
            method=METHOD, status="selected", section_id=chunk.section_id,
            section_title=chunk.section_title, score=score,
            details={
                "snapshot_id": self.snapshot_id,
                "chunk_id": chunk.chunk_id,
                "chunk_position": chunk.position,
                "chunk_text": chunk.text,
                "token_start": chunk.token_start,
                "token_end": chunk.token_end,
                "start_offset": chunk.start_offset,
                "end_offset": chunk.end_offset,
                "source_spans": [asdict(span) for span in chunk.source_spans],
                "section_rule": self.metadata["section_rule"],
            },
        )

    def export(self) -> dict:
        """Return plain data, including sparse vector rows; never load a pickle."""
        return {
            "format_version": _FORMAT_VERSION,
            "snapshot_id": self.snapshot_id,
            "metadata": dict(self.metadata),
            "chunks": [asdict(chunk) for chunk in self.chunks],
            "vocabulary": {word: int(index) for word, index in self.vectorizer.vocabulary_.items()},
            "idf": self.vectorizer.idf_.tolist(),
            "vectors": {
                "data": self.vectors.data.tolist(),
                "indices": self.vectors.indices.tolist(),
                "indptr": self.vectors.indptr.tolist(),
                "shape": list(self.vectors.shape),
            },
        }

    @classmethod
    def restore(cls, payload: dict) -> BaselineIndex:
        """Restore the fitted vocabulary and weights from checked plain data."""
        try:
            if payload["format_version"] != _FORMAT_VERSION:
                raise ValueError("Unsupported baseline index format.")
            metadata = payload["metadata"]
            if metadata["method"] != METHOD or metadata["snapshot_id"] != payload["snapshot_id"]:
                raise ValueError("Baseline index metadata does not match its source.")
            if metadata["scikit_learn_version"] != sklearn.__version__:
                raise ValueError("This saved index needs its recorded scikit-learn version.")
            vocabulary = payload["vocabulary"]
            if not vocabulary or sorted(vocabulary.values()) != list(range(len(vocabulary))):
                raise ValueError("The saved vector vocabulary is invalid.")
            idf = np.asarray(payload["idf"], dtype=np.float64)
            if idf.shape != (len(vocabulary),) or not np.isfinite(idf).all() or (idf <= 0).any():
                raise ValueError("The saved word weights are invalid.")
            chunks = tuple(Chunk(**(chunk | {
                "source_spans": tuple(SourceSpan(**span) for span in chunk["source_spans"]),
            })) for chunk in payload["chunks"])
            if not chunks or [c.position for c in chunks] != list(range(len(chunks))):
                raise ValueError("The saved chunks are incomplete or out of order.")
            stored = payload["vectors"]
            if list(stored["shape"]) != [len(chunks), len(vocabulary)]:
                raise ValueError("The saved vector shape does not match its chunks and vocabulary.")
            vectors = csr_matrix((
                np.asarray(stored["data"], dtype=np.float64),
                np.asarray(stored["indices"], dtype=np.int64),
                np.asarray(stored["indptr"], dtype=np.int64),
            ), shape=tuple(stored["shape"]))
            vectors.check_format(full_check=True)
            if not np.isfinite(vectors.data).all() or (vectors.data < 0).any():
                raise ValueError("The saved vectors contain invalid values.")
            vectorizer = _vectorizer(vocabulary=vocabulary)
            # Initialize sklearn's public fitted state, then restore the real source weights.
            vectorizer.fit([""])
            vectorizer.idf_ = idf
            return cls(payload["snapshot_id"], chunks, vectorizer, vectors, metadata)
        except (KeyError, TypeError, IndexError, OverflowError) as exc:
            raise ValueError("The saved baseline index is incomplete or malformed.") from exc
