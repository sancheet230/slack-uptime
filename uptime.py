"""Utilities for converting presence snapshots into uptime durations."""
from __future__ import annotations

from datetime import datetime


MAX_GAP_MULTIPLIER = 3


def _parse_polled_at(value: str | None) -> datetime | None:
    if not value:
        return None

    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _is_online(row: dict) -> bool:
    """Treat `online=True` as active even if text presence is stale."""
    if row.get("online") is True:
        return True
    return row.get("presence") == "active"


def calculate_active_seconds(
    snapshots: list[dict],
    fallback_interval_seconds: int,
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
        ordered = sorted(rows, key=lambda r: r.get("polled_at") or "")
        total_seconds = 0

        for idx, row in enumerate(ordered):
            if not _is_online(row):
                continue

            current_ts = _parse_polled_at(row.get("polled_at"))
            next_row = ordered[idx + 1] if idx + 1 < len(ordered) else None
            next_ts = _parse_polled_at(next_row.get("polled_at")) if next_row else None

            if current_ts and next_ts and next_ts > current_ts:
                diff = int((next_ts - current_ts).total_seconds())
                max_allowed = max(1, fallback_interval_seconds) * MAX_GAP_MULTIPLIER
                total_seconds += max(0, min(diff, max_allowed))
            else:
                total_seconds += max(1, fallback_interval_seconds)

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
