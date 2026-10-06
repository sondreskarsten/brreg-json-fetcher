from datetime import date

import pytest
from conftest import entity, filing, response

from brreg_fetcher.announcements import Announcement, announcements_for_day, parse_page
from brreg_fetcher.client import SourceError


def test_entity_universe_changes_and_atomic_bad_snapshot(state):
    state.sync_entities([entity(), entity("974760673", "")], "2026-10-01")
    assert state.summary()["eligible_entities"] == 1
    state.sync_entities([entity(year="2026"), entity("974760673", "2025")], "2026-10-02")
    assert state.summary()["eligible_entities"] == 2
    assert state.summary()["pending_signals"] == 3
    with pytest.raises(SourceError):
        state.sync_entities([entity(year="2027"), entity("invalid")], "2026-10-03")
    assert state.get("entities_date") == "2026-10-02"
    assert state.summary()["pending_signals"] == 3
    state.sync_entities([entity(year="")], "2026-10-03")
    assert state.summary()["eligible_entities"] == 0


def test_no_new_load_means_no_new_requests_but_queue_resumes(state):
    state.sync_entities([entity()], "2026-10-01")
    assert state.schedule(set()) == 0
    assert not list(state.todo())
    state.schedule({"load-a"})
    assert len(list(state.todo())) == 1
    state.record("923609016", "a", response(filing()), "2026-10-01T10:00:00+00:00")
    state.add_announcements([Announcement("123", "923609016")], "2026-10-10")
    assert state.schedule({"load-a"}) == 0
    assert not list(state.todo())
    assert state.schedule({"load-a", "load-b"}) == 1
    assert len(list(state.todo())) == 1
    state.failure("923609016", "network error")
    state.schedule({"load-a", "load-b"})
    assert len(list(state.todo())) == 1


@pytest.mark.parametrize(
    "first_seen,answered",
    [("2026-10-02", False), ("2026-10-03", True), ("2026-10-10", True), ("2026-11-01", True)],
)
def test_signal_answer_window_inclusive_and_no_future_expiry(state, first_seen, answered):
    state.sync_entities([entity()], "2026-10-01")
    state.add_announcements([Announcement("123", "923609016")], "2026-10-10")
    state.record("923609016", "a", response(filing()), first_seen + "T12:00:00+00:00")
    row = state.db.execute(
        "SELECT answered_by FROM signals WHERE kind='announcement_70'"
    ).fetchone()
    assert (row[0] == 1) == answered


def test_same_year_resubmission_and_content_revision(state):
    state.sync_entities([entity()], "2026-10-01")
    a = state.record("923609016", "a", response(filing()), "2026-10-01T12:00:00+00:00")
    assert a["new_ids"] == 1
    state.add_announcements([Announcement("123", "923609016")], "2026-10-10")
    b = state.record(
        "923609016", "b", response(filing(eiendeler={"goodwill": 123})), "2026-10-11T12:00:00+00:00"
    )
    assert b["changed_ids"] == 1 and b["new_ids"] == 0
    assert state.summary()["pending_signals"] == 1
    c = state.record("923609016", "c", response(filing(id=2)), "2026-10-12T12:00:00+00:00")
    assert c["new_ids"] == 1 and state.summary()["pending_signals"] == 0
    assert state.summary()["historical_filings"] == 2
    assert state.summary()["current_filings"] == 1
    assert state.db.execute("SELECT count(*) FROM responses").fetchone()[0] == 3


def page(*hits, count=None):
    count = len(hits) if count is None else count
    return f"<p>Antall treff <b>{count}</b></p>" + "".join(
        f'<a href="hent_en.jsp?kid={kid}&amp;sokeverdi={orgnr}">Godkjente årsregnskap</a>'
        for kid, orgnr in hits
    )


def test_announcement_dedup_and_fail_closed():
    hit = ("123", "923609016")
    assert len(parse_page(page(hit, hit, count=1))) == 1
    assert parse_page(page(count=0)) == set()
    assert parse_page("Antall treff overstiger 5000") is None
    with pytest.raises(SourceError, match="Unrecognised"):
        parse_page("<html>Ugyldig input</html>")
    with pytest.raises(SourceError, match="reports 2"):
        parse_page(page(hit, count=2))


def test_overflow_splits_by_region_then_county():
    class Fake:
        def __init__(self):
            self.calls = []

        def announcement_html(self, day, region="0", county=None):
            self.calls.append((region, county))
            if region == "0" or (region == "100" and county is None):
                return "Antall treff overstiger 5000"
            if county:
                return page((county, "923609016"))
            return page()

        def counties(self, region):
            return ["18", "55", "56"]

    fake = Fake()
    assert len(announcements_for_day(fake, date(2026, 10, 1))) == 3
    assert ("999", None) in fake.calls
    assert ("100", "55") in fake.calls


def test_county_overflow_is_not_silently_checkpointed():
    class Fake:
        def announcement_html(self, *args):
            return "Antall treff overstiger 5000"

        def counties(self, region):
            return ["18"]

    with pytest.raises(SourceError, match="cannot checkpoint"):
        announcements_for_day(Fake(), date(2026, 10, 1))


def test_reconcile_only_schedules_on_new_load(state):
    state.sync_entities([entity()], "2026-10-01")
    state.schedule({"load-a"})
    state.record("923609016", "a", response(filing()), "2026-10-01T12:00:00+00:00")
    state.schedule({"load-a"}, reconcile=True)
    assert not list(state.todo())
    state.schedule({"load-b"}, reconcile=True)
    assert len(list(state.todo())) == 1
