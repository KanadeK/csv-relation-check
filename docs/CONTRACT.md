# Version 1 contract

The top-level object accepts only `version: 1` and `tables: [...]`. Repeated JSON object keys are rejected. Each table accepts:

| Field | Required | Meaning |
|---|---|---|
| `name` | yes | Distinct nonempty logical table name |
| `path` | yes | Local relative CSV path confined to the data root |
| `delimiter` | no | One character, default comma; no newline, NUL or quote |
| `primary_key` | no | Ordered column-name array, nonempty values and uniqueness |
| `required` | no | Column-name array whose fields must not equal `""` |
| `unique` | no | Array of nonempty column-name arrays; literal value uniqueness |
| `foreign_keys` | no | Array of membership constraints |

An empty `primary_key` disables that constraint. Column lists cannot repeat a name. A foreign key has `columns`, `references: {"table": "name", "columns": [...]}`, and optional boolean `allow_empty` (default false). Referenced columns, in order, must equal the parent's primary key or one declared unique key. Tables may be declared in any order.

Composite example:

```json
{"columns": ["country", "customer"],
 "references": {"table": "customers", "columns": ["country_code", "customer_id"]},
 "allow_empty": true}
```

For this constraint, `("", "")` is allowed, `("US", "")` fails, and `("US", "001")` must exist verbatim in the parent. No concatenated string key is used, so delimiter-like text inside a component cannot alias another tuple.

Finding codes: `row-width`, `empty-primary-key`, `required-empty`, `duplicate-key`, `partial-foreign-key`, `missing-foreign-key`. Duplicate-key findings name each later record matching an earlier key; blank primary keys get the empty-primary finding instead. A parent with duplicate keys fails its own uniqueness check even when child membership happens to match.

Architecture: strict CSV reader → generated SQLite tables with TEXT/BINARY columns → indexes on declared parent keys → required/key checks and NOT EXISTS joins → metadata-only report. SQLite files live under a private temporary child directory and connections are closed before removal. Input paths are resolved and checked for containment, including symlinks at resolution time; this is not protection against a different process racing to replace a path. Run on a stable export snapshot.

Acceptance: a complete valid contract passes; an orphan, duplicate key, partial composite key or ragged row fails with a logical record location; identifiers preserve their textual representation; aggregate violations remain complete when samples are capped; errors do not include cell contents; temporary directories are removed after success and ordinary exceptions. Large-input tests validate correctness, not a claimed memory/performance benchmark.

Out of scope: SQL execution, database mutation, network resources, globbing, compressed data, type validation, normalization, repair, data inference and a live consistent snapshot across files being actively rewritten. Supply a stable export and explicit relationships.
