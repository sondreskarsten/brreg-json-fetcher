import csv
import json
from decimal import Decimal

from conftest import entity, filing, response

from brreg_fetcher.client import AccountResponse
from brreg_fetcher.export import export_release
from brreg_fetcher.population import FYLKER, NACE2, age_years, describe, fylke, nace2
from brreg_fetcher.state import State


def registered(orgnr, form, kommune, nace, employees=None, vat=False, **extra):
    return entity(
        orgnr,
        form=form,
        forretningsadresse={"kommunenummer": kommune} if kommune else None,
        naeringskode1={"kode": nace} if nace else None,
        antallAnsatte=employees,
        registrertIMvaregisteret=vat,
        registrertIForetaksregisteret=form != "ENK",
        registreringsdatoEnhetsregisteret="2016-10-06",
        kapital={"belop": 30000.0} if form == "AS" else None,
        **extra,
    )


def read(directory, name):
    with (directory / f"{name}.csv").open(newline="") as stream:
        return list(csv.DictReader(stream))


def test_binning_rules():
    assert fylke("0301") == "03" and fylke(None) == "unknown" and fylke("") == "unknown"
    assert nace2("43.210") == "43" and nace2(None) == "unknown"
    assert age_years("2016-10-06", "2026-10-06") == 10.0
    assert age_years(None, "2026-10-06") is None
    assert "03" in FYLKER and NACE2["43"].startswith("Specialised construction")


def test_describe_quantiles_and_spread():
    assert describe([]) == {
        "n": 0,
        "mean": "",
        "sd": "",
        "p10": "",
        "p25": "",
        "median": "",
        "p75": "",
        "p90": "",
        "min": "",
        "max": "",
    }
    one = describe([5.0])
    assert one["n"] == 1 and one["mean"] == 5 and one["sd"] == "" and one["median"] == 5
    five = describe([1.0, 2.0, 3.0, 4.0, 5.0])
    assert (five["mean"], five["median"], five["p25"], five["p75"]) == (3, 3, 2, 4)
    assert five["sd"] == 1.58 and (five["min"], five["max"]) == (1, 5)


def test_population_tables_cover_every_form_and_join_accounts_coverage(tmp_path):
    state = State(tmp_path / "s.sqlite3")
    try:
        state.start_cycle(
            [
                registered("100000001", "AS", "0301", "43.210", employees=11, vat=True),
                registered("100000002", "AS", "1108", "43.210", employees=None, vat=True),
                registered("100000003", "ENK", "0301", "90.030", employees=None, vat=False),
                registered("100000004", "ENK", None, None, employees=2, vat=True, year=None),
                registered("100000005", "BANK", "0301", "64.190", employees=50, vat=False),
            ],
            "2026-10-06",
        )
        state.record("100000001", "2026-10", response(filing(orgnr="100000001")), "2026-10-06")
        state.record("100000002", "2026-10", AccountResponse(404, b""), "2026-10-06")
        state.record("100000003", "2026-10", response(filing(orgnr="100000003")), "2026-10-06")
        error = '{"message":"oppstillingsplan som ikke er stottet (BANK)"}'
        state.record(
            "100000005",
            "2026-10",
            AccountResponse(500, error.encode(), message=error),
            "2026-10-06",
        )
        with state.db:
            state.set("cycle_completed_at", "2026-10-06T12:00:00+00:00")
        manifest = export_release(state, tmp_path / "release")
    finally:
        state.close()
    out = tmp_path / "release"
    population = manifest["population"]
    assert population["entities"] == 5
    assert population["by_form"] == {"AS": 2, "BANK": 1, "ENK": 2}
    assert population["enk"]["n"] == 2 and population["enk"]["exits"] == 0
    by_form = {r["organisasjonsform"]: r for r in read(out, "register_by_form")}
    assert by_form["AS"]["n"] == "2" and by_form["AS"]["n_ok"] == "1"
    assert by_form["AS"]["n_not_found"] == "1" and by_form["AS"]["coverage_ratio"] == "0.500000"
    assert (
        by_form["AS"]["share_capital_n"] == "2" and by_form["AS"]["share_capital_mean"] == "30000"
    )
    assert by_form["AS"]["employees_n"] == "1" and by_form["AS"]["employees_mean"] == "11"
    assert by_form["AS"]["age_years_median"] == "10"
    assert by_form["ENK"]["n_in_fetch_universe"] == "1" and by_form["ENK"]["n_ok"] == "1"
    assert by_form["ENK"]["n_not_in_universe"] == "1" and by_form["ENK"]["n_filed_year"] == "1"
    assert by_form["BANK"]["n_unsupported"] == "1" and by_form["BANK"]["n_filings"] == "0"
    assert by_form["AS"]["n_filings"] == "1" and by_form["AS"]["share_of_total"] == "0.400000"
    assert by_form["AS"]["n_listed"] == "2" and by_form["AS"]["n_removed"] == "0"
    assert population["previous_snapshot_date"] is None
    full = read(out, "register_population")
    cells = {
        (r["organisasjonsform"], r["fylke"], r["nace2"], r["has_employees"], r["vat_registered"])
        for r in full
    }
    assert ("ENK", "unknown", "unknown", "yes", "yes") in cells
    assert ("AS", "03", "43", "yes", "yes") in cells and ("AS", "11", "43", "no", "yes") in cells
    assert all(r["share_of_form"] in ("0.500000", "1.000000") for r in full)
    assert read(out, "register_changes") == []
    codebook = read(out, "register_codebook")
    assert {"dimension": "organisasjonsform", "code": "ENK", "label": "Form ENK"} in codebook
    assert any(r["dimension"] == "fylke" and r["code"] == "03" for r in codebook)
    assert any(r["dimension"] == "rule" and r["code"] == "coverage_ratio" for r in codebook)
    assert set(manifest["population"]["tables"]) == {
        "register_population",
        "register_by_form",
        "register_by_form_fylke",
        "register_by_form_nace2",
        "register_by_form_employees_vat",
        "register_changes",
        "register_codebook",
    }
    assert "register_population.csv" in manifest["assets"]


def test_entries_and_exits_including_enk_are_counted_by_form_fylke_nace(tmp_path):
    state = State(tmp_path / "s.sqlite3")
    try:
        october = [
            registered("100000001", "AS", "0301", "43.210"),
            registered("100000002", "AS", "0301", "43.210"),
            registered("100000003", "ENK", "4601", "90.030", year=None),
            registered("100000004", "ENK", "4601", "90.030", year=None),
        ]
        state.start_cycle(october, "2026-10-06")
        for orgnr in ("100000001", "100000002"):
            state.record(orgnr, "2026-10", response(filing(orgnr=orgnr)), "2026-10-06")
        with state.db:
            state.set("cycle_completed_at", "2026-10-06T12:00:00+00:00")
        november = [
            registered("100000001", "AS", "0301", "43.210"),
            registered("100000003", "ENK", "4601", "90.030", year=None),
            registered("100000005", "ENK", "1108", "47.110", year=None),
            registered("100000006", "NUF", "0301", "62.010"),
        ]
        state.start_cycle(november, "2026-11-02")
        state.record_register("100000002", "deleted", "2026-10-20", "2026-11-02")
        manifest = export_release(state, tmp_path / "release")
    finally:
        state.close()
    changes = {
        (r["organisasjonsform"], r["fylke"], r["nace2"]): r
        for r in read(tmp_path / "release", "register_changes")
    }
    assert changes[("AS", "03", "43")]["exits"] == "1"
    assert changes[("AS", "03", "43")]["exit_deleted"] == "1"
    assert changes[("ENK", "46", "90")]["exits"] == "1"
    assert changes[("ENK", "46", "90")]["exit_unchecked"] == "1"
    assert changes[("ENK", "11", "47")]["entries"] == "1"
    assert changes[("NUF", "03", "62")]["entries"] == "1"
    population = manifest["population"]
    assert population["enk"] == {
        "n": 3,
        "entries": 1,
        "exits": 1,
        "exit_deleted": 0,
        "exit_not_found": 0,
        "exit_still_registered": 0,
        "exit_unchecked": 1,
    }
    assert population["changes_by_form"] == {
        "AS": {"entries": 0, "exits": 1},
        "ENK": {"entries": 1, "exits": 1},
        "NUF": {"entries": 1, "exits": 0},
    }
    by_form = {r["organisasjonsform"]: r for r in read(tmp_path / "release", "register_by_form")}
    # The exited AS stays in the population and in the fetch universe, flagged as removed.
    assert by_form["AS"]["n"] == "2" and by_form["AS"]["n_in_fetch_universe"] == "2"
    assert by_form["AS"]["n_listed"] == "1" and by_form["AS"]["n_removed"] == "1"
    assert population["previous_snapshot_date"] == "2026-10-06"

    # December: the same organisation is still absent but is not an exit again.
    state = State(tmp_path / "s.sqlite3")
    try:
        for row in list(state.todo()):
            state.record(row["orgnr"], "2026-11", AccountResponse(404, b""), "2026-11-03")
        with state.db:
            state.set("cycle_completed_at", "2026-11-05T12:00:00+00:00")
        state.start_cycle(november, "2026-12-01")
        manifest = export_release(state, tmp_path / "december")
    finally:
        state.close()
    assert read(tmp_path / "december", "register_changes") == []
    assert manifest["population"]["changes_by_form"] == {}
    by_form = {r["organisasjonsform"]: r for r in read(tmp_path / "december", "register_by_form")}
    assert by_form["AS"]["n_removed"] == "1" and by_form["ENK"]["n_removed"] == "1"


def test_schema_four_checkpoint_gains_population_columns_and_defers_the_summary(tmp_path):
    path = tmp_path / "s.sqlite3"
    state = State(path)
    try:
        state.start_cycle([entity()], "2026-10-06")
        state.record("923609016", "2026-10", response(filing()), "2026-10-06")
        with state.db:
            for column in ("first_seen", "kommunenummer", "naeringskode", "kapital"):
                state.db.execute(f"ALTER TABLE entities DROP COLUMN {column}")
            state.set("schema_version", "4")
            state.set("cycle_completed_at", "2026-10-06T12:00:00+00:00")
            state.db.execute(
                "DELETE FROM meta WHERE key IN ('register_attributes_date', 'previous_entities_date')"
            )
    finally:
        state.close()
    state = State(path)
    try:
        assert state.get("schema_version") == "5"
        row = state.db.execute("SELECT first_seen, observed_on FROM entities").fetchone()
        assert row["first_seen"] == row["observed_on"] == "2026-10-06"
        assert json.loads(state.get("organisasjonsform_labels")) == {"AS": "Form AS"}
        # Exporting before the next seed publishes no population tables built from NULLs.
        manifest = export_release(state, tmp_path / "recovered")
        assert manifest["population"] is None
        assert not (tmp_path / "recovered/register_population.csv").exists()
        assert (tmp_path / "recovered/accounts.csv").exists()
        state.start_cycle([entity(), entity("974760673", form="NUF")], "2026-11-02")
        manifest = export_release(state, tmp_path / "november")
        assert manifest["population"]["entities"] == 2
        assert manifest["population"]["changes_by_form"] == {"NUF": {"entries": 1, "exits": 0}}
    finally:
        state.close()


def test_register_attributes_accept_streamed_decimal_numbers():
    from brreg_fetcher.state import register_attributes

    row = register_attributes(
        {
            "forretningsadresse": {"kommunenummer": "0301"},
            "naeringskode1": {"kode": "43.210"},
            "antallAnsatte": 11,
            "registrertIMvaregisteret": True,
            "kapital": {"belop": Decimal("2375000.0")},
            "registreringsdatoEnhetsregisteret": "1995-02-19",
        }
    )
    assert row[2] == 11 and row[3] == 1 and row[9] == 2375000.0
    assert register_attributes({"antallAnsatte": None, "kapital": {"belop": "n/a"}})[2:10:7] == (
        None,
        None,
    )
