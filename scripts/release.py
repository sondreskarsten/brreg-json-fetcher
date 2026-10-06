"""Restore/publish data releases with gh; never publish a partial asset upload."""

import argparse
import json
import os
import subprocess
from pathlib import Path

from brreg_fetcher.export import restore_checkpoint


def gh(*args):
    return subprocess.check_output(["gh", *args], text=True)


def resume(repo, directory, state, bootstrap=False):
    # API/auth failures propagate. Only a successful empty listing can bootstrap.
    pages = json.loads(gh("api", "--paginate", "--slurp", f"repos/{repo}/releases"))
    releases = [
        r for page in pages for r in page if r["tag_name"].startswith("data-") and not r["draft"]
    ]
    if not releases:
        if not bootstrap:
            raise RuntimeError("No data checkpoint release found; use the explicit bootstrap input")
        print("Starting the initial entity baseline")
        return
    release = max(releases, key=lambda r: r["published_at"])
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
        "--pattern",
        "checkpoint.sqlite3.gz*",
    )
    restore_checkpoint(directory, state)
    print(f"Restored {release['tag_name']}")


def publish(repo, directory, tag, target):
    manifest = json.loads((directory / "manifest.json").read_text())
    complete = manifest["complete"]
    notes = directory.parent / "release-notes.md"
    notes.write_text(
        f"BRREG account collection through {manifest['entities_date']}.\n\n"
        f"Collection status: {'queued work complete' if complete else 'partial checkpoint; resume required'}.\n\n"
        f"```json\n{json.dumps(manifest['counts'], indent=2)}\n```\n\n"
        "accounts.jsonl.gz and accounts.parquet contain the most recently observed successful "
        "responses; consult observations.jsonl.gz for errors and observation times. "
        "filings-history.jsonl.gz retains previously seen filing IDs. "
        "responses.jsonl.gz preserves exact response bytes as base64. "
        "The checkpoint retains pending signals and unfinished requests.\n\n"
        "Verify SHA256SUMS before using the assets. Large assets are split into numbered "
        "parts; manifest.json records their order and full-file checksums. "
        "A completed queue does not prove that every pending announcement is reflected in the API.\n"
    )
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
        f"BRREG data {tag.removeprefix('data-')}",
        "--notes-file",
        str(notes),
    )
    files = sorted(p for p in directory.iterdir() if p.is_file())
    for path in files:
        gh("release", "upload", tag, str(path), "--repo", repo)
    remote = json.loads(gh("release", "view", tag, "--repo", repo, "--json", "assets"))
    actual = {a["name"]: a["size"] for a in remote["assets"]}
    expected = {p.name: p.stat().st_size for p in files}
    if actual != expected:
        raise RuntimeError("Uploaded asset set differs from local files; release remains a draft")
    gh(
        "release",
        "edit",
        tag,
        "--repo",
        repo,
        "--draft=false",
        "--latest=false",
        f"--prerelease={'false' if complete else 'true'}",
    )


def main():
    p = argparse.ArgumentParser()
    p.add_argument("command", choices=["resume", "publish"])
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
        resume(args.repo, args.directory, args.state, args.bootstrap)
    else:
        if not args.tag or not args.tag.startswith("data-") or not args.target:
            p.error("publish requires a data- tag and an explicit target commit")
        publish(args.repo, args.directory, args.tag, args.target)


if __name__ == "__main__":
    main()
