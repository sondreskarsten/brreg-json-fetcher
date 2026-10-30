"""Probe live register response contracts independently of the accounts sample."""

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from brreg_fetcher.client import Client, decode_register

CASES = {
    "923609016": "still_registered",
    "931264338": "deleted",
    "991128972": "deleted",
    "000000000": "not_found",
}


def run(output, *, client=None, cases=None):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    client = client or Client()
    results = []
    for orgnr, expected in (CASES if cases is None else cases).items():
        result = {"orgnr": orgnr, "expected": expected, "passed": False}
        try:
            reply = client.entity(orgnr)
            status, deleted = decode_register(reply.status, reply.body)
            (output / f"{orgnr}.body").write_bytes(reply.body)
            result.update(
                http_status=reply.status,
                register_status=status,
                register_deleted_date=deleted,
                response_sha256=hashlib.sha256(reply.body).hexdigest(),
                passed=status == expected and (expected != "deleted" or bool(deleted)),
            )
        except (RuntimeError, OSError, ValueError) as exc:
            result["error"] = str(exc)
        results.append(result)
    summary = {
        "fetched_at": datetime.now(UTC).isoformat(),
        "scope": "live Client.entity and decode_register; independent of bulk-seed membership",
        "complete": bool(results) and all(row["passed"] for row in results),
        "results": results,
    }
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    if not summary["complete"]:
        raise RuntimeError("Live register contract check failed; inspect summary.json and bodies")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("data/register-smoke"))
    args = parser.parse_args()
    run(args.output)


if __name__ == "__main__":
    main()
