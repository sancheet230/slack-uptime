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


def format_duration(seconds: int) -> str:
    """Format seconds as readable string (e.g. 2h 30m 15s)."""
    if seconds <= 0:
        return "0s"
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    if hours > 0:
        return f"{hours}h {minutes}m {secs}s"
    elif minutes > 0:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


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
            {"request": request, "users": [], "date": target_date, "search": q, "error": "Supabase not configured", "script_uptime_hrs": round(elapsed / 3600, 1)},
        )

    supabase = get_supabase()

    # Prefer daily_uptime; fallback to computing from presence_snapshots
    start = datetime.combine(target_date, datetime.min.time(), tzinfo=IST)
    end = datetime.combine(target_date, datetime.min.time(), tzinfo=IST) + timedelta(days=1)
    start_str = start.isoformat()
    end_str = end.isoformat()

    resp = supabase.table("daily_uptime").select("*").eq("date", target_date.isoformat()).execute()
    rows = resp.data or []

    if not rows:
        # Compute from presence_snapshots
        snap_resp = supabase.table("presence_snapshots").select("*").gte(
            "polled_at", start_str
        ).lt("polled_at", end_str).execute()
        snapshots = snap_resp.data or []
        by_user: dict[str, dict] = {}
        for s in snapshots:
            uid = s["user_id"]
            if uid not in by_user:
                by_user[uid] = {"user_email": s.get("user_email"), "user_name": s.get("user_name"), "count": 0}
            if s.get("presence") == "active":
                by_user[uid]["count"] += 1
        actual_poll_interval = POLL_SECONDS + (len(by_user) * 3.5) if by_user else POLL_SECONDS
        rows = [
            {
                "user_id": uid,
                "user_email": data["user_email"],
                "user_name": data["user_name"],
                "total_seconds_online": int(data["count"] * actual_poll_interval),
            }
            for uid, data in by_user.items()
        ]

    # Search filter
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
            "formatted": format_duration(r.get("total_seconds_online", 0)),
        }
        for r in rows
    ]
    users.sort(key=lambda x: -x["seconds"])

    # Script uptime in hours (how long the app has been running)
    script_uptime_hrs = 0
    start_time_iso = None
    if _start_time:
        elapsed = (datetime.now(timezone.utc) - _start_time).total_seconds()
        script_uptime_hrs = round(elapsed / 3600, 1)
        start_time_iso = _start_time.isoformat()

    return templates.TemplateResponse(
        "dashboard.html",
        {"request": request, "users": users, "date": target_date, "search": q, "script_uptime_hrs": script_uptime_hrs, "script_start_time": start_time_iso},
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

    supabase = get_supabase()
    start = datetime.combine(target_date, datetime.min.time(), tzinfo=IST)
    end = datetime.combine(target_date, datetime.min.time(), tzinfo=IST) + timedelta(days=1)
    start_str = start.isoformat()
    end_str = end.isoformat()

    resp = supabase.table("daily_uptime").select("*").eq("date", target_date.isoformat()).execute()
    rows = resp.data or []

    if not rows:
        snap_resp = supabase.table("presence_snapshots").select("*").gte(
            "polled_at", start_str
        ).lt("polled_at", end_str).execute()
        snapshots = snap_resp.data or []
        by_user = {}
        for s in snapshots:
            uid = s["user_id"]
            if uid not in by_user:
                by_user[uid] = {"user_email": s.get("user_email"), "user_name": s.get("user_name"), "count": 0}
            if s.get("presence") == "active":
                by_user[uid]["count"] += 1
        actual_poll_interval = POLL_SECONDS + (len(by_user) * 3.5) if by_user else POLL_SECONDS
        rows = [
            {
                "user_id": uid,
                "user_email": data["user_email"],
                "user_name": data["user_name"],
                "total_seconds_online": int(data["count"] * actual_poll_interval),
            }
            for uid, data in by_user.items()
        ]

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
                "formatted": format_duration(r.get("total_seconds_online", 0)),
            }
            for r in rows
        ],
    }
