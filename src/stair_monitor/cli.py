"""Source storage and paired synthetic retrieval tests."""

import argparse
from contextlib import closing
import json
import sqlite3
from pathlib import Path

from stair_monitor.downloads import DownloadError, fetch_page
from stair_monitor.sources import OPENSTAX_SOURCE, SOURCES
from stair_monitor.storage import connect, init_db, list_guidelines, list_snapshots, register_guideline


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare and inspect public-guideline storage.")
    parser.add_argument("--db", type=Path, default=Path("data/guidelines.sqlite3"))
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="Create storage and register the candidate source addresses.")
    status = commands.add_parser("status", help="Show what has and has not been checked.")
    status.add_argument("--json", action="store_true", help="Print a machine-readable status record.")
    fetch = commands.add_parser("fetch", help="Save an official page for inspection, not import.")
    fetch.add_argument("source", choices=[source.slug for source in SOURCES])
    fetch.add_argument("--data-dir", type=Path, default=Path("data"))
    book = commands.add_parser("import-openstax", help="Store the full OpenStax contents and text.")
    book.add_argument("--data-dir", type=Path, default=Path("data/raw"))
    book.add_argument("--offline", action="store_true", help="Use only saved, hash-checked files.")
    book.add_argument("--json", action="store_true", help="Print the complete source import record.")
    retrieval = commands.add_parser("test-retrieval", help="Record both methods on synthetic questions.")
    retrieval.add_argument("--mode", choices=["offline_scripted", "live"], required=True)
    retrieval.add_argument("--limit", type=int, default=5)
    retrieval.add_argument("--model", help="Explicit Claude model ID for a live request.")
    retrieval.add_argument("--json", action="store_true", help="Print the saved paired run as JSON.")
    retrieval.add_argument("--output", type=Path, help="Also save a new JSON report file.")
    comparison = commands.add_parser("compare", help="Export a saved run as a comparison page.")
    comparison.add_argument("--run-id", help="Saved run ID; otherwise show the latest live run.")
    comparison.add_argument("--output", type=Path, required=True, help="New HTML file to write.")
    server = commands.add_parser("serve", help="Open the read-only comparison web application.")
    server.add_argument("--host", default="127.0.0.1")
    server.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)

    if args.command == "serve":
        import uvicorn
        from stair_monitor.web import create_app

        uvicorn.run(create_app(args.db), host=args.host, port=args.port)
        return 0

    if args.command == "compare":
        from stair_monitor.web import render_comparison

        if not args.db.is_file():
            print("No saved source database exists yet.")
            return 1
        try:
            with closing(sqlite3.connect(f"file:{args.db.resolve().as_posix()}?mode=ro", uri=True)) as connection:
                connection.row_factory = sqlite3.Row
                page = render_comparison(connection, args.run_id)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("x", encoding="utf-8") as file:
                file.write(page)
        except (ValueError, OSError, sqlite3.Error) as exc:
            print(f"Comparison export stopped: {exc}")
            return 1
        print(f"Comparison saved: {args.output}")
        print("Saved results only; no model call or medical answer was generated.")
        return 0

    if args.command == "test-retrieval":
        from stair_monitor.retrieval.run import run_synthetic, sample_rows

        if not args.db.is_file():
            print("Import the complete OpenStax source before running retrieval tests.")
            return 1
        try:
            with closing(connect(args.db)) as connection:
                run = run_synthetic(connection, mode=args.mode, limit=args.limit, model=args.model)
        except (ValueError, OSError, sqlite3.Error) as exc:
            print(f"Retrieval test stopped: {exc}")
            return 1
        if args.output:
            try:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                with args.output.open("x", encoding="utf-8") as file:
                    json.dump(run | {"sample": sample_rows(run)}, file, indent=2, ensure_ascii=False)
                    file.write("\n")
            except OSError:
                print("Run is saved in SQLite; the extra report file could not be written or already exists.")
        if args.json:
            print(json.dumps(run | {"sample": sample_rows(run)}, indent=2, ensure_ascii=False))
        else:
            print(f"Saved run: {run['run_id']} ({run['mode']}; {run['status']})")
            print(run["settings"]["mode_notice"])
            for row in sample_rows(run):
                baseline = row["baseline_section"] or row["baseline_status"]
                toc = row["toc_section"] or row["toc_status"]
                print(f"{row['question_id']}: baseline = {baseline}; ToC = {toc}")
            print("View saved results with compare or serve. No medical answers are generated.")
        return 0

    if args.command == "import-openstax":
        from stair_monitor.openstax import import_openstax
        from stair_monitor.openstax_downloads import SourceDownloadError

        try:
            with closing(connect(args.db)) as connection:
                result = import_openstax(connection, args.data_dir, offline=args.offline)
        except (SourceDownloadError, ValueError, OSError, sqlite3.Error) as exc:
            print(f"OpenStax import stopped: {exc}")
            print("No partial section map was saved. Check the saved source files and storage.")
            return 1
        if args.json:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            print("Complete OpenStax textbook contents and text are stored.")
            print(f"Text-bearing sections: {result['module_sections']}")
            print(f"Navigation headings: {result['navigation_groups']}")
            print(f"Sections rows: {result['section_rows']}; contents rows: {result['toc_rows']}")
            print(f"Publication date: {result['publication_date']}")
            print("This is an educational textbook, not a treatment guideline.")
            print("This import does not run retrieval.")
            if result.get("record_warning"):
                print(result["record_warning"])
        return 0

    if args.command == "fetch":
        source = next(source for source in SOURCES if source.slug == args.source)
        try:
            downloaded = fetch_page(source, args.data_dir)
        except DownloadError as exc:
            print(str(exc))
            return 1
        except OSError:
            print("Could not save the page. Check the data path and its write permissions.")
            print("No guideline sections were imported.")
            return 1
        print(f"Saved page: {downloaded.archive_path}")
        print(f"Download record: {downloaded.record_path}")
        print("Publication date, contents, and reuse terms are not checked yet.")
        print("No guideline sections were imported.")
        return 0

    if args.command == "status" and not args.db.is_file():
        print("No storage file exists yet. Run 'stair init' first.")
        return 1
    try:
        with closing(connect(args.db)) as connection:
            if args.command == "init":
                init_db(connection)
                for source in (*SOURCES, OPENSTAX_SOURCE):
                    register_guideline(
                        connection,
                        slug=source.slug,
                        title=source.title,
                        publisher=source.publisher,
                        source_url=source.url,
                    )
                print(f"Storage prepared: {args.db}")
                print("Candidate addresses are registered. This does not verify their contents.")
                return 0
            guidelines = list_guidelines(connection)
            snapshots = list_snapshots(connection)
    except (sqlite3.Error, ValueError, OSError):
        print("Could not read or prepare storage. Check the path and database format.")
        return 1

    if args.json:
        print(json.dumps({"guidelines": guidelines, "snapshots": snapshots}, indent=2))
    else:
        for guideline in guidelines:
            saved = [row for row in snapshots if row["guideline_slug"] == guideline["slug"]]
            checked = [row for row in saved if row.get("verified_at")]
            print(guideline["title"])
            print(f"  Official address: {guideline['source_url']}")
            print(f"  Saved versions: {len(saved)}; verified versions: {len(checked)}")
            if not checked:
                print("  Publication date and full contents: not verified.")
            else:
                latest = checked[-1]
                print(f"  Publication date: {latest.get('publication_date_note') or latest['publication_date'] or 'unknown'}")
        print("Retrieval methods are available through test-retrieval.")
        print("The comparison view is available through compare or serve.")
        print("Answer generation is not built yet.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
