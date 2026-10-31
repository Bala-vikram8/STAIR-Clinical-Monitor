# Local setup

Updated on October 31, 2026. Run these commands from the existing checkout at `/workspace/STAIR-Clinical-Monitor`. Each cloud task already has an isolated workspace; do not make a Git worktree unless the user asks.

## Install the Python dependencies

Use Python 3.11 or newer and `uv`. The cloud environment used Python 3.12.14 with uv 0.12.23 during setup. The Python requirement comes from the user's project request on October 30, 2026; the observed versions come from the setup commands on that date.

```sh
uv sync --frozen --cache-dir .cache/uv
```

`pyproject.toml` lists dependencies and `uv.lock` fixes their versions. The cache stays in the writable checkout because the default user cache may be read-only in the command sandbox. Keep TLS verification enabled and keep the environment's proxy and trust settings. There is no need for an Anthropic key for installation, storage, or these offline tests. Do not request or put an API key in a file for this stage.

## Create and inspect storage

```sh
.venv/bin/stair init
.venv/bin/stair status
.venv/bin/stair status --json
```

Initialization can be repeated. It creates `data/guidelines.sqlite3`, migrates older local storage safely, and registers OpenStax plus the earlier CDC candidate addresses. It does not download a source. The prepared database now contains the complete OpenStax contents and section text; a new empty database needs the import command below.

Use another local database if needed:

```sh
.venv/bin/stair --db /tmp/stair-check.sqlite3 init
.venv/bin/stair --db /tmp/stair-check.sqlite3 status
```

No web server needs to start for this storage stage. Processes are not assumed to survive a published environment snapshot.

## Import or check the complete OpenStax source

For a new local database and cache, run:

```sh
.venv/bin/stair import-openstax
```

This downloads the publisher's fixed contents file, README, licence, and every linked section file using bounded requests. It does not fetch the large image archive, retry CDC or WHO, call an AI model, or write retrieval code. Any missing or invalid required section stops the import before real section rows are saved.

The prepared cloud environment already has all files. Check and repeat the import without network requests:

```sh
.venv/bin/stair import-openstax --offline
.venv/bin/stair status
```

Saved files must pass their recorded hash checks. Repeating the import retains the same source snapshot and section rows. Cache, original files, deterministic source ZIP, and the local import record are under `data/raw/openstax/`. The database also contains the complete original ZIP bytes. A failure to write the extra local import record is reported separately after a successful database import; it does not falsely report that the stored source is missing.

The displayed publication date is **unknown – publisher content**. The database keeps `publication_date` empty and saves that exact label in `publication_date_note`. File revision and download dates are not book publication dates.

The [dated import check](../reports/openstax-import-checks.json) gives actual row counts and sample titles. Images and videos are external; the text keeps their available descriptions and references. This is an educational textbook import, not clinical validation.

## CDC downloads are paused

The user has instructed us not to retry CDC. The current network policy blocks CDC. An older configuration draft proposes `www.cdc.gov` and `cdc.gov`; applying it is no longer a prerequisite for the alternative-source investigation. Do not run the CDC fetch commands for this work.

The older `stair fetch` command only knows the CDC candidates and remains paused. Use `stair import-openstax` for the selected textbook. The [source verification record](source-verification.md) preserves the exact historical CDC and WHO errors; they were not retried during this import.

The contents and text-import milestone is complete. The user subsequently approved retrieval methods and paired synthetic tests. Source fetches are still paused for CDC and WHO; they are not needed by retrieval.

The SQLite database at `data/guidelines.sqlite3` is included in Git. Other files under `data/`, the virtual environment, caches, and `.env` files remain ignored. Do not put patient information in any of them. The original source bytes are stored in SQLite as well as the local ZIP, so the checked-in database retains the original source even without the raw-download cache. The import command can rebuild that cache from the publisher.

## Run the tests

```sh
.venv/bin/python -m pytest -q
```

Tests use temporary SQLite databases and invented source examples through a local test client. A separate preservation check can use an already cached public OpenStax sample. Tests do not contact CDC or Anthropic. They cover storage migrations, parsing, source status, download failures, complete imports, and repeatability; they do not validate medical content or retrieval quality. Actual whole-source checks are recorded separately in the dated import report.

## Run the retrieval checks

```sh
.venv/bin/stair test-retrieval --mode offline_scripted --limit 9
.venv/bin/stair test-retrieval --mode live --limit 5
```

The first command runs actual word-vector search and explicitly scripted ToC test replies on the same synthetic questions. It is a wiring test, not Claude performance evidence. The second uses the real Claude adapter and records blocked outcomes if API configuration is missing. Both save their mode and outcomes in SQLite. See the [retrieval guide](retrieval.md) for settings, limitations, code structure, and secure API configuration.

## What is not built yet

The comparison view is available. Start it with `.venv/bin/stair serve --host 127.0.0.1 --port 8765`, or export a new HTML file with `.venv/bin/stair compare --output reports/new-comparison.html`. The app displays saved results only; opening it does not call Claude. Its default is the latest live run, with failures visible.

Live Claude retrieval has been verified using the configured `claude-opus-5-5` model and injected environment key. The API requires the temperature field to be omitted; the code records that provider defaults apply. No answer generator, held-out benchmark, or care-facing API exists. Stop after this approved comparison view and wait for the next stage approval.
