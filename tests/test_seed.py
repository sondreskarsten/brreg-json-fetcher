import csv
import gzip
import json
import sqlite3
from unittest.mock import Mock

import pytest
from conftest import entity, filing, response
from test_client import http

from brreg_fetcher.client import Client
from brreg_fetcher.export import export_release
from brreg_fetcher.state import State


@pytest.mark.parametrize("year", [None, "", " ", "NA", "N/A", "NaN", "2025"])
def test_missing_year_does_not_exclude_an_entity(state, year):
    state.sync_entities([entity(year=year)], "2026-10-06")
    assert state.summary()["eligible_entities"] == 1


@pytest.mark.parametrize(
    "form,eligible", [("AS", 1), ("ASA", 1), ("ENK", 0), ("NUF", 1), ("ANS", 1), (None, 1)]
)
def test_every_legal_form_except_unfiled_enk_is_eligible(state, form, eligible):
    state.sync_entities([entity(form=form, year=None)], "2026-10-06")
    assert state.summary()["eligible_entities"] == eligible


@pytest.mark.parametrize("year,eligible", [(None, 0), ("", 0), ("NA", 0), ("2025", 1)])
def test_enk_is_eligible_only_with_a_filed_year(state, year, eligible):
    state.sync_entities([entity(form="ENK", year=year)], "2026-10-06")
    assert state.summary()["eligible_entities"] == eligible


def test_entity_missing_from_later_download_is_kept_and_queued_for_register_lookup(state):
    state.start_cycle([entity(), entity("974760673")], "2026-10-05")
    state.record("923609016", "2026-10", response(filing()), "2026-10-05")
    state.record("974760673", "2026-10", response(filing(orgnr="974760673")), "2026-10-05")
    with state.db:
        state.set("cycle_completed_at", "2026-10-05")
    state.start_cycle([entity("974760673")], "2026-11-01")
    assert [row["orgnr"] for row in state.todo()] == ["923609016", "974760673"]
    assert [row["orgnr"] for row in state.register_lookups()] == ["923609016"]
    assert state.summary()["eligible_entities"] == 2
    assert state.summary()["historical_filings"] == 2
    state.record_register("923609016", "deleted", "2026-10-20", "2026-11-01")
    assert not list(state.register_lookups())
    row = state.db.execute("SELECT * FROM entities WHERE orgnr='923609016'").fetchone()
    assert (row["register_status"], row["register_deleted_date"]) == ("deleted", "2026-10-20")
    listed = state.db.execute("SELECT * FROM entities WHERE orgnr='974760673'").fetchone()
    assert (listed["register_status"], listed["register_checked_on"]) == ("listed", "2026-11-01")


def test_failed_register_lookup_is_retried_next_run(state):
    state.start_cycle([entity()], "2026-10-05")
    state.record("923609016", "2026-10", response(filing()), "2026-10-05")
    with state.db:
        state.set("cycle_completed_at", "2026-10-05")
    state.start_cycle([entity("974760673")], "2026-11-01")
    state.record_register("923609016", "lookup_failed", "", "2026-11-01")
    assert [row["orgnr"] for row in state.register_lookups()] == ["923609016"]


def test_export_contains_filtered_seed_with_legal_form(state, tmp_path):
    state.sync_entities(
        [
            entity(),
            entity("974760673", form="ASA"),
            entity("999999999", form="ENK", year=None),
            entity("888888888", form="ENK"),
        ],
        "2026-10-06",
    )
    export_release(state, tmp_path / "release")
    with (tmp_path / "release/observations.csv").open(newline="") as source:
        seed = list(csv.DictReader(source))
    assert len(seed) == 3
    assert {row["orgnr"] for row in seed} == {"923609016", "974760673", "888888888"}


def test_old_checkpoint_requires_fresh_entity_snapshot(tmp_path):
    path = tmp_path / "old.sqlite3"
    with sqlite3.connect(path) as db:
        db.executescript(
            "CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);"
            "INSERT INTO meta VALUES ('schema_version','1'),('entities_date','2026-10-06');"
            "CREATE TABLE entities(orgnr TEXT PRIMARY KEY, year INTEGER, active INTEGER NOT NULL, observed_on TEXT NOT NULL);"
        )
    state = State(path)
    try:
        assert state.get("schema_version") == "5"
        assert state.get("entities_date") is None
        state.sync_entities([entity(form="ENK", year=None)], "2026-10-06")
        assert state.summary()["eligible_entities"] == 0
    finally:
        state.close()


def test_successful_download_retains_readable_gzip_copy(tmp_path):
    raw = json.dumps([entity()]).encode()
    reply = http(200, raw)
    reply.iter_content = lambda size: iter([raw])
    session = Mock()
    session.get.return_value = reply
    path = tmp_path / "enheter.json.gz"
    client = Client(session=session, sleep=lambda _: None, snapshot_path=path)
    assert list(client.entities()) == [entity()]
    assert json.loads(gzip.decompress(path.read_bytes())) == [entity()]
