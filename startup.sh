#!/bin/bash

"""
Startup Script for US Number Order System
Orchestrates webhook server and backorder tracker with health monitoring.

ADDITIVE FEATURE:
- Multi-process orchestration with health monitoring
- Auto-restart on process failure
- Redis server management
- Resource monitoring and logging
- Optimized health check intervals (5 minutes)
"""

set -e

echo "🚀 Starting US Number Order Services with Redis and Health Monitoring..."

# Create data directory if it doesn't exist
mkdir -p /data


# Check if we should use external Redis or start our own
if [ -n "$REDIS_HOST" ] && [ "$REDIS_HOST" != "localhost" ]; then
    echo "🔗 Connecting to external Redis at $REDIS_HOST:$REDIS_PORT"
    # Don't start local Redis, just test connection
    if redis-cli -h $REDIS_HOST -p $REDIS_PORT ping > /dev/null 2>&1; then
        echo "✅ External Redis connection successful"
    else
        echo "❌ External Redis connection failed"
        exit 1
    fi
else
    echo "🔴 Starting local Redis server..."
    REDIS_PORT=${REDIS_PORT:-6379}
    redis-server --daemonize yes --port $REDIS_PORT --bind 0.0.0.0
    echo "✅ Redis server started on port $REDIS_PORT"

    # Wait for Redis to be ready
    echo "🔍 Waiting for Redis to be ready..."
    sleep 3

    # Test Redis connection
    if redis-cli -p $REDIS_PORT ping > /dev/null 2>&1; then
        echo "✅ Redis connection successful on port $REDIS_PORT"
    else
        echo "❌ Redis connection failed on port $REDIS_PORT"
        exit 1
    fi

fi

# Function to check if a process is running
check_process() {
    local pid=$1
    local name=$2
    if ! kill -0 $pid 2>/dev/null; then
        echo "❌ $name process (PID $pid) is not running"
        return 1
    fi
    return 0
}

# Function to restart a failed service
restart_service() {
    local service_name=$1
    local command=$2
    echo "🔄 Restarting $service_name..."
    eval "$command" &
    local pid=$!
    echo "✅ $service_name restarted with PID $pid"
    return $pid
}

# Function to check service health via HTTP
check_service_health() {
    local service_name=$1
    local health_url=$2
    local max_retries=3
    local retry_count=0
    
    while [ $retry_count -lt $max_retries ]; do
        if curl -f -s "$health_url" > /dev/null 2>&1; then
            echo "✅ $service_name health check passed"
            return 0
        else
            echo "⚠️ $service_name health check failed (attempt $((retry_count + 1))/$max_retries)"
            retry_count=$((retry_count + 1))
            sleep 2
        fi
    done
    echo "❌ $service_name health check failed after $max_retries attempts"
    return 1
}

# Function to monitor memory and disk usage
monitor_resources() {
    echo "📊 Resource Usage:"
    echo "Memory:"

    if command -v free >/dev/null 2>&1; then
        free -h | grep -E "Mem|Swap" || echo "Memory info unavailable"
    else
        echo "Memory info unavailable (free command not found)"
    fi

    echo "Disk:"
    df -h /data | tail -1 || echo "Disk info unavailable"
    echo "---"
}

# Start webhook server
echo "🌐 Starting webhook server..."
python zendesk_webhook.py &
WEBHOOK_PID=$!
echo "✅ Webhook server started with PID $WEBHOOK_PID"

# Wait for webhook server to be ready
echo "🔍 Waiting for webhook server to be ready..."
sleep 10

# Check webhook server health endpoint
if ! check_service_health "Webhook Server" "http://localhost:5000/health"; then
    echo "⚠️ Webhook server health check failed, but process is running"
fi

# Start backorder tracker
echo "🔄 Starting backorder tracker..."
python startup.py &
TRACKER_PID=$!
echo "✅ Backorder tracker started with PID $TRACKER_PID"

# Monitor processes
echo "👀 Monitoring services..."
monitor_resources

while true; do
    # Check Redis

    if [ -n "$REDIS_HOST" ] && [ "$REDIS_HOST" != "localhost" ]; then
        # Check external Redis
        if ! redis-cli -h $REDIS_HOST -p $REDIS_PORT ping > /dev/null 2>&1; then
            echo "❌ External Redis connection lost! Exiting..."
            exit 1
        fi
    else
        # Check local Redis
        if ! redis-cli -p $REDIS_PORT ping > /dev/null 2>&1; then
            echo "❌ Redis server died! Restarting..."
            redis-server --daemonize yes --port $REDIS_PORT --bind 0.0.0.0
            sleep 3
        fi

    fi
    
    # Check webhook server
    if ! check_process $WEBHOOK_PID "Webhook Server"; then
        echo "💀 Webhook server died! This is critical - exiting..."
        exit 1
    fi
    
    # Check backorder tracker
    if ! check_process $TRACKER_PID "Backorder Tracker"; then
        echo "⚠️ Backorder tracker died, restarting..."
        python startup.py &
        TRACKER_PID=$!
        echo "✅ Backorder tracker restarted with PID $TRACKER_PID"
    fi
    
    # Health check every 8 hours (silent logging - 3 times per day)
    if ! check_service_health "Webhook Server" "http://localhost:5000/health"; then
        echo "⚠️ Webhook server health check failed"
    fi
    
    # Monitor resources every 8 hours (silent logging)
    if [ $((SECONDS % 28800)) -eq 0 ]; then
        monitor_resources
    fi
    
    # Sleep for 8 hours (silent logging - 3 times per day)
    sleep 28800
done 