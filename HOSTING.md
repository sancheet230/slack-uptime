# Free Hosting Guide – Slack Uptime Tracker

Quick reference for hosting this app for free.

## Prerequisites

- [ ] Supabase project created, tables set up (`supabase_schema.sql`)
- [ ] Slack app with `users:read`, `users:read.email`, `presence:read`
- [ ] Code pushed to GitHub (for Render/Railway)

## Env vars you need

| Variable | Example |
|----------|---------|
| `SLACK_BOT_TOKEN` | `xoxp-xxx...` or `xoxb-xxx...` |
| `SUPABASE_URL` | `https://xxxx.supabase.co` (not `postgresql://`) |
| `SUPABASE_SERVICE_KEY` | `eyJhbGc...` (service_role key) |
| `POLL_SECONDS` | `60` (optional) |

---

## Render (recommended)

1. [render.com](https://render.com) → Sign up → New → Blueprint
2. Connect GitHub repo → Render reads `render.yaml` and creates 2 services
3. Add env vars to **both** services (Dashboard → Environment)
4. Deploy → Dashboard URL like `https://slack-uptime-dashboard.onrender.com`

**Tip:** Free web services sleep after inactivity. Use [cron-job.org](https://cron-job.org) to ping your URL every 10 min to keep it awake.

---

## Fly.io

```bash
fly launch
fly secrets set SLACK_BOT_TOKEN="xxx" SUPABASE_URL="xxx" SUPABASE_SERVICE_KEY="xxx" POLL_SECONDS="60"
fly deploy
```

Dashboard + poller run on one VM. URL: `https://YOUR_APP.fly.dev`

---

## Railway

1. [railway.app](https://railway.app) → New Project → Deploy from GitHub
2. Add **Web** service: Start = `uvicorn dashboard:app --host 0.0.0.0 --port $PORT`
3. Add **Worker** service: Start = `python poller.py`
4. Add env vars to both
5. Deploy

---

## Docker (VPS)

```bash
docker build -t slack-uptime .
docker run -d --env-file .env -p 8000:8000 --restart unless-stopped slack-uptime
```

Good with Oracle Cloud Free Tier, AWS/GCP free tier, or any VPS.
