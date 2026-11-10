"""Regenerate examples/daily_costs.csv.

Synthetic data: 45 days of spend for two accounts, with three planted events:

* 2025-03-28  AmazonEC2 in prod: a batch fleet tagged team=data is left running
* 2025-04-03  AmazonS3 in prod: a one-day burst of requests tagged team=web
* 2025-04-06  AmazonCloudWatch in staging: debug logging left on (untagged), 2 days

Run from the repository root:  python examples/generate_sample.py
"""

import csv
import random
from datetime import date, timedelta
from pathlib import Path

START = date(2025, 2, 25)
DAYS = 45

# (service, account, tag) -> (typical daily cost, relative noise, weekend factor)
SERIES = {
    ("AmazonEC2", "prod", "team=web"): (410.0, 0.03, 0.85),
    ("AmazonEC2", "prod", "team=data"): (265.0, 0.05, 0.90),
    ("AmazonEC2", "prod", "team=platform"): (120.0, 0.02, 1.0),
    ("AmazonEC2", "staging", "team=web"): (64.0, 0.06, 0.55),
    ("AmazonEC2", "staging", "team=data"): (38.0, 0.08, 0.55),
    ("AmazonRDS", "prod", "team=web"): (188.0, 0.01, 1.0),
    ("AmazonRDS", "prod", "team=data"): (96.0, 0.01, 1.0),
    ("AmazonRDS", "staging", "team=web"): (31.0, 0.01, 1.0),
    ("AmazonS3", "prod", "team=web"): (22.0, 0.05, 0.9),
    ("AmazonS3", "prod", "team=data"): (57.0, 0.04, 1.0),
    ("AmazonS3", "staging", "team=data"): (6.5, 0.06, 1.0),
    ("AmazonCloudWatch", "prod", ""): (34.0, 0.04, 0.95),
    ("AmazonCloudWatch", "staging", ""): (7.0, 0.06, 0.9),
    ("AWSDataTransfer", "prod", "team=web"): (48.0, 0.07, 0.8),
    ("AWSLambda", "prod", "team=platform"): (12.0, 0.08, 0.9),
}

EVENTS = {
    (date(2025, 3, 28), "AmazonEC2", "prod", "team=data"): 612.40,
    (date(2025, 4, 3), "AmazonS3", "prod", "team=web"): 141.75,
    (date(2025, 4, 6), "AmazonCloudWatch", "staging", ""): 58.20,
    (date(2025, 4, 7), "AmazonCloudWatch", "staging", ""): 61.05,
}


def main() -> None:
    rng = random.Random(20250225)
    out = Path(__file__).with_name("daily_costs.csv")
    with out.open("w", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["date", "service", "account", "tag", "cost"])
        for offset in range(DAYS):
            day = START + timedelta(days=offset)
            for (service, account, tag), (base, noise, weekend) in SERIES.items():
                cost = base * (1 + rng.gauss(0, noise))
                if day.weekday() >= 5:
                    cost *= weekend
                cost += EVENTS.get((day, service, account, tag), 0.0)
                writer.writerow([day.isoformat(), service, account, tag, f"{cost:.2f}"])
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
