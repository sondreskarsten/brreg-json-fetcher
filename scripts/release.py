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

from brreg_fetcher.export import restore_asset, restore_checkpoint, sha256_file
from brreg_fetcher.state import State


def gh(*args):
    return subprocess.check_output(["gh", *args], text=True)


def resume(repo, directory, state, bootstrap=False, today=None):
    # A failed listing/download is never treated as a missing checkpoint.
    pages = json.loads(gh("api", "--paginate", "--slurp", f"repos/{repo}/releases"))
    releases = [
        r
        for page in pages
        for r in page
        if r["tag_name"].startswith(("data-", "checkpoint-")) and not r["draft"]
    ]
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
    if (
        manifest.get("kind") == "data"
        and manifest.get("complete")
        and manifest.get("cycle") == month
    ):
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
    if manifest.get("kind") == "data" and manifest.get("complete"):
        restored = State(state)
        try:
            with restored.db:
                restored.set("cycle_published", manifest["cycle"])
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


def publish(repo, directory, tag, target):
    manifest = json.loads((directory / "manifest.json").read_text())
    checkpoint = manifest.get("kind") == "checkpoint"
    cycle = manifest.get("cycle")
    if checkpoint:
        if not tag.startswith("checkpoint-"):
            raise RuntimeError("Recovery checkpoints need a checkpoint- tag")
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
    notes.write_text(
        f"BRREG {'recovery checkpoint' if checkpoint else 'monthly data'}: {cycle}.\n\n"
        f"Seed download date: {manifest['entities_date']}. "
        f"Collection window: {manifest.get('collection_started_at')} to "
        f"{manifest.get('collection_finished_at') or 'still running'}.\n\n"
        f"```json\n{json.dumps(manifest['counts'], indent=2)}\n```\n\n"
        + (
            "This is an intermediate recovery checkpoint, not a completed monthly dataset.\n\n"
            if checkpoint
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
            f"BRREG {'checkpoint' if checkpoint else 'data'} {cycle}",
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
    p.add_argument("command", choices=["resume", "publish", "software"])
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
    elif args.command == "software":
        if not args.tag or not args.tag.startswith("v") or not args.target:
            p.error("software requires a v tag and an explicit target commit")
        software(args.repo, args.directory, args.tag, args.target)
    else:
        if not args.tag or not args.tag.startswith(("data-", "checkpoint-")) or not args.target:
            p.error("publish requires a data- or checkpoint- tag and an explicit target commit")
        publish(args.repo, args.directory, args.tag, args.target)


if __name__ == "__main__":
    main()
