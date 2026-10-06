import gzip
import json
from unittest.mock import Mock

import pytest
import requests
from conftest import entity

from brreg_fetcher.client import Client, SourceError


def http(status, body, **headers):
    response = requests.Response()
    response.status_code = status
    response._content = body
    response._content_consumed = True
    response.headers.update(headers)
    return response


def client_with(*responses):
    session = Mock()
    session.get.side_effect = responses
    return Client(session=session, sleep=lambda _: None)


def test_retries_http_200_rate_limit_and_429():
    client = client_with(
        http(200, b"Too many requests"),
        http(429, b"slow", **{"Retry-After": "1"}),
        http(200, b"[]"),
    )
    assert client.json("https://example.test") == []
    assert client.session.get.call_count == 3


def test_exhausted_rate_limit_is_not_success():
    client = client_with(*(http(200, b"Too many requests") for _ in range(4)))
    with pytest.raises(SourceError, match="rate-limit"):
        client.accounts("923609016")


def test_connection_failure_retries_then_recovers():
    client = client_with(requests.ConnectionError("down"), http(200, b'["load-a"]'))
    assert client.json("https://example.test") == ["load-a"]


@pytest.mark.parametrize("compressed", [False, True])
def test_streamed_entity_bulk_plain_or_gzip(compressed):
    raw = json.dumps([entity()]).encode()
    if compressed:
        raw = gzip.compress(raw)
    response = http(200, raw)
    response.iter_content = lambda size: (raw[i : i + 11] for i in range(0, len(raw), 11))
    client = client_with(response)
    assert list(client.entities()) == [entity()]


def test_incomplete_download_does_not_commit_entity_snapshot(state):
    raw = b'[{"organisasjonsnummer":"923609016","sisteInnsendteAarsregnskap":"2025"},'
    response = http(200, raw)
    response.iter_content = lambda size: iter([raw])
    client = client_with(response)
    with pytest.raises(SourceError, match="Incomplete"):
        state.sync_entities(client.entities(), "2026-10-06")
    assert state.get("entities_date") is None
    assert state.summary()["eligible_entities"] == 0


@pytest.mark.parametrize("spelling", ["stottet", "støttet"])
def test_unsupported_bank_plan_is_not_retried(state, spelling):
    message = f"Regnskapet inneholder en oppstillingsplan som ikke er {spelling} (BANK)"
    client = client_with(http(500, json.dumps({"message": message}).encode()))
    result = client.accounts("816914582")
    assert client.session.get.call_count == 1
    outcome = state.record("816914582", "load-a", result, "2026-10-06")
    assert outcome["unsupported"] and not outcome["retry"]
