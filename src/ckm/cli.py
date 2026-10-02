"""`ckm` command line: extract, check, pilot."""

import argparse
import sys
from pathlib import Path

from ckm.config import load_config
from ckm.extract import run_extract
from ckm.gates import run_checks
from ckm.pilot import score_pilot
from ckm.vault import Vault


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to cp1252
    parser = argparse.ArgumentParser(prog="ckm", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    ex = sub.add_parser("extract", help="convert an HTML export into the vault")
    ex.add_argument("--export", type=Path, required=True, help="Confluence HTML export folder")
    ex.add_argument("--vault", type=Path, required=True, help="output vault folder")
    ex.add_argument("--config", type=Path, help="config JSON (default: config/ckm.json)")
    ex.add_argument("--dry-run", action="store_true", help="report changes, write nothing")
    ex.add_argument("--limit", type=int, help="process only the first N pages (no archiving)")
    ex.add_argument("--today", help="override the extraction date (YYYY-MM-DD)")

    ck = sub.add_parser("check", help="run quality gates over a vault")
    ck.add_argument("--vault", type=Path, required=True)
    ck.add_argument("--strict", action="store_true", help="treat warnings as errors")

    pi = sub.add_parser("pilot", help="score a retrieval pilot")
    pi.add_argument("--questions", type=Path, required=True)
    pi.add_argument("--answers", type=Path, required=True)

    args = parser.parse_args(argv)
    if args.command == "extract":
        return _extract(args)
    if args.command == "check":
        return _check(args)
    return _pilot(args)


def _extract(args: argparse.Namespace) -> int:
    report = run_extract(
        args.export,
        Vault(args.vault),
        load_config(args.config),
        today=args.today,
        dry_run=args.dry_run,
        limit=args.limit,
    )
    prefix = "[dry-run] " if args.dry_run else ""
    print(f"{prefix}{report.summary()}")
    for page_id, refs in sorted(report.unresolved.items()):
        print(f"  unresolved in {page_id}: {', '.join(refs)}")
    for page_id in report.blocked:
        print(f"  BLOCKED {page_id}: redaction hit — see manifest.csv note")
    return 1 if report.blocked else 0


def _check(args: argparse.Namespace) -> int:
    findings = run_checks(Vault(args.vault))
    for finding in findings:
        print(finding)
    errors = sum(f.severity == "error" for f in findings)
    warnings = sum(f.severity == "warning" for f in findings)
    print(f"{errors} error(s), {warnings} warning(s)")
    return 1 if errors or (args.strict and warnings) else 0


def _pilot(args: argparse.Namespace) -> int:
    result = score_pilot(args.questions, args.answers)
    print(result.summary())
    for miss in result.misses:
        print(f"  miss {miss}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
