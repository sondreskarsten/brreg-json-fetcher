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

## How ids are laid out

Ids around 60 random rows of `data-2026-11` were probed, from two below the listed SELSKAP id
to three above it. Rows are in `layout.csv`.

| Submission | N-1 | N, listed SELSKAP | N+1 | N+2, listed KONSERN | Rows |
|---|---|---|---|---|---|
| SELSKAP and KONSERN | SELSKAP copy | SELSKAP | KONSERN copy | KONSERN | 30 of 30 |
| SELSKAP only | SELSKAP copy | SELSKAP | 404 | 404 | 28 of 30 |
| SELSKAP only | 404 | SELSKAP | 404 | 404 | 2 of 30 |

- **A copy equals its listed row** on every field except `id`, in 88 of 88 pairs.
- **Parity carries no meaning.** Listed ids are odd for 82% of SELSKAP rows and 85% of KONSERN
  rows in `data-2026-11`.
- **A higher id is the newer version.** In all 390 resubmissions of the November 2026 change
  log the new id is higher. The new journalnr is higher in 385.
- **The orgnr must match.** A valid id with another organisation's orgnr returns 404. A 404
  next to a row can therefore be a row of another organisation.
- **An old version cannot be derived from the new id.** The distance between them varies.

## Not known

- **Why two SELSKAP-only rows have no copy.**
- **What the lower id of a pair is for.**
- **How far back.** Every probed id was collected in October 2026 or later, so the oldest
  fiscal year tested is 2021. Ids for older years are not known to this project.
- **Whether it lasts.** One day of probing says nothing about retention.
- **Organisations deleted from the register.** Not probed.

## Reproduce

```
uv run python investigations/by-id-reach/probe.py path/to/changes-2026-11.csv
uv run python investigations/by-id-reach/layout.py path/to/data-2026-11
```

The change log is the `changelog-2026-11` release rebuilt with version 0.7.0 or later, which
labels aged-out rows `AgedOut`. Sampling is seeded, 25 per group.
