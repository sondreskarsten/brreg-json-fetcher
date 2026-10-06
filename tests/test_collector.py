from datetime import date

from conftest import entity, filing, response

from brreg_fetcher.client import SourceError
from brreg_fetcher.collector import collect


class FakeClient:
    def __init__(self):
        self.calls = []
        self.fail = False
        self.load_names = {"load-a"}

    def entities(self):
        return [entity(), entity("974760673")]

    def announcement_html(self, day, *args):
        return "Antall treff 0"

    def loads(self):
        return self.load_names

    def accounts(self, orgnr):
        self.calls.append(orgnr)
        if self.fail:
            raise SourceError("connection failed")
        return response(filing(orgnr=orgnr))


def test_budgeted_bootstrap_resume_and_unchanged_load(state):
    client = FakeClient()
    kwargs = {
        "workers": 1,
        "lookback": 0,
        "max_entities": 1,
        "account_client_factory": lambda: client,
    }
    first = collect(state, client, date(2026, 10, 6), **kwargs)
    assert first["attempted"] == 1 and first["queued_entities"] == 1 and not first["complete"]
    second = collect(state, client, date(2026, 10, 6), **kwargs)
    assert second["attempted"] == 1 and second["complete"]
    third = collect(state, client, date(2026, 10, 6), **kwargs)
    assert third["attempted"] == 0 and len(client.calls) == 2


def test_transient_failure_stays_queued_and_run_is_incomplete(state):
    client = FakeClient()
    client.fail = True
    report = collect(
        state,
        client,
        date(2026, 10, 6),
        workers=1,
        lookback=0,
        account_client_factory=lambda: client,
    )
    assert report["errors"] == 2 and report["queued_entities"] == 2 and not report["complete"]
    client.fail = False
    report = collect(
        state,
        client,
        date(2026, 10, 6),
        workers=1,
        lookback=0,
        account_client_factory=lambda: client,
    )
    assert report["errors"] == 0 and report["complete"]
