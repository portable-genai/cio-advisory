# The demo book

Fictional clients, their holdings, the instruments they hold, a model portfolio per risk
profile, and the CIO house views a briefing is grounded on. Every id is visibly invented,
every URL is under `example.test`, and no row describes a real person, institution or
security.

One file per table, newline-delimited JSON, keys in the column order the BigQuery schema in
`infra/terraform/bigquery.tf` declares. The same rows feed three consumers, which is the
point of keeping them here rather than in code:

| Consumer | How it reads the files |
|---|---|
| The `local` and `live` profiles | `adapters/local/portfolio.py` opens a DuckDB file and, when its tables are empty, inserts these rows. The house-view FTS index seeds from `house_views.ndjson` under `local` only: under `live` the themes are real grounded research |
| The deployment | `scripts/load_demo_book.py` streams these files into the `wealth_portfolio` dataset, rewriting `tenant` to the value the deployment's identity adapter resolves |
| Tests and the eval gate | `cio_advisory.demo_book` builds the domain objects the fixtures and the golden set use |

| File | Rows | What a row is |
|---|---|---|
| `client_profiles.ndjson` | 7 | one client's suitability profile and the tenant that owns it |
| `holdings.ndjson` | 25 | one position, keyed by client and instrument, with its statement line number |
| `instruments.ndjson` | 15 | one instrument: asset class, theme tags, ESG flag, liquidity |
| `model_portfolios.ndjson` | 15 | one asset-class target and band for one risk profile |
| `book_manifest.ndjson` | 1 | the book's version, its as-of date, and `fictional: true`, which is what the loader's overwrite guard reads |
| `house_views.ndjson` | 4 | one CIO house-view theme with its citation |

Six clients belong to the `demo-bank` tenant. `client-000999` belongs to `other-bank` and
exists to prove the tenant gate: a `demo-bank` persona cannot list or brief it.

Edit these files by hand. Weights per client must sum to one, every `instrument_id` must
exist in `instruments.ndjson`, and every model portfolio's targets must sum to one with each
target inside its band; `tests/contract/test_demo_book.py` refuses anything else.
