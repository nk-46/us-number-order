#!/bin/bash

set -e

echo "🚀 Starting US Number Order Services with Redis and Health Monitoring..."

# Create data directory if it doesn't exist
mkdir -p /data

# Start Redis server
echo "🔴 Starting Redis server..."
redis-server --daemonize yes --port 6379 --bind 0.0.0.0
echo "✅ Redis server started"

# Wait for Redis to be ready
echo "🔍 Waiting for Redis to be ready..."
sleep 3

# Test Redis connection
if redis-cli ping > /dev/null 2>&1; then
    echo "✅ Redis connection successful"
else
    echo "❌ Redis connection failed"
    exit 1
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
    echo "✅ $service_name restarted"
}

# Start the webhook server
echo "🌐 Starting webhook server..."
python3 zendesk_webhook.py &
WEBHOOK_PID=$!
echo "✅ Webhook server started with PID $WEBHOOK_PID"

# Start the main processing service
echo "⚙️ Starting main processing service..."
python3 main.py &
MAIN_PID=$!
echo "✅ Main processing service started with PID $MAIN_PID"

# Start the backorder tracker
echo "📦 Starting backorder tracker..."
python3 backorder_tracker.py &
BACKORDER_PID=$!
echo "✅ Backorder tracker started with PID $BACKORDER_PID"

# Start the startup monitoring service
echo "🔍 Starting startup monitoring service..."
python3 startup.py &
STARTUP_PID=$!
echo "✅ Startup monitoring service started with PID $STARTUP_PID"

# Monitor services in a loop
echo "🔄 Starting service monitoring loop..."
while true; do
    sleep 30
    
    # Check Redis
    if ! redis-cli ping > /dev/null 2>&1; then
        echo "❌ Redis server died! Restarting..."
        redis-server --daemonize yes --port 6379 --bind 0.0.0.0
        sleep 3
    fi
    
    # Check webhook server
    if ! check_process $WEBHOOK_PID "Webhook Server"; then
        echo "💀 Webhook server died! This is critical - exiting..."
        exit 1
    fi
    
    # Check main processing service
    if ! check_process $MAIN_PID "Main Processing Service"; then
        echo "💀 Main processing service died! This is critical - exiting..."
        exit 1
    fi
    
    # Check backorder tracker
    if ! check_process $BACKORDER_PID "Backorder Tracker"; then
        echo "⚠️ Backorder tracker died! Restarting..."
        restart_service "Backorder Tracker" "python3 backorder_tracker.py"
        BACKORDER_PID=$!
    fi
    
    # Check startup monitoring service
    if ! check_process $STARTUP_PID "Startup Monitoring Service"; then
        echo "⚠️ Startup monitoring service died! Restarting..."
        restart_service "Startup Monitoring Service" "python3 startup.py"
        STARTUP_PID=$!
    fi
    
    echo "✅ All services running normally"
done 