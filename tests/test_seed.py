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


@pytest.mark.parametrize("year", [None, "", " ", "NA", "N/A", "NaN"])
def test_missing_year_never_enters_seed(state, year):
    state.sync_entities([entity(year=year)], "2026-10-06")
    assert state.summary()["eligible_entities"] == 0


@pytest.mark.parametrize(
    "form,eligible", [("AS", 1), ("ASA", 1), ("ENK", 0), ("NUF", 0), ("ANS", 0), (None, 0)]
)
def test_only_as_and_asa_with_filed_accounts_are_eligible(state, form, eligible):
    state.sync_entities([entity(form=form)], "2026-10-06")
    assert state.summary()["eligible_entities"] == eligible


def test_legal_form_change_removes_work_and_current_view_but_preserves_history(state):
    state.start_cycle([entity()], "2026-10-05")
    state.record("923609016", "a", response(filing()), "2026-10-05")
    state.sync_entities([entity(form="NUF")], "2026-10-06")
    assert not list(state.todo())
    assert state.summary()["current_filings"] == 0
    assert state.summary()["historical_filings"] == 1


def test_export_contains_filtered_seed_with_legal_form(state, tmp_path):
    state.sync_entities(
        [entity(), entity("974760673", form="ASA"), entity("999999999", form="ENK")], "2026-10-06"
    )
    export_release(state, tmp_path / "release")
    with (tmp_path / "release/observations.csv").open(newline="") as source:
        seed = list(csv.DictReader(source))
    assert len(seed) == 2
    assert {row["organisasjonsform"] for row in seed} == {"AS", "ASA"}


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
        assert state.get("schema_version") == "3"
        assert state.get("entities_date") is None
        state.sync_entities([entity(form="ENK")], "2026-10-06")
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
