"""Basic dashboard for Slack user uptime."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from config import POLL_SECONDS, SUPABASE_SERVICE_KEY, SUPABASE_URL
from uptime import calculate_active_seconds, format_duration_rounded

IST = ZoneInfo("Asia/Kolkata")

app = FastAPI(title="Slack Uptime Dashboard")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
_start_time: datetime | None = None


@app.on_event("startup")
def _on_startup() -> None:
    global _start_time
    _start_time = datetime.now(timezone.utc)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


def get_ist_today() -> date:
    return datetime.now(IST).date()


def _script_uptime_meta() -> tuple[float, str | None]:
    if not _start_time:
        return 0.0, None
    elapsed = (datetime.now(timezone.utc) - _start_time).total_seconds()
    return round(elapsed / 3600, 1), _start_time.isoformat()


def get_supabase():
    from db import create_client

    return create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


def _rows_from_daily_uptime(supabase, target_date: date) -> list[dict]:
    resp = supabase.table("daily_uptime").select("*").eq("date", target_date.isoformat()).execute()
    rows = resp.data or []
    return [
        {
            "user_id": r.get("user_id"),
            "user_email": r.get("user_email"),
            "user_name": r.get("user_name"),
            "total_seconds_online": int(r.get("total_seconds_online", 0) or 0),
        }
        for r in rows
        if r.get("user_id")
    ]


def _rows_from_snapshots(supabase, target_date: date) -> list[dict]:
    start = datetime.combine(target_date, datetime.min.time(), tzinfo=IST)
    end = start + timedelta(days=1)

    resp = (
        supabase.table("presence_snapshots")
        .select("*")
        .gte("polled_at", start.isoformat())
        .lt("polled_at", end.isoformat())
        .execute()
    )
    totals = calculate_active_seconds(resp.data or [], fallback_interval_seconds=POLL_SECONDS)
    return list(totals.values())


def _merge_rows(primary_rows: list[dict], live_rows: list[dict]) -> list[dict]:
    merged: dict[str, dict] = {}

    def _upsert(row: dict) -> None:
        uid = row.get("user_id")
        if not uid:
            return
        seconds = int(row.get("total_seconds_online", 0) or 0)
        current = merged.get(uid)
        if current is None or seconds >= current.get("total_seconds_online", 0):
            merged[uid] = {
                "user_id": uid,
                "user_email": row.get("user_email") or (current or {}).get("user_email"),
                "user_name": row.get("user_name") or (current or {}).get("user_name"),
                "total_seconds_online": seconds,
            }

    for row in primary_rows:
        _upsert(row)
    for row in live_rows:
        _upsert(row)

    return list(merged.values())


def _filter_rows(rows: list[dict], query: str) -> list[dict]:
    if not query:
        return rows

    q = query.strip().lower()
    if not q:
        return rows

    return [
        r
        for r in rows
        if q in (r.get("user_email") or "").lower() or q in (r.get("user_name") or "").lower()
    ]


def _build_rows(supabase, target_date: date) -> list[dict]:
    daily_rows = _rows_from_daily_uptime(supabase, target_date)
    live_rows = _rows_from_snapshots(supabase, target_date)
    return _merge_rows(daily_rows, live_rows)


def _to_api_user(row: dict) -> dict:
    seconds = int(row.get("total_seconds_online", 0) or 0)
    return {
        "email": row.get("user_email"),
        "name": row.get("user_name"),
        "total_seconds_online": seconds,
        "formatted": format_duration_rounded(seconds),
    }


@app.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
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
        return templates.TemplateResponse(
            "dashboard.html",
            {
                "request": request,
                "users": [],
                "date": target_date,
                "search": q,
                "error": "Supabase not configured",
                "script_uptime_hrs": 0,
                "script_start_time": None,
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

    script_uptime_hrs, start_time_iso = _script_uptime_meta()
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
    rows.sort(key=lambda r: -int(r.get("total_seconds_online", 0) or 0))
    script_uptime_hrs, start_time_iso = _script_uptime_meta()

    return {
        "date": target_date.isoformat(),
        "script_uptime_hrs": script_uptime_hrs,
        "script_start_time": start_time_iso,
        "users": [_to_api_user(r) for r in rows],
    }
