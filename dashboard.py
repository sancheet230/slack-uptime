def format_duration_hours_minutes(duration):
    hours = duration // 3600
    minutes = (duration % 3600) // 60
    return f'{hours}h {minutes}m'  

# Existing logic and imports here  

# Example of existing code that calls format_duration_hours function


def some_other_function():
    duration = 9000  # Example duration in seconds
    formatted_duration = format_duration_hours_minutes(duration)
    print(formatted_duration)  # This should now print '2h 30m' for 9000 seconds

# The rest of the existing logic remains unchanged
