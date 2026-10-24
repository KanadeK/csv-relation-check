# csv-relation-check

Validate relationships between local CSV exports before importing them. Composite primary/unique/foreign keys, required fields and CSV structure are checked with **exact string comparisons**. `001` stays different from `1`. No third-party runtime packages and no network access.

[中文说明](README.zh-CN.md) · [Contract reference](docs/CONTRACT.md)

This tool is for migration scripts, small data teams and public-data maintainers who need a repeatable relational check without introducing type inference or a database service. A disposable, disk-backed SQLite database holds the joins; Python does not collect the whole dataset into lists or sets. Reports show table/column names and logical record numbers, never data-cell values.

## Install

Python 3.10+ is required. From a clone:

```sh
git clone https://github.com/KanadeK/csv-relation-check.git
cd csv-relation-check
python -m venv .venv
```

Activate with `source .venv/bin/activate` on macOS/Linux or `.venv\Scripts\Activate.ps1` in Windows PowerShell, then `python -m pip install .`. You can also run `python -m csv_relation_check` from the checkout without installing the package. The v0.1.0 Release includes a wheel: `python -m pip install <downloaded-wheel.whl>`. This project is not claimed to be on PyPI.

## Complete demo

```sh
csv-relation-check examples/contract.json --json
csv-relation-check examples/broken-contract.json --json
```

The first exits `0`: both orders refer to known customers. The second exits `1`: one duplicate order key and two missing foreign keys. One missing key is the literal `1`, which does not match customer `001`. Source files remain unchanged.

Minimal contract:

```json
{
  "version": 1,
  "tables": [
    {"name": "customers", "path": "customers.csv", "primary_key": ["id"]},
    {"name": "orders", "path": "orders.csv", "primary_key": ["order_id"],
     "foreign_keys": [{"columns": ["customer_id"],
       "references": {"table": "customers", "columns": ["id"]}}]}
  ]
}
```

Paths resolve from the contract's directory, independently of your current working directory. `--root exports` chooses a different data root; paths and symlinks must stay inside it. Table names and CSV labels are logical identifiers, not executable SQL. Internally generated SQL identifiers and parameterized values avoid treating input as SQL syntax.

```sh
csv-relation-check contract.json --root exports --temp-dir scratch --max-findings 20 --json
```

Create `scratch` first if using that option. Its temporary child database directory is removed after both success and failure.

## Results and exact semantics

Exit `0`: completed, all checks passed. Exit `1`: completed with violations. Exit `2`: contract, parser, I/O, encoding, resource limit or argument error; do not treat a partial check as a pass. JSON goes to stdout; operational errors go to stderr as JSON (argparse retains its usual text usage errors).

The v1 report includes complete `counts`, `rows`, `finding_count`, capped `findings`, `omitted_findings` and `cell_values_included: false`. A finding's `record: 2` means the first data record after the header; multiline quoted cells still occupy one logical record. `rows` includes malformed-width records, which are reported and excluded from relational queries. A record can violate several constraints, so finding counts are not counts of distinct bad rows.

- UTF-8 CSV, optional BOM, explicit one-character delimiter; comma by default. Use `"delimiter": "\t"` for TSV. NUL characters are rejected consistently across supported Python versions.
- Every field is SQLite TEXT with BINARY equality: no trimming, numeric conversion, Unicode normalization or case folding. Whitespace-only text is a value.
- Primary keys must be nonempty and unique. `required` rejects the exact empty string. A `unique` key compares empty strings as literal values, so repeated empty keys violate uniqueness.
- Foreign keys reference a declared primary or unique key in the same contract, with the same arity. `"allow_empty": true` skips only an entirely empty foreign key. Partly empty composite keys always fail. Self-references and cycles between tables are supported as membership checks.
- Repeated/missing/empty column labels, absent constraint columns, unknown contract fields, repeated JSON object keys and nonunique parent-key declarations are input errors. Header-only files are allowed.

See [the full reference](docs/CONTRACT.md) for boundaries and examples.

## Resource and privacy boundaries

Defaults: 1 MiB contract, 64 tables, 256 columns per CSV, 64 columns per key and 64 unique/foreign constraints per table; 5,000,000 records per table; 1,048,576 characters per field; 100 sampled findings. CLI flags change the last three limits. SQLite uses disk-backed tables/indexes and an 8 MiB page-cache target, but SQLite/OS caches, rows and query planning also consume memory. This is not a hard memory/time/disk sandbox, and sufficient temporary disk space is required.

Temporary databases contain original cell values. Ordinary cleanup is not secure erasure and an interrupted/killed process may leave files behind. Choose an appropriate temporary volume using `--temp-dir`. Reports contain schema metadata but no data-cell samples. No telemetry, external requests, source writes or persistent settings are used. The Python API temporarily changes the process-wide CSV field limit and restores it; concurrent threaded calls are unsupported.

## Alternatives and limitations

[Frictionless](https://framework.frictionlessdata.io/) is the better fit for full Table Schema/CSVW ecosystems, type checks, rich formats and remote resources. [sqlite-utils](https://github.com/simonw/sqlite-utils) is a broader importer and database manipulation tool. csv-relation-check keeps a smaller contract, exact identifiers, no runtime packages, disk-backed joins and redacted reports. It does not infer schemas, cast types, repair data, verify business logic, impose row-count minimums, or support remote/archived inputs. v1 contracts are project-specific, not CSVW descriptors.

## Verify and uninstall

```sh
python -m pip install . ruff==0.17.2 build==1.6.1
python -m unittest discover -s tests -v
ruff check .
ruff format --check .
python -m build
python -m pip uninstall csv-relation-check
```

Tests include real CSV parsing, CLI subprocesses, exact/composite keys, malformed inputs, cleanup on failure, SQL-like labels, redaction and a 100,000-record parent table. CI covers Python 3.10/3.13 on Linux, Windows and macOS; see the actual Actions run for status. Remove your virtual environment/downloaded wheel if no longer needed. No project cache is created.

MIT. [Contributing](CONTRIBUTING.md) · [Security](SECURITY.md) · [Third-party notes](THIRD_PARTY.md)
