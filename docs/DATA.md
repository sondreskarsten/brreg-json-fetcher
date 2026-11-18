# Norske årsregnskap: data reference

Column definitions and the change log format for the monthly releases described in the [README](../README.md).

> Inneholder data under [Norsk lisens for offentlige data (NLOD) 2.0](https://data.norge.no/nlod/no/2.0) tilgjengeliggjort av Brønnøysundregistrene.

This is an unofficial copy. It is not operated or endorsed by Brønnøysundregistrene.

## File names by release

File names differ between releases. Check which release you have before you write code against it.

| Release | Accounts | One row per organisation | Other |
| --- | --- | --- | --- |
| `data-2026-10` | `accounts*.csv`, AS and ASA only | `observations.csv` | |
| `data-2026-11` | `accounts-00001.csv` to `accounts-00003.csv` | `observations.csv` | `register_*.csv` summary tables, `enheter.json.gz`, `checkpoint.sqlite3.gz`, `manifest.json`, `SHA256SUMS`, `DATA_NOTICE.md` |
| From `data-2026-12` | `accounts-0000N.csv` | `organisations.csv` | No `register_*.csv` |

In `manifest.json`, `dataset.<table>.files` lists the files of each table. The per-organisation table is called `observations` up to `data-2026-11` and `organisations` from `data-2026-12`. Code that reads every entry of `dataset` with a `files` list handles both.

Join the tables on `accounts._meta.orgnr = observations.orgnr`, or `accounts._meta.orgnr = organisations.orgnr` from `data-2026-12`.

`data-2026-11` holds 1,240,276 account rows from 1,227,343 regnskap. 719,866 organisations were checked for accounts, out of 1,184,327 in the register download. 443,315 of them had accounts.

## accounts

One row per regnskap and account type, identified by `journalnr` + `regnskapstype`. Each part has its own header and can be read on its own. Stack the parts for the full table.

**What a regnskap is.** `journalnr` is the number Regnskapsregisteret assigns to a submitted annual account. It identifies one regnskap, for one organisation and one fiscal year, and is the number the filed document carries. The first four digits are the year it was received.

**Company and consolidated accounts.** A regnskap always has company accounts, with `regnskapstype` = `SELSKAP`. A parent company's regnskap can also contain consolidated accounts for the group, with `regnskapstype` = `KONSERN`. Both rows then share the same `journalnr`, so `journalnr` + `regnskapstype` identifies a row. In `data-2026-11`, 12,933 regnskap contain both.

**Following a company over time.** `_meta.orgnr` + `regnskapstype` + `_meta.fiscal_year` identifies the accounts for one organisation and year. There is at most one row for each in a release. If its `journalnr` differs from an earlier release, the accounts were resubmitted. The company accounts are always part of a regnskap, so the `journalnr` of the SELSKAP row is the current regnskap for that year.

**Columns.** The keys are `journalnr`, `regnskapstype`, `_meta.orgnr`, `_meta.fiscal_year`, `regnskapsperiode.fraDato` and `regnskapsperiode.tilDato`. From `data-2026-12` they are the first six columns. Releases up to `data-2026-11` do not have them first, so select columns by name.

The key figures are dotted names that mirror the source. Examples:

| Column | Figure |
| --- | --- |
| `eiendeler.sumEiendeler` | Total assets |
| `egenkapitalGjeld.egenkapital.sumEgenkapital` | Equity |
| `resultatregnskapResultat.driftsresultat.driftsinntekter.sumDriftsinntekter` | Revenue |
| `resultatregnskapResultat.driftsresultat.driftsresultat` | Operating result |
| `resultatregnskapResultat.aarsresultat` | Annual result |

Amounts are in whole units of `valuta`. A blank cell means the figure was not reported. It does not mean zero. `_meta.fiscal_year` is the year of `regnskapsperiode.tilDato`.

Also present: `id`, the source's internal row number. It is unique per row, but `journalnr` + `regnskapstype` is the identifier to use. `_meta.first_seen` and `_meta.last_seen` are when this collection first and last saw the row. `_meta.filing_json` is the complete source record and `_meta.filing_sha256` its SHA-256. `_meta.snapshot_date` is the date of the month's register download.

New fields at the source appear as new columns, so select columns by name. Source spellings are kept as they are, including `regnkapsprinsipper` and `sumInnskuttEgenkaptial`.

**Good to know.** A consolidated row occasionally has a different `journalnr` from the company row for the same year. In every such case in `data-2026-11`, the annual-accounts document Brønnøysundregistrene currently holds for that year is the company row's regnskap, and it contains no consolidated accounts. Treat a `KONSERN` row whose `journalnr` has no `SELSKAP` row as left over from a submission that is no longer the current one.

## observations

Up to `data-2026-11`. One row per organisation checked for accounts: 719,866 rows in `data-2026-11`, identified by `orgnr`. Organisations not checked, such as sole proprietorships without a filed annual account, are not in this table.

| Column | Meaning |
| --- | --- |
| `orgnr` | Organisation number |
| `snapshot_date` | Date of the month's register download |
| `organisasjonsform` | Legal form code |
| `latest_filing_year` | Latest year with a filed annual account, according to the register |
| `register_status` | `listed` if in this month's register. Otherwise the result of looking it up: `deleted`, `not_found` or `still_registered` |
| `register_deleted_date` | Deletion date, when deleted |
| `register_checked_on` | When the register status was last established |
| `outcome` | `ok`: accounts are in the accounts files. `not_found`: none on file. `unsupported`: the organisation uses an accounting plan the source does not publish key figures for, for example banks and insurers |
| `observed_at`, `http_status`, `message`, `error_body`, `response_sha256` | When the accounts were requested and what the source answered |

In `data-2026-11`, 443,315 have `outcome` = `ok`, 275,345 `not_found` and 1,206 `unsupported`.

## organisations

From `data-2026-12`. Every organisation in the month's register download, plus organisations from earlier months that have since left the register. 28 columns, identified by `orgnr`.

| Column | Meaning |
| --- | --- |
| `orgnr` | Organisation number |
| `snapshot_date` | Date of the month's register download |
| `navn`, `organisasjonsform` | Name and legal form code, such as AS, ENK or NUF |
| `kommunenummer` | Municipality of the business address, or the postal address if there is none. The first two digits are the county |
| `naeringskode` | Main NACE industry code. The first two digits are the industry division |
| `har_registrert_antall_ansatte` | `true` if the organisation has registered employees. Use this to tell employers from non-employers |
| `antall_ansatte` | Number of employees where the register publishes it. Blank for many employers, so it is not a test for having employees |
| `registrert_i_mvaregisteret`, `registrert_i_foretaksregisteret` | Registered for VAT; registered in the Register of Business Enterprises |
| `konkurs`, `under_avvikling`, `under_tvangsavvikling` | Bankruptcy, liquidation, compulsory liquidation |
| `registreringsdato_enhetsregisteret`, `kapital` | Registration date; share capital where registered |
| `latest_filing_year` | Latest year with a filed annual account, according to the register |
| `first_seen`, `last_listed` | First and latest register download that included the organisation |
| `register_status` | `listed` if in this month's register. Otherwise the result of looking it up: `deleted`, `not_found` or `still_registered` |
| `register_deleted_date` | Deletion date, when deleted |
| `register_checked_on` | When the register status was last established |
| `accounts_requested` | `true` if accounts were requested for this organisation. That is every organisation except sole proprietorships without a filed annual account |
| `outcome` | `ok`: accounts are in the accounts files. `not_found`: none on file. `unsupported`: the organisation uses an accounting plan the source does not publish key figures for. `not_requested`: see `accounts_requested` |
| `observed_at`, `http_status`, `message`, `error_body`, `response_sha256` | When the accounts were requested and what the source answered |

## Change log between months

Every completed month after the first also publishes **`changelog-YYYY-MM`**, built by comparing the new `data-YYYY-MM` release with the previous month's data release. It is shaped like an update feed: one row per field operation, and the rows of one transition share an `event_id`. `changes-YYYY-MM.csv` holds that month's events. `changes.csv` is the cumulative log since the first comparison, with `event_id` continuing across months. From October to November 2026, 384 regnskap were resubmitted.

**What one event is.** An event is a change to one regnskap: one organisation and fiscal year. The regnskap is identified by the `journalnr` of its company accounts. Its consolidated accounts, when it has them, are the KONSERN row on the same `journalnr`.

**Columns.** `event_id, release, orgnr, fiscal_year, endringstype, journalnr_old, journalnr_new, konsern_old, konsern_new, regnskapstype, id_old, id_new, op, path, old_value, new_value`.

| Column | Content |
| --- | --- |
| `journalnr_old`, `journalnr_new` | The regnskap before and after. A different number is a new submission |
| `konsern_old`, `konsern_new` | `true` or `false`: whether the regnskap had consolidated accounts before and after. Blank on the side where the regnskap does not exist |
| `regnskapstype` | Which part the row describes: `SELSKAP` or `KONSERN` |
| `id_old`, `id_new` | The source's row id for that part, before and after |
| `op`, `path`, `old_value`, `new_value` | One changed field: `add`, `remove` or `replace`. An empty `op` means that part has no changed figures |

**Reading the consolidated accounts.**

| `konsern_old` | `konsern_new` | Meaning |
| --- | --- | --- |
| `true` | `true` | Consolidated accounts are in both. Changed figures are listed in the `KONSERN` rows |
| `false` | `true` | The new submission added consolidated accounts. One `KONSERN` row with `op` = `add` |
| `true` | `false` | The new submission has no consolidated accounts. One `KONSERN` row with `op` = `remove` |
| `false` | `false` | No consolidated accounts in either |

| `endringstype` | Meaning | Rows |
| --- | --- | --- |
| `Ny` | A regnskap for a year that was not in the prior release | One `add` row per part. `new_value` is the row's `_meta.filing_sha256` in that month's accounts files |
| `Resubmitted` | The year has a new `journalnr` or `id` | One row per changed field in each part. A single row with empty `op` for a part whose figures are identical |
| `Revised` | Same `journalnr` and `id`, a value differs | One row per changed field. The source cannot tell a re-extraction from a correction |
| `KeyChanged` | A regnskap moved to another fiscal year under the same `journalnr` | Field rows, including `regnskapsperiode.tilDato` |
| `AgedOut` | The regnskap left the response because a newer year arrived and the source returns the latest three fiscal years | One `remove` row per part |
| `Sletting` | The regnskap left the response for any other reason, for example the source now answers 404 | One `remove` row per part |
| `KonsernEnded` | A new year arrived with company accounts only, and the year before had consolidated accounts | `konsernregnskap.last_fiscal_year` and `virksomhet.morselskap`, which says whether the company still reports being a parent |
| `Status` | A change for the organisation as a whole in `outcome`, `http_status`, `message`, `organisasjonsform`, `latest_filing_year`, `register_status` or `register_deleted_date` | One row per changed field |

**Consolidated accounts from an earlier submission.** After a resubmission without consolidated accounts, the source can keep returning the KONSERN row of the earlier submission. That row stays in the accounts files under its own `journalnr` and is not part of the current regnskap. The change log reports the removal once, in the `Resubmitted` event, and stays silent when the row later disappears. The change log's `manifest.json` counts such rows in `konsern_rows_from_earlier_submissions`.

**Layout versions.** This is layout `regnskap-changelog-csv/v2`, used from `changelog-2026-12`. Its `changes.csv` covers every month since the first data release, October 2026. `changelog-2026-11` is the only release in the earlier layout, which had one event per account type.

**Limits.** The cumulative file refuses to chain onto a previous change log for any cycle other than the prior data release, so a skipped month cannot leave a silent gap. Two transitions inside one month collapse into one net transition. A resubmission reversed before the next release is invisible. Regnskapsregisteret has no update feed, so the log records net monthly transitions. A `Revised` event has no date of its own beyond the release month.
