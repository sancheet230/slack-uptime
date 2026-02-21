def format_duration_hours_minutes(seconds: int) -> str:
    if seconds < 0:
        return "0h 0m"
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    return f"{hours}h {minutes}m"

# Assume the rest of dashboard.py content exists here, with all calls to format_duration_hours updated to format_duration_hours_minutes
