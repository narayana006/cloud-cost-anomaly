"""Render scan results as Markdown or JSON."""

from __future__ import annotations

import json

from .detect import Anomaly, ScanResult, Settings


def _money(value: float) -> str:
    return f"{value:,.2f}"


def _signed(value: float) -> str:
    return f"{'+' if value >= 0 else '-'}{abs(value):,.2f}"


def _pct(value: float | None) -> str:
    return "new spend" if value is None else f"{value:+.0f}%"


def _label(key: dict[str, str]) -> str:
    return " / ".join(key.values())


def _score(value: float) -> str:
    return "inf" if value in (float("inf"), float("-inf")) else f"{abs(value):.1f}"


def to_markdown(result: ScanResult, settings: Settings) -> str:
    lines = [
        "# Cloud cost anomalies",
        "",
        f"Scanned {result.scan_start} to {result.last_day} "
        f"(data starts {result.first_day}), grouped by {' + '.join(settings.group_by)}. "
        f"{result.groups_checked} group(s) checked"
        + (f", {result.groups_skipped} skipped for too little history" if result.groups_skipped else "")
        + ".",
        "",
    ]
    if not result.anomalies:
        lines.append("No anomalies found.")
        return "\n".join(lines) + "\n"

    lines += [
        f"**{len(result.anomalies)} anomal{'y' if len(result.anomalies) == 1 else 'ies'} found**, largest change first.",
        "",
        "| Date | " + " | ".join(name.capitalize() for name in settings.group_by)
        + " | Cost | Baseline | Change | Score |",
        "|---|" + "---|" * len(settings.group_by) + "---:|---:|---:|---:|",
    ]
    for a in result.anomalies:
        lines.append(
            f"| {a.day} | " + " | ".join(a.group[name] for name in settings.group_by)
            + f" | {_money(a.cost)} | {_money(a.baseline)} | {_signed(a.change)} ({_pct(a.change_pct)})"
            + f" | {_score(a.score)} |"
        )
    lines.append("")
    for a in result.anomalies:
        lines += _explain(a)
    return "\n".join(lines) + "\n"


def _explain(a: Anomaly) -> list[str]:
    lines = [
        f"## {a.day} {_label(a.group)}: {a.direction} of {_signed(a.change)}",
        "",
        f"Cost was {_money(a.cost)} against a baseline of {_money(a.baseline)} "
        f"(typical day-to-day spread {_money(a.spread)}).",
        "",
    ]
    if a.contributors:
        lines.append("Top contributors:")
        lines.append("")
        for c in a.contributors:
            lines.append(
                f"- `{_label(c.key)}`: {_money(c.cost)} vs usual {_money(c.baseline)} "
                f"({_signed(c.change)}, {c.share_pct:.0f}% of the change)"
            )
    else:
        lines.append("No finer-grained rows to attribute this change to.")
    lines.append("")
    return lines


def _finite(value: float) -> float | None:
    return None if value in (float("inf"), float("-inf")) else round(value, 2)


def to_json(result: ScanResult, settings: Settings) -> str:
    payload = {
        "first_day": result.first_day.isoformat(),
        "last_day": result.last_day.isoformat(),
        "scan_start": result.scan_start.isoformat(),
        "group_by": list(settings.group_by),
        "groups_checked": result.groups_checked,
        "groups_skipped": result.groups_skipped,
        "anomalies": [
            {
                "date": a.day.isoformat(),
                "group": a.group,
                "direction": a.direction,
                "cost": round(a.cost, 2),
                "baseline": round(a.baseline, 2),
                "spread": round(a.spread, 2),
                "change": round(a.change, 2),
                "change_pct": None if a.change_pct is None else round(a.change_pct, 1),
                "score": _finite(a.score),
                "contributors": [
                    {
                        "key": c.key,
                        "cost": round(c.cost, 2),
                        "baseline": round(c.baseline, 2),
                        "change": round(c.change, 2),
                        "share_pct": round(c.share_pct, 1),
                    }
                    for c in a.contributors
                ],
            }
            for a in result.anomalies
        ],
    }
    return json.dumps(payload, indent=2) + "\n"
