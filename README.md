# cloud-cost-anomaly

Detect unusual daily cloud spend from a cost CSV and explain which service, account or tag caused it.

**Status:** early but working. Today it reads a daily cost CSV, flags anomalous days per service and account (or any combination of service, account and tag) against a robust trailing baseline, and names the rows that drove each one, as Markdown or JSON. It does not yet read AWS, Google Cloud or Azure billing exports directly, and it does not send alerts. See the [checklist](#features).

It only reads a file you give it. It never talks to a cloud account.

## Install

Requires Python 3.10 or newer. No third-party dependencies.

```bash
git clone https://github.com/narayana006/cloud-cost-anomaly
cd cloud-cost-anomaly
python -m pip install .
```

## Quick start

The repository ships 45 days of synthetic spend for two accounts in [`examples/daily_costs.csv`](examples/daily_costs.csv), with three planted incidents.

```bash
cloud-cost-anomaly scan --export examples/daily_costs.csv --days 30
```

Output:

```markdown
# Cloud cost anomalies

Scanned 2025-03-12 to 2025-04-10 (data starts 2025-02-25), grouped by service + account. 10 group(s) checked.

**4 anomalies found**, largest change first.

| Date | Service | Account | Cost | Baseline | Change | Score |
|---|---|---|---:|---:|---:|---:|
| 2025-03-28 | AmazonEC2 | prod | 1,403.19 | 776.25 | +626.93 (+81%) | 16.2 |
| 2025-04-03 | AmazonS3 | prod | 225.69 | 79.94 | +145.75 (+182%) | 36.5 |
| 2025-04-07 | AmazonCloudWatch | staging | 68.13 | 7.02 | +61.11 (+871%) | 126.8 |
| 2025-04-06 | AmazonCloudWatch | staging | 64.73 | 7.02 | +57.72 (+823%) | 146.9 |

## 2025-03-28 AmazonEC2 / prod: spike of +626.93

Cost was 1,403.19 against a baseline of 776.25 (typical day-to-day spread 38.81).

Top contributors:

- `team=data`: 855.43 vs usual 256.80 (+598.63, 95% of the change)
- `team=web`: 428.65 vs usual 395.81 (+32.84, 5% of the change)

## 2025-04-03 AmazonS3 / prod: spike of +145.75

Cost was 225.69 against a baseline of 79.94 (typical day-to-day spread 4.00).

Top contributors:

- `team=web`: 164.75 vs usual 22.24 (+142.50, 98% of the change)
- `team=data`: 60.94 vs usual 56.69 (+4.25, 3% of the change)

## 2025-04-07 AmazonCloudWatch / staging: spike of +61.11

Cost was 68.13 against a baseline of 7.02 (typical day-to-day spread 0.48).

Top contributors:

- `(untagged)`: 68.13 vs usual 7.02 (+61.11, 100% of the change)

## 2025-04-06 AmazonCloudWatch / staging: spike of +57.72

Cost was 64.73 against a baseline of 7.02 (typical day-to-day spread 0.39).

Top contributors:

- `(untagged)`: 64.73 vs usual 7.02 (+57.72, 100% of the change)
```

## Input format

A CSV with a header row. Column order does not matter, header names are case-insensitive, and extra columns are ignored.

| Column | Required | Meaning |
|---|---|---|
| `date` | yes | Usage date, `YYYY-MM-DD` |
| `service` | yes | Service or product name, e.g. `AmazonEC2` |
| `account` | yes | Account id or name |
| `tag` | no | One cost-allocation label, e.g. `team=data`. Empty or absent becomes `(untagged)` |
| `cost` | yes | Cost for that row as a plain number (no currency symbol). Negative values (credits) are allowed |

```csv
date,service,account,tag,cost
2025-02-25,AmazonEC2,prod,team=web,387.15
2025-02-25,AmazonEC2,prod,team=data,256.51
2025-02-25,AmazonEC2,prod,team=platform,122.19
2025-02-25,AmazonCloudWatch,prod,,34.25
```

Several rows may share the same date, service, account and tag; they are summed. A day with no rows for a group counts as zero spend for that group. Most billing tools can produce this shape with a "group by day, service, account, tag" query; you do that conversion yourself for now.

Pass `--export -` to read the CSV from standard input.

## How detection works

1. Rows are summed into one daily series per group. The default group is service + account.
2. Each of the most recent `--days` days is compared with the `--baseline-days` days immediately before it (14 by default). Earlier data in the file is used as history, so `--days 30` works best on a file holding more than 30 days.
3. The baseline is the **median** of that window and the spread is the **median absolute deviation** (MAD) scaled by 1.4826. Both shrug off earlier spikes, so one bad day does not mask the next. The spread is floored at 5% of the baseline so that fixed-price services with a MAD of zero do not flag on cents.
4. A day is flagged when `(cost - baseline) / spread` is at least `--threshold` (3.5) **and** the change is at least `--min-change` (10 currency units).
5. For each flagged day, the fields not used for grouping (the tag, by default) are compared with their own baselines, and the slices that moved the most in the same direction are listed as contributors.

A group is not judged until it has `--min-history` days (7) of its own history, counted from its first billed day, so a newly enabled service is not reported as a spike from zero. The "share of the change" figures are relative to the group's change and can add up to slightly more or less than 100%, because each slice is measured against its own median.

## Options

```
cloud-cost-anomaly scan --export FILE [options]
```

| Option | Default | Meaning |
|---|---|---|
| `--export FILE` | required | Cost CSV, or `-` for stdin |
| `--days N` | 30 | Check the most recent N days in the file (counted back from the last date in the file, not from today) |
| `--baseline-days N` | 14 | Trailing window each day is compared with |
| `--min-history N` | 7 | Days of history needed before a day is judged |
| `--threshold X` | 3.5 | Robust z-score needed to flag a day |
| `--min-change X` | 10 | Ignore changes smaller than this amount |
| `--direction {up,down,both}` | up | Flag spikes, drops, or both |
| `--group-by FIELDS` | service,account | Comma-separated mix of `service`, `account`, `tag` |
| `--top N` | 3 | Contributors listed per anomaly |
| `--format {markdown,json}` | markdown | Output format |
| `--output FILE` | stdout | Write the report to a file |
| `--fail-on-anomaly` | off | Exit with status 2 if anything is flagged, for use in cron or CI |

Exit status is 0 on success, 1 for a bad file or bad options, and 2 with `--fail-on-anomaly` when anomalies exist.

Group by tag to see which team's spend moved, explained by service and account:

```bash
cloud-cost-anomaly scan --export examples/daily_costs.csv --group-by tag
```

JSON for piping into other tools:

```bash
cloud-cost-anomaly scan --export examples/daily_costs.csv --days 5 --top 1 --format json
```

```json
{
  "first_day": "2025-02-25",
  "last_day": "2025-04-10",
  "scan_start": "2025-04-06",
  "group_by": [
    "service",
    "account"
  ],
  "groups_checked": 10,
  "groups_skipped": 0,
  "anomalies": [
    {
      "date": "2025-04-07",
      "group": {
        "service": "AmazonCloudWatch",
        "account": "staging"
      },
      "direction": "spike",
      "cost": 68.13,
      "baseline": 7.02,
      "spread": 0.48,
      "change": 61.11,
      "change_pct": 871.2,
      "score": 126.84,
      "contributors": [
        {
          "key": {
            "tag": "(untagged)"
          },
          "cost": 68.13,
          "baseline": 7.02,
          "change": 61.11,
          "share_pct": 100.0
        }
      ]
    },
    {
      "date": "2025-04-06",
      "group": {
        "service": "AmazonCloudWatch",
        "account": "staging"
      },
      "direction": "spike",
      "cost": 64.73,
      "baseline": 7.02,
      "spread": 0.39,
      "change": 57.72,
      "change_pct": 822.7,
      "score": 146.9,
      "contributors": [
        {
          "key": {
            "tag": "(untagged)"
          },
          "cost": 64.73,
          "baseline": 7.02,
          "change": 57.72,
          "share_pct": 100.0
        }
      ]
    }
  ]
}
```

## Features

- [ ] Reads AWS, Google Cloud and Azure billing exports (today: a generic daily cost CSV only)
- [x] Daily anomaly detection per service, account and tag
- [x] Explains each anomaly by its largest contributing line items
- [ ] Slack or webhook alerts
- [x] No write access to cloud accounts required (reads a local file or stdin, makes no network calls)

## Limitations

- No adapters for AWS CUR, Google Cloud billing export or Azure cost exports, and no `s3://` paths. You must flatten your export to the CSV above first.
- No weekly seasonality model. A service that is much more expensive on one weekday than the others can be flagged on that day; widen `--baseline-days`, raise `--threshold`, or use `--min-change` to quieten it.
- A sustained step change is reported for roughly the first half of the baseline window, until the median catches up. There is no separate "level shift" classification.
- One `tag` value per row. Multiple tag keys need to be combined into one string (for example `team=data;env=prod`) before export.
- Costs are treated as plain numbers. Mixed currencies are not converted.
- The example data is synthetic.

## Development

```bash
python -m pip install -e ".[dev]"
python -m pytest
python examples/generate_sample.py   # regenerates the sample CSV deterministically
```

## Contributing

Issues and pull requests are welcome. The most useful contributions right now are billing-export adapters that turn a real AWS, Google Cloud or Azure export into the CSV schema above, and reports of false positives with a (scrubbed) series that reproduces them. Please include a test with any code change.

Built and maintained by [Narayana Vemburaj](https://github.com/narayana006).

## License

[MIT](LICENSE)
