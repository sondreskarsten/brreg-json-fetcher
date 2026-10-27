import json

import pytest

from brreg_fetcher.client import EntityResponse, SourceError
from scripts.register_smoke import run


class FakeClient:
    def __init__(self, replies):
        self.replies = replies
        self.calls = []

    def entity(self, orgnr):
        self.calls.append(orgnr)
        reply = self.replies[orgnr]
        if isinstance(reply, Exception):
            raise reply
        return reply


def test_live_probe_uses_client_and_decoder_and_saves_evidence(tmp_path):
    client = FakeClient(
        {
            "923609016": EntityResponse(200, b'{"organisasjonsnummer":"923609016"}'),
            "931264338": EntityResponse(200, b'{"slettedato":"2026-10-25"}'),
            "991128972": EntityResponse(410, b'{"slettedato":"2026-10-25"}'),
            "000000000": EntityResponse(404, b""),
        }
    )
    summary = run(tmp_path, client=client)
    assert summary["complete"]
    assert len(client.calls) == 4
    assert (tmp_path / "931264338.body").read_bytes() == client.replies["931264338"].body
    assert json.loads((tmp_path / "summary.json").read_text()) == summary


@pytest.mark.parametrize(
    "reply",
    [EntityResponse(503, b"unavailable"), EntityResponse(410, b""), SourceError("timeout")],
)
def test_failed_probe_still_records_evidence_and_checks_other_cases(tmp_path, reply):
    client = FakeClient({"931264338": reply, "000000000": EntityResponse(404, b"")})
    with pytest.raises(RuntimeError, match="contract check failed"):
        run(tmp_path, client=client, cases={"931264338": "deleted", "000000000": "not_found"})
    summary = json.loads((tmp_path / "summary.json").read_text())
    assert not summary["complete"]
    assert not summary["results"][0]["passed"]
    assert summary["results"][1]["passed"]
    assert len(client.calls) == 2
