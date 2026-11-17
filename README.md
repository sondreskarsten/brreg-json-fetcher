# regnskapsregisteret-dataset

**Annual-accounts key figures for every Norwegian organisation that files accounts, as a monthly open dataset.**

Each month this repository publishes one complete, ready-to-use CSV dataset of the key figures (nøkkeltall) from Regnskapsregisteret: assets, equity, debt, revenue, operating result and annual result, for company and consolidated accounts. Alongside it come a record of what changed since the previous month and summary tables of the whole business register, so the figures can be put in context.

`data-2026-11`, the latest release, holds **1,240,276 filings from 719,866 organisations**.

> Inneholder data under Norsk lisens for offentlige data (NLOD) 2.0 tilgjengeliggjort av Brønnøysundregistrene.

An independent, unofficial mirror maintained by [sondreskarsten](https://github.com/sondreskarsten). Not operated or endorsed by Brønnøysundregistrene.

## What you get

- **The whole population in one table.** Every organisation in Enhetsregisteret with accounts on file, across all legal forms, with the latest three fiscal years each. Open it in Excel, R, Python or a database.
- **A history that does not disappear.** Every month is a separate, permanent release. When a company's figures are corrected or an old year drops out at the source, the earlier state is still here.
- **Corrections you can see.** Companies resubmit accounts. The monthly change log lists each resubmission and every figure that changed, with old and new value. From October to November 2026 that was 390 filings.
- **No silent gaps.** Every organisation has a recorded outcome: accounts returned, no accounts on file, accounting plan not available from the source, or removed from the register and when.
- **The full register alongside.** One row per organisation in Enhetsregisteret, sole proprietorships included: name, legal form, municipality, industry code, whether it has employees, VAT registration and more. Join it to the accounts on `orgnr` to compare organisations with and without accounts.
- **Results others can reproduce.** A release never changes after publication and every file has a checksum. Cite the release tag and anyone can retrieve exactly the same data.

## At a glance

| | |
| --- | --- |
| **Source** | Regnskapsregisteret's open key-figures API and the Enhetsregisteret register download, both from Brønnøysundregistrene |
| **Coverage** | All organisations in Enhetsregisteret except sole proprietorships (ENK) without a filed annual account. Organisations that later leave the register are kept |
| **Tables** | `accounts`: one row per regnskap and account type, identified by `journalnr` + `regnskapstype`. `organisations`: one row per organisation, identified by `orgnr` |
| **Figures per filing** | About 30: total, current and fixed assets; equity; short- and long-term debt; revenue; operating result; financial items; tax; annual result. Plus period, currency, audit and accounting-principle flags |
| **Years** | The latest three fiscal years available at the source each month |
| **Updated** | Monthly. The register list is taken at the start of the month; collection takes about five days and every row carries its observation time |
| **Format** | UTF-8 CSV with header, a `manifest.json` describing the files, and `SHA256SUMS` |
| **First release** | `data-2026-10` (limited to AS and ASA). All legal forms from `data-2026-11` |
| **Licence** | NLOD 2.0, with attribution to Brønnøysundregistrene |

### What each month contains

| Release | Contents |
| --- | --- |
| `data-YYYY-MM` | `accounts*.csv`: the key figures. `organisations.csv`: every organisation in the register, with its attributes and whether accounts were found |
| `changelog-YYYY-MM` | `changes-YYYY-MM.csv`: every difference from the previous month. `changes.csv`: all months so far |
| `checkpoint-…` (prerelease) | Working state of a collection in progress. Not a dataset; ignore these |

### What it does not contain

The full annual accounts, notes, auditor's report and PDF are not included, nor line items below the key figures. Banks, insurers, pension funds and a few other groups use accounting plans the source does not publish key figures for; they are listed in `organisations.csv` with that outcome. For a legally authoritative or up-to-the-minute figure for one organisation, consult Brønnøysundregistrene directly.

## Download

1. Open the [releases page](https://github.com/sondreskarsten/regnskapsregisteret-dataset/releases) and choose the newest release whose tag starts with `data-`.
2. Download the files you need from its asset list. For most uses that is the `accounts` files and `organisations.csv`.
3. For the monthly changes, open the matching `changelog-` release.

The accounts are split into several files of at most 1 GB (`accounts-00001.csv`, `accounts-00002.csv`, …). Each part has its own header and can be opened on its own; stack them for the full table.

<details>
<summary>Download and verify from the command line</summary>

```bash
TAG=data-2026-11  # Choose an existing completed data release.
BASE="https://github.com/sondreskarsten/regnskapsregisteret-dataset/releases/download/$TAG"
curl -fSLO "$BASE/manifest.json"
# The manifest names every independently readable CSV, including split files.
python3 - <<'PYCSV' > csv-files.txt
import json
with open("manifest.json") as source:
    dataset = json.load(source)["dataset"]
for table in ("accounts", "organisations"):
    for name in dataset[table]["files"]:
        print(name)
PYCSV
while IFS= read -r file; do
  curl -fSLO "$BASE/$file" || exit 1
done < csv-files.txt
for file in DATA_NOTICE.md SHA256SUMS; do
  curl -fSLO "$BASE/$file" || exit 1
done
sha256sum -c --ignore-missing SHA256SUMS
```

</details>

## The tables

| File | One row per | Identified by |
| --- | --- | --- |
| `accounts.csv` (in numbered parts) | regnskap and account type | `journalnr` + `regnskapstype` |
| `organisations.csv` | organisation in Enhetsregisteret | `orgnr` |

Join them on `accounts._meta.orgnr = organisations.orgnr`.

Other files in a release: `enheter.json.gz` (the complete register download the month is based on), `manifest.json` (file list, row counts, columns), `SHA256SUMS`, `DATA_NOTICE.md` (attribution and licence), and `checkpoint.sqlite3.gz` (the collector's working database, including the exact responses received).

`data-2026-11` holds 1,240,276 account rows from 1,227,343 regnskap, for 719,866 organisations out of 1,184,327 in the register. `data-2026-10` has the accounts for AS and ASA only and predates `organisations.csv`.

### accounts

**What a regnskap is.** `journalnr` is the number Regnskapsregisteret assigns to a submitted annual account. It identifies one regnskap, for one organisation and one fiscal year, and is the number the filed document carries. The first four digits are the year it was received.

**Company and consolidated accounts.** A regnskap always has company accounts (`regnskapstype` = `SELSKAP`). A parent company's regnskap can also contain consolidated accounts for the group (`KONSERN`). Both rows then share the same `journalnr`, so `journalnr` + `regnskapstype` identifies a row. In `data-2026-11`, 12,933 regnskap contain both.

**Following a company over time.** `_meta.orgnr` + `regnskapstype` + `_meta.fiscal_year` identifies the accounts for one organisation and year. There is at most one row for each in a release. If its `journalnr` differs from an earlier release, the accounts were resubmitted.

**Columns.** The first six are the keys: `journalnr`, `regnskapstype`, `_meta.orgnr`, `_meta.fiscal_year`, `regnskapsperiode.fraDato`, `regnskapsperiode.tilDato`. The key figures follow as dotted names that mirror the source, for example `eiendeler.sumEiendeler` (total assets), `egenkapitalGjeld.egenkapital.sumEgenkapital` (equity) and `resultatregnskapResultat.aarsresultat` (annual result). Amounts are in whole units of `valuta`. A blank cell means the figure was not reported; it does not mean zero. `_meta.fiscal_year` is the year of `regnskapsperiode.tilDato`.

Also present: `id`, the source's internal row number (unique per row; `journalnr` + `regnskapstype` is the identifier to use); `_meta.first_seen` and `_meta.last_seen`, when this collection first and last saw the row; `_meta.filing_json`, the complete source record; and `_meta.snapshot_date`, the date of the month's register download.

New fields at the source appear as new columns, so select columns by name. Source spellings are kept as they are, including `regnkapsprinsipper` and `sumInnskuttEgenkaptial`.

**Good to know.** A consolidated row occasionally has a different `journalnr` from the company row for the same year (9 cases in `data-2026-11`). In every such case the annual-accounts document Brønnøysundregistrene currently holds for that year is the company row's regnskap, and it contains no consolidated accounts. Treat a `KONSERN` row whose `journalnr` has no `SELSKAP` row as left over from a submission that is no longer the current one.

### organisations

Every organisation in the month's register download, plus organisations from earlier months that have since left the register.

| Column | Meaning |
| --- | --- |
| `orgnr` | Organisation number |
| `navn`, `organisasjonsform` | Name and legal form code (AS, ENK, NUF, …) |
| `kommunenummer` | Municipality of the business address, or the postal address if there is none. The first two digits are the county |
| `naeringskode` | Main industry code (NACE). The first two digits are the industry division |
| `har_registrert_antall_ansatte` | `true` if the organisation has registered employees. Use this to tell employers from non-employers |
| `antall_ansatte` | Number of employees where the register publishes it. Blank for many employers, so it is not a test for having employees |
| `registrert_i_mvaregisteret`, `registrert_i_foretaksregisteret` | Registered for VAT; registered in the Register of Business Enterprises |
| `konkurs`, `under_avvikling`, `under_tvangsavvikling` | Bankruptcy, liquidation, compulsory liquidation |
| `registreringsdato_enhetsregisteret`, `kapital` | Registration date; share capital where registered |
| `latest_filing_year` | Latest year with a filed annual account, according to the register |
| `first_seen`, `last_listed` | First and latest register download that included the organisation |
| `register_status` | `listed` if in this month's register. Otherwise the result of looking it up: `deleted`, `not_found` or `still_registered` |
| `register_deleted_date` | Deletion date, when deleted |
| `accounts_requested` | `true` if accounts were requested for this organisation: every organisation except sole proprietorships without a filed annual account |
| `outcome` | `ok`: accounts are in `accounts.csv`. `not_found`: none on file. `unsupported`: the organisation uses an accounting plan the source does not publish key figures for. `not_requested`: see above |
| `observed_at`, `http_status`, `message`, `error_body`, `response_sha256` | When the accounts were requested and what the source answered |

### Change log between months

Every completed month after the first also publishes **`changelog-YYYY-MM`**, built by comparing the new `data-YYYY-MM` release with the previous month's data release. It is shaped like an update feed: one row per field operation, and the rows of one transition share an `event_id`. `changes-YYYY-MM.csv` holds that month's events; `changes.csv` is the cumulative log since the first comparison, with `event_id` continuing across months.

Columns: `event_id, release, orgnr, regnskapstype, fiscal_year, endringstype, journalnr_old, journalnr_new, id_old, id_new, op, path, old_value, new_value`. The unit is `orgnr × regnskapstype × fiscal year`; `id` and `journalnr` ride along as attributes. `journalnr` is ten digits, the year Regnskapsregisteret received the submission followed by a sequence number, so a new `journalnr` is a new submission.

| `endringstype` | Meaning | Rows |
| --- | --- | --- |
| `Ny` | The key was not in the prior release | one `add` row; `new_value` is the filing's SHA-256 in that month's `accounts.csv` |
| `Resubmitted` | Same key, new `journalnr` or `id` | one `replace`/`add`/`remove` row per changed field; a single row with empty `op` when the structured figures are identical |
| `Revised` | Same key, same `journalnr` and `id`, a value differs | one row per changed field; the API cannot tell a BRREG re-extraction from an upstream correction |
| `KeyChanged` | A filing moved to another fiscal year under the same `journalnr` | field rows, including `regnskapsperiode.tilDato` |
| `AgedOut` | The key left the response because a newer year arrived and the API returns the latest three fiscal years across both account types | one `remove` row |
| `Sletting` | The key left the response for any other reason, for example the API now answers 404 | one `remove` row |
| `KonsernEnded` | The submission for this fiscal year has company accounts but no consolidated accounts, and the year before had both. Logged on the SELSKAP key when that year first appears, or when its KONSERN filing leaves after a resubmission | `konsernregnskap.last_fiscal_year` and the SELSKAP filing's `virksomhet.morselskap`, which says whether the company still reports being a parent |
| `Status` | A change for the organisation as a whole in `outcome`, `http_status`, `message`, `organisasjonsform`, `latest_filing_year`, `register_status` or `register_deleted_date` | one row per changed field |

The cumulative file refuses to chain onto a previous change log for any cycle other than the prior data release, so a skipped month cannot leave a silent gap. Two transitions inside one month collapse into one net transition, and a resubmission reversed before the next release is invisible: Regnskapsregisteret has no update feed, so the log records net monthly transitions. A `Revised` event has no date of its own beyond the release month.

## Licence and attribution

The data is made available by Brønnøysundregistrene under [NLOD 2.0](https://data.norge.no/nlod/no/2.0). If you use or redistribute it, keep the attribution line above and the licence link, and say what you changed. Each release includes a `DATA_NOTICE.md` with the exact wording. [DATA_LICENSE.md](DATA_LICENSE.md) describes the licence scope and the changes this mirror makes to the source data.

## How to cite

Cite the release you used. Release tags are permanent:

> regnskapsregisteret-dataset, release `data-2026-11`. Unofficial monthly mirror of Regnskapsregisteret key figures. Inneholder data under Norsk lisens for offentlige data (NLOD) 2.0 tilgjengeliggjort av Brønnøysundregistrene. https://github.com/sondreskarsten/regnskapsregisteret-dataset/releases/tag/data-2026-11

## More

- **One organisation:** the [lookup page](https://sondreskarsten.github.io/regnskapsregisteret-dataset/) shows a single organisation's key figures in the browser.
- **How the dataset is produced:** [docs/COLLECTOR.md](docs/COLLECTOR.md) documents the collection process, quality checks and the source's behaviour, and how to run it yourself.
- **Questions or errors:** open an [issue](https://github.com/sondreskarsten/regnskapsregisteret-dataset/issues). For an error in a company's own figures, the source record at Brønnøysundregistrene is authoritative.
