import json
import subprocess

import pytest

from scripts import release


def test_resume_never_bootstraps_after_api_failure(monkeypatch, tmp_path):
    def denied(*args):
        raise subprocess.CalledProcessError(1, "gh")

    monkeypatch.setattr(release, "gh", denied)
    with pytest.raises(subprocess.CalledProcessError):
        release.resume("owner/repo", tmp_path / "download", tmp_path / "state", bootstrap=True)
    assert not (tmp_path / "state").exists()


def test_resume_requires_explicit_bootstrap_for_empty_release_list(monkeypatch, tmp_path):
    monkeypatch.setattr(release, "gh", lambda *args: "[[]]")
    with pytest.raises(RuntimeError, match="explicit bootstrap"):
        release.resume("owner/repo", tmp_path / "download", tmp_path / "state")
    release.resume("owner/repo", tmp_path / "download", tmp_path / "state", bootstrap=True)


def test_resume_uses_latest_published_data_checkpoint_including_prerelease(monkeypatch, tmp_path):
    calls = []

    def fake_gh(*args):
        calls.append(args)
        if args[0] == "api":
            return json.dumps(
                [
                    [
                        {"tag_name": "v0.2.0", "draft": False, "published_at": "2026-10-09"},
                        {"tag_name": "data-1", "draft": False, "published_at": "2026-10-01"},
                        {
                            "tag_name": "data-2",
                            "draft": False,
                            "prerelease": True,
                            "published_at": "2026-10-02",
                        },
                        {"tag_name": "data-3", "draft": True, "published_at": None},
                    ]
                ]
            )
        return ""

    restored = []
    monkeypatch.setattr(release, "gh", fake_gh)
    monkeypatch.setattr(release, "restore_checkpoint", lambda *args: restored.append(args))
    release.resume("owner/repo", tmp_path / "download", tmp_path / "state")
    assert calls[1][2] == "data-2"
    assert len(restored) == 1


def test_publish_keeps_draft_if_uploaded_asset_set_is_incomplete(monkeypatch, tmp_path):
    directory = tmp_path / "assets"
    directory.mkdir()
    (directory / "manifest.json").write_text(
        json.dumps({"complete": True, "entities_date": "2026-10-06", "counts": {}})
    )
    calls = []

    def fake_gh(*args):
        calls.append(args)
        return '{"assets": []}' if args[1] == "view" else ""

    monkeypatch.setattr(release, "gh", fake_gh)
    with pytest.raises(RuntimeError, match="remains a draft"):
        release.publish("owner/repo", directory, "data-1", "a" * 40)
    assert not any(call[1] == "edit" for call in calls)


def test_source_error_clears_previous_complete_status(monkeypatch, state, tmp_path):
    from brreg_fetcher import cli
    from brreg_fetcher.client import SourceError

    with state.db:
        state.set("last_run", '{"complete": true}')

    def fail(*args, **kwargs):
        raise SourceError("announcement page incomplete")

    monkeypatch.setattr(cli, "collect", fail)
    assert cli.main(["collect", "--state", str(tmp_path / "checkpoint.sqlite3")]) == 1
    assert json.loads(state.get("last_run"))["complete"] is False
