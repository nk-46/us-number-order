#!/bin/bash

set -e

echo "🚀 Starting US Number Order Services with External Redis..."

# Create data directory if it doesn't exist
mkdir -p /data

# Use external Redis (configured via Fly.io secrets)
echo "🔗 Connecting to external Redis..."
REDIS_HOST=${REDIS_HOST:-"us-num-order-redis.internal"}
REDIS_PORT=${REDIS_PORT:-6379}

# Wait for external Redis to be ready
echo "🔍 Waiting for external Redis to be ready..."
for i in {1..30}; do
    if redis-cli -h $REDIS_HOST -p $REDIS_PORT ping > /dev/null 2>&1; then
        echo "✅ External Redis connection successful"
        break
    fi
    echo "⏳ Waiting for Redis... (attempt $i/30)"
    sleep 2
done

# Test Redis connection
if ! redis-cli -h $REDIS_HOST -p $REDIS_PORT ping > /dev/null 2>&1; then
    echo "❌ External Redis connection failed"
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

# Wait for webhook server to be ready
echo "🔍 Waiting for webhook server to be ready..."
sleep 5

# Start the main processing service (REMOVED - should only be called by webhook)
# echo "⚙️ Starting main processing service..."
# python3 main.py &
# MAIN_PID=$!
# echo "✅ Main processing service started with PID $MAIN_PID"
echo "⚠️ Main processing service removed - should only be called by webhook"
MAIN_PID=0

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
    
    # Check external Redis
    if ! redis-cli -h $REDIS_HOST -p $REDIS_PORT ping > /dev/null 2>&1; then
        echo "❌ External Redis connection lost! Attempting to reconnect..."
        sleep 5
        if ! redis-cli -h $REDIS_HOST -p $REDIS_PORT ping > /dev/null 2>&1; then
            echo "❌ External Redis connection failed permanently"
            exit 1
        fi
    fi
    
    # Check webhook server
    if ! check_process $WEBHOOK_PID "Webhook Server"; then
        echo "💀 Webhook server died! This is critical - exiting..."
        exit 1
    fi
    
    # Check main processing service (REMOVED - should only be called by webhook)
    # if ! check_process $MAIN_PID "Main Processing Service"; then
    #     echo "💀 Main processing service died! This is critical - exiting..."
    #     exit 1
    # fi
    
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
    
    echo "📊 All services healthy - continuing monitoring..."
done 