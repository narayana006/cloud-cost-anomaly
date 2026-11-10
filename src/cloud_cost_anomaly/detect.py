"""Robust anomaly detection on daily cost series.

Each group (by default service + account) gets one daily series. A day is
compared with the days immediately before it: the baseline is the median of
that trailing window and the spread is the median absolute deviation (MAD).
Both are barely moved by earlier spikes, so one bad day does not hide the next.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from statistics import median
from typing import Sequence

from .loader import CostRow

GROUP_FIELDS = ("service", "account", "tag")
# Scales MAD so it estimates a standard deviation for normally distributed data.
MAD_TO_SIGMA = 1.4826


@dataclass(frozen=True)
class Settings:
    days: int = 30  # how many of the most recent days to check
    baseline_days: int = 14  # trailing window each day is compared with
    min_history: int = 7  # days of history needed before a day is judged
    threshold: float = 3.5  # robust z-score needed to flag a day
    min_change: float = 10.0  # ignore deviations smaller than this (currency units)
    min_spread_pct: float = 5.0  # floor on spread, as % of the baseline
    direction: str = "up"  # "up", "down" or "both"
    group_by: tuple[str, ...] = ("service", "account")
    top: int = 3  # contributors listed per anomaly

    def validate(self) -> None:
        if self.days < 1 or self.baseline_days < 1 or self.min_history < 1:
            raise ValueError("days, baseline-days and min-history must be at least 1")
        if self.min_history > self.baseline_days:
            raise ValueError("min-history cannot be larger than baseline-days")
        if self.threshold <= 0:
            raise ValueError("threshold must be positive")
        if self.direction not in ("up", "down", "both"):
            raise ValueError("direction must be up, down or both")
        if not self.group_by or any(f not in GROUP_FIELDS for f in self.group_by):
            raise ValueError("group-by must be a combination of: " + ", ".join(GROUP_FIELDS))
        if len(set(self.group_by)) != len(self.group_by):
            raise ValueError("group-by lists a field twice")


@dataclass(frozen=True)
class Contributor:
    """One slice of an anomalous group and how far it moved from its own baseline."""

    key: dict[str, str]
    cost: float
    baseline: float
    change: float
    share_pct: float  # share of the group's total change, can exceed 100


@dataclass(frozen=True)
class Anomaly:
    day: date
    group: dict[str, str]
    cost: float
    baseline: float
    spread: float
    score: float
    change: float
    change_pct: float | None  # None when the baseline is zero
    direction: str  # "spike" or "drop"
    contributors: list[Contributor] = field(default_factory=list)


@dataclass(frozen=True)
class ScanResult:
    first_day: date
    last_day: date
    scan_start: date
    groups_checked: int
    groups_skipped: int  # groups with too little history to judge any day
    anomalies: list[Anomaly]


def robust_baseline(history: Sequence[float], min_spread_pct: float = 5.0) -> tuple[float, float]:
    """Return (median, spread) for a window of daily costs.

    Spread is the scaled MAD, floored at ``min_spread_pct`` percent of the
    median so that a perfectly flat series (MAD of zero, common for
    reserved or fixed-price services) does not flag cent-sized wobbles.
    """
    centre = median(history)
    mad = median(abs(value - centre) for value in history)
    spread = max(MAD_TO_SIGMA * mad, abs(centre) * min_spread_pct / 100.0)
    return centre, spread


def _key(row: CostRow, fields: Sequence[str]) -> tuple[str, ...]:
    return tuple(getattr(row, name) for name in fields)


def _daily_totals(rows: Sequence[CostRow], fields: Sequence[str]) -> dict[tuple[str, ...], dict[date, float]]:
    totals: dict[tuple[str, ...], dict[date, float]] = defaultdict(lambda: defaultdict(float))
    for row in rows:
        totals[_key(row, fields)][row.day] += row.cost
    return totals


def _window(series: dict[date, float], day: date, length: int, first_day: date) -> list[float]:
    """Costs for the ``length`` days before ``day``; days with no rows count as zero."""
    values = []
    for offset in range(length, 0, -1):
        earlier = day - timedelta(days=offset)
        if earlier >= first_day:
            values.append(series.get(earlier, 0.0))
    return values


def _score(cost: float, centre: float, spread: float) -> float:
    if spread > 0:
        return (cost - centre) / spread
    if cost == centre:
        return 0.0
    return float("inf") if cost > centre else float("-inf")


def scan(rows: Sequence[CostRow], settings: Settings = Settings()) -> ScanResult:
    """Find anomalous days in the most recent ``settings.days`` days of ``rows``."""
    settings.validate()
    if not rows:
        raise ValueError("no cost rows to scan")

    first_day = min(row.day for row in rows)
    last_day = max(row.day for row in rows)
    scan_start = max(first_day, last_day - timedelta(days=settings.days - 1))

    group_fields = settings.group_by
    detail_fields = tuple(f for f in GROUP_FIELDS if f not in group_fields)
    totals = _daily_totals(rows, group_fields)
    detail_totals = _daily_totals(rows, group_fields + detail_fields) if detail_fields else {}

    anomalies: list[Anomaly] = []
    skipped = 0
    for group_key in sorted(totals):
        series = totals[group_key]
        group_first = min(series)
        judged = False
        day = scan_start
        while day <= last_day:
            # A group's history starts on its first billed day, so a service that
            # is switched on mid-file is not compared with weeks of zeros.
            history = _window(series, day, settings.baseline_days, group_first)
            if len(history) >= settings.min_history:
                judged = True
                cost = series.get(day, 0.0)
                centre, spread = robust_baseline(history, settings.min_spread_pct)
                score = _score(cost, centre, spread)
                change = cost - centre
                is_spike = score >= settings.threshold and change >= settings.min_change
                is_drop = score <= -settings.threshold and -change >= settings.min_change
                if (is_spike and settings.direction in ("up", "both")) or (
                    is_drop and settings.direction in ("down", "both")
                ):
                    anomalies.append(
                        Anomaly(
                            day=day,
                            group=dict(zip(group_fields, group_key)),
                            cost=cost,
                            baseline=centre,
                            spread=spread,
                            score=score,
                            change=change,
                            change_pct=(change / centre * 100.0) if centre > 0 else None,
                            direction="spike" if is_spike else "drop",
                            contributors=_contributors(
                                detail_totals, group_key, group_fields, detail_fields,
                                day, change, settings, group_first,
                            ),
                        )
                    )
            day += timedelta(days=1)
        if not judged:
            skipped += 1

    anomalies.sort(key=lambda a: (-abs(a.change), a.day, sorted(a.group.items())))
    return ScanResult(
        first_day=first_day,
        last_day=last_day,
        scan_start=scan_start,
        groups_checked=len(totals) - skipped,
        groups_skipped=skipped,
        anomalies=anomalies,
    )


def _contributors(
    detail_totals: dict[tuple[str, ...], dict[date, float]],
    group_key: tuple[str, ...],
    group_fields: Sequence[str],
    detail_fields: Sequence[str],
    day: date,
    group_change: float,
    settings: Settings,
    group_first: date,
) -> list[Contributor]:
    """Rank the slices inside a group by how much each moved in the anomaly's direction."""
    if not detail_fields:
        return []
    width = len(group_fields)
    found = []
    for key, series in detail_totals.items():
        if key[:width] != group_key:
            continue
        history = _window(series, day, settings.baseline_days, group_first)
        baseline = median(history) if history else 0.0
        cost = series.get(day, 0.0)
        change = cost - baseline
        # Keep only slices that moved the same way as the group.
        if change * group_change <= 0:
            continue
        found.append(
            Contributor(
                key=dict(zip(detail_fields, key[width:])),
                cost=cost,
                baseline=baseline,
                change=change,
                share_pct=change / group_change * 100.0,
            )
        )
    found.sort(key=lambda c: (-abs(c.change), sorted(c.key.items())))
    return found[: settings.top]
