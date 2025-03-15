FROM python:3.9-slim

# Set the working directory
WORKDIR /app

# Copy the task script into the container
COPY task.py .
COPY example.m3u .

# Install necessary dependencies
RUN pip install requests

# Document environment variables
# M3U_FILE: Path to the M3U file
# M3U_URL: URL to download the M3U file from
# TASK_INTERVAL: Interval in minutes between runs
# JELLYFIN_URL: URL of the Jellyfin server
# JELLYFIN_API_KEY: API key for Jellyfin
# TELEGRAM_BOT_TOKEN: Token for Telegram Bot API
# TELEGRAM_CHAT_ID: Telegram chat ID to send notifications to
# DEBUG_LOGGING: Set to "true" to enable debug logging

# Set the entrypoint to the task script
ENTRYPOINT ["python", "task.py"]
