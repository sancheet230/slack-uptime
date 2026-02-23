"""
Aggregates presence snapshots into daily uptime per user.
Run periodically (e.g. via cron or a separate scheduler) to keep daily_uptime table fresh.
"""
import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from config import SUPABASE_URL, SUPABASE_SERVICE_KEY, POLL_SECONDS
from uptime import calculate_active_seconds

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")


def get_supabase():
    from db import create_client
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


def aggregate_day(supabase, target_date: date):
    """Compute total online seconds per user for a given date and upsert into daily_uptime."""
    start = datetime.combine(target_date, datetime.min.time(), tzinfo=IST)
    end = start + timedelta(days=1)

    resp = supabase.table("presence_snapshots").select("*").gte(
        "polled_at", start.isoformat()
    ).lt("polled_at", end.isoformat()).execute()

    totals = calculate_active_seconds(resp.data or [], fallback_interval_seconds=POLL_SECONDS)

    for uid, data in totals.items():
        try:
            supabase.table("daily_uptime").upsert({
                "user_id": uid,
                "user_email": data["user_email"],
                "user_name": data["user_name"],
                "date": target_date.isoformat(),
                "total_seconds_online": data["total_seconds_online"],
            }, on_conflict="user_id,date").execute()
        except Exception as e:
            logger.warning("Upsert failed for %s: %s", uid, e)

    logger.info("Aggregated %s: %d users", target_date, len(totals))


def main():
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        logger.error("Supabase credentials required")
        return 1

    supabase = get_supabase()
    today = datetime.now(IST).date()
    aggregate_day(supabase, today)
    return 0


if __name__ == "__main__":
    exit(main())
