import gzip
import json

import pyarrow.parquet as pq
import pytest
from conftest import entity, filing, response

from brreg_fetcher.client import SourceError
from brreg_fetcher.export import export_release, restore_checkpoint, sha256_file
from brreg_fetcher.state import State


def test_release_round_trip_union_fields_raw_bytes_and_checkpoint(state, tmp_path):
    state.sync_entities([entity()], "2026-10-01")
    state.schedule({"load-a"})
    raw = response(filing(), filing(id=2, account_type="KONSERN", eiendeler={"goodwill": 200}))
    state.record("923609016", "a", raw, "2026-10-01T12:00:00+00:00")
    out = tmp_path / "release"
    manifest = export_release(state, out, max_asset_bytes=1024)
    assert len(manifest["assets"]["checkpoint.sqlite3.gz"]["parts"]) > 1
    for asset in manifest["assets"].values():
        for part in asset["parts"]:
            assert sha256_file(out / part["name"]) == part["sha256"]
    parquet = tmp_path / "joined.parquet"
    parquet.write_bytes(
        b"".join(
            (out / part["name"]).read_bytes()
            for part in manifest["assets"]["accounts.parquet"]["parts"]
        )
    )
    data = pq.read_table(parquet).to_pylist()
    assert len(data) == 2
    assert data[0]["eiendeler.goodwill"] is None
    assert data[1]["eiendeler.goodwill"] == 200
    assert json.loads(data[1]["_meta.filing_json"])["id"] == 2
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
    assert pq.read_table(out / "accounts.parquet").num_rows == 0
    with pytest.raises(SourceError, match="empty"):
        export_release(state, out)
