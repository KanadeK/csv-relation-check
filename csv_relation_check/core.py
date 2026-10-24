"""Small, exact-string relationship contracts backed by a disposable SQLite database."""

from __future__ import annotations

import csv
import json
import sqlite3
import tempfile
from collections import Counter
from pathlib import Path


class InputError(ValueError):
    """The input or contract could not be completely checked."""


def _object(value, allowed, required, where):
    if not isinstance(value, dict) or set(value) - set(allowed) or set(required) - set(value):
        raise InputError(f"{where}: invalid object fields")


def _columns(value, where, allow_empty=False):
    if not isinstance(value, list) or (not value and not allow_empty):
        raise InputError(f"{where}: expected a column list")
    if any(not isinstance(v, str) or not v or "\x00" in v for v in value):
        raise InputError(f"{where}: column names must be nonempty strings without NUL")
    if len(value) != len(set(value)) or len(value) > 64:
        raise InputError(f"{where}: repeated or too many columns")
    return value


def _distinct_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InputError("contract contains repeated JSON object keys")
        result[key] = value
    return result


def load_contract(path, root=None):
    path = Path(path)
    if path.stat().st_size > 1024**2:
        raise InputError("contract exceeds 1 MiB")
    try:
        spec = json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=_distinct_object)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise InputError("contract must be valid UTF-8 JSON") from exc
    _object(spec, ["version", "tables"], ["version", "tables"], "contract")
    if type(spec["version"]) is not int or spec["version"] != 1:
        raise InputError("contract version must be 1")
    if not isinstance(spec["tables"], list) or not 1 <= len(spec["tables"]) <= 64:
        raise InputError("contract requires 1..64 tables")
    base = Path(root).resolve() if root is not None else path.resolve().parent
    tables = {}
    for table in spec["tables"]:
        _object(
            table,
            ["name", "path", "delimiter", "primary_key", "required", "unique", "foreign_keys"],
            ["name", "path"],
            "table",
        )
        name = table["name"]
        if not isinstance(name, str) or not name or "\x00" in name or name in tables:
            raise InputError("table names must be nonempty and distinct")
        relative = table["path"]
        if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
            raise InputError("CSV path must be relative to the data root")
        target = (base / relative).resolve()
        if not target.is_relative_to(base):
            raise InputError("CSV path escapes the data root (including symlinks)")
        delimiter = table.get("delimiter", ",")
        if not isinstance(delimiter, str) or len(delimiter) != 1 or delimiter in '\r\n\x00"':
            raise InputError("delimiter must be one non-newline, non-NUL, non-quote character")
        table = dict(table, resolved=target)
        table["primary_key"] = _columns(table.get("primary_key", []), "primary_key", True)
        table["required"] = _columns(table.get("required", []), "required", True)
        for key in ("unique", "foreign_keys"):
            if not isinstance(table.get(key, []), list) or len(table.get(key, [])) > 64:
                raise InputError(f"{key}: expected at most 64 constraints")
        table["unique"] = [_columns(key, "unique") for key in table.get("unique", [])]
        table["foreign_keys"] = table.get("foreign_keys", [])
        for fk in table["foreign_keys"]:
            _object(
                fk,
                ["columns", "references", "allow_empty"],
                ["columns", "references"],
                "foreign_key",
            )
            _columns(fk["columns"], "foreign_key.columns")
            _object(fk["references"], ["table", "columns"], ["table", "columns"], "references")
            _columns(fk["references"]["columns"], "references.columns")
            if not isinstance(fk["references"]["table"], str):
                raise InputError("reference table must be a name")
            if len(fk["columns"]) != len(fk["references"]["columns"]):
                raise InputError("foreign key arity mismatch")
            if type(fk.get("allow_empty", False)) is not bool:
                raise InputError("allow_empty must be boolean")
        tables[name] = table
    for table in tables.values():
        for fk in table["foreign_keys"]:
            ref = fk["references"]
            parent = tables.get(ref["table"])
            if parent is None or ref["columns"] not in [parent["primary_key"], *parent["unique"]]:
                raise InputError("foreign keys must reference a declared primary or unique key")
    return tables


def check(
    contract,
    *,
    root=None,
    temp_dir=None,
    max_findings=100,
    max_rows=5_000_000,
    max_field_chars=1024**2,
):
    """Validate all records; findings contain metadata only, never cell values.

    ``max_rows`` is per table. The process-wide CSV field limit is restored on return;
    callers must not run this function concurrently in multiple Python threads.
    """
    for value in (max_findings, max_rows, max_field_chars):
        if type(value) is not int or value <= 0:
            raise InputError("limits must be positive integers")
    tables = load_contract(contract, root)
    findings = []
    counts = Counter()
    rows = {}

    def emit(code, table, record, columns, related=None):
        counts[code] += 1
        if len(findings) < max_findings:
            item = {"code": code, "table": table, "record": record, "columns": columns}
            if related is not None:
                item["references_table"] = related
            findings.append(item)

    previous_field_limit = csv.field_size_limit(max_field_chars)
    try:
        with tempfile.TemporaryDirectory(prefix="csv-relation-", dir=temp_dir) as scratch:
            database = sqlite3.connect(Path(scratch) / "relations.sqlite3")
            try:
                database.execute("PRAGMA cache_size=-8192")
                database.execute("PRAGMA temp_store=FILE")
                for index, (name, table) in enumerate(tables.items()):
                    table["sql"] = f"t{index}"
                    with table["resolved"].open(encoding="utf-8-sig", newline="") as source:
                        reader = csv.reader(
                            source, delimiter=table.get("delimiter", ","), strict=True
                        )
                        header = next(reader, None)
                        if (
                            not header
                            or len(header) > 256
                            or any(not h or "\x00" in h for h in header)
                            or len(set(header)) != len(header)
                        ):
                            raise InputError(
                                f"{name}: CSV needs 1..256 distinct nonempty column labels"
                            )
                        table["header"] = header
                        table["cols"] = {h: f"c{i}" for i, h in enumerate(header)}
                        referenced = [table["required"], table["primary_key"], *table["unique"]]
                        referenced += [fk["columns"] for fk in table["foreign_keys"]]
                        if any(col not in header for group in referenced for col in group):
                            raise InputError(
                                f"{name}: a constraint column is absent from the header"
                            )
                        columns = ",".join(
                            c + " TEXT NOT NULL COLLATE BINARY" for c in table["cols"].values()
                        )
                        sql_table = table["sql"]
                        database.execute(
                            f"CREATE TABLE {sql_table} (record INTEGER PRIMARY KEY,{columns})"
                        )
                        insert = f"INSERT INTO {sql_table} VALUES ({','.join('?' for _ in range(len(header) + 1))})"
                        count = 0
                        for record, row in enumerate(reader, 2):
                            count += 1
                            if any("\x00" in value for value in row):
                                raise InputError(f"{name}: NUL is not supported in CSV data")
                            if count > max_rows:
                                raise InputError(f"{name}: max-rows exceeded; scan incomplete")
                            if len(row) != len(header):
                                emit("row-width", name, record, [])
                                continue
                            database.execute(insert, [record, *row])
                            if any(row[header.index(c)] == "" for c in table["primary_key"]):
                                emit("empty-primary-key", name, record, table["primary_key"])
                            for column in table["required"]:
                                if row[header.index(column)] == "":
                                    emit("required-empty", name, record, [column])
                        rows[name] = count
                    groups = [table["primary_key"], *table["unique"]]
                    for number, group in enumerate(filter(None, groups)):
                        fields = ",".join(table["cols"][c] for c in group)
                        database.execute(
                            f"CREATE INDEX i{index}_{number} ON {sql_table} ({fields})"
                        )
                database.commit()
                for name, table in tables.items():
                    sql_table, cols = table["sql"], table["cols"]
                    for group in filter(None, [table["primary_key"], *table["unique"]]):
                        equality = " AND ".join(f"b.{cols[c]}=a.{cols[c]}" for c in group)
                        nonempty = (
                            " AND ".join(f"a.{cols[c]}<>''" for c in group)
                            if group == table["primary_key"]
                            else "1"
                        )
                        query = f"SELECT a.record FROM {sql_table} a WHERE {nonempty} AND EXISTS (SELECT 1 FROM {sql_table} b WHERE {equality} AND b.record<a.record) ORDER BY a.record"
                        for (record,) in database.execute(query):
                            emit("duplicate-key", name, record, group)
                    for fk in table["foreign_keys"]:
                        ref = fk["references"]
                        parent = tables[ref["table"]]
                        if any(c not in parent["header"] for c in ref["columns"]):
                            raise InputError("reference column absent from parent header")
                        own = [cols[c] for c in fk["columns"]]
                        empty = " + ".join(f"(a.{c}='')" for c in own)
                        conditions = " AND ".join(
                            f"a.{left}=b.{parent['cols'][right]}"
                            for left, right in zip(own, ref["columns"], strict=True)
                        )
                        query = f"SELECT a.record, ({empty}) FROM {sql_table} a WHERE ({empty})>0 OR NOT EXISTS (SELECT 1 FROM {parent['sql']} b WHERE {conditions}) ORDER BY a.record"
                        for record, blanks in database.execute(query):
                            if blanks == len(own) and fk.get("allow_empty", False):
                                continue
                            code = (
                                "partial-foreign-key"
                                if 0 < blanks < len(own)
                                else "missing-foreign-key"
                            )
                            emit(code, name, record, fk["columns"], ref["table"])
            finally:
                database.close()
    except (csv.Error, UnicodeError) as exc:
        raise InputError(
            "CSV decoding/parsing failed (UTF-8, strict CSV and field-size policy required)"
        ) from exc
    finally:
        csv.field_size_limit(previous_field_limit)
    count = sum(counts.values())
    return {
        "schema_version": 1,
        "ok": count == 0,
        "rows": rows,
        "finding_count": count,
        "counts": dict(sorted(counts.items())),
        "findings": findings,
        "omitted_findings": count - len(findings),
        "cell_values_included": False,
    }
