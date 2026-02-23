"""Slack presence poller.

Design goals:
- Refresh workspace membership every cycle so newly joined org members are
  tracked immediately.
- Prefer embedded presence from users.list when available (faster + fewer API
  calls).
- Fallback to users.getPresence per user when users.list does not include
  reliable presence.
- Keep retry and rate-limit handling for Slack and Supabase operations.
"""
from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from config import POLL_SECONDS, SLACK_BOT_TOKEN, SUPABASE_SERVICE_KEY, SUPABASE_URL

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("presence_poller")

REQUESTS_PER_MINUTE = 20
MIN_DELAY_SECONDS = 60.0 / REQUESTS_PER_MINUTE
MAX_JITTER_SECONDS = 0.35
MAX_RETRIES = 4


@dataclass
class SlackUser:
    user_id: str
    email: str
    real_name: str
    embedded_presence: str | None = None
    embedded_online: bool | None = None


class RetryablePollerError(RuntimeError):
    """Raised when a temporary failure should be retried by main loop."""


def get_supabase_client():
    from db import create_client

    return create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


def _sleep_rate_limit_window() -> None:
    time.sleep(max(0.0, MIN_DELAY_SECONDS + random.uniform(0, MAX_JITTER_SECONDS)))


def _safe_retry_after(error: SlackApiError, default: int = 10) -> int:
    try:
        if error.response is not None and error.response.headers is not None:
            raw = error.response.headers.get("Retry-After")
            if raw:
                return max(1, int(raw))
    except Exception:
        pass
    return default


def _slack_error_code(exc: SlackApiError) -> str:
    response = exc.response
    if response is None:
        return "unknown_error"
    try:
        return str(response.get("error", "unknown_error"))
    except Exception:
        return "unknown_error"


def _presence_from_member(member: dict) -> tuple[str | None, bool | None]:
    """Best-effort extraction of presence from users.list payload."""
    raw_presence = str(member.get("presence") or "").strip().lower()
    if raw_presence in {"active", "away"}:
        return raw_presence, raw_presence == "active"

    if "is_active" in member:
        is_active = bool(member.get("is_active"))
        return ("active" if is_active else "away"), is_active

    profile = member.get("profile") or {}
    if "is_online" in profile:
        is_online = bool(profile.get("is_online"))
        return ("active" if is_online else "away"), is_online

    return None, None


def fetch_workspace_users(client: WebClient) -> tuple[list[SlackUser], bool]:
    """Fetch active human users from Slack.

    Returns tuple(users, has_any_embedded_presence).
    """
    users: list[SlackUser] = []
    cursor: str | None = None
    has_any_embedded_presence = False

    while True:
        response = None
        last_exc: Exception | None = None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = client.users_list(limit=200, cursor=cursor, include_locale=False, presence=True)
                break
            except SlackApiError as exc:
                last_exc = exc
                code = _slack_error_code(exc)
                if code == "ratelimited":
                    wait_for = _safe_retry_after(exc)
                    logger.warning("users.list rate-limited, sleeping %ss", wait_for)
                    time.sleep(wait_for)
                    continue
                if code in {"internal_error", "fatal_error", "request_timeout"} and attempt < MAX_RETRIES:
                    backoff = min(20, 2**attempt)
                    logger.warning("users.list temporary failure (%s), retry in %ss", code, backoff)
                    time.sleep(backoff)
                    continue
                raise
            except Exception as exc:
                last_exc = exc
                if attempt < MAX_RETRIES:
                    backoff = min(20, 2**attempt)
                    logger.warning("users.list request failed (%s), retry in %ss", exc, backoff)
                    time.sleep(backoff)
                    continue

        if response is None:
            raise RetryablePollerError(f"Could not fetch users after retries: {last_exc}")

        for member in response.get("members", []):
            if member.get("deleted") or member.get("is_bot"):
                continue
            profile = member.get("profile") or {}
            embedded_presence, embedded_online = _presence_from_member(member)
            if embedded_presence is not None:
                has_any_embedded_presence = True
            users.append(
                SlackUser(
                    user_id=member["id"],
                    email=str(profile.get("email") or ""),
                    real_name=str(profile.get("real_name") or member.get("real_name") or member.get("name") or ""),
                    embedded_presence=embedded_presence,
                    embedded_online=embedded_online,
                )
            )

        cursor = (response.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            break

    return users, has_any_embedded_presence


def fetch_presence(client: WebClient, user_id: str) -> dict | None:
    """Return normalized presence dict, or None when this user should be skipped."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = client.users_getPresence(user=user_id)
            raw_presence = str(resp.get("presence") or "away").strip().lower()
            raw_online = resp.get("online", False)
            online = (
                raw_online.strip().lower() in {"true", "1", "yes", "on", "y", "t"}
                if isinstance(raw_online, str)
                else bool(raw_online)
            )

            manual_away = bool(resp.get("manual_away", False))
            connection_count = int(resp.get("connection_count") or 0)
            inferred_online = online or raw_presence == "active" or (connection_count > 0 and not manual_away)
            return {"presence": "active" if inferred_online else "away", "online": inferred_online}

        except SlackApiError as exc:
            code = _slack_error_code(exc)
            if code == "missing_scope":
                logger.error("Missing presence:read scope for users.getPresence")
                return None
            if code == "user_not_found":
                logger.debug("Skipping missing user %s", user_id)
                return None
            if code == "ratelimited":
                wait_for = _safe_retry_after(exc)
                logger.warning("users.getPresence rate-limited, sleeping %ss", wait_for)
                time.sleep(wait_for)
                continue
            if code in {"internal_error", "fatal_error", "request_timeout"} and attempt < MAX_RETRIES:
                backoff = min(20, 2**attempt)
                logger.warning("presence temporary failure for %s (%s), retry in %ss", user_id, code, backoff)
                time.sleep(backoff)
                continue

            logger.warning("Presence fetch failed for %s: %s", user_id, code)
            return None
        except Exception as exc:
            if attempt < MAX_RETRIES:
                backoff = min(20, 2**attempt)
                logger.warning("Presence transport failure for %s (%s), retry in %ss", user_id, exc, backoff)
                time.sleep(backoff)
                continue
            logger.warning("Presence fetch failed after retries for %s: %s", user_id, exc)
            return None

    return None


def _insert_snapshot(supabase, row: dict) -> None:
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            supabase.table("presence_snapshots").insert(row).execute()
            return
        except Exception as exc:
            if attempt < MAX_RETRIES:
                backoff = min(20, 2**attempt)
                logger.warning("DB insert failed (%s), retry in %ss", exc, backoff)
                time.sleep(backoff)
                continue
            raise RetryablePollerError(f"DB insert failed after retries: {exc}") from exc


def _upsert_user_cache(supabase, user: SlackUser) -> None:
    row = {
        "user_id": user.user_id,
        "email": user.email or None,
        "real_name": user.real_name or None,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            supabase.table("user_cache").upsert(row, on_conflict="user_id").execute()
            return
        except Exception as exc:
            if attempt < MAX_RETRIES:
                backoff = min(20, 2**attempt)
                logger.warning("user_cache upsert failed (%s), retry in %ss", exc, backoff)
                time.sleep(backoff)
                continue
            raise RetryablePollerError(f"user_cache upsert failed after retries: {exc}") from exc


def run_poll_cycle(client: WebClient, supabase, users: list[SlackUser], has_embedded_presence: bool) -> tuple[int, int]:
    logger.info("Starting poll cycle for %d users", len(users))
    stored = 0

    for user in users:
        if has_embedded_presence and user.embedded_presence is not None:
            presence = {
                "presence": user.embedded_presence,
                "online": bool(user.embedded_online),
            }
        else:
            presence = fetch_presence(client, user.user_id)
            _sleep_rate_limit_window()

        if presence is None:
            continue

        snapshot = {
            "user_id": user.user_id,
            "user_email": user.email or None,
            "user_name": user.real_name or None,
            "presence": presence["presence"],
            "online": bool(presence["online"]),
            "polled_at": datetime.now(timezone.utc).isoformat(),
        }

        _insert_snapshot(supabase, snapshot)
        _upsert_user_cache(supabase, user)
        stored += 1

    logger.info("Poll cycle complete: stored=%d", stored)
    return len(users), stored


def main() -> int:
    if not SLACK_BOT_TOKEN:
        logger.error("SLACK_BOT_TOKEN is required")
        return 1
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        logger.error("SUPABASE_URL and SUPABASE_SERVICE_KEY are required")
        return 1

    client = WebClient(token=SLACK_BOT_TOKEN)
    supabase = get_supabase_client()
    known_user_ids: set[str] = set()

    logger.info("Poller started (POLL_SECONDS=%s)", POLL_SECONDS)

    while True:
        cycle_start = time.time()
        try:
            users, has_embedded_presence = fetch_workspace_users(client)
            current_user_ids = {user.user_id for user in users}
            new_ids = current_user_ids - known_user_ids
            if new_ids:
                logger.info("Detected %d newly joined/newly visible members", len(new_ids))
            known_user_ids = current_user_ids

            if not users:
                logger.warning("No eligible users found in workspace; sleeping")
            else:
                run_poll_cycle(client, supabase, users, has_embedded_presence)

        except RetryablePollerError as exc:
            logger.warning("Transient poller error: %s", exc)
        except SlackApiError as exc:
            code = _slack_error_code(exc)
            logger.error("Slack API error in main loop: %s", code)
            if code == "ratelimited":
                wait_for = _safe_retry_after(exc)
                time.sleep(wait_for)
        except Exception as exc:
            logger.exception("Unexpected main-loop error: %s", exc)

        elapsed = time.time() - cycle_start
        sleep_for = max(1.0, float(POLL_SECONDS) - elapsed)
        time.sleep(sleep_for)


if __name__ == "__main__":
    raise SystemExit(main())
