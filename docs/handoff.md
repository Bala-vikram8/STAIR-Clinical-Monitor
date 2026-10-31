# Handoff

Prepared on October 31, 2026. This stage changes documentation only.

## Finished

- Imported the public OpenStax textbook, resolved its full contents hierarchy, and saved section text and source records in SQLite.
- Built fixed-chunk TF-IDF vector search and a Claude picker that receives the full ToC and returns an exact section ID and title.
- Ran the same five synthetic questions through both methods in live mode with `claude-opus-5-5`. The baseline matched 4/5 prepared sections; ToC retrieval matched 5/5. Source and date: [live run](../reports/retrieval-live-results.json), recorded October 31, 2026, and [validation](../reports/live-comparison-checks.json).
- Built a read-only FastAPI/HTML comparison page. Opening it makes no model calls. Earlier scripted replies and failed attempts remain separate history.

## Intentionally not built

- No answer generator, dosage advice, treatment recommendations, patient intake, or care-facing API.
- No real clinical use, hospital or customer deployment, or clinical validation.
- No held-out final benchmark or answer-faithfulness measurement. These development results do not establish broad performance or safety.

Only public textbook content and synthetic questions are used. OpenStax is educational text, not a treatment guideline. Publication date remains **unknown – publisher content**. Images and videos are external; their available descriptions and references are kept. Attribution and reuse terms are in [source verification](source-verification.md). Codex was the build partner.

## Reviewer reproduction

For the exact recorded results, open [the saved comparison](../reports/comparison.html), [comparison data](../reports/comparison-data.json), and [live run](../reports/retrieval-live-results.json). These saved files need no API key. Check the question-file hash, source snapshot, returned model ID, and live labels in the run record.

To run it again from a fresh checkout, use the existing Linux cloud environment or a compatible setup, with Python and `uv`, then run from the repository root:

```sh
uv sync --frozen --cache-dir .cache/uv
.venv/bin/stair init
.venv/bin/stair import-openstax
.venv/bin/python -m pytest -q
.venv/bin/stair test-retrieval --mode live --limit 5 --model claude-opus-5-5
.venv/bin/stair compare --output reports/reviewer-comparison.html
```

The live command needs an injected `ANTHROPIC_API_KEY` and access to `api.anthropic.com`. Configure the key securely; never paste it into chat or save it in the repository. The source import needs the official publisher files on `raw.githubusercontent.com`. Do not retry CDC or WHO downloads.

The checkout includes `data/guidelines.sqlite3`; raw-download caches remain ignored. The import command rebuilds the publisher cache and enables the cached-source preservation check as well as the database integration checks. If that cache already exists, `import-openstax --offline` reuses its hash-checked files. Use a fresh export filename on repeated runs. `stair serve` opens the read-only web app at the address printed by the server.

Keep the lockfile, pinned source revision, and synthetic question fixture unchanged for a comparable rerun. Hosted-model defaults and future availability can change, so a new live response is not guaranteed to reproduce the saved choices. Offline scripted replies test wiring only; they cannot reproduce live Claude performance.

No features were added for handoff. Stop here before any new stage.
