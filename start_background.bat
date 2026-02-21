@echo off
cd /d "%~dp0"
start "Slack Uptime" cmd /c "python run.py & pause"
