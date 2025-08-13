#!/usr/bin/env python3
"""
Startup Script for Background Services
Initializes and starts the backorder tracking service.

ADDITIVE FEATURE:
- Background service orchestration
- Backorder tracking initialization
- Process management and monitoring
"""

import os
import sys
import logging
import signal
import time
from dotenv import load_dotenv

# Load environment variables
load_dotenv(override=True)

# Configure logging

try:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler("/data/startup.log"),
            logging.StreamHandler()
        ]
    )
except FileNotFoundError:
    # Fallback for local development
    os.makedirs("data", exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler("data/startup.log"),
            logging.StreamHandler()
        ]
    )

logger = logging.getLogger(__name__)

def signal_handler(signum, frame):
    """Handle shutdown signals gracefully"""
    logger.info("🛑 Received shutdown signal, stopping services...")
    from backorder_tracker import stop_backorder_tracking
    stop_backorder_tracking()
    sys.exit(0)

def main():
    """Main startup function"""
    logger.info("🚀 Starting US Number Order Automation System")
    
    # Set up signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        # Import and start backorder tracking
        from backorder_tracker import start_backorder_tracking
        
        logger.info("📊 Initializing backorder tracking service...")
        start_backorder_tracking()
        
        logger.info("✅ All services started successfully")
        logger.info("🔄 System is running. Press Ctrl+C to stop.")
        
        # Keep the main thread alive
        while True:
            time.sleep(60)  # Check every minute
            
    except KeyboardInterrupt:
        logger.info("🛑 Received keyboard interrupt")
    except Exception as e:
        logger.error(f"❌ Startup error: {e}")
        sys.exit(1)
    finally:
        logger.info("🛑 Shutting down...")

if __name__ == "__main__":
    main() 