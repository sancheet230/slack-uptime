-- Run this in Supabase SQL Editor to set up tables for Slack presence tracking

-- Presence snapshots: each poll records user presence
CREATE TABLE IF NOT EXISTS presence_snapshots (
    id BIGSERIAL PRIMARY KEY,
    user_id TEXT NOT NULL,
    user_email TEXT,
    user_name TEXT,
    presence TEXT NOT NULL,  -- 'active' or 'away'
    online BOOLEAN NOT NULL,
    polled_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index for querying by date and user
CREATE INDEX IF NOT EXISTS idx_presence_user_date 
    ON presence_snapshots(user_id, DATE(polled_at AT TIME ZONE 'UTC'));
CREATE INDEX IF NOT EXISTS idx_presence_polled_at 
    ON presence_snapshots(polled_at);

-- User cache: store user info to avoid repeated lookups
CREATE TABLE IF NOT EXISTS user_cache (
    user_id TEXT PRIMARY KEY,
    email TEXT,
    real_name TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Optional: Daily aggregates for faster dashboard queries (can be computed from snapshots)
CREATE TABLE IF NOT EXISTS daily_uptime (
    id BIGSERIAL PRIMARY KEY,
    user_id TEXT NOT NULL,
    user_email TEXT,
    user_name TEXT,
    date DATE NOT NULL,
    total_seconds_online INTEGER NOT NULL DEFAULT 0,
    UNIQUE(user_id, date)
);

CREATE INDEX IF NOT EXISTS idx_daily_uptime_date ON daily_uptime(date);
CREATE INDEX IF NOT EXISTS idx_daily_uptime_user ON daily_uptime(user_id);
