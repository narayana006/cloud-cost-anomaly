"""Adapter for Google Cloud billing export rows saved as CSV.

Reads the standard usage cost export from BigQuery (query the export table and
save the result as CSV) and turns each row into a
:class:`~cloud_cost_anomaly.loader.CostRow`. Both dotted and flattened column
names are accepted (``service.description`` or ``service_description``).

Columns used:

    usage_start_time              -> day (the date part of the timestamp)
    service.description           -> service
    project.id                    -> account
    cost                          -> cost
    credits (JSON, optional)      -> amounts are added to the cost (they are
                                     negative), giving the net cost
    labels  (JSON, optional)      -> tag, only when a label key is requested
"""

from __future__ import annotations

import csv
import json
import re
from datetime import date
from typing import IO

from .loader import UNTAGGED, CostFileError, CostRow


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _json_list(text: str, line_no: int, column: str) -> list:
    text = text.strip()
    if not text or text == "null":
        return []
    try:
        value = json.loads(text)
    except ValueError:
        raise CostFileError(f"line {line_no}: {column} is not valid JSON") from None
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list):
        raise CostFileError(f"line {line_no}: {column} must be a JSON array")
    return value


def _number(value: object, line_no: int, what: str) -> float:
    try:
        number = float(str(value).strip())
    except ValueError:
        raise CostFileError(f"line {line_no}: {what} {value!r} is not a number") from None
    if number != number or number in (float("inf"), float("-inf")):
        raise CostFileError(f"line {line_no}: {what} must be a finite number")
    return number


def read_gcp_billing(
    handle: IO[str], label_key: str | None = None, include_credits: bool = True
) -> list[CostRow]:
    """Parse a Google Cloud billing export CSV from an open text file.

    ``label_key`` is a resource label key such as ``team``; the matching entry
    of the ``labels`` column becomes the row's tag, shown as ``team=<value>``.
    With ``include_credits`` false the gross ``cost`` is used and credits
    (committed use discounts, promotions and so on) are ignored.
    """
    reader = csv.DictReader(handle)
    if reader.fieldnames is None:
        raise CostFileError("cost file is empty (no header row)")
    header = {_norm(name): name for name in reader.fieldnames if name}

    needed = {
        "usage_start_time": ("usagestarttime",),
        "service.description": ("servicedescription",),
        "project.id": ("projectid",),
        "cost": ("cost",),
    }
    columns: dict[str, str] = {}
    missing = []
    for label, keys in needed.items():
        found = next((header[k] for k in keys if k in header), None)
        if found is None:
            missing.append(label)
        else:
            columns[label] = found
    if missing:
        raise CostFileError(
            "not a Google Cloud billing export CSV, missing column(s): " + ", ".join(missing)
        )
    credits_col = header.get("credits") if include_credits else None
    labels_col = header.get("labels")
    if label_key and labels_col is None:
        raise CostFileError(f"label {label_key!r} requested but the file has no 'labels' column")

    rows: list[CostRow] = []
    for line_no, raw in enumerate(reader, start=2):
        if not any(v.strip() for v in raw.values() if isinstance(v, str)):
            continue
        stamp = (raw[columns["usage_start_time"]] or "").strip()
        try:
            day = date.fromisoformat(stamp[:10])
        except ValueError:
            raise CostFileError(f"line {line_no}: usage_start_time {stamp!r} is not a date") from None
        cost = _number(raw[columns["cost"]] or "", line_no, "cost")
        if credits_col:
            for credit in _json_list(raw.get(credits_col) or "", line_no, "credits"):
                if isinstance(credit, dict) and credit.get("amount") not in (None, ""):
                    cost += _number(credit["amount"], line_no, "credit amount")
        tag = UNTAGGED
        if label_key and labels_col:
            for label in _json_list(raw.get(labels_col) or "", line_no, "labels"):
                if isinstance(label, dict) and label.get("key") == label_key and label.get("value"):
                    tag = f"{label_key}={label['value']}"
                    break
        rows.append(
            CostRow(
                day=day,
                service=(raw[columns["service.description"]] or "").strip() or "(unknown)",
                account=(raw[columns["project.id"]] or "").strip() or "(unknown)",
                tag=tag,
                cost=cost,
            )
        )
    return rows


def read_gcp_billing_file(
    path: str, label_key: str | None = None, include_credits: bool = True
) -> list[CostRow]:
    with open(path, newline="", encoding="utf-8-sig") as handle:
        return read_gcp_billing(handle, label_key, include_credits)
