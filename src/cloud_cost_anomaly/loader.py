"""Read the daily cost CSV.

Expected columns (header row required, order free, extra columns ignored):

    date     ISO date, YYYY-MM-DD
    service  e.g. "AmazonEC2"
    account  account id or name
    tag      free-form cost allocation tag, may be empty
    cost     non-negative or negative (credits) decimal number
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from typing import IO, Iterable

REQUIRED_COLUMNS = ("date", "service", "account", "cost")
UNTAGGED = "(untagged)"


class CostFileError(ValueError):
    """The cost file is missing columns or contains a row that cannot be parsed."""


@dataclass(frozen=True)
class CostRow:
    day: date
    service: str
    account: str
    tag: str
    cost: float


def read_costs(handle: IO[str]) -> list[CostRow]:
    """Parse a cost CSV from an open text file."""
    reader = csv.DictReader(handle)
    if reader.fieldnames is None:
        raise CostFileError("cost file is empty (no header row)")
    header = {name.strip().lower(): name for name in reader.fieldnames if name}
    missing = [col for col in REQUIRED_COLUMNS if col not in header]
    if missing:
        raise CostFileError(
            "cost file is missing required column(s): " + ", ".join(missing)
        )

    rows: list[CostRow] = []
    for line_no, raw in enumerate(reader, start=2):
        if not any((value or "").strip() for value in raw.values() if isinstance(value, str)):
            continue  # blank line
        try:
            day = date.fromisoformat((raw[header["date"]] or "").strip())
        except ValueError:
            raise CostFileError(
                f"line {line_no}: date {raw[header['date']]!r} is not YYYY-MM-DD"
            ) from None
        try:
            cost = float((raw[header["cost"]] or "").strip())
        except ValueError:
            raise CostFileError(
                f"line {line_no}: cost {raw[header['cost']]!r} is not a number"
            ) from None
        if cost != cost or cost in (float("inf"), float("-inf")):
            raise CostFileError(f"line {line_no}: cost must be a finite number")
        tag = (raw.get(header.get("tag", ""), "") or "").strip() or UNTAGGED
        rows.append(
            CostRow(
                day=day,
                service=(raw[header["service"]] or "").strip() or "(unknown)",
                account=(raw[header["account"]] or "").strip() or "(unknown)",
                tag=tag,
                cost=cost,
            )
        )
    return rows


def read_costs_file(path: str) -> list[CostRow]:
    with open(path, newline="", encoding="utf-8-sig") as handle:
        return read_costs(handle)


def date_span(rows: Iterable[CostRow]) -> tuple[date, date]:
    days = [row.day for row in rows]
    return min(days), max(days)
