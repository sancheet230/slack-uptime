"""
Entry point: runs poller + optional daily aggregator in background,
dashboard server in foreground. Designed for 24/7 operation.
"""
import os
import threading
import time
import uvicorn
from config import SLACK_BOT_TOKEN, SUPABASE_URL, SUPABASE_SERVICE_KEY


def run_poller():
    from poller import main
    main()


def run_aggregator():
    """Run aggregate.py periodically to keep daily_uptime table fresh."""
    from aggregate import get_supabase, aggregate_day
    from datetime import date
    while True:
        try:
            if SUPABASE_URL and SUPABASE_SERVICE_KEY:
                supabase = get_supabase()
                aggregate_day(supabase, date.today())
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("Aggregator error: %s", e)
        time.sleep(3600)  # Every hour


def run_dashboard():
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("dashboard:app", host="0.0.0.0", port=port)


if __name__ == "__main__":
    if not SLACK_BOT_TOKEN or not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        print("Set SLACK_BOT_TOKEN, SUPABASE_URL, SUPABASE_SERVICE_KEY in .env")
        exit(1)

    # Poller: runs forever, collects presence every POLL_SECONDS
    t_poller = threading.Thread(target=run_poller, daemon=True)
    t_poller.start()

    # Aggregator: runs every hour to pre-compute daily totals (faster dashboard)
    t_agg = threading.Thread(target=run_aggregator, daemon=True)
    t_agg.start()

    # Dashboard: main process
    run_dashboard()
