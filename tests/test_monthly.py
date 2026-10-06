import gzip
import json
import shutil
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import entity
from test_collector import FakeClient

from brreg_fetcher.client import SourceError
from brreg_fetcher.collector import collect
from brreg_fetcher.export import export_release, restore_asset, restore_checkpoint
from brreg_fetcher.state import State
from scripts import monthly_run, release


def test_seed_stays_frozen_across_days_and_month_boundary(state):
    client = FakeClient()
    options = {"workers": 1, "max_entities": 1, "account_client_factory": lambda: client}
    first = collect(state, client, date(2026, 10, 31), **options)
    assert first["cycle"] == "2026-10" and not first["complete"]
    second = collect(state, client, date(2026, 11, 1), **options)
    assert second["complete"] and second["cycle"] == "2026-10"
    assert second["seed_date"] == "2026-10-31" and client.downloads == 1
    third = collect(state, client, date(2026, 11, 2), **options)
    assert third["cycle"] == "2026-11" and client.downloads == 2
    assert third["attempted"] == 1 and not third["complete"]
    # The new month refetches even unchanged years/IDs and never mixes old current rows.
    assert third["new_ids"] == 0
    assert state.summary()["current_filings"] == 1
    assert state.summary()["historical_filings"] == 2


def test_incomplete_cycle_cannot_be_reseeded(state):
    state.start_cycle([entity()], "2026-10-01")
    with pytest.raises(SourceError, match="Finish the active month"):
        state.start_cycle([entity("974760673")], "2026-11-01")
    assert [row["orgnr"] for row in state.todo()] == ["923609016"]


def test_failed_new_download_keeps_previous_month_intact(state):
    client = FakeClient()
    collect(state, client, date(2026, 10, 1), account_client_factory=lambda: client)

    def broken_download():
        yield entity(year="2026")
        raise SourceError("download truncated")

    with pytest.raises(SourceError):
        state.start_cycle(broken_download(), "2026-11-01")
    assert state.get("cycle") == "2026-10"
    assert state.summary()["current_filings"] == 2
    assert state.summary()["queued_entities"] == 0


def test_unresolved_errors_hold_month_open(state):
    client = FakeClient()
    client.fail = True
    options = {"workers": 1, "account_client_factory": lambda: client}
    collect(state, client, date(2026, 10, 1), **options)
    report = collect(state, client, date(2026, 11, 1), **options)
    assert report["cycle"] == "2026-10" and not report["complete"]
    assert client.downloads == 1 and report["queued_entities"] == 2


def test_minimal_checkpoint_and_seed_round_trip(state, tmp_path):
    state.start_cycle([entity()], "2026-10-01")
    snapshot = tmp_path / "seed.gz"
    snapshot.write_bytes(gzip.compress(json.dumps([entity()]).encode()))
    out = tmp_path / "checkpoint"
    manifest = export_release(
        state, out, checkpoint_only=True, snapshot_path=snapshot, max_asset_bytes=512
    )
    assert manifest["kind"] == "checkpoint" and manifest["cycle"] == "2026-10"
    assert set(manifest["assets"]) == {"checkpoint.sqlite3.gz", "enheter.json.gz", "DATA_NOTICE.md"}
    restored_path = tmp_path / "restored.sqlite3"
    restore_checkpoint(out, restored_path)
    restored = State(restored_path)
    try:
        assert restored.get("cycle") == "2026-10" and len(list(restored.todo())) == 1
    finally:
        restored.close()
    restored_seed = tmp_path / "restored.gz"
    restore_asset(out, "enheter.json.gz", restored_seed)
    assert restored_seed.read_bytes() == snapshot.read_bytes()


@pytest.mark.parametrize("complete", [False, True])
def test_monthly_release_rejects_incomplete_or_missing_source(tmp_path, complete):
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "kind": "data",
                "cycle": "2026-10",
                "complete": complete,
                "assets": {},
            }
        )
    )
    with pytest.raises(RuntimeError, match="completed cycle and its source"):
        release.publish("owner/repo", tmp_path, "data-2026-10", "a" * 40)


@pytest.mark.parametrize("fail_final", [False, True])
def test_multiple_fresh_runners_resume_then_publish_original_month(
    monkeypatch, tmp_path, fail_final
):
    """Real DB/export/restore; fake only source HTTP and GitHub transport."""
    client = FakeClient()
    snapshot = tmp_path / "enheter.json.gz"
    client.snapshot_path = snapshot
    original_entities = client.entities

    def entities():
        data = original_entities()
        snapshot.write_bytes(gzip.compress(json.dumps(data).encode()))
        return data

    client.entities = entities
    path = tmp_path / "state.sqlite3"
    day = [date(2026, 10, 31)]
    collected = []

    def collect_process(args, **kwargs):
        collected.append(day[0])
        state = State(path)
        try:
            report = collect(
                state,
                client,
                day[0],
                workers=1,
                max_entities=1,
                account_client_factory=lambda: client,
            )
        finally:
            state.close()
        Path(args[args.index("--report") + 1]).write_text(json.dumps(report))
        return SimpleNamespace(returncode=0)

    remote = tmp_path / "remote"
    remote.mkdir()
    publications = []
    fail_once = [fail_final]

    def publish(repo, directory, tag, target):
        if tag.startswith("data-") and fail_once[0]:
            fail_once[0] = False
            raise RuntimeError("simulated upload interruption")
        shutil.copytree(directory, remote / tag)
        publications.append(tag)

    def download(*args):
        assert args[:2] == ("release", "download")
        target = Path(args[args.index("--dir") + 1])
        shutil.copytree(remote / args[2], target, dirs_exist_ok=True)
        return ""

    monkeypatch.setattr(monthly_run.subprocess, "run", collect_process)
    monkeypatch.setattr(monthly_run, "publish", publish)
    monkeypatch.setattr(release, "gh", download)
    options = {"segments": 1, "state_path": path, "snapshot": snapshot}
    assert (
        monthly_run.run_segments(
            "owner/repo", "a" * 40, "run1", output=tmp_path / "out1", **options
        )
        == 0
    )
    assert publications == ["checkpoint-2026-10-run1-1"]

    # Discard local machine state and the source copy, as between GitHub jobs.
    path.unlink()
    snapshot.unlink()
    restore_checkpoint(remote / publications[-1], path)
    day[0] = date(2026, 11, 1)
    if fail_final:
        with pytest.raises(RuntimeError, match="upload interruption"):
            monthly_run.run_segments(
                "owner/repo", "a" * 40, "run2", output=tmp_path / "out2", **options
            )
        path.unlink()
        snapshot.unlink()
        restore_checkpoint(remote / publications[-1], path)
        # Third runner must publish October before attempting a November seed.
        assert (
            monthly_run.run_segments(
                "owner/repo", "a" * 40, "run3", output=tmp_path / "out3", **options
            )
            == 0
        )
    else:
        assert (
            monthly_run.run_segments(
                "owner/repo", "a" * 40, "run2", output=tmp_path / "out2", **options
            )
            == 0
        )
    assert publications[-1] == "data-2026-10"
    assert collected == [date(2026, 10, 31), date(2026, 11, 1)]
    assert client.downloads == 1
    manifest = json.loads((remote / publications[-1] / "manifest.json").read_text())
    assert manifest["complete"] and manifest["counts"]["queued_entities"] == 0
    assert "enheter.json.gz" in manifest["assets"]
