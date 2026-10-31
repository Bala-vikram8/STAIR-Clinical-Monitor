# Retrieval methods and synthetic tests

Updated on October 31, 2026. The user approved live retrieval with `claude-opus-5-5` and the simple comparison view. The live run completed and the view now shows actual responses. This work selects source sections only. It does not write medical answers.

## Code structure

```text
src/stair_monitor/retrieval/
  types.py       shared source and selection records
  corpus.py      require a complete, checked stored source
  baseline.py    fixed chunks, word vectors, and cosine search
  toc.py         full-ToC prompt, Claude client, and exact choice checks
  store.py       SQLite index and paired run records
  run.py         the same synthetic questions through both methods
fixtures/
  synthetic-retrieval-questions.json   development questions and source evidence
  scripted-toc-replies.json           explicitly scripted offline test replies
tests/
  test_baseline.py
  test_toc.py
  test_retrieval_store.py
  test_retrieval_integration.py
```

The [baseline](../src/stair_monitor/retrieval/baseline.py), [ToC picker](../src/stair_monitor/retrieval/toc.py), and [paired runner](../src/stair_monitor/retrieval/run.py) are separate so a test double cannot silently replace the live Claude client.

## Baseline: fixed chunks and vector search

The baseline uses **TF-IDF word vectors**, fitted locally with the locked scikit-learn version. Cosine similarity ranks the chunks. It is a word-based baseline; its scores do not establish the quality of a neural embedding system or all RAG systems.

Fixed design choices for this development stage, recorded before running the paired questions:

- Windows of 256 Unicode word tokens with 64 tokens of overlap. These are word tokens counted with the saved regular expression, not Claude tokens.
- Continuous windows across the 198 text-bearing source modules; the 34 navigation-only headings are excluded from the vector index.
- Single words and adjacent word pairs, lowercase text, the scikit-learn English common-word list, logarithmic term weighting, and normalized vectors.
- Return the highest-ranked chunk. Attribute it to the source section with the most overlapping word tokens; ties use document order. Save every contributing section span, including cross-boundary chunks.
- Keep original punctuation and units inside chunk spans. The saved chunk text is reconstructed from those original ranges, with separators between sections.

The actual source produced 3,344 chunks. Source, chunk settings, vocabulary, word weights, and sparse vector values are stored as plain JSON in SQLite. No executable pickle files are loaded. Reusing the saved index preserves its source link and configuration. These settings have not been tuned against a held-out question set.

Empty questions or questions with no matching vocabulary produce `no_match`. A positive similarity score only identifies shared text; it does not establish that the source supports the question. In particular, the baseline can select an irrelevant section for an unsupported treatment question. No treatment answer is generated.

## STAIR-inspired: full contents and an exact title

Claude receives the same synthetic question plus every one of the 232 stored contents entries, including full parent paths. Navigation headings remain visible for context but cannot be selected because they contain no body text. Section bodies, expected answers, and supporting quotations from the test key are not sent.

The model must return an exact saved section ID and title, or an explicit `no_match`. Unknown IDs, mismatched titles, navigation-only choices, malformed JSON, and unfinished responses are recorded as invalid. There is no fuzzy title repair, silent retry, or fallback to the answer key.

The user selected `claude-opus-5-5`. That exact requested and returned model ID is recorded in the successful [live run](../reports/retrieval-live-opus-5-5-success.json). `STAIR_CLAUDE_MODEL` can select another explicit model ID; no automatic model substitution is made.

The live adapter asks Anthropic to count the exact full prompt before generation. The configured input budget is 20,000 tokens, with an output limit of 256 tokens, a 30-second request timeout, and no automatic retries. Temperature is omitted so the provider default applies. The first real API attempts returned HTTP 400 with the message “\`temperature\` is deprecated for this model.” Removing that field fixed the requests; the regression test checks that it stays omitted. Earlier failed runs remain in SQLite.

The successful prompts used 17,723 to 17,736 input tokens according to the provider's count endpoint, with all 232 contents entries retained. Exact per-question counts and generation settings are in the live run. The limits are bounded-run design choices, not performance targets. Provider defaults and future model changes can affect repeatability even with the saved model name.

## Same questions, different execution modes

The [question fixture](../fixtures/synthetic-retrieval-questions.json) contains 9 synthetic development questions. Each supported question has a prepared source section and an exact supporting excerpt. One question deliberately asks for treatment guidance outside this anatomy textbook. It supplies no dose or treatment answer. The fixture is development material, not a held-out benchmark.

Both methods receive only each question's text. The runner stores the answer key alongside the results for inspection but does not pass it to either retrieval method.

Two modes are kept separate:

| Mode | Baseline | ToC method | What the record establishes |
| --- | --- | --- | --- |
| `offline_scripted` | Actual vector search over the imported book | Fixed replies from the separate scripted fixture, passed through the real prompt and validation code | Integration wiring and error handling; not Claude retrieval accuracy |
| `live` | Actual vector search over the same saved index | Real Claude adapter, or a recorded blocked/error outcome | Live model results only if an API response actually completes |

The earlier offline run completed all 9 questions and saved 18 method outcomes. The earlier live-readiness run saved blocked Claude outcomes. Those records remain historical evidence, not real model predictions.

The new live run completed the first 5 frozen synthetic questions, saving 10 paired method outcomes. Every row is labelled `live`. Claude returned 5 valid source choices with the actual response model ID `claude-opus-5-5`; all matched the prepared development answer key. The word-vector baseline matched 4 of those 5 keys. This is a small development smoke test, not a held-out benchmark or clinical validation. The baseline is TF-IDF rather than a neural embedding system.

See the [successful live run](../reports/retrieval-live-opus-5-5-success.json), [comparison page](../reports/comparison.html), [dated current validation](../reports/live-comparison-checks.json), and [complete comparison data](../reports/comparison-data.json). The earlier [offline run](../reports/retrieval-offline-run.json), [readiness attempt](../reports/retrieval-live-readiness.json), and [retrieval validation](../reports/retrieval-checks.json) are kept separately. Question-file hashes show that the successful run used the same frozen questions. The live run has no scripted-response file hash.

## Run the commands

From the existing project checkout:

```sh
uv sync --frozen --cache-dir .cache/uv
.venv/bin/stair test-retrieval --mode offline_scripted --limit 9
.venv/bin/stair test-retrieval --mode live --limit 5
.venv/bin/python -m pytest -q
```

`--output` writes a new JSON report file. Runs are saved in SQLite first; a report-file failure does not hide a successfully saved run. Report files are not silently overwritten. The command takes synthetic fixture questions only and has no free-text patient input option. Each run is limited to at most 10 questions; the default is 5.

Full-source integration tests use a temporary copy of the imported database. If the source has not been imported, those checks are explicitly skipped; the ordinary parser and retrieval unit tests still run. The current validation ran the full-source checks, not a zero-test substitute.

## Comparison view

The read-only FastAPI app uses the saved SQLite results. Its default is the latest live run, including failures. It never silently replaces failed live responses with offline test replies. Every row and method carries its execution mode, and a “live API response” label requires saved response evidence.

```sh
.venv/bin/stair serve --host 127.0.0.1 --port 8765
.venv/bin/stair compare --output reports/new-comparison.html
```

The HTML export and web route use the same renderer. The app has only read routes for the comparison, JSON data, and health check. It accepts no patient question, creates no model request on page load, and exposes no answer endpoint.

## API configuration and stage boundary

The published environment now supplies the injected Anthropic key and requested model, and API access was verified through the completed live responses. Keep credentials in secure environment settings. Never save keys in code, reports, the database, or chat. Any key exposed in chat must be revoked and replaced.

The approved live run and comparison view are complete. Answer generation, a held-out final benchmark, faithfulness review, and clinical use remain outside this work. Stop here and wait for the user's next stage approval.
