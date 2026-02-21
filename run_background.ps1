# Run Slack Uptime in background (Windows)
# Keeps polling and dashboard running 24/7. Close this window to stop.
$env:PYTHONUNBUFFERED = "1"
Set-Location $PSScriptRoot
python run.py
