# Use official Python base image
FROM python:3.9-slim

# Install redis-tools for Redis connectivity
RUN apt-get update && apt-get install -y redis-tools && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first for better layer caching
COPY requirements.txt .

# Install dependencies with optimizations
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy only necessary files (exclude test files and backups)
COPY main.py .
COPY mcp_integration.py .
COPY backorder_tracker.py .
COPY zendesk_webhook.py .
COPY startup.py .
COPY startup.sh .
COPY fly.toml .
COPY CHANGELOG.md .
COPY README.md .

# Make startup script executable
RUN chmod +x startup.sh

# Create data directory
RUN mkdir -p /data

# Expose port
EXPOSE 5000

# Run the multi-service orchestration
CMD ["./startup.sh"]
