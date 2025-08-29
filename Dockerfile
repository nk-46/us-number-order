# Use official Python base image
FROM python:3.9-slim

# Install redis-tools for Redis connectivity
RUN apt-get update && apt-get install -y redis-tools && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# Make startup script executable
RUN chmod +x startup.sh

# Expose port
EXPOSE 5000

# Run the multi-service orchestration
CMD ["./startup.sh"]
