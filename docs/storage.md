# Guideline storage

Recorded on October 30, 2026. The implemented schema is in [storage.py](../src/stair_monitor/storage.py); tests use invented text in [test_storage.py](../tests/test_storage.py).

## Current database: OpenStax text stored

Checked on October 31, 2026. The [dated import check](../reports/openstax-import-checks.json) records one OpenStax source snapshot, 232 section rows, and 232 contents rows. These include 198 full text-bearing modules and 34 navigation headings. Every title is resolved. Earlier CDC candidates still have no stored content. The table name `guidelines` is retained, but the OpenStax source is explicitly a textbook.

## What each table means

| Table | What it keeps |
| --- | --- |
| `guidelines` | A candidate source ID, title, publisher, and official address. Registration is not verification |
| `snapshots` | Original source files bundled together, their hash, retrieval time, source address, parsed text, parser version, source dates, date evidence, reuse terms, and source-check status |
| `sections` | Original headings, full parent paths, source links, own text, and exact character positions in the saved parsed text |
| `toc_entries` | Original contents order, titles, link destinations, parent relationships, and links to stored sections |

Dates remain empty when unknown. Publication and page-update dates are different fields. A verified record needs a UTC verification time, evidence for the dates or their absence, and checked reuse terms with their source address. This is a record of a source check, not clinical validation or proof the advice is current.

OpenStax's publication-date value is `NULL`; `publication_date_note` stores **unknown – publisher content** exactly. Schema version 2 adds this label field without overwriting earlier records.

## Separate retrieval records

The approved retrieval work adds `retrieval_indexes`, `synthetic_runs`, and `retrieval_results`. They link to the original source snapshot without changing its sections or contents. The source schema version remains unchanged; the retrieval tables are additive.

The index keeps safe JSON values for chunks, source spans, fitted word-vector weights, and configuration. A run keeps its synthetic questions, question-file hash, settings, explicit live or scripted mode, and one outcome per method per question. Outcomes retain selected section IDs/titles or explicit no-match, invalid, blocked, or error states. Missing ToC mode provenance is rejected rather than inferred as live.

These are development-test records. They contain no generated treatment answers, model credentials, or patient data. See the [retrieval guide](retrieval.md) and [dated checks](../reports/retrieval-checks.json).

## Section boundaries

The storage interface expects each section to own only its own body text, excluding text assigned to child sections. A parent's heading path still connects it to its children. This prevents child text from being counted again inside the parent.

Offsets count Python text characters in the exact saved normalized text. The end offset is excluded. These are not raw HTML byte offsets or future embedding token offsets. Sections must occur in document order and cannot overlap. Their stored text must match the indicated slice exactly.

The OpenStax parser keeps module subheadings inline, along with tables, notes, glossary entries, units, mathematical scripts, and source links. Groups hold their own heading text only. Separators are two newline characters between saved sections. Original bytes remain available alongside the normalized text. All stored ranges were checked against the saved textbook. Image binaries and linked videos remain external; their available descriptions and references remain in text.

The contents hierarchy is stored separately from the body heading hierarchy. A source contents list may omit body subheadings. It must point to existing sections; it cannot stand in for checking the actual source. Repeated section titles are allowed when their IDs and full paths are distinct. IDs are scoped to a saved copy.

## Version and write checks

A snapshot ID depends on the guideline ID, original file hash, and parser version. Repeating an identical import returns the same saved copy. The original retrieval record is retained. Changed source bytes or a new parser version create another copy.

The same source bytes and parser version cannot silently replace text, section maps, date evidence, or verification details. A mismatch raises an error. If review changes after an initial unverified import, record a new parser/review version rather than rewriting an old experiment's source record. This is a deliberately simple version rule for the initial project.

Writes use a database savepoint: if a reference or section check fails, none of that import remains. Foreign-key checks are enabled on every connection. Missing parents, broken contents links, duplicate IDs, invalid UTC timestamps, and out-of-bounds text positions are rejected.

The snapshot keeps original bytes in SQLite as well as the external archive path. A missing archive file does not erase the saved original. Old snapshots remain available when a new one is added. The application functions avoid updating old snapshots; SQLite itself is a local file, not a tamper-proof audit service.
