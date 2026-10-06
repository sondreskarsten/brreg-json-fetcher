import json

import pytest
from conftest import entity, filing, response

from brreg_fetcher.client import AccountResponse, SourceError, decode_filings


def test_six_filings_keep_type_id_and_period_year(state):
    items = [
        filing(id=index + 1, account_type=kind, year=year)
        for index, (kind, year) in enumerate(
            (k, y) for k in ["KONSERN", "SELSKAP"] for y in [2023, 2024, 2025]
        )
    ]
    items[-1]["regnskapsperiode"]["fraDato"] = "2024-07-01"
    items[-1]["regnskapsperiode"]["tilDato"] = "2025-06-30"
    for item in items:
        item["journalnr"] = str(item["regnskapsperiode"]["tilDato"][:4])
    state.record("923609016", "a", response(*items), "2026-10-01T12:00:00+00:00")
    assert state.summary()["current_filings"] == 6
    assert state.db.execute("SELECT fiscal_year FROM filings WHERE id=6").fetchone()[0] == 2025


@pytest.mark.parametrize(
    "payload", [[], {}, [None], [filing(orgnr="974760673")], [filing(), filing()], [filing(id="1")]]
)
def test_bad_response_does_not_replace_current_snapshot(state, payload):
    state.record("923609016", "a", response(filing()), "2026-10-01T12:00:00+00:00")
    with pytest.raises(SourceError):
        state.record(
            "923609016",
            "b",
            AccountResponse(200, json.dumps(payload).encode()),
            "2026-10-02T12:00:00+00:00",
        )
    assert state.summary()["observations"] == 1
    assert state.summary()["current_filings"] == 1


def test_404_and_unsupported_are_distinct_from_transient_failure(state):
    state.sync_entities([entity()], "2026-10-01")
    state.schedule({"load-a"})
    outcome = state.record(
        "923609016", "a", AccountResponse(503, b"unavailable", "HTTP 503"), "2026-10-01"
    )
    assert outcome["retry"] and len(list(state.todo())) == 1
    message = "Regnskapet inneholder en oppstillingsplan som ikke er støttet (BANK)"
    outcome = state.record("923609016", "a", AccountResponse(500, b"error", message), "2026-10-01")
    assert outcome["unsupported"] and not outcome["retry"] and not list(state.todo())
    assert state.summary()["pending_signals"] == 1
    state.record("923609016", "b", response(filing()), "2026-10-02")
    state.record("923609016", "c", AccountResponse(404, b""), "2026-10-03")
    assert state.summary()["current_filings"] == 0
    assert state.summary()["historical_filings"] == 1


def test_unknown_fields_preserved():
    item = filing(future_field={"new_amount": 123})
    assert decode_filings(response(item).body, "923609016")[0] == item
