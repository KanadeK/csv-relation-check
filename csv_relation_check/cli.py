from __future__ import annotations

import argparse
import json
import sqlite3
import sys

from . import __version__
from .core import check


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Validate CSV relationships with exact string keys; no cell values in reports."
    )
    parser.add_argument("contract", help="version 1 JSON contract")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--root", help="data root (default: contract directory)")
    parser.add_argument("--temp-dir", help="parent directory for temporary database")
    parser.add_argument("--max-findings", type=int, default=100)
    parser.add_argument("--max-rows", type=int, default=5_000_000, help="maximum records per table")
    parser.add_argument("--max-field-chars", type=int, default=1024**2)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = check(
            args.contract,
            root=args.root,
            temp_dir=args.temp_dir,
            max_findings=args.max_findings,
            max_rows=args.max_rows,
            max_field_chars=args.max_field_chars,
        )
    except (OSError, ValueError, sqlite3.Error, OverflowError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=True), file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=True))
    else:
        print(f"Rows: {sum(report['rows'].values())}; findings: {report['finding_count']}")
        for item in report["findings"]:
            print(json.dumps(item, ensure_ascii=True))
        if report["omitted_findings"]:
            print(f"Omitted findings: {report['omitted_findings']}; counts remain complete")
    return 0 if report["ok"] else 1
