"""Restore/publish data releases with gh; never publish a partial asset upload."""

import argparse
import json
import os
import re
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from brreg_fetcher.attribution import ATTRIBUTION, LICENCE_URL, REPOSITORY
from brreg_fetcher.changelog import build_changelog
from brreg_fetcher.export import restore_asset, restore_checkpoint, sha256_file
from brreg_fetcher.state import State


def gh(*args):
    return subprocess.check_output(["gh", *args], text=True)


def published_releases(repo):
    pages = json.loads(gh("api", "--paginate", "--slurp", f"repos/{repo}/releases"))
    return [r for page in pages for r in page if not r["draft"]]


def previous_release(releases, prefix, cycle):
    """The newest published `{prefix}-YYYY-MM` release for a cycle before `cycle`."""
    cycles = []
    for item in releases:
        match = re.fullmatch(rf"{prefix}-(\d{{4}}-\d{{2}})", item["tag_name"])
        if match and match.group(1) < cycle:
            cycles.append(match.group(1))
    return f"{prefix}-{max(cycles)}" if cycles else None


def download_release(repo, tag, directory, *patterns):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    args = ["release", "download", tag, "--repo", repo, "--dir", str(directory), "--clobber"]
    for pattern in patterns:
        args += ["--pattern", pattern]
    gh(*args)
    return directory


def resume(repo, directory, state, bootstrap=False, today=None):
    # A failed listing/download is never treated as a missing checkpoint.
    published = published_releases(repo)
    releases = [r for r in published if r["tag_name"].startswith(("data-", "checkpoint-"))]
    if not releases:
        if not bootstrap:
            raise RuntimeError(
                "No checkpoint found; use the explicit bootstrap input for the first month"
            )
        print("Starting the first monthly collection")
        return True

    def order(item):
        match = re.match(r"(?:data|checkpoint)-(\d{4}-\d{2})(?:-|$)", item["tag_name"])
        cycle = match.group(1) if match else ""
        final = item["tag_name"] == f"data-{cycle}"
        return cycle, final, item["published_at"]

    release = max(releases, key=order)
    directory.mkdir(parents=True, exist_ok=True)
    gh(
        "release",
        "download",
        release["tag_name"],
        "--repo",
        repo,
        "--dir",
        str(directory),
        "--pattern",
        "manifest.json",
    )
    manifest = json.loads((directory / "manifest.json").read_text())
    if manifest.get("format_version") != 1:
        raise RuntimeError("Unsupported recovery manifest")
    month = (today or datetime.now(ZoneInfo("Europe/Oslo")).date()).strftime("%Y-%m")
    complete = manifest.get("kind") == "data" and manifest.get("complete")
    cycle = manifest.get("cycle")
    # A change log is owed when an earlier data release exists to compare with and the
    # log for this cycle is not published yet; it is recovered like the data release.
    changelog_owed = bool(
        complete
        and previous_release(published, "data", cycle)
        and f"changelog-{cycle}" not in {r["tag_name"] for r in published}
    )
    if complete and cycle == month and not changelog_owed:
        print(f"Monthly release {release['tag_name']} is already complete; nothing to collect")
        return False
    gh(
        "release",
        "download",
        release["tag_name"],
        "--repo",
        repo,
        "--dir",
        str(directory),
        "--pattern",
        "checkpoint.sqlite3.gz*",
    )
    restore_checkpoint(directory, state)
    if complete:
        restored = State(state)
        try:
            with restored.db:
                restored.set("cycle_published", cycle)
                if not changelog_owed:
                    restored.set("changelog_published", cycle)
        finally:
            restored.close()
    print(f"Restored {release['tag_name']}")
    return True


def seed_file(repo, state, destination):
    """Recover the exact initial download from the first checkpoint of this month."""
    destination = Path(destination)
    expected = state.get("seed_sha256")
    if destination.exists():
        if not expected or sha256_file(destination) != expected:
            raise RuntimeError("Local source download differs from the frozen monthly seed")
        return destination
    tag = state.get("seed_release_tag")
    if not tag or not expected:
        raise RuntimeError("Monthly checkpoint is missing its source-download reference")
    with tempfile.TemporaryDirectory(prefix="brreg-source-") as tmp:
        gh(
            "release",
            "download",
            tag,
            "--repo",
            repo,
            "--dir",
            tmp,
            "--pattern",
            "manifest.json",
            "--pattern",
            "enheter.json.gz*",
        )
        restore_asset(tmp, "enheter.json.gz", destination)
    if sha256_file(destination) != expected:
        raise RuntimeError("Recovered source download differs from the frozen monthly seed")
    return destination


def publish_changelog(repo, cycle, output, target):
    """Compare this month's data release with the previous one and publish the log."""
    releases = published_releases(repo)
    prior_tag = previous_release(releases, "data", cycle)
    if prior_tag is None:
        print(f"No data release before {cycle}; nothing to compare")
        return None
    current_dir = output / f"data-{cycle}"
    if not (current_dir / "manifest.json").is_file():
        download_release(
            repo,
            f"data-{cycle}",
            current_dir,
            "manifest.json",
            "accounts*.csv",
            "observations*.csv",
        )
    compare = output / "compare"
    prior_dir = download_release(
        repo, prior_tag, compare / prior_tag, "manifest.json", "accounts*.csv", "observations*.csv"
    )
    previous_tag = previous_release(releases, "changelog", cycle)
    previous_dir = None
    if previous_tag:
        previous_dir = download_release(
            repo, previous_tag, compare / previous_tag, "manifest.json", "changes*.csv"
        )
    changelog_dir = output / f"changelog-{cycle}"
    manifest = build_changelog(
        prior_dir, current_dir, changelog_dir, previous_changelog=previous_dir
    )
    publish(repo, changelog_dir, f"changelog-{cycle}", target)
    return manifest


def publish(repo, directory, tag, target):
    manifest = json.loads((directory / "manifest.json").read_text())
    checkpoint = manifest.get("kind") == "checkpoint"
    changelog = manifest.get("kind") == "changelog"
    cycle = manifest.get("cycle")
    if checkpoint:
        if not tag.startswith("checkpoint-"):
            raise RuntimeError("Recovery checkpoints need a checkpoint- tag")
    elif changelog:
        if tag != f"changelog-{cycle}" or not manifest.get("complete"):
            raise RuntimeError("Change logs need a changelog- tag and a full comparison")
    elif (
        not manifest.get("complete")
        or not cycle
        or tag != f"data-{cycle}"
        or "enheter.json.gz" not in manifest["assets"]
    ):
        raise RuntimeError(
            "Monthly data releases require a completed cycle and its source download"
        )
    notes = directory.parent / "release-notes.md"
    kind = "recovery checkpoint" if checkpoint else "change log" if changelog else "monthly data"
    notes.write_text(
        f"Unofficial BRREG {kind}: {cycle}.\n\n"
        f"{ATTRIBUTION} [NLOD 2.0]({LICENCE_URL}).\n\n"
        "Independent mirror by sondreskarsten; not operated or endorsed by Brønnøysundregistrene. "
        "Monthly selection and CSV conversion are changes made by this mirror. "
        f"[Sources, licence scope and changes]({REPOSITORY}/blob/main/DATA_LICENSE.md). "
        "See DATA_NOTICE.md and manifest.json in the assets.\n\n"
        + (
            f"Changes between data-{manifest['prior_cycle']} and data-{cycle}, one row per field "
            "operation; rows of one transition share event_id. changes.csv is the cumulative log "
            f"since the first comparison.\n\n```json\n{json.dumps(manifest['events'], indent=2)}\n```\n\n"
            if changelog
            else f"Seed download date: {manifest['entities_date']}. "
            f"Collection window: {manifest.get('collection_started_at')} to "
            f"{manifest.get('collection_finished_at') or 'still running'}.\n\n"
            f"```json\n{json.dumps(manifest['counts'], indent=2)}\n```\n\n"
        )
        + (
            "This is an intermediate recovery checkpoint, not a completed monthly dataset.\n\n"
            if checkpoint
            else ""
            if changelog
            else "The monthly queue is complete. Check observations for 404 and unsupported-plan outcomes. "
            "Account values were observed across the collection window, not at one instant.\n\n"
        )
        + "Verify SHA256SUMS. Large files use ordered parts described by manifest.json.\n"
    )
    pages = json.loads(gh("api", "--paginate", "--slurp", f"repos/{repo}/releases"))
    existing = next((r for page in pages for r in page if r["tag_name"] == tag), None)
    if existing and not existing["draft"]:
        raise RuntimeError("Refusing to overwrite an already published release")
    if existing is None:
        gh(
            "release",
            "create",
            tag,
            "--repo",
            repo,
            "--target",
            target,
            "--draft",
            "--title",
            f"BRREG {'checkpoint' if checkpoint else 'changelog' if changelog else 'data'} {cycle}",
            "--notes-file",
            str(notes),
        )
    files = sorted(p for p in directory.iterdir() if p.is_file())
    for path in files:
        gh("release", "upload", tag, str(path), "--repo", repo, "--clobber")
    remote = json.loads(gh("release", "view", tag, "--repo", repo, "--json", "assets"))
    actual = {a["name"]: a["size"] for a in remote["assets"]}
    if actual != {p.name: p.stat().st_size for p in files}:
        raise RuntimeError("Uploaded asset set differs from local files; release remains a draft")
    gh(
        "release",
        "edit",
        tag,
        "--repo",
        repo,
        "--draft=false",
        "--latest=false",
        f"--prerelease={'true' if checkpoint else 'false'}",
    )


def software(repo, directory, tag, target):
    pages = json.loads(gh("api", "--paginate", "--slurp", f"repos/{repo}/releases"))
    existing = next((r for page in pages for r in page if r["tag_name"] == tag), None)
    if existing and not existing["draft"]:
        raise RuntimeError("Refusing to replace assets of a published software release")
    if existing is None:
        gh(
            "release",
            "create",
            tag,
            "--repo",
            repo,
            "--target",
            target,
            "--verify-tag",
            "--draft",
            "--title",
            tag,
            "--notes-file",
            "CHANGELOG.md",
        )
    files = sorted(
        [*directory.glob("*.whl"), *directory.glob("*.tar.gz"), directory / "SHA256SUMS"]
    )
    for path in files:
        gh("release", "upload", tag, str(path), "--repo", repo, "--clobber")
    remote = json.loads(gh("release", "view", tag, "--repo", repo, "--json", "assets"))
    if {a["name"]: a["size"] for a in remote["assets"]} != {
        p.name: p.stat().st_size for p in files
    }:
        raise RuntimeError("Software release assets are incomplete; release remains a draft")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("command", choices=["resume", "publish", "software", "changelog"])
    p.add_argument(
        "--repo",
        default=os.environ.get("GITHUB_REPOSITORY"),
        required=not os.environ.get("GITHUB_REPOSITORY"),
    )
    p.add_argument("--directory", type=Path, required=True)
    p.add_argument("--state", type=Path, default=Path("data/checkpoint.sqlite3"))
    p.add_argument("--bootstrap", action="store_true")
    p.add_argument("--tag")
    p.add_argument("--target")
    args = p.parse_args()
    if args.command == "resume":
        needed = resume(args.repo, args.directory, args.state, args.bootstrap)
        if os.environ.get("GITHUB_OUTPUT"):
            with open(os.environ["GITHUB_OUTPUT"], "a") as out:
                out.write(f"needs_run={str(needed).lower()}\n")
    elif args.command == "changelog":
        if not args.tag or not args.tag.startswith("data-") or not args.target:
            p.error("changelog requires the data- tag of the current month and a target commit")
        publish_changelog(args.repo, args.tag.removeprefix("data-"), args.directory, args.target)
    elif args.command == "software":
        if not args.tag or not args.tag.startswith("v") or not args.target:
            p.error("software requires a v tag and an explicit target commit")
        software(args.repo, args.directory, args.tag, args.target)
    else:
        if (
            not args.tag
            or not args.tag.startswith(("data-", "checkpoint-", "changelog-"))
            or not args.target
        ):
            p.error("publish requires a data-, checkpoint- or changelog- tag and a target commit")
        publish(args.repo, args.directory, args.tag, args.target)


if __name__ == "__main__":
    main()
