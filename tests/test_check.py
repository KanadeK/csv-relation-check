import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from csv_relation_check.core import InputError, check


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.contract = self.root / "contract.json"
        self.scratch = self.root / "scratch"
        self.scratch.mkdir()

    def table(self, name, header, rows, **constraints):
        path = self.root / f"{name}.csv"
        with path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(header)
            writer.writerows(rows)
        return {"name": name, "path": path.name, **constraints}

    def spec(self, tables):
        self.contract.write_text(json.dumps({"version": 1, "tables": tables}), encoding="utf-8")
        return self.contract

    def pair(self, values=("001",)):
        parent = self.table(
            "customers",
            ["id", "name"],
            [("001", "Private Customer")],
            primary_key=["id"],
            required=["name"],
        )
        child = self.table(
            "orders",
            ["id", "customer"],
            [(str(n), v) for n, v in enumerate(values)],
            primary_key=["id"],
            foreign_keys=[
                {"columns": ["customer"], "references": {"table": "customers", "columns": ["id"]}}
            ],
        )
        return [parent, child]

    def test_valid_relations_input_unchanged_and_scratch_cleaned(self):
        self.spec(self.pair())
        before = {p: p.read_bytes() for p in self.root.glob("*.csv")}
        result = check(self.contract, temp_dir=self.scratch)
        self.assertTrue(result["ok"])
        self.assertEqual({"customers": 1, "orders": 1}, result["rows"])
        self.assertEqual([], list(self.scratch.iterdir()))
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_leading_zeros_case_and_spaces_remain_distinct(self):
        self.spec(self.pair(("1", "001", "001 ", "ABC", "abc")))
        result = check(self.contract)
        self.assertEqual(4, result["counts"]["missing-foreign-key"])
        self.assertEqual([2, 4, 5, 6], [f["record"] for f in result["findings"]])

    def test_report_does_not_include_cell_values(self):
        self.spec(self.pair(("PRIVATE-MISSING-KEY",)))
        text = json.dumps(check(self.contract))
        self.assertNotIn("PRIVATE-MISSING-KEY", text)
        self.assertNotIn("Private Customer", text)

    def test_composite_keys_do_not_use_ambiguous_concatenation(self):
        parent = self.table("p", ["a", "b"], [("a|b", "c"), ("a", "b|c")], primary_key=["a", "b"])
        child = self.table(
            "c",
            ["x", "y"],
            [("a", "b|c"), ("a|b", "c"), ("a", "c")],
            foreign_keys=[
                {"columns": ["x", "y"], "references": {"table": "p", "columns": ["a", "b"]}}
            ],
        )
        result = check(self.spec([parent, child]))
        self.assertEqual({"missing-foreign-key": 1}, result["counts"])
        self.assertEqual(4, result["findings"][0]["record"])

    def test_primary_unique_required_and_blank_rules(self):
        table = self.table(
            "p",
            ["id", "email", "name"],
            [("", "same", ""), ("", "same", " "), ("A", "other", "ok"), ("A", "third", "ok")],
            primary_key=["id"],
            unique=[["email"]],
            required=["name"],
        )
        result = check(self.spec([table]))
        self.assertEqual(
            {"empty-primary-key": 2, "duplicate-key": 2, "required-empty": 1}, result["counts"]
        )

    def test_nullable_composite_only_skips_all_empty(self):
        p = self.table("p", ["a", "b"], [("A", "B")], primary_key=["a", "b"])
        c = self.table(
            "c",
            ["a", "b"],
            [("", ""), ("A", ""), ("A", "B")],
            foreign_keys=[
                {
                    "columns": ["a", "b"],
                    "references": {"table": "p", "columns": ["a", "b"]},
                    "allow_empty": True,
                }
            ],
        )
        result = check(self.spec([p, c]))
        self.assertEqual({"partial-foreign-key": 1}, result["counts"])
        c["foreign_keys"][0]["allow_empty"] = False
        result = check(self.spec([p, c]))
        self.assertEqual(1, result["counts"]["missing-foreign-key"])

    def test_unique_parent_key_reference_and_reversed_load_order(self):
        p = self.table("p", ["id", "code"], [("1", "XY")], primary_key=["id"], unique=[["code"]])
        c = self.table(
            "c",
            ["code"],
            [("XY",)],
            foreign_keys=[{"columns": ["code"], "references": {"table": "p", "columns": ["code"]}}],
        )
        self.assertTrue(check(self.spec([c, p]))["ok"])

    def test_self_reference(self):
        t = self.table(
            "nodes",
            ["id", "parent"],
            [("A", ""), ("B", "A")],
            primary_key=["id"],
            foreign_keys=[
                {
                    "columns": ["parent"],
                    "references": {"table": "nodes", "columns": ["id"]},
                    "allow_empty": True,
                }
            ],
        )
        self.assertTrue(check(self.spec([t]))["ok"])

    def test_multiline_records_and_width_errors(self):
        table = self.table(
            "p", ["id", "text"], [("A", "line1\nline2"), ("B",), ("C", "ok")], primary_key=["id"]
        )
        result = check(self.spec([table]))
        self.assertEqual({"row-width": 1}, result["counts"])
        self.assertEqual(3, result["findings"][0]["record"])
        self.assertEqual(3, result["rows"]["p"])

    def test_sql_metacharacters_in_labels_and_values(self):
        col = 'id"; DROP TABLE t0;--'
        t = self.table(
            "safe",
            [col, "ID"],
            [("x'); DROP TABLE t0; --", "a"), ("other", "a")],
            primary_key=[col],
        )
        t["name"] = 'table weird "name'
        self.assertTrue(check(self.spec([t]))["ok"])

    def test_nul_data_is_rejected_consistently(self):
        self.spec(self.pair())
        (self.root / "orders.csv").write_bytes(b"id,customer\n1,PRIVATE\x00DATA\n")
        with self.assertRaises(InputError) as caught:
            check(self.contract, temp_dir=self.scratch)
        self.assertNotIn("PRIVATE", str(caught.exception))
        self.assertEqual([], list(self.scratch.iterdir()))

    def test_duplicate_json_object_keys_are_rejected(self):
        self.contract.write_text('{"version":1,"version":1,"tables":[]}')
        with self.assertRaises(InputError):
            check(self.contract)

    def test_deep_json_is_a_clean_input_error(self):
        self.contract.write_text("[" * 2000 + "0" + "]" * 2000)
        with self.assertRaises(InputError):
            check(self.contract)

    def test_non_utf8_csv_and_cleanup(self):
        self.spec(self.pair())
        (self.root / "orders.csv").write_bytes(b"id,customer\n1,\xff\n")
        with self.assertRaises(InputError):
            check(self.contract, temp_dir=self.scratch)
        self.assertEqual([], list(self.scratch.iterdir()))

    def test_tsv(self):
        t = self.table("p", ["id", "name"], [("a", "A")], primary_key=["id"], delimiter="\t")
        (self.root / "p.csv").write_text("id\tname\na\tA\n")
        self.assertTrue(check(self.spec([t]))["ok"])

    def test_findings_cap_does_not_change_totals(self):
        self.spec(self.pair(("missing",) * 10))
        report = check(self.contract, max_findings=2)
        self.assertEqual(10, report["finding_count"])
        self.assertEqual(8, report["omitted_findings"])

    def test_max_rows_and_field_limit_cleanup(self):
        self.spec(self.pair(("long value", "other")))
        before = csv.field_size_limit()
        for options in ({"max_rows": 1}, {"max_field_chars": 2}):
            with self.assertRaises(InputError):
                check(self.contract, temp_dir=self.scratch, **options)
            self.assertEqual([], list(self.scratch.iterdir()))
            self.assertEqual(before, csv.field_size_limit())

    def test_bad_headers(self):
        for header in (["id", "id"], ["", "id"], []):
            with self.subTest(header=header), self.assertRaises(InputError):
                check(self.spec([self.table("p", header, [])]))

    def test_unknown_column_and_nonunique_parent_are_input_errors(self):
        tables = self.pair()
        tables[0]["primary_key"] = ["missing"]
        with self.assertRaises(InputError):
            check(self.spec(tables))
        tables = self.pair()
        del tables[0]["primary_key"]
        with self.assertRaises(InputError):
            check(self.spec(tables))

    def test_path_escape_is_rejected(self):
        t = {"name": "p", "path": "../outside.csv"}
        with self.assertRaises(InputError):
            check(self.spec([t]))

    def test_missing_file_cleans_temp(self):
        self.spec([{"name": "p", "path": "missing.csv"}])
        with self.assertRaises(OSError):
            check(self.contract, temp_dir=self.scratch)
        self.assertEqual([], list(self.scratch.iterdir()))

    def test_invalid_json_and_contract_types(self):
        for value in (
            [],
            {"version": True, "tables": []},
            {"version": 1, "tables": [{"name": "p", "path": "p.csv", "foreign_keys": ["x"]}]},
            {"version": 1, "tables": [], "typo": True},
        ):
            with self.subTest(value=value):
                self.contract.write_text(json.dumps(value))
                with self.assertRaises(InputError):
                    check(self.contract)
        self.contract.write_text("{broken")
        with self.assertRaises(InputError):
            check(self.contract)

    def test_invalid_limits(self):
        self.spec(self.pair())
        for value in (0, -1, True, 1.5):
            with self.assertRaises(InputError):
                check(self.contract, max_rows=value)

    def test_malformed_csv_no_private_content_in_error(self):
        self.spec(self.pair())
        (self.root / "orders.csv").write_text('id,customer\n"PRIVATE-UNTERMINATED')
        with self.assertRaises(InputError) as caught:
            check(self.contract)
        self.assertNotIn("PRIVATE-UNTERMINATED", str(caught.exception))

    def test_cli_clean_invalid_and_operational_errors(self):
        for values, code in [(("001",), 0), (("unmatched",), 1)]:
            self.spec(self.pair(values))
            result = subprocess.run(
                [sys.executable, "-m", "csv_relation_check", str(self.contract), "--json"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(code, result.returncode, result.stderr)
            self.assertEqual(code == 0, json.loads(result.stdout)["ok"])
        self.contract.write_text("invalid")
        result = subprocess.run(
            [sys.executable, "-m", "csv_relation_check", str(self.contract)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(2, result.returncode)
        self.assertNotIn("Traceback", result.stderr)

    def test_100k_record_flow(self):
        p = self.table("p", ["id"], ((f"{i:08}",) for i in range(100_000)), primary_key=["id"])
        c = self.table(
            "c",
            ["id"],
            [(f"{99_999:08}",), ("not-there",)],
            foreign_keys=[{"columns": ["id"], "references": {"table": "p", "columns": ["id"]}}],
        )
        report = check(self.spec([p, c]), temp_dir=self.scratch)
        self.assertEqual({"p": 100_000, "c": 2}, report["rows"])
        self.assertEqual({"missing-foreign-key": 1}, report["counts"])
        self.assertEqual([], list(self.scratch.iterdir()))
