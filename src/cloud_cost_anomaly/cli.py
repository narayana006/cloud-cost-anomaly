"""Command-line entry point."""

from __future__ import annotations

import argparse
import sys

from . import __version__
from .aws_cur import read_aws_cur, read_aws_cur_file
from .gcp_billing import read_gcp_billing, read_gcp_billing_file
from .detect import GROUP_FIELDS, Settings, scan
from .loader import CostFileError, read_costs, read_costs_file
from .report import to_json, to_markdown


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cloud-cost-anomaly",
        description="Detect unusual daily cloud spend from a cost CSV and explain what caused it.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("scan", help="scan a daily cost CSV for anomalies")
    p.add_argument("--export", required=True, metavar="FILE",
                   help="daily cost CSV (date,service,account,tag,cost); '-' reads stdin")
    p.add_argument("--source", choices=("generic", "aws-cur", "gcp-billing"),
                   default="generic",
                   help="input layout: the generic daily CSV, an AWS Cost and Usage "
                        "Report CSV, or a Google Cloud billing export CSV (default: generic)")
    p.add_argument("--tag-key", metavar="KEY",
                   help="with --source aws-cur: use the resourceTags/user:KEY column as the tag; "
                        "with gcp-billing: use the label KEY from the labels column")
    p.add_argument("--ignore-credits", action="store_true",
                   help="with --source gcp-billing: use gross cost and ignore the credits column")
    p.add_argument("--days", type=int, default=30,
                   help="check the most recent N days in the file (default: 30)")
    p.add_argument("--baseline-days", type=int, default=14,
                   help="trailing days each day is compared with (default: 14)")
    p.add_argument("--min-history", type=int, default=7,
                   help="days of history required before a day is judged (default: 7)")
    p.add_argument("--threshold", type=float, default=3.5,
                   help="robust z-score needed to flag a day (default: 3.5)")
    p.add_argument("--min-change", type=float, default=10.0,
                   help="ignore changes smaller than this amount (default: 10)")
    p.add_argument("--direction", choices=("up", "down", "both"), default="up",
                   help="flag spikes, drops or both (default: up)")
    p.add_argument("--group-by", default="service,account",
                   help="comma-separated fields to detect on: "
                        + ", ".join(GROUP_FIELDS) + " (default: service,account)")
    p.add_argument("--top", type=int, default=3,
                   help="contributors to list per anomaly (default: 3)")
    p.add_argument("--format", choices=("markdown", "json"), default="markdown",
                   help="output format (default: markdown)")
    p.add_argument("--output", metavar="FILE", help="write the report here instead of stdout")
    p.add_argument("--fail-on-anomaly", action="store_true",
                   help="exit with status 2 when at least one anomaly is found")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = Settings(
        days=args.days,
        baseline_days=args.baseline_days,
        min_history=args.min_history,
        threshold=args.threshold,
        min_change=args.min_change,
        direction=args.direction,
        group_by=tuple(part.strip() for part in args.group_by.split(",") if part.strip()),
        top=max(args.top, 0),
    )
    try:
        settings.validate()
        if args.tag_key and args.source == "generic":
            raise ValueError("--tag-key only applies with --source aws-cur or gcp-billing")
        if args.ignore_credits and args.source != "gcp-billing":
            raise ValueError("--ignore-credits only applies with --source gcp-billing")
        if args.source == "gcp-billing":
            credits = not args.ignore_credits
            rows = (read_gcp_billing(sys.stdin, args.tag_key, credits) if args.export == "-"
                    else read_gcp_billing_file(args.export, args.tag_key, credits))
        elif args.source == "aws-cur":
            rows = (read_aws_cur(sys.stdin, args.tag_key) if args.export == "-"
                    else read_aws_cur_file(args.export, args.tag_key))
        else:
            rows = read_costs(sys.stdin) if args.export == "-" else read_costs_file(args.export)
        if not rows:
            raise CostFileError("cost file has a header but no data rows")
        result = scan(rows, settings)
    except (OSError, ValueError) as exc:
        print(f"cloud-cost-anomaly: error: {exc}", file=sys.stderr)
        return 1

    text = to_json(result, settings) if args.format == "json" else to_markdown(result, settings)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(text)
    else:
        sys.stdout.write(text)
    return 2 if args.fail_on_anomaly and result.anomalies else 0


if __name__ == "__main__":
    sys.exit(main())
