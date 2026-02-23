"""Utilities for converting presence snapshots into uptime durations."""
from __future__ import annotations

from datetime import datetime
from statistics import median


MAX_GAP_MULTIPLIER = 3


def _parse_polled_at(value: str | datetime | None) -> datetime | None:
    if isinstance(value, datetime):
        return value

    if not value:
        return None

    normalized = str(value).strip().replace(" ", "T").replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _is_online(row: dict) -> bool:
    """Treat `online=True` as active even if text presence is stale."""
    online = row.get("online")
    if isinstance(online, str):
        online = online.strip().lower() in {"true", "t", "1", "yes", "y", "on"}

    if bool(online):
        return True
    return str(row.get("presence") or "").strip().lower() == "active"


def calculate_active_seconds(
    snapshots: list[dict],
    fallback_interval_seconds: int,
    include_tail_interval: bool = True,
) -> dict[str, dict]:
    """Return per-user totals computed from active durations between snapshots.

    Duration is credited from one snapshot until the next snapshot of the same user,
    when the current snapshot indicates the user is online/active.
    The final active snapshot gets a conservative fallback interval.
    """
    by_user: dict[str, list[dict]] = {}
    for row in snapshots:
        uid = row.get("user_id")
        if uid:
            by_user.setdefault(uid, []).append(row)

    totals: dict[str, dict] = {}
    for uid, rows in by_user.items():
        ordered = sorted(rows, key=lambda r: _parse_polled_at(r.get("polled_at")) or datetime.min)
        total_seconds = 0

        observed_gaps: list[int] = []
        for idx in range(len(ordered) - 1):
            current_ts = _parse_polled_at(ordered[idx].get("polled_at"))
            next_ts = _parse_polled_at(ordered[idx + 1].get("polled_at"))
            if current_ts and next_ts and next_ts > current_ts:
                observed_gaps.append(int((next_ts - current_ts).total_seconds()))

        inferred_interval = int(median(observed_gaps)) if observed_gaps else max(1, fallback_interval_seconds)
        inferred_interval = max(1, inferred_interval)
        max_allowed_gap = inferred_interval * MAX_GAP_MULTIPLIER

        for idx, row in enumerate(ordered):
            if not _is_online(row):
                continue

            current_ts = _parse_polled_at(row.get("polled_at"))
            next_row = ordered[idx + 1] if idx + 1 < len(ordered) else None
            next_ts = _parse_polled_at(next_row.get("polled_at")) if next_row else None

            if current_ts and next_ts and next_ts > current_ts:
                diff = int((next_ts - current_ts).total_seconds())
                total_seconds += max(0, min(diff, max_allowed_gap))
            elif include_tail_interval:
                total_seconds += inferred_interval

        first = ordered[0]
        totals[uid] = {
            "user_id": uid,
            "user_email": first.get("user_email"),
            "user_name": first.get("user_name"),
            "total_seconds_online": int(total_seconds),
        }

    return totals


def format_duration_rounded(seconds: int) -> str:
    """Format seconds as compact user-facing duration without seconds."""
    if seconds <= 0:
        return "0m"

    minutes = int(round(seconds / 60))
    hours = minutes // 60
    rem_minutes = minutes % 60

    if hours > 0:
        return f"{hours}h {rem_minutes}m" if rem_minutes else f"{hours}h"
    return f"{max(1, minutes)}m"
