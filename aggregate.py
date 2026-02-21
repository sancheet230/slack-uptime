"""
Aggregates presence snapshots into daily uptime per user.
Run periodically (e.g. via cron or a separate scheduler) to keep daily_uptime table fresh.
"""
import logging
from datetime import date, datetime, timezone, timedelta
from config import SUPABASE_URL, SUPABASE_SERVICE_KEY, POLL_SECONDS

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def get_supabase():
    from db import create_client
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


def aggregate_day(supabase, target_date: date):
    """Compute total online seconds per user for a given date and upsert into daily_uptime."""
    start = datetime.combine(target_date, datetime.min.time(), tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    start_str = start.isoformat()
    end_str = end.isoformat()

    resp = supabase.table("presence_snapshots").select("*").gte(
        "polled_at", start_str
    ).lt("polled_at", end_str).execute()

    rows = resp.data or []
    by_user: dict[str, dict] = {}

    for r in rows:
        uid = r["user_id"]
        if uid not in by_user:
            by_user[uid] = {"email": r.get("user_email"), "name": r.get("user_name"), "active_count": 0}
        if r.get("presence") == "active":
            by_user[uid]["active_count"] += 1

    for uid, data in by_user.items():
        total_seconds = data["active_count"] * POLL_SECONDS
        try:
            supabase.table("daily_uptime").upsert({
                "user_id": uid,
                "user_email": data["email"],
                "user_name": data["name"],
                "date": target_date.isoformat(),
                "total_seconds_online": total_seconds,
            }, on_conflict="user_id,date").execute()
        except Exception as e:
            logger.warning("Upsert failed for %s: %s", uid, e)

    logger.info("Aggregated %s: %d users", target_date, len(by_user))


def main():
    from config import SUPABASE_URL, SUPABASE_SERVICE_KEY
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        logger.error("Supabase credentials required")
        return 1

    supabase = get_supabase()
    today = date.today()
    aggregate_day(supabase, today)
    return 0


if __name__ == "__main__":
    exit(main())
