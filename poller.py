"""
Slack presence poller: fetches user presence periodically and stores in Supabase.
Slack API rate limit: 20 users.getPresence calls per minute (Tier 2).
"""
import time
import logging
from datetime import datetime, timezone
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from config import SLACK_BOT_TOKEN, POLL_SECONDS, SUPABASE_URL, SUPABASE_SERVICE_KEY

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# Rate limit: 20 requests/minute for users.getPresence
RATE_LIMIT_DELAY = 3.5  # seconds between presence calls


def get_supabase_client():
    from db import create_client
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


def fetch_slack_users(client: WebClient) -> list[dict]:
    """Fetch all non-deleted, non-bot users from Slack."""
    users = []
    cursor = None
    while True:
        resp = client.users_list(
            limit=200,
            cursor=cursor,
            include_locale=False,
        )
        for u in resp.get("members", []):
            if u.get("is_bot") or u.get("deleted"):
                continue
            users.append({
                "user_id": u["id"],
                "email": u.get("profile", {}).get("email") or "",
                "real_name": u.get("profile", {}).get("real_name") or u.get("name", ""),
            })
        cursor = resp.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break
    return users


def fetch_presence(client: WebClient, user_id: str) -> dict | None:
    """Get presence for one user."""
    try:
        resp = client.users_getPresence(user=user_id)
        return {
            "presence": resp.get("presence", "away"),
            "online": resp.get("online", False),
        }
    except SlackApiError as e:
        if e.response["error"] == "missing_scope":
            logger.warning("Need presence:read scope for users.getPresence")
        else:
            logger.debug("Presence error for %s: %s", user_id, e.response.get("error"))
        return None


def run_poll_cycle(client: WebClient, supabase):
    """One poll cycle: get all users, fetch presence with rate limiting, store in DB."""
    users = fetch_slack_users(client)
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

        # Respect rate limit (20 calls/min)
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

    logger.info("Starting presence poller (interval=%ds) - runs 24/7", POLL_SECONDS)

    while True:
        try:
            run_poll_cycle(client, supabase)
        except SlackApiError as e:
            logger.error("Slack API error: %s", e)
        except Exception as e:
            logger.exception("Unexpected error: %s", e)

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    exit(main() or 0)
