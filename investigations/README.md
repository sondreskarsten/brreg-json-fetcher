# Investigations

Questions about the source data that needed evidence to answer. Each folder holds one
question with what was found, what is still unexplained, the evidence, and a script that
refetches it. Nothing here is part of the data releases or the installed package.

| Folder | Question | Status | Evidence collected |
|---|---|---|---|
| [`konsern-without-selskap`](konsern-without-selskap/) | Why do nine KONSERN rows have a journalnr with no SELSKAP row? | Cause established, handling in the dataset undecided | 17 November 2026 |
| [`by-id-reach`](by-id-reach/) | Are rows that left the list response still returned by id, and how are ids laid out? | Yes for every row tested, reach further back unknown | 17 November 2026 |

## Layout of a folder

- `README.md` with these sections: the question, what the evidence shows, not explained or not
  known, open decisions, files, reproduce, sources.
- Scripts that refetch or rebuild the evidence. They overwrite it, so `git diff` shows what the
  source changed.
- Evidence as collected: raw responses, documents, and text versions of anything scanned.
- A status line and the collection date at the top.

An open question has a GitHub issue that links to its folder. The folder holds the evidence,
the issue holds the discussion.
