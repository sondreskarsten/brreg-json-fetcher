import csv
import gzip
import json

import pytest
from conftest import entity, filing, response

from brreg_fetcher.client import SourceError
from brreg_fetcher.export import export_release, restore_checkpoint, sha256_file, write_csv
from brreg_fetcher.state import State


def test_release_round_trip_union_fields_raw_bytes_and_checkpoint(state, tmp_path):
    state.start_cycle([entity()], "2026-10-01")
    raw = response(filing(), filing(id=2, account_type="KONSERN", eiendeler={"goodwill": 200}))
    state.record("923609016", "2026-10", raw, "2026-10-01T12:00:00+00:00")
    out = tmp_path / "release"
    manifest = export_release(state, out, max_asset_bytes=4096)
    assert manifest["assets"]["checkpoint.sqlite3.gz"]["parts"]
    for asset in manifest["assets"].values():
        for part in asset["parts"]:
            assert sha256_file(out / part["name"]) == part["sha256"]
    with (out / "accounts.csv").open(newline="") as stream:
        data = list(csv.DictReader(stream))
    assert len(data) == 2
    assert data[0]["eiendeler.goodwill"] == ""
    assert data[1]["eiendeler.goodwill"] == "200"
    assert json.loads(data[1]["_meta.filing_json"])["id"] == 2
    assert not list(out.glob("*.parquet"))
    restored_path = tmp_path / "restored.sqlite3"
    restore_checkpoint(out, restored_path)
    restored = State(restored_path)
    try:
        assert restored.summary() == state.summary()
        saved = restored.db.execute("SELECT body_gzip FROM responses").fetchone()[0]
        assert gzip.decompress(saved) == raw.body
    finally:
        restored.close()
    with pytest.raises(SourceError, match="existing checkpoint"):
        restore_checkpoint(out, restored_path)


def test_corrupt_checkpoint_part_rejected_before_install(state, tmp_path):
    out = tmp_path / "release"
    manifest = export_release(state, out)
    path = out / manifest["assets"]["checkpoint.sqlite3.gz"]["parts"][0]["name"]
    path.write_bytes(b"corrupt")
    with pytest.raises(SourceError, match="Checksum mismatch"):
        restore_checkpoint(out, tmp_path / "restored.sqlite3")
    assert not (tmp_path / "restored.sqlite3").exists()


def test_empty_export_and_no_mixed_runs(state, tmp_path):
    out = tmp_path / "release"
    manifest = export_release(state, out)
    assert manifest["complete"] is False
    assert manifest["provenance"]["licence"] == "NLOD-2.0"
    assert manifest["provenance"]["official"] is False
    notice = (out / "DATA_NOTICE.md").read_text()
    assert "Brønnøysundregistrene" in notice
    assert "https://data.norge.no/nlod/no/2.0" in notice
    assert manifest["assets"]["DATA_NOTICE.md"]["sha256"] == sha256_file(out / "DATA_NOTICE.md")
    with (out / "accounts.csv").open(newline="") as stream:
        assert list(csv.DictReader(stream)) == []
    with pytest.raises(SourceError, match="empty"):
        export_release(state, out)


def test_six_filings_and_failed_lookups_have_separate_grains(state, tmp_path):
    from brreg_fetcher.client import AccountResponse

    state.start_cycle([entity(), entity("111111111"), entity("222222222")], "2026-10-01")
    filings = [
        filing(id=i + 1, account_type=typ, year=year)
        for i, (typ, year) in enumerate(
            (typ, year) for typ in ("KONSERN", "SELSKAP") for year in (2023, 2024, 2025)
        )
    ]
    filings[-1]["future_field"] = 'æøå, "quoted"\nnew line'
    state.record("923609016", "2026-10", response(*filings), "2026-10-03T12:00:00Z")
    state.record("111111111", "2026-10", AccountResponse(404, b""), "2026-10-03T12:00:00Z")
    error = '{"message":"oppstillingsplan som ikke er stottet (BANK)"}'
    state.record(
        "222222222",
        "2026-10",
        AccountResponse(500, error.encode(), message=error),
        "2026-10-03T12:00:00Z",
    )
    out = tmp_path / "release"
    manifest = export_release(state, out)
    with (out / "accounts.csv").open(newline="") as stream:
        records = list(csv.DictReader(stream))
    assert len(records) == 6
    assert {r["_meta.orgnr"] for r in records} == {"923609016"}
    assert {r["_meta.fiscal_year"] for r in records} == {"2023", "2024", "2025"}
    assert {r["regnskapstype"] for r in records} == {"SELSKAP", "KONSERN"}
    assert records[-1]["future_field"] == filings[-1]["future_field"]
    assert [json.loads(r["_meta.filing_json"]) for r in records] == filings
    with (out / "observations.csv").open(newline="") as stream:
        observations = list(csv.DictReader(stream))
    assert len(observations) == 3
    assert [r["outcome"] for r in observations] == ["not_found", "unsupported", "ok"]
    assert observations[1]["error_body"] == error
    assert manifest["dataset"]["accounts"]["rows"] == 6

    # Next month's partial export cannot reuse earlier accounts or observations.
    with state.db:
        state.set("cycle_completed_at", "2026-10-03T12:00:00Z")
    state.start_cycle([entity()], "2026-11-01")
    out = tmp_path / "november"
    export_release(state, out)
    with (out / "accounts.csv").open(newline="") as stream:
        assert list(csv.DictReader(stream)) == []
    with (out / "observations.csv").open(newline="") as stream:
        (record,) = csv.DictReader(stream)
        assert record["outcome"] == "pending"
        assert record["observed_at"] == ""


def test_csv_parts_are_independently_readable_with_embedded_newlines(tmp_path):
    records = [{"id": n, "text": 'comma, quote"\næ'} for n in range(8)]
    metadata = write_csv(iter(records), ["id", "text"], tmp_path, "accounts", 80)
    assert len(metadata["files"]) > 1
    restored = []
    for name in metadata["files"]:
        path = tmp_path / name
        assert path.stat().st_size <= 80
        with path.open(newline="") as stream:
            restored.extend(csv.DictReader(stream))
    assert restored == [{"id": str(r["id"]), "text": r["text"]} for r in records]
    with pytest.raises(SourceError, match="exceeds"):
        write_csv([{"text": "x" * 100}], ["text"], tmp_path, "oversize", 80)
