"""Configuration loaded from environment variables."""
import os
import sys
from dotenv import load_dotenv

load_dotenv()

SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
POLL_SECONDS = int(os.getenv("POLL_SECONDS", "60"))

# Supabase - use the REST API URL (https://xxx.supabase.co), NOT the postgresql:// connection string
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

if SUPABASE_URL and SUPABASE_URL.strip().lower().startswith("postgresql://"):
    print(
        "ERROR: SUPABASE_URL must be the REST API URL (https://xxx.supabase.co), not the Database connection string.\n"
        "In Supabase: Settings → API → Project URL",
        file=sys.stderr,
    )
    sys.exit(1)
