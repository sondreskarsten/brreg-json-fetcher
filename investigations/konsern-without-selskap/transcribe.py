"""Turn the collected PDFs and kunngjøring pages into text files."""

import argparse
import csv
import html
import os
import re
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).parent


def ocr_page(image):
    result = subprocess.run(
        ["tesseract", str(image), "stdout", "-l", "nor", "--psm", "6"],
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, "OMP_THREAD_LIMIT": "1"},
    )
    return result.stdout.strip()


def pdf_text(pdf, out, dpi, workers):
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(
            ["pdftoppm", "-r", str(dpi), "-gray", "-png", str(pdf), f"{tmp}/p"], check=True
        )
        images = sorted(Path(tmp).glob("p-*.png"))
        with ThreadPoolExecutor(workers) as pool:
            pages = list(pool.map(ocr_page, images))
    body = "\n\n".join(
        f"===== page {n} of {len(pages)} =====\n{text}" for n, text in enumerate(pages, 1)
    )
    (out / f"{pdf.stem}.txt").write_text(body + "\n", encoding="utf-8")


def notice_text(page, out):
    raw = page.read_bytes().decode("latin-1")
    raw = re.sub(r"<script.*?</script>|<style.*?</style>", "", raw, flags=re.DOTALL)
    text = html.unescape(re.sub(r"<[^>]+>", "\n", raw)).replace("\xa0", " ")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    start = max(i for i, line in enumerate(lines) if line.startswith("Kunngjøring for"))
    end = min(i for i, line in enumerate(lines) if i > start and line.startswith("Nytt søk"))
    (out / f"{page.stem}.txt").write_text("\n".join(lines[start:end]) + "\n", encoding="utf-8")


def submissions(notice_out):
    rows = set()
    for path in sorted(notice_out.glob("*.txt")):
        text = path.read_text(encoding="utf-8")
        for block in re.split(r"\n(?=Godkjent årsregnskap\n)", text)[1:]:
            received = re.search(
                r"har den (\d\d\.\d\d\.\d{4}) mottatt (et nytt )?komplett årsregnskap"
                r" for regnskapsåret (\d{4})",
                block,
            )
            announced = re.search(r"Regnskapsregisteret (\d\d\.\d\d\.\d{4})", block)
            parent = re.search(
                r"Foretaket er i denne perioden (ikke )?registrert som morselskap", block
            )
            rows.add(
                (
                    path.stem[:9],
                    received.group(3),
                    received.group(1),
                    announced.group(1),
                    "nytt" if received.group(2) else "first",
                    "" if parent is None else ("nei" if parent.group(1) else "ja"),
                )
            )

    def order(row):
        day, month, year = row[3].split(".")
        return row[0], row[1], year, month, day

    return sorted(rows, key=order)


def run(evidence=HERE / "evidence", dpi=100, workers=4, skip_pdf=False):
    evidence = Path(evidence)
    pdf_out = evidence / "pdf_text"
    notice_out = evidence / "kunngjoring_text"
    pdf_out.mkdir(exist_ok=True)
    notice_out.mkdir(exist_ok=True)
    for pdf in [] if skip_pdf else sorted((evidence / "pdf").glob("*.pdf")):
        pdf_text(pdf, pdf_out, dpi, workers)
    for page in sorted((evidence / "kunngjoring").glob("*-*.html")):
        notice_text(page, notice_out)
    with (evidence / "submissions.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            ["orgnr", "regnskapsaar", "mottatt", "kunngjort", "wording", "morselskap_i_konsern"]
        )
        writer.writerows(submissions(notice_out))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, default=HERE / "evidence")
    parser.add_argument("--dpi", type=int, default=100)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--skip-pdf", action="store_true")
    args = parser.parse_args()
    run(args.evidence, args.dpi, args.workers, args.skip_pdf)
