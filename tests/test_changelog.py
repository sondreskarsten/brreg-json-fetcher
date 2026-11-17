import csv
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import entity, filing

from brreg_fetcher.changelog import COLUMNS, build_changelog
from brreg_fetcher.client import AccountResponse, SourceError
from brreg_fetcher.export import export_release
from brreg_fetcher.state import State
from scripts import monthly_run, release

UNSUPPORTED = '{"message":"oppstillingsplan som ikke er stottet (SKADE)"}'


def ok(*filings):
    return AccountResponse(200, json.dumps(filings).encode())


def make_release(tmp_path, name, day, entities, responses):
    state = State(tmp_path / f"{name}.sqlite3")
    try:
        cycle = day[:7]
        state.start_cycle(entities, day)
        for orgnr, response in responses.items():
            state.record(orgnr, cycle, response, f"{day}T12:00:00+00:00")
        with state.db:
            state.set("cycle_completed_at", f"{day}T13:00:00+00:00")
        export_release(state, tmp_path / name)
    finally:
        state.close()
    return tmp_path / name


def f(orgnr, year, id, journalnr, typ="SELSKAP", **leaves):
    body = filing(id=id, orgnr=orgnr, account_type=typ, year=year)
    body["journalnr"] = journalnr
    body["eiendeler"] = {"sumEiendeler": 1000.0, "sumFordringer": 50.0}
    body["resultatregnskapResultat"] = {"aarsresultat": 10.0}
    for path, value in leaves.items():
        target = body
        parts = path.split(".")
        for part in parts[:-1]:
            target = target.setdefault(part, {})
        if value is None:
            target.pop(parts[-1], None)
        else:
            target[parts[-1]] = value
    return body


ORG = {k: f"1000000{i:02d}" for i, k in enumerate("ABCDEFGHIJK", start=0)}


def two_months(tmp_path):
    o = ORG
    prior_entities = [entity(o[k], form="AS") for k in "ABCDEFGHIK"]
    current_entities = [*prior_entities, entity(o["J"], form="NUF")]
    prior = {
        o["A"]: ok(
            f(o["A"], 2025, 7213446, "2026759398", **{"eiendeler.sumEiendeler": 29755200.0})
        ),
        o["B"]: ok(f(o["B"], 2025, 7100000, "2026701000", **{"eiendeler.sumFordringer": None})),
        o["C"]: ok(f(o["C"], 2024, 6000000, "2025500000")),
        o["D"]: ok(f(o["D"], 2024, 6000001, "2025500001"), f(o["D"], 2025, 7100001, "2026701001")),
        o["E"]: AccountResponse(500, UNSUPPORTED.encode(), message=UNSUPPORTED),
        o["F"]: ok(f(o["F"], 2025, 7120000, "2026710000")),
        o["G"]: ok(f(o["G"], 2024, 6100000, "2025600000")),
        o["H"]: ok(
            f(o["H"], 2025, 7130000, "2026720000"),
            f(o["H"], 2025, 7130001, "2026720000", typ="KONSERN"),
        ),
        o["I"]: ok(
            f(o["I"], 2022, 4000000, "2023100000"),
            f(o["I"], 2023, 5000000, "2024100000"),
            f(o["I"], 2024, 6000002, "2025100000"),
        ),
        o["K"]: ok(f(o["K"], 2025, 7140000, "2026730000")),
    }
    moved = f(o["G"], 2024, 6100000, "2025600000")
    moved["regnskapsperiode"]["tilDato"] = "2025-12-31"
    current = {
        o["A"]: ok(
            f(
                o["A"],
                2025,
                7241960,
                "2026769396",
                **{
                    "eiendeler.sumEiendeler": 13597704.0,
                    "resultatregnskapResultat.aarsresultat": -7513481.0,
                },
            )
        ),
        o["B"]: ok(f(o["B"], 2025, 7250000, "2026771000")),
        o["C"]: ok(
            f(
                o["C"],
                2024,
                6000000,
                "2025500000",
                **{"resultatregnskapResultat.aarsresultat": 12.0},
            )
        ),
        o["D"]: AccountResponse(404, b""),
        o["E"]: ok(f(o["E"], 2025, 7200000, "2026740000")),
        o["F"]: ok(f(o["F"], 2025, 7252000, "2026772000")),
        o["G"]: ok(moved),
        o["H"]: ok(
            f(o["H"], 2025, 7253000, "2026773000"),
            f(
                o["H"],
                2025,
                7253001,
                "2026773000",
                typ="KONSERN",
                **{"eiendeler.sumEiendeler": 42800000.0},
            ),
        ),
        o["I"]: ok(
            f(o["I"], 2023, 5000000, "2024100000"),
            f(o["I"], 2024, 6000002, "2025100000"),
            f(o["I"], 2025, 7260000, "2026774000"),
        ),
        o["J"]: ok(f(o["J"], 2025, 7270000, "2026775000")),
        o["K"]: ok(f(o["K"], 2025, 7140000, "2026730000")),
    }
    prior_dir = make_release(tmp_path, "data-2026-10", "2026-10-06", prior_entities, prior)
    current_dir = make_release(tmp_path, "data-2026-11", "2026-11-03", current_entities, current)
    return prior_dir, current_dir


def read_rows(directory, stem):
    manifest = json.loads((directory / "manifest.json").read_text())
    rows = []
    for name in manifest["dataset"][stem]["files"]:
        with (directory / name).open(newline="") as stream:
            rows.extend(csv.DictReader(stream))
    return rows


def by_org(rows):
    out = {}
    for row in rows:
        out.setdefault(row["orgnr"], []).append(row)
    return out


def test_every_transition_kind_is_logged(tmp_path):
    prior_dir, current_dir = two_months(tmp_path)
    out = tmp_path / "changelog-2026-11"
    manifest = build_changelog(prior_dir, current_dir, out)
    assert manifest["kind"] == "changelog" and manifest["complete"]
    assert manifest["cycle"] == "2026-11" and manifest["prior_cycle"] == "2026-10"
    rows = read_rows(out, "delta")
    assert list(rows[0]) == COLUMNS
    assert read_rows(out, "cumulative") == rows
    assert {r["release"] for r in rows} == {"2026-11"}
    events = by_org(rows)
    o = ORG

    a = events[o["A"]]
    assert {r["endringstype"] for r in a} == {"Resubmitted"}
    assert len({r["event_id"] for r in a}) == 1
    assert {(r["op"], r["path"], r["old_value"], r["new_value"]) for r in a} == {
        ("replace", "eiendeler.sumEiendeler", "29755200", "13597704"),
        ("replace", "resultatregnskapResultat.aarsresultat", "10", "-7513481"),
    }
    assert (a[0]["journalnr_old"], a[0]["journalnr_new"]) == ("2026759398", "2026769396")
    assert (a[0]["id_old"], a[0]["id_new"]) == ("7213446", "7241960")
    assert {(r["regnskapstype"], r["konsern_old"], r["konsern_new"]) for r in a} == {
        ("SELSKAP", "false", "false")
    }

    (b,) = events[o["B"]]
    assert (b["endringstype"], b["op"], b["path"], b["old_value"], b["new_value"]) == (
        "Resubmitted",
        "add",
        "eiendeler.sumFordringer",
        "",
        "50",
    )

    (c,) = events[o["C"]]
    assert (c["endringstype"], c["op"], c["path"], c["new_value"]) == (
        "Revised",
        "replace",
        "resultatregnskapResultat.aarsresultat",
        "12",
    )
    assert c["journalnr_old"] == c["journalnr_new"] and c["id_old"] == c["id_new"]

    d = events[o["D"]]
    status = {
        (r["path"], r["old_value"], r["new_value"]) for r in d if r["endringstype"] == "Status"
    }
    assert ("outcome", "ok", "not_found") in status and ("http_status", "200", "404") in status
    gone = [r for r in d if r["endringstype"] == "Sletting"]
    assert sorted(r["fiscal_year"] for r in gone) == ["2024", "2025"]
    assert all(r["op"] == "remove" and r["id_new"] == "" for r in gone)
    assert {(r["konsern_old"], r["konsern_new"]) for r in gone} == {("false", "")}

    e = events[o["E"]]
    status = {
        (r["path"], r["old_value"], r["new_value"]) for r in e if r["endringstype"] == "Status"
    }
    assert ("outcome", "unsupported", "ok") in status and ("http_status", "500", "200") in status
    (new,) = [r for r in e if r["endringstype"] == "Ny"]
    assert new["op"] == "add" and len(new["new_value"]) == 64 and new["id_new"] == "7200000"

    (bare,) = events[o["F"]]
    assert bare["endringstype"] == "Resubmitted" and bare["op"] == "" and bare["path"] == ""
    assert (bare["journalnr_old"], bare["journalnr_new"]) == ("2026710000", "2026772000")

    (key,) = events[o["G"]]
    assert key["endringstype"] == "KeyChanged" and key["fiscal_year"] == "2025"
    assert (key["path"], key["old_value"], key["new_value"]) == (
        "regnskapsperiode.tilDato",
        "2024-12-31",
        "2025-12-31",
    )

    h = events[o["H"]]
    konsern = [r for r in h if r["regnskapstype"] == "KONSERN"]
    selskap = [r for r in h if r["regnskapstype"] == "SELSKAP"]
    assert [(r["endringstype"], r["path"]) for r in konsern] == [
        ("Resubmitted", "eiendeler.sumEiendeler")
    ]
    assert [(r["endringstype"], r["op"]) for r in selskap] == [("Resubmitted", "")]
    assert selskap[0]["journalnr_new"] == konsern[0]["journalnr_new"] == "2026773000"
    assert selskap[0]["event_id"] == konsern[0]["event_id"]
    assert (selskap[0]["id_old"], selskap[0]["id_new"]) == ("7130000", "7253000")
    assert (konsern[0]["id_old"], konsern[0]["id_new"]) == ("7130001", "7253001")
    assert {(r["konsern_old"], r["konsern_new"]) for r in h} == {("true", "true")}

    i = {r["endringstype"]: r for r in events[o["I"]]}
    assert i["AgedOut"]["fiscal_year"] == "2022" and i["Ny"]["fiscal_year"] == "2025"
    assert set(i) == {"AgedOut", "Ny"}

    j = events[o["J"]]
    assert [r["endringstype"] for r in j if r["op"] == "add" and r["path"] == "outcome"] == [
        "Status"
    ]
    assert "Ny" in {r["endringstype"] for r in j}

    assert o["K"] not in events
    assert manifest["events"] == {
        "Resubmitted": 4,
        "Revised": 1,
        "Status": 3,
        "Sletting": 2,
        "Ny": 3,
        "KeyChanged": 1,
        "AgedOut": 1,
    }


def test_sample_mode_ignores_organisations_missing_from_the_sample(tmp_path):
    prior_dir, current_dir = two_months(tmp_path)
    sample = tmp_path / "sample"
    shutil.copytree(current_dir, sample)
    keep = {ORG["A"], ORG["I"]}
    for name in ("accounts.csv", "organisations.csv"):
        path = sample / name
        with path.open(newline="") as stream:
            reader = csv.DictReader(stream)
            columns = reader.fieldnames
            rows = [r for r in reader if (r.get("orgnr") or r.get("_meta.orgnr")) in keep]
        with path.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\r\n")
            writer.writeheader()
            writer.writerows(rows)
    manifest = json.loads((sample / "manifest.json").read_text())
    for name in ("accounts.csv", "organisations.csv"):
        manifest["assets"].pop(name)
    (sample / "manifest.json").write_text(json.dumps(manifest))
    full = build_changelog(prior_dir, sample, tmp_path / "full")
    assert full["events"]["Sletting"] > 2 and "Status" in full["events"]
    partial = build_changelog(prior_dir, sample, tmp_path / "partial", sample=True)
    assert partial["complete"] is False
    assert partial["events"] == {"Resubmitted": 1, "AgedOut": 1, "Ny": 1}


def test_sample_mode_skips_organisations_whose_fetch_is_still_pending(tmp_path):
    prior_dir, _current_dir = two_months(tmp_path)
    state = State(tmp_path / "pending.sqlite3")
    try:
        state.start_cycle([entity(ORG["A"]), entity(ORG["I"])], "2026-11-03")
        state.record(
            ORG["A"],
            "2026-11",
            ok(f(ORG["A"], 2025, 7241960, "2026769396")),
            "2026-11-03T12:00:00+00:00",
        )
        state.failure(ORG["I"], "connection failed")
        export_release(state, tmp_path / "pending")
    finally:
        state.close()
    manifest = build_changelog(prior_dir, tmp_path / "pending", tmp_path / "log", sample=True)
    rows = read_rows(tmp_path / "log", "delta")
    assert {r["orgnr"] for r in rows} == {ORG["A"]}
    assert "Sletting" not in manifest["events"]


def test_cumulative_log_continues_event_ids(tmp_path):
    prior_dir, current_dir = two_months(tmp_path)
    first = build_changelog(prior_dir, current_dir, tmp_path / "changelog-2026-11")
    later = make_release(
        tmp_path,
        "data-2026-12",
        "2026-12-02",
        [entity(ORG["A"], form="AS")],
        {ORG["A"]: ok(f(ORG["A"], 2025, 7241960, "2026769396", **{"eiendeler.sumEiendeler": 1.0}))},
    )
    second = build_changelog(
        current_dir,
        later,
        tmp_path / "changelog-2026-12",
        previous_changelog=tmp_path / "changelog-2026-11",
    )
    delta = read_rows(tmp_path / "changelog-2026-12", "delta")
    cumulative = read_rows(tmp_path / "changelog-2026-12", "cumulative")
    assert len(cumulative) == first["dataset"]["cumulative"]["rows"] + len(delta)
    first_ids = [int(r["event_id"]) for r in read_rows(tmp_path / "changelog-2026-11", "delta")]
    assert min(int(r["event_id"]) for r in delta) == max(first_ids) + 1
    assert second["prior_cycle"] == "2026-11" and {r["release"] for r in cumulative} == {
        "2026-11",
        "2026-12",
    }
    with pytest.raises(SourceError, match="earlier cycle"):
        build_changelog(later, current_dir, tmp_path / "backwards")


def test_finish_month_publishes_changelog_and_recovers_after_a_crash(monkeypatch, tmp_path):
    prior_dir, _current_dir = two_months(tmp_path)
    remote = tmp_path / "remote"
    shutil.copytree(prior_dir, remote / "data-2026-10")
    published = ["data-2026-10"]

    def gh(*args):
        if args[0] == "api":
            return json.dumps([[{"tag_name": t, "draft": False} for t in published]])
        assert args[:2] == ("release", "download")
        target = Path(args[args.index("--dir") + 1])
        shutil.copytree(remote / args[2], target, dirs_exist_ok=True)
        return ""

    def publish(repo, directory, tag, target):
        if fail[0] and tag.startswith("changelog-"):
            fail[0] = False
            raise RuntimeError("simulated upload interruption")
        shutil.copytree(directory, remote / tag)
        published.append(tag)

    fail = [True]
    monkeypatch.setattr(release, "gh", gh)
    monkeypatch.setattr(monthly_run, "publish", publish)
    monkeypatch.setattr(release, "publish", publish)
    monkeypatch.setattr(monthly_run, "seed_file", lambda repo, state, snapshot: None)
    state = State(tmp_path / "data-2026-11.sqlite3")
    try:
        assert monthly_run.unfinished(state) and monthly_run.data_unpublished(state)
        # The data release is published; the change-log failure is recorded, not raised.
        monthly_run.finish_month("o/r", state, tmp_path / "seed.gz", tmp_path / "out1", "a" * 40)
        assert published[-1] == "data-2026-11" and state.get("changelog_published") is None
        assert "interruption" in state.get("changelog_error")
        assert monthly_run.unfinished(state) and not monthly_run.data_unpublished(state)
        monthly_run.finish_month("o/r", state, tmp_path / "seed.gz", tmp_path / "out2", "a" * 40)
        assert published[-1] == "changelog-2026-11" and not monthly_run.unfinished(state)
        assert state.get("changelog_error") is None
    finally:
        state.close()
    manifest = json.loads((remote / "changelog-2026-11/manifest.json").read_text())
    assert manifest["events"]["Resubmitted"] == 4
    assert (remote / "changelog-2026-11/changes-2026-11.csv").is_file()
    assert (remote / "changelog-2026-11/changes.csv").is_file()


def test_status_columns_missing_from_the_prior_release_are_not_changes(tmp_path):
    prior_dir, current_dir = two_months(tmp_path)
    stripped = tmp_path / "stripped"
    shutil.copytree(prior_dir, stripped)
    path = stripped / "organisations.csv"
    with path.open(newline="") as stream:
        reader = csv.DictReader(stream)
        keep = [c for c in reader.fieldnames if not c.startswith("register_")]
        rows = [{c: r[c] for c in keep} for r in reader]
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=keep, lineterminator="\r\n")
        writer.writeheader()
        writer.writerows(rows)
    manifest = json.loads((stripped / "manifest.json").read_text())
    manifest["assets"].pop("organisations.csv")
    (stripped / "manifest.json").write_text(json.dumps(manifest))
    full = build_changelog(prior_dir, current_dir, tmp_path / "full")
    partial = build_changelog(stripped, current_dir, tmp_path / "partial")
    assert partial["events"] == full["events"]
    paths = {
        r["path"] for r in read_rows(tmp_path / "partial", "delta") if r["endringstype"] == "Status"
    }
    assert "register_status" not in paths
    new_org = [r for r in read_rows(tmp_path / "partial", "delta") if r["orgnr"] == ORG["J"]]
    assert {r["path"] for r in new_org if r["endringstype"] == "Status"} <= {
        "outcome",
        "http_status",
        "organisasjonsform",
        "latest_filing_year",
    }


def test_persistent_changelog_failure_does_not_block_collection(monkeypatch, tmp_path):
    prior_dir, _current_dir = two_months(tmp_path)
    remote = tmp_path / "remote"
    shutil.copytree(prior_dir, remote / "data-2026-10")
    published = ["data-2026-10", "data-2026-11"]

    def gh(*args):
        if args[0] == "api":
            return json.dumps([[{"tag_name": t, "draft": False} for t in published]])
        raise RuntimeError("download refused")

    monkeypatch.setattr(release, "gh", gh)
    monkeypatch.setattr(monthly_run, "publish", lambda *args: None)
    collected = []

    def collect_process(args, **kwargs):
        collected.append(args)
        Path(args[args.index("--report") + 1]).write_text(json.dumps({"complete": False}))
        return SimpleNamespace(returncode=2)

    monkeypatch.setattr(monthly_run.subprocess, "run", collect_process)
    state_path = tmp_path / "data-2026-11.sqlite3"
    state = State(state_path)
    with state.db:
        state.set("cycle", "2026-11")
        state.set("cycle_completed_at", "2026-11-05T12:00:00+00:00")
        state.set("cycle_published", "2026-11")
        state.set("seed_release_tag", "checkpoint-2026-11-run-1")
    state.close()
    result = monthly_run.run_segments(
        "o/r", "a" * 40, "run", segments=1, state_path=state_path, output=tmp_path / "out"
    )
    assert collected and result == 2
    state = State(state_path)
    try:
        assert "download refused" in state.get("changelog_error")
        assert state.get("changelog_published") is None
    finally:
        state.close()


def test_window_is_shared_across_account_types_and_period_start_fixes_are_resubmissions(tmp_path):
    a, b = ORG["A"], ORG["B"]
    entities = [entity(a), entity(b)]
    prior = {
        a: ok(
            f(a, 2022, 4000000, "2023100000"),
            f(a, 2022, 4000001, "2023100000", typ="KONSERN"),
            f(a, 2023, 5000000, "2024100000"),
            f(a, 2024, 6000000, "2025100000"),
        ),
        b: ok(f(b, 2025, 7000000, "2026100000")),
    }
    fixed = f(b, 2025, 7200000, "2026700000")
    fixed["regnskapsperiode"]["fraDato"] = "2024-07-01"
    current = {
        a: ok(
            f(a, 2023, 5000000, "2024100000"),
            f(a, 2024, 6000000, "2025100000"),
            f(a, 2025, 7100000, "2026200000"),
        ),
        b: ok(fixed),
    }
    prior_dir = make_release(tmp_path, "data-2026-10", "2026-10-06", entities, prior)
    current_dir = make_release(tmp_path, "data-2026-11", "2026-11-03", entities, current)
    manifest = build_changelog(prior_dir, current_dir, tmp_path / "log")
    assert manifest["events"] == {"AgedOut": 1, "Ny": 1, "Resubmitted": 1}
    events = by_org(read_rows(tmp_path / "log", "delta"))
    aged = [r for r in events[a] if r["endringstype"] == "AgedOut"]
    assert len({r["event_id"] for r in aged}) == 1
    assert {(r["regnskapstype"], r["fiscal_year"], r["op"]) for r in aged} == {
        ("SELSKAP", "2022", "remove"),
        ("KONSERN", "2022", "remove"),
    }
    assert {(r["konsern_old"], r["konsern_new"]) for r in aged} == {("true", "")}
    (row,) = events[b]
    assert (row["endringstype"], row["path"], row["old_value"], row["new_value"]) == (
        "Resubmitted",
        "regnskapsperiode.fraDato",
        "2025-01-01",
        "2024-07-01",
    )
    assert (row["journalnr_old"], row["journalnr_new"]) == ("2026100000", "2026700000")


def test_konsern_ended_is_logged_once_when_a_group_stops_filing_consolidated_accounts(tmp_path):
    a, b = ORG["A"], ORG["B"]
    entities = [entity(a), entity(b)]
    both_2024 = [
        f(a, 2024, 6000000, "2025100000"),
        f(a, 2024, 6000001, "2025100000", typ="KONSERN"),
    ]
    steady = [
        f(b, 2024, 6100000, "2025200000"),
        f(b, 2024, 6100001, "2025200000", typ="KONSERN"),
        f(b, 2025, 7100000, "2026200000"),
        f(b, 2025, 7100001, "2026200000", typ="KONSERN"),
    ]
    selskap_2025 = f(a, 2025, 7000000, "2026100000", **{"virksomhet.morselskap": True})
    october = make_release(
        tmp_path, "data-2026-10", "2026-10-06", entities, {a: ok(*both_2024), b: ok(*steady)}
    )
    november = make_release(
        tmp_path,
        "data-2026-11",
        "2026-11-03",
        entities,
        {a: ok(*both_2024, selskap_2025), b: ok(*steady)},
    )
    manifest = build_changelog(october, november, tmp_path / "nov")
    assert manifest["events"] == {"Ny": 1, "KonsernEnded": 1}
    ended = [r for r in read_rows(tmp_path / "nov", "delta") if r["endringstype"] == "KonsernEnded"]
    assert {(r["orgnr"], r["regnskapstype"], r["fiscal_year"]) for r in ended} == {
        (a, "SELSKAP", "2025")
    }
    assert {(r["path"], r["old_value"], r["new_value"]) for r in ended} == {
        ("konsernregnskap.last_fiscal_year", "2024", ""),
        ("virksomhet.morselskap", "", "true"),
    }
    assert ended[0]["journalnr_new"] == "2026100000"
    # Unchanged next month: the same state is not reported again.
    december = make_release(
        tmp_path,
        "data-2026-12",
        "2026-12-02",
        entities,
        {a: ok(*both_2024, selskap_2025), b: ok(*steady)},
    )
    again = build_changelog(november, december, tmp_path / "dec")
    assert again["events"] == {}


def test_unrequested_organisations_and_older_table_names_do_not_create_status_events(tmp_path):
    a = ORG["A"]
    filing_a = ok(f(a, 2025, 7000000, "2026100000"))
    quiet = entity(ORG["B"], form="ENK", year=None)
    october = make_release(
        tmp_path, "data-2026-10", "2026-10-06", [entity(a), quiet], {a: filing_a}
    )
    november = make_release(
        tmp_path, "data-2026-11", "2026-11-03", [entity(a), quiet], {a: filing_a}
    )
    # A release from before 0.8.0 names the table `observations` and lists requested rows only.
    manifest = json.loads((october / "manifest.json").read_text())
    with (october / "organisations.csv").open(newline="") as stream:
        reader = csv.DictReader(stream)
        old_columns = [c for c in reader.fieldnames if c in ("orgnr", "outcome", "http_status")]
        rows = [{c: r[c] for c in old_columns} for r in reader if r["accounts_requested"] == "true"]
    (october / "organisations.csv").unlink()
    with (october / "observations.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=old_columns, lineterminator="\r\n")
        writer.writeheader()
        writer.writerows(rows)
    dataset = manifest["dataset"]
    dataset["observations"] = {**dataset.pop("organisations"), "files": ["observations.csv"]}
    manifest["assets"].pop("organisations.csv")
    (october / "manifest.json").write_text(json.dumps(manifest))
    assert build_changelog(october, november, tmp_path / "log")["events"] == {}


def test_a_resubmission_can_remove_or_add_the_konsernregnskap(tmp_path):
    a, b, c = ORG["A"], ORG["B"], ORG["C"]
    entities = [entity(a), entity(b), entity(c)]
    october = make_release(
        tmp_path,
        "data-2026-10",
        "2026-10-06",
        entities,
        {
            a: ok(
                f(a, 2025, 7228636, "2026765272"),
                f(a, 2025, 7228638, "2026765272", typ="KONSERN"),
            ),
            b: ok(f(b, 2025, 7100000, "2026100000")),
            c: ok(
                f(c, 2025, 7300000, "2026300000"),
                f(c, 2025, 7200002, "2026200000", typ="KONSERN"),
            ),
        },
    )
    november = make_release(
        tmp_path,
        "data-2026-11",
        "2026-11-03",
        entities,
        {
            # The source keeps serving the KONSERN row of the earlier submission.
            a: ok(
                f(a, 2025, 7234708, "2026767063"),
                f(a, 2025, 7228638, "2026765272", typ="KONSERN"),
            ),
            b: ok(
                f(b, 2025, 7150000, "2026150000"),
                f(b, 2025, 7150002, "2026150000", typ="KONSERN"),
            ),
            c: ok(
                f(c, 2025, 7300000, "2026300000"),
                f(c, 2025, 7200002, "2026200000", typ="KONSERN"),
            ),
        },
    )
    manifest = build_changelog(october, november, tmp_path / "log")
    assert manifest["events"] == {"Resubmitted": 2}
    assert manifest["konsern_rows_from_earlier_submissions"] == 2
    events = by_org(read_rows(tmp_path / "log", "delta"))
    removed = {r["regnskapstype"]: r for r in events[a]}
    assert len({r["event_id"] for r in events[a]}) == 1
    assert (removed["SELSKAP"]["journalnr_old"], removed["SELSKAP"]["journalnr_new"]) == (
        "2026765272",
        "2026767063",
    )
    assert (removed["SELSKAP"]["konsern_old"], removed["SELSKAP"]["konsern_new"]) == (
        "true",
        "false",
    )
    assert (
        removed["KONSERN"]["op"],
        removed["KONSERN"]["id_old"],
        removed["KONSERN"]["id_new"],
    ) == (
        "remove",
        "7228638",
        "",
    )
    added = {r["regnskapstype"]: r for r in events[b]}
    assert (added["SELSKAP"]["konsern_old"], added["SELSKAP"]["konsern_new"]) == ("false", "true")
    assert (added["KONSERN"]["op"], added["KONSERN"]["id_new"]) == ("add", "7150002")
    # A KONSERN row left from before the log began is not an event.
    assert c not in events


def test_a_change_log_in_an_older_layout_is_rebuilt_from_the_data_releases(monkeypatch, tmp_path):
    october, november = two_months(tmp_path)
    december = make_release(
        tmp_path,
        "data-2026-12",
        "2026-12-02",
        [entity(ORG["A"], form="AS")],
        {ORG["A"]: ok(f(ORG["A"], 2025, 7241960, "2026769396", **{"eiendeler.sumEiendeler": 1.0}))},
    )
    old = tmp_path / "changelog-2026-11"
    build_changelog(october, november, old)
    manifest = json.loads((old / "manifest.json").read_text())
    manifest["dataset"]["schema_version"] = "regnskap-changelog-csv/v1"
    (old / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(SourceError, match="another layout"):
        build_changelog(november, december, tmp_path / "refused", previous_changelog=old)
    remote = {"data-2026-10": october, "data-2026-11": november, "changelog-2026-11": old}
    published = []

    def gh(*args):
        if args[0] == "api":
            return json.dumps(
                [[{"tag_name": t, "draft": False} for t in [*remote, "data-2026-12"]]]
            )
        target = Path(args[args.index("--dir") + 1])
        shutil.copytree(remote[args[2]], target, dirs_exist_ok=True)
        return ""

    monkeypatch.setattr(release, "gh", gh)
    monkeypatch.setattr(
        release, "publish", lambda repo, directory, tag, target: published.append(tag)
    )
    out = tmp_path / "out"
    shutil.copytree(december, out / "data-2026-12")
    built = release.publish_changelog("o/r", "2026-12", out, "a" * 40)
    assert published == ["changelog-2026-12"] and built["prior_cycle"] == "2026-11"
    cumulative = read_rows(out / "changelog-2026-12", "cumulative")
    assert list(cumulative[0]) == COLUMNS
    assert {r["release"] for r in cumulative} == {"2026-11", "2026-12"}
    ids = [int(r["event_id"]) for r in cumulative]
    assert ids == sorted(ids) and ids[0] == 1
