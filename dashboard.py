"""
Basic dashboard for Slack user uptime.
Shows user email/name and total online time per date, with search.
"""
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from config import POLL_SECONDS, SUPABASE_SERVICE_KEY, SUPABASE_URL
from uptime import calculate_active_seconds, format_duration_rounded

IST = ZoneInfo("Asia/Kolkata")


def get_ist_today() -> date:
    return datetime.now(IST).date()


app = FastAPI(title="Slack Uptime Dashboard")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

_start_time: datetime | None = None


@app.on_event("startup")
def _on_startup():
    global _start_time
    _start_time = datetime.now(timezone.utc)


@app.get("/health")
async def health():
    return {"status": "ok"}


def get_supabase():
    from db import create_client

    return create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


def _rows_from_snapshots(supabase, target_date: date) -> list[dict]:
    start = datetime.combine(target_date, datetime.min.time(), tzinfo=IST)
    end = start + timedelta(days=1)

    snap_resp = (
        supabase.table("presence_snapshots")
        .select("*")
        .gte("polled_at", start.isoformat())
        .lt("polled_at", end.isoformat())
        .execute()
    )
    snapshots = snap_resp.data or []
    totals = calculate_active_seconds(snapshots, fallback_interval_seconds=POLL_SECONDS)
    return list(totals.values())


def _merge_rows(primary_rows: list[dict], live_rows: list[dict]) -> list[dict]:
    """Merge rows by user_id, keeping the larger total to avoid zero/stale regressions."""
    merged: dict[str, dict] = {}

    for row in primary_rows:
        uid = row.get("user_id")
        if not uid:
            continue
        merged[uid] = {
            "user_id": uid,
            "user_email": row.get("user_email"),
            "user_name": row.get("user_name"),
            "total_seconds_online": int(row.get("total_seconds_online", 0) or 0),
        }

    for row in live_rows:
        uid = row.get("user_id")
        if not uid:
            continue
        seconds = int(row.get("total_seconds_online", 0) or 0)
        existing = merged.get(uid)
        if not existing or seconds > existing.get("total_seconds_online", 0):
            merged[uid] = {
                "user_id": uid,
                "user_email": row.get("user_email") or (existing or {}).get("user_email"),
                "user_name": row.get("user_name") or (existing or {}).get("user_name"),
                "total_seconds_online": seconds,
            }

    return list(merged.values())


def _build_rows(supabase, target_date: date) -> list[dict]:
    """Build rows with aggregate-first strategy plus live guard for today's data."""
    resp = supabase.table("daily_uptime").select("*").eq("date", target_date.isoformat()).execute()
    aggregate_rows = resp.data or []

    live_rows = _rows_from_snapshots(supabase, target_date)

    if target_date == get_ist_today():
        # Today is still changing; merge with live data to avoid stale/zero aggregates.
        return _merge_rows(aggregate_rows, live_rows)

    if aggregate_rows:
        return aggregate_rows
    return live_rows


def _script_uptime_meta() -> tuple[float, str | None]:
    script_uptime_hrs = 0.0
    start_time_iso = None
    if _start_time:
        elapsed = (datetime.now(timezone.utc) - _start_time).total_seconds()
        script_uptime_hrs = round(elapsed / 3600, 1)
        start_time_iso = _start_time.isoformat()
    return script_uptime_hrs, start_time_iso


def _filter_rows(rows: list[dict], q: str) -> list[dict]:
    if not q:
        return rows
    ql = q.lower()
    return [
        r
        for r in rows
        if (r.get("user_email") or "").lower().find(ql) >= 0
        or (r.get("user_name") or "").lower().find(ql) >= 0
    ]


@app.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    q: str = Query(default="", description="Search user by name or email"),
    d: str = Query(default=None, description="Date (YYYY-MM-DD)"),
):
    target_date = get_ist_today()
    if d:
        try:
            target_date = date.fromisoformat(d)
        except ValueError:
            pass

    script_uptime_hrs, start_time_iso = _script_uptime_meta()

    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        return templates.TemplateResponse(
            "dashboard.html",
            {
                "request": request,
                "users": [],
                "date": target_date,
                "search": q,
                "error": "Supabase not configured",
                "script_uptime_hrs": script_uptime_hrs,
                "script_start_time": start_time_iso,
            },
        )

    rows = _filter_rows(_build_rows(get_supabase(), target_date), q)
    users = [
        {
            "email": r.get("user_email") or "(no email)",
            "name": r.get("user_name") or "(no name)",
            "seconds": int(r.get("total_seconds_online", 0) or 0),
            "formatted": format_duration_rounded(int(r.get("total_seconds_online", 0) or 0)),
        }
        for r in rows
    ]
    users.sort(key=lambda x: -x["seconds"])

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "users": users,
            "date": target_date,
            "search": q,
            "script_uptime_hrs": script_uptime_hrs,
            "script_start_time": start_time_iso,
        },
    )


@app.get("/api/uptime")
async def api_uptime(
    d: str = Query(default=None),
    q: str = Query(default=""),
):
    target_date = get_ist_today()
    if d:
        try:
            target_date = date.fromisoformat(d)
        except ValueError:
            pass

    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        return {"error": "Supabase not configured", "users": []}

    rows = _filter_rows(_build_rows(get_supabase(), target_date), q)
    script_uptime_hrs, start_time_iso = _script_uptime_meta()

    return {
        "date": target_date.isoformat(),
        "script_uptime_hrs": script_uptime_hrs,
        "script_start_time": start_time_iso,
        "users": [
            {
                "email": r.get("user_email"),
                "name": r.get("user_name"),
                "total_seconds_online": int(r.get("total_seconds_online", 0) or 0),
                "formatted": format_duration_rounded(int(r.get("total_seconds_online", 0) or 0)),
            }
            for r in rows
        ],
    }
