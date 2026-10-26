import csv
import json
from datetime import date

import pytest
from conftest import entity, filing, response

from brreg_fetcher.client import EntityResponse, SourceError, decode_register
from brreg_fetcher.collector import collect
from brreg_fetcher.export import export_release


class FakeClient:
    def __init__(self):
        self.calls = []
        self.lookups = []
        self.fail = False
        self.downloads = 0
        self.register = [entity(), entity("974760673")]

    def entities(self):
        self.downloads += 1
        return list(self.register)

    def entity(self, orgnr):
        self.lookups.append(orgnr)
        if self.fail:
            raise SourceError("connection failed")
        body = json.dumps({"organisasjonsnummer": orgnr, "slettedato": "2026-10-20"}).encode()
        return EntityResponse(410, body)

    def accounts(self, orgnr):
        self.calls.append(orgnr)
        if self.fail:
            raise SourceError("connection failed")
        return response(filing(orgnr=orgnr))


def test_budgeted_monthly_collection_resumes_without_redownloading(state):
    client = FakeClient()
    kwargs = {
        "workers": 1,
        "max_entities": 1,
        "account_client_factory": lambda: client,
    }
    first = collect(state, client, date(2026, 10, 6), **kwargs)
    assert first["attempted"] == 1 and first["queued_entities"] == 1 and not first["complete"]
    second = collect(state, client, date(2026, 10, 6), **kwargs)
    assert second["attempted"] == 1 and second["complete"]
    third = collect(state, client, date(2026, 10, 6), **kwargs)
    assert third["attempted"] == 0 and len(client.calls) == 2
    assert client.downloads == 1


def test_transient_failure_stays_queued_and_run_is_incomplete(state):
    client = FakeClient()
    client.fail = True
    report = collect(
        state,
        client,
        date(2026, 10, 6),
        workers=1,
        account_client_factory=lambda: client,
    )
    assert report["errors"] == 2 and report["queued_entities"] == 2 and not report["complete"]
    client.fail = False
    report = collect(
        state,
        client,
        date(2026, 10, 6),
        workers=1,
        account_client_factory=lambda: client,
    )
    assert report["errors"] == 0 and report["complete"]


@pytest.mark.parametrize(
    "status,body,expected",
    [
        (410, b'{"organisasjonsnummer":"1","slettedato":"2026-10-20"}', ("deleted", "2026-10-20")),
        (410, b"", ("deleted", "")),
        (200, b'{"organisasjonsnummer":"1","slettedato":"2026-10-20"}', ("deleted", "2026-10-20")),
        (200, b'{"organisasjonsnummer":"1"}', ("still_registered", "")),
        (404, b"", ("not_found", "")),
        (500, b"<html>", ("lookup_failed", "")),
    ],
)
def test_register_lookup_is_explained_for_end_users(status, body, expected):
    assert decode_register(status, body) == expected


def test_removed_entity_is_looked_up_kept_and_still_fetched(state, tmp_path):
    client = FakeClient()
    options = {"workers": 1, "account_client_factory": lambda: client}
    first = collect(state, client, date(2026, 10, 6), **options)
    assert first["complete"] and first["register_lookups"] == 0
    client.register = [entity("974760673")]
    client.fail = True
    second = collect(state, client, date(2026, 11, 2), **options)
    assert second["cycle"] == "2026-11"
    assert second["register_lookups"] == 1 and second["register_lookup_failed"] == 1
    assert client.lookups == ["923609016"]
    client.fail = False
    third = collect(state, client, date(2026, 11, 3), **options)
    assert third["register_lookups"] == 1 and third["register_deleted"] == 1
    assert third["complete"] and third["eligible_entities"] == 2
    assert second["errors"] == 2 and client.calls.count("923609016") == 3
    fourth = collect(state, client, date(2026, 11, 4), **options)
    assert fourth["register_lookups"] == 0
    export_release(state, tmp_path / "release")
    with (tmp_path / "release/observations.csv").open(newline="") as stream:
        records = {r["orgnr"]: r for r in csv.DictReader(stream)}
    gone, listed = records["923609016"], records["974760673"]
    assert gone["outcome"] == "ok" and gone["register_status"] == "deleted"
    assert gone["register_deleted_date"] == "2026-10-20"
    assert gone["register_checked_on"] == "2026-11-03"
    assert listed["register_status"] == "listed" and listed["register_deleted_date"] == ""
    assert listed["register_checked_on"] == "2026-11-02"
