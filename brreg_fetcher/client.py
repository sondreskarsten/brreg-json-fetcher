"""Read-only BRREG requests with bounded retries and proxy-aware transport."""

import gzip
import json
import os
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import ijson
import requests

ACCOUNTS_URL = "https://data.brreg.no/regnskapsregisteret/regnskap"
ENTITIES_URL = "https://data.brreg.no/enhetsregisteret/api/enheter/lastned"
ANNOUNCEMENTS_URL = "https://w2.brreg.no/kunngjoring"


class SourceError(RuntimeError):
    """A source could not be read completely and must not advance a checkpoint."""


@dataclass(frozen=True)
class AccountResponse:
    status: int
    body: bytes
    message: str = ""


def unsupported_plan(status, message):
    # Live API responses use both the Norwegian and ASCII spellings.
    return status == 500 and "oppstillingsplan som ikke er stottet" in message.casefold().replace(
        "ø", "o"
    )


class Client:
    def __init__(self, session=None, attempts=4, pause=0.1, sleep=time.sleep, snapshot_path=None):
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": "brreg-json-fetcher/0.2.2"})
        self.attempts = attempts
        self.pause = pause
        self.sleep = sleep
        self.snapshot_path = Path(snapshot_path) if snapshot_path else None

    def get(self, url, **kwargs):
        for attempt in range(self.attempts):
            self.sleep(self.pause)
            try:
                response = self.session.get(url, timeout=(15, 120), **kwargs)
            except requests.RequestException as exc:
                if attempt + 1 == self.attempts:
                    raise SourceError(f"Request failed: {url}: {type(exc).__name__}") from exc
                self.sleep(min(2**attempt, 30))
                continue
            retry = response.status_code == 429 or response.status_code in (500, 502, 503, 504)
            if response.status_code == 500 and not kwargs.get("stream"):
                try:
                    message = response.json().get("message", "")
                except (ValueError, AttributeError):
                    message = ""
                if unsupported_plan(response.status_code, str(message)):
                    return response
            # BRREG has also returned its rate-limit message with HTTP 200.
            if not kwargs.get("stream") and b"Too many requests" in response.content[:300]:
                retry = True
            if not retry:
                return response
            if attempt + 1 == self.attempts:
                if response.status_code == 200:
                    response.close()
                    raise SourceError("BRREG returned a rate-limit message instead of JSON")
                return response
            delay = response.headers.get("Retry-After", "")
            self.sleep(min(float(delay), 120) if delay.isdigit() else min(2**attempt, 30))
            response.close()
        raise SourceError("No HTTP attempts configured")

    def json(self, url, **kwargs):
        with self.get(url, **kwargs) as response:
            if response.status_code != 200:
                raise SourceError(f"HTTP {response.status_code}: {url}")
            try:
                return response.json()
            except ValueError as exc:
                raise SourceError(f"Invalid JSON: {url}") from exc

    def loads(self):
        loads = self.json(f"{ACCOUNTS_URL}/log")
        if not isinstance(loads, list) or not all(isinstance(x, str) and x for x in loads):
            raise SourceError("The account load log is not an array of file names")
        return set(loads)

    def entities(self):
        # The download can be gzip as a file, HTTP content encoding, or plain JSON.
        # requests decodes HTTP encoding; inspect the remaining file magic once.
        if self.snapshot_path:
            self.snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix="brreg-entities-", dir=self.snapshot_path.parent if self.snapshot_path else None
        ) as tmp:
            path = Path(tmp) / "entities"
            with self.get(ENTITIES_URL, stream=True) as response:
                if response.status_code != 200:
                    raise SourceError(f"Entity download returned HTTP {response.status_code}")
                with path.open("wb") as out:
                    for chunk in response.iter_content(1024 * 1024):
                        out.write(chunk)
            with path.open("rb") as probe:
                compressed = probe.read(2) == b"\x1f\x8b"
            opener = gzip.open if compressed else open
            with opener(path, "rb") as stream:
                first = stream.read(1)
                while first and first.isspace():
                    first = stream.read(1)
                if first != b"[":
                    raise SourceError("Entity bulk download is not a JSON array")
                stream.seek(0)
                try:
                    yield from ijson.items(stream, "item")
                except ijson.JSONError as exc:
                    raise SourceError("Incomplete or invalid entity bulk JSON") from exc
            if self.snapshot_path:
                if not compressed:
                    packed = Path(tmp) / "entities.gz"
                    with path.open("rb") as source, gzip.open(packed, "wb") as dest:
                        shutil.copyfileobj(source, dest, 1024 * 1024)
                    path = packed
                os.replace(path, self.snapshot_path)

    def accounts(self, orgnr):
        with self.get(f"{ACCOUNTS_URL}/{orgnr}", headers={"Accept": "application/json"}) as r:
            message = ""
            if r.status_code not in (200, 404):
                try:
                    message = str(r.json().get("message", ""))[:2000]
                except (ValueError, AttributeError):
                    message = f"HTTP {r.status_code}"
            return AccountResponse(r.status_code, r.content, message)

    def announcement_html(self, day, region="0", county=None):
        params = {
            "datoFra": day.strftime("%d.%m.%Y"),
            "datoTil": day.strftime("%d.%m.%Y"),
            "id_region": region,
            "id_niva1": "70",
            "id_niva2": "- - -",
            "id_bransje1": "0",
            "spraak": "no",
        }
        if county is not None:
            params["id_fylke"] = county
        with self.get(f"{ANNOUNCEMENTS_URL}/kombisok.jsp", params=params) as r:
            if r.status_code != 200:
                raise SourceError(f"Announcement search returned HTTP {r.status_code}")
            # This legacy endpoint declares windows-1252 in its HTML.
            return r.content.decode("cp1252")

    def counties(self, region):
        payload = self.json(
            f"{ANNOUNCEMENTS_URL}/rest/fylkerIRegion.rest", params={"regionnr": region}
        )
        if not isinstance(payload, dict) or payload.get("valid") is not True:
            raise SourceError(f"Cannot discover counties for region {region}")
        counties = [str(x["nummer"]) for x in payload.get("fylker", [])]
        if not counties:
            raise SourceError(f"No counties returned for overflowing region {region}")
        return counties


def decode_filings(raw, orgnr):
    """Validate identities without projecting away source fields or missing leaves."""
    try:
        filings = json.loads(raw)
        if not isinstance(filings, list) or not filings:
            raise ValueError("Expected a nonempty filing array")
        ids = set()
        for filing in filings:
            if not isinstance(filing, dict):
                raise TypeError("Filing is not an object")
            if str(filing["virksomhet"]["organisasjonsnummer"]) != orgnr:
                raise ValueError("Response organisation differs from the requested orgnr")
            if type(filing["id"]) is not int or filing["id"] in ids:
                raise ValueError("Missing or duplicate filing id")
            ids.add(filing["id"])
            if filing["regnskapstype"] not in ("SELSKAP", "KONSERN"):
                raise ValueError("Unknown account type")
            from datetime import date

            date.fromisoformat(filing["regnskapsperiode"]["tilDato"])
            date.fromisoformat(filing["regnskapsperiode"]["fraDato"])
        return filings
    except (ValueError, KeyError, TypeError) as exc:
        raise SourceError(f"Invalid accounts response for {orgnr}: {exc}") from exc
