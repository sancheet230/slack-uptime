def format_duration_hours_minutes(duration):
    """Convert a duration in seconds to a string formatted as "HH:MM"."""
    hours, remainder = divmod(duration, 3600)
    minutes, _ = divmod(remainder, 60)
    return f"{int(hours):02}:{int(minutes):02}"

# Additional logic and functions in dashboard.py can go here.