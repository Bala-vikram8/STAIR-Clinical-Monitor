"""Storage commands must not turn unverified addresses into accepted sources."""

import json

from stair_monitor.cli import main


def test_initialization_is_repeatable_and_does_not_invent_source_details(tmp_path, capsys):
    path = str(tmp_path / "guidelines.sqlite3")
    assert main(["--db", path, "init"]) == 0
    assert main(["--db", path, "init"]) == 0
    capsys.readouterr()
    assert main(["--db", path, "status", "--json"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert {row["slug"] for row in status["guidelines"]} == {
        "cdc-sti", "cdc-opioid", "openstax-anatomy-physiology",
    }
    assert status["snapshots"] == []
    assert main(["--db", path, "status"]) == 0
    output = capsys.readouterr().out
    assert "not verified" in output
    assert "not built yet" in output


def test_status_without_database_does_not_create_one(tmp_path, capsys):
    path = tmp_path / "absent.sqlite3"
    assert main(["--db", str(path), "status"]) == 1
    assert not path.exists()
    assert "Run 'stair init' first" in capsys.readouterr().out


def test_download_write_failure_has_a_plain_message(monkeypatch, capsys):
    def failed_save(*args, **kwargs):
        raise OSError("unwritable local folder")

    monkeypatch.setattr("stair_monitor.cli.fetch_page", failed_save)
    assert main(["fetch", "cdc-sti"]) == 1
    output = capsys.readouterr().out
    assert "write permissions" in output
    assert "No guideline sections were imported" in output
