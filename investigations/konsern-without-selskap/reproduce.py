"""Refetch the evidence for KONSERN rows whose journalnr has no SELSKAP row."""

import argparse
import csv
import html
import json
import re
import time
from pathlib import Path

import requests

HERE = Path(__file__).parent
ACCOUNTS = "https://data.brreg.no/regnskapsregisteret/regnskap"
NOTICES = "https://w2.brreg.no/kunngjoring"
FIELDS = ["id", "journalnr", "regnskapstype", "fra_dato", "til_dato", "morselskap"]


def summary(row):
    return {
        "id": row["id"],
        "journalnr": row["journalnr"],
        "regnskapstype": row["regnskapstype"],
        "fra_dato": row["regnskapsperiode"]["fraDato"],
        "til_dato": row["regnskapsperiode"]["tilDato"],
        "morselskap": row["virksomhet"].get("morselskap"),
    }


def fetch(session, url, path, pause):
    response = session.get(url, timeout=60)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(response.content)
    time.sleep(pause)
    return response


def account_rows(session, case, out, pause):
    orgnr = case["orgnr"]
    listed = fetch(session, f"{ACCOUNTS}/{orgnr}", out / "api" / "list" / f"{orgnr}.json", pause)
    rows = [
        {"orgnr": orgnr, "source": "list", "http_status": 200, **summary(r)} for r in listed.json()
    ]
    probes = {
        "konsern_id_minus_2": int(case["konsern_id"]) - 2,
        "konsern_id": int(case["konsern_id"]),
        "selskap_id": int(case["selskap_id"]),
        "selskap_id_plus_2": int(case["selskap_id"]) + 2,
    }
    for source, row_id in probes.items():
        path = out / "api" / "by_id" / f"{orgnr}-{row_id}.json"
        response = fetch(session, f"{ACCOUNTS}/{orgnr}/{row_id}", path, pause)
        found = summary(response.json()) if response.status_code == 200 else {"id": row_id}
        rows.append(
            {"orgnr": orgnr, "source": source, "http_status": response.status_code, **found}
        )
    return rows


def notices(session, case, out, pause):
    orgnr = case["orgnr"]
    path = out / "kunngjoring" / f"{orgnr}.html"
    page = fetch(session, f"{NOTICES}/hent_nr.jsp?orgnr={orgnr}", path, pause).content.decode(
        "latin-1"
    )
    rows = []
    date = None
    pattern = r"(\d{2}\.\d{2}\.\d{4})|hent_en\.jsp\?kid=(\d+)[^\"]*\"[^>]*>\s*([^<]+)<"
    for match in re.finditer(pattern, page):
        if match.group(1):
            date = match.group(1)
            continue
        kid, kind = match.group(2), html.unescape(match.group(3)).strip()
        if "regnskap" not in kind.lower() or int(date[-4:]) < int(case["year"]):
            continue
        detail_path = out / "kunngjoring" / f"{orgnr}-{kid}.html"
        url = f"{NOTICES}/hent_en.jsp?kid={kid}&sokeverdi={orgnr}&spraak=nb"
        detail = html.unescape(fetch(session, url, detail_path, pause).content.decode("latin-1"))
        text = re.search(r"har den (\d{2}\.\d{2}\.\d{4}) mottatt (et nytt )?komplett", detail)
        year = re.search(r"regnskaps.ret\s*(\d{4})", detail)
        rows.append(
            {
                "orgnr": orgnr,
                "kunngjort": date,
                "kid": kid,
                "type": kind,
                "regnskapsaar_in_text": year.group(1) if year else "",
                "mottatt_in_text": text.group(1) if text else "",
                "nytt_in_text": bool(text and text.group(2)),
            }
        )
    return rows


def write(path, rows, fields):
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def run(cases=HERE / "cases.csv", out=HERE / "evidence", pause=0.5):
    with Path(cases).open(newline="", encoding="utf-8") as stream:
        cases = list(csv.DictReader(stream))
    session = requests.Session()
    session.headers["Accept"] = "application/json, application/octet-stream, */*"
    accounts, notice_rows = [], []
    for case in cases:
        accounts += account_rows(session, case, out, pause)
        notice_rows += notices(session, case, out, pause)
        pdf = f"{ACCOUNTS}/aarsregnskap/kopi/{case['orgnr']}/{case['year']}"
        fetch(session, pdf, out / "pdf" / f"{case['orgnr']}-{case['year']}.pdf", pause)
    write(out / "account_rows.csv", accounts, ["orgnr", "source", "http_status", *FIELDS])
    write(out / "kunngjoringer.csv", notice_rows, list(notice_rows[0]))
    print(
        json.dumps(
            {"cases": len(cases), "account_rows": len(accounts), "kunngjoringer": len(notice_rows)}
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, default=HERE / "cases.csv")
    parser.add_argument("--out", type=Path, default=HERE / "evidence")
    parser.add_argument("--pause", type=float, default=0.5)
    args = parser.parse_args()
    run(args.cases, args.out, args.pause)
