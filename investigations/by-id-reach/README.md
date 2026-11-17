# What the by-id endpoint still returns

Status: open. Evidence collected 17 November 2026.

## Question

`GET /regnskapsregisteret/regnskap/{orgnr}` returns the three latest fiscal years. Is a row that
has left that response still retrievable with `GET /regnskapsregisteret/regnskap/{orgnr}/{id}`?

## Result

Yes, for every row tested. The sample is drawn from the November 2026 change log: rows that
left the list response between `data-2026-10` and `data-2026-11`. Each probe returned the same
`id` and `journalnr` the October release held.

| Why the row left the list response | Account type | Fiscal year | Probed | Returned |
|---|---|---|---|---|
| Aged out of the three-year window | SELSKAP | 2021 | 13 | 13 |
| Aged out of the three-year window | SELSKAP | 2022 | 25 | 25 |
| Aged out of the three-year window | SELSKAP | 2023 | 25 | 25 |
| Aged out of the three-year window | KONSERN | 2022 | 25 | 25 |
| Aged out of the three-year window | KONSERN | 2023 | 5 | 5 |
| Replaced by a resubmission | SELSKAP | 2024 | 1 | 1 |
| Replaced by a resubmission | SELSKAP | 2025 | 25 | 25 |
| Replaced by a resubmission | KONSERN | 2025 | 6 | 6 |
| Total | | | 125 | 125 |

Rows are in `probes.csv`.

## Other observations

- **The orgnr must match.** A valid `id` with another organisation's orgnr returns 404.
- **Each row answers on two consecutive ids.** For 914310415, ids 6323762 and 6323763 both
  return the SELSKAP row on journalnr 2025756984, and 6323764 and 6323765 both return the
  KONSERN row. The list response uses the higher id of each pair. The same holds for
  938737797 and 920905994. Whether the two ids of a pair ever differ in content was not
  checked beyond three totals.

## Not known

- **How far back.** Every probed id was collected in October 2026 or later, so the oldest
  fiscal year tested is 2021. Ids for older years are not known to this project.
- **Whether it lasts.** One day of probing says nothing about retention.
- **Organisations deleted from the register.** Not probed.

## Reproduce

```
uv run python investigations/by-id-reach/probe.py path/to/changes-2026-11.csv
```

The change log is the `changelog-2026-11` release rebuilt with version 0.7.0 or later, which
labels aged-out rows `AgedOut`. Sampling is seeded, 25 per group.
