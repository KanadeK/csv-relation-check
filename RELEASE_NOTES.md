# v0.1.0

Initial release of the exact-string CSV relationship checker: composite primary/unique/foreign keys, required values, strict CSV structure, local JSON contracts, temporary disk-backed joins and text/JSON reports with redacted cell values. Includes valid/broken export examples, English/Chinese documentation and MIT licensing.

Local validation: 25 unittest cases passed on Windows/Python 3.13, including a 100,000-record parent dataset, failure cleanup, exact identifiers, malformed input, CLI exit codes and report redaction. Ruff checks, wheel/sdist builds, clean environment wheel installation and both README examples are required before upload. Release publication additionally requires all six Linux/Windows/macOS Python 3.10/3.13 CI jobs and sole-owner contributor checks.

Limitations: UTF-8 local CSV/TSV and project-specific v1 contracts only; no inference, type validation, coercion, repair, remote inputs or live cross-file snapshot. Temporary files contain raw values and normal deletion is not secure erasure. See README for resource limits. No PyPI publication is claimed.
