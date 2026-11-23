"""Adapter for AWS Cost and Usage Report (CUR) CSV files.

Reads both the legacy CUR column names (``lineItem/UsageStartDate``) and the
CUR 2.0 / Data Exports names (``line_item_usage_start_date``) and turns each
line item into a :class:`~cloud_cost_anomaly.loader.CostRow`.

Columns used:

    line item usage start date   -> day (the date part of the timestamp)
    line item product code       -> service
    line item usage account id   -> account
    line item unblended cost     -> cost
    resource tag ``user:<key>``  -> tag, only when a tag key is requested

Tax line items are skipped because they are not usage. Credits and refunds
are kept (they have negative cost).
"""

from __future__ import annotations

import csv
import re
from datetime import date
from typing import IO

from .loader import UNTAGGED, CostFileError, CostRow

SKIPPED_LINE_ITEM_TYPES = {"tax"}


def _norm(name: str) -> str:
    """Lowercase and drop punctuation so both CUR naming styles compare equal."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def read_aws_cur(handle: IO[str], tag_key: str | None = None) -> list[CostRow]:
    """Parse an AWS CUR CSV from an open text file.

    ``tag_key`` is a user-defined cost allocation tag key such as ``team``; the
    ``resourceTags/user:team`` column then becomes the row's tag, shown as
    ``team=<value>``.
    """
    reader = csv.DictReader(handle)
    if reader.fieldnames is None:
        raise CostFileError("cost file is empty (no header row)")
    header = {_norm(name): name for name in reader.fieldnames if name}

    needed = {
        "usage start date": "lineitemusagestartdate",
        "product code": "lineitemproductcode",
        "usage account id": "lineitemusageaccountid",
        "unblended cost": "lineitemunblendedcost",
    }
    missing = [label for label, key in needed.items() if key not in header]
    if missing:
        raise CostFileError(
            "not an AWS CUR CSV, missing column(s): " + ", ".join(missing)
        )
    date_col = header[needed["usage start date"]]
    service_col = header[needed["product code"]]
    account_col = header[needed["usage account id"]]
    cost_col = header[needed["unblended cost"]]
    type_col = header.get("lineitemlineitemtype")

    tag_col = None
    if tag_key:
        wanted = _norm("user:" + tag_key.removeprefix("user:"))
        tag_col = header.get("resourcetags" + wanted)
        if tag_col is None:
            raise CostFileError(
                f"tag column for {tag_key!r} not found; expected a column such as "
                f"'resourceTags/user:{tag_key}'"
            )

    rows: list[CostRow] = []
    for line_no, raw in enumerate(reader, start=2):
        if not any(v.strip() for v in raw.values() if isinstance(v, str)):
            continue
        if type_col and (raw.get(type_col) or "").strip().lower() in SKIPPED_LINE_ITEM_TYPES:
            continue
        stamp = (raw[date_col] or "").strip()
        try:
            day = date.fromisoformat(stamp[:10])
        except ValueError:
            raise CostFileError(f"line {line_no}: usage start date {stamp!r} is not a date") from None
        try:
            cost = float((raw[cost_col] or "").strip())
        except ValueError:
            raise CostFileError(
                f"line {line_no}: unblended cost {raw[cost_col]!r} is not a number"
            ) from None
        if cost != cost or cost in (float("inf"), float("-inf")):
            raise CostFileError(f"line {line_no}: cost must be a finite number")
        tag = UNTAGGED
        if tag_col:
            value = (raw.get(tag_col) or "").strip()
            if value:
                tag = f"{tag_key.removeprefix('user:')}={value}"
        rows.append(
            CostRow(
                day=day,
                service=(raw[service_col] or "").strip() or "(unknown)",
                account=(raw[account_col] or "").strip() or "(unknown)",
                tag=tag,
                cost=cost,
            )
        )
    return rows


def read_aws_cur_file(path: str, tag_key: str | None = None) -> list[CostRow]:
    with open(path, newline="", encoding="utf-8-sig") as handle:
        return read_aws_cur(handle, tag_key)
