# KONSERN rows whose journalnr has no SELSKAP row

Status: open. Evidence collected 17 November 2026.

## The problem

`GET /regnskapsregisteret/regnskap/{orgnr}` returns key figures per regnskap. A KONSERN row
normally shares its `journalnr` with a SELSKAP row for the same organisation and year, and its
`id` is the SELSKAP `id` plus 2. In `data-2026-11` that holds for 12,933 journalnr.

Nine KONSERN rows break the pattern. Their journalnr has no SELSKAP row in the list response.
The SELSKAP row for the same organisation and year carries a different journalnr. The same nine
rows were in `data-2026-10`.

## What the evidence shows

1. **The original SELSKAP row still exists.** `GET /regnskapsregisteret/regnskap/{orgnr}/{id}`
   with `id` = KONSERN `id` minus 2 returns a SELSKAP row on the KONSERN row's journalnr.
   This holds in 9 of 9 cases. See `evidence/account_rows.csv`, source `konsern_id_minus_2`.
2. **The current SELSKAP row has no KONSERN partner.** `id` = current SELSKAP `id` plus 2
   returns 404 in 9 of 9 cases.
3. **Every case was resubmitted.** Each has two or three "Godkjente årsregnskap" kunngjøringer
   for the year, worded "mottatt et nytt komplett årsregnskap". See
   `evidence/kunngjoringer.csv`.
4. **The served PDF is the latest approved submission.** Its journalnr is the current SELSKAP
   row's. Its "Utskriftsdato" equals the date of the last kunngjøring for the year in 9 of 9
   cases. See `pdf_cover.csv`.
5. **The current årsregnskap has no konsernregnskap.** Six cover pages say "Morselskap i
   konsern: Ja, Konsernregnskap lagt ved: Nei". Two say "Morselskap i konsern: Nei". One is a
   paper form with a changed period end.

Reading: the first submission had a selskapsregnskap and a konsernregnskap on one journalnr.
A later submission without a konsernregnskap got a new journalnr. The list endpoint replaced
the SELSKAP row and kept the KONSERN row of the earlier submission.

## The nine cases

| orgnr | year | KONSERN journalnr / id | original SELSKAP id | current SELSKAP journalnr / id | kunngjøringer for the year | PDF Utskriftsdato |
|---|---|---|---|---|---|---|
| 914310415 | 2025 | 2025756984 / 6323765 | 6323763 | 2026200177 / 7219008 | 22.09.2025, 28.07.2026 | 28.07.2026 |
| 920905994 | 2025 | 2026765272 / 7228638 | 7228636 | 2026767063 / 7234708 | 17.09.2026, 29.09.2026 | 29.09.2026 |
| 925147885 | 2023 | 2024361285 / 4672801 | 4672799 | 2024467528 / 4844881 | 03.04.2024, 17.04.2024, 01.06.2024 | 01.06.2024 |
| 927652900 | 2023 | 2024466551 / 4843243 | 4843241 | 2024523127 / 5130901 | 01.06.2024, 08.07.2024 | 08.07.2024 |
| 928772896 | 2023 | 2024421229 / 4760711 | 4760709 | 2024403828 / 4849105 | 21.05.2024, 03.06.2024, 03.06.2024 | 03.06.2024 |
| 930076430 | 2023 | 2024744153 / 5418423 | 5418421 | 2024746523 / 5423011 | 07.09.2024, 16.09.2024 | 16.09.2024 |
| 933896129 | 2024 | 2025759894 / 6328869 | 6328867 | 2025761909 / 6332417 | 14.10.2025, 06.11.2025 | 06.11.2025 |
| 934445791 | 2024 | 2025521283 / 5841031 | 5841029 | 2025747881 / 6301779 | 03.06.2025, 07.06.2025, 16.08.2025 | 16.08.2025 |
| 938737797 | 2025 | 2026530527 / 6857974 | 6857972 | 2026530542 / 6883968 | 01.07.2026, 04.07.2026 | 04.07.2026 |

Original and current SELSKAP rows compared field by field:

| orgnr | fields that differ | note |
|---|---|---|
| 914310415 | 26 | period end moved from 30.04.2025 to 31.12.2025 |
| 920905994 | 13 | zeros became missing |
| 925147885 | 5 | |
| 927652900 | 27 | `morselskap` true to false |
| 928772896 | 0 | figures identical |
| 930076430 | 1 | |
| 933896129 | 3 | `morselskap` true to false |
| 934445791 | 21 | |
| 938737797 | 5 | two totals differ by 1 |

## id and journalnr

Both SELSKAP versions can be fetched by `id`: the original one and the current one, in 9 of 9
cases. The list endpoint returns only the current one.

| | `id` | `journalnr` |
|---|---|---|
| Identifies | one row: one version of one account type | one submission, shared by its SELSKAP and KONSERN rows |
| Can be queried | yes, `/{orgnr}/{id}` | no endpoint takes it |
| Changes on resubmission | yes | yes |
| Printed on the PDF | no | yes |

This reverses the earlier working position in this project that `journalnr` alone is the
identity to build on and that `id` adds nothing. `id` is the only handle that retrieves a
superseded version. `journalnr` remains what ties a row to its submission and to the PDF.

## Not explained

- **928772896.** The current SELSKAP journalnr 2024403828 is lower than the KONSERN journalnr
  2024421229, while its `id` is higher and its PDF is dated on the last kunngjøring. The order
  of journalnr and the order of approval disagree.
- **Three kunngjøringer, two journalnr.** 925147885, 928772896 and 934445791 have three
  kunngjøringer for the year. Only two journalnr are known. Ids between the two known ones were
  not probed.
- **Earlier received dates.** Every kunngjøring for the same year shows the same text, with the
  latest received date. The received date of the first submission is not available there.
- **934445791.** Its first kunngjøring is dated 03.06.2025. The current PDF says the accounts
  were adopted 04.06.2025.
- **Scope of the by-id endpoint.** It serves rows the list endpoint no longer returns. How far
  back, and for which resubmissions, is not known. The November change log has 390
  resubmissions that could be probed the same way.
- **Figures inside the PDFs.** Not compared with either row. The PDFs are scanned images.
- **The KONSERN journalnr's own PDF.** The PDF endpoint takes orgnr and year only.

## Open decisions

- How `accounts.csv` treats these rows: keep, flag, or move to a separate file.
- Whether to collect superseded rows through the by-id endpoint.
- Whether to report the nine rows to Brønnøysundregistrene. `opendata@brreg.no` is the contact
  in their Enhetsregisteret API documentation. The OpenAPI spec, version 1.1.16, describes
  `id` as "system-generert id" and has no description of `journalnr`.

## Files

| Path | Content |
|---|---|
| `cases.csv` | The nine cases: orgnr, year, both journalnr and both ids |
| `pdf_cover.csv` | Values read by eye from each PDF's first two pages |
| `reproduce.py` | Refetches everything under `evidence/` |
| `evidence/account_rows.csv` | Every row of the list response, plus four by-id probes per case |
| `evidence/api/list/` | Raw list responses |
| `evidence/api/by_id/` | Raw by-id responses, 404 bodies included |
| `evidence/kunngjoringer.csv` | Accounts kunngjøringer from the case year onward |
| `evidence/kunngjoring/` | Raw kunngjøring pages |
| `evidence/pdf/` | The årsregnskap PDF served for each case |
| `evidence/pages/` | Pages 1 and 2 of each PDF as PNG |

## Reproduce

```
uv run python investigations/konsern-without-selskap/reproduce.py
pdftoppm -r 50 -f 1 -l 2 -png evidence/pdf/920905994-2025.pdf evidence/pages/920905994-2025
```

The script overwrites `evidence/`. Compare with `git diff` to see what the source changed.
The PDFs are generated per request and are not byte-identical between downloads.

To find the cases in a release: KONSERN rows in `accounts-*.csv` whose `journalnr` has no row
with `regnskapstype` = `SELSKAP`.

## Sources

- List and by-id: `https://data.brreg.no/regnskapsregisteret/regnskap/{orgnr}` and `/{orgnr}/{id}`
- PDF: `https://data.brreg.no/regnskapsregisteret/regnskap/aarsregnskap/kopi/{orgnr}/{aar}`
- Kunngjøringer: `https://w2.brreg.no/kunngjoring/hent_nr.jsp?orgnr={orgnr}`
- OpenAPI: `https://data.brreg.no/regnskapsregisteret/regnskap/v3/api-docs`
