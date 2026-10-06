import json

import pytest

from brreg_fetcher.client import AccountResponse
from brreg_fetcher.state import State


@pytest.fixture
def state(tmp_path):
    store = State(tmp_path / "checkpoint.sqlite3")
    yield store
    store.close()


def entity(orgnr="923609016", year="2025"):
    return {"organisasjonsnummer": orgnr, "sisteInnsendteAarsregnskap": year}


def filing(id=1, orgnr="923609016", account_type="SELSKAP", year=2025, **extra):
    return {
        "id": id,
        "journalnr": f"journal-{id}",
        "regnskapstype": account_type,
        "virksomhet": {"organisasjonsnummer": orgnr},
        "regnskapsperiode": {"fraDato": f"{year}-01-01", "tilDato": f"{year}-12-31"},
        "valuta": "NOK",
        "eiendeler": {},
        **extra,
    }


def response(*filings):
    return AccountResponse(200, json.dumps(filings).encode())
