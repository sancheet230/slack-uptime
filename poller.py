"""
Slack presence poller: fetches user presence periodically and stores in Supabase.
Slack API rate limit: 20 users.getPresence calls per minute (Tier 2).
"""
import logging
import time
from datetime import datetime, timezone

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from config import POLL_SECONDS, SLACK_BOT_TOKEN, SUPABASE_SERVICE_KEY, SUPABASE_URL

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

RATE_LIMIT_DELAY = 3.5
USER_CACHE_TTL_SECONDS = 900
# Rate limit: 20 requests/minute for users.getPresence
RATE_LIMIT_DELAY = 3.5  # seconds between presence calls
USER_CACHE_TTL_SECONDS = 900  # refresh member list every 15 minutes


def get_supabase_client():
    from db import create_client

    return create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


def fetch_slack_users(client: WebClient) -> list[dict]:
    users = []
    cursor = None
    while True:
        resp = client.users_list(limit=200, cursor=cursor, include_locale=False)
        for u in resp.get("members", []):
            if u.get("is_bot") or u.get("deleted"):
                continue
            users.append(
                {
                    "user_id": u["id"],
                    "email": u.get("profile", {}).get("email") or "",
                    "real_name": u.get("profile", {}).get("real_name") or u.get("name", ""),
                }
            )
        cursor = resp.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break
    return users


def fetch_presence(client: WebClient, user_id: str) -> dict | None:
    try:
        resp = client.users_getPresence(user=user_id)
        raw_presence = resp.get("presence", "away")
        online_flag = bool(resp.get("online", False))
        normalized_presence = "active" if (online_flag or raw_presence == "active") else "away"
        return {"presence": normalized_presence, "online": online_flag}
    except SlackApiError as e:
        error_code = e.response.get("error") if e.response else "unknown_error"
        if error_code == "missing_scope":
            logger.warning("Need presence:read scope for users.getPresence")
        elif error_code == "ratelimited":
            retry_after = int(e.response.headers.get("Retry-After", "5")) if e.response else 5
            logger.warning("Rate limited by Slack. Sleeping %ss", retry_after)
            time.sleep(retry_after)
        else:
            logger.debug("Presence error for %s: %s", user_id, error_code)
        return None


def run_poll_cycle(client: WebClient, supabase, users: list[dict]):
    """One poll cycle: fetch presence with rate limiting, store in DB."""
    logger.info("Polling presence for %d users", len(users))
    for u in users:
        presence = fetch_presence(client, u["user_id"])
        if presence is None:
            continue

        row = {
            "user_id": u["user_id"],
            "user_email": u["email"] or None,
            "user_name": u["real_name"] or None,
            "presence": presence["presence"],
            "online": presence["online"],
            "polled_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            supabase.table("presence_snapshots").insert(row).execute()
        except Exception as ex:
            logger.error("DB insert failed: %s", ex)

        time.sleep(RATE_LIMIT_DELAY)

    logger.info("Poll cycle done at %s", datetime.now(timezone.utc).isoformat())


def main():
    if not SLACK_BOT_TOKEN:
        logger.error("SLACK_BOT_TOKEN is required. Set it in .env")
        return 1
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        logger.error("SUPABASE_URL and SUPABASE_SERVICE_KEY are required. Set them in .env")
        return 1

    client = WebClient(token=SLACK_BOT_TOKEN)
    supabase = get_supabase_client()
    logger.info("Starting presence poller (target interval=%ds) - runs 24/7", POLL_SECONDS)

    logger.info("Starting presence poller (target interval=%ds) - runs 24/7", POLL_SECONDS)

    cached_users: list[dict] = []
    users_last_fetched = 0.0

    while True:
        cycle_start = time.time()
        try:
            if not cached_users or (cycle_start - users_last_fetched) >= USER_CACHE_TTL_SECONDS:
                cached_users = fetch_slack_users(client)
                users_last_fetched = cycle_start
                logger.info("Refreshed Slack user list: %d users", len(cached_users))

            run_poll_cycle(client, supabase, cached_users)
        except SlackApiError as e:
            logger.error("Slack API error: %s", e)
        except Exception as e:
            logger.exception("Unexpected error: %s", e)

        elapsed = time.time() - cycle_start
        sleep_for = max(0, POLL_SECONDS - elapsed)
        if sleep_for > 0:
            time.sleep(sleep_for)


if __name__ == "__main__":
    exit(main() or 0)
