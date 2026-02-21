# Slack Uptime Tracker

Tracks user presence (online time) in Slack and displays it in a simple dashboard with search.
Designed to run **24/7** – the poller keeps checking presence every minute, data is stored in Supabase, and the dashboard shows uptime for any day/week you choose.

## Setup

### 1. Slack App

1. Create an app at [api.slack.com/apps](https://api.slack.com/apps)
2. Add OAuth scopes: `users:read`, `users:read.email`, `presence:read`
3. Install the app to your workspace and copy the **Bot User OAuth Token** (starts with `xoxb-` or `xoxp-`)

> **Note:** `users.getPresence` may require a User token (`xoxp-`) depending on your setup. Bot tokens work for most cases with the right scopes.

### 2. Supabase

1. Create a project at [supabase.com](https://supabase.com)
2. In **SQL Editor**, run the contents of `supabase_schema.sql` to create tables
3. Go to **Settings → API** and copy:
   - Project URL (`SUPABASE_URL`)
   - `service_role` key (`SUPABASE_SERVICE_KEY`)

### 3. Environment

Create `.env` in the project root:

```env
SLACK_BOT_TOKEN=xoxp-your-token-here
POLL_SECONDS=60
SUPABASE_URL=https://xxxx.supabase.co
SUPABASE_SERVICE_KEY=eyJhbGciOiJIUzI1NiIs...
```

### 4. Install & Run Locally

```bash
pip install -r requirements.txt
python run.py
```

Then open http://localhost:8000

**Run in background (keeps running after closing terminal):**
- Windows: Double-click `start_background.bat` or run `python run.py` in a separate window
- Or: `Start-Process python -ArgumentList "run.py" -NoNewWindow` in PowerShell

**Or run separately:**
- Dashboard only: `uvicorn dashboard:app --host 0.0.0.0 --port 8000`
- Poller only: `python poller.py`
- Aggregator (optional, for faster dashboard): `python aggregate.py` (run daily via cron)

---

## Running 24/7 (Days & Weeks)

The poller runs continuously – every `POLL_SECONDS` it checks all users and stores presence in Supabase. The dashboard reads from Supabase and shows uptime for any date. To keep it running whole days and weeks:

1. **Local PC** – Leave the terminal/command prompt open. Use `start_background.bat` (Windows) to run in a separate window.
2. **Deploy to cloud** – Use Railway, Render, or a VPS (see Deployment below) so it runs even when your PC is off.
3. **Data persists** – All presence data is stored in Supabase. Historical days and weeks stay available in the dashboard.

---

## Free Hosting (How to Host for Free)

### Option 1: Render (Easiest – auto-deploy from GitHub)

1. **Push your code to GitHub** (if not already):
   ```bash
   git init
   git add .
   git commit -m "Slack uptime tracker"
   git remote add origin https://github.com/YOUR_USERNAME/slack-uptime.git
   git push -u origin main
   ```

2. Go to [render.com](https://render.com) and sign up (free).

3. **New → Blueprint** – connect your GitHub repo, select the repo. Render will detect `render.yaml` and create both services automatically.
   - *If Blueprint doesn’t appear:* Create a **Web Service** and a **Background Worker** manually. Use the same build/start commands as in `render.yaml`.

4. **Add environment variables** in Render Dashboard → each service → Environment:
   - `SLACK_BOT_TOKEN` = your Slack token
   - `SUPABASE_URL` = `https://xxxx.supabase.co`
   - `SUPABASE_SERVICE_KEY` = your Supabase service_role key
   - `POLL_SECONDS` = `60` (optional, has default)

5. Deploy. You’ll get:
   - Dashboard URL: `https://slack-uptime-dashboard.onrender.com` (or similar)
   - Poller runs 24/7 as a background worker

**Free tier notes:** Web service may sleep after ~15 min of no traffic (first load can be slow). The poller keeps running. To avoid sleep, use a cron job (e.g. [cron-job.org](https://cron-job.org)) to hit your dashboard URL every 10 min.

---

### Option 2: Fly.io (Single VM – always on)

1. Install [Fly CLI](https://fly.io/docs/hands-on/install-flyctl/).

2. Log in and launch:
   ```bash
   cd slack-uptime
   fly launch
   ```
   When prompted: choose a region, don’t add PostgreSQL (you use Supabase).

3. Set secrets:
   ```bash
   fly secrets set SLACK_BOT_TOKEN="xoxp-your-token"
   fly secrets set SUPABASE_URL="https://xxxx.supabase.co"
   fly secrets set SUPABASE_SERVICE_KEY="your-service-role-key"
   fly secrets set POLL_SECONDS="60"
   ```

4. Deploy:
   ```bash
   fly deploy
   ```

5. Your app will be at `https://YOUR_APP_NAME.fly.dev`. The poller and dashboard run together on one VM.

**Free tier:** Includes a small free allowance. Stays on 24/7 within limits.

---

### Option 3: Railway (if free tier available)

1. Connect repo at [railway.app](https://railway.app).
2. Create **two services**: Web (dashboard) + Worker (poller).
3. For Web: Start command = `uvicorn dashboard:app --host 0.0.0.0 --port $PORT`
4. For Worker: Start command = `python poller.py`
5. Add env vars to both services.

---

### Option 4: Docker (VPS / any server)

```bash
docker build -t slack-uptime .
docker run -d --env-file .env -p 8000:8000 --restart unless-stopped slack-uptime
```

Runs poller + dashboard in one container. Use a free VPS (e.g. Oracle Cloud Free Tier, Google Cloud free tier) if you have one.

---

## Rate Limits

Slack limits `users.getPresence` to **20 requests/minute**. The poller spaces requests ~3.5s apart. For large workspaces (100+ users), a full poll cycle takes several minutes; the next cycle starts after `POLL_SECONDS` from the *beginning* of the previous cycle.

---

## Files

| File | Purpose |
|------|---------|
| `poller.py` | Polls Slack presence every `POLL_SECONDS`, stores in Supabase |
| `dashboard.py` | FastAPI app: HTML + JSON API for uptime by date with search |
| `aggregate.py` | Optional: pre-aggregates snapshots into `daily_uptime` for faster queries |
| `config.py` | Loads env vars |
| `supabase_schema.sql` | Run in Supabase SQL Editor to create tables |
