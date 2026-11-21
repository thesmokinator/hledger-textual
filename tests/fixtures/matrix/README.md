# hledger UI matrix journals

These journals are the fixtures used by the hledger UI test matrix
(https://hledger.org/uis.html) — vendored unmodified so the suite can test
against the exact data the matrix uses (issue #275).

## Provenance and licence

- **Source:** https://github.com/hledgerorg/hledger, directory `examples/`
- **Pinned revision:** commit `61d999db5004253fdb0db188338122e0b545a9c2` (post-1.52.4 `main`)
- **Licence:** these files are part of the hledger project, licensed
  **GPL-3.0**. They are redistributed here unmodified, under their original
  licence, and are **not** covered by this project's MIT licence. They are
  test data only: they are excluded from the published wheel/sdist and must
  never be modified (the test suite asserts their checksums, recorded in
  `tests/test_matrix.py::MATRIX_CHECKSUMS`). To verify by hand run
  `shasum -a 256 *.journal` in this directory; to refresh the fixtures see
  the procedure at the bottom of this file. (The project `.gitignore`
  excludes user journals with `*.journal`; the fixtures are tracked via an
  explicit exception.)

## The files

| File | Content | Date span |
| --- | --- | --- |
| `sample2.journal` | Small journal, conventional english account names, balance assertions | 2025-01 |
| `accounttypes.journal` | Non-english/non-conventional account names, uses account types | 2025-01 |
| `bcexample.journal` | ~1000 transactions, capitalised account names, multiple commodities | 2012–2014 |
| `1ktxns-100accts.journal` | Synthetic: 1000 transactions, unconventional account names, transacted and market prices | 2000–2002 |

To refresh: pick a new hledger commit, download the four files from
`examples/`, verify `hledger stats` loads them, update the checksums in
`tests/test_matrix.py`, and update the pinned commit above.
