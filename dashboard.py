"""
Basic dashboard for Slack user uptime.
Shows user email/name and total online time per date, with search.
"""
from datetime import date, datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from fastapi import FastAPI, Request, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

from uptime import calculate_active_seconds, format_duration_rounded

IST = ZoneInfo("Asia/Kolkata")


def get_ist_today() -> date:
    return datetime.now(IST).date()


from config import SUPABASE_URL, SUPABASE_SERVICE_KEY, POLL_SECONDS

app = FastAPI(title="Slack Uptime Dashboard")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

# Track app start for script uptime display
_start_time: datetime | None = None


@app.on_event("startup")
def _on_startup():
    global _start_time
    _start_time = datetime.now(timezone.utc)


@app.get("/health")
async def health():
    """Health check for load balancers and monitoring."""
    return {"status": "ok"}


def get_supabase():
    from db import create_client
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


def _build_rows(supabase, target_date: date) -> list[dict]:
    start = datetime.combine(target_date, datetime.min.time(), tzinfo=IST)
    end = start + timedelta(days=1)

    resp = supabase.table("daily_uptime").select("*").eq("date", target_date.isoformat()).execute()
    rows = resp.data or []
    if rows:
        return rows

    snap_resp = supabase.table("presence_snapshots").select("*").gte(
        "polled_at", start.isoformat()
    ).lt("polled_at", end.isoformat()).execute()

    snapshots = snap_resp.data or []
    totals = calculate_active_seconds(snapshots, fallback_interval_seconds=POLL_SECONDS)
    return list(totals.values())


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

    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        elapsed = (datetime.now(timezone.utc) - _start_time).total_seconds() if _start_time else 0
        return templates.TemplateResponse(
            "dashboard.html",
            {
                "request": request,
                "users": [],
                "date": target_date,
                "search": q,
                "error": "Supabase not configured",
                "script_uptime_hrs": round(elapsed / 3600, 1),
            },
        )

    rows = _build_rows(get_supabase(), target_date)

    if q:
        ql = q.lower()
        rows = [
            r for r in rows
            if (r.get("user_email") or "").lower().find(ql) >= 0
            or (r.get("user_name") or "").lower().find(ql) >= 0
        ]

    users = [
        {
            "email": r.get("user_email") or "(no email)",
            "name": r.get("user_name") or "(no name)",
            "seconds": r.get("total_seconds_online", 0),
            "formatted": format_duration_rounded(r.get("total_seconds_online", 0)),
        }
        for r in rows
    ]
    users.sort(key=lambda x: -x["seconds"])

    script_uptime_hrs = 0
    start_time_iso = None
    if _start_time:
        elapsed = (datetime.now(timezone.utc) - _start_time).total_seconds()
        script_uptime_hrs = round(elapsed / 3600, 1)
        start_time_iso = _start_time.isoformat()

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
    """JSON API for uptime data."""
    target_date = get_ist_today()
    if d:
        try:
            target_date = date.fromisoformat(d)
        except ValueError:
            pass

    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        return {"error": "Supabase not configured", "users": []}

    rows = _build_rows(get_supabase(), target_date)

    if q:
        ql = q.lower()
        rows = [
            r for r in rows
            if (r.get("user_email") or "").lower().find(ql) >= 0
            or (r.get("user_name") or "").lower().find(ql) >= 0
        ]

    script_uptime_hrs = 0
    start_time_iso = None
    if _start_time:
        elapsed = (datetime.now(timezone.utc) - _start_time).total_seconds()
        script_uptime_hrs = round(elapsed / 3600, 1)
        start_time_iso = _start_time.isoformat()

    return {
        "date": target_date.isoformat(),
        "script_uptime_hrs": script_uptime_hrs,
        "script_start_time": start_time_iso,
        "users": [
            {
                "email": r.get("user_email"),
                "name": r.get("user_name"),
                "total_seconds_online": r.get("total_seconds_online", 0),
                "formatted": format_duration_rounded(r.get("total_seconds_online", 0)),
            }
            for r in rows
        ],
    }
