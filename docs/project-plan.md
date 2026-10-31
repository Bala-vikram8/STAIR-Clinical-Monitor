# Build plan

Prepared on October 30, 2026. This is a proposal, not evidence that the software works. Decisions and assumptions are recorded in [assumptions.md](assumptions.md).

## Approval boundary

The full OpenStax source is stored. The user approved the live Claude run and simple comparison view after the retrieval checkpoint. Both are complete; see [the retrieval guide](retrieval.md) and [dated validation](../reports/live-comparison-checks.json). The displayed ToC choices are actual live responses, not scripted replies. Answer generation and a held-out final benchmark have not started and are not implied by this approval.

Each later stage needs a new **“approved, continue”** from the user. Approval covers the next stage only. A failed check must be diagnosed before that stage can be called complete. Changes to the agreed scope must be recorded rather than silently made.

## Public source plan

Proposed starting sources:

| Guideline | Official location | Status |
| --- | --- | --- |
| CDC sexually transmitted infection treatment guidelines | https://www.cdc.gov/sti/hcp/treatment-guidelines/index.html | Paused by user instruction; previous proxy failure recorded; do not retry |
| CDC guideline for prescribing opioids for pain | https://www.cdc.gov/mmwr/volumes/71/rr/rr7103a1.htm | Paused by user instruction; chained command never sent this request |
| OpenStax anatomy textbook | https://github.com/openstax/osbooks-anatomy-physiology | Primary source; complete contents and linked textual bodies stored at a fixed publisher revision. Publication date: unknown – publisher content. Educational textbook, not a treatment guideline |

These links identify proposed sources. Requests and their outcomes are recorded in [the source check](source-verification.md). Neither guideline is being described as current clinical advice. Do not claim coverage of all clinical guidance.

Use official, freely accessible text. Preserve its warnings, population limits, headings, tables, and units. Check linked corrections and updates before accepting a source. If a source cannot be read, parsed faithfully, or reused as planned, report that before substituting another source.

For each accepted source, keep its title, publisher, URL, edition, stated update date, retrieval time in UTC, reuse terms, and a file hash that identifies the saved copy. If a date is absent, say unknown. Store the original file outside source control and make its hash visible in the run record. Make the download and rebuild steps repeatable.

The stage B environment reports package-download access but no custom destination domains or API secret bindings. A draft adds only the official CDC hosts; this does not apply it to the running environment. Verify actual access before use. Future stages must check model-download hosts and Anthropic separately. Request any missing credentials through environment settings, never through chat or a tracked file. No settings were changed in stage A.

## Sections and traceable sources

Build a section list from the guideline's own table of contents and heading structure. Keep the complete table of contents for every guideline in the comparison. Check it against the saved body text; fail import on missing or ambiguous links instead of silently dropping sections.

Each section has a stable ID, original title, full heading path, source link or anchor, and the location of its text in the saved document. Full paths distinguish repeated titles such as “Treatment.” Explain the rule for whether a parent includes its child sections, and test that rule before import is accepted. Keep table cells and footnotes with the statements they qualify.

For OpenStax, each publisher module is one text-bearing section; internal subheadings remain inline. Part and chapter rows store only their own heading. No child bodies are repeated inside parent rows. This checked source is shared by both retrieval methods. The source snapshot is kept unchanged by retrieval runs.

## The baseline

Split the saved guideline body into fixed text windows with overlap. These are regular windows, not random cuts. Do not use the answer key to choose their boundaries.

The implemented starting baseline fits TF-IDF word vectors locally using a locked scikit-learn version, then ranks by cosine similarity. This is an explicit word-based vector baseline, not evidence about neural embedding methods. Settings and fitted vectors are stored in SQLite. Direct similarity search fits this corpus without a separate search service. A later change to neural embeddings would need its own recorded model, setup, and run.

Record every chunk's source positions, including all sections touched when a chunk crosses a heading. For the main section-selection score, use the section contributing the most text tokens to the highest-ranked chunk. Break a tie by document order. Keep the full overlap map visible so this rule can be audited. This mapping is only for scoring; the baseline answer still uses retrieved chunks rather than substituted full sections.

Freeze chunk size, overlap, embedding model revision, text preparation, similarity calculation, and number of retrieved chunks before the final test. Use only development questions to choose them. Record these choices even if their values seem obvious.

## The table-of-contents approach

Show Claude the full table of contents of the frozen corpus, with source names, exact titles, heading paths, and section IDs. Give it the question and ask for an exact section title and ID, or an explicit refusal if no section fits. It does not see section bodies or the answer key while choosing.

Validate the response against the saved section list. Unknown IDs, title mismatches, and ambiguous titles are invalid outputs. Log them as such. Do not silently guess a replacement. Pull only the selected section's saved text after validation succeeds.

Check that the complete table of contents fits the selected model's input limit. If it does not fit, stop and report that design limit. Do not quietly remove headings or replace the full table of contents with a search shortlist.

## Answers and safety limits

Use the same pinned Claude answer model, answer prompt, generation settings, and maximum source-text budget for both approaches. Report the actual amount of text provided. Full sections and chunks are different evidence; do not claim they are identical inputs.

Choose and test a shared rule for overlong evidence before the final run. Mark shortened context explicitly and save the exact text provided to the answer model. Missing evidence must lead to an explicit limit or refusal rather than an invented treatment. Do not hide a context-limit failure by changing the source after seeing test results.

Require a section citation and supporting quotation for factual answers. The quotation must be checked against the supplied text. A citation alone does not prove a claim is supported.

Treat guideline text as source material, never as instructions to the application. Keep the API key out of browser code, logs, and the database. Send only reviewed synthetic questions and public guideline text to the API. Never add patient records to prompts, fixtures, logs, screenshots, or results.

The initial demo accepts approved synthetic question IDs rather than arbitrary free text. If either approach refuses, returns an invalid section, or finds no usable evidence, skip factual answer generation and display the reason.

## Questions and answer key

Prepare the answer key before running either system. Each question records its synthetic origin, source snapshot, accepted section IDs, supporting passages, answerable status, and review notes.

The main comparison uses questions answerable from a single section. Start with synthetic paraphrases, not copied headings. Include difficult but in-scope questions and questions with no answer in the saved corpus. Avoid patient-identifying details even in examples.

Keep development questions separate from final test questions, preferably by source section. Record any unavoidable shared section. Do not tune prompts, chunking, or model settings on final questions. If a final question is corrected later, version the question set and rerun both systems together.

Questions that require multiple sections form a separately labelled extension. Do not mix them into the main single-section score or silently label a partially supported answer as correct.

No question count, sample-size justification, or target score is set yet. Set and document them in stage D before the final run. A small portfolio test cannot establish clinical safety or broad effectiveness.

## Measurements

The unit for retrieval scores is a question, not a retrieved chunk. Score both approaches on the same final questions and show the counts behind every rate.

| Measure | Rule |
| --- | --- |
| Right-section rate | Answerable questions whose selected section is in the prepared accepted set, divided by all answerable questions |
| Wrong-section rate | Answerable questions whose selected section is outside that set, divided by all answerable questions |
| Refusal rate | Answerable questions with an explicit refusal or no evidence, divided by all answerable questions |
| Invalid-selection rate | Answerable questions with an unusable section choice, divided by all answerable questions |
| Faithfulness | Reviewed factual claims supported by the actual supplied text, divided by all reviewed factual claims |

Give each answerable question exactly one retrieval outcome: right, wrong, refusal, or invalid. A system that crashes or times out produces a separate run error. Show those errors against the full planned question count, and do not present an incomplete run as a completed comparison.

For questions with no answer in the saved source, report correct refusals, attempted answers, invalid selections, and unsupported claims separately. They do not belong in the answerable-question section-score denominator.

For faithfulness, split answers into checkable factual claims. Save a review decision and supporting passage for every claim. Review doses, units, treatment choices, exceptions, and population limits explicitly. A statement that resembles the source but changes its unit or condition is not supported. Show dangerous unsupported claims as their own count.

Use a written review guide and human review for the reported faithfulness result. A future model-based judge can assist, but its scores must be labelled estimates and kept separate. Do not present an AI-only review as clinical validation. Without a human review, display faithfulness as “not reviewed.”

A refused or empty answer has no factual claims: its faithfulness is not applicable, not a perfect score. Show answer and claim counts, answer coverage, and the number of questions where both approaches produced answers. This makes clear when a higher score comes from answering fewer questions.

Show paired outcomes on each question, not just averages. Keep answer usefulness and clinical correctness distinct from faithfulness: repeating a stale source faithfully does not make an answer safe.

## Planned application

- Python 3.11 or newer, FastAPI, SQLite, Anthropic Claude, simple server-rendered HTML, and Pytest, as requested by the user on October 30, 2026.
- A command to import accepted public sources and build both indexes.
- A command to run the same frozen question set through both systems.
- A local results page with run settings, source dates, side-by-side counts, per-question selections, supplied text, answers, citations, and review notes.
- SQLite records for guidelines, sections, chunks and vectors, question-set versions, questions, accepted sections, runs, retrieval choices, generated answers, and claim reviews. Preserve source and settings links so old results cannot silently change when a guideline is updated.
- Dependency and model version pins, a sample configuration containing names only, and repeatable setup instructions. Live API tests remain separate from ordinary offline tests and must be labelled clearly.

## Stages and completion checks

| Stage | Deliverable | Check before stopping for approval |
| --- | --- | --- |
| A — Design | README, plan, and assumptions | Documents agree; no made-up results or deployments; next-stage work has not started |
| B — Public sources and storage | Dependency setup, SQLite schema, source download/import, complete section map | Official sources and dates verified; imports repeat safely; saved text, full heading list, tables, and citations checked; parsing and storage tests pass |
| C — Retrieval (current approval) | Fixed-window vector baseline, Claude section picker, paired synthetic development tests | Offline tests cover cross-section chunks, repeated headings, invalid output, missing sources, context limits, and refusal; live Claude validation is reported separately and currently blocked |
| D — Future answers and frozen comparison | Shared answer writer if approved, final questions, answer key, fixed settings, run command | No final-test tuning; both systems finish the same test set; results and errors are saved; claim reviews are completed or clearly marked pending |
| E — Results page and handoff | HTML dashboard, dated run report, README results, startup instructions | Page matches saved run records; meaningful API/page smoke checks and relevant tests pass; every README number has a dated source; limits and unreviewed items are visible |

Do not start the next row until the user says **“approved, continue.”** When a stage needs source access or credentials, finish its independent work and explain the exact remaining prerequisite. Never invent a passing check to close the stage.
