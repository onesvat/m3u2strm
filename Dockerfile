FROM python:3.9-slim

WORKDIR /app

# Install required packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY task.py .
COPY web_ui.py .
COPY requirements.txt .
COPY templates templates

# Create directory for volume mount
RUN mkdir -p /app/vods
RUN mkdir -p /app/config

# Environment variables (can be overridden at runtime)
ENV TASK_INTERVAL=5 \
    DEBUG_LOGGING=false \
    WEB_UI_PORT=8475 

# Expose the web UI port
EXPOSE ${WEB_UI_PORT}

# Run the application
CMD ["python", "task.py"]
